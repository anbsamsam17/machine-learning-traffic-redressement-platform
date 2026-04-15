"""FastAPI application entry point."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import get_settings
from .session import session_manager

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


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Startup / shutdown lifecycle."""
    settings = get_settings()  # triggers env-var setup
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

# -- CORS -------------------------------------------------------------------
settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -- Routers ----------------------------------------------------------------
from .routers import (  # noqa: E402
    carte,
    compteurs,
    evaluation,
    export,
    mapping,
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


# -- Health -----------------------------------------------------------------

@app.get("/health", tags=["system"])
async def health() -> dict[str, str]:
    return {
        "status": "ok",
        "version": "2.0.0",
        "active_sessions": str(session_manager.active_count),
    }
