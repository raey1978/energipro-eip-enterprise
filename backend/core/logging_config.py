"""
EIP DDR Intelligence v4.5 — Structured Logging
JSON-formatted logs with request ID, user, IP, duration, severity.
"""
import os, logging, sys
from pythonjsonlogger import jsonlogger

APP_ENV     = os.environ.get("APP_ENV", "production")
LOG_LEVEL   = os.environ.get("LOG_LEVEL", "INFO").upper()
LOG_FORMAT  = os.environ.get("LOG_FORMAT", "json")  # json | text

class EIPJsonFormatter(jsonlogger.JsonFormatter):
    def add_fields(self, log_record, record, message_dict):
        super().add_fields(log_record, record, message_dict)
        log_record["level"]   = record.levelname
        log_record["module"]  = record.module
        log_record["service"] = "eip-backend"
        log_record["version"] = os.environ.get("APP_VERSION", "4.5")

def setup_logging():
    """Configure structured logging for the application."""
    root = logging.getLogger()
    root.handlers = []
    root.setLevel(getattr(logging, LOG_LEVEL, logging.INFO))

    handler = logging.StreamHandler(sys.stdout)

    if LOG_FORMAT == "json":
        formatter = EIPJsonFormatter(
            fmt="%(asctime)s %(level)s %(name)s %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S"
        )
    else:
        formatter = logging.Formatter(
            fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        )

    handler.setFormatter(formatter)
    root.addHandler(handler)

    # Suppress noisy libraries
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("passlib").setLevel(logging.WARNING)

    return logging.getLogger("eip")

# Module-level loggers
logger     = logging.getLogger("eip.app")
sec_logger = logging.getLogger("eip.security")
aud_logger = logging.getLogger("eip.audit")
err_logger = logging.getLogger("eip.error")
