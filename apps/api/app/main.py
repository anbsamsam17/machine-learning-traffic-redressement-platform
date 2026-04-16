"""FastAPI application entry point."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from .config import get_settings
from .logging_config import RequestIDMiddleware, setup_logging
from .session import session_manager

# Setup structured JSON logging early
setup_logging()

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Rate limiter (slowapi)
# ---------------------------------------------------------------------------

limiter = Limiter(key_func=get_remote_address, default_limits=["200/minute"])

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


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Startup / shutdown lifecycle."""
    settings = get_settings()

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
        "MDL Redressement API starting (CORS=%s, max_upload=%dMB)",
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
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(
    title="MDL Redressement API",
    version="2.0.0",
    lifespan=lifespan,
)

# -- Rate limiter --------------------------------------------------------------
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# -- Request-ID middleware -----------------------------------------------------
app.add_middleware(RequestIDMiddleware)

# -- CORS (strict: only configured origins) ------------------------------------
settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID"],
)

# -- Prometheus metrics --------------------------------------------------------
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

# -- Auth router ---------------------------------------------------------------
from .auth import router as auth_router  # noqa: E402

app.include_router(auth_router)

# -- Routers ----------------------------------------------------------------
from .routers import (  # noqa: E402
    carte,
    compteurs,
    evaluation,
    export,
    mapping,
    models,
    training,
    upload,
)

app.include_router(upload.router)
app.include_router(mapping.router)
app.include_router(training.router)
app.include_router(evaluation.router)
app.include_router(export.router)
app.include_router(carte.router)
app.include_router(compteurs.router)
app.include_router(models.router)


# -- Health -----------------------------------------------------------------

@app.get("/health", tags=["system"])
async def health() -> dict[str, str]:
    return {
        "status": "ok",
        "version": "2.0.0",
        "active_sessions": str(session_manager.active_count),
    }
