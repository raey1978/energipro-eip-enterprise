"""
EIP v5.1 — Revenue Intelligence & Pipeline API Routes
"""
import logging, json
from fastapi import APIRouter, Request, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional
from core.auth import get_current_user, require_permission
from core.audit import audit_from_request
from core.database import get_db

router = APIRouter()
logger = logging.getLogger("eip.revenue")


def _store(r): return getattr(r.app.state,"intelligence_store",{})
def _opps(r):  return _store(r).get("opportunities",[])


def _get_vr(request):
    conn = get_db()
    row  = conn.execute("SELECT value FROM settings WHERE key='value_rates'").fetchone()
    conn.close()
    vr = {}
    if row:
        try: vr = json.loads(row[0])
        except: pass
    return vr


# ── Revenue Intelligence ──────────────────────────────────────────────────────
@router.get("/pipeline-summary")
async def revenue_pipeline_summary(
    request: Request,
    user: dict = Depends(get_current_user)
):
    """Aggregate revenue intelligence across all current opportunities."""
    from engines.intelligence.revenue_engine import build_revenue_pipeline_summary
    opps = _opps(request)
    return build_revenue_pipeline_summary(opps)


@router.get("/opportunity/{opp_id}")
async def revenue_for_opportunity(
    opp_id: str,
    request: Request,
    user: dict = Depends(get_current_user)
):
    """Full revenue intelligence for one opportunity."""
    from engines.intelligence.revenue_engine import calculate_revenue_intelligence
    opps = _opps(request)
    opp  = next((o for o in opps if o.get("id") == opp_id), None)
    if not opp:
        conn = get_db()
        row  = conn.execute("SELECT * FROM opportunities WHERE id=?", (opp_id,)).fetchone()
        conn.close()
        if not row: raise HTTPException(404,"Opportunity not found")
        opp = dict(row)
    ri = calculate_revenue_intelligence(opp, _get_vr(request))
    return {"opportunity_id": opp_id, "revenue_intelligence": ri}


@router.get("/qualify/{opp_id}")
async def qualify_opportunity(
    opp_id: str,
    request: Request,
    user: dict = Depends(get_current_user)
):
    """Full qualification score for one opportunity."""
    from engines.intelligence.qualification_engine import qualify_opportunity as qo
    opps = _opps(request)
    opp  = next((o for o in opps if o.get("id") == opp_id), None)
    if not opp:
        conn = get_db()
        row  = conn.execute("SELECT * FROM opportunities WHERE id=?", (opp_id,)).fetchone()
        conn.close()
        if not row: raise HTTPException(404,"Opportunity not found")
        opp = dict(row)
    return qo(opp)


@router.get("/win-strategy/{opp_id}")
async def win_strategy(
    opp_id: str,
    request: Request,
    user: dict = Depends(get_current_user)
):
    """Full Win Strategy for one opportunity."""
    from engines.intelligence.win_strategy_engine import generate_win_strategy
    opps = _opps(request)
    opp  = next((o for o in opps if o.get("id") == opp_id), None)
    if not opp:
        conn = get_db()
        row  = conn.execute("SELECT * FROM opportunities WHERE id=?", (opp_id,)).fetchone()
        conn.close()
        if not row: raise HTTPException(404,"Opportunity not found")
        opp = dict(row)
    return generate_win_strategy(opp)


@router.get("/full-intelligence/{opp_id}")
async def full_opportunity_intelligence(
    opp_id: str,
    request: Request,
    user: dict = Depends(get_current_user)
):
    """Combined: Revenue + Qualification + Win Strategy + Commercial Intelligence."""
    from engines.intelligence.revenue_engine        import calculate_revenue_intelligence
    from engines.intelligence.qualification_engine  import qualify_opportunity
    from engines.intelligence.win_strategy_engine   import generate_win_strategy
    from engines.intelligence.commercial_engine     import calculate_commercial_intelligence

    opps = _opps(request)
    opp  = next((o for o in opps if o.get("id") == opp_id), None)
    if not opp:
        conn = get_db()
        row  = conn.execute("SELECT * FROM opportunities WHERE id=?", (opp_id,)).fetchone()
        conn.close()
        if not row: raise HTTPException(404,"Opportunity not found")
        opp = dict(row)
        try: opp["matched_keywords"] = json.loads(opp.get("matched_keywords","[]") or "[]")
        except: opp["matched_keywords"] = []

    vr = _get_vr(request)
    return {
        "opportunity":          opp,
        "commercial":           calculate_commercial_intelligence(opp, vr),
        "revenue":              calculate_revenue_intelligence(opp, vr),
        "qualification":        qualify_opportunity(opp),
        "win_strategy":         generate_win_strategy(opp),
    }


# ── Revenue Pipeline CRUD ─────────────────────────────────────────────────────
class PipelineItemCreate(BaseModel):
    opportunity_id: str = ""
    title: str
    product_line: str = ""
    customer: str = ""
    operator: str = ""
    rig: str = ""
    well: str = ""
    field: str = ""
    stage: str = "Identified"
    revenue_expected: float = 0
    revenue_conservative: float = 0
    revenue_optimistic: float = 0
    gross_margin_pct: float = 0.28
    win_probability: float = 0.25
    expected_award_date: str = ""
    expected_award_month: str = ""
    competitor: str = ""
    owner: str = "Unassigned"
    priority: str = "medium"
    notes: str = ""


class StageAdvance(BaseModel):
    stage: str
    notes: str = ""


class LessonLearned(BaseModel):
    type: str = "general"
    title: str
    description: str = ""
    outcome: str = ""
    product_line: str = ""
    customer: str = ""
    competitor: str = ""
    opportunity_id: str = ""
    pipeline_item_id: str = ""


@router.get("/pipeline")
async def list_pipeline(
    stage: Optional[str] = None,
    product_line: Optional[str] = None,
    owner: Optional[str] = None,
    user: dict = Depends(get_current_user)
):
    from engines.intelligence.pipeline_engine import list_pipeline_items
    return list_pipeline_items(stage=stage, product_line=product_line, owner=owner)


@router.get("/pipeline/summary")
async def pipeline_summary(user: dict = Depends(get_current_user)):
    from engines.intelligence.pipeline_engine import get_pipeline_summary
    return get_pipeline_summary()


@router.post("/pipeline")
async def create_pipeline_item(
    body: PipelineItemCreate,
    request: Request,
    user: dict = Depends(require_permission("convert_lead"))
):
    from engines.intelligence.pipeline_engine import create_pipeline_item
    item = create_pipeline_item(body.model_dump(), user.get("email",""))
    audit_from_request(request,"LEAD_CREATED",user=user,
                       detail=f"Pipeline item: {body.title}",resource_id=item.get("id"))
    return item


@router.post("/pipeline/from-opportunity/{opp_id}")
async def pipeline_from_opportunity(
    opp_id: str,
    request: Request,
    user: dict = Depends(require_permission("convert_lead"))
):
    """Convert opportunity directly to pipeline item with full revenue intelligence."""
    from engines.intelligence.revenue_engine        import calculate_revenue_intelligence
    from engines.intelligence.qualification_engine  import qualify_opportunity
    from engines.intelligence.commercial_engine     import calculate_commercial_intelligence
    from engines.intelligence.pipeline_engine       import create_pipeline_item

    opps = _opps(request)
    opp  = next((o for o in opps if o.get("id") == opp_id), None)
    if not opp:
        conn = get_db()
        row  = conn.execute("SELECT * FROM opportunities WHERE id=?", (opp_id,)).fetchone()
        conn.close()
        if not row: raise HTTPException(404,"Opportunity not found")
        opp = dict(row)
        try: opp["matched_keywords"] = json.loads(opp.get("matched_keywords","[]") or "[]")
        except: opp["matched_keywords"] = []

    vr   = _get_vr(request)
    ri   = calculate_revenue_intelligence(opp, vr)
    ci   = calculate_commercial_intelligence(opp, vr)
    qual = qualify_opportunity(opp)

    data = {
        "opportunity_id":     opp_id,
        "title":              opp.get("title",""),
        "product_line":       opp.get("product_line",""),
        "customer":           opp.get("contact_name","") or opp.get("suggested_contact",""),
        "rig":                opp.get("rig",""),
        "well":               opp.get("well",""),
        "field":              opp.get("field",""),
        "stage":              "Qualifying" if qual["qualification_score"]>=50 else "Identified",
        "revenue_expected":   ri["revenue_expected"],
        "revenue_conservative":ri["revenue_conservative"],
        "revenue_optimistic":  ri["revenue_optimistic"],
        "gross_margin_pct":   ri["gross_margin_pct"]/100,
        "win_probability":    ci["win_probability"]/100 if ci["win_probability"]>1 else ci["win_probability"],
        "expected_award_date": ri["expected_award_date"],
        "expected_award_month":ri["expected_award_month"],
        "competitor":         opp.get("competitor",""),
        "priority":           "high" if ci["commercial_priority"]>=70 else "medium",
        "qualification_score":qual["qualification_score"],
        "commercial_priority":ci["commercial_priority"],
        "notes":              f"Created from DDR opportunity. {qual['verdict']}: {qual['verdict_detail']}",
    }
    item = create_pipeline_item(data, user.get("email",""))
    audit_from_request(request,"LEAD_CREATED",user=user,
                       detail=f"Opportunity {opp.get('title','')} → Pipeline {item.get('stage','')}",
                       resource_id=item.get("id"))
    return {"pipeline_item": item, "revenue_intelligence": ri, "qualification": qual}


@router.patch("/pipeline/{item_id}/advance")
async def advance_stage(
    item_id: str,
    body: StageAdvance,
    request: Request,
    user: dict = Depends(require_permission("validate"))
):
    from engines.intelligence.pipeline_engine import advance_pipeline_stage
    updated = advance_pipeline_stage(item_id, body.stage, body.notes, user.get("email",""))
    if not updated: raise HTTPException(404,"Pipeline item not found")
    audit_from_request(request,"OPP_STATUS_CHANGE",user=user,
                       detail=f"Pipeline stage → {body.stage}",resource_id=item_id)
    return updated


# ── Lessons Learned ───────────────────────────────────────────────────────────
@router.post("/lessons")
async def add_lesson(
    body: LessonLearned,
    request: Request,
    user: dict = Depends(get_current_user)
):
    from engines.intelligence.pipeline_engine import record_lesson_learned
    lesson = record_lesson_learned(body.model_dump(), user.get("email",""))
    return lesson


@router.get("/lessons")
async def get_lessons(
    type_: Optional[str] = None,
    product_line: Optional[str] = None,
    user: dict = Depends(get_current_user)
):
    from engines.intelligence.pipeline_engine import get_lessons_learned
    return get_lessons_learned(type_=type_, product_line=product_line)
