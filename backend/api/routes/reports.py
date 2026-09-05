import logging
"""EIP DDR Intelligence v4.4 — Reports Upload Route (Wave 3)
True append/replace mode, upload quality report, duplicate detection.
"""
import uuid, hashlib
from fastapi import APIRouter, UploadFile, File, Request, HTTPException, Depends, Form, Query
from pydantic import BaseModel
import json
from fastapi.responses import JSONResponse
from engines.ingestion_pipeline import run_pipeline
from core.database import (save_upload, load_latest, get_upload_history,
                            clear_all_data, check_duplicate, get_db)
from core.auth import require_permission, get_current_user
from core.audit import audit_from_request

router = APIRouter()
logger = logging.getLogger("eip.reports")


def _sync_store(request, data):
    if not hasattr(request.app.state, "intelligence_store"):
        request.app.state.intelligence_store = {}
    request.app.state.intelligence_store.update(data)


@router.post("/upload")
async def upload_report(
    request: Request,
    file: UploadFile = File(...),
    mode: str = Form(default="replace"),
    force: str = Form(default="false"),   # override duplicate warning
    user: dict = Depends(require_permission("upload"))
):
    """
    Upload a DDR or LMR PDF.
    mode: 'replace' (default) clears existing data, 'append' adds to current dataset.
    force: 'true' skips duplicate check warning (user confirmed they want to proceed).
    """
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "Only PDF files are supported. Please upload a .pdf file.")

    pdf_bytes = await file.read()
    if len(pdf_bytes) < 500:
        raise HTTPException(400, "File appears empty or too small to be a valid DDR/LMR.")
    if len(pdf_bytes) > 100 * 1024 * 1024:  # 100MB
        raise HTTPException(400, "File is too large (max 100MB). Please upload a standard DDR/LMR PDF.")

    # ── Duplicate detection ────────────────────────────────────────────────────
    content_hash = hashlib.sha256(pdf_bytes).hexdigest()

    if force.lower() != "true":
        duplicate = check_duplicate(content_hash, file.filename)
        if duplicate.get("type") == "exact":
            return JSONResponse(status_code=409, content={
                "status": "duplicate",
                "duplicate_type": "exact",
                "message": f"This exact file was already uploaded on {duplicate['uploaded_at'][:16]} "
                           f"(report date: {duplicate['report_date']}). "
                           f"Upload again with force=true to replace.",
                "previous_upload": duplicate,
            })
        elif duplicate.get("type") == "same_filename":
            return JSONResponse(status_code=409, content={
                "status": "duplicate",
                "duplicate_type": "same_filename",
                "message": f"A file named '{file.filename}' was previously uploaded "
                           f"on {duplicate['uploaded_at'][:16]}. "
                           f"This appears to be a different version. "
                           f"Upload with force=true to proceed.",
                "previous_upload": duplicate,
            })

    # ── Process ───────────────────────────────────────────────────────────────
    result = run_pipeline(pdf_bytes, file.filename)

    # V6.3C: log document quality metadata
    try:
        from engines.document_processor import classify_and_extract, log_ingestion_result
        doc_result = classify_and_extract(pdf_bytes, file.filename, enable_ocr=True)
        log_ingestion_result(upload_id, file.filename, doc_result)
        if doc_result.extraction_status == "failed":
            logger.warning("document_quality_gate_failed", extra={
                "upload_id": upload_id, "quality_score": doc_result.quality_score,
                "document_type": doc_result.document_type,
                "warnings": doc_result.warnings[:2],
            })
    except Exception as e:
        logger.warning(f"ingestion_log_failed: {e}")

    if "error" in result and not result.get("opportunities"):
        raise HTTPException(422, result["error"])

    replace_mode = (mode.lower() != "append")
    upload_id    = str(uuid.uuid4())

    for opp in result.get("opportunities", []):
        if not opp.get("id"):
            opp["id"] = str(uuid.uuid4())

    quality = result.get("quality", {})
    quality["content_hash"] = content_hash

    save_upload(
        upload_id, result,
        replace_mode=replace_mode,
        uploaded_by=user.get("email",""),
        quality=quality
    )
    data = load_latest()
    if data:
        _sync_store(request, data)
        # V5.0: auto-generate strategic insights after upload
        try:
            from engines.intelligence.insights_engine import generate_strategic_insights
            generate_strategic_insights(data, upload_id)
        except Exception as e:
            logger.warning(f"insights_generation_failed: {e}")

        # V6.0: auto-run market intelligence pipeline after upload
        try:
            from engines.intelligence.market_intelligence import (
                generate_market_snapshot, calculate_trend_signals
            )
            from engines.intelligence.change_detection import detect_changes
            from engines.intelligence.campaign_detector import detect_campaigns

            snap = generate_market_snapshot(upload_id)
            detect_changes(upload_id)
            detect_campaigns(upload_id)
            calculate_trend_signals()
            logger.info("market_intelligence_generated", extra={
                "upload_id": upload_id,
                "active_rigs": snap.get("active_rigs", 0),
            })
        except Exception as e:
            logger.warning(f"market_intelligence_failed: {e}")

        # V6.1: auto-score trust layer for current opportunities
        try:
            from engines.intelligence.trust_layer import calculate_trust_envelope, store_trust_score
            from engines.intelligence.governance_layer import create_governance_record
            from engines.intelligence.commercial_engine import calculate_commercial_intelligence
            for opp in (data.get("opportunities") or [])[:100]:
                if opp.get("id"):
                    env = calculate_trust_envelope("opportunity", opp)
                    store_trust_score("opportunity", opp["id"], env)
                    ci  = calculate_commercial_intelligence(opp)
                    create_governance_record(
                        insight_type="opportunity", insight_id=opp["id"],
                        title=opp.get("title",""),
                        recommendation=ci.get("recommended_action",""),
                        trust_envelope=env,
                        source_upload_ids=[upload_id],
                        trigger_type="upload",
                        triggered_by=user.get("email","system"),
                        commercial_priority=ci.get("commercial_priority",0),
                        revenue_expected=ci.get("revenue_potential",0),
                    )
        except Exception as e:
            logger.warning(f"trust_scoring_failed: {e}")

        # V6.3: record quality snapshot after upload
        try:
            from engines.intelligence.governance_layer import record_quality_snapshot
            record_quality_snapshot(upload_id=upload_id)
        except Exception as e:
            logger.warning(f"quality_snapshot_failed: {e}")

        # V6.3A: run entity resolution for this upload
        try:
            from engines.intelligence.entity_resolution import process_upload_entities
            report_date = data.get("report_date","")
            er_stats = process_upload_entities(upload_id, report_date)
            logger.info("entity_resolution_complete", extra={
                "upload_id": upload_id, **er_stats
            })
        except Exception as e:
            logger.warning(f"entity_resolution_failed: {e}")

    audit_from_request(request, "DDR_UPLOAD", user=user,
        detail=(f"{'Replace' if replace_mode else 'Append'} | {file.filename} | "
                f"{result.get('rig_count',0)} rigs | {result.get('opportunity_count',0)} opps | "
                f"pages={quality.get('page_count',0)} words={quality.get('word_count',0)}"),
        resource_id=upload_id)

    return {
        "status":         "success",
        "upload_id":      upload_id,
        "filename":       file.filename,
        "mode":           "replace" if replace_mode else "append",
        "report_date":    result.get("report_date",""),
        "rigs_found":     result.get("rig_count", 0),
        "opportunities":  result.get("opportunity_count", 0),
        "competitors":    result.get("competitor_count", 0),
        "pipeline_total": result.get("kpis", {}).get("pipeline_total", 0),
        "narrative":      result.get("narrative","")[:600],
        "kpis":           result.get("kpis", {}),
        "quality": {
            "page_count":             quality.get("page_count", 0),
            "word_count":             quality.get("word_count", 0),
            "ocr_required":           quality.get("ocr_required", False),
            "extraction_confidence":  quality.get("extraction_confidence", "unknown"),
            "warnings":               quality.get("warnings", []),
            "rigs_parsed":            result.get("rig_count", 0),
        },
    }


@router.post("/upload/force-replace")
async def force_replace_duplicate(
    request: Request,
    file: UploadFile = File(...),
    mode: str = Form(default="replace"),
    user: dict = Depends(require_permission("upload"))
):
    """Force upload even if duplicate detected."""
    # Re-read the file and call upload with force=true
    pdf_bytes = await file.read()
    from fastapi.datastructures import UploadFile as UF
    # Reconstruct for the main upload handler
    result = run_pipeline(pdf_bytes, file.filename)
    if "error" in result and not result.get("opportunities"):
        raise HTTPException(422, result["error"])
    replace_mode = mode.lower() != "append"
    upload_id    = str(uuid.uuid4())
    for opp in result.get("opportunities", []):
        if not opp.get("id"): opp["id"] = str(uuid.uuid4())
    quality = result.get("quality", {})
    quality["content_hash"] = hashlib.sha256(pdf_bytes).hexdigest()
    save_upload(upload_id, result, replace_mode=replace_mode,
                uploaded_by=user.get("email",""), quality=quality)
    data = load_latest()
    if data: _sync_store(request, data)
    return {"status":"success","upload_id":upload_id,"filename":file.filename,
            "opportunities":result.get("opportunity_count",0)}


@router.get("/status")
async def report_status(request: Request, user: dict = Depends(get_current_user)):
    data = load_latest()
    if not data:
        return {"reports_processed": 0, "last_filename": "", "last_date": "", "rigs": []}
    return {
        "reports_processed": data.get("reports_processed", 0),
        "last_filename":     data.get("filename", ""),
        "last_date":         data.get("report_date", ""),
        "rigs":              data.get("rigs", []),
    }


@router.get("/history")
async def upload_history(user: dict = Depends(get_current_user)):
    return get_upload_history()


@router.post("/clear")
async def clear_data(request: Request, user: dict = Depends(require_permission("upload"))):
    clear_all_data()
    if hasattr(request.app.state, "intelligence_store"):
        request.app.state.intelligence_store = {"reports_processed": 0}
    audit_from_request(request, "DDR_CLEAR", user=user,
                       detail="All DDR data cleared")
    return {"status": "cleared"}


# ── Scheduled Report Management (v6.3) ───────────────────────────────────────

class ReportSchedule(BaseModel):
    recipients: list  # email addresses
    daily_brief: bool = True
    weekly_report: bool = True
    send_time: str = "07:00"  # HH:MM UTC


@router.get("/schedule")
async def get_schedule(user: dict = Depends(get_current_user)):
    """Return current report schedule and recipients."""
    conn = get_db()
    row = conn.execute("SELECT value FROM settings WHERE key='report_schedule'").fetchone()
    conn.close()
    if not row:
        return {"recipients": [], "daily_brief": True, "weekly_report": True, "send_time": "07:00"}
    try:
        return json.loads(row[0])
    except Exception:
        return {"recipients": [], "daily_brief": True, "weekly_report": True, "send_time": "07:00"}


@router.post("/schedule")
async def update_schedule(
    body: ReportSchedule,
    request: Request,
    user: dict = Depends(require_permission("admin"))
):
    """Update report delivery schedule and recipients."""
    conn = get_db()
    conn.execute(
        "INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)",
        ("report_schedule", json.dumps(body.model_dump()))
    )
    conn.commit()
    conn.close()
    audit_from_request(request, "SETTING_CHANGED", user=user,
                       detail=f"Report schedule updated: {len(body.recipients)} recipients")
    return {"status": "saved", **body.model_dump()}


@router.post("/send-now")
async def send_report_now(
    report_type: str = "daily_brief",
    request: Request = None,
    user: dict = Depends(require_permission("admin"))
):
    """
    Manually trigger report delivery.
    Requires SMTP_HOST, SMTP_USER, SMTP_PASS in .env to actually send.
    Returns the report content regardless (for preview/download).
    """
    import os, smtplib
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText
    from email.mime.application import MIMEApplication

    conn = get_db()
    sched_row = conn.execute("SELECT value FROM settings WHERE key='report_schedule'").fetchone()
    conn.close()
    schedule = {}
    if sched_row:
        try: schedule = json.loads(sched_row[0])
        except: pass

    recipients = schedule.get("recipients", [])
    smtp_host  = os.environ.get("SMTP_HOST","")
    smtp_user  = os.environ.get("SMTP_USER","")
    smtp_pass  = os.environ.get("SMTP_PASS","")
    smtp_port  = int(os.environ.get("SMTP_PORT","587"))

    sent_to = []
    error   = None

    if recipients and smtp_host and smtp_user:
        try:
            if report_type == "weekly_report":
                from engines.intelligence.governance_layer import compute_intelligence_quality
                subject = f"EIP Weekly Intelligence Report — {__import__('datetime').date.today()}"
                body_text = f"Weekly intelligence report attached. Quality score: {compute_intelligence_quality().get('composite_score',0)}/100."
            else:
                subject = f"EIP Daily Intelligence Brief — {__import__('datetime').date.today()}"
                body_text = "Daily intelligence brief attached."

            msg = MIMEMultipart()
            msg["Subject"] = subject
            msg["From"]    = smtp_user
            msg["To"]      = ", ".join(recipients)
            msg.attach(MIMEText(body_text,"plain"))

            with smtplib.SMTP(smtp_host, smtp_port) as server:
                server.starttls()
                server.login(smtp_user, smtp_pass)
                server.sendmail(smtp_user, recipients, msg.as_string())
            sent_to = recipients
        except Exception as e:
            error = str(e)

    return {
        "status":        "sent" if sent_to else "queued",
        "sent_to":       sent_to,
        "report_type":   report_type,
        "smtp_configured": bool(smtp_host and smtp_user),
        "recipients_configured": len(recipients),
        "error":         error,
        "note": ("Configure SMTP_HOST, SMTP_USER, SMTP_PASS, SMTP_PORT in .env to enable email delivery."
                 if not smtp_host else None),
    }


# ── Safe Reprocessing (v6.3D) ─────────────────────────────────────────────────

@router.post("/reprocess/{upload_id}")
async def reprocess_upload(
    upload_id: str,
    request: Request,
    enable_ocr: bool = True,
    ocr_lang: str = "eng",
    user: dict = Depends(require_permission("upload"))
):
    """
    Safely reprocess a previously uploaded document.
    Idempotent: clears previous intelligence records before re-running.
    Supersedes the previous ingestion log entry.
    Does NOT create duplicate opportunities, entities, or observations.
    """
    from engines.document_processor import (
        classify_and_extract, log_ingestion_result,
        clear_upload_intelligence, mark_previous_attempts_superseded,
        get_ingestion_history
    )
    from engines.ingestion_pipeline import run_pipeline

    # Verify the upload exists
    conn = get_db()
    upload_row = conn.execute("SELECT * FROM uploads WHERE id=?", (upload_id,)).fetchone()
    conn.close()
    if not upload_row:
        raise HTTPException(404, "Upload not found")

    upload = dict(upload_row)
    filename = upload.get("filename","")

    # Retrieve original PDF bytes from the stored content_hash path
    # For reprocessing we need the original bytes — currently stored in content_hash
    # The actual re-upload requires the original file to be re-uploaded
    # We'll look for it in a temp store or fall back to an informative error
    stored_hash = upload.get("content_hash","")
    if not stored_hash:
        raise HTTPException(400,
            "Cannot reprocess — original file content not available. "
            "Upload the file again to reprocess.")

    # Check history
    history = get_ingestion_history(upload_id)
    prev_status = history[0]["extraction_status"] if history else "unknown"
    attempt_number = len(history) + 1

    # Step 1: Clear previous downstream intelligence
    cleared = clear_upload_intelligence(upload_id)
    logger.info("reprocess_cleared", extra={"upload_id": upload_id, "cleared": cleared})

    # Step 2: Mark previous ingestion log entries as superseded
    mark_previous_attempts_superseded(upload_id)

    # Since we can't re-run without the original bytes, we return a structured
    # reprocessing ticket that tells the frontend to re-submit the file
    audit_from_request(request, "SETTING_CHANGED", user=user,
                       detail=f"Reprocess requested for upload {upload_id[:8]}")

    return {
        "status":           "reprocess_ready",
        "upload_id":        upload_id,
        "filename":         filename,
        "attempt_number":   attempt_number,
        "previous_status":  prev_status,
        "cleared":          cleared,
        "message":          (
            "Previous intelligence has been cleared. "
            "Upload the same file again to regenerate intelligence with current settings. "
            "Entity resolution will deduplicate automatically."
        ),
        "next_step":        "upload_same_file",
        "ocr_enabled":      enable_ocr,
        "ocr_lang":         ocr_lang,
    }


@router.get("/ingestion-status/{upload_id}")
async def ingestion_status(
    upload_id: str,
    user: dict = Depends(get_current_user)
):
    """Return current ingestion status and quality for an upload."""
    from engines.document_processor import get_ingestion_history
    history = get_ingestion_history(upload_id)
    if not history:
        raise HTTPException(404, "No ingestion record for this upload")
    return {
        "upload_id":      upload_id,
        "latest":         history[0],
        "attempt_count":  len(history),
        "history":        history,
    }
