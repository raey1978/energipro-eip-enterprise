"""
EIP v5.1 — Opportunity Qualification Engine
Full BANT-style qualification replacing simple confidence as primary qualifier.

Evaluates 10 qualification dimensions, produces:
  - Opportunity Qualification Score (0-100)
  - Sub-scores per dimension
  - Missing information checklist
  - Recommended validation actions
  - Qualification verdict (Pursue / Qualify Further / Monitor / Disqualify)
"""
from __future__ import annotations
from typing import Optional

# Qualification weight per dimension (must sum to 1.0)
QUALIFICATION_WEIGHTS = {
    "rig_activity":        0.20,   # Is the rig actually drilling now?
    "product_line_fit":    0.18,   # Do we supply this?
    "decision_window":     0.15,   # Can we act in time?
    "evidence_quality":    0.12,   # How strong is the DDR evidence?
    "customer_clarity":    0.10,   # Do we know who to contact?
    "competitor_clarity":  0.08,   # Do we know who we're up against?
    "commercial_readiness":0.08,   # Budget/PO likely available?
    "technical_readiness": 0.05,   # Do we have the capability?
    "data_completeness":   0.02,   # Is the opportunity data complete?
    "human_validation":    0.02,   # Has a human reviewed this?
}

assert abs(sum(QUALIFICATION_WEIGHTS.values()) - 1.0) < 0.001, "Weights must sum to 1.0"

KNOWN_PRODUCT_LINES = {
    "MWD / Directional", "Completion", "Fishing / Intervention",
    "Cementing", "Wireline / Logging", "Solids Control",
    "Well Testing", "Rental / Intervention", "H2S / Safety",
}


def qualify_opportunity(opp: dict) -> dict:
    """
    Score an opportunity across 10 qualification dimensions.
    Returns full qualification report.
    """
    pl         = opp.get("product_line", "")
    conf       = opp.get("confidence", 0)
    urgency    = opp.get("urgency", "future")
    comp       = opp.get("competitor", "")
    val_status = opp.get("validation_status", "new")
    ev_text    = opp.get("evidence_text", "") or ""
    ev_section = opp.get("evidence_section", "")
    rig        = opp.get("rig", "")
    well       = opp.get("well", "")
    field      = opp.get("field", "")
    contact    = opp.get("contact_name", "") or opp.get("suggested_contact", "")
    kws        = opp.get("matched_keywords", [])
    if isinstance(kws, str):
        import json
        try: kws = json.loads(kws)
        except: kws = []

    scores     = {}
    rationale  = {}
    missing    = []
    actions    = []

    # ── 1. Rig Activity (0-100) ───────────────────────────────────────────────
    urgency_pts = {"immediate":100,"5_days":85,"7_days":70,"30_days":40,"future":15}
    scores["rig_activity"] = urgency_pts.get(urgency, 30)
    rationale["rig_activity"] = {
        "score":  scores["rig_activity"],
        "label":  urgency.replace("_"," ").title(),
        "detail": _urgency_detail(urgency),
    }
    if urgency == "future":
        missing.append("Operation timing unclear — verify rig programme schedule")
        actions.append({"priority":"medium","action":"Confirm planned operation date with drilling department"})

    # ── 2. Product Line Fit (0-100) ───────────────────────────────────────────
    if pl in KNOWN_PRODUCT_LINES:
        pl_fit = 100 if len(kws) >= 3 else 80 if len(kws) >= 1 else 60
    else:
        pl_fit = 30
        missing.append(f"Product line '{pl}' not in EnergiPro service catalogue — verify fit")
    scores["product_line_fit"] = pl_fit
    rationale["product_line_fit"] = {
        "score":  pl_fit,
        "label":  pl or "Unknown",
        "detail": f"Matched via {len(kws)} keyword(s): {', '.join(kws[:4]) if kws else 'pattern match'}",
    }

    # ── 3. Decision Window (0-100) ────────────────────────────────────────────
    window_pts = {"immediate":100,"5_days":90,"7_days":75,"30_days":50,"future":20}
    win_pts    = window_pts.get(urgency, 30)
    if val_status == "rejected":
        win_pts = 0
    scores["decision_window"] = win_pts
    proposal_timing = _proposal_timing(urgency)
    rationale["decision_window"] = {
        "score":   win_pts,
        "label":   proposal_timing,
        "detail":  f"Based on urgency signal '{urgency}'. {proposal_timing}",
    }
    if urgency in ("future",) and val_status not in ("accepted","converted"):
        actions.append({"priority":"low","action":"Monitor — set calendar reminder to revisit in 30 days"})

    # ── 4. Evidence Quality (0-100) ───────────────────────────────────────────
    ev_q = 0
    section_pts = {"Foreman Remarks":40,"Next 24h Plan":35,"Last 24h Operations":30,
                   "Service Companies & Rental Tools":20}
    ev_q += section_pts.get(ev_section, 10)
    words = len(ev_text.split()) if ev_text else 0
    ev_q += min(40, words // 5)  # Up to 40 pts for evidence length
    ev_q += min(20, conf // 5)   # Up to 20 pts for AI confidence
    ev_q  = min(100, ev_q)
    scores["evidence_quality"] = ev_q
    rationale["evidence_quality"] = {
        "score":  ev_q,
        "label":  "Strong" if ev_q>=70 else "Adequate" if ev_q>=45 else "Weak",
        "detail": f"From '{ev_section}' section. AI confidence: {conf}%. Evidence length: {words} words.",
    }
    if ev_q < 40:
        missing.append("Evidence text is thin — re-examine source DDR pages")
        actions.append({"priority":"high","action":f"Review source document page {opp.get('source_page','?')} for additional evidence"})

    # ── 5. Customer Clarity (0-100) ───────────────────────────────────────────
    cust_score = 0
    if contact:                             cust_score += 60
    if opp.get("contact_name"):            cust_score += 20
    if field:                               cust_score += 20
    scores["customer_clarity"] = min(100, cust_score)
    rationale["customer_clarity"] = {
        "score":  scores["customer_clarity"],
        "label":  "Identified" if cust_score>=60 else "Partial" if cust_score>0 else "Unknown",
        "detail": f"Contact: {contact or 'not identified'}. Field: {field or 'unknown'}.",
    }
    if not contact:
        missing.append("Customer contact not identified")
        actions.append({"priority":"high","action":"Identify Saudi Aramco drilling department contact for this rig/well"})

    # ── 6. Competitor Clarity (0-100) ─────────────────────────────────────────
    if comp:
        comp_score = 90 if comp in ("SLB","Halliburton","Baker Hughes","NESR","Weatherford") else 70
    else:
        comp_score = 50  # No competitor = good (primary approach) but less certainty
    scores["competitor_clarity"] = comp_score
    rationale["competitor_clarity"] = {
        "score":  comp_score,
        "label":  f"Known: {comp}" if comp else "None detected (primary approach)",
        "detail": ("Displacement opportunity — we know who we're competing against."
                   if comp else
                   "No competitor detected — approach as primary vendor. Highest win rate scenario."),
    }
    if not comp:
        actions.append({"priority":"low","action":"Verify with field contact whether any competitor is active on this rig"})

    # ── 7. Commercial Readiness (0-100) ───────────────────────────────────────
    # Estimates likelihood that budget/PO is available
    comm_ready = 40  # Baseline
    if urgency in ("immediate","5_days"):
        comm_ready += 40  # Active rig = budget is approved and flowing
    elif urgency == "7_days":
        comm_ready += 20
    if val_status == "accepted":
        comm_ready += 20
    comm_ready = min(100, comm_ready)
    scores["commercial_readiness"] = comm_ready
    rationale["commercial_readiness"] = {
        "score":  comm_ready,
        "label":  "Ready" if comm_ready>=70 else "Likely" if comm_ready>=50 else "Uncertain",
        "detail": ("Active rig operations confirm budget approved and procurement authorised."
                   if urgency in ("immediate","5_days") else
                   "Budget status unconfirmed — verify with customer before proposal."),
    }
    if comm_ready < 50:
        missing.append("Budget approval status unconfirmed")
        actions.append({"priority":"medium","action":"Confirm budget availability with Saudi Aramco procurement"})

    # ── 8. Technical Readiness (0-100) ───────────────────────────────────────
    # Do we have the capability to deliver?
    tech_ready = 80 if pl in KNOWN_PRODUCT_LINES else 40
    scores["technical_readiness"] = tech_ready
    rationale["technical_readiness"] = {
        "score":  tech_ready,
        "label":  "Capable" if tech_ready >= 70 else "Verify Capability",
        "detail": (f"{pl} is within EnergiPro's service catalogue."
                   if tech_ready >= 70 else
                   f"Verify EnergiPro has capability and equipment for '{pl}'."),
    }

    # ── 9. Data Completeness (0-100) ─────────────────────────────────────────
    fields_present = [
        bool(opp.get("title")), bool(pl), bool(rig), bool(well),
        bool(field), bool(ev_text), bool(urgency), bool(opp.get("estimated_value")),
    ]
    data_comp = round(sum(fields_present) / len(fields_present) * 100)
    scores["data_completeness"] = data_comp
    rationale["data_completeness"] = {
        "score":  data_comp,
        "label":  f"{sum(fields_present)}/{len(fields_present)} fields present",
        "detail": "Complete" if data_comp >= 90 else "Partial data — some fields missing",
    }
    if data_comp < 75:
        missing.append(f"Opportunity record incomplete ({data_comp}% data present)")

    # ── 10. Human Validation (0-100) ─────────────────────────────────────────
    val_pts = {"accepted":100,"converted":100,"needs_review":40,"new":20,"rejected":0}
    scores["human_validation"] = val_pts.get(val_status, 20)
    rationale["human_validation"] = {
        "score":  scores["human_validation"],
        "label":  val_status.replace("_"," ").title(),
        "detail": (f"Validated by a reviewer — high confidence."
                   if val_status in ("accepted","converted") else
                   "Not yet reviewed — qualify and validate before pursuing."),
    }
    if val_status == "new":
        actions.append({"priority":"medium","action":"Validate this opportunity with a senior BD manager"})

    # ── COMPOSITE QUALIFICATION SCORE ─────────────────────────────────────────
    qs = sum(scores[dim] * QUALIFICATION_WEIGHTS[dim] for dim in QUALIFICATION_WEIGHTS)
    qs = round(qs)

    # ── Verdict ───────────────────────────────────────────────────────────────
    if val_status == "rejected":
        verdict = "Disqualify"
        verdict_detail = "This opportunity has been rejected by a reviewer."
    elif qs >= 72:
        verdict = "Pursue"
        verdict_detail = "Strong qualification — assign owner and begin proposal preparation."
    elif qs >= 50:
        verdict = "Qualify Further"
        verdict_detail = "Moderate qualification — address missing information before committing resources."
    elif qs >= 30:
        verdict = "Monitor"
        verdict_detail = "Low qualification — monitor for better signal before pursuing."
    else:
        verdict = "Disqualify"
        verdict_detail = "Insufficient evidence or misfit — do not invest BD resources."

    return {
        "qualification_score":  qs,
        "verdict":              verdict,
        "verdict_detail":       verdict_detail,
        "dimension_scores":     scores,
        "dimension_rationale":  rationale,
        "missing_information":  missing,
        "recommended_actions":  actions,
        "weights_used":         QUALIFICATION_WEIGHTS,
        "score_breakdown": [
            {
                "dimension": dim.replace("_"," ").title(),
                "score":     scores[dim],
                "weight":    round(QUALIFICATION_WEIGHTS[dim]*100),
                "weighted":  round(scores[dim] * QUALIFICATION_WEIGHTS[dim]),
                "rationale": rationale[dim],
            }
            for dim in QUALIFICATION_WEIGHTS
        ],
    }


def _urgency_detail(urgency: str) -> str:
    return {
        "immediate": "Active operation — service window is open NOW. First-mover critical.",
        "5_days":    "Operation within 5 days — proposal must be submitted within 48 hours.",
        "7_days":    "Operation within 7 days — begin qualification immediately.",
        "30_days":   "Operation in ~30 days — time to qualify, propose, and negotiate.",
        "future":    "Future operation — monitor and position. No immediate window.",
    }.get(urgency, "Timing unknown.")


def _proposal_timing(urgency: str) -> str:
    return {
        "immediate": "Submit proposal TODAY",
        "5_days":    "Submit proposal within 24–48 hours",
        "7_days":    "Submit proposal within 3 days",
        "30_days":   "Submit proposal within 2 weeks",
        "future":    "Begin positioning — no proposal yet",
    }.get(urgency, "Timing unclear")
