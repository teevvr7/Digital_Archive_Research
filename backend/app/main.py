"""FastAPI application entrypoint."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.modules.auth.router import router as auth_router
from app.modules.correspondents.router import router as correspondents_router
from app.modules.files.router import dashboard_router
from app.modules.files.router import router as files_router
from app.modules.metadata.router import router as metadata_router
from app.modules.search.router import router as search_router
from app.modules.tags.router import router as tags_router
from app.modules.views.router import router as views_router
from app.modules.export.router import router as export_router

from fastapi.openapi.utils import get_openapi

app = FastAPI(
    title="DataWiz Digital Archive API",
    version="0.1.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
)

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
)

from app.modules.idp.config_router import router as idp_config_router

from app.modules.shares.router import router as shares_router

# ---- Routers ----
app.include_router(auth_router, prefix="/api")
app.include_router(files_router, prefix="/api")
app.include_router(dashboard_router, prefix="/api")
app.include_router(search_router, prefix="/api")
app.include_router(idp_config_router, prefix="/api")
app.include_router(tags_router, prefix="/api")
app.include_router(correspondents_router, prefix="/api")
app.include_router(metadata_router, prefix="/api")
app.include_router(views_router, prefix="/api")
app.include_router(export_router, prefix="/api")
app.include_router(shares_router, prefix="/api")



@app.get("/api/health")
def health():
    return {"status": "ok", "env": settings.env}
