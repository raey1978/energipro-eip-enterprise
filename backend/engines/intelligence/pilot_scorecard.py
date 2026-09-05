"""
EIP v6.3A — Pilot Success Scorecard & Commercial Value Validation

Tracks MEASURED pilot results separately from ESTIMATED potential.
Never conflates potential revenue with awarded revenue.

Categories (strictly separated):
  potential_revenue    — estimated from DDR intelligence (what MIGHT be won)
  weighted_revenue     — potential × win_probability
  validated_influence  — confirmed by BD that insight helped → actual action
  awarded_revenue      — confirmed contract won (manually recorded)

Pilot metrics:
  All thresholds configurable via settings table.
  Shows "not yet measured" for any metric with no real data.
"""
from __future__ import annotations
import uuid, datetime, json
from core.database import get_db


DEFAULT_THRESHOLDS = {
    "min_opportunity_acceptance_rate": 0.30,   # 30% of detected opps accepted
    "min_change_detection_precision":  0.70,   # 70% of detected changes are real
    "min_entity_resolution_rate":      0.90,   # 90% of entities correctly merged
    "min_data_freshness_days":         7,       # Data must be ≤7 days old
    "min_intelligence_quality_score":  60,      # Quality score ≥60/100
    "target_hours_saved_per_week":     5,       # Target BD time saved/week
    "target_opps_discovered_per_week": 3,       # Target new opps/week
}


def init_pilot_tables():
    conn = get_db()
    conn.executescript("""
    -- Commercial value capture — records when an intelligence insight created real value
    CREATE TABLE IF NOT EXISTS commercial_value_events (
        id                  TEXT PRIMARY KEY,
        recorded_at         TEXT NOT NULL,
        recorded_by         TEXT DEFAULT '',

        -- Link to insight
        insight_type        TEXT DEFAULT '',   -- opportunity|change_event|campaign|trend
        insight_id          TEXT DEFAULT '',
        governance_record_id TEXT DEFAULT '',

        -- Type of value created
        value_type          TEXT NOT NULL,     -- see VALUE_TYPES below
        value_description   TEXT DEFAULT '',

        -- Revenue categories (kept STRICTLY SEPARATE)
        potential_revenue   REAL DEFAULT 0,    -- original DDR estimate
        weighted_revenue    REAL DEFAULT 0,    -- potential × win_prob
        validated_influence REAL DEFAULT 0,    -- confirmed insight led to action
        awarded_revenue     REAL DEFAULT 0,    -- actual contract won (confirmed)

        -- BD value metrics
        hours_saved         REAL DEFAULT 0,    -- estimated BD hours saved
        days_earlier        INTEGER DEFAULT 0, -- how many days earlier vs manual

        notes               TEXT DEFAULT ''
    );

    -- Pilot scorecard snapshots — one per week
    CREATE TABLE IF NOT EXISTS pilot_scorecard_snapshots (
        id              TEXT PRIMARY KEY,
        snapshot_date   TEXT NOT NULL,
        snapshot_week   TEXT NOT NULL,   -- YYYY-WNN

        -- Measured (real data)
        opportunities_discovered    INTEGER DEFAULT 0,
        early_warnings_generated    INTEGER DEFAULT 0,
        competitor_movements        INTEGER DEFAULT 0,
        campaigns_identified        INTEGER DEFAULT 0,
        bd_actions_recommended      INTEGER DEFAULT 0,
        bd_actions_completed        INTEGER DEFAULT 0,
        hours_saved_estimated       REAL DEFAULT 0,
        potential_revenue_identified REAL DEFAULT 0,
        validated_influence         REAL DEFAULT 0,
        awarded_revenue             REAL DEFAULT 0,

        -- Quality metrics
        opportunity_acceptance_rate REAL DEFAULT 0,
        change_detection_precision  REAL DEFAULT 0,  -- -1 = not measured
        entity_resolution_rate      REAL DEFAULT 0,
        intelligence_quality_score  INTEGER DEFAULT 0,

        -- Status
        has_real_data   INTEGER DEFAULT 0,    -- 0 = all zeroes / not measured
        notes           TEXT DEFAULT ''
    );

    CREATE INDEX IF NOT EXISTS idx_cve_type   ON commercial_value_events(value_type);
    CREATE INDEX IF NOT EXISTS idx_cve_insight ON commercial_value_events(insight_id);
    CREATE INDEX IF NOT EXISTS idx_pss_week    ON pilot_scorecard_snapshots(snapshot_week);
    """)
    conn.commit()
    conn.close()


VALUE_TYPES = [
    "identified_unknown_opportunity",
    "identified_opportunity_earlier",
    "prioritized_customer_visit",
    "prepared_equipment_earlier",
    "detected_competitor_movement",
    "discovered_campaign",
    "avoided_wasted_bd_effort",
    "improved_proposal_timing",
    "contract_awarded",
    "other",
]


def record_commercial_value(data: dict, user_email: str = "") -> dict:
    """Record that an intelligence insight created measurable commercial value."""
    vt = data.get("value_type","other")
    if vt not in VALUE_TYPES:
        vt = "other"

    conn = get_db()
    vid  = str(uuid.uuid4())
    ts   = datetime.datetime.utcnow().isoformat()
    conn.execute(
        """INSERT INTO commercial_value_events
           (id,recorded_at,recorded_by,insight_type,insight_id,governance_record_id,
            value_type,value_description,potential_revenue,weighted_revenue,
            validated_influence,awarded_revenue,hours_saved,days_earlier,notes)
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (vid, ts, user_email,
         data.get("insight_type",""), data.get("insight_id",""), data.get("governance_record_id",""),
         vt, data.get("value_description",""),
         data.get("potential_revenue",0), data.get("weighted_revenue",0),
         data.get("validated_influence",0), data.get("awarded_revenue",0),
         data.get("hours_saved",0), data.get("days_earlier",0),
         data.get("notes",""))
    )
    conn.commit(); conn.close()
    return {"event_id": vid, "value_type": vt}


def get_commercial_value_summary() -> dict:
    """Aggregate commercial value by category — keeping revenue types SEPARATE."""
    conn = get_db()
    rows = conn.execute("SELECT * FROM commercial_value_events").fetchall()
    validations = conn.execute("SELECT * FROM change_validations").fetchall()
    conn.close()

    events = [dict(r) for r in rows]
    if not events:
        return {
            "status": "not_yet_measured",
            "message": "No commercial value events recorded yet.",
            "instructions": "Record value events from the Pilot Scorecard when insights lead to BD actions.",
            "revenue_disclaimer": "Potential revenue ≠ Awarded revenue. These are tracked separately.",
        }

    by_type = {}
    for vt in VALUE_TYPES:
        by_type[vt] = sum(1 for e in events if e.get("value_type") == vt)

    return {
        "status": "measured",
        "total_events": len(events),
        "by_value_type": by_type,

        # Revenue categories — STRICTLY SEPARATED
        "revenue_categories": {
            "potential_revenue": {
                "value":       sum(e.get("potential_revenue",0) for e in events),
                "definition":  "Estimated from DDR intelligence. Has not been won or confirmed.",
                "warning":     "This is NOT awarded revenue."
            },
            "weighted_revenue": {
                "value":       sum(e.get("weighted_revenue",0) for e in events),
                "definition":  "Potential revenue × win probability. Statistical estimate only.",
                "warning":     "This is NOT awarded revenue."
            },
            "validated_influence": {
                "value":       sum(e.get("validated_influence",0) for e in events),
                "definition":  "Confirmed by BD that this insight directly influenced a commercial action.",
                "warning":     "Influence does not guarantee contract award."
            },
            "awarded_revenue": {
                "value":       sum(e.get("awarded_revenue",0) for e in events),
                "definition":  "Actual contract value confirmed won. Only includes verified awards.",
                "warning":     "Record here ONLY when contract is signed and confirmed."
            },
        },

        "bd_metrics": {
            "total_hours_saved":  sum(e.get("hours_saved",0) for e in events),
            "avg_days_earlier":   round(sum(e.get("days_earlier",0) for e in events) / max(len(events),1), 1),
            "opportunities_influenced": len(set(e.get("insight_id") for e in events if e.get("insight_id"))),
        },
    }


def build_pilot_scorecard(thresholds: dict = None) -> dict:
    """
    Build the full pilot success scorecard from real measured data.
    Shows 'not_yet_measured' for any metric without real data.
    Never fabricates numbers.
    """
    from engines.intelligence.temporal_engine import calculate_change_detection_metrics
    from engines.intelligence.entity_resolution import get_entity_summary
    from engines.intelligence.governance_layer  import compute_intelligence_quality

    th   = {**DEFAULT_THRESHOLDS, **(thresholds or {})}
    conn = get_db()

    # Real data counts
    total_opps     = conn.execute("SELECT COUNT(*) FROM opportunities").fetchone()[0]
    accepted_opps  = conn.execute("SELECT COUNT(*) FROM opportunities WHERE validation_status IN ('accepted','converted')").fetchone()[0]
    rejected_opps  = conn.execute("SELECT COUNT(*) FROM opportunities WHERE validation_status='rejected'").fetchone()[0]
    total_actions  = conn.execute("SELECT COUNT(*) FROM decision_journal").fetchone()[0]
    completed_dec  = conn.execute("SELECT COUNT(*) FROM decision_journal WHERE status='completed'").fetchone()[0]
    campaign_count = conn.execute("SELECT COUNT(*) FROM campaigns").fetchone()[0]
    change_count   = conn.execute("SELECT COUNT(*) FROM change_events").fetchone()[0]
    pipeline_items = conn.execute("SELECT COUNT(*) FROM pipeline_items").fetchone()[0]
    conn.close()

    entity_summary = get_entity_summary()
    quality        = compute_intelligence_quality()
    change_metrics = calculate_change_detection_metrics()
    value_summary  = get_commercial_value_summary()

    # Entity resolution rate
    total_masters = sum(v.get("masters",0) for v in entity_summary.get("by_type",{}).values())
    review_pending = entity_summary.get("review_pending", 0)
    if total_masters > 0:
        entity_res_rate = round(1 - review_pending / max(total_masters,1), 3)
    else:
        entity_res_rate = None  # Not yet measurable

    # Opportunity acceptance rate
    reviewed = accepted_opps + rejected_opps
    opp_acc_rate = round(accepted_opps / max(reviewed,1), 3) if reviewed > 0 else None

    # Change precision
    cp = change_metrics.get("precision") if change_metrics.get("status") == "measured" else None

    def _status(value, threshold, higher_is_better=True):
        if value is None: return "not_yet_measured"
        meets = (value >= threshold) if higher_is_better else (value <= threshold)
        return "pass" if meets else "fail"

    def _fmt(value, pct=False):
        if value is None: return "Not yet measured"
        if pct: return f"{round(value*100,1)}%"
        return str(value)

    metrics = {
        "data_processing_reliability": {
            "measured":   True,
            "value":      total_opps,
            "label":      f"{total_opps} opportunities extracted",
            "status":     "pass" if total_opps > 0 else "fail",
        },
        "entity_resolution_accuracy": {
            "measured":   entity_res_rate is not None,
            "value":      entity_res_rate,
            "threshold":  th["min_entity_resolution_rate"],
            "label":      _fmt(entity_res_rate, pct=True),
            "status":     _status(entity_res_rate, th["min_entity_resolution_rate"]),
            "detail":     f"{total_masters} master entities, {review_pending} pending review",
        },
        "change_detection_precision": {
            "measured":   cp is not None,
            "value":      cp,
            "threshold":  th["min_change_detection_precision"],
            "label":      _fmt(cp, pct=True) if cp else "Not yet measured — validate events first",
            "status":     _status(cp, th["min_change_detection_precision"]),
        },
        "opportunity_acceptance_rate": {
            "measured":   opp_acc_rate is not None,
            "value":      opp_acc_rate,
            "threshold":  th["min_opportunity_acceptance_rate"],
            "label":      _fmt(opp_acc_rate, pct=True),
            "status":     _status(opp_acc_rate, th["min_opportunity_acceptance_rate"]),
            "detail":     f"{accepted_opps} accepted, {rejected_opps} rejected of {reviewed} reviewed",
        },
        "recommendation_adoption_rate": {
            "measured":   total_actions > 0,
            "value":      round(completed_dec/max(total_actions,1), 3) if total_actions else None,
            "label":      f"{completed_dec}/{total_actions} decisions completed" if total_actions else "Not yet measured",
            "status":     "pass" if completed_dec > 0 else ("not_yet_measured" if total_actions == 0 else "fail"),
        },
        "intelligence_quality_score": {
            "measured":   True,
            "value":      quality.get("composite_score",0),
            "threshold":  th["min_intelligence_quality_score"],
            "label":      f"{quality.get('composite_score',0)}/100 ({quality.get('grade_label','')})",
            "status":     _status(quality.get("composite_score",0), th["min_intelligence_quality_score"]),
        },
        "campaigns_identified": {
            "measured":   True,
            "value":      campaign_count,
            "label":      f"{campaign_count} campaigns detected",
            "status":     "pass" if campaign_count > 0 else "not_yet_measured",
        },
        "commercial_actions_generated": {
            "measured":   True,
            "value":      total_actions,
            "label":      f"{total_actions} journal entries, {pipeline_items} pipeline items",
            "status":     "pass" if total_actions > 0 else "not_yet_measured",
        },
        "duplicate_signal_rate": {
            "measured":   change_metrics.get("status") == "measured",
            "value":      change_metrics.get("duplicate_rate"),
            "label":      _fmt(change_metrics.get("duplicate_rate"), pct=True) if change_metrics.get("status")=="measured" else "Not yet measured",
            "status":     _status(change_metrics.get("duplicate_rate"), 0.20, higher_is_better=False) if change_metrics.get("status")=="measured" else "not_yet_measured",
        },
    }

    measured = sum(1 for m in metrics.values() if m.get("measured"))
    passing  = sum(1 for m in metrics.values() if m.get("status") == "pass")
    total_m  = len(metrics)

    return {
        "generated_at":     datetime.datetime.utcnow().isoformat(),
        "thresholds_used":  th,
        "metrics":          metrics,
        "summary": {
            "total_metrics":      total_m,
            "measured":           measured,
            "passing":            passing,
            "not_yet_measured":   total_m - measured,
            "pilot_readiness":    "PILOT READY" if passing >= 5 and measured >= 7 else
                                  "PARTIALLY READY" if passing >= 3 else "NOT YET READY",
        },
        "commercial_value":    value_summary,
        "change_metrics":      change_metrics,
        "entity_summary":      entity_summary,
        "revenue_disclaimer":  (
            "IMPORTANT: 'Potential Revenue' and 'Awarded Revenue' are tracked separately. "
            "Never report potential revenue as awarded. This platform shows estimated pipeline only."
        ),
    }
