"""
EIP DDR Market Intelligence & Opportunity Radar v4.5
Production-hardened FastAPI backend.
"""
import os, sys, datetime, time, uuid
from dotenv import load_dotenv

load_dotenv()  # Load .env before anything else

# ── Setup structured logging FIRST ───────────────────────────────────────────
from core.logging_config import setup_logging, logger, sec_logger
setup_logging()

# ── Startup environment validation ────────────────────────────────────────────
from core.security import validate_environment, generate_temp_password

env_errors = validate_environment()
APP_ENV = os.environ.get("APP_ENV", "production")

if env_errors:
    for err in env_errors:
        logger.critical(f"STARTUP_VALIDATION_FAILED: {err}")
    if APP_ENV == "production":
        logger.critical("Refusing to start in production with invalid configuration.")
        sys.exit(1)
    else:
        logger.warning("Development mode — continuing despite validation warnings.")

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from core.database import init_db, load_latest
from core.users    import init_users_table, seed_admin
from core.audit    import init_audit_table
from api.routes    import analytics, opportunities, reports, export
from api.routes    import auth as auth_routes
from api.routes    import leads as leads_routes
from api.routes    import validation as validation_routes
from api.routes    import intelligence as intelligence_routes
from api.routes    import assistant as assistant_routes
from api.routes    import revenue as revenue_routes
from api.routes    import market as market_routes
from api.routes    import trust as trust_routes
from api.routes    import pilot as pilot_routes
from api.routes    import governance as governance_routes
from api.routes    import license as license_routes
from core.license  import check_license, init_license_table, EXEMPT_PATHS as LICENSE_EXEMPT_PATHS

APP_VERSION  = os.environ.get("APP_VERSION", "4.5")
APP_START_TS = datetime.datetime.utcnow()

# ── CORS ──────────────────────────────────────────────────────────────────────
# Explicit origin list from env (comma-separated). Never use "*" with credentials.
_raw_origins    = os.environ.get("ALLOWED_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000")
ALLOWED_ORIGINS = [o.strip() for o in _raw_origins.split(",") if o.strip()]

# ── Rate limiter ─────────────────────────────────────────────────────────────
limiter = Limiter(key_func=get_remote_address, default_limits=["200/minute"])

# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="EIP DDR Market Intelligence & Opportunity Radar",
    description="Commercial intelligence platform for oilfield service companies.",
    version=APP_VERSION,
    # Disable public docs in production
    docs_url  = "/api/docs"   if APP_ENV != "production" else None,
    redoc_url = "/api/redoc"  if APP_ENV != "production" else None,
    openapi_url = "/api/openapi.json" if APP_ENV != "production" else None,
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Accept", "X-Request-ID"],
)

# ── Security headers middleware ───────────────────────────────────────────────
@app.middleware("http")
async def security_headers(request: Request, call_next):
    # Assign request ID for tracing
    request_id = request.headers.get("X-Request-ID", str(uuid.uuid4())[:8])
    start = time.time()

    # ── Trial / license gate ─────────────────────────────────────────────
    # Runs before every request except health probes and the status
    # endpoint itself. A locked instance (expired trial or remotely
    # revoked license) gets a 423 for everything else — including auth —
    # so a client cannot keep working past their trial just by staying
    # logged in.
    if request.method != "OPTIONS" and request.url.path not in LICENSE_EXEMPT_PATHS:
        lic = check_license()
        if lic["locked"]:
            response = JSONResponse(
                status_code=423,
                content={"detail": lic["message"], "locked": True, "status": lic["status"]},
            )
            response.headers["X-Content-Type-Options"] = "nosniff"
            response.headers["X-Request-ID"] = request_id
            return response

    response = await call_next(request)
    duration_ms = round((time.time() - start) * 1000)

    # Security headers
    response.headers["X-Content-Type-Options"]   = "nosniff"
    response.headers["X-Frame-Options"]          = "DENY"
    response.headers["X-XSS-Protection"]         = "1; mode=block"
    response.headers["Referrer-Policy"]          = "strict-origin-when-cross-origin"
    response.headers["X-Request-ID"]             = request_id

    if APP_ENV == "production":
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        response.headers["Content-Security-Policy"]   = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "font-src 'self' https://fonts.gstatic.com; "
            "img-src 'self' data:; "
            "connect-src 'self';"
        )

    # Structured access log
    if not request.url.path.endswith(("/health", "/ready", "/live")):
        logger.info(
            "request",
            extra={
                "request_id":  request_id,
                "method":      request.method,
                "path":        request.url.path,
                "status_code": response.status_code,
                "duration_ms": duration_ms,
                "client_ip":   request.client.host if request.client else "unknown",
            }
        )
    return response

# ── Startup ───────────────────────────────────────────────────────────────────
@app.on_event("startup")
async def startup():
    init_db()
    init_users_table()
    init_audit_table()
    init_license_table()

    # Trial/license state — creates the first-run timestamp on the very
    # first startup if it doesn't exist yet, and logs current status so
    # it's visible in `docker compose logs backend` for support purposes.
    lic = check_license()
    # NOTE: lic["message"] is deliberately renamed to license_message below —
    # stdlib logging.Logger.makeRecord() always raises KeyError on an
    # `extra` dict containing the literal key "message" (it collides with
    # LogRecord's own reserved attribute), so `**lic` can never be spread
    # directly here without crashing startup on every boot.
    logger.info("license_check", extra={
        "license_id": os.environ.get("EIP_LICENSE_ID", "UNMANAGED-LOCAL"),
        "status": lic["status"],
        "locked": lic["locked"],
        "days_remaining": lic["days_remaining"],
        "license_message": lic["message"],
    })
    if lic["locked"]:
        logger.warning("LICENSE_LOCKED_AT_STARTUP", extra={
            "status": lic["status"], "days_remaining": lic["days_remaining"],
            "license_message": lic["message"],
        })

    # V5.0: initialise learning and intelligence tables
    from engines.intelligence.learning_engine import init_learning_tables
    init_learning_tables()

    # V5.1: initialise revenue pipeline tables
    from engines.intelligence.pipeline_engine import init_pipeline_tables
    init_pipeline_tables()

    # V6.0: initialise market intelligence tables
    from engines.intelligence.market_intelligence import init_market_tables
    init_market_tables()

    # V6.3A: initialise entity resolution + temporal engine tables
    from engines.intelligence.entity_resolution import init_entity_tables
    from engines.intelligence.temporal_engine   import init_temporal_tables
    from engines.intelligence.pilot_scorecard   import init_pilot_tables
    init_entity_tables(); init_temporal_tables(); init_pilot_tables()

    # V6.3C: initialise document ingestion log table
    from engines.document_processor import _init_ingestion_log_table
    _init_ingestion_log_table()

    # V6.1: initialise trust layer tables
    from engines.intelligence.trust_layer import init_trust_tables
    init_trust_tables()

    # V6.2: initialise governance layer tables
    from engines.intelligence.governance_layer import init_governance_tables, init_quality_history_table
    init_governance_tables()
    init_quality_history_table()

    # Bootstrap admin — auto-generate temp password if not set
    admin_email = os.environ.get("ADMIN_EMAIL", "admin@energipro.com")
    admin_password = os.environ.get("ADMIN_PASSWORD", "")

    if not admin_password:
        admin_password = generate_temp_password()
        logger.info(
            "BOOTSTRAP_ADMIN_CREATED",
            extra={
                "admin_email": admin_email,
                "temp_password": admin_password,  # Only logged once at startup
                "note": "Change this password immediately after first login",
            }
        )
        # Print to stdout so ops team can read from docker logs
        print(f"\n{'='*60}")
        print(f"  EIP DDR Intelligence v{APP_VERSION} — First Start")
        print(f"  Admin account: {admin_email}")
        print(f"  Temp password: {admin_password}")
        print(f"  CHANGE THIS PASSWORD IMMEDIATELY AFTER FIRST LOGIN")
        print(f"{'='*60}\n")

    seeded = seed_admin(admin_email, admin_password)
    if seeded:
        logger.info("seed_admin_created", extra={"email": admin_email})

    # Load latest intelligence into memory
    data = load_latest()
    app.state.intelligence_store = data if data else {"reports_processed": 0}

    logger.info(
        "startup_complete",
        extra={"version": APP_VERSION, "env": APP_ENV, "origins": ALLOWED_ORIGINS}
    )

# ── Health / Ready / Live endpoints (unauthenticated — standard ops pattern) ─
@app.get("/health", tags=["Monitoring"])
async def health_root():
    """Lightweight healthcheck for Docker/ops probes.
    No heavy processing; a single trivial DB statement verifies the app can
    genuinely serve requests. Returns 503 only if that fails. No sensitive
    configuration is exposed."""
    try:
        from core.database import get_db
        conn = get_db(); conn.execute("SELECT 1").fetchone(); conn.close()
        return {"status": "healthy"}
    except Exception:
        return JSONResponse(status_code=503, content={"status": "unavailable"})

@app.get("/api/health", tags=["Monitoring"])
async def health():
    """Full health check including DB connectivity."""
    db_ok = True
    db_detail = "ok"
    try:
        from core.database import get_db
        conn = get_db()
        conn.execute("SELECT COUNT(*) FROM sqlite_master").fetchone()
        conn.close()
    except Exception as e:
        db_ok = False
        db_detail = str(e)[:100]

    import psutil
    try:
        mem  = psutil.virtual_memory()
        disk = psutil.disk_usage("/data" if os.path.exists("/data") else "/")
        mem_pct  = mem.percent
        disk_pct = disk.percent
    except Exception:
        mem_pct = disk_pct = -1

    uptime_s = int((datetime.datetime.utcnow() - APP_START_TS).total_seconds())

    return {
        "status":      "healthy" if db_ok else "degraded",
        "version":     APP_VERSION,
        "env":         APP_ENV,
        "db_status":   db_detail,
        "uptime_s":    uptime_s,
        "memory_pct":  mem_pct,
        "disk_pct":    disk_pct,
        "timestamp":   datetime.datetime.utcnow().isoformat() + "Z",
    }

@app.get("/api/ready", tags=["Monitoring"])
async def ready():
    """Kubernetes readiness probe — is app ready to serve traffic?"""
    try:
        from core.database import get_db
        conn = get_db(); conn.execute("SELECT 1").fetchone(); conn.close()
        return {"ready": True}
    except Exception:
        return JSONResponse(status_code=503, content={"ready": False})

@app.get("/api/live", tags=["Monitoring"])
async def live():
    """Kubernetes liveness probe — is the process alive?"""
    return {"live": True, "timestamp": datetime.datetime.utcnow().isoformat() + "Z"}

# ── Route registration ────────────────────────────────────────────────────────
app.include_router(auth_routes.router,          prefix="/api/auth",          tags=["Auth"])
app.include_router(analytics.router,            prefix="/api/analytics",     tags=["Analytics"])
app.include_router(opportunities.router,        prefix="/api/opportunities",  tags=["Opportunities"])
app.include_router(reports.router,              prefix="/api/reports",        tags=["Reports"])
app.include_router(export.router,               prefix="/api/export",         tags=["Export"])
app.include_router(leads_routes.router,         prefix="/api/leads",          tags=["Leads"])
app.include_router(validation_routes.router,    prefix="/api/validation",     tags=["Validation"])
app.include_router(intelligence_routes.router,  prefix="/api/intelligence",   tags=["Intelligence"])
app.include_router(assistant_routes.router,     prefix="/api/assistant",      tags=["Assistant"])
app.include_router(revenue_routes.router,       prefix="/api/revenue",        tags=["Revenue"])
app.include_router(market_routes.router,        prefix="/api/market",         tags=["Market"])
app.include_router(trust_routes.router,         prefix="/api/trust",          tags=["Trust"])
app.include_router(pilot_routes.router,         prefix="/api/pilot",          tags=["Pilot"])
app.include_router(governance_routes.router,    prefix="/api/governance",     tags=["Governance"])
app.include_router(license_routes.router,       prefix="/api/license",        tags=["License"])

# ── Frontend (single-container deployment) ────────────────────────────────────
# The whole frontend is one static index.html (no build step, no bundler).
# Logos are served as top-level static files; any other non-/api, non-health
# GET falls back to index.html so the SPA's own client-side view switching
# (plain onclick handlers, no client-side router) works on a hard refresh.
FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "frontend")

@app.get("/logo-full.png", include_in_schema=False)
async def serve_logo_full():
    return FileResponse(os.path.join(FRONTEND_DIR, "logo-full.png"))

@app.get("/logo-icon.png", include_in_schema=False)
async def serve_logo_icon():
    return FileResponse(os.path.join(FRONTEND_DIR, "logo-icon.png"))

@app.get("/{full_path:path}", include_in_schema=False)
async def serve_frontend(full_path: str):
    if full_path.startswith("api/"):
        return JSONResponse({"detail": "Not found"}, status_code=404)
    return FileResponse(os.path.join(FRONTEND_DIR, "index.html"))

# ── Global error handler ──────────────────────────────────────────────────────
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    request_id = request.headers.get("X-Request-ID", "unknown")
    err_logger_local = __import__("logging").getLogger("eip.error")
    err_logger_local.error(
        "unhandled_exception",
        extra={
            "request_id": request_id,
            "path":       request.url.path,
            "error_type": type(exc).__name__,
            "error":      str(exc)[:200],
        },
        exc_info=True
    )
    # v6.3D: this handler runs in Starlette's outermost ServerErrorMiddleware,
    # OUTSIDE CORSMiddleware — so its response gets no CORS headers by default.
    # Browsers then hide the 500 entirely and report "TypeError: Failed to fetch",
    # making processing errors indistinguishable from a dead backend.
    # Echo the origin back explicitly (only if allowed) so the frontend can
    # read the 500 and classify it as "Document Processing Failed".
    headers = {}
    origin = request.headers.get("origin", "")
    if origin and origin in ALLOWED_ORIGINS:
        headers["Access-Control-Allow-Origin"]      = origin
        headers["Access-Control-Allow-Credentials"] = "true"
        headers["Vary"]                             = "Origin"
    return JSONResponse(
        status_code=500,
        content={
            "detail":     "An internal error occurred. Contact your administrator.",
            "request_id": request_id,
        },
        headers=headers,
    )
