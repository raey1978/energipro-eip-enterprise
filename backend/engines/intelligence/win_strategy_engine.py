"""
EIP v5.1 — Win Strategy Engine
The platform's core BD differentiator.

For every opportunity generates a complete Win Strategy:
  - Why this opportunity matters (business case)
  - Why we can win (our strengths)
  - Why we may lose (honest risk assessment)
  - Customer challenges (what the customer needs)
  - Risk register (commercial / technical / procurement)
  - Positioning strategy
  - Customer engagement sequence
  - BD questions to ask on customer visit
"""
from __future__ import annotations

COMPETITOR_WEAKNESSES = {
    "SLB": [
        "Premium pricing — 20-40% higher than market",
        "Slow mobilisation — large organisation with complex logistics",
        "Less flexibility on contract terms",
        "Less attentive to small/medium jobs",
    ],
    "Halliburton": [
        "Standard offerings — less customisation",
        "Pricing premium on directional and logging",
        "Heavy focus on large package contracts",
    ],
    "Baker Hughes": [
        "Supply chain challenges in KSA post-restructuring",
        "Reduced KSA presence vs. SLB/Halliburton",
    ],
    "Weatherford": [
        "Financial restructuring history creates customer uncertainty",
        "Reduced workforce in KSA market",
    ],
    "NESR": [
        "Growing organisation — still building some service lines",
        "Primarily focused on integrated drilling contracts",
    ],
    "AlMansoori": [
        "Limited product line breadth",
        "Primarily rental tools — limited service delivery",
    ],
}

CUSTOMER_CHALLENGES = {
    "immediate": [
        "Time pressure — operation cannot wait",
        "Risk of NPT if service is delayed",
        "Procurement shortcuts needed to respond fast",
    ],
    "5_days":  [
        "Short procurement window — buyer under pressure",
        "Limited time for complex technical evaluation",
    ],
    "7_days":  [
        "Balancing quality and speed",
        "May be evaluating multiple vendors simultaneously",
    ],
    "30_days": [
        "Budget approval in progress",
        "Technical evaluation ongoing",
        "Procurement formalities to complete",
    ],
    "future":  [
        "Planning phase — interested in capabilities",
        "Budget not yet confirmed",
        "Multiple vendors being evaluated",
    ],
}

COMMERCIAL_RISKS = {
    "MWD / Directional":      ["Competitor already on approved vendor list for this rig","Day rate negotiation in late stage may cut margin"],
    "Completion":              ["Competitor may have frame agreement for accessories","Late notice may affect delivery logistics"],
    "Fishing / Intervention": ["Emergency fishing may bypass normal procurement","Competitor may already be mobilising"],
    "Cementing":               ["Cement company may supply their own additives","Budget may be absorbed in the cementing contract"],
    "Wireline / Logging":      ["SLB logging may be in the well programme","Day rate pressure on slickline"],
    "Solids Control":          ["Mud company may supply own solids control","Day rate contract may be bundled"],
    "Well Testing":            ["Expro/SLB may have standing frame agreement","Budget approval may be delayed for production tests"],
    "Rental / Intervention":   ["NAPESCO frame agreement may cover this tool","Day rate negotiation risk"],
    "H2S / Safety":            ["Rawabi may have exclusive H2S contract","Safety equipment must be pre-certified by Aramco"],
}

PROCUREMENT_RISKS = {
    "immediate": ["Emergency procurement bypass may not include EnergiPro"],
    "5_days":    ["Short-list may already be closed","Direct award to existing vendor likely"],
    "7_days":    ["RFQ may not reach EnergiPro in time"],
    "30_days":   ["Budget approval could be delayed"],
    "future":    ["Procurement timeline unknown — track proactively"],
}

ENGAGEMENT_SEQUENCES = {
    "immediate": [
        {"step":1,"action":"Call drilling supervisor or tool pusher IMMEDIATELY","owner":"BD Manager","timing":"Today"},
        {"step":2,"action":"Confirm service requirement and technical specs","owner":"Technical Sales","timing":"Today"},
        {"step":3,"action":"Submit commercial proposal (even informal)","owner":"BD Manager","timing":"Within 24 hours"},
        {"step":4,"action":"Follow up with procurement on PO","owner":"BD Manager","timing":"Within 48 hours"},
    ],
    "5_days": [
        {"step":1,"action":"Contact drilling department contact within 24 hours","owner":"BD Manager","timing":"Tomorrow"},
        {"step":2,"action":"Request technical specification package","owner":"Technical Sales","timing":"Day 1"},
        {"step":3,"action":"Prepare and submit technical-commercial proposal","owner":"BD + Technical","timing":"Day 2"},
        {"step":4,"action":"Follow up and clarify questions","owner":"BD Manager","timing":"Day 3"},
        {"step":5,"action":"Confirm PO and mobilisation date","owner":"BD Manager","timing":"Day 4"},
    ],
    "7_days": [
        {"step":1,"action":"Contact customer this week","owner":"BD Manager","timing":"Day 1–2"},
        {"step":2,"action":"Technical capability presentation","owner":"Technical Sales","timing":"Day 2–3"},
        {"step":3,"action":"Submit commercial proposal","owner":"BD Manager","timing":"Day 3–4"},
        {"step":4,"action":"Negotiate and confirm","owner":"BD + Commercial","timing":"Day 5–7"},
    ],
    "30_days": [
        {"step":1,"action":"Schedule technical visit within the week","owner":"BD Manager","timing":"Week 1"},
        {"step":2,"action":"Capability presentation and technical Q&A","owner":"Technical Sales","timing":"Week 1"},
        {"step":3,"action":"Submit detailed technical proposal","owner":"Technical Team","timing":"Week 2"},
        {"step":4,"action":"Commercial negotiation","owner":"Commercial Manager","timing":"Week 3"},
        {"step":5,"action":"Contract execution","owner":"Contracts","timing":"Week 4"},
    ],
    "future": [
        {"step":1,"action":"Add to BD call cycle — visit within 30 days","owner":"BD Manager","timing":"Month 1"},
        {"step":2,"action":"Position capability and build relationship","owner":"BD Manager","timing":"Month 1–2"},
        {"step":3,"action":"Monitor DDR for activity signal","owner":"Intelligence Platform","timing":"Ongoing"},
    ],
}

BD_QUESTIONS = {
    "MWD / Directional": [
        "What is the planned BHA for this section?",
        "Is RSS or conventional motor planned?",
        "What trajectory complexity are you expecting?",
        "Who is currently providing MWD services on this rig?",
        "Are you open to a trial well with our directional team?",
        "What are the key concerns with your current MWD vendor?",
    ],
    "Completion": [
        "Who is running the completion string?",
        "What liner/packer specifications are in the programme?",
        "Are you supplying completion accessories separately or through the completion company?",
        "What is the completion date target?",
        "Do you have a preferred float equipment supplier?",
    ],
    "Fishing / Intervention": [
        "What exactly is the fish and at what depth?",
        "What fishing attempts have been made so far?",
        "Has the stuck point been identified?",
        "What is the rig standby rate and how long has it been stuck?",
        "Is there an H2S risk that affects tool selection?",
    ],
    "Cementing": [
        "Who is doing the cementing job?",
        "Are you procuring cement additives separately?",
        "What is the casing size and cementing programme?",
        "What are the BHT/BHP at total depth?",
    ],
    "Well Testing": [
        "What type of test is planned (DST / production / inflow)?",
        "What are the expected flow rates and surface pressures?",
        "Is H2S present and at what concentration?",
        "Who is currently providing testing services on this well?",
        "Is a closed system required or is flaring permitted?",
    ],
    "Solids Control": [
        "Who is the mud contractor and do they supply their own centrifuges?",
        "What is the planned mud weight and circulation rate?",
        "How many centrifuges and shakers are in the rig equipment?",
        "Is this a day-rate rental or full solids control service?",
    ],
    "H2S / Safety": [
        "What is the maximum expected H2S concentration in this well?",
        "How many personnel will require breathing air?",
        "Who is your current H2S safety contractor?",
        "Is SCBA or airline breathing air required?",
        "What does Aramco require for H2S monitoring at this field?",
    ],
    "Wireline / Logging": [
        "What logging suite is in the well programme?",
        "Who is currently providing wireline services on this rig?",
        "Is this open-hole or cased-hole logging?",
        "What is the well deviation at the logging depth?",
    ],
    "Rental / Intervention": [
        "What specific tools are required and what are the specifications?",
        "What is the planned rental duration?",
        "Do you have an existing rental tool frame agreement?",
        "Who is currently your primary rental tool supplier?",
    ],
}


def generate_win_strategy(opp: dict) -> dict:
    """
    Generate complete Win Strategy for an opportunity.
    The BD team's playbook for a single opportunity.
    """
    pl      = opp.get("product_line","")
    comp    = opp.get("competitor","")
    urgency = opp.get("urgency","future")
    conf    = opp.get("confidence",0)
    rig     = opp.get("rig","—")
    well    = opp.get("well","—")
    field   = opp.get("field","—")
    val_st  = opp.get("validation_status","new")
    ev_text = opp.get("evidence_text","") or ""

    # ── Why this opportunity matters ──────────────────────────────────────────
    why_matters = _build_why_matters(opp, pl, comp, urgency, conf, field)

    # ── Why we can win ────────────────────────────────────────────────────────
    why_win = _build_why_win(opp, pl, comp, urgency)

    # ── Why we may lose ───────────────────────────────────────────────────────
    why_lose = _build_why_lose(opp, pl, comp, urgency)

    # ── Customer challenges ───────────────────────────────────────────────────
    cust_challenges = CUSTOMER_CHALLENGES.get(urgency, CUSTOMER_CHALLENGES["future"])

    # ── Risk register ─────────────────────────────────────────────────────────
    commercial_risks  = COMMERCIAL_RISKS.get(pl, ["Standard commercial risks apply"])
    procurement_risks = PROCUREMENT_RISKS.get(urgency, PROCUREMENT_RISKS["future"])
    technical_risks   = _technical_risks(pl, comp, urgency)

    # ── Positioning strategy ──────────────────────────────────────────────────
    positioning = _positioning_strategy(pl, comp, urgency, conf)

    # ── Engagement sequence ───────────────────────────────────────────────────
    engagement = ENGAGEMENT_SEQUENCES.get(urgency, ENGAGEMENT_SEQUENCES["future"])

    # ── BD questions ─────────────────────────────────────────────────────────
    questions = BD_QUESTIONS.get(pl, ["Verify service requirements","Confirm technical specifications"])

    # ── Competitor intelligence ───────────────────────────────────────────────
    comp_intel = None
    if comp:
        comp_intel = {
            "name":          comp,
            "weaknesses":    COMPETITOR_WEAKNESSES.get(comp, ["Evaluate specifically for this opportunity"]),
            "our_advantage": _our_advantage(pl, comp),
        }

    return {
        "opportunity_id":      opp.get("id",""),
        "title":               opp.get("title",""),
        "rig":                 rig,
        "well":                well,
        "field":               field,
        "product_line":        pl,
        "competitor":          comp,
        "urgency":             urgency,

        "why_matters":         why_matters,
        "why_we_win":          why_win,
        "why_we_may_lose":     why_lose,
        "customer_challenges": cust_challenges,

        "risk_register": {
            "commercial":  commercial_risks,
            "technical":   technical_risks,
            "procurement": procurement_risks,
        },

        "positioning_strategy": positioning,
        "engagement_sequence":  engagement,
        "bd_questions":         questions,
        "competitor_intel":     comp_intel,

        "supporting_evidence": {
            "text":    ev_text[:500],
            "section": opp.get("evidence_section",""),
            "source":  opp.get("source_file",""),
            "page":    opp.get("source_page",0),
        },
    }


def _build_why_matters(opp, pl, comp, urgency, conf, field) -> list:
    reasons = []
    if urgency in ("immediate","5_days"):
        reasons.append(f"🔴 Active operation on {opp.get('rig','this rig')} — service window is open NOW. Delay = lost revenue.")
    if comp:
        reasons.append(f"🎯 {comp} is currently on location. This is a displacement opportunity — the contract can change.")
    if conf >= 85:
        reasons.append(f"⭐ High AI confidence ({conf}%) from primary DDR evidence — this is a genuine, confirmed requirement.")
    if not comp:
        reasons.append(f"✅ No competitor detected — EnergiPro can approach as primary vendor with full win probability advantage.")
    reasons.append(f"💰 {pl} is a core service line with strong margins and repeat revenue potential.")
    if any(f in field for f in ["Ghawar","Jafurah","Safaniya","Khurais","Shaybah"]):
        reasons.append(f"📍 {field} is a flagship Saudi Aramco field — a win here builds long-term franchise value.")
    return reasons


def _build_why_win(opp, pl, comp, urgency) -> list:
    reasons = [
        "EnergiPro is a registered Saudi Aramco supplier with an established SC number",
        "Local presence enables faster mobilisation than most international competitors",
        f"EnergiPro has demonstrated {pl} capability in the Kingdom",
    ]
    if urgency in ("immediate","5_days"):
        reasons.append("Speed of response is our strongest differentiator — we can mobilise within 12–24 hours")
    if comp in COMPETITOR_WEAKNESSES:
        reasons.append(f"Key {comp} weakness: {COMPETITOR_WEAKNESSES[comp][0]}")
    if not comp:
        reasons.append("No incumbent competitor — fresh start with customer, full margin available")
    return reasons


def _build_why_lose(opp, pl, comp, urgency) -> list:
    risks = []
    if comp:
        risks.append(f"{comp} is currently on location and has the relationship advantage — inertia favours them")
    if urgency in ("immediate",):
        risks.append("Emergency situations often result in direct award to incumbent — we must pre-position")
    risks.append("If we don't have the customer relationship, procurement may not include us in the RFQ")
    risks.append("Price pressure from lower-cost competitors could erode margin below acceptable levels")
    if pl in ("MWD / Directional","Fishing / Intervention"):
        risks.append(f"Technical performance risk — {pl} jobs require experienced engineers who must be available")
    return risks


def _technical_risks(pl, comp, urgency) -> list:
    risks = [f"Equipment availability for {pl} must be confirmed before committing to customer"]
    if urgency in ("immediate","5_days"):
        risks.append("Short mobilisation window increases risk of wrong tool selection or incomplete preparation")
    if pl == "MWD / Directional":
        risks.append("RSS BHA failure risk — ensure tool has been pre-tested and calibrated")
    if pl == "Fishing / Intervention":
        risks.append("Incorrect fish identification could lead to wrong tool selection")
    if pl == "Well Testing":
        risks.append("H2S risk requires full ATEX-certified equipment and trained crew")
    return risks


def _positioning_strategy(pl, comp, urgency, conf) -> dict:
    if comp in ("SLB","Baker Hughes","Halliburton"):
        approach = "price_and_speed"
        message  = f"EnergiPro delivers equivalent technical performance to {comp} with faster mobilisation and more competitive pricing. We are local, responsive, and Aramco-registered."
    elif comp:
        approach = "quality_and_relationship"
        message  = f"EnergiPro offers stronger technical capability and more attentive service than {comp}. We invest in every customer relationship — not just the large contracts."
    else:
        approach = "primary_vendor"
        message  = f"EnergiPro is the right primary vendor choice for {pl}. We are registered, capable, local, and ready. Let us demonstrate our value on this well."

    return {
        "approach": approach,
        "core_message": message,
        "do": [
            "Lead with availability and readiness — the customer needs certainty",
            "Present your Aramco SC number upfront",
            "Offer a reference from a similar recent job",
            "Show your team is available and ready to mobilise",
        ],
        "avoid": [
            "Do not over-engineer the proposal — keep it clear and commercial",
            "Do not promise what you cannot deliver on timeline",
            "Do not bid below sustainable margin just to win",
        ],
    }


def _our_advantage(pl, comp) -> list:
    advantages = [
        "Faster mobilisation — local KSA inventory and crew on standby",
        "More competitive pricing — lower overhead than international majors",
        "Dedicated account management — you will not be a small customer to us",
        "Saudi Aramco-registered — no procurement barriers",
    ]
    if comp in ("SLB","Baker Hughes","Halliburton"):
        advantages.append(f"Agility — {comp} requires multiple approval layers. We decide and deploy quickly.")
    return advantages
