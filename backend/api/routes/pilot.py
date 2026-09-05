"""
EIP v6.3A — Pilot Readiness, Entity Resolution & Temporal Validation API
/api/pilot/* and /api/entities/*
"""
import logging, json
from fastapi import APIRouter, Request, Depends, HTTPException, Query
from pydantic import BaseModel
from typing import Optional
from core.auth import get_current_user, require_permission
from core.database import get_db
from core.audit import audit_from_request

router  = APIRouter()
logger  = logging.getLogger("eip.pilot")


# ═══════════════════════════════════════════════════════════
# ENTITY RESOLUTION
# ═══════════════════════════════════════════════════════════

@router.get("/entities/summary")
async def entity_summary(user: dict = Depends(get_current_user)):
    """Master entity counts and review queue status."""
    from engines.intelligence.entity_resolution import get_entity_summary
    return get_entity_summary()


@router.get("/entities/{entity_type}")
async def list_entities(
    entity_type: str,
    limit: int = 50,
    user: dict = Depends(get_current_user)
):
    """List all master entities of a given type with observation counts."""
    from engines.intelligence.entity_resolution import get_master_entities
    valid = {"rig","field","well","competitor","operator","product_line","campaign"}
    if entity_type not in valid:
        raise HTTPException(400, f"entity_type must be one of: {', '.join(valid)}")
    return get_master_entities(entity_type=entity_type, limit=limit)


@router.get("/entities/rig/{entity_id}/history")
async def entity_observation_history(
    entity_id: str,
    user: dict = Depends(get_current_user)
):
    """All DDR observations for one master rig entity."""
    from engines.intelligence.entity_resolution import get_entity_observation_history
    return get_entity_observation_history(entity_id)


@router.get("/entities/review-queue")
async def review_queue(
    status: str = "pending",
    user: dict = Depends(get_current_user)
):
    """Entity alias review queue — low-confidence matches awaiting human review."""
    from engines.intelligence.entity_resolution import get_entity_review_queue
    return get_entity_review_queue(status=status)


class ReviewDecision(BaseModel):
    action: str  # confirmed | rejected | ignored


@router.post("/entities/review/{item_id}")
async def resolve_review_item(
    item_id: str,
    body: ReviewDecision,
    request: Request,
    user: dict = Depends(require_permission("validate"))
):
    """Confirm or reject an entity alias match from the review queue."""
    from engines.intelligence.entity_resolution import resolve_review_item
    result = resolve_review_item(item_id, body.action, user.get("email",""))
    audit_from_request(request,"OPP_VALIDATED",user=user,
                       detail=f"Entity review: {body.action} on {item_id[:8]}")
    return result


@router.post("/entities/process-upload/{upload_id}")
async def process_upload_entities(
    upload_id: str,
    request: Request,
    user: dict = Depends(require_permission("upload"))
):
    """Run entity resolution for all records in an upload."""
    from engines.intelligence.entity_resolution import process_upload_entities
    conn = get_db()
    upload = conn.execute("SELECT report_date FROM uploads WHERE id=?", (upload_id,)).fetchone()
    conn.close()
    if not upload:
        raise HTTPException(404, "Upload not found")
    rd = dict(upload).get("report_date","")
    stats = process_upload_entities(upload_id, rd)
    logger.info("entity_resolution_complete", extra={**stats, "upload_id": upload_id})
    return {"upload_id": upload_id, "entity_resolution": stats}


@router.post("/entities/process-all")
async def process_all_entities(
    request: Request,
    user: dict = Depends(require_permission("upload"))
):
    """Run entity resolution across ALL uploads. Use after first install or import."""
    from engines.intelligence.entity_resolution import process_upload_entities
    conn = get_db()
    uploads = conn.execute("SELECT id, report_date FROM uploads ORDER BY upload_ts ASC").fetchall()
    conn.close()
    all_stats = {"rigs":0,"fields":0,"competitors":0,"new_entities":0,"merged":0,"observations":0}
    for row in uploads:
        uid, rd = row
        stats = process_upload_entities(uid, rd or "")
        for k in all_stats: all_stats[k] += stats.get(k,0)
    return {"uploads_processed": len(uploads), "totals": all_stats}


# ═══════════════════════════════════════════════════════════
# TEMPORAL STATE ENGINE
# ═══════════════════════════════════════════════════════════

@router.get("/temporal/states")
async def entity_states(
    entity_type: str = "rig",
    limit: int = 50,
    user: dict = Depends(get_current_user)
):
    """Current authoritative state for all entities of a given type."""
    from engines.intelligence.temporal_engine import get_all_entity_states
    return get_all_entity_states(entity_type=entity_type, limit=limit)


@router.get("/temporal/transitions/{entity_id}")
async def entity_transitions(
    entity_id: str,
    entity_type: str = "rig",
    user: dict = Depends(get_current_user)
):
    """All meaningful state transitions for one master entity."""
    from engines.intelligence.temporal_engine import detect_entity_transitions
    transitions = detect_entity_transitions(entity_id, entity_type)
    return {"entity_id": entity_id, "entity_type": entity_type, "transitions": transitions}


@router.get("/temporal/change-metrics")
async def change_detection_metrics(user: dict = Depends(get_current_user)):
    """
    Change detection accuracy metrics.
    Returns 'not_yet_measured' if no human validations exist.
    """
    from engines.intelligence.temporal_engine import calculate_change_detection_metrics
    return calculate_change_detection_metrics()


class ChangeValidation(BaseModel):
    change_event_id: str
    validation_type: str  # true_positive|false_positive|duplicate|delayed|missed|needs_review
    master_entity_id: str = ""
    notes: str = ""


@router.post("/temporal/validate-change")
async def validate_change(
    body: ChangeValidation,
    request: Request,
    user: dict = Depends(get_current_user)
):
    """Record human validation of a detected change event."""
    from engines.intelligence.temporal_engine import validate_change_event
    result = validate_change_event(
        body.change_event_id, body.validation_type,
        body.master_entity_id, user.get("email",""), body.notes
    )
    return result


# ═══════════════════════════════════════════════════════════
# CAMPAIGN VALIDATION
# ═══════════════════════════════════════════════════════════

class CampaignValidation(BaseModel):
    validation_status: str  # confirmed|probable|possible|rejected|needs_review
    notes: str = ""


@router.post("/campaigns/{campaign_id}/validate")
async def validate_campaign(
    campaign_id: str,
    body: CampaignValidation,
    request: Request,
    user: dict = Depends(get_current_user)
):
    """Validate or reject a detected campaign."""
    valid = {"confirmed","probable","possible","rejected","needs_review"}
    if body.validation_status not in valid:
        raise HTTPException(400, f"validation_status must be one of: {', '.join(valid)}")

    import datetime
    conn = get_db()
    ts   = datetime.datetime.utcnow().isoformat()
    row  = conn.execute("SELECT id FROM campaigns WHERE id=?", (campaign_id,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "Campaign not found")
    conn.execute(
        """UPDATE campaigns
           SET validation_status=?, validated_by=?, validated_at=?, validation_notes=?
           WHERE id=?""",
        (body.validation_status, user.get("email",""), ts, body.notes, campaign_id)
    )
    conn.commit(); conn.close()
    audit_from_request(request,"OPP_VALIDATED",user=user,
                       detail=f"Campaign {campaign_id[:8]} → {body.validation_status}")
    return {"campaign_id": campaign_id, "validation_status": body.validation_status}


# ═══════════════════════════════════════════════════════════
# PILOT SCORECARD & COMMERCIAL VALUE
# ═══════════════════════════════════════════════════════════

@router.get("/scorecard")
async def pilot_scorecard(user: dict = Depends(get_current_user)):
    """
    Full pilot success scorecard with all measured metrics.
    Shows 'not_yet_measured' for any metric without real validation data.
    """
    from engines.intelligence.pilot_scorecard import build_pilot_scorecard
    # Load configurable thresholds from settings
    conn = get_db()
    row  = conn.execute("SELECT value FROM settings WHERE key='pilot_thresholds'").fetchone()
    conn.close()
    thresholds = {}
    if row:
        try: thresholds = json.loads(row[0])
        except: pass
    return build_pilot_scorecard(thresholds)


@router.post("/scorecard/thresholds")
async def update_thresholds(
    request: Request,
    user: dict = Depends(require_permission("admin"))
):
    """Update configurable pilot success thresholds."""
    body = await request.json()
    conn = get_db()
    conn.execute("INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)",
                 ("pilot_thresholds", json.dumps(body)))
    conn.commit(); conn.close()
    return {"status": "saved", "thresholds": body}


class CommercialValueEvent(BaseModel):
    insight_type: str = "opportunity"
    insight_id: str = ""
    value_type: str  # see VALUE_TYPES
    value_description: str = ""
    potential_revenue: float = 0
    weighted_revenue: float = 0
    validated_influence: float = 0
    awarded_revenue: float = 0
    hours_saved: float = 0
    days_earlier: int = 0
    notes: str = ""


@router.get("/commercial-value")
async def commercial_value(user: dict = Depends(get_current_user)):
    """Aggregated commercial value with STRICTLY separated revenue categories."""
    from engines.intelligence.pilot_scorecard import get_commercial_value_summary
    return get_commercial_value_summary()


@router.post("/commercial-value")
async def record_value(
    body: CommercialValueEvent,
    request: Request,
    user: dict = Depends(get_current_user)
):
    """Record that an intelligence insight created real commercial value."""
    from engines.intelligence.pilot_scorecard import record_commercial_value
    result = record_commercial_value(body.model_dump(), user.get("email",""))
    audit_from_request(request,"OPP_STATUS_CHANGE",user=user,
                       detail=f"Commercial value recorded: {body.value_type}")
    return result
