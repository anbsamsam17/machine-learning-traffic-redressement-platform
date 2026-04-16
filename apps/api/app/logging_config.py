"""Structured JSON logging configuration with request-ID middleware."""

from __future__ import annotations

import json
import logging
import sys
import uuid
from datetime import datetime, timezone
from typing import Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from .config import get_settings

# ---------------------------------------------------------------------------
# Contextvars for request-scoped data
# ---------------------------------------------------------------------------

import contextvars

_request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")


def get_request_id() -> str:
    return _request_id_var.get()


# ---------------------------------------------------------------------------
# JSON formatter
# ---------------------------------------------------------------------------

class JSONFormatter(logging.Formatter):
    """Emit one JSON object per log line."""

    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": _request_id_var.get("-"),
        }
        if record.exc_info and record.exc_info[1]:
            log_entry["exception"] = self.formatException(record.exc_info)
        if hasattr(record, "extra_data"):
            log_entry["data"] = record.extra_data
        return json.dumps(log_entry, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Setup function
# ---------------------------------------------------------------------------

def setup_logging() -> None:
    """Configure root logger with JSON formatter."""
    settings = get_settings()
    level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JSONFormatter())

    root = logging.getLogger()
    root.setLevel(level)
    # Remove default handlers
    root.handlers.clear()
    root.addHandler(handler)

    # Silence noisy libraries
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.error").setLevel(logging.WARNING)
    logging.getLogger("tensorflow").setLevel(logging.ERROR)


# ---------------------------------------------------------------------------
# Request-ID middleware
# ---------------------------------------------------------------------------

class RequestIDMiddleware(BaseHTTPMiddleware):
    """Inject a unique request_id into every request, available in logs."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        request_id = request.headers.get("X-Request-ID", uuid.uuid4().hex[:16])
        _request_id_var.set(request_id)
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response
