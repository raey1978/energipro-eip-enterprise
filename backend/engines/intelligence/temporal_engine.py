"""
EIP v6.3A — Temporal State Engine

Detects meaningful entity state transitions from historical observations.
Suppresses duplicate signals (same rig, same state, different upload = NOT a new event).

Core rule:
  Rig AD-73: Drilling(DDR1) → Drilling(DDR2) → Drilling(DDR3) → Completion(DDR4)
  → ONE transition event: Drilling → Completion (at DDR4)
  → NOT four "rig activity" events

Change signal classification:
  NEW_CHANGE       — first time this specific state is observed for this entity
  CONFIRMED        — same state as previous observation (no new event)
  MEANINGFUL_TRANSITION — state changed from previous (one event, not one per DDR)
  REVERSAL         — state returned to a previous value
  TEMPORARY_SIGNAL — appeared once then reverted (needs review)
  DUPLICATE        — identical to already-stored change event for this entity
"""
from __future__ import annotations
import uuid, datetime, json
from typing import Optional
from core.database import get_db

# ── State vocabulary ──────────────────────────────────────────────────────────
# Ordered lifecycle — later index = more advanced stage
RIG_LIFECYCLE_ORDER = [
    "spud", "drilling", "coring", "logging", "wireline",
    "completion", "total_depth", "td", "workover", "testing",
    "abandonment", "idle", "suspended", "mobilising", "demobilised"
]

URGENCY_TO_STATE = {
    "immediate": "drilling",
    "5_days":    "drilling",
    "7_days":    "active",
    "30_days":   "planned",
    "future":    "planned",
}

# How many consecutive observations confirm a transition?
CONFIRMATION_THRESHOLD = 2


# ── Temporal state detection ──────────────────────────────────────────────────

def get_entity_state_history(master_entity_id: str) -> list:
    """
    Return ordered observation history for an entity.
    Each entry: {upload_id, report_date, state, field, well, confidence}
    """
    conn = get_db()
    rows = conn.execute(
        """SELECT eo.*, u.report_date as rpt_date
           FROM entity_observations eo
           LEFT JOIN uploads u ON u.id=eo.upload_id
           WHERE eo.master_entity_id=?
           ORDER BY COALESCE(eo.report_date, u.report_date, eo.created_at) ASC""",
        (master_entity_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def detect_entity_transitions(master_entity_id: str, entity_type: str) -> list:
    """
    Analyse observation history and return only MEANINGFUL transitions.
    Suppresses: duplicate uploads of same state, noise fluctuations.
    Returns list of {from_state, to_state, date, confirmed_by, upload_id}
    """
    history = get_entity_state_history(master_entity_id)
    if len(history) < 2:
        return []

    transitions = []
    prev_state  = None
    prev_date   = None

    for obs in history:
        state = _extract_state(obs, entity_type)
        date  = obs.get("report_date") or obs.get("rpt_date") or obs.get("created_at","")[:10]

        if prev_state is None:
            prev_state = state
            prev_date  = date
            continue

        if state == prev_state:
            # Same state — update confirmation date, no new event
            prev_date = date
            continue

        # State changed — record ONE transition
        if _is_meaningful_transition(prev_state, state, entity_type):
            transitions.append({
                "from_state":   prev_state,
                "to_state":     state,
                "detected_at":  date,
                "first_upload": obs.get("upload_id",""),
                "transition_type": _classify_transition(prev_state, state),
                "master_entity_id": master_entity_id,
            })

        prev_state = state
        prev_date  = date

    return transitions


def _extract_state(obs: dict, entity_type: str) -> str:
    """Extract a normalised state string from an observation."""
    raw = (obs.get("observed_state","") or "").lower().strip()

    # Map urgency-based states for rigs
    if entity_type == "rig":
        state = URGENCY_TO_STATE.get(raw, raw)
        # Also check product_line for lifecycle hint
        pl = (obs.get("product_line","") or "").lower()
        if "completion" in pl: return "completion"
        if "wireline" in pl or "logging" in pl: return "logging"
        if "well testing" in pl: return "testing"
        if "fishing" in pl: return "intervention"
        return state or "drilling"  # default active rig = drilling

    elif entity_type == "competitor":
        return obs.get("observed_state","active") or "active"

    return raw or "active"


def _is_meaningful_transition(from_state: str, to_state: str, entity_type: str) -> bool:
    """Filter out noise — only meaningful state changes."""
    if from_state == to_state: return False

    # Both unknown/empty = not meaningful
    if not from_state or not to_state: return False

    # For rigs: must be a recognised lifecycle change
    if entity_type == "rig":
        known = set(RIG_LIFECYCLE_ORDER)
        return from_state in known or to_state in known

    return True


def _classify_transition(from_state: str, to_state: str) -> str:
    """Classify the nature of a state transition."""
    if from_state in RIG_LIFECYCLE_ORDER and to_state in RIG_LIFECYCLE_ORDER:
        fi = RIG_LIFECYCLE_ORDER.index(from_state) if from_state in RIG_LIFECYCLE_ORDER else -1
        ti = RIG_LIFECYCLE_ORDER.index(to_state)   if to_state   in RIG_LIFECYCLE_ORDER else -1
        if fi >= 0 and ti >= 0:
            if ti > fi: return "progression"   # Moving forward in lifecycle
            if ti < fi: return "reversal"       # Going back (unusual)
    if to_state in ("idle","suspended","demobilised"): return "deactivation"
    if from_state in ("idle","suspended","demobilised"): return "reactivation"
    return "state_change"


# ── Deduplication Engine ──────────────────────────────────────────────────────

def init_temporal_tables():
    conn = get_db()
    conn.executescript("""
    -- Persistent entity states — current authoritative state per master entity
    CREATE TABLE IF NOT EXISTS entity_states (
        id                  TEXT PRIMARY KEY,
        master_entity_id    TEXT NOT NULL UNIQUE,
        entity_type         TEXT NOT NULL,
        current_state       TEXT DEFAULT '',
        previous_state      TEXT DEFAULT '',
        state_since_date    TEXT DEFAULT '',
        state_since_upload  TEXT DEFAULT '',
        confirmed_count     INTEGER DEFAULT 1,  -- how many obs confirm current state
        transition_count    INTEGER DEFAULT 0,  -- total meaningful transitions seen
        is_confirmed        INTEGER DEFAULT 0,  -- confirmed by ≥ CONFIRMATION_THRESHOLD obs
        last_updated        TEXT NOT NULL,
        FOREIGN KEY(master_entity_id) REFERENCES master_entities(id)
    );

    -- Deduplication log — tracks which change events have already been filed
    CREATE TABLE IF NOT EXISTS change_dedup_log (
        id              TEXT PRIMARY KEY,
        master_entity_id TEXT NOT NULL,
        change_fingerprint TEXT NOT NULL UNIQUE,  -- hash(entity_id+from_state+to_state)
        change_event_id TEXT DEFAULT '',
        first_detected  TEXT NOT NULL,
        last_confirmed  TEXT NOT NULL,
        confirmation_count INTEGER DEFAULT 1,
        suppressed_count   INTEGER DEFAULT 0,     -- how many duplicates were suppressed
        status          TEXT DEFAULT 'active'    -- active|superseded|reversed
    );

    -- Validated change events — with human classification
    CREATE TABLE IF NOT EXISTS change_validations (
        id              TEXT PRIMARY KEY,
        change_event_id TEXT NOT NULL,
        master_entity_id TEXT DEFAULT '',
        validation_type TEXT NOT NULL,  -- true_positive|false_positive|duplicate|delayed|missed|needs_review
        validated_by    TEXT DEFAULT '',
        validated_at    TEXT NOT NULL,
        notes           TEXT DEFAULT ''
    );

    CREATE INDEX IF NOT EXISTS idx_es_entity ON entity_states(master_entity_id);
    CREATE INDEX IF NOT EXISTS idx_dedup_fp  ON change_dedup_log(change_fingerprint);
    CREATE INDEX IF NOT EXISTS idx_cv_event  ON change_validations(change_event_id);
    """)
    conn.commit()
    conn.close()


def update_entity_state(
    master_entity_id: str,
    entity_type: str,
    new_state: str,
    upload_id: str,
    report_date: str,
) -> dict:
    """
    Update the entity state machine. Returns what happened:
    NEW_STATE / CONFIRMED / TRANSITION / SUPPRESSED
    """
    conn    = get_db()
    ts      = datetime.datetime.utcnow().isoformat()
    row     = conn.execute(
        "SELECT * FROM entity_states WHERE master_entity_id=?", (master_entity_id,)
    ).fetchone()

    result = {}

    if not row:
        # First observation — create state record
        conn.execute(
            """INSERT INTO entity_states
               (id,master_entity_id,entity_type,current_state,previous_state,
                state_since_date,state_since_upload,confirmed_count,transition_count,
                is_confirmed,last_updated)
               VALUES(?,?,?,?,?,?,?,1,0,0,?)""",
            (str(uuid.uuid4()), master_entity_id, entity_type,
             new_state, "", report_date, upload_id, ts)
        )
        result = {"status": "NEW_STATE", "state": new_state}

    else:
        d = dict(row)
        current = d.get("current_state","")

        if current == new_state:
            # Confirmed — increment count
            confirmed = d.get("confirmed_count",1) + 1
            is_conf   = 1 if confirmed >= CONFIRMATION_THRESHOLD else 0
            conn.execute(
                "UPDATE entity_states SET confirmed_count=?, is_confirmed=?, last_updated=? WHERE master_entity_id=?",
                (confirmed, is_conf, ts, master_entity_id)
            )
            result = {"status": "CONFIRMED", "state": current, "confirmed_count": confirmed}

        else:
            # State transition — check dedup
            fingerprint = f"{master_entity_id}:{current}→{new_state}"
            dup = conn.execute(
                "SELECT id, suppressed_count FROM change_dedup_log WHERE change_fingerprint=? AND status='active'",
                (fingerprint,)
            ).fetchone()

            if dup:
                # Already logged this exact transition — suppress duplicate
                conn.execute(
                    "UPDATE change_dedup_log SET suppressed_count=suppressed_count+1, last_confirmed=? WHERE id=?",
                    (ts, dup[0])
                )
                result = {"status": "DUPLICATE_SUPPRESSED", "from": current, "to": new_state,
                          "suppressed_count": (dup[1] or 0) + 1}
            else:
                # Genuine new transition
                conn.execute(
                    """INSERT INTO change_dedup_log
                       (id,master_entity_id,change_fingerprint,first_detected,last_confirmed,
                        confirmation_count,suppressed_count,status)
                       VALUES(?,?,?,?,?,1,0,'active')""",
                    (str(uuid.uuid4()), master_entity_id, fingerprint, ts, ts)
                )
                conn.execute(
                    """UPDATE entity_states
                       SET previous_state=?, current_state=?, state_since_date=?,
                           state_since_upload=?, confirmed_count=1, transition_count=transition_count+1,
                           is_confirmed=0, last_updated=?
                       WHERE master_entity_id=?""",
                    (current, new_state, report_date, upload_id, ts, master_entity_id)
                )
                result = {"status": "TRANSITION", "from": current, "to": new_state,
                          "entity_id": master_entity_id}

    conn.commit()
    conn.close()
    return result


def get_entity_current_state(master_entity_id: str) -> dict:
    """Return the current authoritative state for an entity."""
    conn = get_db()
    row  = conn.execute(
        "SELECT * FROM entity_states WHERE master_entity_id=?", (master_entity_id,)
    ).fetchone()
    conn.close()
    return dict(row) if row else {}


def get_all_entity_states(entity_type: str = None, limit: int = 100) -> list:
    conn = get_db()
    q = """SELECT es.*, me.canonical_name, me.observation_count
           FROM entity_states es
           JOIN master_entities me ON me.id=es.master_entity_id
           WHERE 1=1"""
    p = []
    if entity_type: q += " AND es.entity_type=?"; p.append(entity_type)
    q += " ORDER BY me.observation_count DESC LIMIT ?"; p.append(limit)
    rows = conn.execute(q, p).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── Change validation metrics ─────────────────────────────────────────────────

def validate_change_event(
    change_event_id: str,
    validation_type: str,
    master_entity_id: str = "",
    user_email: str = "",
    notes: str = "",
) -> dict:
    """Record a human validation of a change event."""
    valid_types = {"true_positive","false_positive","duplicate","delayed","missed","needs_review"}
    if validation_type not in valid_types:
        raise ValueError(f"validation_type must be one of {valid_types}")

    conn = get_db()
    vid  = str(uuid.uuid4())
    ts   = datetime.datetime.utcnow().isoformat()
    conn.execute(
        """INSERT INTO change_validations
           (id,change_event_id,master_entity_id,validation_type,validated_by,validated_at,notes)
           VALUES(?,?,?,?,?,?,?)""",
        (vid, change_event_id, master_entity_id, validation_type, user_email, ts, notes)
    )
    conn.commit(); conn.close()
    return {"validation_id": vid, "change_event_id": change_event_id, "type": validation_type}


def calculate_change_detection_metrics() -> dict:
    """
    Calculate precision, recall, FP rate from human-validated change events.
    Returns 'not_yet_measured' if no validated events exist.
    """
    conn = get_db()
    validations = conn.execute("SELECT validation_type, COUNT(*) n FROM change_validations GROUP BY validation_type").fetchall()
    total_validated = conn.execute("SELECT COUNT(*) FROM change_validations").fetchone()[0]
    total_change_events = conn.execute("SELECT COUNT(*) FROM change_events").fetchone()[0]
    suppressed = conn.execute("SELECT SUM(suppressed_count) FROM change_dedup_log").fetchone()[0] or 0
    conn.close()

    if total_validated == 0:
        return {
            "status": "not_yet_measured",
            "message": "Accuracy not yet measured — requires reviewed signals.",
            "instructions": "Open the What Changed? page and classify each event as True/False Positive.",
            "total_change_events": total_change_events,
            "total_validated": 0,
            "suppressed_duplicates": suppressed,
        }

    counts = {v[0]: v[1] for v in validations}
    tp  = counts.get("true_positive", 0)
    fp  = counts.get("false_positive", 0)
    dup = counts.get("duplicate", 0)
    delayed = counts.get("delayed", 0)

    precision  = round(tp / max(tp + fp, 1), 3)
    dup_rate   = round((fp + dup) / max(total_validated, 1), 3)

    return {
        "status":             "measured",
        "total_change_events":total_change_events,
        "total_validated":    total_validated,
        "true_positives":     tp,
        "false_positives":    fp,
        "duplicates_found":   dup,
        "delayed_detections": delayed,
        "precision":          precision,
        "duplicate_rate":     dup_rate,
        "suppressed_automatically": suppressed,
        "pct_validated":      round(total_validated / max(total_change_events, 1) * 100, 1),
        "note": "Recall cannot be calculated without a ground-truth list of all real changes.",
    }
