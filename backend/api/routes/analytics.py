"""EIP DDR Intelligence v4.4 — Analytics Routes (Wave 4)"""
from fastapi import APIRouter, Request, Depends
from core.database import load_latest, get_settings
from core.auth import get_current_user
from collections import Counter, defaultdict

router = APIRouter()

def _store(request):
    s = getattr(request.app.state, "intelligence_store", None)
    if s and s.get("opportunities"):
        return s
    data = load_latest()
    if data:
        if not hasattr(request.app.state, "intelligence_store"):
            request.app.state.intelligence_store = {}
        request.app.state.intelligence_store.update(data)
        return request.app.state.intelligence_store
    return {}

@router.get("/executive-summary")
async def executive_summary(request: Request, user: dict = Depends(get_current_user)):
    s = _store(request)
    return {"narrative": s.get("narrative","No DDR uploaded yet."),
            "report_date": s.get("report_date",""), "filename": s.get("filename","")}

@router.get("/kpis")
async def kpis(request: Request, user: dict = Depends(get_current_user)):
    s = _store(request)
    k = s.get("kpis", {})
    if not k:
        k = {"open_opportunities":0,"pipeline_total":0,"immediate_targets":0,
             "active_rigs":0,"competitor_mentions":0,"reports_processed":0}
    return k

@router.get("/product-line-demand")
async def product_line_demand(request: Request, user: dict = Depends(get_current_user)):
    opps = _store(request).get("opportunities", [])
    summary = {}
    for o in opps:
        pl = o.get("product_line","Other")
        if pl not in summary:
            summary[pl] = {"product_line":pl,"opportunity_count":0,"total_value":0,
                           "rigs":set(),"wells":set(),"competitors":set(),"top_confidence":0}
        summary[pl]["opportunity_count"] += 1
        summary[pl]["total_value"] += o.get("estimated_value",0)
        if o.get("rig"): summary[pl]["rigs"].add(o["rig"])
        if o.get("well"): summary[pl]["wells"].add(o["well"])
        if o.get("competitor"): summary[pl]["competitors"].add(o["competitor"])
        summary[pl]["top_confidence"] = max(summary[pl]["top_confidence"], o.get("confidence",0))
    return [{"product_line":pl,"opportunity_count":d["opportunity_count"],
             "total_value":d["total_value"],"rigs":list(d["rigs"])[:5],
             "wells":list(d["wells"])[:5],"competitors":list(d["competitors"]),
             "top_confidence":d["top_confidence"]}
            for pl,d in sorted(summary.items(), key=lambda x:-x[1]["total_value"])]

@router.get("/competitor-breakdown")
async def competitor_breakdown(request: Request, user: dict = Depends(get_current_user)):
    comps = _store(request).get("competitors", [])
    summary = {}
    for c in comps:
        name = c.get("normalized", c.get("raw_name","Unknown"))
        if name not in summary:
            summary[name] = {"company":name,"mentions":0,"rigs":set(),"wells":set(),"services":set(),"statuses":[]}
        summary[name]["mentions"] += 1
        if c.get("rig"): summary[name]["rigs"].add(c["rig"])
        if c.get("well"): summary[name]["wells"].add(c["well"])
        if c.get("service_category"): summary[name]["services"].add(c["service_category"])
        if c.get("status"): summary[name]["statuses"].append(c["status"])
    return [{"company":n,"mentions":d["mentions"],"rig_count":len(d["rigs"]),
             "rigs":list(d["rigs"])[:8],"wells":list(d["wells"])[:5],
             "services":list(d["services"])}
            for n,d in sorted(summary.items(),key=lambda x:-x[1]["mentions"])]

@router.get("/lifecycle")
async def lifecycle(request: Request, user: dict = Depends(get_current_user)):
    return _store(request).get("lifecycle", [])

@router.get("/trend")
async def trend(user: dict = Depends(get_current_user)):
    """Compare the latest two upload snapshots (persists across replace-mode uploads)."""
    from core.database import get_snapshots
    snaps = get_snapshots(10)
    if len(snaps) < 2:
        return {"available": False, "snapshots": snaps}
    cur, prev = snaps[0], snaps[1]
    pl_delta = {}
    for pl in set(list(cur.get("pl_counts", {}).keys()) + list(prev.get("pl_counts", {}).keys())):
        pl_delta[pl] = cur.get("pl_counts", {}).get(pl, 0) - prev.get("pl_counts", {}).get(pl, 0)
    return {"available": True, "current": cur, "previous": prev,
            "delta": {
                "opp_count":   cur["opp_count"]   - prev["opp_count"],
                "pipeline":    cur["pipeline"]    - prev["pipeline"],
                "immediate":   cur["immediate"]   - prev["immediate"],
                "rigs_parsed": cur["rigs_parsed"] - prev["rigs_parsed"],
                "product_lines": pl_delta,
            }}

@router.get("/settings")
async def settings_get(user: dict = Depends(get_current_user)):
    return get_settings()

@router.get("/fields")
async def fields_list(request: Request, user: dict = Depends(get_current_user)):
    """Return unique field names for filter dropdown."""
    opps = _store(request).get("opportunities", [])
    fields = sorted(set(o.get("field","") for o in opps if o.get("field","")))
    return fields

@router.get("/operators")
async def operators_list(request: Request, user: dict = Depends(get_current_user)):
    """Return unique contractors/operators extracted from competitor + rig data."""
    comps = _store(request).get("competitors", [])
    operators = sorted(set(c.get("normalized","") for c in comps if c.get("normalized","")))
    return operators

@router.get("/action-summary")
async def action_summary(user: dict = Depends(get_current_user)):
    from core.database import load_actions
    actions = load_actions()
    total = len(actions)
    by_status = {}
    by_priority = {}
    total_value = 0
    for a in actions:
        s = a.get("status","open")
        by_status[s] = by_status.get(s,0) + 1
        p = a.get("priority","medium")
        by_priority[p] = by_priority.get(p,0) + 1
    return {
        "total": total,
        "open": by_status.get("open",0),
        "contacted": by_status.get("contacted",0),
        "won": by_status.get("won",0),
        "lost": by_status.get("lost",0),
        "by_priority": by_priority,
        "conversion_rate": round(by_status.get("won",0)/max(total,1)*100,1),
    }

# ── Wave 4: Enhanced dashboard endpoints ─────────────────────────────────────

@router.get("/executive-overview")
async def executive_overview_full(request: Request, user: dict = Depends(get_current_user)):
    """Full executive dashboard: KPIs + product line breakdown + competitor summary + actions."""
    s    = _store(request)
    opps = s.get("opportunities", [])
    comps = s.get("competitors", [])
    k    = s.get("kpis", {})

    # Validation breakdown
    val_counts = Counter(o.get("validation_status","new") for o in opps)

    # Product line summary
    pl_summary = defaultdict(lambda: {"count":0,"value":0,"immediate":0,"high_conf":0})
    for o in opps:
        pl = o.get("product_line","Other")
        pl_summary[pl]["count"]     += 1
        pl_summary[pl]["value"]     += o.get("estimated_value",0)
        pl_summary[pl]["immediate"] += 1 if o.get("urgency") in ("immediate","5_days") else 0
        pl_summary[pl]["high_conf"] += 1 if o.get("confidence",0) >= 80 else 0

    top_pl = sorted(
        [{"product_line":pl, **v} for pl,v in pl_summary.items()],
        key=lambda x: -x["value"]
    )[:6]

    # Top rigs by opportunity count
    rig_counts = Counter(o.get("rig","?") for o in opps if o.get("rig"))
    top_rigs = [{"rig":r,"count":c} for r,c in rig_counts.most_common(8)]

    # Top competitors
    comp_counts = Counter(c.get("normalized","?") for c in comps if c.get("normalized"))
    top_comps = [{"company":n,"mentions":c} for n,c in comp_counts.most_common(6)]

    # High-confidence opps (≥80%)
    high_conf = [o for o in opps if o.get("confidence",0) >= 80]

    # Accepted / converted counts
    from core.database import list_leads, load_actions
    leads   = list_leads()
    actions = load_actions()

    return {
        "kpis": {
            **k,
            "high_confidence":    len(high_conf),
            "accepted":           val_counts.get("accepted",0),
            "needs_review":       val_counts.get("needs_review",0),
            "converted_leads":    val_counts.get("converted",0),
            "total_leads":        len(leads),
            "open_actions":       sum(1 for a in actions if a.get("status")=="open"),
        },
        "validation_breakdown": dict(val_counts),
        "top_product_lines":   top_pl,
        "top_rigs":            top_rigs,
        "top_competitors":     top_comps,
        "report_date":         s.get("report_date",""),
        "filename":            s.get("filename",""),
    }


@router.get("/rig-timeline")
async def rig_timeline(request: Request, user: dict = Depends(get_current_user),
                       rig: str = None, field: str = None):
    """Rig activity timeline: per-rig opportunity and competitor events."""
    s    = _store(request)
    opps = s.get("opportunities", [])
    comps = s.get("competitors", [])
    lc_list = s.get("lifecycle", [])

    # Filter
    if rig:   opps = [o for o in opps if o.get("rig","").upper() == rig.upper()]
    if field: opps = [o for o in opps if o.get("field","").lower() == field.lower()]

    # Build per-rig timeline
    rigs_data = defaultdict(lambda: {
        "rig":"","field":"","well":"","opportunities":[],"competitors":[],"lifecycle":None
    })

    for o in opps:
        r = o.get("rig","?")
        rigs_data[r]["rig"]   = r
        rigs_data[r]["field"] = o.get("field","")
        rigs_data[r]["well"]  = o.get("well","")
        rigs_data[r]["opportunities"].append({
            "id":               o.get("id"),
            "title":            o.get("title",""),
            "product_line":     o.get("product_line",""),
            "urgency":          o.get("urgency",""),
            "confidence":       o.get("confidence",0),
            "estimated_value":  o.get("estimated_value",0),
            "competitor":       o.get("competitor",""),
            "evidence_text":    (o.get("evidence_text","") or "")[:200],
            "evidence_section": o.get("evidence_section",""),
            "validation_status":o.get("validation_status","new"),
            "timing_label":     o.get("timing_label",""),
        })

    for c in comps:
        r = c.get("rig","?")
        if r in rigs_data:
            rigs_data[r]["competitors"].append({
                "company":  c.get("normalized",""),
                "service":  c.get("service_category",""),
                "status":   c.get("status",""),
                "evidence": (c.get("evidence","") or "")[:150],
            })

    for lc in lc_list:
        r = lc.get("rig","?")
        if r in rigs_data:
            rigs_data[r]["lifecycle"] = {
                "current_stage": lc.get("current_stage",""),
                "next_stage":    lc.get("next_stage",""),
                "confidence":    lc.get("confidence",0),
                "commercial_rec":lc.get("commercial_rec",""),
                "timing":        lc.get("timing_estimate",""),
            }

    # Sort by number of immediate opportunities
    result = sorted(
        rigs_data.values(),
        key=lambda x: (
            -sum(1 for o in x["opportunities"] if o["urgency"] in ("immediate","5_days")),
            -len(x["opportunities"])
        )
    )
    return {"rigs": result, "total_rigs": len(result)}


@router.get("/heat-map")
async def competitor_heat_map(request: Request, user: dict = Depends(get_current_user)):
    """Competitor presence heat map: company × product line × field × frequency."""
    s     = _store(request)
    comps = s.get("competitors", [])
    opps  = s.get("opportunities", [])

    # Build matrix: company → product_line → count
    matrix = defaultdict(lambda: defaultdict(int))
    comp_meta = defaultdict(lambda: {"rigs": set(), "fields": set(), "services": set()})
    rig_to_field = {o.get("rig",""):o.get("field","") for o in opps if o.get("rig")}

    for c in comps:
        name    = c.get("normalized","?")
        svc     = c.get("service_category","Other")
        rig     = c.get("rig","")
        field   = rig_to_field.get(rig,"")
        matrix[name][svc] += 1
        comp_meta[name]["rigs"].add(rig)
        comp_meta[name]["fields"].add(field)
        comp_meta[name]["services"].add(svc)

    # Build heat map rows
    all_services = sorted(set(
        svc for company_svcs in matrix.values() for svc in company_svcs
    ))
    rows = []
    for company, svc_counts in sorted(matrix.items(), key=lambda x: -sum(x[1].values())):
        rows.append({
            "company":       company,
            "total":         sum(svc_counts.values()),
            "rig_count":     len(comp_meta[company]["rigs"]),
            "field_count":   len(comp_meta[company]["fields"]),
            "services":      dict(svc_counts),
            "top_service":   max(svc_counts, key=svc_counts.get) if svc_counts else "",
            "fields":        list(comp_meta[company]["fields"] - {""})[:4],
        })

    return {
        "rows":         rows,
        "service_cols": all_services,
        "total_mentions": len(comps),
    }


@router.get("/seven-day-plan")
async def seven_day_plan(request: Request, user: dict = Depends(get_current_user)):
    """
    Auto-generated 7-day commercial action plan.
    Based on accepted / high-confidence / immediate opportunities.
    """
    s    = _store(request)
    opps = s.get("opportunities", [])

    urgency_order = {"immediate":0, "5_days":1, "7_days":2, "30_days":3, "future":4}

    # Priority: accepted first, then high-confidence immediate
    priority_opps = sorted(
        [o for o in opps if
         o.get("validation_status") in ("accepted","new") and
         o.get("urgency") in ("immediate","5_days","7_days")],
        key=lambda o: (
            0 if o.get("validation_status")=="accepted" else 1,
            urgency_order.get(o.get("urgency","future"),9),
            -o.get("confidence",0)
        )
    )[:20]

    def action_items(opp):
        urg   = opp.get("urgency","")
        pl    = opp.get("product_line","")
        comp  = opp.get("competitor","")
        rig   = opp.get("rig","")
        well  = opp.get("well","")
        field = opp.get("field","")
        items = []

        # Primary call-to-action
        items.append({
            "type":     "primary",
            "priority": "high" if urg in ("immediate","5_days") else "medium",
            "action":   opp.get("action","Contact client immediately."),
            "contact":  opp.get("suggested_contact","Technical team"),
            "contact_name": opp.get("contact_name",""),
        })
        # Competitor displacement note
        if comp:
            items.append({
                "type":     "intel",
                "priority": "medium",
                "action":   f"Competitor intelligence: {comp} on {rig}/{well}. "
                            f"Prepare displacement strategy for {pl}.",
                "contact":  "Commercial Manager",
            })
        # Proposal prep
        items.append({
            "type":     "prep",
            "priority": "medium",
            "action":   f"Prepare technical proposal for {pl} — {opp.get('what_we_sell','')[:100]}",
            "contact":  "Technical Sales",
        })
        return items

    plan_items = []
    for opp in priority_opps:
        plan_items.append({
            "opportunity_id":   opp.get("id"),
            "title":            opp.get("title",""),
            "rig":              opp.get("rig",""),
            "well":             opp.get("well",""),
            "field":            opp.get("field",""),
            "product_line":     opp.get("product_line",""),
            "urgency":          opp.get("urgency",""),
            "confidence":       opp.get("confidence",0),
            "estimated_value":  opp.get("estimated_value",0),
            "competitor":       opp.get("competitor",""),
            "validation_status":opp.get("validation_status","new"),
            "timing_label":     opp.get("timing_label",""),
            "action_items":     action_items(opp),
        })

    total_value = sum(p.get("estimated_value",0) for p in plan_items)
    return {
        "plan":          plan_items,
        "total_actions": len(plan_items),
        "total_value":   total_value,
        "report_date":   s.get("report_date",""),
    }
