"""
EnergiPro – Product Line Intelligence Engine v3
Fixed: precision keyword rules — commercial signals only, no drilling noise.
"""
import re
from dataclasses import dataclass, field as dc_field
from typing import List, Dict

# ── Realistic Aramco service contract values (Saudi Arabia market rates) ──────
# These represent what a service company (NESR, Rawabi, Expro, etc.) can actually
# earn per job/well — NOT full well completion costs.
# Sources: typical Aramco frame agreements, unit rate contracts, spot orders.
VALUE_TABLE = {
    # Float shoes, centralizers, stage collars, running tool accessories per well
    "Completion":             {"low": 12_000,  "medium": 35_000,   "high": 75_000},
    # Fishing string assembly, overshot/spear/jar, mill runs — per job
    "Fishing / Intervention": {"low": 25_000,  "medium": 70_000,   "high": 160_000},
    # Float equipment, cement retainers, plugs — per cement job (not full service)
    "Cementing":              {"low": 12_000,  "medium": 40_000,   "high": 90_000},
    # Directional motor, survey tool, MWD package — per lateral section
    "MWD / Directional":      {"low": 55_000,  "medium": 130_000,  "high": 220_000},
    # Centrifuge, shaker services — per rig-month
    "Solids Control":         {"low": 12_000,  "medium": 30_000,   "high": 60_000},
    # DST package, flowback equipment, separator — per test
    "Well Testing":           {"low": 45_000,  "medium": 110_000,  "high": 200_000},
    # Pressure/fluid sampling run, memory gauge — per wireline run
    "Wireline / Logging":     {"low": 12_000,  "medium": 35_000,   "high": 70_000},
    # H2S monitoring package — per rig-month
    "H2S / Safety":           {"low": 6_000,   "medium": 15_000,   "high": 28_000},
    # Frac tanks, tubular running tools, PBL subs — per job
    "Rental / Intervention":  {"low": 4_000,   "medium": 18_000,   "high": 45_000},
}

# Human-readable descriptions of what the service company actually sells
# (shown in "Why This?" popup and opportunity cards)
PRODUCT_LINE_WHAT_WE_SELL = {
    "Completion":
        "Completion accessories: float shoes, centralizers, stage collars, landing nipples, running tools. NOT the completion string itself.",
    "Fishing / Intervention":
        "Fishing assembly: overshot, spear, jar, accelerator, mill, fishing string. Charged per job day.",
    "Cementing":
        "Cement accessories: float equipment, retainers, plugs, centralizers. NOT the full cementing service.",
    "MWD / Directional":
        "Directional motor package, survey tools, MWD measurement system. Priced per lateral section drilled.",
    "Solids Control":
        "Centrifuge or shaker service, barite recovery unit. Priced per rig-month.",
    "Well Testing":
        "DST/flowback package: separator, choke manifold, desander, sand filter. Per test event.",
    "Wireline / Logging":
        "Pressure/fluid sampling run (RDT/TLC), memory gauge, PLT. Priced per wireline run.",
    "H2S / Safety":
        "H2S monitoring package on location. Priced per rig-month.",
    "Rental / Intervention":
        "Rental tools: frac tanks, PBL sub, tubular running tools, motorhead adapters. Per job.",
}

# Urgency adjusts probability, not the contract value itself
URGENCY_PROBABILITY = {"immediate":0.9,"5_days":0.75,"7_days":0.60,"30_days":0.40,"future":0.20}

def estimate_value(product_line, confidence, urgency):
    """
    Realistic value estimate based on actual Aramco service contract rates.
    = base_value × confidence_factor
    Urgency affects win probability shown separately, not the contract value.
    """
    vt = VALUE_TABLE.get(product_line, {"low":5_000,"medium":20_000,"high":50_000})
    # Confidence determines which tier (low/medium/high) we use
    if confidence >= 90:
        base = vt["high"]
    elif confidence >= 75:
        base = vt["medium"]
    else:
        base = vt["low"]
    # Confidence as a probability factor (are we sure this is a real opportunity?)
    cf = 1.0 if confidence>=90 else 0.80 if confidence>=75 else 0.60
    return round(base * cf)


@dataclass
class PLRule:
    product_line: str
    # Primary patterns: must match for any opportunity to be created
    primary_patterns: List[str]
    # Confirmation patterns: at least ONE must match (in addition to primary)
    # If empty, primary alone is sufficient
    confirmation_patterns: List[str] = dc_field(default_factory=list)
    # Exclusion patterns: if matched, suppress the opportunity
    exclusion_patterns: List[str] = dc_field(default_factory=list)
    high_value_patterns: List[str] = dc_field(default_factory=list)
    section_weights: dict = dc_field(default_factory=dict)
    # If True: primary must appear in one of these sections (not just anywhere)
    require_sections: List[str] = dc_field(default_factory=list)


PRODUCT_LINE_RULES: List[PLRule] = [

    # ── COMPLETION ──────────────────────────────────────────────────────────
    # Strong: named completion tools, tubing runs, ICV/ESP systems
    PLRule(
        "Completion",
        primary_patterns=[
            r"completion\s+string",
            r"GRE\s+lined\s+tubing",
            r"\bSCT\b",
            r"Baker\s+SCT",
            r"retrievable\s+packer",
            r"Halliburton\s+(?:packer|downhole)",
            r"7[\"']\s*(?:retrievable|packer)",
            r"liner\s+hanger",
            r"4[\-\s]?1/2.*?(?:tubing|completion)",
            r"upper\s+completion",
            r"lower\s+completion",
            r"\bICV\b",
            r"\bICDS\b",
            r"\bSSDS\b",
            r"production\s+packer",
            r"Y-TOOL\b",
            r"ESP.*?(?:Y-TOOL|completion)",
            r"intermediate\s+completion",
            r"SLB.*?intermediate\s+completion",
            r"monobore\s+completion",
            r"5-?1/2[\"'].*?completion",
            r"TUBING.*?COMPLETION",
            r"COMPLETION.*?TUBING",
        ],
        exclusion_patterns=[
            r"completion\s+(?:of\s+)?(?:drilling|cement|casing)\s+job",
        ],
        high_value_patterns=[
            r"Baker\s+SCT",r"retrievable\s+packer",
            r"completion\s+string",r"GRE\s+lined\s+tubing",r"monobore"
        ],
        section_weights={"Foreman Remarks":15,"Next 24h Plan":10},
    ),

    # ── FISHING / INTERVENTION ──────────────────────────────────────────────
    # Strong: fish in hole, stuck pipe, named fishing tools
    PLRule(
        "Fishing / Intervention",
        primary_patterns=[
            r"fish\s+in\s+hole",
            r"1st\s+fish",
            r"2nd\s+fish",
            r"stuck\s+pipe",
            r"\bovershot\b",
            r"\bspear\b",
            r"milling\s+window",
            r"\bwhipstock\b",
            r"WIS\s+whipstock",
            r"reaming\s+(?:trip|BHA)",
            r"fishing\s+tool",
            r"\bTOF\b",
            r"remedial\s+(?:op|operation)",
            r"lost-?in-?hole",
            r"cut\s+(?:and\s+)?(?:pull|pipe)",
        ],
        exclusion_patterns=[
            # jar alone is a tool accessory, not a fishing job
            r"^jar$",
        ],
        high_value_patterns=[r"fish\s+in\s+hole",r"1st\s+fish",r"2nd\s+fish",r"stuck\s+pipe"],
        section_weights={"Foreman Remarks":15,"Last 24h Operations":10},
    ),

    # ── CEMENTING ──────────────────────────────────────────────────────────
    # Must be a future/planned cement job — not just the word "cement"
    PLRule(
        "Cementing",
        primary_patterns=[
            r"liner\s+cement(?:ing)?",
            r"primary\s+cement(?:ing)?",
            r"squeeze\s+cement",
            r"cement\s+(?:job|plug|retainer|liner|stinger)",
            r"CMT\s+(?:JOB|PLUG|LINER|COMPLETION|STAGE)",
            r"5\.5[\"']\s+CEMENT\s+JOB",
            r"G[\-\s]?class\s+cement",
            r"float\s+(?:equipment|shoe|collar)",
            r"cement\s+(?:RIH|run|perform)",
            r"OEDP\s+CEMENT",
            r"spot\s+cmt\s+plug",
            # Abbreviation-based: NCS/HCM/SCM/BCM on location = cementing service present
            r"\b(?:NCS|HCM|BCM|SCM|WCM|SJC|OCT|NCA)\b.*?(?:on\s+loc|crew|rig(?:ged)?\s+up)",
            r"(?:on\s+loc|crew|rig(?:ged)?\s+up).*?\b(?:NCS|HCM|BCM|SCM|WCM|SJC)\b",
        ],
        # Must appear in Next 24h or current ops — not just mentioned historically
        require_sections=["Next 24h Plan","Last 24h Operations","Foreman Remarks"],
        exclusion_patterns=[
            r"cement(?:ed|ing)\s+(?:shoe|casing)\s+(?:was|is|at|to)\s+\d",
        ],
        section_weights={"Next 24h Plan":15,"Last 24h Operations":8},
    ),

    # ── MWD / DIRECTIONAL ──────────────────────────────────────────────────
    # Must have a named directional service company or specific tool reference
    # NOT triggered by: BHA alone, SURVEY column header, hole size mentions
    PLRule(
        "MWD / Directional",
        primary_patterns=[
            r"SLB\s+(?:MTR|RSS|NEOSTEER|ORBIT|PowerDrive)",
            r"BHI\s+MWD",
            r"Baker\s+(?:MWD|directional)",
            r"Halliburton\s+(?:MWD|directional|iCruise)",
            r"MWD\s+(?:ASSY|engineer|tool\s+run|survey\s+taken|data)",
            r"RSS\s+(?:BHA|tool|on\s+loc|run)",
            r"LWD\s+(?:tool|run|data|log)",
            r"GWD\s+BHA",
            r"directional\s+drill(?:er|ing)\s+on\s+loc",
            r"MTR/GWD",
            r"directional\s+drill.*?(?:22|17\.5|12\.25|8\.5|6\.125)[\"'\"]\s*hole",
            r"ROTARY\s+STEERABLE",
        ],
        # Must NOT be just from hole size or generic BHA mention
        exclusion_patterns=[
            r"SURVEY\s+MD",      # column header in mud table
            r"SURVEY\s+ANGLE",   # table header
        ],
        high_value_patterns=[r"RSS",r"ROTARY\s+STEERABLE",r"LWD"],
        section_weights={"Last 24h Operations":10,"Next 24h Plan":12,"Service Companies & Rental Tools":8},
    ),

    # ── SOLIDS CONTROL ──────────────────────────────────────────────────────
    # Must have actual equipment on location — NOT just LGS% column or mud type
    PLRule(
        "Solids Control",
        primary_patterns=[
            r"(?:SLB|MI.SWACO|Halliburton|Baker|M-?I)\s+centrifuge",
            r"centrifuge\s+(?:on\s+loc|active|running|rental|service)",
            r"shale\s+shaker\s+(?:service|rental|on\s+loc|running)",
            r"barite\s+recovery\s+(?:unit|system)",
            r"solids\s+control\s+(?:service|company|unit|package)",
            r"mud\s+(?:recycl|reclaim)",
            r"ditch\s+magnet\s+(?:on\s+loc|service)",
            r"brine\s+filtration\s+(?:unit|service)",
        ],
        # Explicitly exclude LGS % data column and mud type
        exclusion_patterns=[
            r"%\s*LGS",
            r"LGS\s*%",
            r"\bOBM\b(?!\s+centrifuge|\s+treatment)",
            r"\bWBM\b(?!\s+centrifuge|\s+treatment)",
        ],
        high_value_patterns=[r"centrifuge",r"barite\s+recovery"],
        section_weights={"Service Companies & Rental Tools":15,"Last 24h Operations":8},
    ),

    # ── WELL TESTING ──────────────────────────────────────────────────────
    PLRule(
        "Well Testing",
        primary_patterns=[
            r"\bflowback\b",
            r"production\s+test(?:ing)?",
            r"well\s+test(?:ing)?",
            r"\bDST\b",
            r"drill\s+stem\s+test",
            r"clean[\-\s]up\s+(?:operation|test|fluid)",
            r"testing\s+package\s+on\s+loc",
            r"choke\s+manifold\s+(?:on\s+loc|rental|service)",
            r"\bdesander\b",
            r"sand\s+filter\s+(?:on\s+loc|service)",
        ],
        section_weights={"Next 24h Plan":12,"Last 24h Operations":8},
    ),

    # ── WIRELINE / LOGGING ──────────────────────────────────────────────────
    PLRule(
        "Wireline / Logging",
        primary_patterns=[
            r"\bTLC\b",
            r"\bRDT\b",
            r"pressure\s+point(?:\s+survey)?",
            r"fluid\s+sampling",
            r"Baker\s+TLC",
            r"Baker\s+RDT",
            r"open\s+hole\s+log(?:ging)?",
            r"formation\s+eval(?:uation)?",
            r"wireline\s+(?:log|run|tool|service)\s+on\s+loc",
            r"slickline\s+(?:run|operation|service)",
            r"\bPLT\b",
            r"memory\s+gauge\s+(?:run|on\s+loc)",
        ],
        high_value_patterns=[r"Baker\s+TLC",r"Baker\s+RDT",r"pressure\s+point"],
        section_weights={"Next 24h Plan":15,"Foreman Remarks":12},
    ),

    # ── H2S / SAFETY ──────────────────────────────────────────────────────
    # Must be an actual H2S monitoring SERVICE — not a safety drill or concentration reading
    PLRule(
        "H2S / Safety",
        primary_patterns=[
            r"Rawabi\s+H2S",
            r"H2S\s+(?:monitoring|detection)\s+(?:system|unit|package|service)\s+on\s+loc",
            r"SINOPEC\s+H2S\s+detection",
            r"H2S\s+monitoring\s+(?:package|contract|service)",
            r"H2S\s+(?:service\s+company|contractor)\s+on\s+loc",
            r"breathing\s+air\s+(?:unit|package)\s+on\s+loc",
            r"emergency\s+response\s+(?:unit|vehicle|package)\s+on\s+loc",
        ],
        # Exclude drill records, concentration readings, and generic mentions
        exclusion_patterns=[
            r"H2S\s+DRILL",
            r"HELD\s+H2S",
            r"H2S\s*:\s*[\d.]+\s*(?:PPM|%|MOL)",
            r"H2S\s+RELEASE.*?DRILL",
            r"H2S\s+AND\s+ABANDON",
            r"RER\s+\d+\s+PPM.*?H2S",
        ],
        high_value_patterns=[r"Rawabi\s+H2S",r"H2S\s+monitoring"],
        section_weights={"Service Companies & Rental Tools":15,"Foreman Remarks":10},
    ),

    # ── RENTAL / INTERVENTION ──────────────────────────────────────────────
    PLRule(
        "Rental / Intervention",
        primary_patterns=[
            r"frac\s+tank\s+(?:on\s+loc|rental)",
            r"\bPBL\s+sub\b",
            r"tubular\s+running\s+(?:tool|service)",
            r"\bCRT\b",
            r"casing\s+running\s+tool",
            r"NAPESCO\s+HMJ",
            r"motorhead\s+(?:assembly|adapter)",
        ],
        section_weights={"Service Companies & Rental Tools":10},
    ),
]


SECTION_URGENCY = {
    "Next 24h Plan":                    "immediate",
    "Foreman Remarks":                  "5_days",
    "Last 24h Operations":              "7_days",
    "Service Companies & Rental Tools": "7_days",
    "Equipment on Location":            "7_days",
    "Next Location":                    "30_days",
}

TIMING_LABELS = {
    "immediate": "Act Today",
    "5_days":    "Act within 5 working days",
    "7_days":    "Act within 7 days",
    "30_days":   "Act within 30 days",
    "future":    "Monitor – future signal",
}

CONTACT_ROLES = {
    "Completion":             "Completion Engineer / Well Services Supervisor",
    "Fishing / Intervention": "Drilling Superintendent / Well Services Supervisor",
    "Cementing":              "Cementing Engineer / Well Services",
    "MWD / Directional":      "Directional Drilling Supervisor",
    "Solids Control":         "Mud Engineer / Drilling Superintendent",
    "Well Testing":           "Well Test Engineer / Production Supervisor",
    "Wireline / Logging":     "Wireline Engineer / Well Services Supervisor",
    "H2S / Safety":           "HSE Supervisor / Safety Coordinator",
    "Rental / Intervention":  "Rig Superintendent / Procurement",
}

ACTIONS = {
    "Completion":             "Call client immediately and position completion accessories/alternative strings.",
    "Fishing / Intervention": "Contact drilling superintendent and well services supervisor immediately.",
    "Cementing":              "Prepare technical offer for liner cementing services.",
    "MWD / Directional":      "Schedule technical discussion with directional supervisor.",
    "Solids Control":         "Propose solids control package to mud engineer on location.",
    "Well Testing":           "Prepare well testing package proposal for upcoming flowback/clean-up.",
    "Wireline / Logging":     "Contact wireline supervisor and prepare TLC/RDT tool offer.",
    "H2S / Safety":           "Submit H2S monitoring package proposal to HSE supervisor.",
    "Rental / Intervention":  "Contact rig superintendent with rental equipment catalogue.",
}

# ── Opportunity title builder ─────────────────────────────────────────────────
# Title maps keyed by product_line — uses matched keywords, not evidence text
PL_TITLE_MAP = {
    "Completion": [
        (r"Baker\s+SCT",                       "SCT Completion Running Tools"),
        (r"GRE\s+lined|GRE\s+tubing",          "GRE Lined Tubing Completion"),
        (r"monobore",                             "Monobore Completion String"),
        (r"completion\s+string|5-?1/2.*?compl",  "Completion String Running"),
        (r"upper\s+completion|ICV|ICDS|SSDS",    "Smart Well Completion"),
        (r"retrievable\s+packer|7.*?packer",      "Completion Packer"),
        (r"liner\s+hanger",                      "Liner Hanger Running"),
        (r"ESP.*?Y-TOOL|ESP.*?completion",         "ESP / Smart Well Completion"),
        (r"completion",                            "Completion Services"),
    ],
    "MWD / Directional": [
        (r"SLB.*?(?:NEOSTEER|ORBIT|PowerDrive)",   "SLB RSS / Directional Drilling"),
        (r"RSS\s+(?:BHA|tool)|ROTARY\s+STEER",   "RSS Directional Drilling"),
        (r"BHI\s+MWD|Baker.*?MWD",               "Baker MWD Services"),
        (r"LWD\s+(?:tool|run|data)",              "LWD / Formation Evaluation"),
        (r"MWD\s+(?:ASSY|tool|survey)",           "MWD Survey Services"),
        (r"directional\s+drill",                   "Directional Drilling"),
        (r"GWD\s+BHA",                            "GWD / Directional BHA"),
    ],
    "Fishing / Intervention": [
        (r"fish\s+in\s+hole|1st\s+fish|2nd\s+fish",  "Active Fishing Job"),
        (r"stuck\s+pipe",                          "Stuck Pipe / Fishing"),
        (r"whipstock|milling\s+window",            "Whipstock / Sidetrack"),
        (r"overshot|spear",                         "Fishing Tool Run"),
        (r"reaming\s+(?:trip|BHA)",                "Reaming Trip / Intervention"),
    ],
    "Cementing": [
        (r"liner\s+cement",                        "Liner Cementing"),
        (r"primary\s+cement",                      "Primary Cementing"),
        (r"squeeze\s+cement",                      "Squeeze Cementing"),
        (r"OEDP\s+cement|cement\s+stinger",       "OEDP Cement Job"),
        (r"cement\s+(?:job|plug)",                 "Cement Job"),
        (r"5\.5.*?cement|5-?1/2.*?cement",         "Completion Cementing"),
    ],
    "Wireline / Logging": [
        (r"Baker\s+TLC|Baker\s+RDT",              "Baker TLC / RDT Logging"),
        (r"pressure\s+point",                      "Pressure Point Survey"),
        (r"fluid\s+sampling",                      "Fluid Sampling / RDT"),
        (r"open\s+hole\s+log",                    "Open Hole Logging"),
        (r"wireline|slickline",                     "Wireline Services"),
    ],
    "Well Testing": [
        (r"flowback",                               "Flowback / Clean-up Testing"),
        (r"\bDST\b|drill\s+stem\s+test",        "DST Well Testing"),
        (r"well\s+test|production\s+test",        "Well Testing"),
    ],
    "H2S / Safety": [
        (r"Rawabi\s+H2S",                          "Rawabi H2S Monitoring Package"),
        (r"H2S\s+monitoring|H2S\s+detection",     "H2S Monitoring Package"),
    ],
    "Solids Control": [
        (r"centrifuge",                             "Centrifuge / Solids Control"),
        (r"barite\s+recovery",                     "Barite Recovery Unit"),
        (r"solids\s+control",                      "Solids Control Services"),
    ],
    "Rental / Intervention": [
        (r"frac\s+tank",                           "Frac Tank Rental"),
        (r"PBL\s+sub",                             "PBL Sub Rental"),
        (r"tubular\s+running",                     "Tubular Running Tools"),
        (r"NAPESCO\s+HMJ",                         "NAPESCO HMJ Rental"),
    ],
}

def _build_title(product_line: str, matched_keywords: list, evidence: str, rig: str, well: str) -> str:
    """Build title from matched keywords (product-line-specific), not generic evidence scan."""
    rules = PL_TITLE_MAP.get(product_line, [])
    # Check matched keywords first (most precise)
    kw_text = " ".join(matched_keywords)
    for pat, label in rules:
        if re.search(pat, kw_text, re.IGNORECASE):
            return f"{label} – {rig}/{well}"
    # Fallback: check evidence but only with product-line rules (not cross-PL)
    for pat, label in rules:
        if re.search(pat, evidence, re.IGNORECASE):
            return f"{label} – {rig}/{well}"
    return f"{product_line} Opportunity – {rig}/{well}"


@dataclass
class Opportunity:
    title: str
    product_line: str
    rig: str
    well: str
    field: str
    confidence: int
    estimated_value: float
    urgency: str
    timing_label: str
    stage: str
    status: str = "open"
    competitor: str = ""
    evidence_text: str = ""
    evidence_section: str = ""
    matched_keywords: List[str] = dc_field(default_factory=list)
    action: str = ""
    suggested_contact: str = ""
    what_we_sell: str = ""
    win_probability: float = 0.0
    rank: int = 0


def _clean_ctx(ctx: str) -> str:
    """Normalize whitespace and strip stray leading punctuation from sliced context."""
    ctx = re.sub(r"\s+", " ", ctx).strip()
    return re.sub(r"^[^A-Za-z0-9$(]+", "", ctx)


# ── Closed-window detection (MWD / Directional) ──────────────────────────────
# If the directional toolstring is being pulled / laid down, the directional
# window on THIS well has closed — the realistic play is the rig's NEXT well,
# not an immediate call about the current one.
DIRECTIONAL_CLOSING_PATTERNS = [
    r"POOH\b.{0,80}\bL/?D\b",
    r"\bL/?D\b.{0,50}\b(?:RSS|BHA|MTR|MWD)\b",
    r"LAY\s+DOWN.{0,40}\b(?:RSS|BHA|MTR)\b",
    r"LAID\s+DOWN.{0,40}\b(?:RSS|BHA)\b",
    r"RIG\s+RELEASE",
    r"RETRIEVED\s+WB",
]

def _directional_window_closing(ctx: str) -> bool:
    return any(re.search(p, ctx, re.IGNORECASE) for p in DIRECTIONAL_CLOSING_PATTERNS)


def _check_exclusions(rule: PLRule, text: str) -> bool:
    """Returns True if text is excluded (should NOT create opportunity)."""
    for ex_pat in rule.exclusion_patterns:
        if re.search(ex_pat, text, re.IGNORECASE):
            return True
    return False


def _score(rule: PLRule, matches_by_section: Dict[str, list], match_kws: List[str]) -> int:
    """
    v3.1: discriminating score — never returns 100 (no extraction is certain).
    Range in practice: 65–97.
    """
    base = 65  # raised from 60 — require more signal

    # High-value pattern bonus
    for hv_pat in rule.high_value_patterns:
        for kw in match_kws:
            if re.search(hv_pat, kw, re.IGNORECASE):
                base = max(base, 86)
                break

    # Multiple matches in high-priority sections → higher confidence
    foreman_hits = len(matches_by_section.get("Foreman Remarks", []))
    next24_hits  = len(matches_by_section.get("Next 24h Plan", []))
    if foreman_hits >= 2 or next24_hits >= 2:
        base = max(base, 80)
    if foreman_hits >= 1 and next24_hits >= 1:
        base = max(base, 84)

    # Section weight bonuses — capped at +8 total
    total_bonus = 0
    for sec in matches_by_section.keys():
        b = rule.section_weights.get(sec, 0)
        total_bonus = min(total_bonus + b, 8)

    # Corroboration bonus: distinct keyword variety (up to +3)
    distinct = len(set(k.lower().strip() for k in match_kws))
    corroboration = min(3, max(0, distinct - 1))

    return min(97, base + total_bonus + corroboration)


def detect_opportunities(sections: list, rig: str, well: str, field: str,
                         competitor_mentions: list) -> List[Opportunity]:
    opps: List[Opportunity] = []
    seen_pl = set()

    for rule in PRODUCT_LINE_RULES:
        matches_by_section: Dict[str, list] = {}

        for sec in sections:
            sec_name = sec.name if hasattr(sec, 'name') else sec.get('name', '')
            sec_text = sec.text if hasattr(sec, 'text') else sec.get('text', '')

            # Section restriction check
            if rule.require_sections and sec_name not in rule.require_sections:
                continue

            for pat in rule.primary_patterns:
                for m in re.finditer(pat, sec_text, re.IGNORECASE):
                    kw  = m.group(0)
                    s   = max(0, m.start() - 120)
                    if s > 0:  # avoid cutting mid-word (e.g. "OBJECTIVE" → "JECTIVE")
                        sp = sec_text.find(" ", s)
                        if 0 <= sp < m.start():
                            s = sp + 1
                    e   = min(len(sec_text), m.end() + 120)
                    ctx = _clean_ctx(sec_text[s:e])

                    # Per-match exclusion check
                    if _check_exclusions(rule, ctx):
                        continue

                    if sec_name not in matches_by_section:
                        matches_by_section[sec_name] = []
                    matches_by_section[sec_name].append((ctx, kw))

        if not matches_by_section:
            continue

        pl_key = (rule.product_line, rig, well)
        if pl_key in seen_pl:
            continue
        seen_pl.add(pl_key)

        all_matches  = [(ctx, kw) for mlist in matches_by_section.values() for ctx, kw in mlist]
        all_kws      = [kw for _, kw in all_matches]
        all_ctx      = " ".join(ctx for ctx, _ in all_matches[:3])

        # Global exclusion check on combined context
        if _check_exclusions(rule, all_ctx):
            continue

        confidence   = _score(rule, matches_by_section, all_kws)
        if confidence < 65:
            continue
        # Require at least 2 distinct keyword matches for 65-74% confidence
        # Prevents single-word false positives like ADC-34 cementing
        # Require ≥2 matches for low confidence, EXCEPT:
        # - abbreviation matches (raw keyword has format "ABC (Company)") are high-quality
        # - or the evidence contains "on loc/rigged up" which confirms physical presence
        is_abbrev_match = any('(' in kw and ')' in kw for kw in all_kws)
        is_confirmed_onloc = any(re.search(r'on\s+loc|rigged?\s+up|on\s+location', ctx, re.IGNORECASE)
                                  for ctx, _ in all_matches)
        if confidence < 75 and len(all_matches) < 2 and not is_abbrev_match and not is_confirmed_onloc:
            continue

        sections_hit = list(matches_by_section.keys())

        # Urgency: highest-priority section
        urgency = "future"
        for sec_pri in ["Next 24h Plan","Foreman Remarks","Last 24h Operations",
                        "Service Companies & Rental Tools","Equipment on Location","Next Location"]:
            if sec_pri in sections_hit:
                urgency = SECTION_URGENCY[sec_pri]
                break

        best_sec = sections_hit[0]
        evidence_ctx = all_matches[0][0]

        # ── Closed-window check: directional tools being laid down means the
        #    directional phase on this well just ENDED — retarget to next well.
        window_closing = (
            rule.product_line == "MWD / Directional"
            and _directional_window_closing(evidence_ctx)
        )
        action_override = ""
        if window_closing:
            urgency = "30_days"
            action_override = ("Directional window on this well is closing (tools being "
                               "laid down) — position MWD/directional package for the rig's NEXT well.")

        # ── Future-dated operation check: "WILL BE COMPLETED ... IN 95 DAYS" is a
        #    forward objective statement, not a near-term job. Downgrade urgency.
        m_future = re.search(r"\bIN\s+(\d{1,3})\s+DAYS\b", evidence_ctx, re.IGNORECASE)
        if m_future:
            days_out = int(m_future.group(1))
            if days_out > 30 and urgency in ("immediate", "5_days", "7_days", "30_days"):
                urgency = "future"
                action_override = action_override or (
                    f"Operation is ~{days_out} days out per the report — schedule early "
                    f"positioning and follow up closer to the date; not an immediate call.")
            elif days_out > 7 and urgency in ("immediate", "5_days", "7_days"):
                urgency = "30_days"
                action_override = action_override or (
                    f"Operation is ~{days_out} days out per the report — prepare offer "
                    f"and contact within the coming weeks.")

        # ── Competitor assignment: category-matched + validated ───────────────
        # Rules:
        # 1. Match competitor's service_category to the opportunity's product line
        # 2. Validate that the matched company actually does that product line
        # 3. Prefer competitors found in the same section as the evidence
        # 4. Fall back to broader match only if no category match found
        # 5. Never assign a competitor that can't do this product line

        # Category families per product line
        PL_COMP_CATS = {
            "Completion":             {"Completion","Completion Running Tools","Oilfield Services"},
            "Fishing / Intervention": {"Fishing / Intervention","Oilfield Services","Rental / Intervention"},
            "Cementing":              {"Cementing","Oilfield Services"},
            "MWD / Directional":      {"MWD / Directional","RSS / Directional","LWD / Formation Evaluation"},
            "Solids Control":         {"Solids Control","Drilling Fluids"},
            "Well Testing":           {"Well Testing","Oilfield Services"},
            "Wireline / Logging":     {"Wireline / Logging","Slickline"},
            "H2S / Safety":           {"H2S / Safety"},
            "Rental / Intervention":  {"Rental / Intervention","Oilfield Services"},
        }

        # Companies validated to operate in each product line (from Aramco SC database)
        PL_VALID_COMPS = {
            "Completion":             {"SLB","Baker Hughes","Halliburton","Weatherford","NOV","NESR","AlMansoori","Coretrax","Franks","Oilserv (Zamil)","Rawabi","Rawabi O&G","Innovex","TIW","Well Dynamic Energy","WIS (Wellbore Integrity)","Sapesco","TAQA Group","Expro"},
            "Fishing / Intervention": {"SLB","Baker Hughes","Halliburton","Weatherford","NESR","AlMansoori","Coretrax","Rawabi O&G","Rawabi","Rawabi United","WIS (Wellbore Integrity)","Gulf Energy","Oilserv (Zamil)","Arabian Est. Fishing"},
            "Cementing":              {"SLB","Baker Hughes","Halliburton","Weatherford","NESR","TAQA Group","Oilserv (Zamil)","Wellcem"},
            "MWD / Directional":      {"SLB","Baker Hughes","Halliburton","Weatherford","NOV","NESR","TAQA Group","Oilserv (Zamil)","Nabors","Scientific Drilling","Gas & Oil Technologies","Sapesco","GDMC"},
            "Solids Control":         {"SLB","Baker Hughes","Halliburton","Weatherford","NOV","Gulf Energy","Sinopec","AlMansoori"},
            "Well Testing":           {"SLB","Baker Hughes","Halliburton","Weatherford","Expro","NESR","AlMansoori","Oilserv (Zamil)","Mohamed Barwani","SGS","Tetra","Power Well Services","Well Flow"},
            "Wireline / Logging":     {"SLB","Baker Hughes","Halliburton","Weatherford","NESR","TAQA Group","Oilserv (Zamil)","GDMC","Bureau Geophysical"},
            "H2S / Safety":           {"Rawabi","Rawabi United","Rawabi Trading","Rawabi O&G","Sinopec","NAPESCO","NESR","AlMansoori","Total Safety Company"},
            "Rental / Intervention":  {"SLB","Baker Hughes","Halliburton","Weatherford","NOV","NESR","NAPESCO","AlMansoori","Oilserv (Zamil)","Franks","Rawabi","TAQA Group","Tetra","Well Dynamic Energy","Sapesco"},
        }

        rel_cats   = PL_COMP_CATS.get(rule.product_line, set())
        valid_cos  = PL_VALID_COMPS.get(rule.product_line, set())

        def _comp_score(cm):
            """Score a competitor mention for relevance to this product line. Higher = better."""
            cm_norm = cm.normalized if hasattr(cm, 'normalized') else cm.get('normalized','')
            cm_cat  = cm.service_category if hasattr(cm, 'service_category') else cm.get('service_category','')
            cm_sec  = cm.section if hasattr(cm, 'section') else cm.get('section','')
            score   = 0
            # Category match — primary filter
            if any(rc.lower() in cm_cat.lower() or cm_cat.lower() in rc.lower() for rc in rel_cats):
                score += 30
            # Valid competitor for this product line
            if cm_norm in valid_cos:
                score += 20
            # Same section as evidence
            if cm_sec in sections_hit:
                score += 10
            # High-priority section
            if cm_sec == "Foreman Remarks": score += 5
            elif cm_sec == "Next 24h Plan": score += 4
            return score

        comp = ""
        if competitor_mentions:
            # Score all candidates
            scored = [(cm, _comp_score(cm)) for cm in competitor_mentions]
            # Filter: must have category match OR be in valid list for this PL
            # Minimum score = 20 (valid company) to avoid completely wrong assignments
            candidates = [(cm, s) for cm, s in scored if s >= 30]  # must have category match
            if candidates:
                best_cm = max(candidates, key=lambda x: x[1])[0]
                comp = best_cm.normalized if hasattr(best_cm, 'normalized') else best_cm.get('normalized','')
            # If no candidate passes the threshold, leave competitor blank
            # (blank is better than wrong)


        title = _build_title(rule.product_line, all_kws, all_ctx, rig, well)
        val   = estimate_value(rule.product_line, confidence, urgency)

        # Win probability: reduced if dominant competitor already on location
        base_win_prob = URGENCY_PROBABILITY.get(urgency, 0.3)
        # If competitor is confirmed on location doing the SAME service, our prob drops
        comp_penalty = 0.0
        if comp:
            major_competitors = ['SLB', 'Baker Hughes', 'Halliburton']
            if any(c in comp for c in major_competitors):
                # Major competitor on location = harder displacement = lower win prob
                # But still worth positioning for next well / complementary products
                comp_penalty = 0.20
        win_prob = round(max(0.05, base_win_prob - comp_penalty), 2)

        opps.append(Opportunity(
            title=title,
            product_line=rule.product_line,
            rig=rig,
            well=well,
            field=field,
            confidence=confidence,
            estimated_value=val,
            urgency=urgency,
            timing_label=("Window closing – position for next well" if window_closing
                          else (f"~{m_future.group(1)} days out – schedule positioning" if (m_future and int(m_future.group(1)) > 7 and action_override)
                          else TIMING_LABELS[urgency])),
            stage=("Directional Phase Ending → Next Well" if window_closing
                   else _infer_stage(sections_hit, evidence_ctx)),
            competitor=comp,
            evidence_text=evidence_ctx,
            evidence_section=best_sec,
            matched_keywords=all_kws[:5],
            action=action_override or ACTIONS.get(rule.product_line, "Prepare commercial offer."),
            suggested_contact=CONTACT_ROLES.get(rule.product_line, "Technical Sales"),
            what_we_sell=PRODUCT_LINE_WHAT_WE_SELL.get(rule.product_line, ""),
            win_probability=round(win_prob * (confidence / 100), 2),
        ))

    urgency_order = {"immediate":0,"5_days":1,"7_days":2,"30_days":3,"future":4}
    opps.sort(key=lambda o: (-o.confidence, urgency_order.get(o.urgency, 9)))
    for i, o in enumerate(opps, 1):
        o.rank = i
    return opps


def _infer_stage(sections_hit, ctx):
    ctx_l = ctx.lower()
    if re.search(r"completion|packer|tubing|SCT|monobore|ICV", ctx_l):
        return "Lateral Drilling → Completion"
    if re.search(r"fish|stuck|remedial|whipstock", ctx_l):
        return "Drilling → Intervention"
    if re.search(r"logging|wireline|TLC|RDT|pressure\s+point", ctx_l):
        return "Completion → Logging"
    if re.search(r"liner\s+cement|CMT\s+JOB|cement\s+plug", ctx_l):
        return "Drilling → Cementing"
    if re.search(r"flowback|well\s+test|clean.up", ctx_l):
        return "Completion → Production/Testing"
    if re.search(r"RSS|directional|MWD\s+ASSY", ctx_l):
        return "Drilling – Directional Phase"
    return "Active Operations"
