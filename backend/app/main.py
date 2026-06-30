"""FastAPI application entrypoint."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.modules.auth.router import router as auth_router
from app.modules.correspondents.router import router as correspondents_router
from app.modules.files.router import dashboard_router
from app.modules.files.router import router as files_router
from app.modules.search.router import router as search_router
from app.modules.tags.router import router as tags_router

app = FastAPI(
    title="DataWiz Digital Archive API",
    version="0.1.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
)

# ---- CORS ----
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---- Routers ----
app.include_router(auth_router, prefix="/api")
app.include_router(files_router, prefix="/api")
app.include_router(dashboard_router, prefix="/api")
app.include_router(search_router, prefix="/api")
app.include_router(tags_router, prefix="/api")
app.include_router(correspondents_router, prefix="/api")


@app.get("/api/health")
def health():
    return {"status": "ok", "env": settings.env}
