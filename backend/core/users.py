"""
EIP DDR Intelligence v4.4 — User Management
CRUD operations for users table.
"""
import uuid, datetime
from typing import Optional
from core.database import get_db
from core.auth import hash_password, verify_password, ROLES


def init_users_table():
    """Create users table if not exists."""
    conn = get_db()
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS users (
        id          TEXT PRIMARY KEY,
        email       TEXT UNIQUE NOT NULL,
        full_name   TEXT NOT NULL,
        role        TEXT NOT NULL DEFAULT 'viewer',
        password_hash TEXT NOT NULL,
        is_active   INTEGER NOT NULL DEFAULT 1,
        created_at  TEXT,
        updated_at  TEXT,
        last_login  TEXT,
        must_change_password INTEGER NOT NULL DEFAULT 0
    );
    CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);
    """)
    conn.commit()
    conn.close()


def get_user_by_email(email: str) -> Optional[dict]:
    conn = get_db()
    row = conn.execute("SELECT * FROM users WHERE email=? AND is_active=1", (email.lower(),)).fetchone()
    conn.close()
    return dict(row) if row else None


def get_user_by_id(user_id: str) -> Optional[dict]:
    conn = get_db()
    row = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def list_users() -> list:
    conn = get_db()
    rows = conn.execute("SELECT id,email,full_name,role,is_active,created_at,last_login FROM users ORDER BY created_at DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def create_user(email: str, full_name: str, role: str, password: str, must_change_password: bool = False) -> dict:
    if role not in ROLES:
        raise ValueError(f"Invalid role: {role}")
    uid = str(uuid.uuid4())
    ts  = datetime.datetime.utcnow().isoformat()
    ph  = hash_password(password)
    conn = get_db()
    conn.execute(
        "INSERT INTO users(id,email,full_name,role,password_hash,is_active,created_at,updated_at,must_change_password) VALUES(?,?,?,?,?,1,?,?,?)",
        (uid, email.lower(), full_name, role, ph, ts, ts, 1 if must_change_password else 0)
    )
    conn.commit()
    conn.close()
    return {"id": uid, "email": email.lower(), "full_name": full_name, "role": role}


def update_user(user_id: str, updates: dict) -> Optional[dict]:
    allowed = {"full_name", "role", "is_active"}
    conn = get_db()
    ts = datetime.datetime.utcnow().isoformat()
    for k, v in updates.items():
        if k in allowed:
            conn.execute(f"UPDATE users SET {k}=?, updated_at=? WHERE id=?", (v, ts, user_id))
    conn.commit()
    row = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def change_password(user_id: str, new_password: str, clear_must_change: bool = False) -> bool:
    ph  = hash_password(new_password)
    ts  = datetime.datetime.utcnow().isoformat()
    conn = get_db()
    if clear_must_change:
        conn.execute("UPDATE users SET password_hash=?, updated_at=?, must_change_password=0 WHERE id=?", (ph, ts, user_id))
    else:
        conn.execute("UPDATE users SET password_hash=?, updated_at=? WHERE id=?", (ph, ts, user_id))
    conn.commit()
    conn.close()
    return True


def record_login(user_id: str):
    ts = datetime.datetime.utcnow().isoformat()
    conn = get_db()
    conn.execute("UPDATE users SET last_login=? WHERE id=?", (ts, user_id))
    conn.commit()
    conn.close()


def authenticate(email: str, password: str) -> Optional[dict]:
    user = get_user_by_email(email)
    if not user:
        return None
    if not verify_password(password, user["password_hash"]):
        return None
    record_login(user["id"])
    return user


def seed_admin(email: str, password: str):
    """Create super admin on first run if no users exist."""
    conn = get_db()
    count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    conn.close()
    if count == 0:
        create_user(email, "System Administrator", "super_admin", password)
        print(f"[EIP] Bootstrap: super admin created → {email}")
