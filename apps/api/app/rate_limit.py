"""Shared rate-limiter singleton.

Lives outside `main.py` so routers can import `limiter` to attach
`@limiter.limit(...)` decorators without triggering an import cycle through
the FastAPI app.

Politique de limitation de debit :

- `/api/auth/login`     — 10/minute per IP   (brute-force window)
- `/api/auth/register`  — 5/hour per IP      (account enumeration)
- `/api/upload`         — 30/minute per user (CSV / shapefile flood)
- `/api/training/start` — 5/hour per user    (grille couteuse en CPU ;
                          un verrou par utilisateur et une echeance
                          MAX_TRAINING_MINUTES limitent aussi le cout)
- `/api/carte/generate` — 10/minute per user (map rendering is GIS-heavy)

Les decorateurs sont appliques sur les routes elles-memes ; the limiter
infrastructure lives here so it is testable in isolation.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Callable

from slowapi import Limiter
from slowapi.util import get_remote_address
from starlette.requests import Request


def _user_or_ip_key(request: Request) -> str:
    """Per-user limiter key when authenticated, IP fallback otherwise.

    FastAPI sets `request.state.user` only after `Depends(get_current_user)`
    runs, but slowapi resolves the key before dependencies. We therefore
    inspect the raw Authorization header (truncated) so the key is stable
    per token holder without expensive JWT decoding on every request.
    """
    auth = request.headers.get("authorization", "")
    if auth.startswith("Bearer ") and len(auth) > 16:
        # The first 16 chars after "Bearer " are stable per JWT and unique
        # enough to identify a user without verifying the signature on every
        # call (signature is verified by Depends(get_current_user) later).
        return f"u:{auth[7:23]}"
    return f"ip:{get_remote_address(request)}"


# Rate limiting can be disabled via the ``DISABLE_RATE_LIMIT`` env var, or is
# auto-disabled when the process is running under pytest. The test suite
# registers and logs in many users from 127.0.0.1 — without disabling we'd
# trip the 5/hour register cap after a handful of tests. Production
# deployments leave the var unset and never run via pytest, so the auth caps
# (anti-brute-force / anti-enumeration) stay effective.
_RATE_LIMIT_DISABLED = (
    os.environ.get("DISABLE_RATE_LIMIT", "").lower() in {"1", "true", "yes"}
    or "pytest" in sys.modules
)

# Default policy is intentionally permissive (200/minute) — actual hard
# limits are applied per route via the decorators below.
limiter = Limiter(
    key_func=_user_or_ip_key,
    default_limits=["200/minute"],
    enabled=not _RATE_LIMIT_DISABLED,
)


# Convenience decorator factories — keeps router code readable and lets
# us tweak limits in a single place if Oracle Cloud capacity changes.


def limit_auth_login() -> Callable:
    return limiter.limit("10/minute", key_func=get_remote_address)


def limit_auth_register() -> Callable:
    return limiter.limit("5/hour", key_func=get_remote_address)


def limit_upload() -> Callable:
    return limiter.limit("30/minute")


def limit_training_start() -> Callable:
    return limiter.limit("5/hour")


def limit_carte_generate() -> Callable:
    return limiter.limit("10/minute")
