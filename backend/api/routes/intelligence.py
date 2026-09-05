"""
EIP v5.0 — Commercial Intelligence API Routes
Serves commercial priority scores, insights, learning data, customer profiles, daily briefs.
"""
import logging
from fastapi import APIRouter, Request, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional
from core.auth import get_current_user, require_permission
from core.database import get_db
from engines.intelligence.commercial_engine import calculate_commercial_intelligence
from engines.intelligence.learning_engine import (
    record_learning_event, get_learning_stats,
    get_customer_profiles, upsert_customer_profile
)
from engines.intelligence.insights_engine import (
    get_strategic_insights, mark_insight_read,
    generate_strategic_insights, generate_daily_brief
)

router = APIRouter()
logger = logging.getLogger("eip.intelligence")


def _store(request):
    return getattr(request.app.state, "intelligence_store", {})


# ── Commercial Intelligence ───────────────────────────────────────────────────
@router.get("/opportunities")
async def get_commercial_opps(
    request: Request,
    user: dict = Depends(get_current_user)
):
    """Return all opportunities enriched with commercial intelligence scores."""
    opps = _store(request).get("opportunities", [])

    # Get value rates from settings
    conn = get_db()
    vr_row = conn.execute("SELECT value FROM settings WHERE key='value_rates'").fetchone()
    conn.close()
    import json
    vr = {}
    if vr_row:
        try: vr = json.loads(vr_row[0])
        except: pass

    enriched = []
    for opp in opps:
        ci = calculate_commercial_intelligence(opp, vr)
        enriched.append({**opp, "commercial_intelligence": ci})

    # Sort by commercial_priority desc
    enriched.sort(key=lambda x: x["commercial_intelligence"]["commercial_priority"], reverse=True)
    return enriched


@router.get("/opportunity/{opp_id}")
async def get_opp_intelligence(
    opp_id: str,
    request: Request,
    user: dict = Depends(get_current_user)
):
    """Full commercial intelligence for one opportunity."""
    opps = _store(request).get("opportunities", [])
    opp  = next((o for o in opps if o.get("id") == opp_id), None)
    if not opp:
        # Try DB
        conn = get_db()
        row = conn.execute("SELECT * FROM opportunities WHERE id=?", (opp_id,)).fetchone()
        conn.close()
        if not row:
            raise HTTPException(404, "Opportunity not found")
        import json
        opp = dict(row)
        try: opp["matched_keywords"] = json.loads(opp.get("matched_keywords","[]") or "[]")
        except: opp["matched_keywords"] = []

    ci = calculate_commercial_intelligence(opp)
    return {"opportunity": opp, "commercial_intelligence": ci}


@router.get("/summary")
async def intelligence_summary(
    request: Request,
    user: dict = Depends(get_current_user)
):
    """Executive intelligence summary — top metrics for the daily brief card."""
    opps  = _store(request).get("opportunities", [])
    comps = _store(request).get("competitors", [])

    if not opps:
        return {"status": "no_data", "message": "Upload a DDR to generate intelligence."}

    import json
    conn = get_db()
    vr_row = conn.execute("SELECT value FROM settings WHERE key='value_rates'").fetchone()
    conn.close()
    vr = {}
    if vr_row:
        try: vr = json.loads(vr_row[0])
        except: pass

    scores = [calculate_commercial_intelligence(o, vr) for o in opps]

    # Priority distribution
    critical = sum(1 for s in scores if s["commercial_priority"] >= 75)
    high_p   = sum(1 for s in scores if 50 <= s["commercial_priority"] < 75)
    medium_p = sum(1 for s in scores if 30 <= s["commercial_priority"] < 50)

    # Top 5 by priority
    ranked = sorted(zip(opps, scores), key=lambda x: x[1]["commercial_priority"], reverse=True)
    top5 = [{"opp": {k: o.get(k) for k in ["id","title","rig","well","field","product_line","urgency","confidence","estimated_value","competitor"]},
              "ci": s} for o, s in ranked[:5]]

    total_pipeline   = sum(s["revenue_potential"] for s in scores)
    total_risk_adj   = sum(s["risk_adjusted_revenue"] for s in scores)
    avg_win_prob     = round(sum(s["win_probability"] for s in scores) / max(len(scores),1), 1)
    avg_oqi          = round(sum(s["opportunity_quality_index"] for s in scores) / max(len(scores),1), 1)

    from collections import Counter
    comp_names = [c.get("normalized","") for c in comps if c.get("normalized")]
    top_comp = Counter(comp_names).most_common(1)[0] if comp_names else ("None",0)

    return {
        "total_opportunities":    len(opps),
        "critical_priority":      critical,
        "high_priority":          high_p,
        "medium_priority":        medium_p,
        "total_pipeline":         total_pipeline,
        "risk_adjusted_pipeline": total_risk_adj,
        "avg_win_probability":    avg_win_prob,
        "avg_opportunity_quality":avg_oqi,
        "top_competitor":         {"name": top_comp[0], "count": top_comp[1]},
        "top_5":                  top5,
    }


# ── Strategic Insights ────────────────────────────────────────────────────────
@router.get("/insights")
async def get_insights(
    unread_only: bool = False,
    limit: int = 20,
    user: dict = Depends(get_current_user)
):
    return get_strategic_insights(limit=limit, unread_only=unread_only)


@router.post("/insights/generate")
async def generate_insights(
    request: Request,
    user: dict = Depends(require_permission("upload"))
):
    data     = _store(request)
    insights = generate_strategic_insights(data)
    logger.info("insights_generated", extra={"count": len(insights), "user": user.get("email")})
    return {"generated": len(insights), "insights": insights}


@router.patch("/insights/{insight_id}/read")
async def read_insight(insight_id: str, user: dict = Depends(get_current_user)):
    mark_insight_read(insight_id)
    return {"status": "marked_read"}


# ── Daily Brief ───────────────────────────────────────────────────────────────
@router.get("/daily-brief")
async def get_daily_brief(
    request: Request,
    user: dict = Depends(get_current_user)
):
    """Get today's executive brief, generating if not yet created."""
    import datetime, json
    today = datetime.date.today().isoformat()
    conn  = get_db()
    row   = conn.execute("SELECT * FROM daily_briefs WHERE date=? ORDER BY generated_at DESC LIMIT 1",
                         (today,)).fetchone()
    conn.close()

    if row:
        d = dict(row)
        for f in ["opportunities","competitor_moves","insights","actions","kpis"]:
            try: d[f] = json.loads(d.get(f,"[]") or "[]")
            except: d[f] = [] if f != "kpis" else {}
        return d

    # Generate fresh
    data  = _store(request)
    brief = generate_daily_brief(data)
    return brief


@router.post("/daily-brief/regenerate")
async def regenerate_brief(
    request: Request,
    user: dict = Depends(require_permission("upload"))
):
    data  = _store(request)
    brief = generate_daily_brief(data)
    return brief


# ── Learning Engine ───────────────────────────────────────────────────────────
@router.get("/learning/stats")
async def learning_stats(user: dict = Depends(get_current_user)):
    return get_learning_stats()


class CorrectionEvent(BaseModel):
    opportunity_id: str
    field_name: str
    original_value: str
    corrected_value: str
    context: dict = {}


@router.post("/learning/correction")
async def record_correction(
    body: CorrectionEvent,
    user: dict = Depends(get_current_user)
):
    record_learning_event(
        event_type="human_correction",
        opportunity_id=body.opportunity_id,
        user_id=user.get("sub"),
        user_email=user.get("email"),
        original_value=body.original_value,
        corrected_value=body.corrected_value,
        field_name=body.field_name,
        context=body.context,
        was_correct=False,
    )
    return {"status": "recorded"}


# ── Customer Intelligence ─────────────────────────────────────────────────────
@router.get("/customers")
async def get_customers(
    limit: int = 50,
    user: dict = Depends(get_current_user)
):
    return get_customer_profiles(limit=limit)


@router.get("/customers/refresh")
async def refresh_customers(
    request: Request,
    user: dict = Depends(require_permission("upload"))
):
    """Rebuild customer profiles from current opportunity data."""
    opps = _store(request).get("opportunities", [])
    for opp in opps:
        customer = opp.get("contact_name") or opp.get("suggested_contact") or opp.get("field")
        if customer:
            upsert_customer_profile(customer, opp)
    return {"refreshed": len(opps)}


# ── Competitor Intelligence ───────────────────────────────────────────────────
@router.get("/competitors")
async def competitor_intelligence(
    request: Request,
    user: dict = Depends(get_current_user)
):
    """Detailed competitor intelligence with activity trends and market position."""
    comps = _store(request).get("competitors", [])
    opps  = _store(request).get("opportunities", [])

    from collections import defaultdict, Counter
    profiles = defaultdict(lambda: {
        "name": "", "mentions": 0, "rigs": set(), "fields": set(),
        "product_lines": set(), "services": set(), "rigs_list": [],
        "displacement_value": 0,
    })

    rig_to_field = {o.get("rig",""): o.get("field","") for o in opps}
    rig_to_opp   = {}
    for o in opps:
        r = o.get("rig","")
        if r and o.get("competitor"):
            rig_to_opp[r] = o

    for c in comps:
        name = c.get("normalized","")
        if not name: continue
        p = profiles[name]
        p["name"]     = name
        p["mentions"] += 1
        rig = c.get("rig","")
        if rig:
            p["rigs"].add(rig)
            p["rigs_list"].append(rig)
            field = rig_to_field.get(rig,"")
            if field: p["fields"].add(field)
            opp = rig_to_opp.get(rig)
            if opp: p["displacement_value"] += opp.get("estimated_value",0)
        if c.get("service_category"): p["services"].add(c["service_category"])

    # Map opp product lines to competitors
    for o in opps:
        comp = o.get("competitor","")
        if comp and comp in profiles:
            profiles[comp]["product_lines"].add(o.get("product_line",""))

    result = []
    for name, p in sorted(profiles.items(), key=lambda x: -x[1]["mentions"]):
        result.append({
            "name":                name,
            "mentions":            p["mentions"],
            "rig_count":           len(p["rigs"]),
            "field_count":         len(p["fields"]),
            "fields":              list(p["fields"])[:5],
            "rigs":                list(p["rigs"])[:8],
            "product_lines":       list(p["product_lines"]),
            "services":            list(p["services"]),
            "displacement_value":  round(p["displacement_value"]),
            "competitive_strength":10 if name in ("SLB","Baker Hughes","Halliburton") else
                                   7 if name in ("Weatherford","NESR","Expro") else 5,
            "threat_level":        "High" if p["mentions"] >= 10 else
                                   "Medium" if p["mentions"] >= 4 else "Low",
        })
    return result


# ── Prediction / Forecast ─────────────────────────────────────────────────────
@router.get("/forecast")
async def get_forecast(
    request: Request,
    user: dict = Depends(get_current_user)
):
    """30-day pipeline forecast with trend analysis and confidence intervals."""
    from engines.intelligence.prediction_engine import generate_forecast
    data = _store(request)
    return generate_forecast(data)


@router.get("/recommendations")
async def get_recommendations(
    request: Request,
    user: dict = Depends(get_current_user)
):
    """Personalised recommendations based on user role and current data."""
    from engines.intelligence.prediction_engine import get_recommendation_for_user
    data = _store(request)
    role = user.get("role", "viewer")
    return get_recommendation_for_user(role, data)


# ── Commercial Playbooks ──────────────────────────────────────────────────────
@router.get("/playbooks")
async def list_playbooks(user: dict = Depends(get_current_user)):
    """List all available commercial playbooks."""
    from engines.intelligence.playbook_engine import get_all_playbook_names
    return get_all_playbook_names()


@router.get("/playbooks/{product_line:path}")
async def get_playbook(product_line: str, user: dict = Depends(get_current_user)):
    """Get the full commercial playbook for a product line."""
    from engines.intelligence.playbook_engine import get_playbook
    import urllib.parse
    pl = urllib.parse.unquote(product_line)
    playbook = get_playbook(pl)
    if not playbook.get("key_differentiators"):
        raise HTTPException(404, f"No playbook found for '{pl}'")
    return {"product_line": pl, "playbook": playbook}


# ── Document Classification ───────────────────────────────────────────────────
@router.post("/classify-document")
async def classify_document(
    request: Request,
    user: dict = Depends(get_current_user)
):
    """Classify a document's type from its text content."""
    body = await request.json()
    text     = body.get("text","")
    filename = body.get("filename","")
    from engines.intelligence.document_classifier import classify_document as clf
    result = clf(text, filename)
    return {
        "doc_type":       result.doc_type,
        "doc_type_label": result.doc_type_label,
        "confidence":     result.confidence,
        "report_date":    result.report_date,
        "subject":        result.subject,
        "signals":        result.signals,
    }


# ── Knowledge Graph Data ──────────────────────────────────────────────────────
@router.get("/knowledge-graph")
async def knowledge_graph_data(
    request: Request,
    user: dict = Depends(get_current_user)
):
    """
    Returns node-link data for the Knowledge Graph visualization.
    Connects: Rig → Well → Field → Competitor → Opportunity → Product Line
    """
    data  = _store(request)
    opps  = data.get("opportunities", [])
    comps = data.get("competitors", [])

    nodes = {}
    links = []

    def add_node(nid: str, label: str, node_type: str, weight: int = 1, meta: dict = None):
        if nid not in nodes:
            nodes[nid] = {"id": nid, "label": label, "type": node_type, "weight": weight, **(meta or {})}
        else:
            nodes[nid]["weight"] += 1

    def add_link(source: str, target: str, rel: str):
        links.append({"source": source, "target": target, "rel": rel})

    # Build graph from opportunities
    for opp in opps[:100]:  # Cap for performance
        rig   = opp.get("rig","")
        well  = opp.get("well","")
        field = opp.get("field","")
        pl    = opp.get("product_line","")
        comp  = opp.get("competitor","")
        opp_id = opp.get("id","")

        rig_id   = f"rig:{rig}"
        well_id  = f"well:{well}"
        field_id = f"field:{field}"
        pl_id    = f"pl:{pl}"
        comp_id  = f"comp:{comp}" if comp else None
        opp_nid  = f"opp:{opp_id[:8]}"

        if rig:
            add_node(rig_id,   rig,   "rig",         meta={"urgency": opp.get("urgency","")})
            add_node(field_id, field, "field")
            add_link(rig_id, field_id, "operates_in")

        if well and rig:
            add_node(well_id, well, "well")
            add_link(rig_id, well_id, "drilling")

        if pl:
            add_node(pl_id, pl, "product_line", meta={"color": "#2563EB"})
            if rig: add_link(rig_id, pl_id, "needs")

        if comp and rig:
            add_node(comp_id, comp, "competitor", meta={"color": "#EF4444"})
            add_link(rig_id, comp_id, "has_competitor")

        # Opportunity node (only top 20 to avoid clutter)
        if opp.get("confidence",0) >= 80 and len([n for n in nodes if n.startswith("opp:")]) < 20:
            add_node(opp_nid, opp.get("title","Opp")[:30], "opportunity",
                     meta={"confidence": opp.get("confidence",0),
                           "value": opp.get("estimated_value",0),
                           "urgency": opp.get("urgency","")})
            if rig:   add_link(opp_nid, rig_id, "on_rig")
            if pl:    add_link(opp_nid, pl_id,  "product_line")

    # Add competitor nodes from competitor table
    for c in comps:
        comp = c.get("normalized","")
        rig  = c.get("rig","")
        if comp and rig:
            comp_id = f"comp:{comp}"
            rig_id  = f"rig:{rig}"
            if comp_id not in nodes:
                add_node(comp_id, comp, "competitor")
            if rig_id in nodes:
                link_exists = any(l["source"]==rig_id and l["target"]==comp_id for l in links)
                if not link_exists:
                    add_link(rig_id, comp_id, "has_competitor")

    # Node type statistics
    type_counts = {}
    for n in nodes.values():
        t = n.get("type","?")
        type_counts[t] = type_counts.get(t, 0) + 1

    return {
        "nodes": list(nodes.values()),
        "links": links,
        "stats": {
            "total_nodes": len(nodes),
            "total_links": len(links),
            "by_type": type_counts,
        }
    }
