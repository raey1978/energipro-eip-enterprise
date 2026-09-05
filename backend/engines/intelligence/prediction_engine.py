"""
EIP v5.1 — Prediction Engine
Time-series trend analysis and 30-day pipeline forecasting.
Uses snapshot history to project future activity.

IMPORTANT: All predictions shown with confidence intervals.
Never presented as facts. Assumptions clearly stated.
"""
import json, datetime
from typing import List, Dict
from core.database import get_db


def get_snapshot_history() -> List[dict]:
    """Retrieve all historical snapshots for trend analysis."""
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM snapshots ORDER BY upload_ts ASC"
    ).fetchall()
    conn.close()
    result = []
    for r in rows:
        d = dict(r)
        try: d["pl_counts"] = json.loads(d.get("pl_counts","{}") or "{}")
        except: d["pl_counts"] = {}
        result.append(d)
    return result


def generate_forecast(current_data: dict) -> dict:
    """
    Generate 30-day pipeline forecast from current data and historical snapshots.
    
    Returns forecast with:
    - Trend direction (growing/stable/declining)
    - Projected pipeline in 30 days
    - Confidence interval
    - Key assumptions
    - By-product-line breakdown
    """
    snapshots  = get_snapshot_history()
    opps       = current_data.get("opportunities", [])
    current_pl = {}
    for o in opps:
        pl = o.get("product_line","")
        current_pl[pl] = current_pl.get(pl, 0) + 1

    current_pipeline = sum(o.get("estimated_value",0) for o in opps)
    current_rigs     = len(set(o.get("rig","") for o in opps if o.get("rig")))
    current_imm      = sum(1 for o in opps if o.get("urgency") in ("immediate","5_days"))

    # ── Trend calculation from snapshots ─────────────────────────────────────
    if len(snapshots) >= 2:
        recent = snapshots[-3:]   # Last 3 snapshots
        older  = snapshots[:max(1, len(snapshots)-3)]

        avg_recent_pipeline = sum(s.get("pipeline",0) for s in recent) / max(len(recent),1)
        avg_older_pipeline  = sum(s.get("pipeline",0) for s in older)  / max(len(older),1)
        avg_recent_rigs     = sum(s.get("rigs_parsed",0) for s in recent) / max(len(recent),1)
        avg_older_rigs      = sum(s.get("rigs_parsed",0) for s in older)  / max(len(older),1)

        if avg_older_pipeline > 0:
            pipeline_growth = (avg_recent_pipeline - avg_older_pipeline) / avg_older_pipeline
        else:
            pipeline_growth = 0.0

        if avg_older_rigs > 0:
            rig_growth = (avg_recent_rigs - avg_older_rigs) / avg_older_rigs
        else:
            rig_growth = 0.0

        trend = "growing"   if pipeline_growth > 0.10 else \
                "declining" if pipeline_growth < -0.10 else "stable"
        data_confidence = min(0.80, 0.40 + len(snapshots) * 0.08)
    else:
        pipeline_growth = 0.0
        rig_growth      = 0.0
        trend           = "stable"
        data_confidence = 0.25  # Low confidence with single data point

    # ── 30-day forecast ───────────────────────────────────────────────────────
    # Base: current pipeline × growth rate (dampened for uncertainty)
    dampening_factor = 0.6  # Don't extrapolate aggressively
    projected_growth = pipeline_growth * dampening_factor

    forecast_pipeline = current_pipeline * (1 + projected_growth)
    # Confidence interval: ±20% at low data, ±10% at high data
    ci_width = (1.0 - data_confidence) * 0.3 + 0.05
    ci_low   = forecast_pipeline * (1 - ci_width)
    ci_high  = forecast_pipeline * (1 + ci_width)

    # ── Product line forecasts ─────────────────────────────────────────────
    pl_forecasts = []
    for pl, count in sorted(current_pl.items(), key=lambda x: -x[1]):
        val = sum(o.get("estimated_value",0) for o in opps if o.get("product_line")==pl)
        pl_trend = "stable"
        if snapshots:
            # Check if this PL is trending in snapshots
            recent_pl_counts = [s.get("pl_counts",{}).get(pl,0) for s in snapshots[-3:] if s.get("pl_counts")]
            older_pl_counts  = [s.get("pl_counts",{}).get(pl,0) for s in snapshots[:max(1,len(snapshots)-3)] if s.get("pl_counts")]
            if recent_pl_counts and older_pl_counts:
                avg_r = sum(recent_pl_counts)/len(recent_pl_counts)
                avg_o = sum(older_pl_counts)/len(older_pl_counts)
                if avg_o > 0:
                    pl_growth = (avg_r-avg_o)/avg_o
                    pl_trend  = "growing" if pl_growth>0.15 else "declining" if pl_growth<-0.15 else "stable"
        pl_forecasts.append({
            "product_line": pl,
            "current_count": count,
            "current_value": val,
            "trend": pl_trend,
            "forecast_note": (
                f"Increasing demand detected" if pl_trend=="growing" else
                f"Declining activity" if pl_trend=="declining" else
                f"Stable demand"
            ),
        })

    # ── Market signals ─────────────────────────────────────────────────────
    signals = []
    if current_imm > 5:
        signals.append({"type":"warning","text":f"{current_imm} immediate actions — high activity period"})
    if trend == "growing":
        signals.append({"type":"positive","text":"Pipeline trending upward based on recent history"})
    elif trend == "declining":
        signals.append({"type":"warning","text":"Pipeline declining — recommend increased sales activity"})
    if current_rigs < 5 and current_pipeline > 500_000:
        signals.append({"type":"info","text":"High-value concentrated pipeline — key account risk"})
    if len(snapshots) < 3:
        signals.append({"type":"info","text":f"Only {len(snapshots)} report(s) loaded — upload more DDRs for better forecasting accuracy"})

    return {
        "forecast_date":        datetime.date.today().isoformat(),
        "horizon_days":         30,
        "trend":                trend,
        "trend_description":    f"Pipeline is {trend} based on {len(snapshots)} historical reports",
        "current_pipeline":     current_pipeline,
        "forecast_pipeline":    round(forecast_pipeline),
        "forecast_ci_low":      round(ci_low),
        "forecast_ci_high":     round(ci_high),
        "data_confidence":      round(data_confidence * 100),
        "pipeline_growth_rate": round(pipeline_growth * 100, 1),
        "current_rigs":         current_rigs,
        "current_opportunities":len(opps),
        "immediate_actions":    current_imm,
        "by_product_line":      pl_forecasts,
        "market_signals":       signals,
        "snapshots_available":  len(snapshots),
        "assumptions": [
            "Revenue estimates based on Saudi Aramco unit-rate service contracts per job",
            f"Forecast uses {len(snapshots)} historical data point(s) — more reports = better accuracy",
            "Win probability applied per product line based on historical industry benchmarks",
            "Competitor displacement factors reduce win probability by 2% per competitor strength point",
            f"Confidence interval: ±{round(ci_width*100)}% (widens with limited historical data)",
            "Predictions are estimates only — actual results depend on customer decisions and market conditions",
        ],
        "disclaimer": (
            "This forecast is generated from DDR intelligence data and should be used "
            "as one input among many for business planning. It is not a guarantee of future performance."
        ),
    }


def get_recommendation_for_user(user_role: str, data: dict) -> List[dict]:
    """
    Per-user recommendations based on role and current data.
    The Recommendation Engine.
    """
    opps = data.get("opportunities", [])
    if not opps:
        return [{"type":"info","title":"No data","description":"Upload a DDR to get personalised recommendations."}]

    recs = []
    immediate = sorted(
        [o for o in opps if o.get("urgency") in ("immediate","5_days")],
        key=lambda x: -x.get("confidence",0)
    )
    high_conf = [o for o in opps if o.get("confidence",0) >= 85 and o.get("validation_status","new")=="new"]
    unvalidated_count = sum(1 for o in opps if o.get("validation_status","new") == "new")

    if user_role in ("super_admin","admin","commercial_manager"):
        if immediate:
            recs.append({
                "type":        "action",
                "title":       f"📞 {len(immediate)} immediate opportunities need owner assignment",
                "description": f"Top: {immediate[0].get('product_line','')} on {immediate[0].get('rig','')} — ${immediate[0].get('estimated_value',0):,.0f}",
                "action_link": "radar",
            })
        if high_conf:
            recs.append({
                "type":        "review",
                "title":       f"✓ {len(high_conf)} high-confidence opportunities need validation",
                "description": "Accept or reject to improve pipeline accuracy.",
                "action_link": "radar",
            })

    if user_role in ("super_admin","admin"):
        if unvalidated_count > 10:
            recs.append({
                "type":        "warning",
                "title":       f"⚠ {unvalidated_count} opportunities unreviewed",
                "description": "Large backlog reduces pipeline credibility. Use bulk validation.",
                "action_link": "evidence",
            })

    if user_role in ("super_admin","admin","commercial_manager","product_line_manager"):
        no_comp = [o for o in immediate if not o.get("competitor")]
        if no_comp:
            recs.append({
                "type":        "opportunity",
                "title":       f"🎯 {len(no_comp)} uncontested immediate opportunities",
                "description": "No competitor detected — highest win probability. Act first.",
                "action_link": "radar",
            })

    if not recs:
        recs.append({
            "type":        "info",
            "title":       "Pipeline looks healthy",
            "description": f"{len(opps)} opportunities tracked. Review the Daily Brief for priorities.",
            "action_link": "brief",
        })

    return recs[:5]
