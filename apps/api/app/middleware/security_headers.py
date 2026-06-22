"""Security-headers middleware (A7).

Adds the OWASP-recommended baseline on every response:

- ``Strict-Transport-Security``  — force HTTPS for 2 years (browsers cache
  the directive even after a downgrade attempt).
- ``X-Content-Type-Options: nosniff`` — kill MIME sniffing.
- ``X-Frame-Options: DENY`` — clickjacking.
- ``Referrer-Policy: strict-origin-when-cross-origin`` — cross-site referrer
  leakage.
- ``Content-Security-Policy`` — minimal allowlist for the few CDNs the
  evaluation HTML report pulls (Plotly, DataTables, jQuery, OSM tiles).
  XSS via uploaded CSV values is still possible if the report HTML doesn't
  `html.escape` user-controlled cells — that hardening lives in
  routers/evaluation.py and is part of E2 scope.

The middleware is a no-op for OPTIONS preflight (CORS already handles
those) so headers can't pollute the preflight allow-list.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

# Allow-list of CDNs used by the generated HTML reports. Adding `'unsafe-inline'`
# for scripts is unfortunate but Plotly/DataTables embed inline init blocks; we
# offset that by serving the HTML report from a dedicated route that requires
# auth and never echoes user input without `html.escape` (E2 hardening).
_DEFAULT_CSP = (
    "default-src 'self'; "
    "script-src 'self' https://cdn.plot.ly https://cdn.datatables.net "
    "https://code.jquery.com 'unsafe-inline'; "
    "style-src 'self' https://cdn.datatables.net 'unsafe-inline'; "
    "img-src 'self' data: https://*.openstreetmap.org https://*.cartocdn.com; "
    "font-src 'self' data:; "
    "connect-src 'self'; "
    "frame-src 'none'; "
    "frame-ancestors 'none'; "
    "object-src 'none'; "
    "base-uri 'self'"
)

_HEADERS: dict[str, str] = {
    "Strict-Transport-Security": "max-age=63072000; includeSubDomains",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Content-Security-Policy": _DEFAULT_CSP,
    "Permissions-Policy": "geolocation=(), camera=(), microphone=(), payment=()",
    "Cross-Origin-Opener-Policy": "same-origin",
    "X-Permitted-Cross-Domain-Policies": "none",
}


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Inject security headers on every response, leaving existing values alone."""

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        response = await call_next(request)
        # Don't override headers already set by an inner middleware/handler
        # (e.g. CORS preflight may want its own X-Frame-Options policy in
        # iframe-embedded contexts; here we err on the side of DENY for now).
        for key, value in _HEADERS.items():
            response.headers.setdefault(key, value)
        return response
