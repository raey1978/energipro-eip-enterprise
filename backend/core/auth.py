"""
EIP DDR Intelligence v4.4 — Authentication & Security Core
JWT tokens, password hashing, role enforcement.
"""
import os, datetime
from typing import Optional
from fastapi import Depends, HTTPException, status, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from passlib.context import CryptContext
from core.database import get_db

# ── Config from environment ───────────────────────────────────────────────────
_raw_secret = os.environ.get("JWT_SECRET_KEY", "")
if not _raw_secret or len(_raw_secret) < 32:
    import logging as _log
    _log.getLogger("eip.security").critical(
        "INSECURE: JWT_SECRET_KEY is missing or too short. "
        "Set a 64-char random hex value in your .env file."
    )
    # Use a per-process random key as last resort (tokens invalidated on restart)
    import secrets as _sec
    _raw_secret = _sec.token_hex(32)
SECRET_KEY = _raw_secret
ALGORITHM      = os.environ.get("JWT_ALGORITHM", "HS256")
EXPIRE_MINUTES = int(os.environ.get("JWT_EXPIRE_MINUTES", "480"))

pwd_ctx  = CryptContext(schemes=["bcrypt"], deprecated="auto")
bearer   = HTTPBearer(auto_error=False)

# ── Role hierarchy ────────────────────────────────────────────────────────────
ROLES = ["super_admin", "admin", "commercial_manager", "product_line_manager", "viewer"]
ROLE_LABELS = {
    "super_admin":           "Super Admin",
    "admin":                 "Admin",
    "commercial_manager":    "Commercial Manager",
    "product_line_manager":  "Product Line Manager",
    "viewer":                "Viewer",
}

# Role → allowed actions (additive)
ROLE_PERMISSIONS = {
    "super_admin":          {"*"},                                   # all
    "admin":                {"upload","analyze","export","view","validate"},
    "commercial_manager":   {"view","validate","convert_lead","export"},
    "product_line_manager": {"view","validate"},
    "viewer":               {"view"},
}

def hash_password(plain: str) -> str:
    return pwd_ctx.hash(plain)

def verify_password(plain: str, hashed: str) -> bool:
    return pwd_ctx.verify(plain, hashed)

def create_token(user_id: str, email: str, role: str) -> str:
    expire = datetime.datetime.utcnow() + datetime.timedelta(minutes=EXPIRE_MINUTES)
    return jwt.encode(
        {"sub": user_id, "email": email, "role": role, "exp": expire},
        SECRET_KEY, algorithm=ALGORITHM
    )

def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired token.")

# ── Dependency: get current user from Bearer token ────────────────────────────
def get_current_user(
    creds: Optional[HTTPAuthorizationCredentials] = Depends(bearer)
) -> dict:
    if not creds:
        raise HTTPException(status_code=401, detail="Authentication required.")
    return decode_token(creds.credentials)

def require_role(*allowed_roles: str):
    """FastAPI dependency factory — restricts endpoint to specific roles.
    super_admin always has access. Other roles must be in allowed_roles.
    """
    def _check(user: dict = Depends(get_current_user)):
        role = user.get("role", "")
        if role == "super_admin":
            return user  # super_admin always allowed
        if role not in allowed_roles:
            raise HTTPException(status_code=403, detail="Insufficient permissions.")
        return user
    return _check

def require_permission(action: str):
    """Dependency: check role has permission for action."""
    def _check(user: dict = Depends(get_current_user)):
        role = user.get("role", "viewer")
        perms = ROLE_PERMISSIONS.get(role, {"view"})
        if "*" not in perms and action not in perms:
            raise HTTPException(status_code=403, detail=f"Role '{role}' cannot perform '{action}'.")
        return user
    return _check

# ── Optional auth: returns user or None (for public-readable endpoints) ───────
def optional_user(
    creds: Optional[HTTPAuthorizationCredentials] = Depends(bearer)
) -> Optional[dict]:
    if not creds:
        return None
    try:
        return decode_token(creds.credentials)
    except Exception:
        return None
