"""
EIP v5.0 — AI Learning Engine
Records human corrections and builds accuracy trend data.
Every validation action, correction, or conversion is a signal.
"""
import uuid, datetime, json
from core.database import get_db


def init_learning_tables():
    """Create learning tables if not exist."""
    conn = get_db()
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS learning_events (
        id              TEXT PRIMARY KEY,
        ts              TEXT NOT NULL,
        event_type      TEXT NOT NULL,
        opportunity_id  TEXT,
        user_id         TEXT,
        user_email      TEXT,
        original_value  TEXT,
        corrected_value TEXT,
        field_name      TEXT,
        context         TEXT,
        product_line    TEXT,
        rig             TEXT,
        field           TEXT,
        ai_confidence   INTEGER,
        was_correct     INTEGER
    );
    CREATE TABLE IF NOT EXISTS customer_profiles (
        id              TEXT PRIMARY KEY,
        name            TEXT NOT NULL,
        type            TEXT DEFAULT 'operator',
        region          TEXT DEFAULT '',
        fields          TEXT DEFAULT '[]',
        active_rigs     TEXT DEFAULT '[]',
        service_demand  TEXT DEFAULT '[]',
        opportunity_count INTEGER DEFAULT 0,
        last_seen       TEXT,
        trend           TEXT DEFAULT 'stable',
        notes           TEXT DEFAULT '',
        updated_at      TEXT
    );
    CREATE TABLE IF NOT EXISTS strategic_insights (
        id              TEXT PRIMARY KEY,
        ts              TEXT NOT NULL,
        insight_type    TEXT NOT NULL,
        title           TEXT NOT NULL,
        summary         TEXT NOT NULL,
        evidence        TEXT DEFAULT '[]',
        severity        TEXT DEFAULT 'info',
        product_lines   TEXT DEFAULT '[]',
        competitors     TEXT DEFAULT '[]',
        fields          TEXT DEFAULT '[]',
        rigs            TEXT DEFAULT '[]',
        is_read         INTEGER DEFAULT 0,
        upload_id       TEXT
    );
    CREATE TABLE IF NOT EXISTS daily_briefs (
        id              TEXT PRIMARY KEY,
        date            TEXT NOT NULL,
        generated_at    TEXT NOT NULL,
        summary         TEXT NOT NULL,
        opportunities   TEXT DEFAULT '[]',
        competitor_moves TEXT DEFAULT '[]',
        insights        TEXT DEFAULT '[]',
        actions         TEXT DEFAULT '[]',
        kpis            TEXT DEFAULT '{}',
        generated_by    TEXT DEFAULT 'system'
    );
    CREATE INDEX IF NOT EXISTS idx_learning_ts ON learning_events(ts);
    CREATE INDEX IF NOT EXISTS idx_learning_pl ON learning_events(product_line);
    CREATE INDEX IF NOT EXISTS idx_customer_name ON customer_profiles(name);
    CREATE INDEX IF NOT EXISTS idx_insights_ts ON strategic_insights(ts);
    CREATE INDEX IF NOT EXISTS idx_briefs_date ON daily_briefs(date);
    """)
    conn.commit()
    conn.close()


def record_learning_event(
    event_type: str,
    opportunity_id: str = None,
    user_id: str = None,
    user_email: str = None,
    original_value: str = None,
    corrected_value: str = None,
    field_name: str = None,
    context: dict = None,
    was_correct: bool = None,
):
    """Record a human correction or validation event for AI learning."""
    ctx = context or {}
    conn = get_db()
    conn.execute(
        """INSERT INTO learning_events
           (id,ts,event_type,opportunity_id,user_id,user_email,
            original_value,corrected_value,field_name,context,
            product_line,rig,field,ai_confidence,was_correct)
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (str(uuid.uuid4()),
         datetime.datetime.utcnow().isoformat(),
         event_type,
         opportunity_id,
         user_id,
         user_email,
         str(original_value) if original_value is not None else None,
         str(corrected_value) if corrected_value is not None else None,
         field_name,
         json.dumps(ctx),
         ctx.get("product_line"),
         ctx.get("rig"),
         ctx.get("field"),
         ctx.get("ai_confidence"),
         1 if was_correct else 0 if was_correct is False else None)
    )
    conn.commit()
    conn.close()


def get_learning_stats() -> dict:
    """Return accuracy trends and learning statistics."""
    conn = get_db()

    total   = conn.execute("SELECT COUNT(*) FROM learning_events").fetchone()[0]
    by_type = {}
    for row in conn.execute(
        "SELECT event_type, COUNT(*) n FROM learning_events GROUP BY event_type ORDER BY n DESC"
    ).fetchall():
        by_type[row["event_type"]] = row["n"]

    # Accuracy by product line
    pl_acc = []
    for row in conn.execute("""
        SELECT product_line, COUNT(*) total,
               SUM(CASE WHEN was_correct=1 THEN 1 ELSE 0 END) correct,
               AVG(ai_confidence) avg_conf
        FROM learning_events
        WHERE product_line IS NOT NULL AND was_correct IS NOT NULL
        GROUP BY product_line ORDER BY total DESC
    """).fetchall():
        total_pl = row["total"] or 0
        correct  = row["correct"] or 0
        accuracy = round(correct / max(total_pl, 1) * 100, 1)
        pl_acc.append({
            "product_line": row["product_line"],
            "total":        total_pl,
            "correct":      correct,
            "accuracy_pct": accuracy,
            "avg_ai_conf":  round(row["avg_conf"] or 0, 1),
        })

    # Weekly trend (last 8 weeks)
    weekly = []
    for row in conn.execute("""
        SELECT strftime('%Y-W%W', ts) week,
               COUNT(*) events,
               SUM(CASE WHEN was_correct=1 THEN 1 ELSE 0 END) correct
        FROM learning_events
        WHERE ts >= datetime('now','-56 days')
        GROUP BY week ORDER BY week
    """).fetchall():
        weekly.append({
            "week":    row["week"],
            "events":  row["events"],
            "correct": row["correct"] or 0,
        })

    # Recent corrections
    recent = []
    for row in conn.execute(
        "SELECT * FROM learning_events ORDER BY ts DESC LIMIT 20"
    ).fetchall():
        recent.append(dict(row))

    conn.close()
    return {
        "total_events":    total,
        "by_event_type":   by_type,
        "by_product_line": pl_acc,
        "weekly_trend":    weekly,
        "recent_events":   recent,
    }


def upsert_customer_profile(customer_name: str, opp: dict):
    """Create or update a customer profile from an opportunity."""
    if not customer_name:
        return
    conn = get_db()
    existing = conn.execute(
        "SELECT * FROM customer_profiles WHERE name=?", (customer_name,)
    ).fetchone()

    now = datetime.datetime.utcnow().isoformat()
    field = opp.get("field","")
    rig   = opp.get("rig","")
    pl    = opp.get("product_line","")

    if existing:
        e = dict(existing)
        fields     = set(json.loads(e.get("fields","[]") or "[]"))
        rigs       = set(json.loads(e.get("active_rigs","[]") or "[]"))
        svc_demand = set(json.loads(e.get("service_demand","[]") or "[]"))
        if field: fields.add(field)
        if rig:   rigs.add(rig)
        if pl:    svc_demand.add(pl)
        conn.execute(
            """UPDATE customer_profiles
               SET fields=?,active_rigs=?,service_demand=?,
                   opportunity_count=opportunity_count+1,last_seen=?,updated_at=?
               WHERE name=?""",
            (json.dumps(list(fields)), json.dumps(list(rigs)),
             json.dumps(list(svc_demand)), now, now, customer_name)
        )
    else:
        conn.execute(
            """INSERT INTO customer_profiles
               (id,name,type,region,fields,active_rigs,service_demand,
                opportunity_count,last_seen,trend,notes,updated_at)
               VALUES(?,?,?,?,?,?,?,1,?,?,?,?)""",
            (str(uuid.uuid4()), customer_name, "operator", "",
             json.dumps([field] if field else []),
             json.dumps([rig] if rig else []),
             json.dumps([pl] if pl else []),
             now, "stable", "", now)
        )
    conn.commit()
    conn.close()


def get_customer_profiles(limit: int = 50) -> list:
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM customer_profiles ORDER BY opportunity_count DESC LIMIT ?",
        (limit,)
    ).fetchall()
    conn.close()
    result = []
    for r in rows:
        d = dict(r)
        for f in ["fields","active_rigs","service_demand"]:
            try: d[f] = json.loads(d.get(f,"[]") or "[]")
            except: d[f] = []
        result.append(d)
    return result
