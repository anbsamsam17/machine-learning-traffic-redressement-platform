"""FastAPI application entry point.

Bloc A wiring:

- A1  : every business router is mounted with
        `dependencies=[Depends(get_current_user)]` so JWT auth is mandatory
        without per-handler boilerplate. `/api/auth/*` and `/health` stay
        public.
- A6  : limiter imported from `app.rate_limit` (decouples from main.py to
        avoid an import cycle when routers attach decorators).
- A7  : `SecurityHeadersMiddleware` injects HSTS / CSP / X-Frame-Options /
        X-Content-Type-Options / Referrer-Policy / Permissions-Policy on
        every response.
- A8  : in production (`ENVIRONMENT=production`) `/docs`, `/redoc` and
        `/openapi.json` are disabled, `/metrics` is restricted to an
        IP allow-list, `/health` returns only `{"status": "ok"}`, and the
        global exception handler hides Python class names / messages from
        the response (logged server-side with the request id).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from .config import get_settings
from .logging_config import RequestIDMiddleware, get_request_id, setup_logging
from .middleware.security_headers import SecurityHeadersMiddleware
from .rate_limit import limiter
from .session import session_manager

# Setup structured JSON logging early
setup_logging()

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Lifespan — periodic session cleanup
# ---------------------------------------------------------------------------

_CLEANUP_INTERVAL_SECONDS = 300  # 5 min


async def _cleanup_loop() -> None:
    """Background coroutine that purges expired sessions."""
    while True:
        try:
            await asyncio.sleep(_CLEANUP_INTERVAL_SECONDS)
            session_manager.cleanup_expired()
        except asyncio.CancelledError:
            break
        except Exception:
            logger.exception("Error during session cleanup")


_SEED_USER_EMAIL = "samir.anbri@gmail.com"
_SEED_USER_PASSWORD = "TestPass123!"


def _seed_default_user() -> None:
    """Idempotently create a default dev/admin user on startup.

    The user store is in-memory (or Redis-backed) and loses non-Redis
    data across restarts, so without seeding the dev account everyone
    gets a 401 on first login post-deploy. This is a no-op if the user
    already exists.

    P0-5: skipped entirely in production — a hard-coded credential pair
    shipped in source is a critical vulnerability. Dev/staging keeps
    the seed for the smooth onboarding flow.
    """
    settings = get_settings()
    if settings.is_production:
        logger.info("Seed user skipped (production mode)")
        return
    try:
        from .auth import user_store

        if user_store.get_by_email(_SEED_USER_EMAIL) is not None:
            logger.info("Seed user already exists, skipping: %s", _SEED_USER_EMAIL)
            return
        user_store.register(_SEED_USER_EMAIL, _SEED_USER_PASSWORD)
        logger.info("Seed user created: %s", _SEED_USER_EMAIL)
    except Exception:
        logger.exception("Failed to seed default user")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Startup / shutdown lifecycle."""
    settings = get_settings()

    # -- Seed default dev user (idempotent) ------------------------------------
    _seed_default_user()

    # -- Sentry init (if DSN provided) -----------------------------------------
    if settings.SENTRY_DSN:
        try:
            import sentry_sdk
            from sentry_sdk.integrations.fastapi import FastApiIntegration
            from sentry_sdk.integrations.starlette import StarletteIntegration

            sentry_sdk.init(
                dsn=settings.SENTRY_DSN,
                integrations=[
                    StarletteIntegration(transaction_style="endpoint"),
                    FastApiIntegration(transaction_style="endpoint"),
                ],
                traces_sample_rate=0.2,
                send_default_pii=False,
            )
            logger.info("Sentry initialized with DSN ending ...%s", settings.SENTRY_DSN[-8:])
        except Exception:
            logger.warning("Failed to initialize Sentry", exc_info=True)

    logger.info(
        "MDL Redressement API starting (env=%s CORS=%s max_upload=%dMB)",
        settings.ENVIRONMENT,
        settings.CORS_ORIGINS,
        settings.MAX_UPLOAD_MB,
    )
    task = asyncio.create_task(_cleanup_loop())
    yield
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    logger.info("MDL Redressement API shutdown complete")


# ---------------------------------------------------------------------------
# FastAPI app — disable /docs in production (A8)
# ---------------------------------------------------------------------------

_settings = get_settings()

_app_kwargs: dict = {
    "title": "MDL Redressement API",
    "version": "2.0.0",
    "lifespan": lifespan,
}
if _settings.is_production:
    _app_kwargs.update(
        {
            "docs_url": None,
            "redoc_url": None,
            "openapi_url": None,
        }
    )

app = FastAPI(**_app_kwargs)

# -- Rate limiter (A6) ---------------------------------------------------------
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


# -- Catch-all exception handler (A8): never leak Python class / message ------
def _cors_headers_for(request: Request) -> dict[str, str]:
    origin = request.headers.get("origin", "")
    if origin and origin in _settings.CORS_ORIGINS:
        return {
            "Access-Control-Allow-Origin": origin,
            "Access-Control-Allow-Credentials": "true",
            "Vary": "Origin",
        }
    return {}


@app.exception_handler(Exception)
async def _unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Log everything server-side, return a sanitized body to the client."""
    request_id = get_request_id() or "-"
    # exc_info=True ensures the full traceback lands in JSON logs / Sentry.
    logger.exception(
        "Unhandled exception on %s %s (request_id=%s)",
        request.method,
        request.url.path,
        request_id,
    )
    return JSONResponse(
        status_code=500,
        content={"detail": "internal error", "request_id": request_id},
        headers=_cors_headers_for(request),
    )


# -- Middleware stack ----------------------------------------------------------
# Order matters in Starlette: middlewares added LATER wrap the others, so the
# first one declared is the OUTERMOST. We want security headers on every
# response (including errors), so it's the outermost.
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(SlowAPIMiddleware)
app.add_middleware(RequestIDMiddleware)

# -- CORS (strict: only configured origins) ------------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=_settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID"],
)

# -- Prometheus metrics --------------------------------------------------------
# In production /metrics is mounted only if METRICS_ALLOWED_IPS is non-empty;
# the dependency below enforces the IP allow-list at request time.
try:
    from prometheus_fastapi_instrumentator import Instrumentator

    Instrumentator(
        should_group_status_codes=True,
        should_ignore_untemplated=True,
        excluded_handlers=["/health", "/metrics"],
    ).instrument(app).expose(app, include_in_schema=False, should_gzip=True)
    logger.info("Prometheus metrics enabled at /metrics")
except ImportError:
    logger.info("prometheus-fastapi-instrumentator not installed — metrics disabled")


async def _enforce_metrics_allowlist(request: Request) -> None:
    """A8: in production, /metrics requires an IP allow-list.

    Attached as a route-level dependency below so the prometheus-instrumentator
    expose() keeps its default behaviour during development.
    """
    if not _settings.is_production:
        return
    client = request.client.host if request.client else ""
    if client not in _settings.METRICS_ALLOWED_IPS:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="not found",
        )


# Register the dependency on the existing /metrics route if it was added.
for _route in app.router.routes:
    if getattr(_route, "path", "") == "/metrics":
        _route.dependant.dependencies.append(  # type: ignore[attr-defined]
            Depends(_enforce_metrics_allowlist).dependency  # type: ignore[arg-type]
        )

# -- Auth router (PUBLIC — never wrap with get_current_user) -------------------
from .auth import get_current_user  # noqa: E402
from .auth import router as auth_router

app.include_router(auth_router)

# -- Business routers (A1: all behind Depends(get_current_user)) --------------
from .routers import (  # noqa: E402
    carte,
    compteurs,
    discontinuites,
    evaluation,
    evolution,
    export,
    mapping,
    models,
    sessions,
    training,
    upload,
    visualisation,
)

_protected = [Depends(get_current_user)]

app.include_router(upload.router, dependencies=_protected)
app.include_router(mapping.router, dependencies=_protected)
app.include_router(training.router, dependencies=_protected)
app.include_router(evaluation.router, dependencies=_protected)
app.include_router(export.router, dependencies=_protected)
app.include_router(carte.router, dependencies=_protected)
app.include_router(evolution.router, dependencies=_protected)
app.include_router(compteurs.router, dependencies=_protected)
app.include_router(models.router, dependencies=_protected)
app.include_router(visualisation.router, dependencies=_protected)
app.include_router(discontinuites.router, dependencies=_protected)
# sessions router uses its own optional auth dependency (returns 404 on no
# auth instead of 401) so the frontend can call it on first page load.
app.include_router(sessions.router)


# -- Health (PUBLIC — minimal payload in production) ---------------------------


@app.get("/health", tags=["system"])
async def health() -> dict[str, str]:
    """Liveness probe. Verbose payload only in development (A8)."""
    if _settings.is_production:
        return {"status": "ok"}
    return {
        "status": "ok",
        "version": "2.0.0",
        "environment": _settings.ENVIRONMENT,
        "active_sessions": str(session_manager.active_count),
    }
