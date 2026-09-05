"""
EnergiPro – Rig Lifecycle Classification Engine
"""
import re
from dataclasses import dataclass, field as dc_field
from typing import Optional, List

@dataclass
class LifecycleResult:
    rig: str
    well: str
    current_stage: str
    sub_stage: str
    next_stage: str
    transition_signal: str
    timing_estimate: str
    confidence: int
    evidence: str
    expected_product_lines: List[str] = dc_field(default_factory=list)
    next_well: str = ""
    readiness_pct: int = 0
    commercial_rec: str = ""


STAGE_RULES = [
    # ── COMPLETION signals ────────────────────────────────────────────────
    ("Completion", "Liner / Tubing Running", [
        r"completion\s+string", r"GRE\s+lined\s+tubing", r"Baker\s+SCT",
        r"liner\s+hanger", r"tubing\s+running", r"4[\-\s]?1/2.*?completion",
        r"SLB.*?intermediate\s+completion",
    ], ["Fishing / Intervention", "Cementing", "Wireline / Logging"]),
    ("Completion", "Packer Setting", [
        r"\bpacker\b", r"retrievable\s+packer", r"Halliburton.*?packer",
        r"production\s+packer",
    ], ["Well Testing", "Wireline / Logging"]),
    # ── INTERVENTION signals ──────────────────────────────────────────────
    ("Intervention", "Fishing", [
        r"fish\s+in\s+hole", r"1st\s+fish", r"2nd\s+fish",
        r"\bovershot\b", r"\bspear\b",
    ], ["Fishing / Intervention", "MWD / Directional"]),
    ("Intervention", "Whipstock / Milling", [
        r"\bwhipstock\b", r"milling\s+window", r"\bmill\b", r"sidetrack",
        r"WIS\s+whipstock",
    ], ["MWD / Directional", "Cementing"]),
    ("Intervention", "Reaming / Jar", [
        r"\bjar\b", r"\breaming\b", r"\bscraper\b",
    ], ["Fishing / Intervention"]),
    # ── DRILLING signals ──────────────────────────────────────────────────
    ("Drilling", "Lateral / Sidetrack", [
        r"\blateral\b", r"lateral\s+drilling", r"\bMWD\b", r"\bLWD\b",
        r"directional\s+drill",
    ], ["MWD / Directional", "Solids Control", "Cementing"]),
    ("Drilling", "Intermediate Hole", [
        r"intermediate\s+hole", r"surface\s+hole",
    ], ["MWD / Directional", "Cementing", "Solids Control"]),
    # ── WORKOVER / LOGGING ────────────────────────────────────────────────
    ("Workover / Logging", "Wireline Logging", [
        r"\bTLC\b", r"\bRDT\b", r"pressure\s+point", r"fluid\s+sampling",
        r"Baker\s+TLC",
    ], ["Wireline / Logging"]),
    ("Workover / Logging", "Coil / Slickline", [
        r"coil\s+tubing", r"\bslickline\b", r"\bwireline\b",
    ], ["Well Testing", "Wireline / Logging"]),
    # ── SOLIDS CONTROL / MUD ─────────────────────────────────────────────
    ("Drilling", "Solids Control Active", [
        r"\bcentrifuge\b", r"shale\s+shaker", r"barite\s+recovery",
    ], ["Solids Control"]),
    # ── PRODUCTION / TESTING ─────────────────────────────────────────────
    ("Production / Testing", "Flowback", [
        r"\bflowback\b", r"well\s+test", r"production\s+test", r"clean[\-\s]up",
    ], ["Well Testing", "Wireline / Logging"]),
]

NEXT_STAGE_MAP = {
    "Lateral / Sidetrack":       ("Completion",    ["Completion", "Cementing", "Fishing / Intervention"]),
    "Whipstock / Milling":       ("Lateral Drill",  ["MWD / Directional", "Solids Control"]),
    "Fishing":                   ("Resume Drilling", ["MWD / Directional", "Cementing"]),
    "Liner / Tubing Running":    ("Packer / Logging", ["Well Testing", "Wireline / Logging"]),
    "Packer Setting":            ("Production / Testing", ["Well Testing"]),
    "Wireline Logging":          ("Completion / Abandonment", ["Cementing"]),
    "Intermediate Hole":         ("Lateral Drilling", ["MWD / Directional"]),
    "Flowback":                  ("Production", []),
    "Solids Control Active":     ("Continue Drilling", ["Solids Control"]),
    "Coil / Slickline":          ("Well Testing", ["Well Testing"]),
    "Reaming / Jar":             ("Resume Drilling", ["MWD / Directional"]),
}

READINESS_PAT = re.compile(r"readiness[:\s]+([0-9]+)\s*%", re.IGNORECASE)
NEXT_WELL_PAT = re.compile(
    r"next\s+(?:well|loc(?:ation)?)[:\s]+([A-Z]{2,6}[\-\s]?[0-9]{2,4}[A-Z]?)", re.IGNORECASE
)


def classify_lifecycle(ddr) -> Optional[LifecycleResult]:
    all_text = " ".join([
        getattr(ddr, 'last_24h', ''),
        getattr(ddr, 'next_24h', ''),
        getattr(ddr, 'foreman_remarks', ''),
        getattr(ddr, 'service_companies', ''),
        getattr(ddr, 'equipment_on_location', ''),
        getattr(ddr, 'next_location', ''),
    ])

    best_stage = best_sub = best_evidence = ""
    best_conf  = 0
    best_pl    = []

    for stage, sub, patterns, prod_lines in STAGE_RULES:
        for pat in patterns:
            m = re.search(pat, all_text, re.IGNORECASE)
            if m:
                ctx_start = max(0, m.start() - 120)
                ctx_end   = min(len(all_text), m.end() + 120)
                evidence  = all_text[ctx_start:ctx_end].strip()
                # Weight by section – foreman remarks = higher confidence
                conf = 80
                for sec in getattr(ddr, 'sections', []):
                    sn = sec.name if hasattr(sec, 'name') else sec.get('name', '')
                    st = sec.text if hasattr(sec, 'text') else sec.get('text', '')
                    if re.search(pat, st, re.IGNORECASE) and sn == "Foreman Remarks":
                        conf = 95
                        break
                    elif re.search(pat, st, re.IGNORECASE) and sn == "Next 24h Plan":
                        conf = 90
                        break

                if conf > best_conf:
                    best_conf  = conf
                    best_stage = stage
                    best_sub   = sub
                    best_evidence = evidence
                    best_pl    = prod_lines

    if not best_stage:
        return None

    next_stage_info = NEXT_STAGE_MAP.get(best_sub, ("Unknown", []))
    next_stage  = next_stage_info[0]
    next_pl     = best_pl + [p for p in next_stage_info[1] if p not in best_pl]

    # Next well
    nw_match = NEXT_WELL_PAT.search(getattr(ddr, 'next_location', ''))
    next_well = nw_match.group(1) if nw_match else ""

    # Readiness
    rd_match = READINESS_PAT.search(getattr(ddr, 'next_location', ''))
    readiness = int(rd_match.group(1)) if rd_match else 0

    # Commercial rec
    if readiness >= 71:
        rec = f"Act now – position services for {next_well or 'next well'} before rig arrival."
    elif readiness >= 31:
        rec = f"Prepare positioning plan for {next_well or 'upcoming well'}."
    elif next_well:
        rec = f"Monitor {next_well} – begin early commercial approach."
    else:
        rec = f"Engage {best_stage} services immediately on {getattr(ddr, 'rig', '')}."

    timing = "5–10 days" if best_conf >= 90 else "10–20 days"

    return LifecycleResult(
        rig=getattr(ddr, 'rig', ''),
        well=getattr(ddr, 'well', ''),
        current_stage=best_stage,
        sub_stage=best_sub,
        next_stage=next_stage,
        transition_signal=best_evidence[:300],
        timing_estimate=timing,
        confidence=best_conf,
        evidence=best_evidence[:300],
        expected_product_lines=list(dict.fromkeys(next_pl)),
        next_well=next_well,
        readiness_pct=readiness,
        commercial_rec=rec,
    )
