"""
EIP v6.0 — Market Change Detection Engine
Detects what changed between DDR uploads.

Every time a new DDR is processed, this engine compares:
  - New vs previous snapshot
  - New vs previous competitor set
  - New vs previous rig/field activity
  - New vs previous opportunity distribution

Output: "What Changed?" feed with commercial impact assessment.
Never generates changes without evidence.
"""
from __future__ import annotations
import json, uuid, datetime
from collections import defaultdict
from core.database import get_db

CHANGE_TYPES = {
    "rig_mobilised":     ("high",   "New rig detected in market"),
    "rig_demobilised":   ("medium", "Rig no longer active"),
    "competitor_entered":("high",   "Competitor entered new field/rig"),
    "competitor_exited": ("medium", "Competitor no longer detected on rig"),
    "demand_surge":      ("high",   "Service line demand significantly increased"),
    "demand_drop":       ("medium", "Service line demand significantly decreased"),
    "new_field":         ("high",   "Activity detected in new field"),
    "activity_surge":    ("high",   "Overall activity significantly increased"),
    "activity_drop":     ("medium", "Overall activity significantly decreased"),
    "campaign_signal":   ("medium", "Multi-rig activity pattern detected"),
    "competitor_expanded":("high",  "Competitor expanded to more rigs"),
    "new_operator":      ("medium", "New operator/field region detected"),
    "window_closing":    ("high",   "Displacement window identified on rig"),
}


def detect_changes(upload_id: str, prev_upload_id: str = None) -> list:
    """
    Compare new upload to previous upload and generate change events.
    Returns list of detected change events.
    """
    conn = get_db()
    ts   = datetime.datetime.utcnow().isoformat()

    # Get snapshots
    current_snap  = conn.execute(
        "SELECT * FROM market_snapshots WHERE upload_id=? LIMIT 1", (upload_id,)
    ).fetchone()

    if not prev_upload_id:
        prev_snap = conn.execute(
            "SELECT * FROM market_snapshots WHERE upload_id!=? ORDER BY generated_at DESC LIMIT 1",
            (upload_id,)
        ).fetchone()
    else:
        prev_snap = conn.execute(
            "SELECT * FROM market_snapshots WHERE upload_id=? LIMIT 1", (prev_upload_id,)
        ).fetchone()

    if not current_snap:
        conn.close()
        return []

    curr = dict(current_snap)
    prev = dict(prev_snap) if prev_snap else None
    prev_upload_id = prev.get("upload_id","") if prev else ""

    # Get current opportunities and competitors
    curr_opps  = [dict(o) for o in conn.execute(
        "SELECT * FROM opportunities WHERE upload_id=?", (upload_id,)).fetchall()]
    curr_comps = [dict(c) for c in conn.execute(
        "SELECT * FROM competitors WHERE upload_id=?", (upload_id,)).fetchall()]

    prev_opps  = []
    prev_comps = []
    if prev_upload_id:
        prev_opps  = [dict(o) for o in conn.execute(
            "SELECT * FROM opportunities WHERE upload_id=?", (prev_upload_id,)).fetchall()]
        prev_comps = [dict(c) for c in conn.execute(
            "SELECT * FROM competitors WHERE upload_id=?", (prev_upload_id,)).fetchall()]

    conn.close()

    changes = []

    def add_change(change_type, title, summary, detail="", rig="", field="", pl="", comp="",
                   severity=None, impact="", action="", confidence=75, evidence=None):
        sev, _ = CHANGE_TYPES.get(change_type, ("info",""))
        changes.append({
            "id":                str(uuid.uuid4()),
            "detected_at":       ts,
            "upload_id":         upload_id,
            "prev_upload_id":    prev_upload_id,
            "change_type":       change_type,
            "change_category":   change_type.split("_")[0] if "_" in change_type else change_type,
            "title":             title,
            "summary":           summary,
            "detail":            detail,
            "affected_rig":      rig,
            "affected_field":    field,
            "affected_pl":       pl,
            "affected_comp":     comp,
            "severity":          severity or sev,
            "commercial_impact": impact,
            "recommended_action":action,
            "confidence":        confidence,
            "evidence":          json.dumps(evidence or []),
            "is_read":           0,
        })

    # ── 1. Rig mobilisation / demobilisation ──────────────────────────────────
    if prev:
        try:
            curr_rigs  = set(json.loads(curr.get("rig_list","[]") or "[]"))
            prev_rigs  = set(json.loads(prev.get("rig_list","[]") or "[]"))
        except:
            curr_rigs  = set()
            prev_rigs  = set()

        new_rigs   = curr_rigs  - prev_rigs
        lost_rigs  = prev_rigs  - curr_rigs

        for rig in new_rigs:
            rig_opps = [o for o in curr_opps if o.get("rig") == rig]
            field    = rig_opps[0].get("field","") if rig_opps else ""
            pls      = list(set(o.get("product_line","") for o in rig_opps))
            val      = sum(o.get("estimated_value",0) for o in rig_opps)
            add_change(
                "rig_mobilised",
                f"🆕 New rig in market: {rig}",
                f"Rig {rig} detected for the first time (field: {field or 'unknown'}). "
                f"{len(rig_opps)} service opportunities identified.",
                detail=f"Active operations: {', '.join(pls[:3])}. Estimated value: ${val:,.0f}",
                rig=rig, field=field,
                impact=f"New rig entry — ${val:,.0f} in potential contracts",
                action=f"Identify contact at {field or 'this location'} and schedule capability visit",
                confidence=90,
                evidence=[f"First detection of {rig} in this report series"]
            )

        for rig in lost_rigs:
            prev_rig_opps = [o for o in prev_opps if o.get("rig") == rig]
            field = prev_rig_opps[0].get("field","") if prev_rig_opps else ""
            add_change(
                "rig_demobilised",
                f"Rig {rig} no longer detected",
                f"Rig {rig} was active in the previous report but is absent from this one. "
                f"The rig may have completed its programme or moved location.",
                rig=rig, field=field,
                impact="Service window may be closing — verify rig status",
                action=f"Confirm with field contact whether {rig} has completed or relocated",
                confidence=65,
                evidence=[f"{rig} present in previous report, absent in current"]
            )

    # ── 2. Competitor entry / exit ────────────────────────────────────────────
    if prev_comps:
        curr_comp_rigs = defaultdict(set)
        prev_comp_rigs = defaultdict(set)
        for c in curr_comps: curr_comp_rigs[c.get("normalized","")].add(c.get("rig",""))
        for c in prev_comps: prev_comp_rigs[c.get("normalized","")].add(c.get("rig",""))

        all_comps = set(list(curr_comp_rigs.keys()) + list(prev_comp_rigs.keys()))
        for comp in all_comps:
            if not comp: continue
            curr_r  = curr_comp_rigs.get(comp, set())
            prev_r  = prev_comp_rigs.get(comp, set())
            new_r   = curr_r  - prev_r
            lost_r  = prev_r  - curr_r

            if new_r:
                val_at_risk = sum(o.get("estimated_value",0) for o in curr_opps
                                  if o.get("rig") in new_r and o.get("competitor") == comp)
                add_change(
                    "competitor_entered",
                    f"⚠ {comp} entered {len(new_r)} new rig(s)",
                    f"{comp} is now detected on {len(new_r)} rig(s) where they were not before: "
                    f"{', '.join(list(new_r)[:3])}. This represents a competitive incursion.",
                    comp=comp,
                    impact=f"${val_at_risk:,.0f} in contracts now under competitive pressure from {comp}",
                    action=f"Review EnergiPro positioning vs {comp} on affected rigs immediately",
                    confidence=85,
                    evidence=[f"{comp} detected on: {', '.join(list(new_r)[:4])}"]
                )
            if lost_r and len(curr_r) < len(prev_r):
                add_change(
                    "competitor_exited",
                    f"🟢 {comp} retreated from {len(lost_r)} rig(s)",
                    f"{comp} is no longer detected on: {', '.join(list(lost_r)[:3])}. "
                    f"This may represent a displacement opportunity.",
                    comp=comp,
                    impact=f"Displacement window opened on {len(lost_r)} rig(s)",
                    action=f"Approach drilling team on {', '.join(list(lost_r)[:2])} — window is open",
                    confidence=70,
                    evidence=[f"{comp} absent from: {', '.join(list(lost_r)[:4])}"]
                )

    # ── 3. Demand surge / drop by product line ────────────────────────────────
    if prev:
        try:
            curr_pl = json.loads(curr.get("pl_distribution","{}") or "{}")
            prev_pl = json.loads(prev.get("pl_distribution","{}") or "{}")
        except:
            curr_pl = prev_pl = {}

        for pl in set(list(curr_pl.keys()) + list(prev_pl.keys())):
            curr_n = curr_pl.get(pl, 0)
            prev_n = prev_pl.get(pl, 0)
            if prev_n > 0:
                change_pct = (curr_n - prev_n) / prev_n * 100
                if change_pct >= 40 and curr_n >= 3:
                    add_change(
                        "demand_surge",
                        f"📈 {pl} demand surged +{change_pct:.0f}%",
                        f"{pl} opportunities increased from {prev_n} to {curr_n} "
                        f"(+{change_pct:.0f}%). This indicates a market-wide demand increase.",
                        pl=pl,
                        impact=f"Equipment and personnel capacity needed immediately for {pl}",
                        action=f"Confirm {pl} equipment availability and assign BD resources",
                        confidence=80,
                        evidence=[f"{pl}: {prev_n}→{curr_n} opportunities in consecutive reports"]
                    )
                elif change_pct <= -40 and prev_n >= 3:
                    add_change(
                        "demand_drop",
                        f"📉 {pl} demand dropped {abs(change_pct):.0f}%",
                        f"{pl} opportunities decreased from {prev_n} to {curr_n}. "
                        f"This may indicate campaign completion or seasonal slowdown.",
                        pl=pl,
                        impact=f"Reduce {pl} resource allocation — demand has softened",
                        action=f"Review {pl} pipeline and reallocate BD effort to growing product lines",
                        confidence=70,
                        evidence=[f"{pl}: {prev_n}→{curr_n} opportunities"]
                    )

        # ── 4. Overall activity surge / drop ─────────────────────────────────
        curr_int = curr.get("activity_intensity", 0)
        prev_int = prev.get("activity_intensity", 0)
        if prev_int > 0:
            int_change = (curr_int - prev_int) / prev_int * 100
            if int_change >= 30:
                add_change(
                    "activity_surge",
                    f"🔥 Market activity surged +{int_change:.0f}%",
                    f"Overall market activity intensity increased from {prev_int} to {curr_int}/100. "
                    f"More rigs, more immediate opportunities, and higher competitor density detected.",
                    impact="Peak period — BD team must be fully active",
                    action="All BD resources to active mode — review full opportunity list immediately",
                    confidence=85,
                    evidence=[f"Activity intensity: {prev_int}→{curr_int}"]
                )
            elif int_change <= -30:
                add_change(
                    "activity_drop",
                    f"Market activity declined {abs(int_change):.0f}%",
                    f"Overall market activity decreased from {prev_int} to {curr_int}/100. "
                    f"This may indicate a seasonal slowdown or end of a drilling campaign.",
                    impact="Use the quieter period to prepare proposals and build relationships",
                    action="Schedule customer visits and technical presentations during slower period",
                    confidence=70,
                    evidence=[f"Activity intensity: {prev_int}→{curr_int}"]
                )

    # ── 5. New field entry ────────────────────────────────────────────────────
    if prev:
        try:
            curr_fields = set(json.loads(curr.get("field_distribution","{}") or "{}").keys())
            prev_fields = set(json.loads(prev.get("field_distribution","{}") or "{}").keys())
        except:
            curr_fields = prev_fields = set()

        new_fields = curr_fields - prev_fields - {"","Unknown"}
        for field in new_fields:
            field_opps = [o for o in curr_opps if o.get("field") == field]
            val = sum(o.get("estimated_value",0) for o in field_opps)
            add_change(
                "new_field",
                f"🗺 New field active: {field}",
                f"Activity detected in {field} for the first time in this reporting period. "
                f"{len(field_opps)} opportunities identified with ${val:,.0f} potential.",
                field=field,
                impact=f"New geographic opportunity — ${val:,.0f} at {field}",
                action=f"Identify customer contact at {field} and assess entry strategy",
                confidence=80,
                evidence=[f"First {field} detection in current vs previous report"]
            )

    # Persist changes
    if changes:
        conn = get_db()
        for ch in changes:
            conn.execute(
                """INSERT OR REPLACE INTO change_events
                   (id,detected_at,upload_id,prev_upload_id,change_type,change_category,
                    title,summary,detail,affected_rig,affected_field,affected_pl,affected_comp,
                    severity,commercial_impact,recommended_action,confidence,evidence,is_read)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (ch["id"],ch["detected_at"],ch["upload_id"],ch["prev_upload_id"],
                 ch["change_type"],ch["change_category"],ch["title"],ch["summary"],
                 ch["detail"],ch["affected_rig"],ch["affected_field"],
                 ch["affected_pl"],ch["affected_comp"],ch["severity"],
                 ch["commercial_impact"],ch["recommended_action"],
                 ch["confidence"],ch["evidence"],ch["is_read"])
            )
        conn.commit()
        conn.close()

    return changes


def get_change_feed(upload_id: str=None, severity: str=None, limit: int=30, unread_only: bool=False) -> list:
    conn = get_db()
    q = "SELECT * FROM change_events WHERE 1=1"
    p = []
    if upload_id:   q += " AND upload_id=?";  p.append(upload_id)
    if severity:    q += " AND severity=?";   p.append(severity)
    if unread_only: q += " AND is_read=0"
    q += " ORDER BY detected_at DESC LIMIT ?"; p.append(limit)
    rows = conn.execute(q, p).fetchall()
    conn.close()
    result = []
    for r in rows:
        d = dict(r)
        try: d["evidence"] = json.loads(d.get("evidence","[]") or "[]")
        except: d["evidence"] = []
        result.append(d)
    return result


def mark_change_read(change_id: str):
    conn = get_db()
    conn.execute("UPDATE change_events SET is_read=1 WHERE id=?", (change_id,))
    conn.commit(); conn.close()
