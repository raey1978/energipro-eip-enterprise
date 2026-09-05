"""
EIP DDR Intelligence v4.4 — Validation Workflow Routes
Manage opportunity validation status, bulk operations, evidence search.
"""
from fastapi import APIRouter, HTTPException, Request, Depends
from pydantic import BaseModel
from typing import Optional, List
from core.database import (update_opp_validation, bulk_update_validation,
                            search_evidence, get_confidence_score)
from core.auth import get_current_user, require_permission
from core.audit import audit_from_request

router = APIRouter()

VALID_STATUSES = {"new", "accepted", "rejected", "needs_review", "converted"}


class ValidationUpdate(BaseModel):
    validation_status: str
    validator_comment: str = ""
    rejection_reason: str = ""
    next_action: str = ""


class BulkValidation(BaseModel):
    opportunity_ids: List[str]
    validation_status: str
    comment: str = ""


class EvidenceSearchParams(BaseModel):
    query: Optional[str] = None
    product_line: Optional[str] = None
    rig: Optional[str] = None
    field: Optional[str] = None
    competitor: Optional[str] = None
    validation_status: Optional[str] = None
    min_confidence: int = 0
    limit: int = 100


@router.patch("/{opp_id}")
async def validate_opportunity(
    opp_id: str,
    body: ValidationUpdate,
    request: Request,
    user: dict = Depends(require_permission("validate"))
):
    if body.validation_status not in VALID_STATUSES:
        raise HTTPException(400, f"Invalid status. Use: {', '.join(sorted(VALID_STATUSES))}")

    updated = update_opp_validation(
        opp_id,
        body.validation_status,
        validated_by=user.get("email",""),
        comment=body.validator_comment,
        rejection_reason=body.rejection_reason,
        next_action=body.next_action,
    )
    if not updated:
        raise HTTPException(404, "Opportunity not found")

    # Sync in-memory store
    from fastapi import Request as FRequest
    audit_from_request(request, "OPP_VALIDATED", user=user,
                       detail=f"Status: {body.validation_status} | Comment: {body.validator_comment[:80]}",
                       resource_id=opp_id)
    return updated


@router.post("/bulk")
async def bulk_validate(
    body: BulkValidation,
    request: Request,
    user: dict = Depends(require_permission("validate"))
):
    if body.validation_status not in VALID_STATUSES:
        raise HTTPException(400, f"Invalid status.")
    if not body.opportunity_ids:
        raise HTTPException(400, "No opportunity IDs provided.")
    if len(body.opportunity_ids) > 200:
        raise HTTPException(400, "Maximum 200 opportunities per bulk operation.")

    affected = bulk_update_validation(
        body.opportunity_ids,
        body.validation_status,
        validated_by=user.get("email",""),
        comment=body.comment,
    )
    audit_from_request(request, "OPP_VALIDATED", user=user,
                       detail=f"Bulk validation: {affected} opps → {body.validation_status}",
                       resource_id=None)
    return {"updated": affected, "status": body.validation_status}


@router.get("/evidence/search")
async def evidence_search(
    query: Optional[str] = None,
    product_line: Optional[str] = None,
    rig: Optional[str] = None,
    field: Optional[str] = None,
    competitor: Optional[str] = None,
    validation_status: Optional[str] = None,
    min_confidence: int = 0,
    limit: int = 100,
    user: dict = Depends(get_current_user)
):
    results = search_evidence(
        query=query,
        product_line=product_line,
        rig=rig,
        field=field,
        competitor=competitor,
        validation_status=validation_status,
        min_confidence=min_confidence,
        limit=min(limit, 500),
    )
    return {"count": len(results), "results": results}


@router.get("/confidence/{opp_id}")
async def get_confidence_breakdown(
    opp_id: str,
    request: Request,
    user: dict = Depends(get_current_user)
):
    """Return full confidence score breakdown for an opportunity."""
    # Try stored breakdown first
    stored = get_confidence_score(opp_id)
    if stored:
        return stored

    # Fall back to computing on the fly from opportunity data
    from core.database import get_db
    conn = get_db()
    row = conn.execute("SELECT * FROM opportunities WHERE id=?", (opp_id,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, "Opportunity not found")

    opp = dict(row)
    import json
    try:
        opp["matched_keywords"] = json.loads(opp.get("matched_keywords","[]") or "[]")
    except Exception:
        opp["matched_keywords"] = []

    from engines.ingestion_pipeline import compute_confidence_breakdown
    breakdown = compute_confidence_breakdown(opp)
    return {
        "opportunity_id":  opp_id,
        "title":           opp.get("title",""),
        "confidence":      opp.get("confidence", 0),
        "breakdown":       breakdown,
        "source_file":     opp.get("source_file",""),
        "source_page":     opp.get("source_page", 0),
        "source_section":  opp.get("source_section",""),
        "evidence_text":   opp.get("evidence_text",""),
        "matched_keywords":opp.get("matched_keywords",[]),
        "competitor":      opp.get("competitor",""),
        "validation_status":    opp.get("validation_status","new"),
        "validator_comment":    opp.get("validator_comment",""),
        "validated_by":         opp.get("validated_by",""),
        "validated_at":         opp.get("validated_at",""),
    }
