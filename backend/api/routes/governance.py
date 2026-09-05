"""
EIP v6.2 — Intelligence Governance & Audit API Routes
/api/governance/* — governance records, evidence comparison,
intelligence quality, decision journal, report generation.
"""
import logging, json, datetime
from fastapi import APIRouter, Request, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from typing import Optional
from pydantic import BaseModel
from core.auth import get_current_user, require_permission
from core.database import get_db
from core.audit import audit_from_request

router = APIRouter()
logger = logging.getLogger("eip.governance")

def _store(r): return getattr(r.app.state, "intelligence_store", {})


# ── Governance Records ────────────────────────────────────────────────────────

@router.get("/records")
async def list_governance_records(
    insight_type: Optional[str] = None,
    min_trust: int = 0,
    limit: int = 100,
    user: dict = Depends(get_current_user)
):
    from engines.intelligence.governance_layer import get_active_governance_records
    return get_active_governance_records(insight_type=insight_type, min_trust=min_trust, limit=limit)


@router.get("/records/{governance_id}")
async def get_governance_record(
    governance_id: str,
    user: dict = Depends(get_current_user)
):
    from engines.intelligence.governance_layer import get_governance_record
    rec = get_governance_record(governance_id)
    if not rec: raise HTTPException(404, "Governance record not found")
    return rec


@router.get("/history/{insight_type}/{insight_id}")
async def governance_history(
    insight_type: str,
    insight_id: str,
    user: dict = Depends(get_current_user)
):
    """Full version history for an insight — side-by-side comparison ready."""
    from engines.intelligence.governance_layer import get_governance_history
    history = get_governance_history(insight_type, insight_id)
    if not history: raise HTTPException(404, "No governance history found")

    # Build side-by-side comparison between latest and previous version
    comparison = None
    if len(history) >= 2:
        current  = history[0]
        previous = history[1]
        comparison = {
            "trust_score_change":    current["trust_score"] - previous["trust_score"],
            "evidence_strength_changed": current["evidence_strength"] != previous["evidence_strength"],
            "recommendation_changed":    current["recommendation"] != previous["recommendation"],
            "what_changed":              current.get("change_summary",""),
            "trigger":                   current.get("trigger_type",""),
            "triggered_by":              current.get("triggered_by",""),
            "previous_trust":            previous["trust_score"],
            "current_trust":             current["trust_score"],
            "previous_strength":         previous["evidence_strength"],
            "current_strength":          current["evidence_strength"],
        }

    return {
        "insight_type":   insight_type,
        "insight_id":     insight_id,
        "version_count":  len(history),
        "history":        history,
        "latest_version": history[0] if history else None,
        "comparison":     comparison,
    }


@router.post("/record")
async def create_governance_record(
    request: Request,
    user: dict = Depends(require_permission("validate"))
):
    """Manually create / update a governance record for an insight."""
    from engines.intelligence.governance_layer import create_governance_record
    from engines.intelligence.trust_layer import calculate_trust_envelope

    body = await request.json()
    insight_type = body.get("insight_type","opportunity")
    insight_id   = body.get("insight_id","")
    if not insight_id: raise HTTPException(400,"insight_id required")

    # Fetch the insight and calculate trust
    conn = get_db()
    table_map = {
        "opportunity":  "opportunities",
        "change_event": "change_events",
        "campaign":     "campaigns",
        "trend_signal": "trend_signals",
    }
    table = table_map.get(insight_type)
    row   = conn.execute(f"SELECT * FROM {table} WHERE id=?", (insight_id,)).fetchone() if table else None
    conn.close()
    if not row: raise HTTPException(404,"Insight not found")
    data = dict(row)

    te  = calculate_trust_envelope(insight_type, data)
    rec = create_governance_record(
        insight_type=insight_type, insight_id=insight_id,
        title=body.get("title", data.get("title",insight_id)),
        recommendation=body.get("recommendation",""),
        trust_envelope=te,
        trigger_type="human", triggered_by=user.get("email",""),
        trigger_detail=body.get("trigger_detail","Manual governance record"),
    )
    audit_from_request(request,"OPP_VALIDATED",user=user,
                       detail=f"Governance record v{rec['version']} for {insight_type}:{insight_id}",
                       resource_id=rec["governance_id"])
    return rec


@router.post("/refresh-all")
async def refresh_all_governance(
    request: Request,
    user: dict = Depends(require_permission("upload"))
):
    """Refresh governance records for all active opportunities. Run after upload."""
    from engines.intelligence.governance_layer import create_governance_record
    from engines.intelligence.trust_layer import calculate_trust_envelope
    from engines.intelligence.commercial_engine import calculate_commercial_intelligence

    conn = get_db()
    opps = conn.execute(
        "SELECT id,title,product_line,rig,well,field,confidence,urgency,estimated_value,"
        "competitor,validation_status,evidence_text,evidence_section,source_file,source_page,"
        "upload_id,created_at,matched_keywords FROM opportunities LIMIT 200"
    ).fetchall()
    conn.close()

    created = 0
    for row in opps:
        opp = dict(row)
        try:
            kws = json.loads(opp.get("matched_keywords","[]") or "[]")
        except: kws = []
        opp["matched_keywords"] = kws
        te  = calculate_trust_envelope("opportunity", opp)
        ci  = calculate_commercial_intelligence(opp)
        rec = create_governance_record(
            insight_type="opportunity", insight_id=opp["id"],
            title=opp.get("title",""),
            recommendation=ci.get("recommended_action",""),
            trust_envelope=te,
            source_upload_ids=[opp.get("upload_id","")],
            trigger_type="upload",
            triggered_by=user.get("email","system"),
            commercial_priority=ci.get("commercial_priority",0),
            revenue_expected=ci.get("revenue_potential",0),
        )
        created += 1

    logger.info("governance_refresh", extra={"created": created, "user": user.get("email")})
    return {"created": created, "status": "complete"}


# ── Evidence Comparison ───────────────────────────────────────────────────────

@router.get("/compare")
async def compare_evidence(
    upload_a: str = Query(..., description="First upload ID"),
    upload_b: str = Query(..., description="Second upload ID"),
    user: dict = Depends(get_current_user)
):
    """Side-by-side comparison between two DDR uploads."""
    from engines.intelligence.governance_layer import compare_uploads
    return compare_uploads(upload_a, upload_b)


@router.get("/compare/latest-two")
async def compare_latest_two(user: dict = Depends(get_current_user)):
    """Compare the two most recent uploads automatically."""
    from engines.intelligence.governance_layer import compare_uploads
    conn = get_db()
    uploads = conn.execute(
        "SELECT id FROM uploads ORDER BY upload_ts DESC LIMIT 2"
    ).fetchall()
    conn.close()
    if len(uploads) < 2:
        return {"error": "Need at least 2 uploads for comparison", "uploads_available": len(uploads)}
    return compare_uploads(uploads[0]["id"], uploads[1]["id"])


# ── Intelligence Quality ──────────────────────────────────────────────────────

@router.get("/quality")
async def intelligence_quality(user: dict = Depends(get_current_user)):
    """Compute the overall Intelligence Quality Score."""
    from engines.intelligence.governance_layer import compute_intelligence_quality
    return compute_intelligence_quality()


# ── Decision Journal ──────────────────────────────────────────────────────────

class DecisionEntry(BaseModel):
    governance_id: str = ""
    insight_type: str = "opportunity"
    insight_id: str
    decision_type: str   # customer_contacted|proposal_submitted|award|loss|meeting|other
    title: str
    description: str = ""
    outcome: str = ""
    owner: str = ""
    customer: str = ""
    product_line: str = ""
    pipeline_item_id: str = ""
    revenue_actual: float = 0


@router.get("/journal")
async def get_journal(
    insight_id: Optional[str] = None,
    decision_type: Optional[str] = None,
    limit: int = 50,
    user: dict = Depends(get_current_user)
):
    from engines.intelligence.governance_layer import get_decision_journal
    return get_decision_journal(insight_id=insight_id, decision_type=decision_type, limit=limit)


@router.get("/journal/timeline")
async def journal_timeline(user: dict = Depends(get_current_user)):
    from engines.intelligence.governance_layer import get_decision_timeline
    return get_decision_timeline()


@router.post("/journal")
async def add_journal_entry(
    body: DecisionEntry,
    request: Request,
    user: dict = Depends(get_current_user)
):
    from engines.intelligence.governance_layer import add_decision
    entry = add_decision(body.model_dump(), user.get("email",""))
    audit_from_request(request, "OPP_STATUS_CHANGE", user=user,
                       detail=f"Decision journal: {body.decision_type} — {body.title}",
                       resource_id=entry.get("id",""))
    return entry


# ── PDF Audit Package Export ──────────────────────────────────────────────────

@router.get("/export/audit-pdf/{insight_id}")
async def export_audit_pdf(
    insight_id: str,
    token: str = Query(default=None),
    user: dict = Depends(_get_user_export := __import__('api.routes.export',
        fromlist=['_get_user_export'])._get_user_export if False else get_current_user)
):
    """Export a complete audit package for an insight as a PDF."""
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib import colors
        from reportlab.lib.units import cm
        from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table,
                                         TableStyle, HRFlowable, KeepTogether)
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.enums import TA_LEFT, TA_CENTER
        import io
    except ImportError:
        raise HTTPException(500, "reportlab not installed")

    from engines.intelligence.governance_layer import get_governance_history
    from engines.intelligence.trust_layer import calculate_trust_envelope, OBS_TYPE_META
    from core.database import get_settings

    settings   = get_settings()
    co         = settings.get("company_name","EnergiPro")
    today      = datetime.date.today().strftime("%d %B %Y")
    history    = get_governance_history("opportunity", insight_id)

    conn = get_db()
    row  = conn.execute("SELECT * FROM opportunities WHERE id=?", (insight_id,)).fetchone()
    decisions = conn.execute(
        "SELECT * FROM decision_journal WHERE insight_id=? ORDER BY created_at", (insight_id,)
    ).fetchall()
    upload    = None
    if row:
        upload = conn.execute("SELECT * FROM uploads WHERE id=?", (dict(row).get("upload_id",""),)).fetchone()
    conn.close()

    if not row: raise HTTPException(404,"Opportunity not found")
    opp = dict(row)
    try: opp["matched_keywords"]=json.loads(opp.get("matched_keywords","[]") or "[]")
    except: opp["matched_keywords"]=[]

    te = calculate_trust_envelope("opportunity", opp)

    # Build PDF
    NAVY  = colors.HexColor("#0D1F3C")
    TEAL  = colors.HexColor("#1F6460")
    GREEN = colors.HexColor("#10B981")
    AMBER = colors.HexColor("#F59E0B")
    RED   = colors.HexColor("#EF4444")
    LGREY = colors.HexColor("#F4F6FB")
    MGREY = colors.HexColor("#E2E8F0")

    def sty(name, **kw):
        return ParagraphStyle(name, parent=getSampleStyleSheet()["Normal"], **kw)
    def hr(c=MGREY, t=0.5):
        return HRFlowable(width="100%", color=c, thickness=t, spaceAfter=6, spaceBefore=4)

    buf   = io.BytesIO()
    doc   = SimpleDocTemplate(buf, pagesize=A4,
                              leftMargin=1.8*cm, rightMargin=1.8*cm,
                              topMargin=1.5*cm, bottomMargin=1.8*cm)
    story = []

    # Cover
    story.append(Paragraph(f"<b>{co}</b>", sty("h1",fontName="Helvetica-Bold",fontSize=20,textColor=NAVY)))
    story.append(Paragraph("Intelligence Audit Package", sty("h2",fontName="Helvetica",fontSize=14,textColor=TEAL)))
    story.append(Paragraph(f"Generated: {today} | EIP v6.2 | Confidential",
                            sty("s",fontName="Helvetica",fontSize=10,textColor=colors.HexColor("#64748B"),spaceAfter=12)))
    story.append(hr(NAVY,1)); story.append(Spacer(1,12))

    # Section 1: Executive Summary
    story.append(Paragraph("<b>1. Executive Summary</b>", sty("s1",fontName="Helvetica-Bold",fontSize=13,textColor=NAVY,spaceAfter=8)))
    summary_data = [
        ["Opportunity", opp.get("title","")],
        ["Product Line", opp.get("product_line","")],
        ["Rig / Well", f"{opp.get('rig','—')} / {opp.get('well','—')}"],
        ["Field", opp.get("field","")],
        ["Competitor", opp.get("competitor","None detected")],
        ["AI Confidence", f"{opp.get('confidence',0)}%"],
        ["Trust Score", f"{te.get('trust_score',0)}/100"],
        ["Evidence Strength", te.get("evidence_strength",{}).get("label","—") if isinstance(te.get("evidence_strength"),dict) else str(te.get("evidence_strength","—"))],
        ["Observation Type", te.get("observation_type","")],
        ["Governance Versions", str(len(history))],
        ["Source File", f"{opp.get('source_file','—')} p.{opp.get('source_page',0) or '?'}"],
    ]
    t = Table(summary_data, colWidths=[5.5*cm, 11.5*cm])
    t.setStyle(TableStyle([
        ("FONTNAME",(0,0),(0,-1),"Helvetica-Bold"),
        ("FONTSIZE",(0,0),(-1,-1),10),
        ("BACKGROUND",(0,0),(0,-1),LGREY),
        ("TOPPADDING",(0,0),(-1,-1),5),("BOTTOMPADDING",(0,0),(-1,-1),5),
        ("ROWBACKGROUNDS",(0,0),(-1,-1),[colors.white,LGREY]),
        ("LINEBELOW",(0,0),(-1,-1),0.3,MGREY),
    ]))
    story.append(t); story.append(Spacer(1,14))

    # Section 2: Evidence Chain
    story.append(Paragraph("<b>2. Evidence Chain</b>", sty("s2",fontName="Helvetica-Bold",fontSize=13,textColor=NAVY,spaceAfter=8)))
    if upload:
        upload_d = dict(upload)
        story.append(Paragraph(
            f"<b>Source Document:</b> {upload_d.get('filename','—')} | "
            f"Report Date: {upload_d.get('report_date','—')} | "
            f"Upload ID: {opp.get('upload_id','—')[:16]}…",
            sty("ev",fontName="Helvetica",fontSize=10,textColor=colors.HexColor("#334155"),spaceAfter=6)
        ))
    story.append(Paragraph(
        f"<b>Extracted Section:</b> {opp.get('evidence_section','—')} | Page {opp.get('source_page',0) or '?'}",
        sty("ev2",fontName="Helvetica",fontSize=10,spaceAfter=4)
    ))
    ev_text = (opp.get("evidence_text","") or "No evidence captured.")[:800]
    story.append(Paragraph(f"<b>Extracted Text:</b>",
                            sty("evh",fontName="Helvetica-Bold",fontSize=10,spaceAfter=4)))
    story.append(Paragraph(ev_text,
                            sty("evt",fontName="Courier",fontSize=9,leading=13,
                                leftIndent=12,textColor=colors.HexColor("#334155"))))
    kws = opp.get("matched_keywords",[])
    if kws:
        story.append(Paragraph(f"<b>Detection Keywords:</b> {', '.join(kws[:8])}",
                                sty("kw",fontName="Helvetica",fontSize=10,spaceAfter=6)))
    story.append(Spacer(1,10))

    # Section 3: Trust Assessment
    story.append(Paragraph("<b>3. Trust Assessment</b>", sty("s3",fontName="Helvetica-Bold",fontSize=13,textColor=NAVY,spaceAfter=8)))
    ev_str = te.get("evidence_strength",{})
    ev_label = ev_str.get("label","—") if isinstance(ev_str,dict) else str(ev_str)
    ev_desc  = ev_str.get("description","") if isinstance(ev_str,dict) else ""
    trust_data = [
        ["Trust Score",        f"{te.get('trust_score',0)}/100"],
        ["Evidence Strength",  f"{ev_label}"],
        ["Observation Type",   te.get("observation_type","")],
        ["Data Sources",       str(te.get("source_count",1))],
        ["Data Freshness",     te.get("data_freshness_label","UNKNOWN")],
        ["Assumption Quality", te.get("assumption_quality","")],
        ["Needs Review",       "YES" if te.get("needs_review") else "No"],
        ["Contradictions",     str(len(te.get("contradictions",[]) or []))],
    ]
    tt = Table(trust_data, colWidths=[5.5*cm, 11.5*cm])
    tt.setStyle(TableStyle([
        ("FONTNAME",(0,0),(0,-1),"Helvetica-Bold"),("FONTSIZE",(0,0),(-1,-1),10),
        ("BACKGROUND",(0,0),(0,-1),LGREY),("TOPPADDING",(0,0),(-1,-1),5),
        ("BOTTOMPADDING",(0,0),(-1,-1),5),("ROWBACKGROUNDS",(0,0),(-1,-1),[colors.white,LGREY]),
        ("LINEBELOW",(0,0),(-1,-1),0.3,MGREY),
    ]))
    story.append(tt); story.append(Spacer(1,8))
    if ev_desc:
        story.append(Paragraph(ev_desc, sty("evd",fontName="Helvetica",fontSize=9,textColor=colors.HexColor("#64748B"))))

    # Challenge Points
    challenges = te.get("challenge_points",[]) or []
    if challenges:
        story.append(Spacer(1,8))
        story.append(Paragraph("<b>Challenge Points:</b>", sty("cp",fontName="Helvetica-Bold",fontSize=10,spaceAfter=4)))
        for cp in challenges:
            story.append(Paragraph(f"• {cp}", sty("cpi",fontName="Helvetica",fontSize=9,leftIndent=12,textColor=colors.HexColor("#B45309"))))

    # Alternative Hypotheses
    alts = te.get("alternative_hypotheses",[]) or []
    if alts:
        story.append(Spacer(1,8))
        story.append(Paragraph("<b>Alternative Interpretations:</b>", sty("ai",fontName="Helvetica-Bold",fontSize=10,spaceAfter=4)))
        for alt in alts:
            story.append(Paragraph(f"◈ {alt.get('hypothesis','')}", sty("alh",fontName="Helvetica-Bold",fontSize=9,textColor=colors.HexColor("#1D4ED8"),spaceAfter=2)))
            story.append(Paragraph(f"  Probability: {alt.get('probability','')}",  sty("alp",fontName="Helvetica",fontSize=9,leftIndent=12,textColor=colors.HexColor("#64748B"))))

    story.append(Spacer(1,12))

    # Section 4: Recommendation History
    if history:
        story.append(Paragraph("<b>4. Recommendation History</b>", sty("s4",fontName="Helvetica-Bold",fontSize=13,textColor=NAVY,spaceAfter=8)))
        for i, rec in enumerate(history):
            story.append(Paragraph(
                f"<b>Version {rec.get('version',i+1)}</b> — {rec.get('created_at','')[:16]} — "
                f"Trust: {rec.get('trust_score',0)}/100 — {rec.get('evidence_strength','—')} — "
                f"Status: {rec.get('status','')}",
                sty("rh",fontName="Helvetica",fontSize=9,textColor=colors.HexColor("#334155"),spaceAfter=3)
            ))
            if rec.get("change_summary"):
                story.append(Paragraph(f"  Change: {rec['change_summary']}",
                                        sty("rc",fontName="Helvetica",fontSize=9,
                                            textColor=colors.HexColor("#B45309"),leftIndent=12,spaceAfter=4)))
        story.append(Spacer(1,12))

    # Section 5: Decision Journal
    if decisions:
        story.append(Paragraph("<b>5. Decision Journal</b>", sty("s5",fontName="Helvetica-Bold",fontSize=13,textColor=NAVY,spaceAfter=8)))
        for dec in decisions:
            d = dict(dec)
            story.append(Paragraph(
                f"<b>{d.get('decision_type','').replace('_',' ').title()}</b> — {d.get('created_at','')[:16]} — {d.get('title','')}",
                sty("dj",fontName="Helvetica-Bold",fontSize=10,textColor=TEAL,spaceAfter=3)
            ))
            if d.get("description"):
                story.append(Paragraph(d["description"],sty("djd",fontName="Helvetica",fontSize=9,leftIndent=12,textColor=colors.HexColor("#334155"),spaceAfter=4)))
        story.append(Spacer(1,12))

    # Section 6: Limitations
    limitations = te.get("limitations",[]) or []
    if limitations:
        story.append(Paragraph("<b>6. Known Limitations</b>", sty("s6",fontName="Helvetica-Bold",fontSize=13,textColor=NAVY,spaceAfter=8)))
        for lim in limitations:
            story.append(Paragraph(f"• {lim}", sty("lim",fontName="Helvetica",fontSize=9,leftIndent=12,textColor=colors.HexColor("#64748B"),spaceAfter=4)))

    # Audit Trail Footer
    story.append(hr(NAVY,1))
    audit_data = te.get("audit_trail",{})
    story.append(Paragraph(
        f"{co} — Intelligence Audit Package | EIP v6.2 | {today} | "
        f"Engine: {audit_data.get('engine','')} | "
        f"Method: {audit_data.get('method','')} | CONFIDENTIAL",
        sty("foot",fontName="Helvetica",fontSize=7,textColor=colors.HexColor("#94A3B8"),alignment=TA_CENTER)
    ))

    doc.build(story)
    buf.seek(0)
    audit_from_request(request,"EXPORT_PDF",user=user,
                       detail=f"Audit package for opportunity {insight_id[:8]}")
    fname = f"{co.replace(' ','_')}_Audit_{insight_id[:8]}_{datetime.date.today()}.pdf"
    return StreamingResponse(buf, media_type="application/pdf",
                             headers={"Content-Disposition":f'attachment; filename="{fname}"'})


# ── Weekly Report Generation ──────────────────────────────────────────────────

@router.get("/export/weekly-report")
async def weekly_report_pdf(
    request: Request,
    token: str = Query(default=None),
    user: dict = Depends(get_current_user)
):
    """Generate a Weekly Intelligence Report PDF."""
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib import colors
        from reportlab.lib.units import cm
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.enums import TA_CENTER
        import io
    except ImportError:
        raise HTTPException(500, "reportlab not installed")

    from engines.intelligence.market_intelligence import get_market_pulse, get_market_aggregates
    from engines.intelligence.change_detection import get_change_feed
    from engines.intelligence.campaign_detector import get_campaigns
    from engines.intelligence.governance_layer import compute_intelligence_quality
    from core.database import get_settings

    settings = get_settings()
    co       = settings.get("company_name","EnergiPro")
    today    = datetime.date.today().strftime("%d %B %Y")
    store    = _store(request)
    opps     = store.get("opportunities",[])

    pulse   = get_market_pulse()
    agg     = get_market_aggregates()
    changes = get_change_feed(limit=10)
    camps   = get_campaigns()[:5]
    quality = compute_intelligence_quality()

    NAVY=colors.HexColor("#0D1F3C"); TEAL=colors.HexColor("#1F6460")
    LGREY=colors.HexColor("#F4F6FB"); MGREY=colors.HexColor("#E2E8F0")
    GREEN=colors.HexColor("#10B981"); AMBER=colors.HexColor("#F59E0B")
    RED=colors.HexColor("#EF4444")

    def sty(name,**kw): return ParagraphStyle(name,parent=getSampleStyleSheet()["Normal"],**kw)
    def hr(c=MGREY,t=0.5): return HRFlowable(width="100%",color=c,thickness=t,spaceAfter=6,spaceBefore=4)
    def fv(v): return f"${v/1_000_000:.1f}M" if v>=1_000_000 else f"${v/1_000:.0f}k" if v>=1000 else f"${v:.0f}"

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf,pagesize=A4,leftMargin=1.8*cm,rightMargin=1.8*cm,topMargin=1.5*cm,bottomMargin=1.8*cm)
    story=[]

    # Header
    story.append(Paragraph(f"<b>{co}</b>",sty("h1",fontName="Helvetica-Bold",fontSize=20,textColor=NAVY)))
    story.append(Paragraph("Weekly Market Intelligence Report",sty("h2",fontName="Helvetica",fontSize=14,textColor=TEAL)))
    story.append(Paragraph(f"Week ending {today} | EIP v6.2 | Intelligence Quality: {quality['composite_score']}/100 ({quality['grade_label']})",
                            sty("s",fontName="Helvetica",fontSize=10,textColor=colors.HexColor("#64748B"),spaceAfter=12)))
    story.append(hr(NAVY,1)); story.append(Spacer(1,10))

    # Executive Summary
    imm_opps = [o for o in opps if o.get("urgency") in ("immediate","5_days")]
    total_pipeline = sum(o.get("estimated_value",0) for o in opps)
    story.append(Paragraph("<b>Executive Summary</b>",sty("es",fontName="Helvetica-Bold",fontSize=13,textColor=NAVY,spaceAfter=6)))
    story.append(Paragraph(
        f"As of {today}, the platform has identified {len(opps)} commercial opportunities "
        f"totalling {fv(total_pipeline)} in potential revenue. "
        f"{len(imm_opps)} require immediate or 5-day action. "
        f"{len(changes)} market changes detected in this period. "
        f"{len(camps)} active drilling campaigns identified. "
        f"Intelligence quality score: {quality['composite_score']}/100.",
        sty("body",fontName="Helvetica",fontSize=11,leading=16,spaceAfter=12)
    ))

    # Market Pulse Table
    M = pulse.get("metrics",{})
    story.append(Paragraph("<b>Market Pulse</b>",sty("mp",fontName="Helvetica-Bold",fontSize=13,textColor=NAVY,spaceAfter=6)))
    def pct_str(m):
        p = m.get("change_pct") if m else None
        return f"{'+' if p and p>0 else ''}{p}%" if p is not None else "N/A (first)"
    pulse_data = [
        ["Metric","Current","vs Previous"],
        ["Active Rigs",        str(M.get("active_rigs",{}).get("current","—")),  pct_str(M.get("active_rigs"))],
        ["Active Fields",      str(M.get("active_fields",{}).get("current","—")),pct_str(M.get("active_fields"))],
        ["Total Opportunities",str(M.get("total_opps",{}).get("current","—")),   pct_str(M.get("total_opps"))],
        ["Immediate Actions",  str(M.get("immediate_opps",{}).get("current","—")),pct_str(M.get("immediate_opps"))],
        ["Pipeline Value",     fv(M.get("pipeline",{}).get("current",0) or 0),   pct_str(M.get("pipeline"))],
        ["Activity Index",     str(M.get("activity_intensity",{}).get("current","—")),pct_str(M.get("activity_intensity"))],
    ]
    pt = Table(pulse_data, colWidths=[6*cm,4*cm,4*cm])
    pt.setStyle(TableStyle([
        ("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),("BACKGROUND",(0,0),(-1,0),NAVY),
        ("TEXTCOLOR",(0,0),(-1,0),colors.white),("FONTSIZE",(0,0),(-1,-1),10),
        ("TOPPADDING",(0,0),(-1,-1),5),("BOTTOMPADDING",(0,0),(-1,-1),5),
        ("ROWBACKGROUNDS",(0,1),(-1,-1),[colors.white,LGREY]),
        ("LINEBELOW",(0,0),(-1,-1),0.3,MGREY),
    ]))
    story.append(pt); story.append(Spacer(1,12))

    # Market Changes
    if changes:
        story.append(Paragraph("<b>Market Changes This Period</b>",sty("mc",fontName="Helvetica-Bold",fontSize=13,textColor=NAVY,spaceAfter=6)))
        for ch in changes[:6]:
            story.append(Paragraph(f"<b>{ch.get('title','')}</b>",sty("cht",fontName="Helvetica-Bold",fontSize=10,textColor=TEAL,spaceAfter=3)))
            story.append(Paragraph(ch.get("summary",""),sty("chs",fontName="Helvetica",fontSize=9,leftIndent=12,textColor=colors.HexColor("#334155"),spaceAfter=3)))
            if ch.get("recommended_action"):
                story.append(Paragraph(f"→ {ch['recommended_action']}",sty("cha",fontName="Helvetica",fontSize=9,leftIndent=12,textColor=colors.HexColor("#1D4ED8"),spaceAfter=6)))
        story.append(Spacer(1,10))

    # Active Campaigns
    if camps:
        story.append(Paragraph("<b>Active Campaigns</b>",sty("ac",fontName="Helvetica-Bold",fontSize=13,textColor=NAVY,spaceAfter=6)))
        for c in camps[:4]:
            rigs = c.get("rigs",[]) if isinstance(c.get("rigs"),list) else []
            story.append(Paragraph(
                f"<b>{c.get('name','')}</b> — {c.get('campaign_stage','').replace('_',' ').title()} — "
                f"{len(rigs)} rigs — {fv(c.get('estimated_market_value',0))} potential — "
                f"{c.get('confidence',0)}% confidence",
                sty("camp",fontName="Helvetica",fontSize=10,spaceAfter=5)
            ))
        story.append(Spacer(1,10))

    # Intelligence Quality
    story.append(Paragraph("<b>Intelligence Quality Assessment</b>",sty("iq",fontName="Helvetica-Bold",fontSize=13,textColor=NAVY,spaceAfter=6)))
    dim_data = [["Dimension","Score","Weight"]]
    for dim,score in quality.get("dimension_scores",{}).items():
        w = quality.get("weights",{}).get(dim,0)
        dim_data.append([dim.replace("_"," ").title(), f"{score}/100", f"{round(w*100)}%"])
    dim_data.append(["COMPOSITE SCORE",f"{quality['composite_score']}/100 ({quality['grade_label']})", ""])
    qt = Table(dim_data, colWidths=[7*cm,4*cm,3*cm])
    qt.setStyle(TableStyle([
        ("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),("BACKGROUND",(0,0),(-1,0),NAVY),
        ("TEXTCOLOR",(0,0),(-1,0),colors.white),("FONTSIZE",(0,0),(-1,-1),10),
        ("TOPPADDING",(0,0),(-1,-1),5),("BOTTOMPADDING",(0,0),(-1,-1),5),
        ("ROWBACKGROUNDS",(0,1),(-1,-2),[colors.white,LGREY]),
        ("FONTNAME",(0,-1),(-1,-1),"Helvetica-Bold"),("BACKGROUND",(0,-1),(-1,-1),LGREY),
        ("LINEBELOW",(0,0),(-1,-1),0.3,MGREY),
    ]))
    story.append(qt); story.append(Spacer(1,12))

    # Footer
    story.append(hr(NAVY,1))
    story.append(Paragraph(
        f"{co} Weekly Intelligence Report | EIP v6.2 | {today} | "
        f"Intelligence Quality: {quality['composite_score']}/100 | CONFIDENTIAL",
        sty("foot",fontName="Helvetica",fontSize=7,textColor=colors.HexColor("#94A3B8"),alignment=TA_CENTER)
    ))

    doc.build(story)
    buf.seek(0)
    audit_from_request(request,"EXPORT_PDF",user=user,detail="Weekly intelligence report exported")
    fname=f"{co.replace(' ','_')}_Weekly_Report_{datetime.date.today()}.pdf"
    return StreamingResponse(buf,media_type="application/pdf",
                             headers={"Content-Disposition":f'attachment; filename="{fname}"'})


# ── Intelligence Quality History ──────────────────────────────────────────────

@router.get("/quality/history")
async def quality_history(
    limit: int = 20,
    user: dict = Depends(get_current_user)
):
    """Quality score trend over time — one point per upload."""
    from engines.intelligence.governance_layer import get_quality_history
    return get_quality_history(limit=limit)


# ── Client Intelligence Report (per operator) ────────────────────────────────

@router.get("/export/client-report/{operator}")
async def client_intelligence_report(
    operator: str,
    token: str = Query(default=None),
    user: dict = Depends(get_current_user),
    request: Request = None
):
    """
    Generate a per-operator client intelligence PDF.
    Covers: activity history, competitor presence, opportunities, engagement recommendation.
    """
    import urllib.parse, datetime, io
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib import colors
        from reportlab.lib.units import cm
        from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer,
                                         Table, TableStyle, HRFlowable)
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.enums import TA_CENTER
    except ImportError:
        raise HTTPException(500, "reportlab not installed")

    op_name  = urllib.parse.unquote(operator)
    conn     = get_db()
    settings = __import__('core.database', fromlist=['get_settings']).get_settings()
    co       = settings.get("company_name", "EnergiPro Solutions")
    today    = datetime.date.today().strftime("%d %B %Y")

    # Fetch all opportunities related to this operator (by field or contact)
    opps = conn.execute(
        """SELECT * FROM opportunities
           WHERE field LIKE ? OR contact_name LIKE ? OR suggested_contact LIKE ?
           ORDER BY created_at DESC LIMIT 100""",
        (f"%{op_name}%", f"%{op_name}%", f"%{op_name}%")
    ).fetchall()
    comps = conn.execute(
        "SELECT DISTINCT normalized, COUNT(*) n FROM competitors GROUP BY normalized ORDER BY n DESC LIMIT 10"
    ).fetchall()
    conn.close()

    opps_list = [dict(o) for o in opps]
    if not opps_list:
        # Fall back to all opportunities if no operator-specific match
        conn2 = get_db()
        opps_list = [dict(o) for o in conn2.execute(
            "SELECT * FROM opportunities ORDER BY confidence DESC LIMIT 30"
        ).fetchall()]
        conn2.close()

    from collections import Counter
    pls   = Counter(o.get("product_line","") for o in opps_list)
    rigs  = list(set(o.get("rig","")  for o in opps_list if o.get("rig")))
    wells = list(set(o.get("well","") for o in opps_list if o.get("well")))
    total_val = sum(o.get("estimated_value",0) for o in opps_list)
    imm   = [o for o in opps_list if o.get("urgency") in ("immediate","5_days")]

    NAVY=colors.HexColor("#1A4A5C"); TEAL=colors.HexColor("#1F6460")
    ORANGE=colors.HexColor("#E07820"); LGREY=colors.HexColor("#F4F6FB")
    MGREY=colors.HexColor("#E2E8F0"); GREEN=colors.HexColor("#10B981")

    def sty(name,**kw): return ParagraphStyle(name,parent=getSampleStyleSheet()["Normal"],**kw)
    def hr(c=MGREY,t=0.5): return HRFlowable(width="100%",color=c,thickness=t,spaceAfter=6,spaceBefore=4)
    def fv(v): return f"${v/1_000_000:.1f}M" if v>=1_000_000 else f"${v/1_000:.0f}k" if v>=1000 else f"${v:.0f}"

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf,pagesize=A4,leftMargin=1.8*cm,rightMargin=1.8*cm,
                            topMargin=1.5*cm,bottomMargin=1.8*cm)
    story = []

    story.append(Paragraph(f"<b>{co}</b>",sty("h1",fontName="Helvetica-Bold",fontSize=20,textColor=NAVY)))
    story.append(Paragraph("Client Intelligence Report",sty("h2",fontName="Helvetica",fontSize=14,textColor=TEAL)))
    story.append(Paragraph(f"Operator / Customer: {op_name} | Generated: {today} | EIP v6.3",
                            sty("s",fontName="Helvetica",fontSize=10,textColor=colors.HexColor("#64748B"),spaceAfter=10)))
    story.append(hr(NAVY,1)); story.append(Spacer(1,10))

    # Activity overview
    story.append(Paragraph("<b>Activity Overview</b>",sty("ao",fontName="Helvetica-Bold",fontSize=13,textColor=NAVY,spaceAfter=6)))
    ov_data = [
        ["Metric","Value"],
        ["Opportunities Detected",   str(len(opps_list))],
        ["Immediate/5-Day Actions",  str(len(imm))],
        ["Total Pipeline Potential", fv(total_val)],
        ["Active Rigs",              str(len(rigs))],
        ["Wells Tracked",            str(len(wells))],
        ["Service Lines Demanded",   str(len(pls))],
    ]
    ot = Table(ov_data, colWidths=[7*cm,7*cm])
    ot.setStyle(TableStyle([
        ("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),("BACKGROUND",(0,0),(-1,0),NAVY),
        ("TEXTCOLOR",(0,0),(-1,0),colors.white),("FONTSIZE",(0,0),(-1,-1),10),
        ("TOPPADDING",(0,0),(-1,-1),5),("BOTTOMPADDING",(0,0),(-1,-1),5),
        ("ROWBACKGROUNDS",(0,1),(-1,-1),[colors.white,LGREY]),
        ("LINEBELOW",(0,0),(-1,-1),0.3,MGREY),
    ]))
    story.append(ot); story.append(Spacer(1,12))

    # Service demand
    story.append(Paragraph("<b>Service Line Demand</b>",sty("sd",fontName="Helvetica-Bold",fontSize=13,textColor=NAVY,spaceAfter=6)))
    if pls:
        pl_data = [["Product Line","Opportunities","% of Total"]]
        total_opps = max(len(opps_list),1)
        for pl,cnt in pls.most_common(8):
            pl_data.append([pl, str(cnt), f"{round(cnt/total_opps*100)}%"])
        plt = Table(pl_data, colWidths=[8*cm,3.5*cm,2.5*cm])
        plt.setStyle(TableStyle([
            ("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),("BACKGROUND",(0,0),(-1,0),TEAL),
            ("TEXTCOLOR",(0,0),(-1,0),colors.white),("FONTSIZE",(0,0),(-1,-1),10),
            ("TOPPADDING",(0,0),(-1,-1),5),("BOTTOMPADDING",(0,0),(-1,-1),5),
            ("ROWBACKGROUNDS",(0,1),(-1,-1),[colors.white,LGREY]),
            ("LINEBELOW",(0,0),(-1,-1),0.3,MGREY),
        ]))
        story.append(plt); story.append(Spacer(1,10))

    # Recent opportunities
    story.append(Paragraph("<b>Recent Opportunities</b>",sty("ro",fontName="Helvetica-Bold",fontSize=13,textColor=NAVY,spaceAfter=6)))
    for opp in opps_list[:8]:
        story.append(Paragraph(
            f"<b>{opp.get('product_line','')}</b> — {opp.get('rig','—')}/{opp.get('well','—')} — "
            f"Conf:{opp.get('confidence',0)}% — {opp.get('urgency','').replace('_',' ')} — "
            f"{fv(opp.get('estimated_value',0) or 0)}"
            + (f" — vs {opp.get('competitor','')}" if opp.get('competitor') else ""),
            sty("opp",fontName="Helvetica",fontSize=9,leftIndent=12,spaceAfter=4)
        ))
    story.append(Spacer(1,10))

    # Engagement recommendation
    story.append(Paragraph("<b>Recommended Engagement Strategy</b>",
                            sty("rs",fontName="Helvetica-Bold",fontSize=13,textColor=NAVY,spaceAfter=6)))
    if imm:
        story.append(Paragraph(
            f"IMMEDIATE ACTION: {len(imm)} opportunities require response within 5 days. "
            f"Contact the drilling department for {', '.join(set(o.get('rig','') for o in imm[:3]))} immediately.",
            sty("rs_body",fontName="Helvetica-Bold",fontSize=11,textColor=colors.HexColor("#B45309"),spaceAfter=6)
        ))
    top_pl = pls.most_common(1)[0][0] if pls else ""
    if top_pl:
        story.append(Paragraph(
            f"Primary service line demand: {top_pl}. Ensure equipment availability and assign BD owner.",
            sty("rs_b2",fontName="Helvetica",fontSize=10,spaceAfter=6)
        ))
    story.append(Paragraph(
        "This report is based on DDR intelligence data only. "
        "Opportunity values are indicative estimates. Always verify with the customer before committing resources.",
        sty("disc",fontName="Helvetica",fontSize=8,textColor=colors.HexColor("#94A3B8"),spaceAfter=6)
    ))

    story.append(hr(NAVY,1))
    story.append(Paragraph(
        f"{co} Client Intelligence Report | EIP v6.3 | {today} | CONFIDENTIAL",
        sty("foot",fontName="Helvetica",fontSize=7,textColor=colors.HexColor("#94A3B8"),alignment=TA_CENTER)
    ))

    doc.build(story)
    buf.seek(0)
    fname = f"{co.replace(' ','_')}_{op_name.replace(' ','_')}_Intelligence_{datetime.date.today()}.pdf"
    from fastapi.responses import StreamingResponse
    return StreamingResponse(buf, media_type="application/pdf",
                             headers={"Content-Disposition": f'attachment; filename="{fname}"'})


# ── Document Ingestion Quality (v6.3C) ───────────────────────────────────────

@router.get("/ingestion-log")
async def ingestion_log(
    limit: int = 50,
    user: dict = Depends(get_current_user)
):
    """Per-upload document processing quality log."""
    import json
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM document_ingestion_log ORDER BY logged_at DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    result = []
    for r in rows:
        d = dict(r)
        try: d["warnings"] = json.loads(d.get("warnings","[]") or "[]")
        except: d["warnings"] = []
        try: d["page_quality_json"] = json.loads(d.get("page_quality_json","{}") or "{}")
        except: d["page_quality_json"] = {}
        result.append(d)
    return result


@router.get("/ingestion-log/{upload_id}")
async def ingestion_log_for_upload(
    upload_id: str,
    user: dict = Depends(get_current_user)
):
    """Full document quality report for a specific upload."""
    import json
    conn = get_db()
    row  = conn.execute(
        "SELECT * FROM document_ingestion_log WHERE upload_id=? ORDER BY logged_at DESC LIMIT 1",
        (upload_id,)
    ).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, "No ingestion log for this upload")
    d = dict(row)
    try: d["warnings"]          = json.loads(d.get("warnings","[]") or "[]")
    except: d["warnings"] = []
    try: d["page_quality_json"] = json.loads(d.get("page_quality_json","{}") or "{}")
    except: d["page_quality_json"] = {}
    return d
