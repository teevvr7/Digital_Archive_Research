"""FastAPI application entrypoint."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.core.config import settings
from app.core.monitoring import init_sentry
from app.core.rate_limit import limiter
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

# Must run before the app is constructed so startup errors are also captured.
init_sentry("api")

app = FastAPI(
    title="DataWiz Digital Archive API",
    version="0.1.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
)

# ---- Rate limiting (targeted — see core/rate_limit.py) ----
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

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

# ---- Routers ----
app.include_router(auth_router, prefix="/api")
app.include_router(files_router, prefix="/api")
app.include_router(dashboard_router, prefix="/api")
app.include_router(search_router, prefix="/api")
app.include_router(tags_router, prefix="/api")
app.include_router(correspondents_router, prefix="/api")
app.include_router(metadata_router, prefix="/api")
app.include_router(views_router, prefix="/api")
app.include_router(export_router, prefix="/api")
app.include_router(shares_router, prefix="/api")
app.include_router(shares_public_router, prefix="/api")


@app.get("/api/health")
def health():
    return {"status": "ok", "env": settings.env}
