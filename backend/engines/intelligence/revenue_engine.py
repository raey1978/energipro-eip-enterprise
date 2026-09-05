"""
EIP v5.1 — Revenue Intelligence Engine
Extends Commercial Engine with full revenue estimation:
  - Revenue Range (Conservative / Expected / Optimistic)
  - Rental / Service Duration estimates
  - Equipment & Personnel Demand
  - Gross Margin estimation
  - Revenue Confidence Score
  - Strategic Importance

DESIGN: This module EXTENDS commercial_engine.py output — never duplicates it.
All configurable assumptions are passed in from Settings.
"""
from __future__ import annotations
import datetime
from typing import Optional

# ── Default Assumptions (all configurable via Settings) ───────────────────────
DEFAULT_ASSUMPTIONS = {
    # Revenue variance from expected value
    "conservative_factor":    0.60,   # 60% of expected
    "optimistic_factor":      1.40,   # 140% of expected

    # Gross Margin by product line (%)
    "gross_margins": {
        "MWD / Directional":       0.35,
        "Completion":               0.28,
        "Fishing / Intervention":  0.40,
        "Cementing":                0.22,
        "Wireline / Logging":       0.30,
        "Solids Control":           0.32,
        "Well Testing":             0.33,
        "Rental / Intervention":    0.38,
        "H2S / Safety":             0.25,
    },

    # Typical duration by product line (rental days)
    "rental_duration_days": {
        "MWD / Directional":       14,
        "Completion":               5,
        "Fishing / Intervention":   7,
        "Cementing":                2,
        "Wireline / Logging":       3,
        "Solids Control":          21,
        "Well Testing":            10,
        "Rental / Intervention":   14,
        "H2S / Safety":            30,
    },

    # Typical service duration (field weeks)
    "service_duration_weeks": {
        "MWD / Directional":       3,
        "Completion":               1,
        "Fishing / Intervention":   1,
        "Cementing":                1,
        "Wireline / Logging":       1,
        "Solids Control":           5,
        "Well Testing":             2,
        "Rental / Intervention":    2,
        "H2S / Safety":             6,
    },

    # Equipment items by product line (typical per job)
    "equipment_items": {
        "MWD / Directional":       3,    # MWD tool, RSS, subs
        "Completion":               8,    # liner hanger, packers, float eq, etc.
        "Fishing / Intervention":   5,    # overshot, jar, safety joint, etc.
        "Cementing":                4,    # float shoe, collar, centralizers
        "Wireline / Logging":       4,    # tools + head + jars
        "Solids Control":           3,    # centrifuge, shakers
        "Well Testing":             6,    # separator, choke, gauges
        "Rental / Intervention":    4,
        "H2S / Safety":             5,    # monitor, SCBA, rescue kit
    },

    # Personnel demand by product line (typical per job)
    "personnel_demand": {
        "MWD / Directional":       2,    # MWD eng + directional driller
        "Completion":               3,    # sup + 2 crew
        "Fishing / Intervention":   3,    # fishing sup + 2 crew
        "Cementing":                3,    # cement eng + 2 operators
        "Wireline / Logging":       2,    # wireline eng + operator
        "Solids Control":           2,    # SC eng + operator
        "Well Testing":             4,    # test sup + 3 crew
        "Rental / Intervention":    2,
        "H2S / Safety":             2,    # H2S sup + standby
    },

    # Strategic multiplier weights
    "strategic_weights": {
        "aramco_direct":      1.5,    # multiplier if direct Aramco work
        "repeat_customer":    1.3,
        "new_field_entry":    1.4,    # entering a new field
        "displacing_major":   1.6,    # displacing SLB/HAL/BHI
    },
}

# ── Strategic importance helpers ──────────────────────────────────────────────
MAJOR_COMPETITORS = {"SLB","Baker Hughes","Halliburton","Weatherford","NESR"}

STRATEGIC_FIELDS_KSA = {
    "Ghawar", "Khurais", "Shaybah", "Safaniya", "Marjan",
    "Zuluf", "Abu Hadriya", "Fadhili", "Haradh", "Hawiyah",
    "Uthmaniyah", "Shedgum", "Ain Dar", "Abqaiq", "Berri",
    "Jafurah",  # Unconventional — very high strategic value
}


def calculate_revenue_intelligence(opp: dict, assumptions: dict = None) -> dict:
    """
    Main entry point.
    Accepts an opportunity dict + configurable assumptions.
    Returns full revenue intelligence block — intended to EXTEND commercial_engine output.
    """
    asm = {**DEFAULT_ASSUMPTIONS, **(assumptions or {})}

    pl          = opp.get("product_line", "")
    conf        = opp.get("confidence", 0)
    urgency     = opp.get("urgency", "future")
    comp        = opp.get("competitor", "")
    val_status  = opp.get("validation_status", "new")
    ev_text     = opp.get("evidence_text", "") or ""
    rig         = opp.get("rig", "")
    field       = opp.get("field", "") or ""
    win_prob    = opp.get("win_probability", 0.30)  # from commercial_engine if pre-calculated

    base_value  = opp.get("estimated_value", 0) or asm["rental_duration_days"].get(pl, 10) * 5000

    # ── Revenue Range ─────────────────────────────────────────────────────────
    conservative = round(base_value * asm["conservative_factor"])
    expected     = round(base_value)
    optimistic   = round(base_value * asm["optimistic_factor"])

    # ── Gross Margin ──────────────────────────────────────────────────────────
    gm_pct       = asm["gross_margins"].get(pl, 0.28)
    gm_expected  = round(expected * gm_pct)
    gm_conservative = round(conservative * gm_pct)
    gm_optimistic   = round(optimistic   * gm_pct)

    # ── Durations ─────────────────────────────────────────────────────────────
    rental_days    = asm["rental_duration_days"].get(pl, 7)
    service_weeks  = asm["service_duration_weeks"].get(pl, 1)

    # Adjust for urgency — immediate windows are shorter
    if urgency == "immediate":
        rental_days   = max(1, round(rental_days * 0.7))
        service_weeks = max(1, round(service_weeks * 0.7))

    # ── Equipment & Personnel ─────────────────────────────────────────────────
    equipment_items = asm["equipment_items"].get(pl, 3)
    personnel_count = asm["personnel_demand"].get(pl, 2)

    # ── Revenue Confidence Score (0-100) ─────────────────────────────────────
    # Independent from AI confidence — measures revenue estimate reliability
    rev_conf = 0
    if conf >= 90:             rev_conf += 30
    elif conf >= 75:           rev_conf += 20
    elif conf >= 60:           rev_conf += 10

    if val_status == "accepted":   rev_conf += 30
    elif val_status == "new":      rev_conf += 15
    elif val_status == "rejected": rev_conf = 0

    if opp.get("contact_name") or opp.get("suggested_contact"): rev_conf += 15
    if opp.get("well") and opp.get("rig"):                       rev_conf += 10
    if len(ev_text) > 100:                                         rev_conf += 10
    if comp:                                                        rev_conf += 5

    rev_conf = min(100, rev_conf)
    rev_conf_label = "High" if rev_conf>=70 else "Medium" if rev_conf>=40 else "Low"

    # ── Strategic Importance (0-100) ─────────────────────────────────────────
    strategic_score  = 40  # baseline
    strategic_reasons = []

    if comp in MAJOR_COMPETITORS:
        strategic_score += 25
        strategic_reasons.append(f"Displacing {comp} — a major international competitor")
    elif comp:
        strategic_score += 10
        strategic_reasons.append(f"Displacement opportunity vs {comp}")
    else:
        strategic_score += 15
        strategic_reasons.append("Primary vendor approach — no competitor to displace")

    field_clean = field.strip().title()
    for sf in STRATEGIC_FIELDS_KSA:
        if sf.lower() in field_clean.lower():
            strategic_score += 20
            strategic_reasons.append(f"{sf} is a strategically important Saudi Aramco field")
            break

    if pl in ("MWD / Directional", "Fishing / Intervention", "Well Testing"):
        strategic_score += 15
        strategic_reasons.append(f"{pl} services have high strategic value and strong margins")

    if urgency in ("immediate", "5_days"):
        strategic_score += 10
        strategic_reasons.append("Immediate window — first-mover advantage available")

    strategic_score = min(100, strategic_score)
    strategic_label = "Critical" if strategic_score>=80 else "High" if strategic_score>=60 else "Medium" if strategic_score>=40 else "Low"

    # ── Expected Award Month ──────────────────────────────────────────────────
    days_to_award = {
        "immediate": 7,
        "5_days":   14,
        "7_days":   21,
        "30_days":  45,
        "future":   90,
    }
    award_date = (datetime.date.today() +
                  datetime.timedelta(days=days_to_award.get(urgency, 30)))

    # ── Mobilisation effort ───────────────────────────────────────────────────
    mob_effort = _mobilisation_effort(pl, urgency, comp)

    # ── Weighted pipeline contribution ────────────────────────────────────────
    wp = opp.get("win_probability", 0)
    if isinstance(wp, (int, float)) and wp > 1:
        win_prob_decimal = wp / 100  # already in percentage form
    else:
        win_prob_decimal = wp or 0.25

    weighted_value = round(expected * win_prob_decimal)

    return {
        # Revenue Range
        "revenue_conservative":  conservative,
        "revenue_expected":      expected,
        "revenue_optimistic":    optimistic,
        "revenue_range_label":   f"${conservative:,.0f} – ${optimistic:,.0f}",

        # Margin
        "gross_margin_pct":      round(gm_pct * 100, 1),
        "gross_margin_expected": gm_expected,
        "gross_margin_conservative": gm_conservative,
        "gross_margin_optimistic":   gm_optimistic,

        # Durations
        "rental_duration_days":  rental_days,
        "service_duration_weeks":service_weeks,

        # Demand
        "equipment_items_required": equipment_items,
        "personnel_required":        personnel_count,

        # Pipeline
        "weighted_pipeline_value": weighted_value,
        "expected_award_month":    award_date.strftime("%B %Y"),
        "expected_award_date":     award_date.isoformat(),

        # Scores
        "revenue_confidence":      rev_conf,
        "revenue_confidence_label":rev_conf_label,
        "strategic_importance":    strategic_score,
        "strategic_importance_label": strategic_label,
        "strategic_reasons":       strategic_reasons,

        # Mobilisation
        "mobilisation_effort":     mob_effort["effort"],
        "mobilisation_timeline":   mob_effort["timeline"],
        "mobilisation_notes":      mob_effort["notes"],

        # Assumptions used (transparency)
        "assumptions_used": {
            "conservative_factor":   asm["conservative_factor"],
            "optimistic_factor":     asm["optimistic_factor"],
            "gross_margin_pct":      gm_pct,
            "rental_duration_days":  asm["rental_duration_days"].get(pl, 7),
            "service_duration_weeks":asm["service_duration_weeks"].get(pl, 1),
            "equipment_items":       asm["equipment_items"].get(pl, 3),
            "personnel_demand":      asm["personnel_demand"].get(pl, 2),
        },
        "assumptions_disclaimer": (
            "Revenue estimates are based on Saudi Aramco unit-rate service contracts. "
            "Conservative = 60% of expected. Optimistic = 140% of expected. "
            "Gross margin is an estimate based on industry benchmarks and may vary. "
            "These are indicative figures only — not confirmed contract values."
        ),
    }


def _mobilisation_effort(pl: str, urgency: str, comp: str) -> dict:
    effort_map = {
        "MWD / Directional":       ("High",   "48–72 hours", "MWD tool pre-test + directional driller assignment + BHA preparation"),
        "Completion":               ("Medium", "24–48 hours", "Tool availability check + delivery to wellsite"),
        "Fishing / Intervention":  ("High",   "12–24 hours", "Fishing tool selection + programme preparation + emergency mobilisation"),
        "Cementing":                ("Low",    "12–24 hours", "Slurry design + additive check + crew assignment"),
        "Wireline / Logging":       ("Medium", "24–48 hours", "Tool make-up + calibration + programme review"),
        "Solids Control":           ("Medium", "24–48 hours", "Equipment delivery + installation + engineer assignment"),
        "Well Testing":             ("High",   "48–96 hours", "Equipment rig-up + separator testing + procedure review"),
        "Rental / Intervention":    ("Low",    "12–24 hours", "Tool availability check + delivery"),
        "H2S / Safety":             ("Medium", "24–48 hours", "Monitor calibration + SCBA check + crew briefing"),
    }
    effort, timeline, notes = effort_map.get(pl, ("Medium","24–48 hours","Standard mobilisation"))
    if urgency == "immediate" and effort != "Low":
        notes = f"⚠ IMMEDIATE WINDOW: {notes} — Start now."
    return {"effort": effort, "timeline": timeline, "notes": notes}


def build_revenue_pipeline_summary(opps: list, assumptions: dict = None) -> dict:
    """
    Aggregate revenue intelligence across all opportunities.
    Returns pipeline-level summary.
    """
    if not opps:
        return {
            "total_opportunities": 0,
            "pipeline_expected":   0,
            "pipeline_weighted":   0,
            "pipeline_conservative":0,
            "pipeline_optimistic": 0,
            "total_gross_margin":  0,
            "by_product_line":     [],
            "by_field":            [],
            "by_stage":            [],
        }

    asm   = {**DEFAULT_ASSUMPTIONS, **(assumptions or {})}
    total_expected     = 0
    total_weighted     = 0
    total_conservative = 0
    total_optimistic   = 0
    total_margin       = 0

    by_pl    = {}
    by_field = {}

    for opp in opps:
        ri = calculate_revenue_intelligence(opp, asm)
        total_expected     += ri["revenue_expected"]
        total_weighted     += ri["weighted_pipeline_value"]
        total_conservative += ri["revenue_conservative"]
        total_optimistic   += ri["revenue_optimistic"]
        total_margin       += ri["gross_margin_expected"]

        pl    = opp.get("product_line","Other")
        field = opp.get("field","Unknown") or "Unknown"
        wp    = ri["weighted_pipeline_value"]
        ev    = ri["revenue_expected"]

        if pl not in by_pl:
            by_pl[pl] = {"product_line":pl,"count":0,"expected":0,"weighted":0,"margin":0}
        by_pl[pl]["count"]    += 1
        by_pl[pl]["expected"] += ev
        by_pl[pl]["weighted"] += wp
        by_pl[pl]["margin"]   += ri["gross_margin_expected"]

        if field not in by_field:
            by_field[field] = {"field":field,"count":0,"expected":0,"weighted":0}
        by_field[field]["count"]    += 1
        by_field[field]["expected"] += ev
        by_field[field]["weighted"] += wp

    # Sort
    pl_list    = sorted(by_pl.values(),    key=lambda x: -x["weighted"])
    field_list = sorted(by_field.values(), key=lambda x: -x["weighted"])

    return {
        "total_opportunities":   len(opps),
        "pipeline_expected":     round(total_expected),
        "pipeline_weighted":     round(total_weighted),
        "pipeline_conservative": round(total_conservative),
        "pipeline_optimistic":   round(total_optimistic),
        "total_gross_margin":    round(total_margin),
        "avg_margin_pct":        round(total_margin / max(total_expected,1) * 100, 1),
        "by_product_line":       pl_list[:10],
        "by_field":              field_list[:10],
        "disclaimer": (
            "Pipeline values are estimated based on unit-rate service contracts. "
            "Weighted pipeline = Expected Value × Win Probability. "
            "Gross margin estimates use industry benchmarks and may vary significantly."
        ),
    }
