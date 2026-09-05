"""
EIP v6.0 — Market Intelligence API Routes
/api/market/* endpoints — all market-level intelligence.
"""
import logging
from fastapi import APIRouter, Depends, Request, HTTPException
from typing import Optional
from core.auth import get_current_user, require_permission

router = APIRouter()
logger = logging.getLogger("eip.market")


@router.get("/pulse")
async def market_pulse(user: dict = Depends(get_current_user)):
    """Live market pulse with period-over-period comparison."""
    from engines.intelligence.market_intelligence import get_market_pulse
    return get_market_pulse()


@router.get("/aggregates")
async def market_aggregates(user: dict = Depends(get_current_user)):
    """Aggregated intelligence across ALL uploaded DDRs."""
    from engines.intelligence.market_intelligence import get_market_aggregates
    return get_market_aggregates()


@router.get("/trends")
async def market_trends(
    dimension: Optional[str] = None,
    user: dict = Depends(get_current_user)
):
    """Calculated trend signals from historical data."""
    from engines.intelligence.market_intelligence import get_trend_signals
    return get_trend_signals(dimension=dimension)


@router.get("/snapshots")
async def market_snapshots(
    limit: int = 10,
    user: dict = Depends(get_current_user)
):
    """Historical market snapshots for trend visualization."""
    import json
    from core.database import get_db
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM market_snapshots ORDER BY snapshot_date DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    result = []
    for r in rows:
        d = dict(r)
        for f in ["pl_distribution","field_distribution","comp_distribution"]:
            try: d[f] = json.loads(d.get(f,"{}") or "{}")
            except: d[f] = {}
        for f in ["rig_list","operator_list"]:
            try: d[f] = json.loads(d.get(f,"[]") or "[]")
            except: d[f] = []
        result.append(d)
    return result


@router.get("/changes")
async def change_feed(
    severity: Optional[str] = None,
    unread_only: bool = False,
    limit: int = 30,
    user: dict = Depends(get_current_user)
):
    """What changed? Feed — detected market changes between uploads."""
    from engines.intelligence.change_detection import get_change_feed
    return get_change_feed(severity=severity, unread_only=unread_only, limit=limit)


@router.patch("/changes/{change_id}/read")
async def mark_change_read(change_id: str, user: dict = Depends(get_current_user)):
    from engines.intelligence.change_detection import mark_change_read
    mark_change_read(change_id)
    return {"status": "marked_read"}


@router.get("/campaigns")
async def get_campaigns(
    campaign_type: Optional[str] = None,
    user: dict = Depends(get_current_user)
):
    """Detected drilling / completion campaigns."""
    from engines.intelligence.campaign_detector import get_campaigns
    return get_campaigns(campaign_type=campaign_type)


@router.post("/campaigns/refresh")
async def refresh_campaigns(
    request: Request,
    user: dict = Depends(require_permission("upload"))
):
    """Rerun campaign detection from current data."""
    from core.database import get_db
    from engines.intelligence.campaign_detector import detect_campaigns
    conn = get_db()
    upload = conn.execute("SELECT id FROM uploads ORDER BY upload_ts DESC LIMIT 1").fetchone()
    conn.close()
    if not upload:
        return {"detected": 0, "message": "No uploads found"}
    campaigns = detect_campaigns(dict(upload)["id"])
    return {"detected": len(campaigns), "campaigns": campaigns[:5]}


@router.post("/refresh")
async def refresh_market_intelligence(
    request: Request,
    user: dict = Depends(require_permission("upload"))
):
    """
    Regenerate all market intelligence from current data.
    Called automatically on upload — also available manually.
    """
    from core.database import get_db
    from engines.intelligence.market_intelligence import (
        generate_market_snapshot, calculate_trend_signals
    )
    from engines.intelligence.change_detection import detect_changes
    from engines.intelligence.campaign_detector import detect_campaigns

    conn = get_db()
    uploads = conn.execute(
        "SELECT id FROM uploads ORDER BY upload_ts DESC LIMIT 2"
    ).fetchall()
    conn.close()

    if not uploads:
        return {"status": "no_data"}

    latest_id = dict(uploads[0])["id"]
    prev_id   = dict(uploads[1])["id"] if len(uploads) > 1 else None

    snap = generate_market_snapshot(latest_id)
    changes = detect_changes(latest_id, prev_id)
    campaigns = detect_campaigns(latest_id)
    trends = calculate_trend_signals()

    logger.info("market_refresh", extra={
        "upload_id": latest_id,
        "changes_detected": len(changes),
        "campaigns": len(campaigns),
        "trends": len(trends),
    })

    return {
        "snapshot":       snap,
        "changes_detected": len(changes),
        "campaigns":      len(campaigns),
        "trend_signals":  len(trends),
    }


@router.get("/operations-center")
async def market_operations_center(
    request: Request,
    user: dict = Depends(get_current_user)
):
    """
    Full Executive Market Operations Center data.
    Single endpoint that powers the main executive dashboard.
    Aggregates: pulse + changes + campaigns + trends + brief + recommendations.
    """
    from engines.intelligence.market_intelligence import get_market_pulse, get_market_aggregates, get_trend_signals
    from engines.intelligence.change_detection    import get_change_feed
    from engines.intelligence.campaign_detector   import get_campaigns
    from engines.intelligence.insights_engine     import get_strategic_insights
    from engines.intelligence.prediction_engine   import get_recommendation_for_user

    data = getattr(request.app.state, "intelligence_store", {})
    role = user.get("role","viewer")

    pulse      = get_market_pulse()
    aggregates = get_market_aggregates()
    changes    = get_change_feed(limit=8, unread_only=False)
    campaigns  = get_campaigns()[:4]
    trends     = get_trend_signals()[:6]
    insights   = get_strategic_insights(limit=4)
    recs       = get_recommendation_for_user(role, data)

    # Unread change count
    from core.database import get_db
    conn = get_db()
    unread_changes = conn.execute("SELECT COUNT(*) FROM change_events WHERE is_read=0").fetchone()[0]
    conn.close()

    opps = data.get("opportunities", [])
    imm  = [o for o in opps if o.get("urgency") in ("immediate","5_days")]

    return {
        "market_pulse":      pulse,
        "aggregates":        aggregates,
        "recent_changes":    changes[:6],
        "unread_changes":    unread_changes,
        "active_campaigns":  campaigns,
        "trend_signals":     trends,
        "strategic_insights":insights,
        "recommendations":   recs,
        "current_opportunities": len(opps),
        "immediate_actions": len(imm),
        "report_date":       data.get("report_date",""),
        "generated_at":      __import__("datetime").datetime.utcnow().isoformat(),
    }
