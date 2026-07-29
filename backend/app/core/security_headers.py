"""Security-related HTTP response headers, applied to every response.

Defense-in-depth for a browser-facing JSON API: none of these change behavior
for a normal API client — they only constrain what a browser is allowed to do
if a response is ever coerced into rendering (clickjacking via an iframe,
MIME-sniffing a JSON body as something executable, etc).
"""

# Awaitable/Callable are used purely for typing the "call_next" middleware parameter.
from collections.abc import Awaitable, Callable

# BaseHTTPMiddleware is Starlette's base class for writing ASGI middleware
# using a simple "async dispatch(request, call_next)" shape.
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.core.config import settings

# Swagger UI / ReDoc (dev-only — gated off entirely in production in main.py)
# load their own JS/CSS from a CDN, which a locked-down CSP would break. Every
# other route returns pure JSON and gets the strict policy.
_DOCS_PATHS = {"/api/docs", "/api/redoc", "/api/openapi.json"}
# The Content-Security-Policy value applied to every non-docs route — "trust
# nothing" is safe because the API only ever returns JSON, never HTML/JS.
_STRICT_CSP = "default-src 'none'; frame-ancestors 'none'"


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Adds standard hardening headers to every response."""

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        # Let the actual route handler run first and produce its response...
        response = await call_next(request)
        # ...then stamp security headers onto whatever it returned.
        # Stops browsers from "guessing" a different content-type than declared
        # (prevents some MIME-confusion attacks).
        response.headers["X-Content-Type-Options"] = "nosniff"
        # Blocks this response from ever being embedded in an <iframe> anywhere
        # (prevents clickjacking).
        response.headers["X-Frame-Options"] = "DENY"
        # Only send the referring page's origin (not full URL) when navigating
        # away from this site, and never when going from HTTPS to HTTP.
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        if settings.env == "production":
            # Isolates this page's browsing context from cross-origin popups it opens.
            response.headers["Cross-Origin-Opener-Policy"] = "same-origin"

        # Explicitly denies the browser permissions APIs this API has no use for.
        response.headers["Permissions-Policy"] = "geolocation=(), camera=(), microphone=()"
        # The docs routes need to load external Swagger/ReDoc assets, so they're
        # the one exception to the otherwise blanket CSP below.
        if request.url.path not in _DOCS_PATHS:
            response.headers["Content-Security-Policy"] = _STRICT_CSP
        if settings.env == "production":
            # Only meaningful behind TLS — assumes production always terminates HTTPS.
            # Tells browsers to ALWAYS use HTTPS for this domain, even if the
            # user typed http:// or clicked an old http:// link.
            response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
        return response
