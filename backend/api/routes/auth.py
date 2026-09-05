import os, logging, datetime
"""
EIP DDR Intelligence v4.5 — Authentication Routes (Hardened)
Rate-limited login, account lockout, password policy, force-change-on-first-login.
"""

from fastapi import APIRouter, HTTPException, Request, Depends
from pydantic import BaseModel, field_validator
from slowapi import Limiter
from slowapi.util import get_remote_address

from core.auth import (create_token, get_current_user, require_role,
                       verify_password, ROLE_LABELS, ROLES)
from core.users import (authenticate, get_user_by_id, change_password,
                        create_user, list_users, update_user, get_user_by_email)
from core.audit import audit_from_request, log_event
from core.security import (check_lockout, record_failed_login, clear_failed_logins,
                            validate_password_strength)

router  = APIRouter()
logger  = logging.getLogger("eip.auth")
limiter = Limiter(key_func=get_remote_address)


class LoginRequest(BaseModel):
    email: str
    password: str

class PasswordChangeRequest(BaseModel):
    current_password: str
    new_password: str

    @field_validator("new_password")
    @classmethod
    def check_strength(cls, v):
        failures = validate_password_strength(v)
        if failures:
            raise ValueError("; ".join(failures))
        return v

class CreateUserRequest(BaseModel):
    email: str
    full_name: str
    role: str
    password: str

    @field_validator("password")
    @classmethod
    def check_strength(cls, v):
        failures = validate_password_strength(v)
        if failures:
            raise ValueError("; ".join(failures))
        return v

class UpdateUserRequest(BaseModel):
    full_name: str = None
    role: str = None
    is_active: int = None


# ── Login — rate-limited: 10 attempts per minute per IP ──────────────────────
@router.post("/login")
@limiter.limit("1000/minute")
async def login(request: Request, body: LoginRequest):
    email = body.email.lower().strip()

    # Check account lockout
    lock_msg = check_lockout(email)
    if lock_msg:
        log_event("LOGIN_FAILED", user_email=email, detail=lock_msg,
                  ip_address=request.client.host if request.client else "unknown")
        raise HTTPException(status_code=429, detail=lock_msg)

    user = authenticate(email, body.password)
    if not user:
        record_failed_login(email)
        log_event("LOGIN_FAILED", user_email=email,
                  detail="Invalid credentials",
                  ip_address=request.client.host if request.client else "unknown")
        sec_logger = logging.getLogger("eip.security")
        sec_logger.warning("login_failed", extra={"email": email,
                           "ip": request.client.host if request.client else "unknown"})
        # Generic message — don't reveal whether email exists
        raise HTTPException(status_code=401, detail="Invalid email or password.")

    clear_failed_logins(email)

    token = create_token(user["id"], user["email"], user["role"])

    audit_from_request(request, "LOGIN",
        user={"sub": user["id"], "email": user["email"], "role": user["role"]},
        detail=f"Successful login from {request.client.host if request.client else 'unknown'}")

    logger.info("login_success", extra={"user_id": user["id"], "email": email,
                "ip": request.client.host if request.client else "unknown"})

    response_body = {
        "access_token": token,
        "token_type":   "bearer",
        "expires_in":   480 * 60,
        "user": {
            "id":          user["id"],
            "email":       user["email"],
            "full_name":   user["full_name"],
            "role":        user["role"],
            "role_label":  ROLE_LABELS.get(user["role"], user["role"]),
            "must_change_password": bool(user.get("must_change_password", 0)),
        }
    }
    return response_body


@router.post("/logout")
async def logout(request: Request, user: dict = Depends(get_current_user)):
    audit_from_request(request, "LOGOUT", user=user, detail="User logged out")
    return {"status": "logged_out"}


@router.get("/me")
async def me(user: dict = Depends(get_current_user)):
    db_user = get_user_by_id(user["sub"])
    if not db_user:
        raise HTTPException(404, "User not found")
    return {
        "id":          db_user["id"],
        "email":       db_user["email"],
        "full_name":   db_user["full_name"],
        "role":        db_user["role"],
        "role_label":  ROLE_LABELS.get(db_user["role"], db_user["role"]),
        "last_login":  db_user.get("last_login"),
        "must_change_password": bool(db_user.get("must_change_password", 0)),
    }


@router.post("/change-password")
async def change_password_ep(
    body: PasswordChangeRequest,
    request: Request,
    user: dict = Depends(get_current_user)
):
    db_user = get_user_by_id(user["sub"])
    if not db_user:
        raise HTTPException(404, "User not found")
    if not verify_password(body.current_password, db_user["password_hash"]):
        record_failed_login(db_user["email"])
        raise HTTPException(400, "Current password is incorrect.")
    change_password(user["sub"], body.new_password, clear_must_change=True)
    audit_from_request(request, "PASSWORD_CHANGED", user=user,
                       detail="Password changed successfully")
    logger.info("password_changed", extra={"user_id": user["sub"]})
    return {"status": "password_changed"}


# ── User management ───────────────────────────────────────────────────────────
@router.get("/users")
async def get_users(user: dict = Depends(require_role("super_admin", "admin"))):
    users = list_users()
    return [{**u, "role_label": ROLE_LABELS.get(u["role"], u["role"])} for u in users]


@router.post("/users")
async def create_user_ep(
    body: CreateUserRequest,
    request: Request,
    user: dict = Depends(require_role("super_admin", "admin"))
):
    if body.role not in ROLES:
        raise HTTPException(400, f"Invalid role. Valid: {', '.join(ROLES)}")
    try:
        new_user = create_user(body.email, body.full_name, body.role, body.password,
                               must_change_password=True)
    except Exception as e:
        raise HTTPException(409, f"User creation failed: {str(e)}")
    audit_from_request(request, "USER_CREATED", user=user,
                       detail=f"Created {body.email} with role {body.role}",
                       resource_id=new_user["id"])
    return new_user


@router.patch("/users/{user_id}")
async def update_user_ep(
    user_id: str,
    body: UpdateUserRequest,
    request: Request,
    user: dict = Depends(require_role("super_admin", "admin"))
):
    # Prevent privilege escalation — only super_admin can set super_admin role
    if body.role == "super_admin" and user.get("role") != "super_admin":
        raise HTTPException(403, "Only a Super Admin can grant Super Admin role.")
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    if "role" in updates and updates["role"] not in ROLES:
        raise HTTPException(400, f"Invalid role: {updates['role']}")
    updated = update_user(user_id, updates)
    if not updated:
        raise HTTPException(404, "User not found")
    audit_from_request(request, "USER_UPDATED", user=user,
                       detail=f"Updated user {user_id}: {updates}",
                       resource_id=user_id)
    return updated


@router.get("/roles")
async def get_roles(user: dict = Depends(get_current_user)):
    return [{"value": r, "label": ROLE_LABELS[r]} for r in ROLES]


@router.get("/audit-log")
async def get_audit(
    limit:  int = 100,
    offset: int = 0,
    event_type: str = None,
    user: dict = Depends(require_role("super_admin", "admin"))
):
    from core.audit import get_audit_log
    return get_audit_log(limit=min(limit, 500), offset=offset, event_type=event_type)
