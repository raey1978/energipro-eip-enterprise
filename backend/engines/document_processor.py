"""
EIP v6.3C — Document Processor

Replaces the single-function extract_text_from_pdf with a full pipeline:

  1. Document classification (type detection before any extraction)
  2. Page-by-page quality assessment
  3. Native text extraction via pdfplumber
  4. OCR fallback for low-quality / scanned pages
  5. Page ordering and text merging
  6. Quality gate — refuses to proceed on zero-content documents
  7. Full audit trail per page

Every failure is explicit. No silent zero-content processing.

Returns DocumentProcessingResult — consumed by ingestion_pipeline.py.
"""
from __future__ import annotations
import time, logging, re, io
from dataclasses import dataclass, field
from typing import Optional
import pdfplumber

logger = logging.getLogger("eip.document_processor")

# ── Thresholds ────────────────────────────────────────────────────────────────
MIN_CHARS_NATIVE_PAGE    = 50    # Below this → page needs OCR
MIN_WORDS_TOTAL          = 20    # Below this → document fails quality gate
SCANNED_RATIO_THRESHOLD  = 0.60  # >60% scanned pages → document is "Scanned PDF"
MIN_ALPHA_RATIO          = 0.30  # < 30% alphabetic chars → likely garbage/image
MIN_QUALITY_SCORE        = 25    # 0-100 composite → below this = document fails


@dataclass
class PageResult:
    page_number:      int
    char_count:       int
    word_count:       int
    extraction_method:str          # native | ocr | empty | failed
    ocr_confidence:   float        # 0.0-1.0 (0 if native)
    quality:          str          # good | acceptable | low | failed
    quality_score:    int          # 0-100
    text:             str
    warnings:         list[str]    = field(default_factory=list)
    rotation_detected:bool         = False
    table_detected:   bool         = False


@dataclass
class DocumentProcessingResult:
    # Classification
    document_type:    str          # native_pdf | scanned_pdf | mixed_pdf | empty | encrypted | corrupted | unsupported
    page_count:       int
    native_pages:     int
    scanned_pages:    int
    ocr_pages:        int

    # Quality
    quality_score:    int          # 0-100
    extraction_status:str          # success | partial | needs_review | failed
    warnings:         list[str]    = field(default_factory=list)

    # Output
    full_text:        str          = ""
    page_results:     list[PageResult] = field(default_factory=list)

    # Metrics
    total_words:      int          = 0
    total_chars:      int          = 0
    processing_ms:    float        = 0.0
    ocr_used:         bool         = False

    # Traceability
    page_texts:       dict         = field(default_factory=dict)   # {page_num: text}


def classify_and_extract(
    pdf_bytes: bytes,
    filename: str = "",
    enable_ocr: bool = True,
    ocr_lang: str = "eng",
) -> DocumentProcessingResult:
    """
    Main entry point. Classify the document and extract text with quality control.
    Never silently returns empty content without an explicit status.
    """
    t0 = time.perf_counter()

    # ── 0. Pre-check: encrypted / corrupted ──────────────────────────────────
    if not pdf_bytes or len(pdf_bytes) < 100:
        return DocumentProcessingResult(
            document_type="corrupted", page_count=0,
            native_pages=0, scanned_pages=0, ocr_pages=0,
            quality_score=0, extraction_status="failed",
            warnings=["File is empty or too small to be a valid PDF"],
        )

    if pdf_bytes[:4] != b'%PDF':
        return DocumentProcessingResult(
            document_type="unsupported", page_count=0,
            native_pages=0, scanned_pages=0, ocr_pages=0,
            quality_score=0, extraction_status="failed",
            warnings=[f"Not a PDF file (header: {pdf_bytes[:4]!r})"],
        )

    # ── 1. Open with pdfplumber ───────────────────────────────────────────────
    try:
        pdf = pdfplumber.open(io.BytesIO(pdf_bytes))
    except Exception as e:
        err = str(e).lower()
        if "encrypt" in err or "password" in err:
            return DocumentProcessingResult(
                document_type="encrypted", page_count=0,
                native_pages=0, scanned_pages=0, ocr_pages=0,
                quality_score=0, extraction_status="failed",
                warnings=["Cannot process — document is password-protected. "
                          "Remove password protection before uploading."],
            )
        return DocumentProcessingResult(
            document_type="corrupted", page_count=0,
            native_pages=0, scanned_pages=0, ocr_pages=0,
            quality_score=0, extraction_status="failed",
            warnings=[f"Cannot open PDF: {str(e)[:120]}"],
        )

    page_count  = len(pdf.pages)
    if page_count == 0:
        pdf.close()
        return DocumentProcessingResult(
            document_type="empty", page_count=0,
            native_pages=0, scanned_pages=0, ocr_pages=0,
            quality_score=0, extraction_status="failed",
            warnings=["PDF contains zero pages."],
        )

    # ── 2. Page-by-page extraction ────────────────────────────────────────────
    page_results   = []
    global_warnings = []
    native_count   = 0
    scanned_count  = 0
    ocr_count      = 0

    for i, page in enumerate(pdf.pages, start=1):
        pr = _process_page(page, i, enable_ocr, ocr_lang)
        page_results.append(pr)
        if pr.extraction_method == "native":  native_count  += 1
        elif pr.extraction_method == "ocr":   ocr_count     += 1; scanned_count += 1
        elif pr.extraction_method == "empty": scanned_count += 1
        if pr.warnings:
            global_warnings.extend([f"Page {i}: {w}" for w in pr.warnings])

    pdf.close()

    # ── 3. Document type classification ──────────────────────────────────────
    native_ratio  = native_count / max(page_count, 1)
    scanned_ratio = scanned_count / max(page_count, 1)

    if native_ratio >= 0.90:
        doc_type = "native_pdf"
    elif scanned_ratio >= SCANNED_RATIO_THRESHOLD:
        doc_type = "scanned_pdf"
    elif native_count > 0 and (scanned_count > 0 or ocr_count > 0):
        doc_type = "mixed_pdf"
    else:
        doc_type = "native_pdf"

    # ── 4. Merge text in page order ───────────────────────────────────────────
    page_texts   = {}
    all_texts    = []
    total_words  = 0
    total_chars  = 0

    for pr in page_results:
        if pr.text.strip():
            page_texts[pr.page_number] = pr.text
            all_texts.append(f"\n[PAGE {pr.page_number}]\n{pr.text}")
            total_words += pr.word_count
            total_chars += pr.char_count

    full_text = "\n".join(all_texts)

    # ── 5. Quality gate ───────────────────────────────────────────────────────
    failed_pages = [pr for pr in page_results if pr.quality == "failed"]
    low_pages    = [pr for pr in page_results if pr.quality == "low"]

    # Composite quality score
    if page_results:
        avg_page_score = sum(pr.quality_score for pr in page_results) / len(page_results)
        quality_score  = int(avg_page_score)
    else:
        quality_score = 0

    # Extraction status
    if total_words < MIN_WORDS_TOTAL:
        extraction_status = "failed"
        global_warnings.append(
            f"QUALITY GATE FAILED: Only {total_words} words extracted from {page_count} pages. "
            "Document may be a scanned image requiring OCR, or the content is not in recognised format. "
            "Action: Verify the PDF contains extractable text, or enable OCR if this is a scanned document."
        )
    elif len(failed_pages) > page_count * 0.5:
        extraction_status = "needs_review"
        global_warnings.append(
            f"{len(failed_pages)}/{page_count} pages failed extraction. "
            "Intelligence quality will be reduced. Manual review recommended."
        )
    elif len(failed_pages) > 0 or len(low_pages) > 0:
        extraction_status = "partial"
        global_warnings.append(
            f"Partial extraction: {len(failed_pages)} failed pages, {len(low_pages)} low-quality pages. "
            "Some intelligence may be missing."
        )
    else:
        extraction_status = "success"

    processing_ms = round((time.perf_counter() - t0) * 1000, 1)
    ocr_used      = ocr_count > 0

    return DocumentProcessingResult(
        document_type=doc_type, page_count=page_count,
        native_pages=native_count, scanned_pages=scanned_count, ocr_pages=ocr_count,
        quality_score=quality_score, extraction_status=extraction_status,
        warnings=global_warnings, full_text=full_text,
        page_results=page_results, total_words=total_words, total_chars=total_chars,
        processing_ms=processing_ms, ocr_used=ocr_used, page_texts=page_texts,
    )


def _process_page(page, page_num: int, enable_ocr: bool, lang: str) -> PageResult:
    """Process a single page: native extraction first, OCR fallback if needed."""
    warnings = []

    # ── Native text extraction ────────────────────────────────────────────────
    try:
        native_text = page.extract_text() or ""
    except Exception as e:
        warnings.append(f"pdfplumber extraction error: {str(e)[:60]}")
        native_text = ""

    # ── Table extraction — merge table content into text ─────────────────────
    # FIXED (was: nested loop always re-read tables[0], duplicating the first
    # table's text once per table found and silently dropping every other
    # table on the page). Confirmed via forensic_audit.py / bounded_forensic_audit.py.
    table_detected = False
    try:
        tables = page.extract_tables()
        if tables:
            table_detected = True
            for table in tables:
                for row in table:
                    cells = [str(c or "").strip() for c in row if c]
                    if cells:
                        native_text += " " + " | ".join(cells)
    except Exception:
        pass

    # ── Assess native text quality ────────────────────────────────────────────
    native_chars = len(native_text.strip())
    native_words = len(native_text.split()) if native_text.strip() else 0
    native_quality = _assess_text_quality(native_text)

    # Decide if OCR is needed
    needs_ocr = (native_chars < MIN_CHARS_NATIVE_PAGE or native_quality == "failed")

    if not needs_ocr:
        qs = _quality_score(native_text, native_quality, 0.0)
        return PageResult(
            page_number=page_num, char_count=native_chars, word_count=native_words,
            extraction_method="native", ocr_confidence=0.0, quality=native_quality,
            quality_score=qs, text=native_text, warnings=warnings,
            table_detected=table_detected,
        )

    # ── OCR fallback ──────────────────────────────────────────────────────────
    if not enable_ocr:
        warnings.append(f"Page needs OCR but OCR is disabled — {native_chars} native chars only")
        qs = _quality_score(native_text, "low", 0.0)
        return PageResult(
            page_number=page_num, char_count=native_chars, word_count=native_words,
            extraction_method="native" if native_chars > 0 else "empty",
            ocr_confidence=0.0, quality="low" if native_chars > 0 else "failed",
            quality_score=qs, text=native_text, warnings=warnings,
            table_detected=table_detected,
        )

    try:
        from engines.ocr_pipeline import get_ocr_provider, OcrNotAvailable
        provider = get_ocr_provider()

        # Render page to image
        from pdf2image import convert_from_bytes
        # Can't pass page object directly — use page's parent PDF bytes
        # Use pdfplumber's page bbox to isolate page
        images = _render_page_to_image(page)
        if not images:
            warnings.append("Could not render page to image for OCR")
            qs = _quality_score(native_text, "failed", 0.0)
            return PageResult(
                page_number=page_num, char_count=native_chars, word_count=native_words,
                extraction_method="failed", ocr_confidence=0.0, quality="failed",
                quality_score=max(0, qs), text=native_text, warnings=warnings,
            )

        # Detect rotation
        rotation = _detect_rotation(images[0])
        rot_detected = False
        if rotation and rotation != 0:
            rot_detected = True
            warnings.append(f"Page rotation detected: {rotation}°. Correcting before OCR.")
            images[0] = images[0].rotate(-rotation, expand=True)

        ocr_result = provider.ocr_page(images[0], lang=lang)
        warnings.extend(ocr_result.warnings)

        # Use OCR text if better quality than native
        if ocr_result.word_count > native_words:
            final_text = ocr_result.text
            method     = "ocr"
            confidence = ocr_result.confidence
        else:
            # Native was better — keep it but note OCR was attempted
            final_text = native_text
            method     = "native"
            confidence = 0.0
            if ocr_result.word_count > 0:
                warnings.append(f"Native text ({native_words}w) used over OCR ({ocr_result.word_count}w)")

        quality   = _assess_text_quality(final_text)
        qs        = _quality_score(final_text, quality, confidence)

        return PageResult(
            page_number=page_num, char_count=len(final_text), word_count=len(final_text.split()),
            extraction_method=method, ocr_confidence=confidence, quality=quality,
            quality_score=qs, text=final_text, warnings=warnings,
            rotation_detected=rot_detected, table_detected=table_detected,
        )

    except ImportError as e:
        warnings.append(f"OCR dependency missing: {e}. Install pdf2image and pytesseract.")
        qs = _quality_score(native_text, "low", 0.0)
        return PageResult(
            page_number=page_num, char_count=native_chars, word_count=native_words,
            extraction_method="native" if native_chars > 0 else "empty",
            ocr_confidence=0.0, quality="low" if native_chars > 0 else "failed",
            quality_score=qs, text=native_text, warnings=warnings,
        )
    except Exception as e:
        warnings.append(f"OCR failed: {str(e)[:80]}")
        qs = _quality_score(native_text, "low", 0.0)
        return PageResult(
            page_number=page_num, char_count=native_chars, word_count=native_words,
            extraction_method="native" if native_chars > 0 else "empty",
            ocr_confidence=0.0, quality="low" if native_chars > 0 else "failed",
            quality_score=qs, text=native_text, warnings=warnings,
        )


def _render_page_to_image(page) -> list:
    """Render a pdfplumber page to PIL Image via pdf2image."""
    try:
        from pdf2image import convert_from_bytes
        # Get the source PDF bytes from the page's parent
        pdf_stream = io.BytesIO()
        # pdfplumber pages have a .page_obj — extract just this page via pypdf
        try:
            import pypdf
            writer = pypdf.PdfWriter()
            reader = pypdf.PdfReader(io.BytesIO(page.pdf.stream.get_data()))
            writer.add_page(reader.pages[page.page_number])
            writer.write(pdf_stream)
            pdf_bytes = pdf_stream.getvalue()
        except Exception:
            # Fallback: try to get raw page data from pdfplumber
            pdf_bytes = page.pdf.stream.get_data()

        images = convert_from_bytes(pdf_bytes, dpi=200, first_page=1, last_page=1)
        return images
    except Exception as e:
        logger.warning("Page render failed: %s", e)
        return []


def _detect_rotation(image) -> int:
    """Detect page rotation using Tesseract OSD. Returns degrees (0/90/180/270)."""
    try:
        import pytesseract
        osd = pytesseract.image_to_osd(image, output_type=pytesseract.Output.DICT)
        return osd.get("rotate", 0)
    except Exception:
        return 0


def _assess_text_quality(text: str) -> str:
    """Classify text quality: good | acceptable | low | failed."""
    if not text or not text.strip():
        return "failed"
    words = text.split()
    if len(words) < 3:
        return "failed"
    # Ratio of alphabetic characters
    alpha = sum(1 for c in text if c.isalpha())
    total = max(len(text), 1)
    alpha_ratio = alpha / total
    if alpha_ratio < 0.20:
        return "low"    # Mostly numbers/symbols — likely garbage
    if len(words) >= 20 and alpha_ratio >= MIN_ALPHA_RATIO:
        return "good"
    if len(words) >= 5:
        return "acceptable"
    return "low"


def _quality_score(text: str, quality: str, ocr_conf: float) -> int:
    """Compute 0-100 quality score for a page."""
    base = {"good":80, "acceptable":55, "low":25, "failed":0}.get(quality, 0)
    words = len(text.split()) if text else 0
    word_bonus = min(20, words // 5)
    if ocr_conf > 0:
        conf_adj = int(ocr_conf * 10) - 5  # OCR: confidence pushes score up or down
        return max(0, min(100, base + word_bonus + conf_adj))
    return max(0, min(100, base + word_bonus))


# ── Ingestion log table ────────────────────────────────────────────────────────

def _init_ingestion_log_table():
    """Create document_ingestion_log table for per-upload quality tracking."""
    from core.database import get_db
    conn = get_db()
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS document_ingestion_log (
        id              TEXT PRIMARY KEY,
        upload_id       TEXT NOT NULL,
        logged_at       TEXT NOT NULL,
        filename        TEXT DEFAULT '',
        document_type   TEXT DEFAULT '',
        extraction_status TEXT DEFAULT '',
        quality_score   INTEGER DEFAULT 0,
        page_count      INTEGER DEFAULT 0,
        native_pages    INTEGER DEFAULT 0,
        scanned_pages   INTEGER DEFAULT 0,
        ocr_pages       INTEGER DEFAULT 0,
        ocr_used        INTEGER DEFAULT 0,
        total_words     INTEGER DEFAULT 0,
        processing_ms   REAL DEFAULT 0,
        warnings        TEXT DEFAULT '[]',
        page_quality_json TEXT DEFAULT '{}',
        attempt_number  INTEGER DEFAULT 1,
        ocr_lang        TEXT DEFAULT 'eng',
        superseded      INTEGER DEFAULT 0,
        records_generated INTEGER DEFAULT 0
    );
    CREATE INDEX IF NOT EXISTS idx_dil_upload ON document_ingestion_log(upload_id);
    CREATE INDEX IF NOT EXISTS idx_dil_status ON document_ingestion_log(extraction_status);
    """)
    conn.commit()
    conn.close()


def log_ingestion_result(upload_id: str, filename: str, result: DocumentProcessingResult):
    """Persist document processing result to ingestion log."""
    from core.database import get_db
    import uuid, datetime, json
    conn = get_db()
    page_quality_dict = {
        str(pr.page_number): {
            "method": pr.extraction_method, "quality": pr.quality,
            "score": pr.quality_score, "words": pr.word_count,
        }
        for pr in result.page_results
    }
    # Get attempt number
    existing_count = conn.execute(
        "SELECT COUNT(*) FROM document_ingestion_log WHERE upload_id=?", (upload_id,)
    ).fetchone()[0]
    attempt_num = existing_count + 1

    conn.execute(
        """INSERT OR REPLACE INTO document_ingestion_log
           (id,upload_id,logged_at,filename,document_type,extraction_status,quality_score,
            page_count,native_pages,scanned_pages,ocr_pages,ocr_used,total_words,
            processing_ms,warnings,page_quality_json,attempt_number,ocr_lang,superseded,records_generated)
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (str(uuid.uuid4()), upload_id,
         datetime.datetime.utcnow().isoformat(),
         filename, result.document_type, result.extraction_status,
         result.quality_score, result.page_count,
         result.native_pages, result.scanned_pages, result.ocr_pages,
         1 if result.ocr_used else 0, result.total_words, result.processing_ms,
         json.dumps(result.warnings[:10]),
         json.dumps(page_quality_dict),
         attempt_num, "eng", 0, 0)
    )
    conn.commit()
    conn.close()


# ── Reprocessing support ──────────────────────────────────────────────────────

REPROCESS_STATUS = {
    "failed":        "previous_failed",
    "needs_review":  "previous_needs_review",
    "partial":       "previous_partial",
    "success":       "superseded",
}


def get_ingestion_history(upload_id: str) -> list:
    """Return all processing attempts for an upload, newest first."""
    from core.database import get_db
    import json
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM document_ingestion_log WHERE upload_id=? ORDER BY logged_at DESC",
        (upload_id,)
    ).fetchall()
    conn.close()
    result = []
    for r in rows:
        d = dict(r)
        try: d["warnings"]          = json.loads(d.get("warnings","[]") or "[]")
        except: d["warnings"]       = []
        try: d["page_quality_json"] = json.loads(d.get("page_quality_json","{}") or "{}")
        except: d["page_quality_json"] = {}
        result.append(d)
    return result


def clear_upload_intelligence(upload_id: str) -> dict:
    """
    Delete all downstream intelligence for an upload before reprocessing.
    Idempotent: safe to call multiple times.
    Does NOT delete the upload record itself.
    """
    from core.database import get_db
    conn = get_db()
    deleted = {}
    for table, col in [
        ("opportunities",    "upload_id"),
        ("competitors",      "upload_id"),
        ("lifecycle",        "upload_id"),
        ("entity_observations", "upload_id"),
        ("market_snapshots", "upload_id"),
        ("change_events",    "upload_id"),
        ("trust_scores",     "insight_id"),   # purge by matching upload's opp IDs
    ]:
        if table == "trust_scores":
            # Get opp IDs for this upload first
            opp_ids = [r[0] for r in conn.execute(
                "SELECT id FROM opportunities WHERE upload_id=?", (upload_id,)
            ).fetchall()]
            if opp_ids:
                placeholders = ",".join("?" * len(opp_ids))
                r = conn.execute(
                    f"DELETE FROM trust_scores WHERE insight_id IN ({placeholders})", opp_ids
                )
                deleted[table] = r.rowcount
        else:
            r = conn.execute(f"DELETE FROM {table} WHERE {col}=?", (upload_id,))
            deleted[table] = r.rowcount
    conn.commit()
    conn.close()
    return deleted


def mark_previous_attempts_superseded(upload_id: str):
    """Mark all previous ingestion log rows for this upload as superseded."""
    from core.database import get_db
    import datetime
    conn = get_db()
    conn.execute(
        "UPDATE document_ingestion_log SET extraction_status='superseded' WHERE upload_id=? AND extraction_status != 'superseded'",
        (upload_id,)
    )
    conn.commit()
    conn.close()


def get_processing_attempt_number(upload_id: str) -> int:
    """Return the next processing attempt number (1 for first, 2 for reprocess, etc.)."""
    from core.database import get_db
    conn = get_db()
    count = conn.execute(
        "SELECT COUNT(*) FROM document_ingestion_log WHERE upload_id=?", (upload_id,)
    ).fetchone()[0]
    conn.close()
    return count + 1
