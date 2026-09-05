"""
EnergiPro – SQLite persistence layer
"""
import json, os, sqlite3, datetime
from pathlib import Path

DB_PATH = os.environ.get("EIP_DB_PATH", "/data/energipro.db")

def get_db():
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn

def init_db():
    conn = get_db()
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS uploads (
        id TEXT PRIMARY KEY, filename TEXT, upload_ts TEXT,
        report_date TEXT, rig_count INTEGER, opp_count INTEGER,
        comp_count INTEGER, pipeline REAL, narrative TEXT,
        content_hash TEXT DEFAULT '',
        page_count INTEGER DEFAULT 0,
        word_count INTEGER DEFAULT 0,
        extraction_warnings TEXT DEFAULT '',
        ocr_required INTEGER DEFAULT 0,
        upload_mode TEXT DEFAULT 'replace',
        uploaded_by TEXT DEFAULT ''
    );
    CREATE TABLE IF NOT EXISTS opportunities (
        id TEXT PRIMARY KEY, upload_id TEXT, title TEXT, product_line TEXT,
        rig TEXT, well TEXT, field TEXT, confidence INTEGER, estimated_value REAL,
        urgency TEXT, timing_label TEXT, stage TEXT, status TEXT DEFAULT 'open',
        competitor TEXT, evidence_text TEXT, evidence_section TEXT,
        matched_keywords TEXT, action TEXT, suggested_contact TEXT,
        rank INTEGER, created_at TEXT,
        what_we_sell TEXT DEFAULT '',
        win_probability REAL DEFAULT 0.0,
        contact_name TEXT DEFAULT '',
        -- Wave 2: validation workflow
        validation_status TEXT DEFAULT 'new',
        validated_by TEXT DEFAULT '',
        validated_at TEXT DEFAULT '',
        validator_comment TEXT DEFAULT '',
        rejection_reason TEXT DEFAULT '',
        next_action TEXT DEFAULT '',
        -- Wave 2: source traceability
        source_file TEXT DEFAULT '',
        source_page INTEGER DEFAULT 0,
        source_section TEXT DEFAULT ''
    );
    CREATE TABLE IF NOT EXISTS competitors (
        id TEXT PRIMARY KEY, upload_id TEXT, normalized TEXT, raw_name TEXT,
        service_category TEXT, rig TEXT, well TEXT, status TEXT,
        evidence TEXT, section TEXT, confidence INTEGER
    );
    CREATE TABLE IF NOT EXISTS lifecycle (
        id TEXT PRIMARY KEY, upload_id TEXT, rig TEXT, well TEXT,
        current_stage TEXT, sub_stage TEXT, next_stage TEXT,
        transition_signal TEXT, timing_estimate TEXT, confidence INTEGER,
        expected_product_lines TEXT, next_well TEXT, readiness_pct INTEGER,
        commercial_rec TEXT
    );
    CREATE TABLE IF NOT EXISTS actions (
        id TEXT PRIMARY KEY, opportunity_id TEXT, title TEXT, owner TEXT,
        due_date TEXT, priority TEXT, reason TEXT, expected_outcome TEXT,
        status TEXT DEFAULT 'open', notes TEXT, created_at TEXT, updated_at TEXT
    );
    CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
    CREATE TABLE IF NOT EXISTS snapshots (
        id TEXT PRIMARY KEY, upload_ts TEXT, report_date TEXT, filename TEXT,
        opp_count INTEGER, pipeline REAL, immediate INTEGER, rigs_parsed INTEGER,
        pl_counts TEXT
    );
    CREATE TABLE IF NOT EXISTS leads (
        id TEXT PRIMARY KEY,
        opportunity_id TEXT,
        title TEXT NOT NULL,
        customer TEXT DEFAULT '',
        rig TEXT DEFAULT '',
        well TEXT DEFAULT '',
        field TEXT DEFAULT '',
        product_line TEXT DEFAULT '',
        description TEXT DEFAULT '',
        evidence TEXT DEFAULT '',
        priority TEXT DEFAULT 'medium',
        owner TEXT DEFAULT 'Unassigned',
        due_date TEXT DEFAULT '',
        status TEXT DEFAULT 'open',
        created_by TEXT DEFAULT '',
        created_at TEXT,
        updated_at TEXT,
        notes TEXT DEFAULT ''
    );
    CREATE TABLE IF NOT EXISTS confidence_scores (
        id TEXT PRIMARY KEY,
        opportunity_id TEXT NOT NULL,
        pl_match_score INTEGER DEFAULT 0,
        activity_score INTEGER DEFAULT 0,
        rig_clarity_score INTEGER DEFAULT 0,
        competitor_score INTEGER DEFAULT 0,
        evidence_score INTEGER DEFAULT 0,
        recency_score INTEGER DEFAULT 0,
        total_score INTEGER DEFAULT 0,
        explanation TEXT DEFAULT '',
        created_at TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_opps_upload ON opportunities(upload_id);
    CREATE INDEX IF NOT EXISTS idx_opps_validation ON opportunities(validation_status);
    CREATE INDEX IF NOT EXISTS idx_comp_upload ON competitors(upload_id);
    CREATE INDEX IF NOT EXISTS idx_leads_status ON leads(status);
    CREATE INDEX IF NOT EXISTS idx_leads_opp ON leads(opportunity_id);
    """)
    conn.commit()
    defaults = {
        "company_name":"EnergiPro","primary_color":"#2563EB",
        "logo_text":"EIP","min_confidence":"65",
        "tagline":"Intelligence Platform",
        "company_tagline":"Enterprise Oilfield Market Intelligence",
        "value_rates": '{"MWD / Directional":220000,"Completion":75000,"Fishing / Intervention":160000,"Cementing":45000,"Wireline / Logging":53000,"Solids Control":60000,"Well Testing":88000,"Rental / Intervention":22000,"H2S / Safety":17000}',
    }
    # Migrate existing DB: add new columns if they don't exist
    wave2_migrations = [
        ("opportunities", "what_we_sell",       "TEXT DEFAULT ''"),
        ("opportunities", "win_probability",     "REAL DEFAULT 0.0"),
        ("opportunities", "contact_name",        "TEXT DEFAULT ''"),
        ("opportunities", "validation_status",   "TEXT DEFAULT 'new'"),
        ("opportunities", "validated_by",        "TEXT DEFAULT ''"),
        ("opportunities", "validated_at",        "TEXT DEFAULT ''"),
        ("opportunities", "validator_comment",   "TEXT DEFAULT ''"),
        ("opportunities", "rejection_reason",    "TEXT DEFAULT ''"),
        ("opportunities", "next_action",         "TEXT DEFAULT ''"),
        ("opportunities", "source_file",         "TEXT DEFAULT ''"),
        ("opportunities", "source_page",         "INTEGER DEFAULT 0"),
        ("opportunities", "source_section",      "TEXT DEFAULT ''"),
    ]
    for table, col, defn in wave2_migrations:
        try:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {defn}")
            conn.commit()
        except Exception:
            pass  # Column already exists

    # Wave 3: uploads table new columns
    upload_migrations = [
        ("content_hash",        "TEXT DEFAULT ''"),
        ("page_count",          "INTEGER DEFAULT 0"),
        ("word_count",          "INTEGER DEFAULT 0"),
        ("extraction_warnings", "TEXT DEFAULT ''"),
        ("ocr_required",        "INTEGER DEFAULT 0"),
        ("upload_mode",         "TEXT DEFAULT 'replace'"),
        ("uploaded_by",         "TEXT DEFAULT ''"),
    ]
    for col, defn in upload_migrations:
        try:
            conn.execute(f"ALTER TABLE uploads ADD COLUMN {col} {defn}")
            conn.commit()
        except Exception:
            pass

    for k,v in defaults.items():
        conn.execute("INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)",(k,v))
    conn.commit(); conn.close()

def clear_all_data():
    """Clear all extracted intelligence data (keep settings and actions)."""
    conn = get_db()
    conn.executescript("""
        DELETE FROM opportunities;
        DELETE FROM competitors;
        DELETE FROM lifecycle;
        DELETE FROM uploads;
        DELETE FROM snapshots;
    """)
    conn.commit(); conn.close()

def check_duplicate(content_hash: str, filename: str) -> dict:
    """Check if this file has been uploaded before. Returns match info or {}."""
    conn = get_db()
    # Exact hash match
    row = conn.execute(
        "SELECT id, filename, upload_ts, report_date, opp_count FROM uploads WHERE content_hash=? LIMIT 1",
        (content_hash,)
    ).fetchone()
    conn.close()
    if row:
        return {"type": "exact", "upload_id": row["id"], "filename": row["filename"],
                "uploaded_at": row["upload_ts"], "report_date": row["report_date"]}
    # Same filename (near-duplicate warning)
    conn = get_db()
    row2 = conn.execute(
        "SELECT id, upload_ts, report_date FROM uploads WHERE filename=? ORDER BY upload_ts DESC LIMIT 1",
        (filename,)
    ).fetchone()
    conn.close()
    if row2:
        return {"type": "same_filename", "upload_id": row2["id"],
                "uploaded_at": row2["upload_ts"], "report_date": row2["report_date"]}
    return {}


def save_upload(upload_id, result, replace_mode=True, uploaded_by="", quality=None):
    import uuid as _uuid
    conn = get_db()
    ts = datetime.datetime.utcnow().isoformat()
    q = quality or {}

    if replace_mode:
        conn.executescript("""
            DELETE FROM opportunities;
            DELETE FROM competitors;
            DELETE FROM lifecycle;
            DELETE FROM uploads;
        """)

    conn.execute(
        "INSERT OR REPLACE INTO uploads VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (upload_id, result.get("filename",""), ts, result.get("report_date",""),
         result.get("rig_count",0), result.get("opportunity_count",0),
         result.get("competitor_count",0),
         result.get("kpis",{}).get("pipeline_total",0),
         result.get("narrative","")[:5000],
         q.get("content_hash",""),
         q.get("page_count", 0),
         q.get("word_count", 0),
         json.dumps(q.get("warnings", [])),
         1 if q.get("ocr_required") else 0,
         "replace" if replace_mode else "append",
         uploaded_by,
        )
    )
    # Snapshot: persists across replace-mode uploads → enables trend comparison
    pl_counts = {}
    for opp in result.get("opportunities", []):
        pl = opp.get("product_line", "Other")
        pl_counts[pl] = pl_counts.get(pl, 0) + 1
    conn.execute("INSERT OR REPLACE INTO snapshots VALUES(?,?,?,?,?,?,?,?,?)",
        (upload_id, ts, result.get("report_date",""), result.get("filename",""),
         result.get("opportunity_count",0),
         result.get("kpis",{}).get("pipeline_total",0),
         result.get("kpis",{}).get("immediate_targets",0),
         result.get("rig_count",0),
         json.dumps(pl_counts)))
    for opp in result.get("opportunities",[]):
        oid = opp.get("id") or str(_uuid.uuid4())
        conn.execute(
            "INSERT OR REPLACE INTO opportunities VALUES("
            "?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,"  # original 24
            "?,?,?,?,?,?,?,?,?"                                   # wave2 9 new cols
            ")",
            (oid, upload_id, opp.get("title",""), opp.get("product_line",""),
             opp.get("rig",""), opp.get("well",""), opp.get("field",""),
             opp.get("confidence",0), opp.get("estimated_value",0),
             opp.get("urgency",""), opp.get("timing_label",""), opp.get("stage",""),
             opp.get("status","open"), opp.get("competitor",""),
             opp.get("evidence_text","")[:1000], opp.get("evidence_section",""),
             json.dumps(opp.get("matched_keywords",[])),
             opp.get("action",""), opp.get("suggested_contact",""),
             opp.get("rank",0), ts,
             opp.get("what_we_sell",""), opp.get("win_probability",0.0),
             opp.get("contact_name",""),
             # Wave 2: validation
             "new", "", "", "", "", "",
             # Wave 2: source traceability
             opp.get("source_file",""), opp.get("source_page",0), opp.get("source_section","")
             ))
    for c in result.get("competitors",[]):
        conn.execute("INSERT OR REPLACE INTO competitors VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (str(_uuid.uuid4()), upload_id, c.get("normalized",""), c.get("raw_name",""),
             c.get("service_category",""), c.get("rig",""), c.get("well",""),
             c.get("status",""), c.get("evidence","")[:500], c.get("section",""), c.get("confidence",80)))
    for lc in result.get("lifecycle",[]):
        conn.execute("INSERT OR REPLACE INTO lifecycle VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (str(_uuid.uuid4()), upload_id, lc.get("rig",""), lc.get("well",""),
             lc.get("current_stage",""), lc.get("sub_stage",""), lc.get("next_stage",""),
             lc.get("transition_signal","")[:500], lc.get("timing_estimate",""),
             lc.get("confidence",0), json.dumps(lc.get("expected_product_lines",[])),
             lc.get("next_well",""), lc.get("readiness_pct",0), lc.get("commercial_rec","")))
    conn.commit(); conn.close()

def load_latest(n_uploads=1):
    conn = get_db()
    uploads = conn.execute("SELECT * FROM uploads ORDER BY upload_ts DESC LIMIT ?",(n_uploads,)).fetchall()
    if not uploads: conn.close(); return None
    uids = [u["id"] for u in uploads]
    ph = ",".join("?"*len(uids))
    def rows(q,p): return conn.execute(q,p).fetchall()
    opps  = rows(f"SELECT * FROM opportunities WHERE upload_id IN ({ph}) ORDER BY rank", uids)
    comps = rows(f"SELECT * FROM competitors WHERE upload_id IN ({ph})", uids)
    lcs   = rows(f"SELECT * FROM lifecycle WHERE upload_id IN ({ph})", uids)
    latest = uploads[0]; conn.close()
    def to_d(r):
        d=dict(r)
        for k in ("matched_keywords","expected_product_lines"):
            if d.get(k):
                try: d[k]=json.loads(d[k])
                except: pass
        return d
    ol=[to_d(o) for o in opps]; cl=[to_d(c) for c in comps]; ll=[to_d(l) for l in lcs]
    return {
        "filename":latest["filename"],"report_date":latest["report_date"],
        "narrative":latest["narrative"],
        "rigs":list(set(o["rig"] for o in ol if o["rig"])),
        "rig_count":latest["rig_count"],
        "opportunities":ol,"opportunity_count":latest["opp_count"],
        "competitors":cl,"competitor_count":latest["comp_count"],
        "lifecycle":ll,"reports_processed":len(uploads),
        "kpis":{
            "open_opportunities":len(ol),
            "pipeline_total":sum(o.get("estimated_value",0) for o in ol),
            "immediate_targets":sum(1 for o in ol if o.get("urgency") in ("immediate","5_days")),
            "active_rigs":len(set(o["rig"] for o in ol if o["rig"])),
            "rigs_parsed":latest["rig_count"],
            "report_date":latest["report_date"],
            "competitor_mentions":len(cl),
            "reports_processed":len(uploads),
        }
    }

def get_snapshots(n=10):
    conn=get_db()
    rows=conn.execute("SELECT * FROM snapshots ORDER BY upload_ts DESC LIMIT ?",(n,)).fetchall()
    conn.close()
    out=[]
    for r in rows:
        d=dict(r)
        try: d["pl_counts"]=json.loads(d.get("pl_counts") or "{}")
        except Exception: d["pl_counts"]={}
        out.append(d)
    return out

def load_actions():
    conn=get_db(); rows=conn.execute("SELECT * FROM actions ORDER BY created_at DESC").fetchall(); conn.close(); return [dict(r) for r in rows]

def save_action(a):
    conn=get_db(); ts=datetime.datetime.utcnow().isoformat()
    conn.execute("INSERT OR REPLACE INTO actions VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
        (a["id"],a.get("opportunity_id",""),a.get("title",""),a.get("owner","Unassigned"),
         a.get("due_date",""),a.get("priority","high"),a.get("reason",""),
         a.get("expected_outcome",""),a.get("status","open"),a.get("notes",""),
         a.get("created_at",ts),ts))
    conn.commit(); conn.close()

def update_opp_status(opp_id, status):
    """Backwards compatibility alias for update_opp_validation."""
    conn=get_db(); conn.execute("UPDATE opportunities SET status=? WHERE id=?",(status,opp_id)); conn.commit()
    opp=conn.execute("SELECT * FROM opportunities WHERE id=?",(opp_id,)).fetchone(); conn.close()
    return dict(opp) if opp else None

def update_opp_validation(opp_id: str, validation_status: str, validated_by: str,
                           comment: str = "", rejection_reason: str = "", next_action: str = "") -> dict:
    """Update validation workflow fields on an opportunity."""
    import datetime as _dt
    conn = get_db()
    ts = _dt.datetime.utcnow().isoformat()
    conn.execute(
        """UPDATE opportunities SET
           validation_status=?, validated_by=?, validated_at=?,
           validator_comment=?, rejection_reason=?, next_action=?
           WHERE id=?""",
        (validation_status, validated_by, ts, comment, rejection_reason, next_action, opp_id)
    )
    conn.commit()
    row = conn.execute("SELECT * FROM opportunities WHERE id=?", (opp_id,)).fetchone()
    conn.close()
    return dict(row) if row else {}


def bulk_update_validation(opp_ids: list, validation_status: str,
                            validated_by: str, comment: str = "") -> int:
    """Bulk update validation status for multiple opportunities."""
    import datetime as _dt
    if not opp_ids:
        return 0
    conn = get_db()
    ts = _dt.datetime.utcnow().isoformat()
    ph = ",".join("?" * len(opp_ids))
    conn.execute(
        f"UPDATE opportunities SET validation_status=?, validated_by=?, validated_at=?, validator_comment=? WHERE id IN ({ph})",
        [validation_status, validated_by, ts, comment] + list(opp_ids)
    )
    affected = conn.execute("SELECT changes()").fetchone()[0]
    conn.commit(); conn.close()
    return affected


# ── Lead management ───────────────────────────────────────────────────────────
def create_lead(lead: dict) -> dict:
    import uuid as _uuid, datetime as _dt
    conn = get_db()
    lid = lead.get("id") or str(_uuid.uuid4())
    ts  = _dt.datetime.utcnow().isoformat()
    conn.execute(
        "INSERT INTO leads(id,opportunity_id,title,customer,rig,well,field,product_line,"
        "description,evidence,priority,owner,due_date,status,created_by,created_at,updated_at,notes) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (lid, lead.get("opportunity_id",""), lead.get("title",""),
         lead.get("customer",""), lead.get("rig",""), lead.get("well",""),
         lead.get("field",""), lead.get("product_line",""),
         lead.get("description",""), lead.get("evidence",""),
         lead.get("priority","medium"), lead.get("owner","Unassigned"),
         lead.get("due_date",""), lead.get("status","open"),
         lead.get("created_by",""), ts, ts, lead.get("notes",""))
    )
    conn.commit()
    row = conn.execute("SELECT * FROM leads WHERE id=?", (lid,)).fetchone()
    conn.close()
    return dict(row) if row else {}


def list_leads(status: str = None, owner: str = None, priority: str = None) -> list:
    conn = get_db()
    q = "SELECT * FROM leads WHERE 1=1"
    p = []
    if status:   q += " AND status=?";   p.append(status)
    if owner:    q += " AND owner=?";    p.append(owner)
    if priority: q += " AND priority=?"; p.append(priority)
    q += " ORDER BY created_at DESC"
    rows = conn.execute(q, p).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_lead(lead_id: str) -> dict:
    conn = get_db()
    row = conn.execute("SELECT * FROM leads WHERE id=?", (lead_id,)).fetchone()
    conn.close()
    return dict(row) if row else {}


def update_lead(lead_id: str, updates: dict) -> dict:
    import datetime as _dt
    allowed = {"title","customer","rig","well","field","product_line","description",
               "evidence","priority","owner","due_date","status","notes"}
    conn = get_db()
    ts = _dt.datetime.utcnow().isoformat()
    for k, v in updates.items():
        if k in allowed:
            conn.execute(f"UPDATE leads SET {k}=?, updated_at=? WHERE id=?", (v, ts, lead_id))
    conn.commit()
    row = conn.execute("SELECT * FROM leads WHERE id=?", (lead_id,)).fetchone()
    conn.close()
    return dict(row) if row else {}


def get_lead_pipeline_summary() -> dict:
    """Summary stats for lead pipeline dashboard."""
    conn = get_db()
    total  = conn.execute("SELECT COUNT(*) FROM leads").fetchone()[0]
    by_status = {}
    for row in conn.execute("SELECT status, COUNT(*) as n FROM leads GROUP BY status").fetchall():
        by_status[row["status"]] = row["n"]
    by_priority = {}
    for row in conn.execute("SELECT priority, COUNT(*) as n FROM leads GROUP BY priority").fetchall():
        by_priority[row["priority"]] = row["n"]
    by_pl = []
    for row in conn.execute("SELECT product_line, COUNT(*) as n, COUNT(CASE WHEN status='won' THEN 1 END) as won FROM leads GROUP BY product_line ORDER BY n DESC").fetchall():
        by_pl.append(dict(row))
    conn.close()
    return {
        "total": total,
        "by_status": by_status,
        "by_priority": by_priority,
        "by_product_line": by_pl,
        "open": by_status.get("open", 0),
        "won":  by_status.get("won", 0),
        "lost": by_status.get("lost", 0),
        "conversion_rate": round(by_status.get("won",0)/max(total,1)*100, 1),
    }


# ── Confidence score storage ──────────────────────────────────────────────────
def save_confidence_score(opp_id: str, scores: dict):
    import uuid as _uuid, datetime as _dt
    conn = get_db()
    conn.execute(
        "INSERT OR REPLACE INTO confidence_scores VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        (str(_uuid.uuid4()), opp_id,
         scores.get("pl_match", 0), scores.get("activity", 0),
         scores.get("rig_clarity", 0), scores.get("competitor", 0),
         scores.get("evidence", 0), scores.get("recency", 0),
         scores.get("total", 0), scores.get("explanation",""),
         _dt.datetime.utcnow().isoformat())
    )
    conn.commit(); conn.close()


def get_confidence_score(opp_id: str) -> dict:
    conn = get_db()
    row = conn.execute("SELECT * FROM confidence_scores WHERE opportunity_id=? ORDER BY created_at DESC LIMIT 1", (opp_id,)).fetchone()
    conn.close()
    return dict(row) if row else {}


# ── Evidence search ───────────────────────────────────────────────────────────
def search_evidence(query: str = None, product_line: str = None,
                    rig: str = None, field: str = None,
                    competitor: str = None, validation_status: str = None,
                    min_confidence: int = 0, limit: int = 100) -> list:
    """Full-text search across opportunity evidence."""
    conn = get_db()
    q = "SELECT id,title,product_line,rig,well,field,competitor,confidence,validation_status,evidence_text,evidence_section,source_file,source_page FROM opportunities WHERE 1=1"
    p = []
    if query:             q += " AND (evidence_text LIKE ? OR title LIKE ?)"; p += [f"%{query}%", f"%{query}%"]
    if product_line:      q += " AND product_line=?";       p.append(product_line)
    if rig:               q += " AND rig=?";                p.append(rig)
    if field:             q += " AND field=?";              p.append(field)
    if competitor:        q += " AND competitor LIKE ?";    p.append(f"%{competitor}%")
    if validation_status: q += " AND validation_status=?";  p.append(validation_status)
    if min_confidence:    q += " AND confidence>=?";        p.append(min_confidence)
    q += " ORDER BY confidence DESC LIMIT ?"
    p.append(limit)
    rows = conn.execute(q, p).fetchall()
    conn.close()
    return [dict(r) for r in rows]
    conn=get_db(); conn.execute("UPDATE opportunities SET status=? WHERE id=?",(status,opp_id)); conn.commit()
    opp=conn.execute("SELECT * FROM opportunities WHERE id=?",(opp_id,)).fetchone(); conn.close()
    return dict(opp) if opp else None

def update_contact_name(opp_id, name):
    conn=get_db(); conn.execute("UPDATE opportunities SET contact_name=? WHERE id=?",(name,opp_id)); conn.commit()
    opp=conn.execute("SELECT * FROM opportunities WHERE id=?",(opp_id,)).fetchone(); conn.close()
    return dict(opp) if opp else None

def get_value_rates():
    conn=get_db(); row=conn.execute("SELECT value FROM settings WHERE key='value_rates'").fetchone(); conn.close()
    if row:
        try: return json.loads(row[0])
        except: pass
    return {}

def save_value_rates(rates_dict):
    conn=get_db(); conn.execute("INSERT OR REPLACE INTO settings(key,value) VALUES('value_rates',?)",(json.dumps(rates_dict),)); conn.commit(); conn.close()

def get_settings():
    conn=get_db(); rows=conn.execute("SELECT key,value FROM settings").fetchall(); conn.close(); return {r["key"]:r["value"] for r in rows}

def save_setting(key,value):
    conn=get_db(); conn.execute("INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)",(key,value)); conn.commit(); conn.close()

def get_upload_history():
    conn = get_db()
    rows = conn.execute(
        "SELECT id,filename,upload_ts,report_date,rig_count,opp_count,comp_count,pipeline,"
        "content_hash,page_count,word_count,extraction_warnings,ocr_required,upload_mode,uploaded_by "
        "FROM uploads ORDER BY upload_ts DESC LIMIT 50"
    ).fetchall()
    conn.close()
    out = []
    for r in rows:
        d = dict(r)
        try:
            d["extraction_warnings"] = json.loads(d.get("extraction_warnings") or "[]")
        except Exception:
            d["extraction_warnings"] = []
        out.append(d)
    return out
