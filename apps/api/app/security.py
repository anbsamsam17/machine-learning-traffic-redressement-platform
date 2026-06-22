"""Path traversal protection — confine user-supplied paths to per-session roots.

A5 (audit 01, P1-1 / P1-2):

User-controlled paths (`model_dir`, `output_dir`, `dir`) used to be passed
straight to `Path(...)` and walked with `rglob("*")`. Without ownership
plumbing, an attacker could exfiltrate any file readable by the API user
just by setting `model_dir=/etc`.

Mitigation:

1. Disk layout is now namespaced per user AND per session:
       WORKSPACE_ROOT/{user_id}/{session_id}/{models|carte|compteurs}/
2. Routers compute `session_root(user.user_id, session.session_id)` and pass
   it as `allowed_root` to `validate_path(user_path, allowed_root=...)`.
3. `validate_path` symlink-resolves both sides and refuses any path that
   leaves the allowed root.

Routes that simply need their session's root (no user-supplied path
fragment) should call `session_root(...)` directly instead of trusting
client input — the E2 router refacto wires this in each handler.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import HTTPException, status

from .config import get_settings


def session_root(user_id: str, session_id: str) -> Path:
    """Return the per-user / per-session workspace root.

    Both ids are validated (alphanumeric + dash + underscore only) to refuse
    accidental traversal attempts (`..`, slashes, NUL). The directory is
    created on first call.
    """
    _ensure_safe_segment(user_id, "user_id")
    _ensure_safe_segment(session_id, "session_id")
    root = Path(get_settings().WORKSPACE_ROOT).resolve() / user_id / session_id
    root.mkdir(parents=True, exist_ok=True)
    return root


_ALLOWED_SEGMENT_CHARS = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_")


def _ensure_safe_segment(value: str, name: str) -> None:
    if not value or not isinstance(value, str):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{name} requis",
        )
    if any(ch not in _ALLOWED_SEGMENT_CHARS for ch in value):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{name} contient des caracteres non autorises",
        )
    if len(value) > 128:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{name} trop long",
        )


def validate_path(user_path: str, allowed_root: str | Path | None = None) -> Path:
    """Resolve *user_path* and ensure it is under *allowed_root*.

    *allowed_root* should normally be the result of `session_root(...)`. When
    omitted, falls back to the global ``WORKSPACE_ROOT`` for backwards
    compatibility — but callers handling session-scoped data MUST pass the
    per-session root (A5).

    Returns the resolved ``Path`` on success.
    Raises ``HTTPException(400)`` when the path is malformed, ``403`` when it
    escapes the allowed root.
    """
    settings = get_settings()
    root_path = Path(allowed_root) if allowed_root else Path(settings.WORKSPACE_ROOT)
    root_path = root_path.resolve()

    if not user_path or not isinstance(user_path, str):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Chemin requis",
        )

    # Reject NUL bytes outright (filesystem APIs may treat them as terminators).
    if "\x00" in user_path:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Chemin invalide (NUL)",
        )

    try:
        resolved = Path(user_path).resolve()
    except (OSError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Chemin invalide: {exc}",
        ) from exc

    # Check the path is under root (or IS root). `is_relative_to` (py 3.9+)
    # is symlink-safe because we already called `.resolve()` on both sides.
    try:
        resolved.relative_to(root_path)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Acces refuse: le chemin sort du repertoire autorise",
        ) from None

    return resolved


def validate_session_path(
    user_path: str,
    user_id: str,
    session_id: str,
) -> Path:
    """Shortcut: validate *user_path* against session_root(user_id, session_id).

    Convenience helper for the E2 router refacto. Behaves like
    `validate_path(user_path, allowed_root=session_root(user_id, session_id))`
    but creates the root on demand so first writes succeed.
    """
    return validate_path(user_path, allowed_root=session_root(user_id, session_id))
