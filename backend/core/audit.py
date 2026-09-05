"""
EIP DDR Intelligence v4.4 — Audit Log
Immutable record of all security-relevant actions.
"""
import uuid, datetime
from core.database import get_db


AUDIT_EVENTS = {
    "LOGIN":              "User logged in",
    "LOGOUT":             "User logged out",
    "LOGIN_FAILED":       "Failed login attempt",
    "DDR_UPLOAD":         "DDR file uploaded",
    "DDR_CLEAR":          "All DDR data cleared",
    "ANALYSIS_RUN":       "Intelligence analysis executed",
    "OPP_STATUS_CHANGE":  "Opportunity status updated",
    "OPP_VALIDATED":      "Opportunity validated",
    "LEAD_CREATED":       "Opportunity converted to lead",
    "EXPORT_EXCEL":       "Excel export downloaded",
    "EXPORT_PDF":         "PDF brief exported",
    "USER_CREATED":       "New user created",
    "USER_UPDATED":       "User profile updated",
    "USER_DEACTIVATED":   "User deactivated",
    "PASSWORD_CHANGED":   "Password changed",
    "ROLE_CHANGED":       "User role changed",
    "SETTINGS_CHANGED":   "System settings updated",
}


def init_audit_table():
    conn = get_db()
    conn.execute("""
    CREATE TABLE IF NOT EXISTS audit_log (
        id          TEXT PRIMARY KEY,
        ts          TEXT NOT NULL,
        event_type  TEXT NOT NULL,
        user_id     TEXT,
        user_email  TEXT,
        user_role   TEXT,
        detail      TEXT,
        ip_address  TEXT,
        resource_id TEXT
    )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit_log(ts)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_user ON audit_log(user_id)")
    conn.commit()
    conn.close()


def log_event(
    event_type: str,
    user_id: str = None,
    user_email: str = None,
    user_role: str = None,
    detail: str = None,
    ip_address: str = None,
    resource_id: str = None,
):
    conn = get_db()
    conn.execute(
        "INSERT INTO audit_log(id,ts,event_type,user_id,user_email,user_role,detail,ip_address,resource_id) VALUES(?,?,?,?,?,?,?,?,?)",
        (str(uuid.uuid4()), datetime.datetime.utcnow().isoformat(),
         event_type, user_id, user_email, user_role, detail, ip_address, resource_id)
    )
    conn.commit()
    conn.close()


def get_audit_log(limit=200, offset=0, event_type=None, user_id=None):
    conn = get_db()
    q = "SELECT * FROM audit_log WHERE 1=1"
    p = []
    if event_type:
        q += " AND event_type=?"
        p.append(event_type)
    if user_id:
        q += " AND user_id=?"
        p.append(user_id)
    q += " ORDER BY ts DESC LIMIT ? OFFSET ?"
    p += [limit, offset]
    rows = conn.execute(q, p).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def audit_from_request(request, event_type: str, user: dict = None, detail: str = None, resource_id: str = None):
    """Convenience: log event with request context."""
    ip = request.client.host if request.client else "unknown"
    log_event(
        event_type=event_type,
        user_id=user.get("sub") if user else None,
        user_email=user.get("email") if user else None,
        user_role=user.get("role") if user else None,
        detail=detail,
        ip_address=ip,
        resource_id=resource_id,
    )
