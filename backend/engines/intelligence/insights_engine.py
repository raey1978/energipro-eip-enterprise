"""
EIP v5.0 — Strategic Insights Engine
Automatically detects market signals, competitor patterns, and emerging opportunities.
"""
import uuid, datetime, json
from collections import Counter, defaultdict
from core.database import get_db


def generate_strategic_insights(data: dict, upload_id: str = None) -> list:
    """
    Analyse current intelligence store and generate strategic insights.
    Returns list of insight dicts.
    """
    opps   = data.get("opportunities", [])
    comps  = data.get("competitors", [])
    lc     = data.get("lifecycle", [])
    insights = []
    ts     = datetime.datetime.utcnow().isoformat()

    if not opps:
        return []

    # ── 1. Competitor dominance alert ────────────────────────────────────────
    comp_counts = Counter(o.get("competitor","") for o in opps if o.get("competitor"))
    if comp_counts:
        top_comp, top_count = comp_counts.most_common(1)[0]
        total_with_comp = sum(comp_counts.values())
        dominance_pct = round(top_count / max(len(opps), 1) * 100)
        if dominance_pct >= 25:
            insights.append({
                "id": str(uuid.uuid4()), "ts": ts,
                "insight_type": "competitor_dominance",
                "title": f"⚠ {top_comp} detected on {top_count} opportunities ({dominance_pct}%)",
                "summary": (f"{top_comp} appears on {top_count} out of {len(opps)} opportunities "
                            f"({dominance_pct}% share). This represents significant competitive "
                            f"exposure. Prioritise displacement strategy for {top_comp} accounts."),
                "evidence": [f"{o.get('rig')}/{o.get('well')} — {o.get('product_line')}"
                             for o in opps if o.get("competitor") == top_comp][:5],
                "severity": "high" if dominance_pct >= 40 else "medium",
                "competitors": [top_comp],
                "upload_id": upload_id,
            })

    # ── 2. Immediate opportunity cluster ─────────────────────────────────────
    immediate = [o for o in opps if o.get("urgency") in ("immediate","5_days")]
    if len(immediate) >= 3:
        total_val = sum(o.get("estimated_value",0) for o in immediate)
        fields = list(set(o.get("field","") for o in immediate if o.get("field")))[:3]
        insights.append({
            "id": str(uuid.uuid4()), "ts": ts,
            "insight_type": "immediate_cluster",
            "title": f"🔥 {len(immediate)} opportunities require immediate action",
            "summary": (f"There are {len(immediate)} immediate or 5-day opportunities "
                        f"with combined pipeline of ${total_val:,.0f}. "
                        f"Fields active: {', '.join(fields) if fields else 'multiple'}. "
                        f"Business development must act now."),
            "evidence": [f"#{o.get('rank',0)} {o.get('title','')}" for o in immediate[:5]],
            "severity": "critical",
            "fields": fields,
            "upload_id": upload_id,
        })

    # ── 3. Product line demand surge ─────────────────────────────────────────
    pl_counts = Counter(o.get("product_line","") for o in opps)
    top_pl, top_pl_count = pl_counts.most_common(1)[0] if pl_counts else ("", 0)
    if top_pl_count >= 5:
        top_pl_val = sum(o.get("estimated_value",0) for o in opps
                         if o.get("product_line") == top_pl)
        insights.append({
            "id": str(uuid.uuid4()), "ts": ts,
            "insight_type": "demand_surge",
            "title": f"📈 High demand for {top_pl} ({top_pl_count} opportunities)",
            "summary": (f"{top_pl} is the most demanded service line with {top_pl_count} "
                        f"opportunities and ${top_pl_val:,.0f} pipeline value. "
                        f"Ensure equipment availability and team readiness."),
            "evidence": [],
            "severity": "info",
            "product_lines": [top_pl],
            "upload_id": upload_id,
        })

    # ── 4. Rigs with no competitor (clean approach) ───────────────────────────
    no_comp_opps = [o for o in opps if not o.get("competitor") and
                    o.get("urgency") in ("immediate","5_days","7_days")]
    if no_comp_opps:
        insights.append({
            "id": str(uuid.uuid4()), "ts": ts,
            "insight_type": "uncontested_opportunity",
            "title": f"✅ {len(no_comp_opps)} uncontested opportunities (no competitor detected)",
            "summary": (f"{len(no_comp_opps)} active opportunities show no competitor on location. "
                        f"These represent primary vendor approach opportunities — highest win probability. "
                        f"Prioritise these in your immediate sales effort."),
            "evidence": [f"{o.get('rig')}/{o.get('well')} — {o.get('product_line')}"
                         for o in no_comp_opps[:5]],
            "severity": "info",
            "upload_id": upload_id,
        })

    # ── 5. Field concentration risk ────────────────────────────────────────
    field_counts = Counter(o.get("field","") for o in opps if o.get("field"))
    if field_counts:
        top_field, top_field_count = field_counts.most_common(1)[0]
        concentration = round(top_field_count / max(len(opps), 1) * 100)
        if concentration >= 40:
            insights.append({
                "id": str(uuid.uuid4()), "ts": ts,
                "insight_type": "field_concentration",
                "title": f"📍 {concentration}% of opportunities concentrated in {top_field}",
                "summary": (f"{top_field_count} of {len(opps)} opportunities ({concentration}%) "
                            f"are in {top_field}. This represents both a market concentration "
                            f"opportunity and a diversification risk."),
                "evidence": [],
                "severity": "info",
                "fields": [top_field],
                "upload_id": upload_id,
            })

    # ── 6. Lifecycle transition signals ──────────────────────────────────────
    approaching_td = [l for l in lc if "total depth" in (l.get("next_stage","") or "").lower()
                      or "completion" in (l.get("next_stage","") or "").lower()]
    if approaching_td:
        insights.append({
            "id": str(uuid.uuid4()), "ts": ts,
            "insight_type": "lifecycle_transition",
            "title": f"🔄 {len(approaching_td)} rigs approaching completion/TD phase",
            "summary": (f"{len(approaching_td)} rigs are transitioning to completion or "
                        f"TD phase — high probability of completion, wireline, and "
                        f"well testing service needs in the near term."),
            "evidence": [f"{l.get('rig')} → {l.get('next_stage','')}" for l in approaching_td[:5]],
            "severity": "medium",
            "upload_id": upload_id,
        })

    # Save insights to DB
    _save_insights(insights)
    return insights


def _save_insights(insights: list):
    if not insights:
        return
    conn = get_db()
    for ins in insights:
        conn.execute(
            """INSERT OR REPLACE INTO strategic_insights
               (id,ts,insight_type,title,summary,evidence,severity,
                product_lines,competitors,fields,rigs,is_read,upload_id)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,0,?)""",
            (ins["id"], ins["ts"], ins["insight_type"], ins["title"],
             ins["summary"],
             json.dumps(ins.get("evidence",[])),
             ins.get("severity","info"),
             json.dumps(ins.get("product_lines",[])),
             json.dumps(ins.get("competitors",[])),
             json.dumps(ins.get("fields",[])),
             json.dumps(ins.get("rigs",[])),
             ins.get("upload_id"))
        )
    conn.commit()
    conn.close()


def get_strategic_insights(limit: int = 20, unread_only: bool = False) -> list:
    conn = get_db()
    q = "SELECT * FROM strategic_insights WHERE 1=1"
    p = []
    if unread_only:
        q += " AND is_read=0"
    q += " ORDER BY ts DESC LIMIT ?"
    p.append(limit)
    rows = conn.execute(q, p).fetchall()
    conn.close()
    result = []
    for r in rows:
        d = dict(r)
        for f in ["evidence","product_lines","competitors","fields","rigs"]:
            try: d[f] = json.loads(d.get(f,"[]") or "[]")
            except: d[f] = []
        result.append(d)
    return result


def mark_insight_read(insight_id: str):
    conn = get_db()
    conn.execute("UPDATE strategic_insights SET is_read=1 WHERE id=?", (insight_id,))
    conn.commit()
    conn.close()


def generate_daily_brief(data: dict) -> dict:
    """Generate an executive daily brief from current intelligence."""
    opps  = data.get("opportunities", [])
    comps = data.get("competitors", [])
    kpis  = data.get("kpis", {})

    today = datetime.date.today().isoformat()
    ts    = datetime.datetime.utcnow().isoformat()

    immediate = [o for o in opps if o.get("urgency") in ("immediate","5_days")]
    high_conf = [o for o in opps if o.get("confidence",0) >= 85]
    new_opps  = [o for o in opps if o.get("validation_status") == "new"]

    comp_names = list(dict.fromkeys(
        c.get("normalized","") for c in comps if c.get("normalized")
    ))[:6]

    pipeline = sum(o.get("estimated_value",0) for o in opps)
    imm_val  = sum(o.get("estimated_value",0) for o in immediate)

    summary = (
        f"As of {today}, the system has identified {len(opps)} commercial opportunities "
        f"with a total pipeline of ${pipeline:,.0f}. "
        f"{len(immediate)} require immediate or 5-day action (${imm_val:,.0f} at risk). "
        f"{len(high_conf)} are high-confidence (≥85%). "
        f"Active competitors: {', '.join(comp_names) if comp_names else 'none detected'}. "
        f"{len(new_opps)} opportunities await validation."
    )

    # Top actions
    actions = []
    for o in immediate[:5]:
        actions.append({
            "priority": "critical",
            "action":   f"Contact {o.get('suggested_contact','technical team')} for {o.get('product_line','service')} on {o.get('rig','—')}/{o.get('well','—')}",
            "deadline": "Today" if o.get("urgency") == "immediate" else "Within 5 days",
            "value":    f"${o.get('estimated_value',0):,.0f}",
        })

    brief = {
        "id":          str(uuid.uuid4()),
        "date":        today,
        "generated_at":ts,
        "summary":     summary,
        "opportunities":opps[:10],
        "competitor_moves": comp_names,
        "insights":    get_strategic_insights(limit=5),
        "actions":     actions,
        "kpis": {
            "total_opportunities":  len(opps),
            "immediate_actions":    len(immediate),
            "high_confidence":      len(high_conf),
            "pipeline_total":       pipeline,
            "immediate_value":      imm_val,
            "competitors_detected": len(comp_names),
            "pending_validation":   len(new_opps),
        },
        "generated_by": "system",
    }

    # Save
    conn = get_db()
    conn.execute(
        """INSERT OR REPLACE INTO daily_briefs
           (id,date,generated_at,summary,opportunities,competitor_moves,
            insights,actions,kpis,generated_by)
           VALUES(?,?,?,?,?,?,?,?,?,?)""",
        (brief["id"], today, ts, summary,
         json.dumps([{"id":o.get("id"),"title":o.get("title"),"rig":o.get("rig"),
                      "product_line":o.get("product_line"),"urgency":o.get("urgency"),
                      "confidence":o.get("confidence"),"estimated_value":o.get("estimated_value",0)}
                     for o in opps[:10]]),
         json.dumps(comp_names),
         json.dumps([{"title":i["title"],"severity":i["severity"]} for i in brief["insights"]]),
         json.dumps(actions),
         json.dumps(brief["kpis"]),
         "system")
    )
    conn.commit()
    conn.close()
    return brief
