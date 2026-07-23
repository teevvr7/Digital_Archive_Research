"""Security-related HTTP response headers, applied to every response.

Defense-in-depth for a browser-facing JSON API: none of these change behavior
for a normal API client — they only constrain what a browser is allowed to do
if a response is ever coerced into rendering (clickjacking via an iframe,
MIME-sniffing a JSON body as something executable, etc).
"""

from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.core.config import settings

# Swagger UI / ReDoc (dev-only — gated off entirely in production in main.py)
# load their own JS/CSS from a CDN, which a locked-down CSP would break. Every
# other route returns pure JSON and gets the strict policy.
_DOCS_PATHS = {"/api/docs", "/api/redoc", "/api/openapi.json"}
_STRICT_CSP = "default-src 'none'; frame-ancestors 'none'"


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Adds standard hardening headers to every response."""

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
        response.headers["Permissions-Policy"] = "geolocation=(), camera=(), microphone=()"
        if request.url.path not in _DOCS_PATHS:
            response.headers["Content-Security-Policy"] = _STRICT_CSP
        if settings.env == "production":
            # Only meaningful behind TLS — assumes production always terminates HTTPS.
            response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
        return response
