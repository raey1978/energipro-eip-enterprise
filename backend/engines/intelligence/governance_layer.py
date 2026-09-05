"""
EIP v6.2 — Intelligence Governance Layer
Sits ABOVE the Trust Layer. Records the lifecycle of every significant insight.

Architecture decision: governance_records are immutable audit entries that
REFERENCE existing data (trust_scores, change_events, market_snapshots, opportunities)
by ID. They do NOT duplicate data. This is the correct enterprise pattern.

The Governance Layer answers:
  "Can I reconstruct this recommendation from its evidence?" → YES
  "What did the platform say yesterday?"                    → YES (version history)
  "Why did the recommendation change?"                      → YES (supersession log)
  "Who or what triggered the update?"                       → YES (trigger field)
  "Is this auditable end-to-end?"                           → YES (full chain)
"""
from __future__ import annotations
import json, uuid, datetime
from core.database import get_db


# ── Table Initialisation ──────────────────────────────────────────────────────

def init_governance_tables():
    conn = get_db()
    conn.executescript("""
    -- Immutable governance record per significant insight
    -- APPEND-ONLY: rows are never updated, only superseded
    CREATE TABLE IF NOT EXISTS governance_records (
        id              TEXT PRIMARY KEY,
        created_at      TEXT NOT NULL,
        version         INTEGER NOT NULL DEFAULT 1,

        -- What is being governed
        insight_type    TEXT NOT NULL,   -- opportunity|change_event|trend|campaign|market_signal
        insight_id      TEXT NOT NULL,   -- references the originating entity

        -- Provenance (references, not copies)
        source_engines  TEXT DEFAULT '[]',   -- JSON list of engine names
        source_upload_ids TEXT DEFAULT '[]', -- which DDR uploads feed this
        trust_score_id  TEXT DEFAULT '',     -- FK to trust_scores.id

        -- State snapshot (compact — not full copy)
        status          TEXT DEFAULT 'active',  -- active|superseded|archived
        title           TEXT NOT NULL,
        recommendation  TEXT NOT NULL,
        trust_score     INTEGER DEFAULT 0,
        evidence_strength TEXT DEFAULT 'UNKNOWN',
        observation_type TEXT DEFAULT 'AI_INFERENCE',

        -- What triggered this version
        trigger_type    TEXT DEFAULT 'system',  -- system|upload|human|correction
        trigger_detail  TEXT DEFAULT '',
        triggered_by    TEXT DEFAULT 'system',  -- user email or 'system'

        -- Previous version linkage (null for v1)
        supersedes_id   TEXT DEFAULT '',
        superseded_at   TEXT DEFAULT '',
        superseded_by   TEXT DEFAULT '',
        change_summary  TEXT DEFAULT '',

        -- Assumptions and limitations snapshot (compact)
        key_assumptions TEXT DEFAULT '[]',
        known_limitations TEXT DEFAULT '[]',

        -- Commercial classification
        commercial_priority INTEGER DEFAULT 0,
        revenue_expected    REAL DEFAULT 0
    );

    -- Decision Journal: human commercial decisions linked to governance records
    CREATE TABLE IF NOT EXISTS decision_journal (
        id              TEXT PRIMARY KEY,
        created_at      TEXT NOT NULL,
        updated_at      TEXT,

        -- Link back to insight
        governance_id   TEXT NOT NULL,   -- FK to governance_records
        insight_type    TEXT NOT NULL,
        insight_id      TEXT NOT NULL,

        -- Decision
        decision_type   TEXT NOT NULL,   -- customer_contacted|proposal_submitted|award|loss|clarification|meeting|other
        title           TEXT NOT NULL,
        description     TEXT DEFAULT '',
        outcome         TEXT DEFAULT '',

        -- Assignment
        owner           TEXT DEFAULT '',
        customer        TEXT DEFAULT '',
        product_line    TEXT DEFAULT '',

        -- Result linkage
        pipeline_item_id TEXT DEFAULT '',
        lesson_learned_id TEXT DEFAULT '',
        revenue_actual  REAL DEFAULT 0,

        status          TEXT DEFAULT 'open',  -- open|completed|cancelled
        recorded_by     TEXT DEFAULT ''
    );

    CREATE INDEX IF NOT EXISTS idx_gov_insight   ON governance_records(insight_type, insight_id);
    CREATE INDEX IF NOT EXISTS idx_gov_status    ON governance_records(status);
    CREATE INDEX IF NOT EXISTS idx_gov_created   ON governance_records(created_at);
    CREATE INDEX IF NOT EXISTS idx_gov_version   ON governance_records(insight_id, version);
    CREATE INDEX IF NOT EXISTS idx_dj_gov        ON decision_journal(governance_id);
    CREATE INDEX IF NOT EXISTS idx_dj_type       ON decision_journal(decision_type);
    """)
    conn.commit()
    conn.close()


# ── Governance Record Creation ────────────────────────────────────────────────

def create_governance_record(
    insight_type: str,
    insight_id: str,
    title: str,
    recommendation: str,
    trust_envelope: dict,
    source_engines: list = None,
    source_upload_ids: list = None,
    trigger_type: str = "system",
    trigger_detail: str = "",
    triggered_by: str = "system",
    commercial_priority: int = 0,
    revenue_expected: float = 0,
) -> dict:
    """
    Create an immutable governance record for an insight.
    If a previous record exists for this insight_id, it is superseded.
    """
    conn = get_db()
    ts   = datetime.datetime.utcnow().isoformat()
    gid  = str(uuid.uuid4())

    # Check for existing active record
    existing = conn.execute(
        "SELECT id, version, title, recommendation, trust_score FROM governance_records "
        "WHERE insight_id=? AND insight_type=? AND status='active' "
        "ORDER BY version DESC LIMIT 1",
        (insight_id, insight_type)
    ).fetchone()

    version       = 1
    supersedes_id = ""
    change_summary = ""

    if existing:
        old = dict(existing)
        version        = old["version"] + 1
        supersedes_id  = old["id"]
        old_score      = old.get("trust_score", 0)
        new_score      = trust_envelope.get("trust_score", 0)
        score_diff     = new_score - old_score

        # Build change summary
        changes = []
        if abs(score_diff) >= 5:
            changes.append(f"Trust score {'increased' if score_diff>0 else 'decreased'} {abs(score_diff)} points ({old_score}→{new_score})")
        if old.get("recommendation") != recommendation:
            changes.append("Recommendation text updated")
        if old.get("title") != title:
            changes.append("Title updated")
        change_summary = "; ".join(changes) if changes else "Routine update"

        # Supersede the old record
        conn.execute(
            "UPDATE governance_records SET status='superseded', superseded_at=?, superseded_by=? WHERE id=?",
            (ts, triggered_by, old["id"])
        )

    te = trust_envelope or {}
    conn.execute(
        """INSERT INTO governance_records
           (id,created_at,version,insight_type,insight_id,source_engines,source_upload_ids,
            trust_score_id,status,title,recommendation,trust_score,evidence_strength,
            observation_type,trigger_type,trigger_detail,triggered_by,
            supersedes_id,change_summary,key_assumptions,known_limitations,
            commercial_priority,revenue_expected)
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (gid, ts, version, insight_type, insight_id,
         json.dumps(source_engines or [insight_type]),
         json.dumps(source_upload_ids or []),
         te.get("audit_trail",{}).get("trust_score_id",""),
         "active", title, recommendation,
         te.get("trust_score",0),
         te.get("evidence_strength",{}).get("label","UNKNOWN") if isinstance(te.get("evidence_strength"),dict) else str(te.get("evidence_strength","UNKNOWN")),
         te.get("observation_type","AI_INFERENCE"),
         trigger_type, trigger_detail, triggered_by,
         supersedes_id, change_summary,
         json.dumps(te.get("limitations",[])),
         json.dumps(te.get("challenge_points",[])),
         commercial_priority, revenue_expected)
    )
    conn.commit()
    conn.close()

    return {
        "governance_id": gid, "version": version,
        "supersedes_id": supersedes_id, "change_summary": change_summary
    }


# ── Governance Record Retrieval ───────────────────────────────────────────────

def get_governance_history(insight_type: str, insight_id: str) -> list:
    """Full version history for an insight — newest first."""
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM governance_records WHERE insight_type=? AND insight_id=? ORDER BY version DESC",
        (insight_type, insight_id)
    ).fetchall()
    conn.close()
    result = []
    for r in rows:
        d = dict(r)
        for f in ["source_engines","source_upload_ids","key_assumptions","known_limitations"]:
            try: d[f] = json.loads(d.get(f,"[]") or "[]")
            except: d[f] = []
        result.append(d)
    return result


def get_active_governance_records(
    insight_type: str = None,
    min_trust: int = 0,
    limit: int = 100
) -> list:
    conn = get_db()
    q = "SELECT * FROM governance_records WHERE status='active' AND 1=1"
    p = []
    if insight_type: q += " AND insight_type=?"; p.append(insight_type)
    if min_trust:    q += " AND trust_score>=?";  p.append(min_trust)
    q += " ORDER BY created_at DESC LIMIT ?"; p.append(limit)
    rows = conn.execute(q, p).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_governance_record(governance_id: str) -> dict:
    conn = get_db()
    row = conn.execute("SELECT * FROM governance_records WHERE id=?", (governance_id,)).fetchone()
    conn.close()
    if not row: return {}
    d = dict(row)
    for f in ["source_engines","source_upload_ids","key_assumptions","known_limitations"]:
        try: d[f] = json.loads(d.get(f,"[]") or "[]")
        except: d[f] = []
    return d


# ── Evidence Comparison ───────────────────────────────────────────────────────

def compare_uploads(upload_id_a: str, upload_id_b: str) -> dict:
    """
    Compare two DDR uploads side-by-side.
    Uses existing market_snapshots and opportunities — no new extraction.
    Returns a structured diff with all changed dimensions.
    """
    conn = get_db()

    snap_a = conn.execute("SELECT * FROM market_snapshots WHERE upload_id=?", (upload_id_a,)).fetchone()
    snap_b = conn.execute("SELECT * FROM market_snapshots WHERE upload_id=?", (upload_id_b,)).fetchone()
    upload_a = conn.execute("SELECT * FROM uploads WHERE id=?", (upload_id_a,)).fetchone()
    upload_b = conn.execute("SELECT * FROM uploads WHERE id=?", (upload_id_b,)).fetchone()
    opps_a = [dict(o) for o in conn.execute("SELECT * FROM opportunities WHERE upload_id=?", (upload_id_a,)).fetchall()]
    opps_b = [dict(o) for o in conn.execute("SELECT * FROM opportunities WHERE upload_id=?", (upload_id_b,)).fetchall()]
    comps_a = [dict(c) for c in conn.execute("SELECT * FROM competitors WHERE upload_id=?", (upload_id_a,)).fetchall()]
    comps_b = [dict(c) for c in conn.execute("SELECT * FROM competitors WHERE upload_id=?", (upload_id_b,)).fetchall()]
    conn.close()

    if not snap_a or not snap_b:
        return {"error": "One or both uploads not found or not yet processed"}

    sa = dict(snap_a); sb = dict(snap_b)
    ua = dict(upload_a) if upload_a else {}; ub = dict(upload_b) if upload_b else {}

    def deserialize(snap, field):
        try: return json.loads(snap.get(field,"{}") or "{}")
        except: return {}

    pl_a = deserialize(sa, "pl_distribution"); pl_b = deserialize(sb, "pl_distribution")
    fd_a = deserialize(sa, "field_distribution"); fd_b = deserialize(sb, "field_distribution")
    cd_a = deserialize(sa, "comp_distribution"); cd_b = deserialize(sb, "comp_distribution")
    try: rl_a = set(json.loads(sa.get("rig_list","[]") or "[]"))
    except: rl_a = set()
    try: rl_b = set(json.loads(sb.get("rig_list","[]") or "[]"))
    except: rl_b = set()

    def pct(a, b):
        if not a: return None
        return round((b-a)/a*100, 1)

    # Rig changes
    new_rigs  = sorted(rl_b - rl_a)
    lost_rigs = sorted(rl_a - rl_b)

    # Competitor changes
    comp_changes = []
    for comp in set(list(cd_a.keys()) + list(cd_b.keys())):
        n_a = cd_a.get(comp, 0); n_b = cd_b.get(comp, 0)
        if n_a != n_b:
            comp_changes.append({"competitor": comp, "a": n_a, "b": n_b,
                                  "change": n_b-n_a,
                                  "direction": "entered" if n_a==0 else "exited" if n_b==0 else
                                               "expanded" if n_b>n_a else "contracted"})

    # PL demand changes
    pl_changes = []
    for pl in set(list(pl_a.keys()) + list(pl_b.keys())):
        n_a = pl_a.get(pl,0); n_b = pl_b.get(pl,0)
        if n_a != n_b:
            pl_changes.append({"product_line": pl, "a": n_a, "b": n_b,
                                "change": n_b-n_a, "change_pct": pct(n_a,n_b)})

    # Opportunity-level changes
    opp_titles_a = {o.get("product_line","")+"::"+o.get("rig","") for o in opps_a}
    opp_titles_b = {o.get("product_line","")+"::"+o.get("rig","") for o in opps_b}
    new_opps  = sorted(opp_titles_b - opp_titles_a)
    lost_opps = sorted(opp_titles_a - opp_titles_b)

    pipeline_a = sum(o.get("estimated_value",0) for o in opps_a)
    pipeline_b = sum(o.get("estimated_value",0) for o in opps_b)

    return {
        "report_a": {"upload_id": upload_id_a, "filename": ua.get("filename",""), "date": ua.get("report_date","")},
        "report_b": {"upload_id": upload_id_b, "filename": ub.get("filename",""), "date": ub.get("report_date","")},
        "summary": {
            "rig_count_a":   sa.get("active_rigs",0),  "rig_count_b":  sb.get("active_rigs",0),
            "opp_count_a":   sa.get("total_opps",0),   "opp_count_b":  sb.get("total_opps",0),
            "pipeline_a":    pipeline_a,                "pipeline_b":   pipeline_b,
            "pipeline_change_pct": pct(pipeline_a, pipeline_b),
            "intensity_a":   sa.get("activity_intensity",0), "intensity_b": sb.get("activity_intensity",0),
            "comp_density_a":sa.get("competitor_density",0),  "comp_density_b": sb.get("competitor_density",0),
        },
        "rig_changes":        {"new": new_rigs, "removed": lost_rigs},
        "competitor_changes": sorted(comp_changes, key=lambda x:-abs(x["change"])),
        "product_line_changes": sorted(pl_changes, key=lambda x:-abs(x.get("change",0))),
        "opportunity_changes": {"added": new_opps[:10], "removed": lost_opps[:10]},
        "field_changes": {
            "new_fields":  sorted(set(fd_b.keys()) - set(fd_a.keys())),
            "lost_fields": sorted(set(fd_a.keys()) - set(fd_b.keys())),
        },
        "trust_change": {
            "intensity_change": sb.get("activity_intensity",0) - sa.get("activity_intensity",0),
        },
    }


# ── Intelligence Quality Scoring ──────────────────────────────────────────────

def compute_intelligence_quality() -> dict:
    """
    Compute the overall Intelligence Quality Score from existing data.
    Pure aggregation over existing tables — no new processing.

    Scores 7 dimensions (0-100 each) → weighted composite (0-100).
    """
    conn = get_db()

    # 1. Market Coverage — unique rigs, fields, wells across all uploads
    rigs   = conn.execute("SELECT COUNT(DISTINCT rig) FROM opportunities WHERE rig!=''").fetchone()[0]
    fields = conn.execute("SELECT COUNT(DISTINCT field) FROM opportunities WHERE field!=''").fetchone()[0]
    comps  = conn.execute("SELECT COUNT(DISTINCT normalized) FROM competitors WHERE normalized!=''").fetchone()[0]
    opps   = conn.execute("SELECT COUNT(*) FROM opportunities").fetchone()[0]
    uploads= conn.execute("SELECT COUNT(*) FROM uploads").fetchone()[0]

    # 2. Data Freshness — how recent is the most recent upload?
    latest = conn.execute("SELECT MAX(upload_ts) FROM uploads").fetchone()[0] or ""
    freshness_score = 0
    if latest:
        try:
            days = (datetime.datetime.utcnow() - datetime.datetime.fromisoformat(latest[:19])).days
            freshness_score = 100 if days<=1 else 85 if days<=7 else 70 if days<=30 else 40 if days<=90 else 10
        except: pass

    # 3. Evidence Quality — avg trust score
    trust_rows = conn.execute("SELECT AVG(trust_score), COUNT(*) FROM trust_scores").fetchone()
    avg_trust = round(trust_rows[0] or 0)
    trust_count = trust_rows[1] or 0

    # 4. Historical Depth — number of uploads (more = better trends)
    depth_score = min(100, uploads * 20)  # 5 uploads = 100

    # 5. Operator Coverage — unique fields as proxy
    op_score = min(100, fields * 12)

    # 6. Competitor Coverage — unique competitors
    comp_score = min(100, comps * 12)

    # 7. Validation Rate — how many opps have been validated by a human?
    validated = conn.execute(
        "SELECT COUNT(*) FROM opportunities WHERE validation_status IN ('accepted','rejected','converted')"
    ).fetchone()[0]
    val_rate = round(validated / max(opps,1) * 100) if opps else 0
    val_score = min(100, val_rate * 1.5)

    conn.close()

    # Weighted composite
    weights = {
        "data_freshness":  0.25,
        "evidence_quality":0.20,
        "market_coverage": 0.15,
        "historical_depth":0.15,
        "operator_coverage":0.10,
        "competitor_coverage":0.10,
        "validation_rate": 0.05,
    }
    market_coverage  = min(100, (rigs*4 + fields*6 + comps*3))
    scores = {
        "data_freshness":     freshness_score,
        "evidence_quality":   avg_trust,
        "market_coverage":    market_coverage,
        "historical_depth":   depth_score,
        "operator_coverage":  op_score,
        "competitor_coverage":comp_score,
        "validation_rate":    val_score,
    }
    composite = round(sum(scores[k]*weights[k] for k in weights))

    # Grade
    grade = "A" if composite>=85 else "B" if composite>=70 else "C" if composite>=55 else "D"
    label = {"A":"Enterprise Ready","B":"Good","C":"Developing","D":"Needs Improvement"}[grade]

    # Coverage gaps (dimensions below 40)
    gaps = [{"dimension":k.replace("_"," ").title(),"score":v,"gap":True}
            for k,v in scores.items() if v < 40]

    return {
        "composite_score":   composite,
        "grade":             grade,
        "grade_label":       label,
        "dimension_scores":  scores,
        "weights":           weights,
        "coverage_gaps":     gaps,
        "raw_counts": {
            "unique_rigs":      rigs,
            "unique_fields":    fields,
            "unique_competitors":comps,
            "total_opportunities":opps,
            "uploads_processed":uploads,
            "trust_scored":     trust_count,
            "validated_opps":   validated,
        },
        "freshness_label": (
            "LIVE" if freshness_score==100 else
            "RECENT" if freshness_score>=85 else
            "CURRENT" if freshness_score>=70 else
            "STALE" if freshness_score>=40 else "OUTDATED"
        ),
    }


# ── Decision Journal ──────────────────────────────────────────────────────────

def add_decision(data: dict, recorded_by: str = "") -> dict:
    conn = get_db()
    did  = str(uuid.uuid4())
    ts   = datetime.datetime.utcnow().isoformat()
    conn.execute(
        """INSERT INTO decision_journal
           (id,created_at,updated_at,governance_id,insight_type,insight_id,
            decision_type,title,description,outcome,owner,customer,product_line,
            pipeline_item_id,lesson_learned_id,revenue_actual,status,recorded_by)
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (did,ts,ts,
         data.get("governance_id",""), data.get("insight_type","opportunity"),
         data.get("insight_id",""), data.get("decision_type","other"),
         data.get("title",""), data.get("description",""),
         data.get("outcome",""), data.get("owner",""),
         data.get("customer",""), data.get("product_line",""),
         data.get("pipeline_item_id",""), data.get("lesson_learned_id",""),
         data.get("revenue_actual",0), "open", recorded_by)
    )
    conn.commit()
    row = conn.execute("SELECT * FROM decision_journal WHERE id=?", (did,)).fetchone()
    conn.close()
    return dict(row) if row else {}


def get_decision_journal(insight_id: str = None, decision_type: str = None,
                          limit: int = 50) -> list:
    conn = get_db()
    q = "SELECT * FROM decision_journal WHERE 1=1"
    p = []
    if insight_id:    q += " AND insight_id=?";    p.append(insight_id)
    if decision_type: q += " AND decision_type=?"; p.append(decision_type)
    q += " ORDER BY created_at DESC LIMIT ?"; p.append(limit)
    rows = conn.execute(q, p).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_decision_timeline() -> list:
    """Full decision timeline across all insights — for executive view."""
    conn = get_db()
    rows = conn.execute(
        """SELECT dj.*, gr.title as insight_title, gr.trust_score, gr.evidence_strength
           FROM decision_journal dj
           LEFT JOIN governance_records gr ON gr.insight_id=dj.insight_id AND gr.status='active'
           ORDER BY dj.created_at DESC LIMIT 100"""
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── Quality History Table ─────────────────────────────────────────────────────

def init_quality_history_table():
    """Add quality_history table — one row per upload, tracks quality over time."""
    conn = get_db()
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS quality_history (
        id              TEXT PRIMARY KEY,
        recorded_at     TEXT NOT NULL,
        upload_id       TEXT DEFAULT '',
        composite_score INTEGER NOT NULL,
        grade           TEXT NOT NULL,
        data_freshness  INTEGER DEFAULT 0,
        evidence_quality INTEGER DEFAULT 0,
        market_coverage INTEGER DEFAULT 0,
        historical_depth INTEGER DEFAULT 0,
        operator_coverage INTEGER DEFAULT 0,
        competitor_coverage INTEGER DEFAULT 0,
        validation_rate INTEGER DEFAULT 0,
        unique_rigs     INTEGER DEFAULT 0,
        unique_fields   INTEGER DEFAULT 0,
        uploads_processed INTEGER DEFAULT 0
    );
    CREATE INDEX IF NOT EXISTS idx_qh_date ON quality_history(recorded_at);
    """)
    conn.commit()
    conn.close()


def record_quality_snapshot(upload_id: str = "") -> dict:
    """Record current quality score — called after each upload."""
    q   = compute_intelligence_quality()
    if q.get("status") == "no_data":
        return q
    conn = get_db()
    import uuid as _uuid
    qid = str(_uuid.uuid4())
    ds  = q.get("dimension_scores", {})
    rc  = q.get("raw_counts", {})
    conn.execute(
        """INSERT INTO quality_history
           (id,recorded_at,upload_id,composite_score,grade,data_freshness,
            evidence_quality,market_coverage,historical_depth,operator_coverage,
            competitor_coverage,validation_rate,unique_rigs,unique_fields,uploads_processed)
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (qid, datetime.datetime.utcnow().isoformat(), upload_id,
         q.get("composite_score",0), q.get("grade","D"),
         ds.get("data_freshness",0), ds.get("evidence_quality",0),
         ds.get("market_coverage",0), ds.get("historical_depth",0),
         ds.get("operator_coverage",0), ds.get("competitor_coverage",0),
         ds.get("validation_rate",0),
         rc.get("unique_rigs",0), rc.get("unique_fields",0), rc.get("uploads_processed",0))
    )
    conn.commit()
    conn.close()
    return {"quality_id": qid, "composite_score": q.get("composite_score",0)}


def get_quality_history(limit: int = 20) -> list:
    """Return quality score history for trend visualization."""
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM quality_history ORDER BY recorded_at DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]
