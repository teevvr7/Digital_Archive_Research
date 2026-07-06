"""Files module router — document ingestion and retrieval endpoints."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile, status
from sqlalchemy.orm import Session

from app.core.deps import get_tenant_db
from app.core.security import TokenData
from app.modules.files import service
from app.modules.files.schemas import DashboardOut, DocumentListOut, DocumentOut

router = APIRouter(tags=["documents"])
dashboard_router = APIRouter(tags=["dashboard"])

_DbCtx = Annotated[tuple[Session, TokenData], Depends(get_tenant_db)]


@router.post(
    "/documents",
    response_model=DocumentListOut,
    response_model_by_alias=True,
    status_code=status.HTTP_201_CREATED,
    summary="Upload one or more documents",
)
async def upload_documents(
    ctx: _DbCtx,
    files: Annotated[list[UploadFile], File(description="Files to upload")],
    document_type: Annotated[list[str] | None, Form()] = None,
    template_id: Annotated[list[str] | None, Form()] = None,
) -> DocumentListOut:
    db, user = ctx
    types = document_type or []
    # Pad with "other" so every file has a type hint
    if len(types) < len(files):
        types += ["other"] * (len(files) - len(types))
        
    tpl_ids = []
    if template_id:
        for tid in template_id:
            if tid and tid.strip() and tid != "null" and tid != "undefined":
                try:
                    tpl_ids.append(uuid.UUID(tid))
                except ValueError:
                    tpl_ids.append(None)
            else:
                tpl_ids.append(None)
                
    return service.create_documents(db, user, files, types, template_ids=tpl_ids)


@router.post(
    "/documents/single",
    response_model=DocumentListOut,
    response_model_by_alias=True,
    status_code=status.HTTP_201_CREATED,
    summary="Upload a single document (with file browser button)",
)
async def upload_single_document(
    ctx: _DbCtx,
    file: UploadFile = File(description="File to upload"),
    document_type: str | None = Form(None),
    template_id: str | None = Form(None),
) -> DocumentListOut:
    db, user = ctx
    types = [document_type or "other"]
    
    tpl_id = None
    if template_id and template_id.strip() and template_id != "null" and template_id != "undefined":
        try:
            tpl_id = uuid.UUID(template_id)
        except ValueError:
            pass
            
    return service.create_documents(db, user, [file], types, template_ids=[tpl_id])


@router.get(
    "/documents",
    response_model=DocumentListOut,
    response_model_by_alias=True,
    summary="List documents with optional filters",
)
def list_documents(
    ctx: _DbCtx,
    status_q: Annotated[str | None, Query(alias="status")] = None,
    type_q: Annotated[str | None, Query(alias="type")] = None,
    q: str | None = None,
    sort: str = "date_desc",
    page: int = 1,
) -> DocumentListOut:
    db, _ = ctx
    return service.list_documents(
        db,
        status_filter=status_q,
        type_filter=type_q,
        q=q,
        sort=sort,
        page=max(1, page),
    )


@router.get(
    "/documents/{doc_id}",
    response_model=DocumentOut,
    response_model_by_alias=True,
    summary="Get a single document by ID",
)
def get_document(ctx: _DbCtx, doc_id: uuid.UUID) -> DocumentOut:
    db, _ = ctx
    return service.get_document(db, doc_id)


@router.get(
    "/documents/{doc_id}/download",
    summary="Return a short-lived signed download URL",
)
def download_document(ctx: _DbCtx, doc_id: uuid.UUID) -> dict[str, str]:
    db, user = ctx
    url = service.get_download_url(db, user, doc_id)
    return {"url": url}


@router.post(
    "/documents/{doc_id}/retry",
    response_model=DocumentOut,
    response_model_by_alias=True,
    summary="Retry a failed document",
)
def retry_document(ctx: _DbCtx, doc_id: uuid.UUID) -> DocumentOut:
    db, _ = ctx
    return service.retry_document(db, doc_id)


@router.post(
    "/documents/{doc_id}/reprocess",
    response_model=DocumentOut,
    response_model_by_alias=True,
    summary="Reprocess a document with optional template selection",
)
def reprocess_document(
    ctx: _DbCtx,
    doc_id: uuid.UUID,
    template_id: uuid.UUID | None = Query(None)
) -> DocumentOut:
    db, _ = ctx
    return service.reprocess_document(db, doc_id, template_id)


@router.post(
    "/documents/{doc_id}/extract",
    response_model=DocumentOut,
    response_model_by_alias=True,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Re-run VLM structured extraction on one document",
)
def extract_document(ctx: _DbCtx, doc_id: uuid.UUID) -> DocumentOut:
    db, _ = ctx
    return service.extract_document(db, doc_id)


@router.post(
    "/documents/extract-missing",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Enqueue VLM extraction for all completed docs without structured data",
)
def extract_missing(ctx: _DbCtx) -> dict[str, int]:
    db, _ = ctx
    count = service.extract_missing(db)
    return {"enqueued": count}


# ---- Dashboard (separate prefix registered in main.py) ----


@dashboard_router.get(
    "/dashboard",
    response_model=DashboardOut,
    response_model_by_alias=True,
    summary="Dashboard stats, recent docs, and activity feed",
)
def get_dashboard(ctx: _DbCtx) -> DashboardOut:
    db, _ = ctx
    return service.get_dashboard(db)
