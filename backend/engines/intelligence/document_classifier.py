"""
EIP v5.1 — Enterprise Data Layer Document Classifier
Classifies uploaded documents beyond DDR: RFQs, Tenders, Completion Reports,
Workover Reports, Well Testing Reports, Procurement Notices.

Every document type feeds the same intelligence layer — the extraction
strategy differs but the opportunity output is identical.
"""
import re
from dataclasses import dataclass
from typing import List, Optional

@dataclass
class DocumentClassification:
    doc_type: str          # ddr | lmr | rfq | tender | completion | workover | well_test | procurement | unknown
    doc_type_label: str    # Human-readable label
    confidence: float      # 0.0-1.0
    report_date: str
    subject: str           # Extracted subject/title if any
    signals: List[str]     # Matched classification signals

# ── Classification signals per document type ──────────────────────────────────
CLASSIFIERS = [
    {
        "doc_type":  "lmr",
        "label":     "Limited Morning Report (LMR)",
        "patterns":  [
            r"limited\s+morning\s+report",
            r"\bLMR\b",
        ],
        "weight": 1.0,
    },
    {
        "doc_type":  "ddr",
        "label":     "Daily Drilling Report (DDR)",
        "patterns":  [
            r"daily\s+drilling\s+report",
            r"\bDDR\b",
            r"foreman\s+remarks",
            r"last\s+24h?\s+operations?",
            r"next\s+24h?\s+plan",
            r"drilling\s+parameters",
        ],
        "weight": 0.9,
    },
    {
        "doc_type":  "rfq",
        "label":     "Request for Quotation (RFQ)",
        "patterns":  [
            r"request\s+for\s+quotat?ion",
            r"\bRFQ\b",
            r"request\s+for\s+proposal",
            r"\bRFP\b",
            r"please\s+quote",
            r"submission\s+deadline",
            r"bid\s+submission",
            r"technical\s+bid",
            r"commercial\s+bid",
        ],
        "weight": 1.0,
    },
    {
        "doc_type":  "tender",
        "label":     "Tender / Invitation to Bid",
        "patterns":  [
            r"invitation\s+to\s+(tender|bid)",
            r"\bITB\b",
            r"tender\s+document",
            r"scope\s+of\s+work",
            r"contract\s+requirements",
            r"bidder.*qualification",
            r"tender\s+no\.?\s*\d+",
            r"saudi\s+aramco.*tender",
        ],
        "weight": 1.0,
    },
    {
        "doc_type":  "completion",
        "label":     "Completion Report",
        "patterns":  [
            r"completion\s+report",
            r"final\s+completion",
            r"well\s+completion\s+summary",
            r"liner\s+cement",
            r"perforation.*completion",
            r"completion\s+string",
        ],
        "weight": 0.9,
    },
    {
        "doc_type":  "workover",
        "label":     "Workover Report",
        "patterns":  [
            r"workover\s+report",
            r"work-?over\s+summary",
            r"recompletion",
            r"well\s+intervention\s+report",
            r"stimulation\s+report",
        ],
        "weight": 0.9,
    },
    {
        "doc_type":  "well_test",
        "label":     "Well Testing Report",
        "patterns":  [
            r"well\s+test(?:ing)?\s+report",
            r"drill\s+stem\s+test",
            r"\bDST\s+report",
            r"flow\s+test\s+results",
            r"production\s+test",
            r"inflow\s+performance",
        ],
        "weight": 0.9,
    },
    {
        "doc_type":  "procurement",
        "label":     "Procurement Notice",
        "patterns":  [
            r"procurement\s+notice",
            r"purchase\s+order",
            r"\bPO\b.*issued",
            r"approved\s+vendor",
            r"material\s+requisition",
            r"delivery\s+order",
        ],
        "weight": 0.8,
    },
]

# ── Date extraction ────────────────────────────────────────────────────────────
DATE_PATTERNS = [
    r"(\d{1,2}[/-]\d{1,2}[/-]\d{4})",
    r"(\d{4}[/-]\d{1,2}[/-]\d{1,2})",
    r"((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*\s+\d{1,2},?\s+\d{4})",
    r"(\d{1,2}\s+(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{4})",
]


def classify_document(text: str, filename: str = "") -> DocumentClassification:
    """Classify a document from its text content and filename."""
    text_lower   = text.lower()
    filename_low = filename.lower()
    best_type    = "unknown"
    best_label   = "Unknown Document"
    best_conf    = 0.0
    matched_sigs = []

    for clf in CLASSIFIERS:
        hits = 0
        sigs = []
        for pat in clf["patterns"]:
            if re.search(pat, text_lower, re.IGNORECASE):
                hits += 1
                sigs.append(pat)
        if hits > 0:
            conf = min(1.0, (hits / len(clf["patterns"])) * clf["weight"] + 0.3)
            if conf > best_conf:
                best_conf   = conf
                best_type   = clf["doc_type"]
                best_label  = clf["label"]
                matched_sigs= sigs[:3]

    # Filename hints can boost confidence
    fn_boosts = {
        "lmr": ["lmr","morning_report"],
        "ddr": ["ddr","drilling_report","drilling_daily"],
        "rfq": ["rfq","request_for_quot","rfp"],
        "tender": ["tender","itb","invitation_to_bid"],
        "completion": ["completion","completion_report"],
        "workover": ["workover","work_over","intervention"],
        "well_test": ["well_test","dst","flow_test"],
        "procurement": ["po_","purchase_order","procurement"],
    }
    for dtype, hints in fn_boosts.items():
        if any(h in filename_low for h in hints):
            if dtype == best_type:
                best_conf = min(1.0, best_conf + 0.2)
            elif best_conf < 0.5:
                # File name overrides weak text match
                best_type  = dtype
                for clf in CLASSIFIERS:
                    if clf["doc_type"] == dtype:
                        best_label = clf["label"]
                best_conf  = 0.55

    # Extract report date
    report_date = ""
    for dp in DATE_PATTERNS:
        m = re.search(dp, text[:2000])
        if m:
            report_date = m.group(1)
            break

    # Extract subject/title (first meaningful line)
    lines  = [l.strip() for l in text[:500].split("\n") if len(l.strip()) > 10]
    subject = lines[0][:100] if lines else filename

    return DocumentClassification(
        doc_type       = best_type,
        doc_type_label = best_label,
        confidence     = round(best_conf, 2),
        report_date    = report_date,
        subject        = subject,
        signals        = matched_sigs,
    )


def extraction_strategy(doc_type: str) -> dict:
    """
    Return the extraction strategy hints for a document type.
    These guide the ingestion pipeline on what sections to look for.
    """
    strategies = {
        "ddr":         {"primary_sections": ["Foreman Remarks","Next 24h Plan","Last 24h Operations"],
                        "look_for": ["rigs","competitors","product_lines","lifecycle"]},
        "lmr":         {"primary_sections": ["Foreman Remarks","Next 24h Plan","Last 24h Operations"],
                        "look_for": ["rigs","competitors","product_lines","lifecycle"]},
        "rfq":         {"primary_sections": ["Scope of Work","Requirements","Technical Specs"],
                        "look_for": ["product_lines","customer","timeline","budget"],
                        "opportunity_type": "rfq"},
        "tender":      {"primary_sections": ["Scope","Requirements","Submission"],
                        "look_for": ["product_lines","customer","timeline"],
                        "opportunity_type": "tender"},
        "completion":  {"primary_sections": ["Summary","Operations","Results"],
                        "look_for": ["product_lines","rig","well","lifecycle"]},
        "workover":    {"primary_sections": ["Objective","Operations","Results"],
                        "look_for": ["product_lines","rig","well","competitors"]},
        "well_test":   {"primary_sections": ["Test Summary","Results","Recommendations"],
                        "look_for": ["product_lines","rig","well"]},
        "procurement": {"primary_sections": ["Items","Specifications","Delivery"],
                        "look_for": ["product_lines","customer","timeline"]},
    }
    return strategies.get(doc_type, {"primary_sections":[], "look_for":[]})
