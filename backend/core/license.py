"""
EnergiPro – Trial / Licensing Gate
────────────────────────────────────────────────────────────────────────────
Every trial package embeds a unique EIP_LICENSE_ID (set in backend/.env at
build time). This module enforces two independent, complementary safeguards
so a trial install can never quietly turn into a free permanent one:

  1. LOCAL HARD EXPIRY — works fully offline, zero dependency on us.
     The first time this instance ever starts, its first-run timestamp is
     written to the local database. EIP_TRIAL_DAYS (default 14) days after
     that, the instance locks itself automatically. No network required.

  2. REMOTE KILL-SWITCH — best-effort, needs occasional internet.
     On a low-frequency schedule this instance checks a small, public,
     read-only JSON file (EIP_LICENSE_CHECK_URL) for its license_id's status:
        "trial"   – normal trial, still subject to the local expiry above
        "active"  – client has paid; trial restrictions are lifted entirely
        "revoked" – EnergiPro Solutions has switched this client off; the
                    instance locks immediately, regardless of days remaining
     The last known-good remote result is cached locally (in the same DB
     row) so a client who is briefly offline is never falsely locked out.
     If the remote check can never be reached at all, the local 14-day
     expiry above is still fully enforced — this is deliberately NOT a
     "must-phone-home-to-run" design, so the trial always works for a
     legitimate client with normal intermittent internet.

Nothing about a client's uploaded DDR/LMR data is ever sent by this check —
only the license_id itself (a meaningless string with no client content).
"""
import os, json, datetime, logging, urllib.request

from core.database import get_db

logger = logging.getLogger("eip.license")

TRIAL_DAYS              = int(os.environ.get("EIP_TRIAL_DAYS", "14"))
LICENSE_ID              = os.environ.get("EIP_LICENSE_ID", "").strip() or "UNMANAGED-LOCAL"
LICENSE_CHECK_URL       = os.environ.get("EIP_LICENSE_CHECK_URL", "").strip()
REMOTE_CHECK_INTERVAL_S = 6 * 3600     # re-check the remote file at most every 6 hours
REMOTE_TIMEOUT_S        = 4

# Paths that must always work, even when locked — health probes, and the
# status endpoint the frontend itself needs in order to show the lock screen.
EXEMPT_PATHS = {"/health", "/api/health", "/api/ready", "/api/live", "/api/license/status"}

# In-process cache so a busy instance doesn't hit the network (or DB) on
# every single request — only once per REMOTE_CHECK_INTERVAL_S.
_cache = {"checked_at": None, "remote_status": None}


def init_license_table():
    conn = get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS license_state (
            license_id TEXT PRIMARY KEY,
            first_run_at TEXT NOT NULL,
            last_remote_status TEXT DEFAULT '',
            last_remote_checked_at TEXT DEFAULT ''
        )
    """)
    conn.commit()
    conn.close()


def _get_or_create_state():
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM license_state WHERE license_id = ?", (LICENSE_ID,)
    ).fetchone()
    if row is None:
        now = datetime.datetime.utcnow().isoformat() + "Z"
        conn.execute(
            "INSERT INTO license_state (license_id, first_run_at) VALUES (?, ?)",
            (LICENSE_ID, now),
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM license_state WHERE license_id = ?", (LICENSE_ID,)
        ).fetchone()
    conn.close()
    return dict(row)


def _persist_remote_status(status: str):
    conn = get_db()
    now = datetime.datetime.utcnow().isoformat() + "Z"
    conn.execute(
        "UPDATE license_state SET last_remote_status = ?, last_remote_checked_at = ? "
        "WHERE license_id = ?",
        (status, now, LICENSE_ID),
    )
    conn.commit()
    conn.close()


def _fetch_remote_status():
    """Best-effort remote check. Returns 'trial'/'active'/'revoked', or None on
    any failure (offline, DNS, timeout, malformed JSON, unknown license_id) —
    callers must treat None as 'could not determine, fall back to last known'."""
    if not LICENSE_CHECK_URL:
        return None
    try:
        req = urllib.request.Request(
            LICENSE_CHECK_URL, headers={"User-Agent": "EnergiPro-License-Check/1.0"}
        )
        with urllib.request.urlopen(req, timeout=REMOTE_TIMEOUT_S) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        entry = data.get(LICENSE_ID)
        if not entry:
            return None  # unknown license_id in the file — don't punish for that
        status = str(entry.get("status", "trial")).lower()
        if status not in ("trial", "active", "revoked"):
            return None
        return status
    except Exception as e:
        logger.info("license_remote_check_failed", extra={"error": str(e)[:150]})
        return None


def check_license() -> dict:
    """
    Main entry point — cheap to call on every request. Only hits the network
    (and does a DB write) at most once per REMOTE_CHECK_INTERVAL_S.
    Returns: {locked, status, days_remaining, message}
    """
    state = _get_or_create_state()
    now = datetime.datetime.utcnow()

    stale = (
        _cache["checked_at"] is None
        or (now - _cache["checked_at"]).total_seconds() > REMOTE_CHECK_INTERVAL_S
    )
    if stale:
        remote = _fetch_remote_status()
        _cache["checked_at"] = now
        if remote is not None:
            _cache["remote_status"] = remote
            _persist_remote_status(remote)

    # Resolve status to use: fresh remote > cached remote (this process) >
    # last known-good from DB (survives restarts/offline) > default "trial".
    status = _cache["remote_status"] or state.get("last_remote_status") or "trial"

    first_run_at = datetime.datetime.fromisoformat(state["first_run_at"].replace("Z", ""))
    days_elapsed = max(0, (now - first_run_at).days)
    days_remaining = max(0, TRIAL_DAYS - days_elapsed)

    if status == "revoked":
        return {
            "locked": True,
            "status": "revoked",
            "days_remaining": 0,
            "message": "This trial has been deactivated by EnergiPro Solutions. "
                       "Contact us to reactivate or to purchase a full license.",
        }

    if status == "active":
        return {
            "locked": False,
            "status": "active",
            "days_remaining": None,
            "message": "Licensed.",
        }

    # status == "trial" (or unknown/never reached)
    if days_elapsed >= TRIAL_DAYS:
        return {
            "locked": True,
            "status": "trial_expired",
            "days_remaining": 0,
            "message": f"Your {TRIAL_DAYS}-day trial has ended. "
                       "Contact EnergiPro Solutions to activate your license.",
        }
    return {
        "locked": False,
        "status": "trial",
        "days_remaining": days_remaining,
        "message": f"Trial — {days_remaining} day(s) remaining.",
    }
