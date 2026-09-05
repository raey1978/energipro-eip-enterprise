"""
EIP v6.1 — AI Trust Layer
The quality gate between all intelligence engines and the user interface.

Design principle: WRAP existing engine outputs. Never rebuild engines.

Every insight receives a trust_envelope{} containing:
  - evidence_strength:        VERY HIGH / HIGH / MODERATE / LOW / VERY LOW
  - trust_score:              0-100 (composite)
  - source_count:             number of DDRs supporting this insight
  - data_freshness_days:      days since most recent supporting report
  - data_freshness_label:     LIVE / RECENT / STALE / OUTDATED
  - assumption_quality:       CONFIRMED / INFERRED / ESTIMATED / ASSUMED
  - observation_type:         OBSERVED_FACT / DERIVED_METRIC / AI_INFERENCE / ASSUMPTION / FORECAST
  - contradictions:           list of conflicting signals (if any)
  - challenge_points:         list of reasons to question this insight
  - alternative_hypotheses:   list of alternative interpretations
  - limitations:              explicit statements of what this insight cannot claim
  - audit_trail:              {engine, timestamp, method, data_sources_used}

TRANSPARENCY RULES (enforced at this layer):
  1. Observed Facts: directly extracted from DDR text — highest trust
  2. Derived Metrics: calculated from facts (counts, sums, averages) — high trust
  3. AI Inferences: pattern recognition across facts — moderate trust
  4. Assumptions: domain knowledge applied — stated explicitly
  5. Forecasts: projections with confidence intervals — always labelled as estimates
"""
from __future__ import annotations
import datetime, json
from typing import Optional
from core.database import get_db

# ── Evidence Strength Thresholds ──────────────────────────────────────────────
EVIDENCE_STRENGTH_THRESHOLDS = [
    (85, "VERY HIGH", "⬛⬛⬛⬛⬛", "Multiple independent DDR reports confirm this. Very high confidence."),
    (70, "HIGH",      "⬛⬛⬛⬛⬜", "Consistent evidence from DDR source text. High confidence."),
    (55, "MODERATE",  "⬛⬛⬛⬜⬜", "Reasonable evidence base. Verify before committing significant resources."),
    (40, "LOW",       "⬛⬛⬜⬜⬜", "Limited evidence. Treat as indicative, not confirmed."),
    (0,  "VERY LOW",  "⬛⬜⬜⬜⬜", "Insufficient evidence. Do not act on this alone."),
]

# ── Observation type labels ───────────────────────────────────────────────────
OBS_TYPE_META = {
    "OBSERVED_FACT":   {"label": "Observed Fact",   "color": "green",  "icon": "✓",
                        "description": "Directly extracted from DDR text. This is what the report says."},
    "DERIVED_METRIC":  {"label": "Derived Metric",  "color": "cyan",   "icon": "∑",
                        "description": "Calculated from observed facts using defined formulas. Transparent arithmetic."},
    "AI_INFERENCE":    {"label": "AI Inference",    "color": "accent", "icon": "◈",
                        "description": "Pattern detected by the intelligence engine across multiple data points."},
    "ASSUMPTION":      {"label": "Assumption",      "color": "amber",  "icon": "~",
                        "description": "Domain knowledge applied. Industry standard assumption — stated explicitly."},
    "FORECAST":        {"label": "Estimate",        "color": "purple", "icon": "◇",
                        "description": "Forward-looking estimate with stated confidence interval. Not a guarantee."},
}

# ── Data freshness ────────────────────────────────────────────────────────────
def _freshness(days: Optional[float]) -> tuple:
    if days is None: return ("UNKNOWN", "var(--muted2)")
    if days <= 1:   return ("LIVE",     "var(--green)")
    if days <= 7:   return ("RECENT",   "var(--cyan)")
    if days <= 30:  return ("CURRENT",  "var(--amber)")
    if days <= 90:  return ("STALE",    "var(--amber)")
    return ("OUTDATED", "var(--red)")


def get_evidence_strength(trust_score: int) -> dict:
    """Convert numeric trust score to labelled Evidence Strength."""
    for threshold, label, bars, desc in EVIDENCE_STRENGTH_THRESHOLDS:
        if trust_score >= threshold:
            return {"label": label, "bars": bars, "description": desc, "score": trust_score}
    return {"label": "VERY LOW", "bars": "⬛⬜⬜⬜⬜", "description": "Insufficient evidence.", "score": trust_score}


# ── Core trust envelope calculator ───────────────────────────────────────────

def calculate_trust_envelope(
    insight_type: str,
    data: dict,
    context: dict = None,
) -> dict:
    """
    Calculate the full trust envelope for any insight type.
    
    insight_type: opportunity | change_event | trend_signal | campaign |
                  strategic_insight | revenue | qualification
    data:         the insight dict from the originating engine
    context:      optional extra DB context (upload history, etc.)
    """
    ctx       = context or {}
    ts        = datetime.datetime.utcnow().isoformat()

    # ── Step 1: Base trust score from existing confidence field ───────────────
    raw_conf  = data.get("confidence", data.get("qualification_score",
                data.get("revenue_confidence", data.get("trust_score", 60))))
    # Normalise — some are 0-100, some are fractions
    if isinstance(raw_conf, float) and raw_conf <= 1.0:
        raw_conf = int(raw_conf * 100)
    base_score = min(100, max(0, int(raw_conf)))

    # ── Step 2: Source count modifier ────────────────────────────────────────
    source_count = _count_sources(insight_type, data, ctx)
    source_bonus = min(20, source_count * 5)  # Max +20 for 4+ sources

    # ── Step 3: Data freshness ────────────────────────────────────────────────
    freshness_days = _calculate_freshness_days(data, ctx)
    freshness_label, freshness_color = _freshness(freshness_days)
    freshness_penalty = 0
    if freshness_days and freshness_days > 30: freshness_penalty = 15
    elif freshness_days and freshness_days > 90: freshness_penalty = 30

    # ── Step 4: Compute final trust score ────────────────────────────────────
    trust_score = min(100, max(0, base_score + source_bonus - freshness_penalty))

    # ── Step 5: Determine observation type ───────────────────────────────────
    obs_type = _determine_observation_type(insight_type, data)

    # ── Step 6: Evidence strength ─────────────────────────────────────────────
    ev_strength = get_evidence_strength(trust_score)

    # ── Step 7: Contradictions ────────────────────────────────────────────────
    contradictions = _find_contradictions(insight_type, data, ctx)

    # ── Step 8: Challenge points (honest weaknesses) ─────────────────────────
    challenge_points = _build_challenge_points(insight_type, data, trust_score,
                                                source_count, freshness_days)

    # ── Step 9: Alternative hypotheses ───────────────────────────────────────
    alternatives = _build_alternatives(insight_type, data)

    # ── Step 10: Limitations (what this insight CANNOT claim) ─────────────────
    limitations = _build_limitations(insight_type, data, source_count)

    # ── Step 11: Audit trail ──────────────────────────────────────────────────
    audit_trail = {
        "engine":              insight_type,
        "calculated_at":       ts,
        "base_confidence":     base_score,
        "source_count_bonus":  source_bonus,
        "freshness_penalty":   freshness_penalty,
        "final_trust_score":   trust_score,
        "method":              "EIP Trust Layer v6.1 — composite scoring",
        "data_sources_used":   _list_sources(insight_type, data),
    }

    return {
        # Core scores
        "trust_score":           trust_score,
        "evidence_strength":     ev_strength,
        "observation_type":      obs_type,
        "obs_type_meta":         OBS_TYPE_META.get(obs_type, {}),

        # Source quality
        "source_count":          source_count,
        "data_freshness_days":   freshness_days,
        "data_freshness_label":  freshness_label,
        "data_freshness_color":  freshness_color,

        # Transparency
        "assumption_quality":    _assumption_quality(insight_type, data),
        "contradictions":        contradictions,
        "challenge_points":      challenge_points,
        "alternative_hypotheses":alternatives,
        "limitations":           limitations,

        # Audit
        "audit_trail":           audit_trail,

        # Quick UI indicators
        "is_high_trust":         trust_score >= 70,
        "needs_review":          trust_score < 50 or bool(contradictions),
        "is_forecast":           obs_type == "FORECAST",
        "is_assumption":         obs_type == "ASSUMPTION",
    }


# ── Helper functions ──────────────────────────────────────────────────────────

def _count_sources(insight_type: str, data: dict, ctx: dict) -> int:
    """Count number of independent DDR reports supporting this insight."""
    if insight_type == "opportunity":
        # Single DDR per opportunity — but high-evidence sections count more
        section = data.get("evidence_section","")
        return 2 if section in ("Foreman Remarks","Next 24h Plan") else 1

    elif insight_type == "trend_signal":
        return data.get("data_points", 1)

    elif insight_type == "campaign":
        try:
            ids = json.loads(data.get("evidence_upload_ids","[]") or "[]")
        except: ids = []
        return max(1, len(ids))

    elif insight_type == "change_event":
        return 2 if data.get("prev_upload_id") else 1

    elif insight_type == "strategic_insight":
        try:
            ev = json.loads(data.get("evidence","[]") or "[]")
        except: ev = []
        return max(1, len(ev))

    elif insight_type in ("qualification","revenue"):
        # These are derived from a single opportunity
        return 1 + (1 if data.get("validated_by") else 0)

    return 1


def _calculate_freshness_days(data: dict, ctx: dict) -> Optional[float]:
    """Calculate how many days old the most recent supporting data is."""
    ts_fields = ["detected_at","calculated_at","created_at","period_end","snapshot_date","generated_at"]
    for field in ts_fields:
        val = data.get(field,"") or ctx.get(field,"")
        if val:
            try:
                dt = datetime.datetime.fromisoformat(val[:19])
                delta = (datetime.datetime.utcnow() - dt).total_seconds() / 86400
                return round(delta, 1)
            except Exception:
                continue
    return None


def _determine_observation_type(insight_type: str, data: dict) -> str:
    if insight_type == "opportunity":
        return "OBSERVED_FACT"  # Extracted directly from DDR text
    elif insight_type in ("qualification","revenue"):
        return "DERIVED_METRIC"  # Calculated from facts
    elif insight_type == "change_event":
        change_type = data.get("change_type","")
        if change_type in ("rig_mobilised","new_field","competitor_entered"):
            return "OBSERVED_FACT"
        return "AI_INFERENCE"
    elif insight_type == "trend_signal":
        dp = data.get("data_points",1)
        return "DERIVED_METRIC" if dp >= 3 else "AI_INFERENCE"
    elif insight_type == "campaign":
        return "AI_INFERENCE"
    elif insight_type == "strategic_insight":
        return "AI_INFERENCE"
    elif insight_type == "forecast":
        return "FORECAST"
    return "AI_INFERENCE"


def _assumption_quality(insight_type: str, data: dict) -> str:
    if insight_type == "opportunity":
        val_status = data.get("validation_status","new")
        return "CONFIRMED" if val_status in ("accepted","converted") else \
               "INFERRED" if val_status == "new" else "ESTIMATED"
    elif insight_type == "revenue":
        return "ESTIMATED"  # Revenue estimates are always assumptions
    elif insight_type == "trend_signal":
        dp = data.get("data_points",1)
        return "INFERRED" if dp >= 3 else "ASSUMED"
    elif insight_type == "forecast":
        return "ASSUMED"
    return "INFERRED"


def _find_contradictions(insight_type: str, data: dict, ctx: dict) -> list:
    contradictions = []
    if insight_type == "change_event":
        if data.get("confidence",100) < 70:
            contradictions.append("Low confidence score suggests this change may not be definitive")
        if not data.get("prev_upload_id"):
            contradictions.append("No previous report to compare against — this may be first detection only")

    elif insight_type == "trend_signal":
        dp = data.get("data_points",1)
        if dp < 3:
            contradictions.append(f"Only {dp} data point(s) — trend direction not yet statistically reliable")
        if abs(data.get("magnitude",0)) < 20:
            contradictions.append("Magnitude is small — within normal variation range")

    elif insight_type == "opportunity":
        conf = data.get("confidence",0)
        if conf < 65:
            contradictions.append(f"Detection confidence is {conf}% — below recommended threshold")
        if data.get("validation_status") == "rejected":
            contradictions.append("This opportunity was rejected by a reviewer")
        if not data.get("evidence_text"):
            contradictions.append("No supporting evidence text extracted from DDR")

    elif insight_type == "campaign":
        if data.get("confidence",0) < 60:
            contradictions.append("Campaign confidence is low — may be coincidental rig co-location")
        rigs = []
        try: rigs = json.loads(data.get("rigs","[]") or "[]")
        except: pass
        if len(rigs) < 2:
            contradictions.append("Only one rig detected — a single-rig campaign may be a standalone operation")

    return contradictions


def _build_challenge_points(insight_type: str, data: dict, trust_score: int,
                              source_count: int, freshness_days: Optional[float]) -> list:
    points = []

    if source_count == 1:
        points.append(f"Based on a single DDR report — a second report would increase confidence significantly")
    if freshness_days and freshness_days > 7:
        points.append(f"Data is {freshness_days:.0f} days old — market conditions may have changed")
    if trust_score < 60:
        points.append("Trust score below 60 — treat as indicative intelligence, not confirmed fact")

    if insight_type == "opportunity":
        if not data.get("competitor"):
            points.append("No competitor detected — could indicate primary approach OR our intelligence coverage is incomplete")
        if data.get("urgency") == "future":
            points.append("Future timing means the operation is not yet confirmed — probability remains speculative")
        if not data.get("well") or not data.get("rig"):
            points.append("Rig/well location incomplete — verify before contacting customer")

    elif insight_type == "trend_signal":
        points.append("Trends are statistical — individual DDRs may not represent the full market")
        points.append("Saudi Aramco activity follows budget cycles — verify against Aramco planning calendar")

    elif insight_type == "change_event" and data.get("change_type") == "competitor_entered":
        points.append("Competitor detection relies on SC abbreviation matching — name variations may cause misclassification")
        points.append("Verify competitor presence directly with the rig site before acting on displacement strategy")

    elif insight_type == "campaign":
        points.append("Campaign grouping is based on field co-location — rigs may have independent scopes")
        points.append("Estimated duration uses historical industry averages — actual duration may differ significantly")

    elif insight_type == "revenue":
        points.append("Revenue estimates use Saudi Aramco unit-rate benchmarks — actual contract terms will vary")
        points.append("Win probability is statistical — individual opportunities may deviate significantly")

    return points


def _build_alternatives(insight_type: str, data: dict) -> list:
    alternatives = []

    if insight_type == "trend_signal":
        direction = data.get("direction","stable")
        dim       = data.get("dimension_value","")
        mag       = abs(data.get("magnitude",0))

        if direction == "growing":
            alternatives = [
                {"hypothesis": f"Primary: Market genuinely increasing demand for {dim}",
                 "probability": "Most likely",
                 "evidence_for": f"Demand signal detected in {data.get('data_points',1)} reports",
                 "evidence_against": "Cannot confirm without operator budget confirmation"},
                {"hypothesis": "Alternative: Aramco activity cycle coincidence — not structural growth",
                 "probability": "Possible",
                 "evidence_for": "Aramco drilling follows 6-month programme cycles",
                 "evidence_against": f"Growth trend of {mag:.0f}% exceeds typical seasonal variation"},
                {"hypothesis": "Alternative: EnergiPro is detecting more DDRs — sample bias",
                 "probability": "Low if source count ≥3",
                 "evidence_for": "More uploads = more detections even without real growth",
                 "evidence_against": f"Growth calculated relative to upload volume, not absolute"},
            ]
        elif direction == "declining":
            alternatives = [
                {"hypothesis": f"Primary: {dim} demand genuinely declining in this market",
                 "probability": "Most likely",
                 "evidence_for": f"Consistent decline across {data.get('data_points',1)} reports",
                 "evidence_against": "Could be seasonal or programme-end"},
                {"hypothesis": "Alternative: Completion of a specific drilling campaign — temporary dip",
                 "probability": "Plausible",
                 "evidence_for": "Campaign completion typically causes sharp service demand drops",
                 "evidence_against": "Would recover when next campaign starts"},
            ]

    elif insight_type == "change_event":
        change_type = data.get("change_type","")
        if change_type == "competitor_entered":
            comp = data.get("affected_comp","")
            alternatives = [
                {"hypothesis": f"Primary: {comp} is actively providing services on these rigs",
                 "probability": "High",
                 "evidence_for": "SC abbreviation detected in DDR service company section",
                 "evidence_against": ""},
                {"hypothesis": f"Alternative: {comp} is on standby or mobilising, not yet operational",
                 "probability": "Moderate",
                 "evidence_for": "DDR sometimes lists standby contractors in service companies section",
                 "evidence_against": "Would still represent competitive presence"},
                {"hypothesis": f"Alternative: DDR abbreviation mismatch — different company with similar code",
                 "probability": "Low (our database has 225 verified codes)",
                 "evidence_for": "SC code overlap can occur between companies",
                 "evidence_against": "EnergiPro database is cross-referenced against known Aramco approved vendors"},
            ]
        elif change_type == "rig_mobilised":
            rig = data.get("affected_rig","")
            alternatives = [
                {"hypothesis": f"Primary: {rig} is newly mobilised to this location",
                 "probability": "High",
                 "evidence_for": "Rig not detected in any previous DDR in this series",
                 "evidence_against": ""},
                {"hypothesis": f"Alternative: {rig} was always active — we simply did not upload the earlier DDR",
                 "probability": "Possible if report series is incomplete",
                 "evidence_for": "First detection ≠ first mobilisation",
                 "evidence_against": "Strengthened if multiple rigs entered simultaneously"},
            ]

    elif insight_type == "campaign":
        fields = []
        try: fields = json.loads(data.get("fields","[]") or "[]")
        except: pass
        field = fields[0] if fields else "this field"
        alternatives = [
            {"hypothesis": f"Primary: Coordinated multi-rig campaign in {field}",
             "probability": "High if rigs ≥3",
             "evidence_for": "Multiple rigs active simultaneously in same field",
             "evidence_against": ""},
            {"hypothesis": "Alternative: Independent rig operations that happen to co-locate",
             "probability": "Possible for 2 rigs",
             "evidence_for": "Aramco assigns multiple rigs to large fields independently",
             "evidence_against": "Campaign services (completion, testing) signal coordination"},
        ]

    return alternatives


def _build_limitations(insight_type: str, data: dict, source_count: int) -> list:
    base = [
        "This intelligence is derived from DDR report text and does not represent confirmed contract awards.",
        "EnergiPro does not have access to Saudi Aramco's internal planning systems or budget data.",
    ]

    if source_count == 1:
        base.append("This insight is based on a single report. A single DDR captures a 24-hour window only.")

    if insight_type == "revenue":
        base.append("Revenue estimates use unit-rate benchmarks. Actual contract value depends on scope, duration, and negotiation.")
        base.append("Win probability is derived from industry averages — EnergiPro's specific historical data is not yet incorporated.")

    elif insight_type == "trend_signal":
        dp = data.get("data_points",1)
        base.append(f"Trend calculated from {dp} report(s). Statistical reliability increases significantly above 5 reports.")
        base.append("Trends represent the period covered by uploaded DDRs only — not the full market.")

    elif insight_type == "forecast":
        base.append("This is a forward-looking estimate. It is NOT a sales prediction or guarantee.")
        base.append("Forecast confidence interval widens significantly beyond 30 days.")

    elif insight_type == "campaign":
        base.append("Campaign detection uses field co-location and service pattern analysis — not operator programme documents.")

    return base


def _list_sources(insight_type: str, data: dict) -> list:
    sources = []
    if data.get("source_file"):
        sources.append(f"DDR: {data['source_file']} (p.{data.get('source_page','?')})")
    if data.get("upload_id"):
        sources.append(f"Upload ID: {data['upload_id'][:8]}…")
    if data.get("evidence_upload_ids"):
        try:
            ids = json.loads(data["evidence_upload_ids"])
            sources.extend([f"Upload: {uid[:8]}…" for uid in ids[:3]])
        except: pass
    if data.get("evidence_section"):
        sources.append(f"Section: {data['evidence_section']}")
    if not sources:
        sources.append("Derived from intelligence database")
    return sources


# ── Trust Score DB storage ────────────────────────────────────────────────────

def init_trust_tables():
    """Create trust score storage tables."""
    conn = get_db()
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS trust_scores (
        id              TEXT PRIMARY KEY,
        insight_type    TEXT NOT NULL,
        insight_id      TEXT NOT NULL,
        calculated_at   TEXT NOT NULL,
        trust_score     INTEGER NOT NULL,
        evidence_strength TEXT NOT NULL,
        observation_type TEXT NOT NULL,
        source_count    INTEGER DEFAULT 1,
        freshness_days  REAL,
        freshness_label TEXT DEFAULT 'UNKNOWN',
        assumption_quality TEXT DEFAULT 'INFERRED',
        has_contradictions INTEGER DEFAULT 0,
        needs_review    INTEGER DEFAULT 0,
        challenge_count INTEGER DEFAULT 0,
        full_envelope   TEXT DEFAULT '{}'
    );
    CREATE INDEX IF NOT EXISTS idx_trust_insight ON trust_scores(insight_type, insight_id);
    CREATE INDEX IF NOT EXISTS idx_trust_score   ON trust_scores(trust_score);
    CREATE INDEX IF NOT EXISTS idx_trust_needs_review ON trust_scores(needs_review);
    """)
    conn.commit()
    conn.close()


def store_trust_score(insight_type: str, insight_id: str, envelope: dict):
    """Persist a trust envelope to the database."""
    import uuid as _uuid
    conn = get_db()
    conn.execute(
        """INSERT OR REPLACE INTO trust_scores
           (id,insight_type,insight_id,calculated_at,trust_score,evidence_strength,
            observation_type,source_count,freshness_days,freshness_label,
            assumption_quality,has_contradictions,needs_review,challenge_count,full_envelope)
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (str(_uuid.uuid4()), insight_type, insight_id,
         envelope.get("audit_trail",{}).get("calculated_at",""),
         envelope["trust_score"],
         envelope["evidence_strength"]["label"],
         envelope["observation_type"],
         envelope["source_count"],
         envelope.get("data_freshness_days"),
         envelope.get("data_freshness_label","UNKNOWN"),
         envelope.get("assumption_quality","INFERRED"),
         1 if envelope.get("contradictions") else 0,
         1 if envelope.get("needs_review") else 0,
         len(envelope.get("challenge_points",[])),
         json.dumps({k: v for k, v in envelope.items()
                     if k not in ("audit_trail",) and not isinstance(v, dict)}))
    )
    conn.commit()
    conn.close()


def get_platform_trust_summary() -> dict:
    """Overall platform trust dashboard metrics."""
    conn = get_db()
    rows = conn.execute("SELECT * FROM trust_scores ORDER BY calculated_at DESC LIMIT 500").fetchall()
    conn.close()

    if not rows:
        return {"status": "no_data"}

    scores = [dict(r) for r in rows]
    total  = len(scores)

    by_strength = {}
    for s in scores:
        es = s.get("evidence_strength","UNKNOWN")
        by_strength[es] = by_strength.get(es,0) + 1

    return {
        "total_insights":          total,
        "avg_trust_score":         round(sum(s["trust_score"] for s in scores)/max(total,1)),
        "high_trust_count":        sum(1 for s in scores if s["trust_score"] >= 70),
        "needs_review_count":      sum(1 for s in scores if s["needs_review"]),
        "has_contradictions_count":sum(1 for s in scores if s["has_contradictions"]),
        "by_evidence_strength":    by_strength,
        "by_type":                 {t: sum(1 for s in scores if s["insight_type"]==t)
                                    for t in set(s["insight_type"] for s in scores)},
        "freshness_breakdown": {
            "live":    sum(1 for s in scores if s.get("freshness_label")=="LIVE"),
            "recent":  sum(1 for s in scores if s.get("freshness_label")=="RECENT"),
            "stale":   sum(1 for s in scores if s.get("freshness_label") in ("STALE","CURRENT")),
            "outdated":sum(1 for s in scores if s.get("freshness_label")=="OUTDATED"),
        },
        "low_quality_insights": [
            {"type":s["insight_type"],"trust":s["trust_score"],"strength":s["evidence_strength"]}
            for s in sorted(scores, key=lambda x:x["trust_score"])[:5]
        ],
    }
