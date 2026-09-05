"""
EIP DDR Intelligence v4.5 — Security Core
Startup validation, secret scanning, password policy, account lockout, rate limiting.
"""
import os, re, secrets, string, hashlib, datetime
from typing import Optional

# ── Startup environment validation ────────────────────────────────────────────

REQUIRED_ENV_VARS = ["JWT_SECRET_KEY", "ALLOWED_ORIGINS"]

WEAK_KEY_PATTERNS = [
    "dev-insecure",
    "change-in-production",
    "your-secret",
    "REPLACE_WITH",
    "example",
    "changeme",
]

def validate_environment() -> list[str]:
    """
    Validate all required environment variables are present and safe.
    Returns list of error strings. Empty = OK.
    Called at startup — if errors exist, app refuses to start in production.
    """
    errors = []
    env = os.environ.get("APP_ENV", "production")

    # Check required vars
    for var in REQUIRED_ENV_VARS:
        val = os.environ.get(var, "")
        if not val:
            errors.append(f"MISSING: {var} is required but not set")
            continue

        # Scan for weak/default values
        if var == "JWT_SECRET_KEY":
            for pattern in WEAK_KEY_PATTERNS:
                if pattern.lower() in val.lower():
                    errors.append(f"INSECURE: {var} contains default/weak value ('{pattern}')")
            if len(val) < 32:
                errors.append(f"WEAK: {var} is too short (minimum 32 chars)")

    # Check admin credentials in env
    admin_pw = os.environ.get("ADMIN_PASSWORD", "")
    if admin_pw:
        for weak in ["password123", "admin123", "123456789"]:
            if weak.lower() == admin_pw.lower():
                errors.append(f"INSECURE: ADMIN_PASSWORD is a known weak value ('{weak}')")

    # In production, wildcard origins are forbidden
    origins = os.environ.get("ALLOWED_ORIGINS", "")
    if env == "production" and ("*" in origins or "localhost" in origins):
        errors.append(f"INSECURE: ALLOWED_ORIGINS contains '*' or 'localhost' in production mode")

    return errors


def generate_temp_password(length: int = 16) -> str:
    """Generate a cryptographically secure temporary password."""
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
    while True:
        pw = "".join(secrets.choice(alphabet) for _ in range(length))
        # Ensure it meets complexity: upper, lower, digit, special
        if (any(c.isupper() for c in pw) and
            any(c.islower() for c in pw) and
            any(c.isdigit() for c in pw) and
            any(c in "!@#$%^&*" for c in pw)):
            return pw


# ── Password policy ───────────────────────────────────────────────────────────

MIN_PASSWORD_LENGTH = int(os.environ.get("PASSWORD_MIN_LENGTH", "10"))

def validate_password_strength(password: str) -> list[str]:
    """
    Validate password meets enterprise complexity requirements.
    Returns list of failure reasons. Empty = OK.
    """
    failures = []
    if len(password) < MIN_PASSWORD_LENGTH:
        failures.append(f"Minimum {MIN_PASSWORD_LENGTH} characters required")
    if not any(c.isupper() for c in password):
        failures.append("At least one uppercase letter required")
    if not any(c.islower() for c in password):
        failures.append("At least one lowercase letter required")
    if not any(c.isdigit() for c in password):
        failures.append("At least one number required")
    if not any(c in "!@#$%^&*()_+-=[]{}|;':\",./<>?" for c in password):
        failures.append("At least one special character required")
    return failures


# ── Account lockout ───────────────────────────────────────────────────────────

MAX_ATTEMPTS  = int(os.environ.get("MAX_LOGIN_ATTEMPTS", "5"))
LOCKOUT_MINS  = int(os.environ.get("LOCKOUT_MINUTES", "15"))

# In-memory lockout store: {email: {"attempts": int, "locked_until": datetime|None}}
_lockout: dict = {}

def check_lockout(email: str) -> Optional[str]:
    """Returns error message if account is locked, None if OK to proceed."""
    email = email.lower()
    entry = _lockout.get(email)
    if not entry:
        return None
    locked_until = entry.get("locked_until")
    if locked_until and datetime.datetime.utcnow() < locked_until:
        remaining = int((locked_until - datetime.datetime.utcnow()).total_seconds() / 60) + 1
        return f"Account locked after too many failed attempts. Try again in {remaining} minute(s)."
    return None

def record_failed_login(email: str):
    """Record a failed login attempt; lock account if threshold exceeded."""
    email = email.lower()
    entry = _lockout.setdefault(email, {"attempts": 0, "locked_until": None})
    # Reset if previous lockout has expired
    if entry.get("locked_until") and datetime.datetime.utcnow() > entry["locked_until"]:
        entry["attempts"] = 0
        entry["locked_until"] = None
    entry["attempts"] += 1
    if entry["attempts"] >= MAX_ATTEMPTS:
        entry["locked_until"] = datetime.datetime.utcnow() + datetime.timedelta(minutes=LOCKOUT_MINS)

def clear_failed_logins(email: str):
    """Clear failed attempts on successful login."""
    _lockout.pop(email.lower(), None)


# ── Request ID ────────────────────────────────────────────────────────────────

def generate_request_id() -> str:
    return secrets.token_hex(8)
