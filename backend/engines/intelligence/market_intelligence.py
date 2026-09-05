"""
EIP v6.0 — Market Intelligence Engine
The analytical layer ABOVE individual opportunities.

Reads across ALL uploaded DDRs to produce market-level intelligence:
  - Operator activity profiles (not per-opportunity, per-operator)
  - Field activity intensity and trend
  - Product line demand across the market
  - Rig activity and migration patterns
  - Competitor market presence
  - Campaign detection signals
  - "What Changed?" detection between uploads

Design principle: this engine reads the DB directly, not the in-memory store.
It operates at market level — individual opportunities are evidence, not the output.
"""
from __future__ import annotations
import json, uuid, datetime
from collections import defaultdict, Counter
from typing import Optional
from core.database import get_db


# ── DB Table Initialisation ───────────────────────────────────────────────────

def init_market_tables():
    """Create all market intelligence tables."""
    conn = get_db()
    conn.executescript("""
    -- Time-series market state snapshot per upload
    CREATE TABLE IF NOT EXISTS market_snapshots (
        id              TEXT PRIMARY KEY,
        upload_id       TEXT NOT NULL,
        snapshot_date   TEXT NOT NULL,
        generated_at    TEXT NOT NULL,

        -- Activity counts
        active_rigs     INTEGER DEFAULT 0,
        active_wells    INTEGER DEFAULT 0,
        active_fields   INTEGER DEFAULT 0,
        active_operators INTEGER DEFAULT 0,
        total_opps      INTEGER DEFAULT 0,
        immediate_opps  INTEGER DEFAULT 0,
        high_conf_opps  INTEGER DEFAULT 0,

        -- Pipeline
        pipeline_expected  REAL DEFAULT 0,
        pipeline_weighted  REAL DEFAULT 0,

        -- Market composition (JSON)
        pl_distribution    TEXT DEFAULT '{}',  -- {product_line: count}
        field_distribution TEXT DEFAULT '{}',
        comp_distribution  TEXT DEFAULT '{}',
        rig_list           TEXT DEFAULT '[]',
        operator_list      TEXT DEFAULT '[]',

        -- Market intensity (0-100 scale)
        activity_intensity INTEGER DEFAULT 0,
        competitor_density INTEGER DEFAULT 0,
        opportunity_density INTEGER DEFAULT 0
    );

    -- Detected changes between consecutive uploads
    CREATE TABLE IF NOT EXISTS change_events (
        id              TEXT PRIMARY KEY,
        detected_at     TEXT NOT NULL,
        upload_id       TEXT NOT NULL,         -- The upload that triggered this change
        prev_upload_id  TEXT DEFAULT '',

        -- What changed
        change_type     TEXT NOT NULL,         -- See CHANGE_TYPES
        change_category TEXT DEFAULT '',       -- rig_activity|competitor|demand|operator|campaign
        title           TEXT NOT NULL,
        summary         TEXT NOT NULL,
        detail          TEXT DEFAULT '',

        -- Context
        affected_rig    TEXT DEFAULT '',
        affected_field  TEXT DEFAULT '',
        affected_pl     TEXT DEFAULT '',
        affected_comp   TEXT DEFAULT '',

        -- Assessment
        severity        TEXT DEFAULT 'info',   -- critical|high|medium|info
        commercial_impact TEXT DEFAULT '',
        recommended_action TEXT DEFAULT '',
        confidence      INTEGER DEFAULT 70,
        evidence        TEXT DEFAULT '[]',

        is_read         INTEGER DEFAULT 0
    );

    -- Campaign groups (multi-rig/multi-well drilling programmes)
    CREATE TABLE IF NOT EXISTS campaigns (
        id              TEXT PRIMARY KEY,
        name            TEXT NOT NULL,
        campaign_type   TEXT DEFAULT 'drilling',  -- drilling|completion|testing|workover
        status          TEXT DEFAULT 'active',    -- active|completed|planned
        detected_at     TEXT NOT NULL,

        -- Scope
        fields          TEXT DEFAULT '[]',
        rigs            TEXT DEFAULT '[]',
        wells           TEXT DEFAULT '[]',
        operators       TEXT DEFAULT '[]',

        -- Intelligence
        estimated_duration_weeks INTEGER DEFAULT 0,
        estimated_market_value   REAL DEFAULT 0,
        expected_services        TEXT DEFAULT '[]',  -- product lines likely needed
        campaign_stage           TEXT DEFAULT 'early',  -- early|mid|late|wrapping_up
        confidence               INTEGER DEFAULT 60,
        evidence_upload_ids      TEXT DEFAULT '[]',

        -- Notes
        notes           TEXT DEFAULT '',
        updated_at      TEXT
    );

    -- Competitor movement events (entry/exit from fields/rigs)
    CREATE TABLE IF NOT EXISTS competitor_movements (
        id              TEXT PRIMARY KEY,
        detected_at     TEXT NOT NULL,
        upload_id       TEXT NOT NULL,
        competitor      TEXT NOT NULL,
        movement_type   TEXT NOT NULL,  -- entered|exited|expanded|contracted|new_service
        field           TEXT DEFAULT '',
        rig             TEXT DEFAULT '',
        service_line    TEXT DEFAULT '',
        previous_state  TEXT DEFAULT '',
        current_state   TEXT DEFAULT '',
        confidence      INTEGER DEFAULT 70,
        evidence        TEXT DEFAULT '',
        commercial_threat TEXT DEFAULT ''
    );

    -- Trend signals (calculated direction per dimension)
    CREATE TABLE IF NOT EXISTS trend_signals (
        id              TEXT PRIMARY KEY,
        calculated_at   TEXT NOT NULL,
        dimension       TEXT NOT NULL,  -- product_line|field|competitor|rig_count|pipeline
        dimension_value TEXT NOT NULL,  -- the specific PL/field/competitor name
        direction       TEXT NOT NULL,  -- growing|stable|declining|emerging|disappearing
        magnitude       REAL DEFAULT 0, -- % change
        data_points     INTEGER DEFAULT 0,
        confidence      INTEGER DEFAULT 50,
        evidence        TEXT DEFAULT '',
        period_start    TEXT DEFAULT '',
        period_end      TEXT DEFAULT ''
    );

    CREATE INDEX IF NOT EXISTS idx_msnap_upload  ON market_snapshots(upload_id);
    CREATE INDEX IF NOT EXISTS idx_msnap_date    ON market_snapshots(snapshot_date);
    CREATE INDEX IF NOT EXISTS idx_change_type   ON change_events(change_type);
    CREATE INDEX IF NOT EXISTS idx_change_date   ON change_events(detected_at);
    CREATE INDEX IF NOT EXISTS idx_campaign_type ON campaigns(campaign_type);
    CREATE INDEX IF NOT EXISTS idx_compmov_comp  ON competitor_movements(competitor);
    CREATE INDEX IF NOT EXISTS idx_trend_dim     ON trend_signals(dimension, dimension_value);
    """)
    conn.commit()
    conn.close()


# ── Market Snapshot Generation ────────────────────────────────────────────────

def generate_market_snapshot(upload_id: str) -> dict:
    """
    Generate and persist a market snapshot for a given upload.
    Called automatically after every successful DDR upload.
    This is what enables trend analysis over time.
    """
    conn = get_db()
    ts   = datetime.datetime.utcnow().isoformat()

    # Get upload metadata
    upload = conn.execute("SELECT * FROM uploads WHERE id=?", (upload_id,)).fetchone()
    if not upload:
        conn.close()
        return {}
    snap_date = dict(upload).get("report_date") or ts[:10]

    # Get all opportunities for this upload
    opps  = conn.execute("SELECT * FROM opportunities WHERE upload_id=?", (upload_id,)).fetchall()
    comps = conn.execute("SELECT * FROM competitors   WHERE upload_id=?", (upload_id,)).fetchall()

    opps  = [dict(o) for o in opps]
    comps = [dict(c) for c in comps]

    # Compute distributions
    pl_dist   = Counter(o.get("product_line","") for o in opps)
    field_dist = Counter(o.get("field","")        for o in opps if o.get("field"))
    comp_dist  = Counter(c.get("normalized","")   for c in comps if c.get("normalized"))
    rigs      = list(set(o.get("rig","")  for o in opps if o.get("rig")))
    operators = list(set(o.get("field","") for o in opps if o.get("field")))  # field as proxy for operator region

    imm_opps   = sum(1 for o in opps if o.get("urgency") in ("immediate","5_days"))
    high_conf  = sum(1 for o in opps if o.get("confidence",0) >= 80)
    pipeline   = sum(o.get("estimated_value",0) for o in opps)
    wells      = list(set(o.get("well","") for o in opps if o.get("well")))

    # Activity intensity (0-100)
    intensity  = min(100, (
        len(rigs)   * 5 +
        imm_opps    * 8 +
        high_conf   * 3 +
        len(comps)  * 2
    ))
    comp_density = min(100, len(comps) * 6)
    opp_density  = min(100, len(opps) * 4)

    # Weighted pipeline (estimate — use 25% base win rate)
    weighted = round(pipeline * 0.25)

    snap_id = str(uuid.uuid4())
    conn.execute(
        """INSERT OR REPLACE INTO market_snapshots
           (id,upload_id,snapshot_date,generated_at,active_rigs,active_wells,
            active_fields,active_operators,total_opps,immediate_opps,high_conf_opps,
            pipeline_expected,pipeline_weighted,pl_distribution,field_distribution,
            comp_distribution,rig_list,operator_list,activity_intensity,
            competitor_density,opportunity_density)
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (snap_id, upload_id, snap_date, ts,
         len(rigs), len(wells), len(field_dist), len(operators),
         len(opps), imm_opps, high_conf,
         pipeline, weighted,
         json.dumps(dict(pl_dist.most_common(10))),
         json.dumps(dict(field_dist.most_common(10))),
         json.dumps(dict(comp_dist.most_common(10))),
         json.dumps(rigs[:20]),
         json.dumps(operators[:15]),
         intensity, comp_density, opp_density)
    )
    conn.commit()
    conn.close()
    return {"snapshot_id": snap_id, "upload_id": upload_id, "snapshot_date": snap_date,
            "active_rigs": len(rigs), "total_opps": len(opps), "intensity": intensity}


# ── Market Pulse (current state + period comparison) ─────────────────────────

def get_market_pulse() -> dict:
    """
    Calculate the current market pulse by comparing the latest snapshot
    to the previous snapshot. Returns percentage changes for every dimension.
    """
    conn = get_db()
    snaps = conn.execute(
        "SELECT * FROM market_snapshots ORDER BY generated_at DESC LIMIT 2"
    ).fetchall()
    conn.close()

    if not snaps:
        return {"status": "no_data", "message": "Upload DDR reports to generate market pulse."}

    current  = dict(snaps[0])
    previous = dict(snaps[1]) if len(snaps) > 1 else None

    def pct_change(cur, prev):
        if not prev or prev == 0: return None
        return round((cur - prev) / max(prev,1) * 100, 1)

    def deserialize(field, snap):
        try: return json.loads(snap.get(field,"{}") or "{}")
        except: return {}

    cur_pl    = deserialize("pl_distribution",   current)
    cur_field = deserialize("field_distribution", current)
    cur_comp  = deserialize("comp_distribution",  current)
    prev_pl   = deserialize("pl_distribution",   previous) if previous else {}
    prev_comp = deserialize("comp_distribution",  previous) if previous else {}

    # Top product lines with trend
    pl_trend = []
    for pl, count in sorted(cur_pl.items(), key=lambda x:-x[1]):
        prev_count = prev_pl.get(pl, 0)
        change = pct_change(count, prev_count)
        pl_trend.append({"product_line": pl, "count": count, "prev_count": prev_count,
                         "change_pct": change,
                         "direction": ("↑" if change and change>5 else "↓" if change and change<-5 else "→")})

    # Competitor changes
    comp_changes = []
    all_comps = set(list(cur_comp.keys()) + list(prev_comp.keys()))
    for comp in all_comps:
        cur_n  = cur_comp.get(comp,0)
        prev_n = prev_comp.get(comp,0)
        if cur_n != prev_n:
            comp_changes.append({
                "competitor": comp, "current": cur_n, "previous": prev_n,
                "change": cur_n - prev_n,
                "direction": "expanding" if cur_n > prev_n else "contracting",
            })

    # Market intensity vs previous
    intensity_change = pct_change(current["activity_intensity"],
                                  previous["activity_intensity"] if previous else None)

    return {
        "status": "live",
        "generated_at": datetime.datetime.utcnow().isoformat(),
        "current_period": current.get("snapshot_date",""),
        "previous_period": previous.get("snapshot_date","") if previous else None,
        "has_comparison": previous is not None,

        "metrics": {
            "active_rigs":      {"current": current["active_rigs"],
                                 "previous": previous["active_rigs"] if previous else None,
                                 "change_pct": pct_change(current["active_rigs"], previous["active_rigs"] if previous else None)},
            "active_fields":    {"current": current["active_fields"],
                                 "previous": previous["active_fields"] if previous else None,
                                 "change_pct": pct_change(current["active_fields"], previous["active_fields"] if previous else None)},
            "total_opps":       {"current": current["total_opps"],
                                 "previous": previous["total_opps"] if previous else None,
                                 "change_pct": pct_change(current["total_opps"], previous["total_opps"] if previous else None)},
            "immediate_opps":   {"current": current["immediate_opps"],
                                 "previous": previous["immediate_opps"] if previous else None,
                                 "change_pct": pct_change(current["immediate_opps"], previous["immediate_opps"] if previous else None)},
            "pipeline":         {"current": current["pipeline_expected"],
                                 "previous": previous["pipeline_expected"] if previous else None,
                                 "change_pct": pct_change(current["pipeline_expected"], previous["pipeline_expected"] if previous else None)},
            "activity_intensity":{"current": current["activity_intensity"],
                                   "previous": previous["activity_intensity"] if previous else None,
                                   "change_pct": intensity_change},
            "competitor_density":{"current": current["competitor_density"],
                                   "previous": previous["competitor_density"] if previous else None,
                                   "change_pct": pct_change(current["competitor_density"], previous["competitor_density"] if previous else None)},
        },

        "product_line_pulse":  pl_trend,
        "competitor_changes":  comp_changes,
        "current_rigs":        json.loads(current.get("rig_list","[]") or "[]"),
        "current_fields":      list(deserialize("field_distribution",current).keys()),
        "top_competitors":     sorted(cur_comp.items(), key=lambda x:-x[1])[:6],
    }


# ── Multi-DDR Market Aggregation ──────────────────────────────────────────────

def get_market_aggregates() -> dict:
    """
    Aggregate intelligence across ALL DDR uploads.
    This is the multi-DDR layer — insights only visible from many reports.
    """
    conn = get_db()

    all_opps  = conn.execute("SELECT * FROM opportunities").fetchall()
    all_comps = conn.execute("SELECT * FROM competitors").fetchall()
    all_snaps = conn.execute("SELECT * FROM market_snapshots ORDER BY snapshot_date ASC").fetchall()

    opps  = [dict(o) for o in all_opps]
    comps = [dict(c) for c in all_comps]
    snaps = [dict(s) for s in all_snaps]
    conn.close()

    if not opps:
        return {"status": "no_data"}

    # All-time market totals
    pl_total    = Counter(o.get("product_line","") for o in opps)
    field_total = Counter(o.get("field","")        for o in opps if o.get("field"))
    comp_total  = Counter(c.get("normalized","")   for c in comps if c.get("normalized"))
    rig_total   = Counter(o.get("rig","")          for o in opps if o.get("rig"))
    well_seen   = set(o.get("well","")             for o in opps if o.get("well"))

    # Unique entities
    unique_rigs   = len(rig_total)
    unique_fields = len(field_total)
    unique_comps  = len(comp_total)
    total_pipeline = sum(o.get("estimated_value",0) for o in opps)
    uploads_processed = len(set(o.get("upload_id","") for o in opps))

    # Cross-DDR: rigs that appear across multiple uploads (persistent activity)
    rig_upload_map = defaultdict(set)
    for o in opps:
        if o.get("rig") and o.get("upload_id"):
            rig_upload_map[o["rig"]].add(o["upload_id"])
    persistent_rigs = [r for r, ups in rig_upload_map.items() if len(ups) > 1]

    # Cross-DDR: competitors consistently active in specific fields
    comp_field_map = defaultdict(Counter)
    for c in comps:
        comp = c.get("normalized","")
        rig  = c.get("rig","")
        # Find field for this rig from opportunities
        field = next((o.get("field","") for o in opps
                      if o.get("rig") == rig and o.get("field")), "")
        if comp and field:
            comp_field_map[comp][field] += 1

    # Competitor strongholds (consistently dominant in a field)
    comp_strongholds = {}
    for comp, field_counts in comp_field_map.items():
        if field_counts:
            top_field, count = field_counts.most_common(1)[0]
            if count >= 2:
                comp_strongholds[comp] = {"field": top_field, "mentions": count}

    return {
        "status":              "aggregated",
        "uploads_processed":   uploads_processed,
        "total_opportunities": len(opps),
        "total_pipeline":      total_pipeline,
        "unique_rigs":         unique_rigs,
        "unique_fields":       unique_fields,
        "unique_wells":        len(well_seen),
        "unique_competitors":  unique_comps,
        "persistent_rigs":     persistent_rigs[:10],
        "top_product_lines":   pl_total.most_common(10),
        "top_fields":          field_total.most_common(8),
        "top_competitors":     comp_total.most_common(8),
        "top_rigs":            rig_total.most_common(10),
        "competitor_strongholds": comp_strongholds,
        "historical_snapshots": len(snaps),
    }


# ── Trend Signals ─────────────────────────────────────────────────────────────

def calculate_trend_signals() -> list:
    """
    Calculate market trends from historical snapshot data.
    Requires at least 2 snapshots to detect direction.
    Only generates signals with supporting evidence — never inferred.
    """
    conn = get_db()
    snaps = conn.execute(
        "SELECT * FROM market_snapshots ORDER BY snapshot_date ASC"
    ).fetchall()
    snaps = [dict(s) for s in snaps]
    conn.close()

    if len(snaps) < 2:
        return []

    signals = []
    ts = datetime.datetime.utcnow().isoformat()

    # ── Product line trends ───────────────────────────────────────────────────
    pl_history = defaultdict(list)
    for snap in snaps:
        try:
            pl_dist = json.loads(snap.get("pl_distribution","{}") or "{}")
        except: pl_dist = {}
        for pl, count in pl_dist.items():
            pl_history[pl].append((snap["snapshot_date"], count))

    for pl, history in pl_history.items():
        if len(history) < 2:
            continue
        counts  = [h[1] for h in history]
        first_h = sum(counts[:len(counts)//2]) / max(len(counts)//2, 1)
        last_h  = sum(counts[len(counts)//2:]) / max(len(counts) - len(counts)//2, 1)
        if first_h == 0: continue

        pct_change = (last_h - first_h) / first_h * 100

        if abs(pct_change) >= 20:
            direction = "growing" if pct_change > 0 else "declining"
            # Classify trend strength
            dp = len(history)
            trend_class = (
                "Sustained Trend"        if dp >= 5 and abs(pct_change) >= 30 else
                "Short-Term Spike"       if dp <= 2 and abs(pct_change) >= 40 else
                "Data Coverage Artifact" if dp == 1 else
                "Needs Review"           if dp < 3 else
                "Developing Trend"
            )
            signals.append({
                "dimension":          "product_line",
                "dimension_value":    pl,
                "direction":          direction,
                "magnitude":          round(pct_change, 1),
                "data_points":        dp,
                "unique_observations":dp,
                "confidence":         min(90, 40 + dp * 10),
                "trend_classification":trend_class,
                "evidence":           f"From avg {first_h:.0f} to {last_h:.0f} detections across {dp} reports",
                "period_start":       history[0][0],
                "period_end":         history[-1][0],
                "persistence":        "high" if dp >= 5 else "medium" if dp >= 3 else "low",
                "is_statistically_reliable": dp >= 3,
                "reliability_note":   f"Based on {dp} report(s). Minimum 3 recommended for reliable trend classification.",
            })

    # ── Rig count trend ───────────────────────────────────────────────────────
    if len(snaps) >= 3:
        rig_counts = [s["active_rigs"] for s in snaps]
        first_avg  = sum(rig_counts[:len(rig_counts)//2]) / max(len(rig_counts)//2, 1)
        last_avg   = sum(rig_counts[len(rig_counts)//2:]) / max(len(rig_counts)-len(rig_counts)//2, 1)
        if first_avg > 0:
            rig_pct = (last_avg - first_avg) / first_avg * 100
            if abs(rig_pct) >= 10:
                signals.append({
                    "dimension":       "market",
                    "dimension_value": "rig_count",
                    "direction":       "growing" if rig_pct > 0 else "declining",
                    "magnitude":       round(rig_pct, 1),
                    "data_points":     len(snaps),
                    "confidence":      min(85, 40 + len(snaps) * 8),
                    "evidence":        f"Active rig count {'+' if rig_pct>0 else ''}{rig_pct:.0f}% across {len(snaps)} reports",
                    "period_start":    snaps[0]["snapshot_date"],
                    "period_end":      snaps[-1]["snapshot_date"],
                })

    # ── Pipeline trend ────────────────────────────────────────────────────────
    pipeline_vals = [s["pipeline_expected"] for s in snaps if s["pipeline_expected"] > 0]
    if len(pipeline_vals) >= 2:
        first_p = sum(pipeline_vals[:len(pipeline_vals)//2]) / max(len(pipeline_vals)//2, 1)
        last_p  = sum(pipeline_vals[len(pipeline_vals)//2:]) / max(len(pipeline_vals)-len(pipeline_vals)//2,1)
        if first_p > 0:
            pip_pct = (last_p - first_p) / first_p * 100
            if abs(pip_pct) >= 10:
                signals.append({
                    "dimension":       "market",
                    "dimension_value": "pipeline_value",
                    "direction":       "growing" if pip_pct > 0 else "declining",
                    "magnitude":       round(pip_pct, 1),
                    "data_points":     len(pipeline_vals),
                    "confidence":      min(80, 35 + len(pipeline_vals) * 10),
                    "evidence":        f"Pipeline {'up' if pip_pct>0 else 'down'} {abs(pip_pct):.0f}% on recent vs earlier reports",
                    "period_start":    snaps[0]["snapshot_date"],
                    "period_end":      snaps[-1]["snapshot_date"],
                })

    # Persist signals
    if signals:
        conn = get_db()
        conn.execute("DELETE FROM trend_signals")  # Replace each recalculation
        for sig in signals:
            conn.execute(
                """INSERT INTO trend_signals
                   (id,calculated_at,dimension,dimension_value,direction,
                    magnitude,data_points,confidence,evidence,period_start,period_end)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (str(uuid.uuid4()), ts, sig["dimension"], sig["dimension_value"],
                 sig["direction"], sig["magnitude"], sig["data_points"],
                 sig["confidence"], sig["evidence"], sig["period_start"], sig["period_end"])
            )
        conn.commit()
        conn.close()

    return signals


def get_trend_signals(dimension: str = None) -> list:
    conn = get_db()
    q = "SELECT * FROM trend_signals WHERE 1=1"
    p = []
    if dimension:
        q += " AND dimension=?"; p.append(dimension)
    q += " ORDER BY magnitude DESC"
    rows = conn.execute(q, p).fetchall()
    conn.close()
    return [dict(r) for r in rows]
