"""
EIP v5.0 — Commercial Intelligence Engine
Transforms raw opportunities into executive-grade commercial intelligence.

For every opportunity, calculates:
  - Commercial Priority Score (0-100)
  - Business Impact Score (0-100)
  - Estimated Win Probability (%)
  - Competitive Pressure Index (0-10)
  - Operational Urgency (0-10)
  - Opportunity Quality Index (0-100)
  - Recommended Sales Action
  - Business Impact Narrative
"""
import datetime
from typing import Optional

# ── Configurable weights (can be overridden from Settings) ────────────────────
DEFAULT_WEIGHTS = {
    "urgency":        0.30,   # Timing urgency
    "confidence":     0.25,   # AI detection confidence
    "value":          0.20,   # Estimated revenue
    "competitor":     0.15,   # Competitive pressure
    "validation":     0.10,   # Human validation signal
}

URGENCY_SCORES = {
    "immediate": 10,
    "5_days":    8,
    "7_days":    6,
    "30_days":   3,
    "future":    1,
}

VALIDATION_SCORES = {
    "accepted":      10,
    "new":            6,
    "needs_review":   4,
    "rejected":       0,
    "converted":     10,
}

# Unit value rates by product line (USD, overridden by Settings value_rates)
DEFAULT_VALUE_RATES = {
    "MWD / Directional":      220_000,
    "Completion":              75_000,
    "Fishing / Intervention": 160_000,
    "Cementing":               45_000,
    "Wireline / Logging":      53_000,
    "Solids Control":          60_000,
    "Well Testing":            88_000,
    "Rental / Intervention":   22_000,
    "H2S / Safety":            17_000,
}

# Base win rates by product line (% chance of winning vs competitor)
BASE_WIN_RATES = {
    "MWD / Directional":      0.35,
    "Completion":              0.42,
    "Fishing / Intervention": 0.45,
    "Cementing":               0.38,
    "Wireline / Logging":      0.40,
    "Solids Control":          0.50,
    "Well Testing":            0.38,
    "Rental / Intervention":   0.55,
    "H2S / Safety":            0.48,
}

# Competitors ranked by competitive strength (lower = harder to displace)
COMPETITOR_STRENGTH = {
    "SLB":              9,   # Hardest to displace
    "Baker Hughes":     8,
    "Halliburton":      8,
    "Weatherford":      6,
    "NOV":              5,
    "NESR":             6,
    "Expro":            6,
    "AlMansoori":       5,
    "TAQA Group":       4,
    "GDMC":             4,
    "Oilserv (Zamil)":  4,
    "Sinopec":          5,
    "Rawabi":           5,
    "Sapesco":          3,
    "NAPESCO":          3,
}

RECOMMENDED_ACTIONS = {
    "immediate": "📞 Contact customer TODAY — mobilise immediately",
    "5_days":    "📋 Prepare proposal within 48 hours",
    "7_days":    "📅 Schedule site visit this week",
    "30_days":   "🔍 Begin qualification — confirm need and budget",
    "future":    "👁 Monitor and position for when window opens",
}

DEPARTMENTS = {
    "MWD / Directional":      "Directional Drilling",
    "Completion":              "Completion Services",
    "Fishing / Intervention": "Fishing & Remedial",
    "Cementing":               "Cementing",
    "Wireline / Logging":      "Wireline",
    "Solids Control":          "Drilling Services",
    "Well Testing":            "Production Services",
    "Rental / Intervention":   "Rental Tools",
    "H2S / Safety":            "HSE & Safety",
}


def calculate_commercial_intelligence(opp: dict, value_rates: dict = None) -> dict:
    """
    Main entry point — takes a raw opportunity dict and returns
    full commercial intelligence enrichment.
    """
    vr      = {**DEFAULT_VALUE_RATES, **(value_rates or {})}
    pl      = opp.get("product_line", "")
    conf    = opp.get("confidence", 0)
    urgency = opp.get("urgency", "future")
    comp    = opp.get("competitor", "")
    val_st  = opp.get("validation_status", "new")
    ev      = opp.get("evidence_text", "") or ""
    est_val = opp.get("estimated_value", 0) or vr.get(pl, 0)

    # ── 1. Competitive Pressure (0-10) ────────────────────────────────────────
    comp_strength = COMPETITOR_STRENGTH.get(comp, 5) if comp else 0
    competitive_pressure = comp_strength

    # ── 2. Win Probability (%) ────────────────────────────────────────────────
    base_win = BASE_WIN_RATES.get(pl, 0.40)
    # Adjust for competitor strength
    if comp:
        comp_penalty = comp_strength * 0.02   # 2% per competitor strength point
        win_prob = max(0.05, base_win - comp_penalty)
    else:
        win_prob = min(0.80, base_win + 0.15)  # No competitor = primary approach

    # Adjust for confidence
    conf_factor = conf / 100
    win_prob = win_prob * (0.5 + 0.5 * conf_factor)

    # Adjust for human validation
    if val_st == "accepted":
        win_prob = min(0.90, win_prob * 1.2)
    elif val_st == "rejected":
        win_prob = 0.0

    win_prob_pct = round(win_prob * 100, 1)

    # ── 3. Estimated Revenue Potential ────────────────────────────────────────
    revenue_potential = est_val if est_val > 0 else vr.get(pl, 0)
    risk_adjusted_revenue = round(revenue_potential * win_prob)

    # ── 4. Operational Urgency (0-10) ─────────────────────────────────────────
    operational_urgency = URGENCY_SCORES.get(urgency, 1)

    # ── 5. Commercial Priority Score (0-100) ──────────────────────────────────
    # Weighted composite
    urgency_norm  = operational_urgency / 10
    conf_norm     = conf / 100
    val_norm      = VALIDATION_SCORES.get(val_st, 5) / 10
    comp_norm     = competitive_pressure / 10
    # Value normalised against top value ($500k)
    val_norm_rev  = min(1.0, revenue_potential / 500_000)

    w = DEFAULT_WEIGHTS
    priority_raw = (
        urgency_norm * w["urgency"] +
        conf_norm    * w["confidence"] +
        val_norm_rev * w["value"] +
        comp_norm    * w["competitor"] +
        val_norm     * w["validation"]
    )
    commercial_priority = round(priority_raw * 100)

    # ── 6. Business Impact Score (0-100) ─────────────────────────────────────
    # Higher for: high value + immediate + no competitor (cleaner win)
    impact = (
        (revenue_potential / 500_000) * 40 +
        (operational_urgency / 10)   * 35 +
        (conf / 100)                 * 25
    )
    business_impact = min(100, round(impact))

    # ── 7. Opportunity Quality Index (OQI 0-100) ─────────────────────────────
    completeness = _completeness_score(opp)
    evidence_q   = _evidence_quality(ev, opp.get("evidence_section",""))
    validation_q = VALIDATION_SCORES.get(val_st, 5) * 10
    comp_clarity  = 100 if comp else 40
    customer_q   = 100 if opp.get("contact_name") or opp.get("suggested_contact") else 30
    rig_q        = 100 if opp.get("rig") and opp.get("well") else 40

    oqi = round(
        completeness * 0.25 +
        evidence_q   * 0.25 +
        validation_q * 0.20 +
        comp_clarity * 0.10 +
        customer_q   * 0.10 +
        rig_q        * 0.10
    )
    oqi = min(100, oqi)
    oqi_label = "Excellent" if oqi >= 80 else "Good" if oqi >= 65 else "Acceptable" if oqi >= 50 else "Poor"

    # ── 8. Recommended Action ─────────────────────────────────────────────────
    recommended_action = RECOMMENDED_ACTIONS.get(urgency, RECOMMENDED_ACTIONS["future"])
    if val_st == "rejected":
        recommended_action = "❌ Rejected — do not pursue without new evidence"
    elif val_st == "converted":
        recommended_action = "✓ Converted to lead — track in pipeline"

    # ── 9. Suggested Owner / Department ──────────────────────────────────────
    suggested_dept  = DEPARTMENTS.get(pl, "Business Development")
    follow_up_days  = {"immediate": 0, "5_days": 3, "7_days": 5, "30_days": 14, "future": 30}
    follow_up_date  = (datetime.date.today() +
                       datetime.timedelta(days=follow_up_days.get(urgency, 14))).isoformat()

    # ── 10. Business Impact Narrative ─────────────────────────────────────────
    narrative = _build_narrative(opp, win_prob_pct, revenue_potential,
                                  risk_adjusted_revenue, comp, urgency, pl, oqi)

    # ── 11. Why This Matters ──────────────────────────────────────────────────
    why_matters = _build_why_matters(opp, comp, urgency, pl, conf)

    # ── 12. Technical & Commercial Preparation ───────────────────────────────
    tech_prep, comm_prep = _build_preparation(pl, comp, urgency)

    return {
        "commercial_priority":    commercial_priority,
        "business_impact":        business_impact,
        "win_probability":        win_prob_pct,
        "competitive_pressure":   competitive_pressure,
        "operational_urgency":    operational_urgency,
        "opportunity_quality_index": oqi,
        "oqi_label":              oqi_label,
        "revenue_potential":      revenue_potential,
        "risk_adjusted_revenue":  risk_adjusted_revenue,
        "recommended_action":     recommended_action,
        "suggested_department":   suggested_dept,
        "follow_up_date":         follow_up_date,
        "why_matters":            why_matters,
        "business_narrative":     narrative,
        "technical_preparation":  tech_prep,
        "commercial_preparation": comm_prep,
    }


def _completeness_score(opp: dict) -> float:
    """Score 0-100 for how complete the opportunity data is."""
    fields = {
        "title":          bool(opp.get("title")),
        "product_line":   bool(opp.get("product_line")),
        "rig":            bool(opp.get("rig")),
        "well":           bool(opp.get("well")),
        "field":          bool(opp.get("field")),
        "competitor":     bool(opp.get("competitor")),
        "evidence_text":  bool(opp.get("evidence_text")),
        "urgency":        opp.get("urgency","") != "future",
        "contact":        bool(opp.get("suggested_contact") or opp.get("contact_name")),
    }
    return sum(1 for v in fields.values() if v) / len(fields) * 100


def _evidence_quality(evidence: str, section: str) -> float:
    """Score 0-100 for evidence text quality."""
    if not evidence:
        return 0
    words = len(evidence.split())
    section_bonus = {"Foreman Remarks": 20, "Next 24h Plan": 15, "Last 24h Operations": 10}.get(section, 0)
    return min(100, (words / 30 * 60) + section_bonus)


def _build_narrative(opp, win_prob, revenue, risk_adj, comp, urgency, pl, oqi) -> str:
    rig   = opp.get("rig","—")
    well  = opp.get("well","—")
    field = opp.get("field","—")
    umap  = {"immediate":"requires action TODAY","5_days":"requires action within 5 days",
              "7_days":"should be addressed this week","30_days":"warrants attention this month",
              "future":"should be monitored"}
    timing = umap.get(urgency,"warrants attention")

    comp_str = f"Currently, **{comp}** is on location — this is a displacement opportunity." if comp \
               else "No competitor detected — this is a primary vendor approach."

    return (
        f"**{pl}** opportunity on rig **{rig}** (well {well}, field {field}) "
        f"{timing}. {comp_str} "
        f"Estimated revenue potential: **${revenue:,.0f}**, "
        f"risk-adjusted (at {win_prob}% win probability): **${risk_adj:,.0f}**. "
        f"Opportunity Quality Index: **{oqi}/100**."
    )


def _build_why_matters(opp, comp, urgency, pl, conf) -> str:
    rig = opp.get("rig","—")
    reasons = []
    if urgency in ("immediate", "5_days"):
        reasons.append(f"Rig {rig} is in active operations — the service window is open now.")
    if comp:
        reasons.append(f"{comp} is currently on location, meaning work is actively being executed — a displacement window exists.")
    if conf >= 85:
        reasons.append(f"High detection confidence ({conf}%) from Foreman Remarks — the primary source of ground truth.")
    if not comp:
        reasons.append(f"No competitor detected — EnergiPro can approach as primary and preferred vendor.")
    reasons.append(f"{pl} is a core service line with established contract rates.")
    return " ".join(reasons)


def _build_preparation(pl, comp, urgency) -> tuple:
    urgency_hours = {"immediate": "24 hours", "5_days": "48 hours", "7_days": "3 days",
                     "30_days": "1 week", "future": "2 weeks"}
    timeline = urgency_hours.get(urgency, "1 week")

    tech_items = {
        "MWD / Directional":      ["Confirm MWD/RSS tool availability", "Review well trajectory requirements", "Assign directional driller"],
        "Completion":              ["Check completion tools inventory", "Confirm liner hanger/packer specs", "Review wellbore conditions"],
        "Fishing / Intervention": ["Identify fish description and BHA details", "Check fishing tool inventory", "Assign fishing supervisor"],
        "Cementing":               ["Confirm cementing unit availability", "Review casing programme", "Calculate slurry design"],
        "Wireline / Logging":      ["Check wireline tool availability", "Review logging programme", "Confirm borehole conditions"],
        "Solids Control":          ["Confirm centrifuge/shaker availability", "Review mud weight programme", "Assign solids control engineer"],
        "Well Testing":            ["Check testing equipment availability", "Review well deliverability data", "Confirm separator capacity"],
        "Rental / Intervention":   ["Confirm rental tool inventory", "Review downhole specifications", "Prepare delivery logistics"],
        "H2S / Safety":            ["Confirm H2S monitoring package availability", "Review H2S concentrations", "Brief safety team"],
    }
    comm_items = [
        f"Identify procurement contact at operator within {timeline}",
        f"Prepare and send technical proposal within {timeline}",
    ]
    if comp:
        comm_items.append(f"Prepare competitive positioning vs {comp}")
    comm_items.append("Confirm budget approval status")
    comm_items.append("Check existing MSA / frame agreement")

    return (
        tech_items.get(pl, ["Review technical requirements", "Confirm equipment availability"]),
        comm_items
    )
