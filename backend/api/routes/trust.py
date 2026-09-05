"""
EIP v6.1 — AI Trust Layer & Demo Mode API Routes
"""
import logging, json
from fastapi import APIRouter, Request, Depends, HTTPException
from typing import Optional
from core.auth import get_current_user, require_permission
from core.database import get_db

router  = APIRouter()
logger  = logging.getLogger("eip.trust")


def _store(r): return getattr(r.app.state,"intelligence_store",{})


# ── Trust Scoring ─────────────────────────────────────────────────────────────

@router.get("/platform-summary")
async def platform_trust_summary(user: dict = Depends(get_current_user)):
    """Overall platform trust dashboard metrics."""
    from engines.intelligence.trust_layer import get_platform_trust_summary
    return get_platform_trust_summary()


@router.get("/opportunity/{opp_id}")
async def opportunity_trust(
    opp_id: str,
    request: Request,
    user: dict = Depends(get_current_user)
):
    """Full trust envelope for an opportunity."""
    from engines.intelligence.trust_layer import calculate_trust_envelope, store_trust_score

    opps = _store(request).get("opportunities",[])
    opp  = next((o for o in opps if o.get("id")==opp_id), None)
    if not opp:
        conn = get_db()
        row  = conn.execute("SELECT * FROM opportunities WHERE id=?", (opp_id,)).fetchone()
        conn.close()
        if not row: raise HTTPException(404,"Opportunity not found")
        opp = dict(row)
        try: opp["matched_keywords"]=json.loads(opp.get("matched_keywords","[]") or "[]")
        except: opp["matched_keywords"]=[]

    envelope = calculate_trust_envelope("opportunity", opp)
    store_trust_score("opportunity", opp_id, envelope)
    return {"opportunity_id": opp_id, "trust_envelope": envelope}


@router.get("/change/{change_id}")
async def change_trust(change_id: str, user: dict = Depends(get_current_user)):
    """Trust envelope for a change event."""
    from engines.intelligence.trust_layer import calculate_trust_envelope
    conn = get_db()
    row  = conn.execute("SELECT * FROM change_events WHERE id=?", (change_id,)).fetchone()
    conn.close()
    if not row: raise HTTPException(404,"Change event not found")
    data = dict(row)
    try: data["evidence"] = json.loads(data.get("evidence","[]") or "[]")
    except: data["evidence"] = []
    return calculate_trust_envelope("change_event", data)


@router.get("/trend/{dimension}/{value}")
async def trend_trust(dimension: str, value: str, user: dict = Depends(get_current_user)):
    """Trust envelope for a trend signal."""
    from engines.intelligence.trust_layer import calculate_trust_envelope
    conn = get_db()
    row  = conn.execute(
        "SELECT * FROM trend_signals WHERE dimension=? AND dimension_value=? LIMIT 1",
        (dimension, value)
    ).fetchone()
    conn.close()
    if not row: raise HTTPException(404,"Trend signal not found")
    return calculate_trust_envelope("trend_signal", dict(row))


@router.get("/campaign/{campaign_id}")
async def campaign_trust(campaign_id: str, user: dict = Depends(get_current_user)):
    """Trust envelope for a campaign."""
    from engines.intelligence.trust_layer import calculate_trust_envelope
    conn = get_db()
    row  = conn.execute("SELECT * FROM campaigns WHERE id=?", (campaign_id,)).fetchone()
    conn.close()
    if not row: raise HTTPException(404,"Campaign not found")
    return calculate_trust_envelope("campaign", dict(row))


@router.post("/score-all")
async def score_all_insights(
    request: Request,
    user: dict = Depends(require_permission("upload"))
):
    """Calculate trust scores for all current insights. Run after upload."""
    from engines.intelligence.trust_layer import (
        calculate_trust_envelope, store_trust_score, init_trust_tables
    )
    init_trust_tables()

    conn    = get_db()
    opps    = conn.execute("SELECT id,confidence,urgency,validation_status,evidence_text,evidence_section,source_file,source_page,competitor,rig,well,field,created_at FROM opportunities LIMIT 200").fetchall()
    changes = conn.execute("SELECT * FROM change_events ORDER BY detected_at DESC LIMIT 100").fetchall()
    trends  = conn.execute("SELECT * FROM trend_signals").fetchall()
    camps   = conn.execute("SELECT * FROM campaigns").fetchall()
    conn.close()

    scored = 0
    for row in opps:
        opp = dict(row)
        env = calculate_trust_envelope("opportunity", opp)
        store_trust_score("opportunity", opp["id"], env)
        scored += 1

    for row in changes:
        ch   = dict(row)
        try: ch["evidence"]=json.loads(ch.get("evidence","[]") or "[]")
        except: ch["evidence"]=[]
        env  = calculate_trust_envelope("change_event", ch)
        store_trust_score("change_event", ch["id"], env)
        scored += 1

    for row in trends:
        ts  = dict(row)
        env = calculate_trust_envelope("trend_signal", ts)
        store_trust_score("trend_signal", ts["id"], env)
        scored += 1

    for row in camps:
        camp = dict(row)
        env  = calculate_trust_envelope("campaign", camp)
        store_trust_score("campaign", camp["id"], env)
        scored += 1

    logger.info("trust_scoring_complete", extra={"scored": scored})
    return {"scored": scored, "status": "complete"}


# ── Evidence Explorer ─────────────────────────────────────────────────────────

@router.get("/explain/{insight_type}/{insight_id}")
async def explain_insight(
    insight_type: str,
    insight_id: str,
    request: Request,
    user: dict = Depends(get_current_user)
):
    """
    Evidence Explorer — trace any insight back to its source DDR evidence.
    Returns the full evidence chain.
    """
    from engines.intelligence.trust_layer import (
        calculate_trust_envelope, OBS_TYPE_META
    )
    conn = get_db()

    data        = None
    trust_env   = {}
    evidence_chain = []
    related_opps   = []
    related_changes = []

    if insight_type == "opportunity":
        row = conn.execute("SELECT * FROM opportunities WHERE id=?", (insight_id,)).fetchone()
        if not row: raise HTTPException(404,"Not found")
        data = dict(row)
        try: data["matched_keywords"]=json.loads(data.get("matched_keywords","[]") or "[]")
        except: data["matched_keywords"]=[]
        trust_env = calculate_trust_envelope("opportunity", data)

        # Evidence chain: source upload
        upload = conn.execute("SELECT * FROM uploads WHERE id=?", (data.get("upload_id",""),)).fetchone()
        if upload:
            evidence_chain.append({
                "type":    "source_document",
                "label":   "Source DDR",
                "detail":  dict(upload).get("filename",""),
                "date":    dict(upload).get("report_date",""),
                "page":    data.get("source_page",0),
                "section": data.get("evidence_section",""),
            })
        evidence_chain.append({
            "type":     "evidence_text",
            "label":    "Extracted Evidence",
            "section":  data.get("evidence_section",""),
            "text":     data.get("evidence_text",""),
            "keywords": data.get("matched_keywords",[]),
        })

        # Related opportunities (same rig/field)
        related_rows = conn.execute(
            "SELECT id,title,product_line,urgency,confidence FROM opportunities WHERE rig=? AND id!=? LIMIT 5",
            (data.get("rig",""), insight_id)
        ).fetchall()
        related_opps = [dict(r) for r in related_rows]

    elif insight_type == "change_event":
        row = conn.execute("SELECT * FROM change_events WHERE id=?", (insight_id,)).fetchone()
        if not row: raise HTTPException(404,"Not found")
        data = dict(row)
        try: data["evidence"]=json.loads(data.get("evidence","[]") or "[]")
        except: data["evidence"]=[]
        trust_env = calculate_trust_envelope("change_event", data)

        # Current and previous uploads
        for uid in [data.get("upload_id"), data.get("prev_upload_id")]:
            if uid:
                upload = conn.execute("SELECT * FROM uploads WHERE id=?", (uid,)).fetchone()
                if upload:
                    evidence_chain.append({
                        "type":  "source_document",
                        "label": "Compared DDR",
                        "detail":dict(upload).get("filename",""),
                        "date":  dict(upload).get("report_date",""),
                        "role":  "current" if uid==data.get("upload_id") else "previous",
                    })
        for ev in (data.get("evidence") or []):
            evidence_chain.append({"type":"evidence_item","label":"Evidence","text":ev})

        # Related opportunities on affected rig/field
        rig = data.get("affected_rig","")
        if rig:
            related_rows = conn.execute(
                "SELECT id,title,product_line,urgency,confidence FROM opportunities WHERE rig=? LIMIT 5",
                (rig,)
            ).fetchall()
            related_opps = [dict(r) for r in related_rows]

    elif insight_type == "campaign":
        row = conn.execute("SELECT * FROM campaigns WHERE id=?", (insight_id,)).fetchone()
        if not row: raise HTTPException(404,"Not found")
        data = dict(row)
        for f in ["fields","rigs","wells","expected_services","evidence_upload_ids"]:
            try: data[f]=json.loads(data.get(f,"[]") or "[]")
            except: data[f]=[]
        trust_env = calculate_trust_envelope("campaign", data)

        for uid in data.get("evidence_upload_ids",[]):
            upload = conn.execute("SELECT * FROM uploads WHERE id=?", (uid,)).fetchone()
            if upload:
                evidence_chain.append({
                    "type":"source_document","label":"Supporting DDR",
                    "detail":dict(upload).get("filename",""),
                    "date":dict(upload).get("report_date",""),
                })

    conn.close()

    return {
        "insight_type":    insight_type,
        "insight_id":      insight_id,
        "data":            data,
        "trust_envelope":  trust_env,
        "evidence_chain":  evidence_chain,
        "related_opportunities":  related_opps,
        "related_change_events":  related_changes,
        "obs_type_meta":   OBS_TYPE_META,
    }


# ── Demo Mode ─────────────────────────────────────────────────────────────────

@router.post("/demo/load")
async def load_demo(
    request: Request,
    user: dict = Depends(require_permission("upload"))
):
    """Load the executive demonstration dataset."""
    from engines.intelligence.demo_data import seed_demo_data, DEMO_TALKING_POINTS

    result = seed_demo_data()

    # Load latest into memory store
    from core.database import load_latest
    data = load_latest()
    if data:
        request.app.state.intelligence_store = data

    # Score all insights
    from engines.intelligence.trust_layer import init_trust_tables, calculate_trust_envelope, store_trust_score
    init_trust_tables()

    logger.info("demo_loaded", extra={"user": user.get("email"), **result})
    return {**result, "talking_points": DEMO_TALKING_POINTS}


@router.post("/demo/reset")
async def reset_demo(
    request: Request,
    user: dict = Depends(require_permission("upload"))
):
    """Reset demo data and reload."""
    from core.database import get_db
    conn = get_db()
    for table in ["uploads","opportunities","competitors","market_snapshots",
                  "change_events","campaigns","trend_signals","trust_scores"]:
        conn.execute(f"DELETE FROM {table} WHERE 1=1")
    conn.commit(); conn.close()
    request.app.state.intelligence_store = {"reports_processed": 0}
    return {"status": "reset_complete"}


@router.get("/demo/talking-points")
async def demo_talking_points(user: dict = Depends(get_current_user)):
    from engines.intelligence.demo_data import DEMO_TALKING_POINTS
    return DEMO_TALKING_POINTS


@router.post("/demo/load-pilot")
async def load_pilot_dataset(
    request: Request,
    user: dict = Depends(require_permission("upload"))
):
    """Load the realistic 90-day pilot validation dataset."""
    from engines.intelligence.pilot_dataset import seed_pilot_dataset
    result = seed_pilot_dataset()
    # Reload intelligence store
    from core.database import load_latest
    data = load_latest()
    if data:
        request.app.state.intelligence_store = data
    logger.info("pilot_dataset_loaded", extra={"user": user.get("email"), **{k:v for k,v in result.items() if isinstance(v,(int,str))}})
    return result
