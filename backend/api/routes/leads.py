"""
EIP DDR Intelligence v4.4 — Lead Pipeline Routes
Create, manage, and convert opportunities into commercial leads.
"""
import uuid, datetime
from fastapi import APIRouter, HTTPException, Depends, Request
from pydantic import BaseModel
from typing import Optional, List
from core.database import (create_lead, list_leads, get_lead, update_lead,
                            get_lead_pipeline_summary)
from core.auth import get_current_user, require_permission
from core.audit import audit_from_request

router = APIRouter()


class LeadCreate(BaseModel):
    opportunity_id: str = ""
    title: str
    customer: str = ""
    rig: str = ""
    well: str = ""
    field: str = ""
    product_line: str = ""
    description: str = ""
    evidence: str = ""
    priority: str = "medium"
    owner: str = "Unassigned"
    due_date: str = ""
    notes: str = ""


class LeadUpdate(BaseModel):
    title: Optional[str] = None
    customer: Optional[str] = None
    rig: Optional[str] = None
    well: Optional[str] = None
    field: Optional[str] = None
    product_line: Optional[str] = None
    description: Optional[str] = None
    evidence: Optional[str] = None
    priority: Optional[str] = None
    owner: Optional[str] = None
    due_date: Optional[str] = None
    status: Optional[str] = None
    notes: Optional[str] = None


@router.get("/")
async def get_leads(
    status: Optional[str] = None,
    owner: Optional[str] = None,
    priority: Optional[str] = None,
    user: dict = Depends(get_current_user)
):
    return list_leads(status=status, owner=owner, priority=priority)


@router.get("/summary")
async def lead_summary(user: dict = Depends(get_current_user)):
    return get_lead_pipeline_summary()


@router.get("/{lead_id}")
async def get_lead_detail(lead_id: str, user: dict = Depends(get_current_user)):
    lead = get_lead(lead_id)
    if not lead:
        raise HTTPException(404, "Lead not found")
    return lead


@router.post("/")
async def create_lead_endpoint(
    body: LeadCreate,
    request: Request,
    user: dict = Depends(require_permission("convert_lead"))
):
    lead_data = body.model_dump()
    lead_data["created_by"] = user.get("email", "")
    lead_data["id"] = str(uuid.uuid4())
    lead = create_lead(lead_data)
    audit_from_request(request, "LEAD_CREATED", user=user,
                       detail=f"Lead created: {body.title} | {body.product_line} | {body.rig}",
                       resource_id=lead["id"])
    return lead


@router.patch("/{lead_id}")
async def update_lead_endpoint(
    lead_id: str,
    body: LeadUpdate,
    request: Request,
    user: dict = Depends(require_permission("validate"))
):
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    updated = update_lead(lead_id, updates)
    if not updated:
        raise HTTPException(404, "Lead not found")
    audit_from_request(request, "OPP_STATUS_CHANGE", user=user,
                       detail=f"Lead updated: {updates}",
                       resource_id=lead_id)
    return updated


@router.post("/from-opportunity/{opp_id}")
async def convert_to_lead(
    opp_id: str,
    request: Request,
    user: dict = Depends(require_permission("convert_lead"))
):
    """Convert an opportunity directly into a commercial lead."""
    from core.database import get_db, update_opp_validation
    conn = get_db()
    opp = conn.execute("SELECT * FROM opportunities WHERE id=?", (opp_id,)).fetchone()
    conn.close()
    if not opp:
        raise HTTPException(404, "Opportunity not found")
    opp = dict(opp)

    # Build lead from opportunity data
    lead_data = {
        "id":             str(uuid.uuid4()),
        "opportunity_id": opp_id,
        "title":          opp.get("title",""),
        "customer":       opp.get("contact_name",""),
        "rig":            opp.get("rig",""),
        "well":           opp.get("well",""),
        "field":          opp.get("field",""),
        "product_line":   opp.get("product_line",""),
        "description":    opp.get("what_we_sell",""),
        "evidence":       opp.get("evidence_text","")[:500],
        "priority":       "high" if opp.get("urgency") in ("immediate","5_days") else "medium",
        "owner":          "Unassigned",
        "due_date":       "",
        "status":         "open",
        "created_by":     user.get("email",""),
        "notes":          f"Converted from opportunity. Competitor: {opp.get('competitor','none')}. Action: {opp.get('action','')}",
    }
    lead = create_lead(lead_data)

    # Update opportunity validation status to "converted"
    update_opp_validation(opp_id, "converted", user.get("email",""),
                          comment=f"Converted to lead {lead['id']}")

    audit_from_request(request, "LEAD_CREATED", user=user,
                       detail=f"Opportunity {opp.get('title','')} converted to lead",
                       resource_id=lead["id"])
    return {"lead": lead, "opportunity_id": opp_id, "status": "converted"}
