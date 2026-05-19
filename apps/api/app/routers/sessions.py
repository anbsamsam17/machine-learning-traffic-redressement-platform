"""Sessions router — exposes the user's currently active session so the frontend
can restore its store after a reload (APP-P0-4).

This endpoint inspects ``session_manager`` for the active session of the
authenticated user and returns a derived state ("upload" / "mapping" /
"preview" / "config" / "training" / "evaluation") so the React store and
stepper can hydrate without forcing the user to redo the pipeline.
"""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from ..auth import UserRecord, verify_token, user_store
from ..session import session_manager

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/sessions", tags=["sessions"])


# ---------------------------------------------------------------------------
# Optional auth dependency
#
# We don't want this endpoint to crash with a hard 401 when the bearer header
# is missing — the frontend calls it on every pipeline page mount, including
# the very first visit before the user has uploaded anything. A 401 would be
# surfaced as a noisy console error. Instead, we treat "no auth" as "no
# active session" (404) so the frontend just keeps its empty state.
# ---------------------------------------------------------------------------


async def get_current_user_optional(request: Request) -> UserRecord | None:
    """Return the authenticated user if a valid bearer token is present, else None.

    Never raises — used by endpoints that must remain reachable without auth
    during the transition to multi-user security.
    """
    auth_header = request.headers.get("Authorization") or request.headers.get("authorization")
    if not auth_header or not auth_header.lower().startswith("bearer "):
        return None
    token = auth_header.split(" ", 1)[1].strip()
    if not token:
        return None
    try:
        payload = verify_token(token)
    except HTTPException:
        return None
    user_id = payload.get("sub")
    if not user_id:
        return None
    return user_store.get_by_id(user_id)


# ---------------------------------------------------------------------------
# Response model
# ---------------------------------------------------------------------------


class SessionStateResponse(BaseModel):
    session_id: str
    mode: str  # "tv" | "pl"
    step: str  # "upload" | "mapping" | "preview" | "config" | "training" | "evaluation"
    file_name: str | None
    rows: int | None
    columns_count: int | None
    mapping_validated: bool
    training_task_id: str | None
    output_dir: str | None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _derive_step(session_data: dict) -> str:
    """Derive the furthest step the user has reached from the session contents.

    The order mirrors the frontend pipeline: upload -> mapping -> preview ->
    config -> training -> evaluation. We inspect which artefacts have been
    persisted in the session and return the most advanced one reached.
    """
    # Evaluation: an evaluation result was stored
    if session_data.get("eval_result") is not None or session_data.get("evaluation_metrics") is not None:
        return "evaluation"
    # Training kicked off
    if session_data.get("training_task_id") or session_data.get("output_dir"):
        return "training"
    # Config saved (training_config persisted before /start)
    if session_data.get("training_config") is not None:
        return "config"
    # Mapping was validated => learning_df was built
    if session_data.get("learning_df") is not None or session_data.get("confirmed_mapping") is not None:
        return "preview"
    # Raw file uploaded
    if session_data.get("raw_df") is not None or session_data.get("filename"):
        return "mapping"
    return "upload"


def _safe_rows(session_data: dict) -> int | None:
    """Return the row count of the most relevant DataFrame, if available."""
    for key in ("learning_df", "raw_df"):
        df = session_data.get(key)
        if df is not None:
            try:
                return int(len(df))
            except Exception:
                continue
    return None


def _safe_cols(session_data: dict) -> int | None:
    for key in ("learning_df", "raw_df"):
        df = session_data.get(key)
        if df is not None:
            try:
                return int(len(df.columns))
            except Exception:
                continue
    return None


def _normalize_mode(raw_mode: str | None) -> str:
    """Backend stores mode in any case ("TV", "tv", "PL"). Frontend expects lower-case."""
    if not raw_mode:
        return "tv"
    m = raw_mode.strip().lower()
    if m in ("tv", "pl"):
        return m
    if "pl" in m:
        return "pl"
    return "tv"


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/current", response_model=SessionStateResponse)
async def get_current_session(
    current_user: Annotated[UserRecord | None, Depends(get_current_user_optional)],
) -> SessionStateResponse:
    """Return the authenticated user's currently active session state.

    Returns 404 ``{detail: "no_active_session"}`` if no session is mapped to
    the user (or no user is authenticated yet).
    """
    if current_user is None:
        # No bearer token / invalid token — no session can be restored
        raise HTTPException(status_code=404, detail="no_active_session")

    session_id = session_manager.get_user_session(current_user.user_id)
    if session_id is None:
        raise HTTPException(status_code=404, detail="no_active_session")

    session = session_manager.get_session(session_id)
    if session is None:
        # Stale mapping (TTL drift) — clean up and report no session
        session_manager.clear_user_session(current_user.user_id)
        raise HTTPException(status_code=404, detail="no_active_session")

    # session.data may be a lazy Redis proxy or a plain dict — both support
    # ``.get(key, default)``.
    data = session.data
    step = _derive_step(data)
    file_name = data.get("filename")
    rows = _safe_rows(data)
    columns_count = _safe_cols(data)
    mapping_validated = data.get("learning_df") is not None or data.get("confirmed_mapping") is not None
    training_task_id = data.get("training_task_id")
    output_dir = data.get("output_dir")

    return SessionStateResponse(
        session_id=session_id,
        mode=_normalize_mode(session.mode),
        step=step,
        file_name=file_name if isinstance(file_name, str) else None,
        rows=rows,
        columns_count=columns_count,
        mapping_validated=bool(mapping_validated),
        training_task_id=training_task_id if isinstance(training_task_id, str) else None,
        output_dir=output_dir if isinstance(output_dir, str) else None,
    )


@router.delete("/current", status_code=status.HTTP_204_NO_CONTENT)
async def clear_current_session(
    current_user: Annotated[UserRecord | None, Depends(get_current_user_optional)],
) -> None:
    """Detach the user's active session (does NOT delete the session itself).

    Useful for "start over" actions on the frontend.
    """
    if current_user is None:
        return None
    session_manager.clear_user_session(current_user.user_id)
    return None
