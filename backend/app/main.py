"""FastAPI application entrypoint."""

import sentry_sdk
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.core.config import settings
from app.core.monitoring import init_sentry
from app.core.rate_limit import limiter
from app.core.security_headers import SecurityHeadersMiddleware
from app.modules.auth.router import router as auth_router
from app.modules.correspondents.router import router as correspondents_router
from app.modules.export.router import router as export_router
from app.modules.files.router import dashboard_router
from app.modules.files.router import router as files_router
from app.modules.metadata.router import router as metadata_router
from app.modules.search.router import router as search_router
from app.modules.shares.router import public_router as shares_public_router
from app.modules.shares.router import router as shares_router
from app.modules.tags.router import router as tags_router
from app.modules.views.router import router as views_router
from app.modules.idp.config_router import router as idp_config_router

from fastapi.openapi.utils import get_openapi

# Must run before the app is constructed so startup errors are also captured.
init_sentry("api")

_is_prod = settings.env == "production"

app = FastAPI(
    title="DataWiz Digital Archive API",
    version="0.1.0",
    # The full API surface (incl. schemas) shouldn't be publicly enumerable in
    # production; Swagger/ReDoc/the raw OpenAPI doc stay dev-only.
    docs_url=None if _is_prod else "/api/docs",
    redoc_url=None if _is_prod else "/api/redoc",
    openapi_url=None if _is_prod else "/api/openapi.json",
)

# ---- Rate limiting (targeted — see core/rate_limit.py) ----
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)


# ---- Custom OpenAPI schema (Swagger UI file-upload support) ----
def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    openapi_schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
    )
    # Modify schema to support Swagger UI file upload for OpenAPI 3.1
    # Convert 'contentMediaType: application/octet-stream' to 'format: binary'
    for schema in openapi_schema.get("components", {}).get("schemas", {}).values():
        if "properties" in schema:
            for prop in schema["properties"].values():
                if prop.get("type") == "string" and prop.get("contentMediaType") == "application/octet-stream":
                    prop.pop("contentMediaType", None)
                    prop["format"] = "binary"
                elif prop.get("type") == "array" and prop.get("items", {}).get("type") == "string" and prop.get("items", {}).get("contentMediaType") == "application/octet-stream":
                    prop["items"].pop("contentMediaType", None)
                    prop["items"]["format"] = "binary"
    app.openapi_schema = openapi_schema
    return app.openapi_schema

app.openapi = custom_openapi

# ---- CORS ----
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    # Export downloads are fetched via JS (need the auth header attached), so
    # the frontend needs to read these two response headers to name the file
    # and detect the row-cap — browsers hide custom headers by default.
    expose_headers=["Content-Disposition", "X-Export-Truncated"],
)

# ---- Security headers (see core/security_headers.py) ----
app.add_middleware(SecurityHeadersMiddleware)

if _is_prod:

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        """Catch-all so a bug never leaks an internal error message or traceback
        to the client. Sentry still gets the real exception either way — this
        only changes what crosses the network boundary. Dev keeps FastAPI's
        default (verbose) handling untouched, so this handler is only
        registered in production.
        """
        sentry_sdk.capture_exception(exc)
        return JSONResponse(status_code=500, content={"detail": "Internal server error"})

# ---- Routers ----
# export_router's literal "GET /documents/export" MUST be included before
# files_router — Starlette matches routes in registration order, and
# files_router's "GET /documents/{doc_id}" is a catch-all for that same verb
# that would otherwise swallow the request first (doc_id="export" fails UUID
# parsing -> a 422 that looks unrelated to the real cause). Any future router
# adding a literal GET under /documents/ needs the same ordering care.
app.include_router(auth_router, prefix="/api")
app.include_router(export_router, prefix="/api")
app.include_router(files_router, prefix="/api")
app.include_router(dashboard_router, prefix="/api")
app.include_router(search_router, prefix="/api")
app.include_router(idp_config_router, prefix="/api")
app.include_router(tags_router, prefix="/api")
app.include_router(correspondents_router, prefix="/api")
app.include_router(metadata_router, prefix="/api")
app.include_router(views_router, prefix="/api")
app.include_router(shares_router, prefix="/api")
app.include_router(shares_public_router, prefix="/api")


@app.get("/api/health")
def health():
    return {"status": "ok", "env": settings.env}
