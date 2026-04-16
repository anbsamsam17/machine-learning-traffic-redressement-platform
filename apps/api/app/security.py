"""Path traversal protection — validate that user-supplied paths stay within allowed bounds."""

from __future__ import annotations

from pathlib import Path

from fastapi import HTTPException, status

from .config import get_settings


def validate_path(user_path: str, allowed_root: str | None = None) -> Path:
    """Resolve *user_path* and ensure it is under *allowed_root* (or WORKSPACE_ROOT).

    Returns the resolved ``Path`` on success.
    Raises ``HTTPException(403)`` if the resolved path escapes the allowed root.
    """
    settings = get_settings()
    root = Path(allowed_root) if allowed_root else Path(settings.WORKSPACE_ROOT)
    root = root.resolve()

    try:
        resolved = Path(user_path).resolve()
    except (OSError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Chemin invalide: {exc}",
        )

    # Check the path is under root (or IS root)
    try:
        resolved.relative_to(root)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Acces refuse: le chemin sort du repertoire autorise",
        )

    return resolved
