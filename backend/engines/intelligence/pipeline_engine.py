"""
EIP v5.1 — Revenue Pipeline Engine
Manages proposal lifecycle and weighted revenue pipeline.

Lifecycle stages:
  Identified → Qualifying → Playbook → Proposal → Negotiation → Award → Lost

Extends the existing `leads` table concept with revenue-pipeline structure.
"""
import uuid, datetime, json
from core.database import get_db

PIPELINE_STAGES = [
    "Identified",   # Detected from DDR
    "Qualifying",   # Being assessed
    "Playbook",     # Win strategy prepared
    "Proposal",     # Proposal submitted
    "Negotiation",  # Commercial negotiation
    "Award",        # Contract won
    "Lost",         # Contract lost
]

STAGE_WIN_PROB_OVERRIDE = {
    # Override win probability at each stage (replaces AI estimate)
    "Identified":  None,    # Use AI estimate
    "Qualifying":  None,    # Use AI estimate
    "Playbook":    0.40,
    "Proposal":    0.55,
    "Negotiation": 0.75,
    "Award":       1.00,
    "Lost":        0.00,
}


def init_pipeline_tables():
    """Create revenue pipeline tables."""
    conn = get_db()
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS pipeline_items (
        id                  TEXT PRIMARY KEY,
        opportunity_id      TEXT,
        title               TEXT NOT NULL,
        product_line        TEXT DEFAULT '',
        customer            TEXT DEFAULT '',
        operator            TEXT DEFAULT '',
        rig                 TEXT DEFAULT '',
        well                TEXT DEFAULT '',
        field               TEXT DEFAULT '',
        country             TEXT DEFAULT 'Saudi Arabia',
        stage               TEXT DEFAULT 'Identified',
        revenue_expected    REAL DEFAULT 0,
        revenue_conservative REAL DEFAULT 0,
        revenue_optimistic  REAL DEFAULT 0,
        gross_margin_pct    REAL DEFAULT 0.28,
        win_probability     REAL DEFAULT 0.25,
        weighted_value      REAL DEFAULT 0,
        expected_award_date TEXT DEFAULT '',
        expected_award_month TEXT DEFAULT '',
        competitor          TEXT DEFAULT '',
        owner               TEXT DEFAULT 'Unassigned',
        priority            TEXT DEFAULT 'medium',
        qualification_score INTEGER DEFAULT 0,
        commercial_priority INTEGER DEFAULT 0,
        notes               TEXT DEFAULT '',
        lessons_learned     TEXT DEFAULT '',
        win_reason          TEXT DEFAULT '',
        loss_reason         TEXT DEFAULT '',
        stage_history       TEXT DEFAULT '[]',
        created_at          TEXT,
        updated_at          TEXT
    );
    CREATE TABLE IF NOT EXISTS engagement_plans (
        id              TEXT PRIMARY KEY,
        pipeline_item_id TEXT,
        opportunity_id  TEXT,
        step_number     INTEGER,
        action          TEXT NOT NULL,
        owner           TEXT DEFAULT 'Unassigned',
        target_date     TEXT,
        status          TEXT DEFAULT 'pending',
        priority        TEXT DEFAULT 'medium',
        notes           TEXT DEFAULT '',
        completed_at    TEXT,
        created_at      TEXT
    );
    CREATE TABLE IF NOT EXISTS lessons_learned (
        id              TEXT PRIMARY KEY,
        opportunity_id  TEXT,
        pipeline_item_id TEXT,
        type            TEXT NOT NULL,
        title           TEXT NOT NULL,
        description     TEXT,
        outcome         TEXT,
        product_line    TEXT,
        customer        TEXT,
        competitor      TEXT,
        recorded_by     TEXT,
        created_at      TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_pipeline_stage ON pipeline_items(stage);
    CREATE INDEX IF NOT EXISTS idx_pipeline_pl ON pipeline_items(product_line);
    CREATE INDEX IF NOT EXISTS idx_pipeline_opp ON pipeline_items(opportunity_id);
    CREATE INDEX IF NOT EXISTS idx_engplan_item ON engagement_plans(pipeline_item_id);
    CREATE INDEX IF NOT EXISTS idx_lessons_type ON lessons_learned(type);
    """)
    conn.commit()
    conn.close()


def create_pipeline_item(data: dict, user_email: str = "") -> dict:
    """Create a revenue pipeline item from opportunity or manual entry."""
    conn = get_db()
    pid  = str(uuid.uuid4())
    ts   = datetime.datetime.utcnow().isoformat()

    # Calculate weighted value
    exp  = data.get("revenue_expected", 0) or 0
    wp   = data.get("win_probability", 0.25) or 0.25
    if wp > 1: wp = wp / 100
    weighted = round(exp * wp)

    stage    = data.get("stage", "Identified")
    stage_hist = [{"stage": stage, "ts": ts, "by": user_email}]

    conn.execute(
        """INSERT INTO pipeline_items
           (id,opportunity_id,title,product_line,customer,operator,
            rig,well,field,country,stage,revenue_expected,revenue_conservative,
            revenue_optimistic,gross_margin_pct,win_probability,weighted_value,
            expected_award_date,expected_award_month,competitor,owner,priority,
            qualification_score,commercial_priority,notes,stage_history,created_at,updated_at)
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (pid, data.get("opportunity_id",""), data.get("title",""),
         data.get("product_line",""), data.get("customer",""), data.get("operator",""),
         data.get("rig",""), data.get("well",""), data.get("field",""),
         data.get("country","Saudi Arabia"), stage,
         exp, data.get("revenue_conservative",exp*0.6), data.get("revenue_optimistic",exp*1.4),
         data.get("gross_margin_pct",0.28), wp, weighted,
         data.get("expected_award_date",""), data.get("expected_award_month",""),
         data.get("competitor",""), data.get("owner","Unassigned"), data.get("priority","medium"),
         data.get("qualification_score",0), data.get("commercial_priority",0),
         data.get("notes",""), json.dumps(stage_hist), ts, ts)
    )
    conn.commit()
    row = conn.execute("SELECT * FROM pipeline_items WHERE id=?", (pid,)).fetchone()
    conn.close()
    return _enrich(dict(row)) if row else {}


def advance_pipeline_stage(item_id: str, new_stage: str, notes: str="", user_email: str="") -> dict:
    """Move pipeline item to next stage."""
    if new_stage not in PIPELINE_STAGES:
        raise ValueError(f"Invalid stage. Must be one of: {', '.join(PIPELINE_STAGES)}")

    conn = get_db()
    item = conn.execute("SELECT * FROM pipeline_items WHERE id=?", (item_id,)).fetchone()
    if not item:
        conn.close()
        return {}
    item = dict(item)
    ts   = datetime.datetime.utcnow().isoformat()

    try:
        hist = json.loads(item.get("stage_history","[]") or "[]")
    except:
        hist = []
    hist.append({"stage": new_stage, "ts": ts, "by": user_email, "notes": notes})

    # Override win probability at certain stages
    wp_override = STAGE_WIN_PROB_OVERRIDE.get(new_stage)
    new_wp      = wp_override if wp_override is not None else item.get("win_probability",0.25)
    exp         = item.get("revenue_expected",0) or 0
    new_weighted = round(exp * new_wp)

    conn.execute(
        """UPDATE pipeline_items
           SET stage=?,stage_history=?,win_probability=?,weighted_value=?,updated_at=?,notes=?
           WHERE id=?""",
        (new_stage, json.dumps(hist), new_wp, new_weighted, ts,
         (item.get("notes","") + f"\n[{ts[:10]}] Stage → {new_stage}: {notes}").strip(),
         item_id)
    )
    conn.commit()
    row = conn.execute("SELECT * FROM pipeline_items WHERE id=?", (item_id,)).fetchone()
    conn.close()
    return _enrich(dict(row)) if row else {}


def list_pipeline_items(stage: str=None, product_line: str=None,
                         owner: str=None, limit: int=100) -> list:
    conn = get_db()
    q = "SELECT * FROM pipeline_items WHERE 1=1"
    p = []
    if stage:        q += " AND stage=?";        p.append(stage)
    if product_line: q += " AND product_line=?"; p.append(product_line)
    if owner:        q += " AND owner=?";        p.append(owner)
    q += " ORDER BY commercial_priority DESC, created_at DESC LIMIT ?"
    p.append(limit)
    rows = conn.execute(q, p).fetchall()
    conn.close()
    return [_enrich(dict(r)) for r in rows]


def get_pipeline_summary() -> dict:
    """Aggregate pipeline metrics for the Revenue Pipeline Dashboard."""
    conn = get_db()
    rows = conn.execute("SELECT * FROM pipeline_items").fetchall()
    conn.close()

    if not rows:
        return {"total":0,"by_stage":{},"total_expected":0,"total_weighted":0,"by_pl":[],"by_field":[]}

    items = [dict(r) for r in rows]

    total_expected = sum(i.get("revenue_expected",0) for i in items)
    total_weighted = sum(i.get("weighted_value",0)   for i in items)
    total_margin   = sum(i.get("revenue_expected",0)*i.get("gross_margin_pct",0.28) for i in items)

    by_stage = {}
    for stage in PIPELINE_STAGES:
        stage_items = [i for i in items if i.get("stage")==stage]
        by_stage[stage] = {
            "count":    len(stage_items),
            "expected": sum(i.get("revenue_expected",0) for i in stage_items),
            "weighted": sum(i.get("weighted_value",0)   for i in stage_items),
        }

    from collections import defaultdict
    by_pl    = defaultdict(lambda:{"expected":0,"weighted":0,"count":0})
    by_field = defaultdict(lambda:{"expected":0,"weighted":0,"count":0})
    for i in items:
        pl = i.get("product_line","Other")
        by_pl[pl]["expected"] += i.get("revenue_expected",0)
        by_pl[pl]["weighted"] += i.get("weighted_value",0)
        by_pl[pl]["count"]    += 1
        f  = i.get("field","Unknown") or "Unknown"
        by_field[f]["expected"] += i.get("revenue_expected",0)
        by_field[f]["weighted"] += i.get("weighted_value",0)
        by_field[f]["count"]    += 1

    by_pl_list    = [{"product_line":k,**v} for k,v in by_pl.items()]
    by_field_list = [{"field":k,**v}        for k,v in by_field.items()]

    return {
        "total":           len(items),
        "total_expected":  round(total_expected),
        "total_weighted":  round(total_weighted),
        "total_margin":    round(total_margin),
        "avg_margin_pct":  round(total_margin/max(total_expected,1)*100,1),
        "by_stage":        by_stage,
        "stages":          PIPELINE_STAGES,
        "by_product_line": sorted(by_pl_list,    key=lambda x:-x["weighted"])[:10],
        "by_field":        sorted(by_field_list, key=lambda x:-x["weighted"])[:10],
    }


def record_lesson_learned(data: dict, user_email: str="") -> dict:
    conn = get_db()
    lid  = str(uuid.uuid4())
    ts   = datetime.datetime.utcnow().isoformat()
    conn.execute(
        """INSERT INTO lessons_learned
           (id,opportunity_id,pipeline_item_id,type,title,description,
            outcome,product_line,customer,competitor,recorded_by,created_at)
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
        (lid, data.get("opportunity_id",""), data.get("pipeline_item_id",""),
         data.get("type","general"), data.get("title",""),
         data.get("description",""), data.get("outcome",""),
         data.get("product_line",""), data.get("customer",""),
         data.get("competitor",""), user_email, ts)
    )
    conn.commit(); conn.close()
    return {"id": lid, "created_at": ts}


def get_lessons_learned(type_: str=None, product_line: str=None, limit: int=50) -> list:
    conn = get_db()
    q = "SELECT * FROM lessons_learned WHERE 1=1"
    p = []
    if type_:        q += " AND type=?";         p.append(type_)
    if product_line: q += " AND product_line=?"; p.append(product_line)
    q += " ORDER BY created_at DESC LIMIT ?"; p.append(limit)
    rows = conn.execute(q, p).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def _enrich(item: dict) -> dict:
    try:
        item["stage_history"] = json.loads(item.get("stage_history","[]") or "[]")
    except:
        item["stage_history"] = []
    return item
