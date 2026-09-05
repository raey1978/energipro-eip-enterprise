"""
EIP v6.0 — Campaign Detection Engine
Identifies and groups multi-rig/multi-well drilling campaigns.

A "campaign" is a structured multi-well programme where:
  - Multiple rigs are active in the same field simultaneously, or
  - The same field shows sustained activity across consecutive reports, or
  - A high-value operator is running coordinated operations

Campaigns create large revenue opportunities and BD strategic importance.
"""
from __future__ import annotations
import json, uuid, datetime
from collections import defaultdict, Counter
from core.database import get_db


CAMPAIGN_TYPES = {
    "drilling":    {"min_rigs": 2, "min_opps": 4},
    "completion":  {"min_rigs": 1, "min_opps": 3},
    "testing":     {"min_rigs": 1, "min_opps": 2},
    "workover":    {"min_rigs": 1, "min_opps": 2},
}

# Product lines that signal specific campaign types
CAMPAIGN_SIGNALS = {
    "completion":  ["Completion", "Cementing"],
    "testing":     ["Well Testing", "Wireline / Logging"],
    "workover":    ["Fishing / Intervention", "Wireline / Logging"],
}


def detect_campaigns(upload_id: str) -> list:
    """
    Detect drilling campaigns from current + historical opportunity data.
    Runs after each upload to identify new or continuing campaigns.
    """
    conn = get_db()
    ts   = datetime.datetime.utcnow().isoformat()

    # Get ALL historical opportunities (cross-DDR)
    all_opps  = [dict(o) for o in conn.execute("SELECT * FROM opportunities").fetchall()]
    all_comps = [dict(c) for c in conn.execute("SELECT * FROM competitors").fetchall()]
    conn.close()

    if not all_opps:
        return []

    detected = []

    # ── Group by field — detect field campaigns ────────────────────────────────
    field_opps = defaultdict(list)
    for opp in all_opps:
        field = opp.get("field","")
        if field and field != "Unknown":
            field_opps[field].append(opp)

    for field, opps in field_opps.items():
        if len(opps) < 3:
            continue

        rigs  = list(set(o.get("rig","")  for o in opps if o.get("rig")))
        wells = list(set(o.get("well","") for o in opps if o.get("well")))
        pls   = Counter(o.get("product_line","") for o in opps)
        uploads_seen = set(o.get("upload_id","") for o in opps)
        val   = sum(o.get("estimated_value",0) for o in opps)
        imm   = sum(1 for o in opps if o.get("urgency") in ("immediate","5_days"))

        # Must meet minimum campaign criteria
        if len(rigs) < 2 and len(uploads_seen) < 2:
            continue

        # Determine campaign type
        top_pls = [pl for pl, _ in pls.most_common(3)]
        camp_type = "drilling"
        for ctype, signals in CAMPAIGN_SIGNALS.items():
            if any(s in top_pls for s in signals):
                camp_type = ctype
                break

        # Determine stage
        if imm >= len(opps) * 0.5:
            stage = "mid"
        elif any(o.get("stage","") in ("TD","Total Depth") for o in opps):
            stage = "wrapping_up"
        elif len(uploads_seen) == 1:
            stage = "early"
        else:
            stage = "mid"

        # Estimated duration based on PL and rig count
        base_weeks = {"drilling":8,"completion":4,"testing":2,"workover":3}
        est_duration = base_weeks.get(camp_type, 6) * max(1, len(rigs) // 2)

        confidence = min(90, 40 + len(rigs)*10 + len(uploads_seen)*8)

        expected_services = list(pls.keys())[:5]

        detected.append({
            "id":                     str(uuid.uuid4()),
            "name":                   f"{field} {camp_type.title()} Campaign",
            "campaign_type":          camp_type,
            "status":                 "active",
            "detected_at":            ts,
            "fields":                 [field],
            "rigs":                   rigs[:10],
            "wells":                  wells[:15],
            "operators":              [],
            "estimated_duration_weeks":est_duration,
            "estimated_market_value": val,
            "expected_services":      expected_services,
            "campaign_stage":         stage,
            "confidence":             confidence,
            "evidence_upload_ids":    list(uploads_seen)[:5],
            "notes":                  (
                f"{len(rigs)} rigs across {len(wells)} wells in {field}. "
                f"Top services: {', '.join(expected_services[:3])}. "
                f"Seen across {len(uploads_seen)} report(s). "
                f"Immediate opportunities: {imm}."
            ),
            "updated_at": ts,
        })

    # Persist campaigns
    if detected:
        conn = get_db()
        conn.execute("DELETE FROM campaigns")  # Regenerate fresh each time
        for camp in detected:
            conn.execute(
                """INSERT OR REPLACE INTO campaigns
                   (id,name,campaign_type,status,detected_at,fields,rigs,wells,operators,
                    estimated_duration_weeks,estimated_market_value,expected_services,
                    campaign_stage,confidence,evidence_upload_ids,notes,updated_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (camp["id"], camp["name"], camp["campaign_type"], camp["status"],
                 camp["detected_at"],
                 json.dumps(camp["fields"]),
                 json.dumps(camp["rigs"]),
                 json.dumps(camp["wells"]),
                 json.dumps(camp["operators"]),
                 camp["estimated_duration_weeks"],
                 camp["estimated_market_value"],
                 json.dumps(camp["expected_services"]),
                 camp["campaign_stage"],
                 camp["confidence"],
                 json.dumps(camp["evidence_upload_ids"]),
                 camp["notes"],
                 camp["updated_at"])
            )
        conn.commit()
        conn.close()

    return detected


def get_campaigns(campaign_type: str = None) -> list:
    conn = get_db()
    q = "SELECT * FROM campaigns WHERE 1=1"
    p = []
    if campaign_type: q += " AND campaign_type=?"; p.append(campaign_type)
    q += " ORDER BY estimated_market_value DESC"
    rows = conn.execute(q, p).fetchall()
    conn.close()
    result = []
    for r in rows:
        d = dict(r)
        for f in ["fields","rigs","wells","operators","expected_services","evidence_upload_ids"]:
            try: d[f] = json.loads(d.get(f,"[]") or "[]")
            except: d[f] = []
        result.append(d)
    return result
