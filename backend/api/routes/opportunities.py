"""EIP DDR Intelligence v4.4 — Opportunities Route"""
import uuid, datetime
from fastapi import APIRouter, Request, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional
from core.database import load_latest, load_actions, save_action, update_opp_status, get_settings, save_setting
from core.auth import get_current_user, require_permission
from core.audit import audit_from_request

router = APIRouter()

def _opps(request):
    s = getattr(request.app.state,"intelligence_store",{})
    if s and s.get("opportunities"): return s.get("opportunities",[])
    data = load_latest()
    if data:
        if not hasattr(request.app.state,"intelligence_store"): request.app.state.intelligence_store={}
        request.app.state.intelligence_store.update(data)
        return data.get("opportunities",[])
    return []

@router.get("/")
async def list_opportunities(request: Request,
    user: dict = Depends(get_current_user),
    product_line:Optional[str]=None, rig:Optional[str]=None, well:Optional[str]=None,
    min_confidence:Optional[int]=65, urgency:Optional[str]=None,
    competitor:Optional[str]=None, status:Optional[str]=None, sort:Optional[str]="confidence"):
    opps = _opps(request)
    if product_line: opps = [o for o in opps if product_line.lower() in o.get("product_line","").lower()]
    if rig:          opps = [o for o in opps if rig.lower() in o.get("rig","").lower()]
    if well:         opps = [o for o in opps if well.lower() in o.get("well","").lower()]
    if min_confidence is not None: opps = [o for o in opps if o.get("confidence",0) >= min_confidence]
    if urgency:      opps = [o for o in opps if o.get("urgency")==urgency]
    if competitor:   opps = [o for o in opps if competitor.lower() in o.get("competitor","").lower()]
    if status:       opps = [o for o in opps if o.get("status")==status]
    uo = {"immediate":0,"5_days":1,"7_days":2,"30_days":3,"future":4}
    if sort=="value":   opps=sorted(opps,key=lambda o:-o.get("estimated_value",0))
    elif sort=="urgency": opps=sorted(opps,key=lambda o:uo.get(o.get("urgency","future"),9))
    else:               opps=sorted(opps,key=lambda o:(-o.get("confidence",0),uo.get(o.get("urgency","future"),9)))
    for i,o in enumerate(opps,1): o["rank"]=i
    return opps

@router.get("/next-wells/list")
async def next_wells(request: Request, user: dict = Depends(get_current_user)):
    s = getattr(request.app.state,"intelligence_store",{})
    lifecycle = s.get("lifecycle",[])
    if not lifecycle:
        data = load_latest()
        if data: lifecycle = data.get("lifecycle",[])
    result=[]
    for lc in lifecycle:
        if lc.get("next_well"):
            rdp=lc.get("readiness_pct",0)
            result.append({"rig":lc.get("rig"),"current_well":lc.get("well"),
                "next_well":lc.get("next_well"),"readiness_pct":rdp,
                "action_level":"act_now" if rdp>=71 else "prepare" if rdp>=31 else "monitor",
                "commercial_rec":lc.get("commercial_rec"),
                "product_lines":lc.get("expected_product_lines",[])})
    return result

@router.get("/actions/list")
async def list_actions(user: dict = Depends(get_current_user)): return load_actions()

class ActionCreate(BaseModel):
    opportunity_id:str; title:str; owner:Optional[str]="Unassigned"
    due_date:Optional[str]=""; priority:Optional[str]="high"
    reason:Optional[str]=""; expected_outcome:Optional[str]=""; notes:Optional[str]=""

@router.post("/{opp_id}/actions")
async def create_action(opp_id:str, body:ActionCreate, request:Request, user: dict = Depends(get_current_user)):
    a={"id":str(uuid.uuid4()),"opportunity_id":opp_id,"title":body.title,
       "owner":body.owner,"due_date":body.due_date,"priority":body.priority,
       "reason":body.reason,"expected_outcome":body.expected_outcome,
       "notes":body.notes or "","status":"open",
       "created_at":datetime.datetime.utcnow().isoformat()}
    save_action(a); return a

class StatusUpdate(BaseModel):
    status:str

@router.patch("/{opp_id}/status")
async def update_status(opp_id:str, body:StatusUpdate, request:Request,
    user: dict = Depends(require_permission("validate"))):
    updated = update_opp_status(opp_id, body.status)
    if not updated: raise HTTPException(404,"Opportunity not found")
    s = getattr(request.app.state,"intelligence_store",{})
    for o in s.get("opportunities",[]):
        if o.get("id")==opp_id: o["status"]=body.status
    audit_from_request(request,"OPP_STATUS_CHANGE",user=user,
        detail=f"Status set to '{body.status}'",resource_id=opp_id)
    return updated

class ContactUpdate(BaseModel):
    contact_name: str

@router.patch("/{opp_id}/contact")
async def patch_contact(opp_id:str, body:ContactUpdate, request:Request, user: dict = Depends(get_current_user)):
    from core.database import update_contact_name
    updated = update_contact_name(opp_id, body.contact_name)
    if not updated: raise HTTPException(404,"Opportunity not found")
    s = getattr(request.app.state,"intelligence_store",{})
    for o in s.get("opportunities",[]):
        if o.get("id")==opp_id: o["contact_name"]=body.contact_name
    return updated

@router.get("/{opp_id}/why")
async def why_this(opp_id:str, request:Request, user: dict = Depends(get_current_user)):
    """Return full transparent confidence breakdown for an opportunity."""
    from core.database import get_db
    import json as _json
    conn = get_db()
    row = conn.execute("SELECT * FROM opportunities WHERE id=?", (opp_id,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, "Opportunity not found")
    opp = dict(row)
    try:
        opp["matched_keywords"] = _json.loads(opp.get("matched_keywords","[]") or "[]")
    except Exception:
        opp["matched_keywords"] = []

    from engines.ingestion_pipeline import compute_confidence_breakdown
    breakdown = compute_confidence_breakdown(opp)

    urg_labels = {"immediate":"Immediate — next 24h","5_days":"Within 5 days",
                  "7_days":"Within 7 days","30_days":"Within 30 days","future":"Future — monitor"}
    comp = opp.get("competitor","")

    # Structured scoring factors for the modal
    reasons = [
        {"factor": "Product Line Match",
         "score": f"{breakdown['pl_match']}/25",
         "weight": "25%",
         "detail": f"'{opp.get('product_line','')}' matched via keywords: "
                   f"{', '.join((opp.get('matched_keywords') or [])[:5]) or 'pattern match'}."},
        {"factor": "Activity / Lifecycle Signal",
         "score": f"{breakdown['activity']}/20",
         "weight": "20%",
         "detail": f"Urgency: {urg_labels.get(opp.get('urgency','future'), opp.get('urgency',''))}. "
                   f"Source section: {opp.get('evidence_section','unknown')}."},
        {"factor": "Rig / Well / Field Clarity",
         "score": f"{breakdown['rig_clarity']}/15",
         "weight": "15%",
         "detail": f"Rig: {opp.get('rig','—')} | Well: {opp.get('well','—')} | Field: {opp.get('field','—')}."},
        {"factor": "Competitor / Company Signal",
         "score": f"{breakdown['competitor']}/15",
         "weight": "15%",
         "detail": f"{'Competitor ' + comp + ' detected on location — displacement opportunity.' if comp else 'No competitor identified — primary vendor opportunity.'}"},
        {"factor": "Evidence Quality",
         "score": f"{breakdown['evidence']}/15",
         "weight": "15%",
         "detail": f"Extracted from '{opp.get('evidence_section','—')}' section. "
                   f"Source: {opp.get('source_file','—')}, page {opp.get('source_page',0) or 'unknown'}."},
        {"factor": "Recency / Timing",
         "score": f"{breakdown['recency']}/10",
         "weight": "10%",
         "detail": f"Based on DDR timing signals and section priority."},
    ]

    return {
        "opportunity_id":    opp_id,
        "title":             opp.get("title",""),
        "total_score":       breakdown["total"],
        "confidence":        opp.get("confidence", 0),
        "confidence_category": breakdown["confidence_category"],
        "reasons":           reasons,
        "explanation":       breakdown["explanation"],
        "source_evidence":   opp.get("evidence_text",""),
        "source_file":       opp.get("source_file",""),
        "source_page":       opp.get("source_page", 0),
        "validation_status": opp.get("validation_status","new"),
    }

@router.get("/value-rates")
async def get_rates(user: dict = Depends(get_current_user)):
    from core.database import get_value_rates
    return get_value_rates()

class RatesUpdate(BaseModel):
    rates: dict

@router.post("/value-rates")
async def save_rates(body:RatesUpdate, request:Request, user: dict = Depends(require_permission("upload"))):
    from core.database import save_value_rates
    save_value_rates(body.rates)
    return {"saved": True}

class SettingUpdate(BaseModel):
    key:str; value:str

@router.post("/settings/update")
async def update_setting(body:SettingUpdate, request:Request, user: dict = Depends(require_permission("upload"))):
    save_setting(body.key, body.value)
    return {"key":body.key,"value":body.value}
