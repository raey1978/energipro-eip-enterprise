"""
EIP DDR Intelligence v4.4 — Market Intelligence Ingestion Pipeline
Orchestrates: DDR parsing → competitor detection → product line detection
             → lifecycle classification → opportunity scoring → narrative
Wave 2: source traceability (page, file, section) per opportunity
"""
import io, uuid, datetime, hashlib
from dataclasses import asdict
from typing import List, Dict, Any

try:
    import pdfplumber
    HAS_PDF = True
except ImportError:
    HAS_PDF = False

from engines.nlp.ddr_extractor       import parse_pdf_text, ExtractedDDR
from engines.nlp.company_mapper       import extract_competitors
from engines.nlp.product_line_engine  import detect_opportunities, Opportunity
from engines.nlp.lifecycle_engine     import classify_lifecycle


def _safe_asdict(obj) -> dict:
    try:
        return asdict(obj)
    except Exception:
        return obj.__dict__ if hasattr(obj, '__dict__') else {}


def extract_text_from_pdf(pdf_bytes: bytes, enable_ocr: bool = None, ocr_lang: str = None) -> tuple:
    """
    Extract text with page map AND quality report.
    Returns (full_text, page_map, quality_report).
    v6.3C: uses DocumentProcessor with OCR fallback, rotation detection, quality gate.
    Backward-compatible: same return signature as before.
    """
    import os
    from core.database import get_settings
    from engines.document_processor import classify_and_extract

    # Read OCR settings from environment / settings table
    if enable_ocr is None:
        settings = get_settings()
        ocr_setting = settings.get("ocr_enabled","true")
        enable_ocr = str(ocr_setting).lower() not in ("false","0","no","disabled")
        # Also check environment variable override
        env_ocr = os.environ.get("OCR_ENABLED","")
        if env_ocr: enable_ocr = env_ocr.lower() not in ("false","0","no")

    if ocr_lang is None:
        settings = get_settings() if 'settings' not in dir() else settings
        ocr_lang = os.environ.get("OCR_LANG","") or settings.get("ocr_lang","eng") or "eng"

    # Validate OCR language availability
    if enable_ocr and ocr_lang != "eng":
        try:
            import pytesseract
            available_langs = pytesseract.get_languages(config='')
            if ocr_lang not in available_langs and f"{ocr_lang}" not in " ".join(available_langs):
                import logging
                logging.getLogger("eip.ingestion").warning(
                    f"OCR language '{ocr_lang}' not installed. "
                    f"Available: {available_langs}. Falling back to 'eng'."
                )
                ocr_lang = "eng"
        except Exception:
            ocr_lang = "eng"

    result = classify_and_extract(pdf_bytes, enable_ocr=enable_ocr, ocr_lang=ocr_lang)

    # Build backward-compatible page_map {page_num: text}
    page_map = result.page_texts

    # Build backward-compatible quality report
    extraction_quality = (
        "high"   if result.quality_score >= 70 else
        "medium" if result.quality_score >= 45 else
        "low"
    )

    _page_quality = {
        pr.page_number: {
            "method": pr.extraction_method,
            "quality": pr.quality,
            "score":   pr.quality_score,
            "words":   pr.word_count,
            "ocr_confidence": round(pr.ocr_confidence, 2),
        }
        for pr in result.page_results
    }

    # ── CANONICAL QUALITY SCHEMA (v6.3D contract repair) ──────────────────────
    # This dict is the ONE quality contract consumed by run_pipeline,
    # api/routes/reports.py, and core/database.py (document_ingestion_log).
    # Every DocumentProcessor return path flows through here, so every key
    # below is guaranteed present on every path (failed/encrypted/empty
    # documents carry word_count=0 etc. — real values, never fabricated).
    # Legacy v6.3C names (total_words/total_pages/extraction_quality/ocr_used)
    # are retained alongside canonical names for backward compatibility.
    quality = {
        # Canonical names (consumed by run_pipeline:408, reports.py, database.py)
        "document_type":     result.document_type,
        "extraction_status": result.extraction_status,
        "word_count":        result.total_words,
        "page_count":        result.page_count,
        "quality_score":     result.quality_score,
        "ocr_pages":         result.ocr_pages,
        "ocr_ratio":         round(result.ocr_pages / max(result.page_count, 1), 3),
        "ocr_required":      result.ocr_used,
        "extraction_confidence": extraction_quality,
        "warnings":          result.warnings,
        "page_quality":      _page_quality,
        # Legacy v6.3C names (kept — other consumers may reference them)
        "total_pages":       result.page_count,
        "total_words":       result.total_words,
        "total_chars":       result.total_chars,
        "extraction_quality": extraction_quality,
        "native_pages":      result.native_pages,
        "scanned_pages":     result.scanned_pages,
        "ocr_used":          result.ocr_used,
        "processing_ms":     result.processing_ms,
        "page_quality_summary": _page_quality,
    }

    # Hard failure gate — refuse to process documents with no extractable content
    if result.extraction_status == "failed" or result.total_words < 20:
        quality["critical_warning"] = (
            f"EXTRACTION FAILED: {result.total_words} words from {result.page_count} pages. "
            f"Document type: {result.document_type}. "
            + ("; ".join(result.warnings[:3]) if result.warnings else "")
        )
        return result.full_text, page_map, quality

    return result.full_text, page_map, quality


def find_source_page(evidence_text: str, page_map: dict) -> int:
    """Find which page an evidence snippet came from."""
    if not evidence_text or not page_map:
        return 0
    snippet = evidence_text[:80].strip().upper()
    for page_num, page_text in page_map.items():
        if snippet in page_text.upper():
            return page_num
    return 0


def generate_narrative(opps: List[Opportunity], competitor_mentions: list,
                       rigs_count: int, report_date: str) -> str:
    total_val = sum(o.estimated_value for o in opps)
    imm = [o for o in opps if o.urgency in ("immediate", "5_days")]
    comp_names = list(dict.fromkeys(
        (cm.normalized if hasattr(cm, 'normalized') else cm.get('normalized', ''))
        for cm in competitor_mentions
    ))[:5]
    top5 = opps[:5]

    top_opp_lines = ""
    for i, o in enumerate(top5, 1):
        top_opp_lines += (
            f"{i}. {o.title} ({o.product_line}, {o.rig}/{o.well}) — "
            f"Confidence {o.confidence}%, Est. ${o.estimated_value:,.0f}. "
            f"Action: {o.action} "
            f"Evidence: {o.evidence_text[:150]}... "
        )

    pl_counts: Dict[str, int] = {}
    for o in opps:
        pl_counts[o.product_line] = pl_counts.get(o.product_line, 0) + 1
    top_pl = sorted(pl_counts.items(), key=lambda x: -x[1])[:3]
    pl_str = ", ".join(f"{pl} ({cnt})" for pl, cnt in top_pl)

    narrative = (
        f"Report dated {report_date or 'latest'} identified {len(opps)} commercial "
        f"opportunities across {rigs_count} rig{'s' if rigs_count != 1 else ''} with an "
        f"estimated pipeline of ${total_val:,.0f}. "
        f"{len(imm)} opportunities require immediate or 5-day action. "
        f"Top product lines: {pl_str}. "
        f"Competitors active: {', '.join(comp_names) if comp_names else 'None identified'}. "
        f"\n\nTop 5 Opportunities:\n{top_opp_lines}"
        f"\n\nRecommended 7-day actions: "
    )
    for o in imm[:3]:
        narrative += f"• {o.action} on {o.rig}/{o.well}. "
    return narrative.strip()


def compute_confidence_breakdown(opp_dict: dict) -> dict:
    """
    Wave 2: Transparent confidence scoring breakdown.
    Returns per-factor scores and explanation.
    Weights: PL match 25%, Activity 20%, Rig clarity 15%,
             Competitor 15%, Evidence quality 15%, Recency 10%
    """
    conf   = opp_dict.get("confidence", 0)
    kws    = opp_dict.get("matched_keywords", [])
    comp   = opp_dict.get("competitor", "")
    urg    = opp_dict.get("urgency", "future")
    sec    = opp_dict.get("evidence_section", "")
    ev     = opp_dict.get("evidence_text", "")
    pl     = opp_dict.get("product_line", "")

    # Product line match (25 pts max)
    pl_score = 25 if pl and len(kws) >= 2 else 15 if pl and len(kws) == 1 else 0

    # Activity / lifecycle match (20 pts max)
    urgency_pts = {"immediate": 20, "5_days": 18, "7_days": 14, "30_days": 8, "future": 3}
    act_score = urgency_pts.get(urg, 5)

    # Rig / well / field clarity (15 pts max)
    rig_score = 15 if opp_dict.get("rig") and opp_dict.get("well") and opp_dict.get("field") else \
                10 if opp_dict.get("rig") and opp_dict.get("well") else 5

    # Competitor / company clarity (15 pts max)
    comp_score = 15 if comp else 5

    # Evidence quality (15 pts max)
    section_pts = {"Foreman Remarks": 15, "Next 24h Plan": 13, "Last 24h Operations": 10,
                   "Service Companies & Rental Tools": 8}
    ev_score = section_pts.get(sec, 5) if ev and len(ev) > 30 else 0

    # Recency (10 pts max)
    rec_score = 10 if urg in ("immediate","5_days") else 7 if urg == "7_days" else 3

    total = pl_score + act_score + rig_score + comp_score + ev_score + rec_score

    # Build explanation
    urg_label = {"immediate":"Immediate — next 24h","5_days":"Within 5 days",
                 "7_days":"Within 7 days","30_days":"Within 30 days","future":"Future"}
    explanation = (
        f"Product line match ({pl_score}/25): '{pl}' detected via keywords: "
        f"{', '.join(kws[:4]) if kws else 'none'}. "
        f"Activity signal ({act_score}/20): urgency '{urg_label.get(urg,urg)}' from "
        f"'{sec}' section. "
        f"Location clarity ({rig_score}/15): rig/well/field "
        f"{'all identified' if rig_score==15 else 'partially identified'}. "
        f"Competitor signal ({comp_score}/15): "
        f"{'competitor ' + comp + ' detected on location' if comp else 'no competitor identified — primary approach available'}. "
        f"Evidence quality ({ev_score}/15): extracted from '{sec}' section. "
        f"Recency ({rec_score}/10): based on timing urgency."
    )

    return {
        "pl_match":    pl_score,
        "activity":    act_score,
        "rig_clarity": rig_score,
        "competitor":  comp_score,
        "evidence":    ev_score,
        "recency":     rec_score,
        "total":       total,
        "explanation": explanation,
        "confidence_category": (
            "High Confidence" if total >= 80 else
            "Medium Confidence" if total >= 60 else
            "Low Confidence — Needs Review"
        ),
    }


def run_pipeline(pdf_bytes: bytes, filename: str) -> dict:
    """
    Main entry point.
    Returns a dict suitable for direct JSON serialization.
    Wave 3: quality report, content hash, source traceability.
    """
    # 0. Content hash for duplicate detection
    content_hash = hashlib.sha256(pdf_bytes).hexdigest()

    # 1. Extract text with page map and quality report
    raw_text, page_map, quality = extract_text_from_pdf(pdf_bytes)

    # ── V6.3D: HARD STOP — failed extraction must never produce intelligence ──
    _ext_status = quality.get("extraction_status","")
    _doc_type   = quality.get("document_type","")
    _tot_words  = quality.get("total_words",0) or len(raw_text.split())
    _BLOCKED_DT = {"corrupted","encrypted","unsupported","empty"}

    if _ext_status == "failed" or _doc_type in _BLOCKED_DT or _tot_words < 20:
        if _doc_type == "encrypted":
            _reason = "Failed — Protected Document"
            _detail = ("Password-protected document cannot be processed. "
                       "Remove the password before uploading.")
        elif _doc_type in ("corrupted","unsupported"):
            _reason = "Failed — Unsupported or Corrupted File"
            _detail = "File could not be read as a valid PDF."
        elif _tot_words < 20:
            _reason = "Failed — Insufficient Extractable Content"
            _detail = (f"Only {_tot_words} words extracted from "
                       f"{quality.get('total_pages',0)} pages. "
                       "Document may be scanned — enable OCR and reprocess.")
        else:
            _reason = "Failed — Extraction Error"
            _detail = "; ".join((quality.get("warnings") or [])[:2]) or "Extraction failed."
        return {
            "opportunities":[], "competitors":[], "lifecycle":[],
            "report_date":"","narrative":"","confidence_breakdown":{},
            "quality_report": quality,
            "extraction_failed": True,
            "extraction_status": _reason,
            "extraction_detail": _detail,
            "document_type":    _doc_type,
            "total_words_extracted": _tot_words,
            "error":   _reason,
            "warnings": quality.get("warnings",[]),
        }
    # ── END HARD STOP ─────────────────────────────────────────────────────────

    # ── V6.3D Phase 5: Scanned-heavy document warning ─────────────────────────
    _scanned_pages  = quality.get("scanned_pages", 0)
    _total_pages    = quality.get("total_pages", 1) or 1
    _scanned_ratio  = _scanned_pages / _total_pages
    _scanned_heavy  = _scanned_ratio > 0.50

    if _scanned_heavy:
        _ocr_quality_scores = [
            pr.get("score", 0)
            for pr in quality.get("page_quality_summary", {}).values()
            if pr.get("method") == "ocr"
        ]
        _avg_ocr_quality = (
            sum(_ocr_quality_scores) / len(_ocr_quality_scores)
            if _ocr_quality_scores else 0
        )
        if _avg_ocr_quality < 30:
            # OCR quality too low — block extraction, require review
            return {
                "opportunities":[], "competitors":[], "lifecycle":[],
                "report_date":"","narrative":"","confidence_breakdown":{},
                "quality_report": quality,
                "extraction_failed": True,
                "extraction_status": "Needs Review — Low OCR Confidence",
                "extraction_detail": (
                    f"{_scanned_pages}/{_total_pages} pages required OCR "
                    f"but average OCR quality is {_avg_ocr_quality:.0f}/100. "
                    "Review the document quality and consider uploading a higher-resolution scan."
                ),
                "document_type":    _doc_type,
                "scanned_heavy":    True,
                "total_words_extracted": _tot_words,
                "error": "Needs Review — Low OCR Confidence",
                "warnings": quality.get("warnings",[]) + [
                    f"Scanned-heavy document: {_scanned_pages}/{_total_pages} pages used OCR.",
                    f"Average OCR quality: {_avg_ocr_quality:.0f}/100. Minimum required: 30/100.",
                ],
            }
        # Scanned-heavy but OCR quality acceptable — add to quality report warnings
        quality.setdefault("warnings", [])
        if isinstance(quality.get("warnings"), list):
            quality["warnings"].append(
                f"SCANNED-HEAVY DOCUMENT: {_scanned_pages}/{_total_pages} pages ({_scanned_ratio:.0%}) "
                "required OCR. Intelligence quality depends on OCR accuracy. "
                "Review extraction quality before relying on results."
            )
        quality["scanned_heavy"] = True
        quality["scanned_ratio"] = round(_scanned_ratio, 2)

    if not raw_text.strip():
        return {
            "error": (
                "Could not extract text from PDF. "
                "This file may be a scanned image PDF. "
                "Please use a text-based PDF or apply OCR before uploading."
            ),
            "opportunities": [], "competitors": [], "lifecycle": [],
            "narrative": "",
            "quality": quality,
            "content_hash": content_hash,
        }

    # 2. Parse into DDR objects (one per rig/well block)
    ddrs: List[ExtractedDDR] = parse_pdf_text(raw_text)

    if not ddrs:
        quality["warnings"].append(
            "⚠ No rig blocks found in this PDF. "
            "Ensure the PDF is a Saudi Aramco DDR or LMR with the standard format: "
            "'RIG @ WELL Limited Morning Report for DATE'."
        )

    all_opportunities = []
    all_competitors   = []
    all_lifecycle     = []
    report_date       = ""

    for ddr in ddrs:
        if not report_date:
            report_date = ddr.report_date

        comps = extract_competitors(ddr.sections, ddr.rig, ddr.well)
        all_competitors.extend(comps)

        opps = detect_opportunities(ddr.sections, ddr.rig, ddr.well, ddr.field, comps)
        all_opportunities.extend(opps)

        lc = classify_lifecycle(ddr)
        if lc:
            all_lifecycle.append(lc)

    # 3. Re-rank globally
    urgency_order = {"immediate": 0, "5_days": 1, "7_days": 2, "30_days": 3, "future": 4}
    all_opportunities.sort(key=lambda o: (-o.confidence, urgency_order.get(o.urgency, 9)))
    for i, o in enumerate(all_opportunities, 1):
        o.rank = i

    # 4. Narrative
    rigs_seen = list(dict.fromkeys(d.rig for d in ddrs if d.rig))
    narrative = generate_narrative(all_opportunities, all_competitors, len(rigs_seen), report_date)

    # 5. KPIs
    pipeline_total  = sum(o.estimated_value for o in all_opportunities)
    immediate_count = sum(1 for o in all_opportunities if o.urgency in ("immediate", "5_days"))

    # 6. Enrich each opp dict with source traceability + confidence breakdown
    opp_dicts = []
    for o in all_opportunities:
        d = _safe_asdict(o)
        d["id"] = d.get("id") or str(uuid.uuid4())
        d["source_file"]    = filename
        d["source_page"]    = find_source_page(d.get("evidence_text",""), page_map)
        d["source_section"] = d.get("evidence_section", "")
        d["confidence_breakdown"] = compute_confidence_breakdown(d)
        opp_dicts.append(d)

    # 7. Add quality summary warning if very few rigs found vs words
    # v6.3D contract repair: defensive access + structured contract-violation
    # logging. A missing word_count must never crash the pipeline, but it must
    # also never silently disable this suspicious-document check.
    if "word_count" not in quality:
        import logging as _logging
        _logging.getLogger("eip.ingestion").error(
            "quality_contract_violation",
            extra={
                "missing_key": "word_count",
                "present_keys": sorted(quality.keys()),
                "filename": filename,
            },
        )
    _wc = quality.get("word_count", quality.get("total_words", 0)) or 0
    if rigs_seen and _wc > 5000 and len(rigs_seen) < 3:
        quality["warnings"].append(
            f"ℹ Only {len(rigs_seen)} rig(s) parsed from a {_wc:,}-word document. "
            f"Some rig blocks may not match the expected header format."
        )

    quality["content_hash"] = content_hash
    quality["rigs_parsed"]  = len(rigs_seen)

    return {
        "filename":          filename,
        "report_date":       report_date,
        "content_hash":      content_hash,
        "rigs":              rigs_seen,
        "rig_count":         len(rigs_seen),
        "opportunities":     opp_dicts,
        "opportunity_count": len(opp_dicts),
        "competitors":       [_safe_asdict(c) for c in all_competitors],
        "competitor_count":  len(all_competitors),
        "lifecycle":         [_safe_asdict(lc) for lc in all_lifecycle],
        "narrative":         narrative,
        "quality":           quality,
        "kpis": {
            "open_opportunities": len(opp_dicts),
            "pipeline_total":     pipeline_total,
            "immediate_targets":  immediate_count,
            "active_rigs":        len(rigs_seen),
            "competitor_mentions":len(all_competitors),
        },
    }
    """
    Main entry point.
    Returns a dict suitable for direct JSON serialization.
    Wave 2: includes source traceability and confidence breakdown per opportunity.
    """
    # 1. Extract text with page map
    raw_text, page_map = extract_text_from_pdf(pdf_bytes)
    if not raw_text.strip():
        return {"error": "Could not extract text from PDF. Ensure the PDF contains selectable text.",
                "opportunities": [], "competitors": [], "lifecycle": [], "narrative": ""}

    # 2. Parse into DDR objects (one per rig/well block)
    ddrs: List[ExtractedDDR] = parse_pdf_text(raw_text)

    all_opportunities = []
    all_competitors   = []
    all_lifecycle     = []
    report_date       = ""

    for ddr in ddrs:
        if not report_date:
            report_date = ddr.report_date

        # 3. Competitor detection
        comps = extract_competitors(ddr.sections, ddr.rig, ddr.well)
        all_competitors.extend(comps)

        # 4. Opportunity detection
        opps = detect_opportunities(ddr.sections, ddr.rig, ddr.well, ddr.field, comps)
        all_opportunities.extend(opps)

        # 5. Lifecycle
        lc = classify_lifecycle(ddr)
        if lc:
            all_lifecycle.append(lc)

    # 6. Re-rank globally
    urgency_order = {"immediate": 0, "5_days": 1, "7_days": 2, "30_days": 3, "future": 4}
    all_opportunities.sort(key=lambda o: (-o.confidence, urgency_order.get(o.urgency, 9)))
    for i, o in enumerate(all_opportunities, 1):
        o.rank = i

    # 7. Narrative
    rigs_seen = list(dict.fromkeys(d.rig for d in ddrs if d.rig))
    narrative = generate_narrative(all_opportunities, all_competitors, len(rigs_seen), report_date)

    # 8. KPI summary
    pipeline_total  = sum(o.estimated_value for o in all_opportunities)
    immediate_count = sum(1 for o in all_opportunities if o.urgency in ("immediate", "5_days"))

    # 9. Wave 2: enrich each opportunity dict with source traceability + confidence breakdown
    opp_dicts = []
    for o in all_opportunities:
        d = _safe_asdict(o)
        d["id"] = d.get("id") or str(uuid.uuid4())
        # Source traceability
        d["source_file"]    = filename
        d["source_page"]    = find_source_page(d.get("evidence_text",""), page_map)
        d["source_section"] = d.get("evidence_section", "")
        # Confidence breakdown (stored for Why This? modal)
        d["confidence_breakdown"] = compute_confidence_breakdown(d)
        opp_dicts.append(d)

    return {
        "filename":          filename,
        "report_date":       report_date,
        "rigs":              rigs_seen,
        "rig_count":         len(rigs_seen),
        "opportunities":     opp_dicts,
        "opportunity_count": len(opp_dicts),
        "competitors":       [_safe_asdict(c) for c in all_competitors],
        "competitor_count":  len(all_competitors),
        "lifecycle":         [_safe_asdict(lc) for lc in all_lifecycle],
        "narrative":         narrative,
        "kpis": {
            "open_opportunities": len(opp_dicts),
            "pipeline_total":     pipeline_total,
            "immediate_targets":  immediate_count,
            "active_rigs":        len(rigs_seen),
            "competitor_mentions":len(all_competitors),
        },
    }
