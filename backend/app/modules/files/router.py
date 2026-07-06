"""Files module router — document ingestion and retrieval endpoints."""

import datetime
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile, status
from sqlalchemy.orm import Session

from app.core.deps import get_tenant_db
from app.core.security import TokenData
from app.modules.files import service
from app.modules.files.schemas import (
    BulkSetTypeIn,
    BulkTagIn,
    BulkTrashIn,
    DashboardOut,
    DocumentListOut,
    DocumentOut,
    DocumentPatchIn,
)

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
    tag_id: uuid.UUID | None = None,
    correspondent_id: uuid.UUID | None = None,
    date_from: datetime.date | None = None,
    date_to: datetime.date | None = None,
    inbox: bool = False,
    q: str | None = None,
    sort: str = "date_desc",
    page: int = 1,
    trashed: bool = False,
) -> DocumentListOut:
    db, _ = ctx
    return service.list_documents(
        db,
        status_filter=status_q,
        type_filter=type_q,
        tag_id=tag_id,
        correspondent_id=correspondent_id,
        date_from=date_from,
        date_to=date_to,
        inbox=inbox,
        q=q,
        sort=sort,
        page=max(1, page),
        trashed=trashed,
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


@router.get(
    "/documents/{doc_id}/thumbnail",
    summary="Return a short-lived signed thumbnail URL (404 if none was generated)",
)
def get_document_thumbnail(ctx: _DbCtx, doc_id: uuid.UUID) -> dict[str, str]:
    db, _ = ctx
    url = service.get_thumbnail_url(db, doc_id)
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
    template_id: uuid.UUID | None = Query(None),
    document_type_id: uuid.UUID | None = Query(None)
) -> DocumentOut:
    db, _ = ctx
    return service.reprocess_document(db, doc_id, template_id, document_type_id)


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


@router.post(
    "/documents/empty-trash",
    status_code=status.HTTP_200_OK,
    summary="Permanently delete all trashed documents and their storage objects",
)
def empty_trash(ctx: _DbCtx) -> dict[str, int]:
    db, user = ctx
    deleted = service.empty_trash(db, user)
    return {"deleted": deleted}


@router.post(
    "/documents/bulk-trash",
    status_code=status.HTTP_200_OK,
    summary="Soft-delete multiple documents in one call",
)
def bulk_trash(ctx: _DbCtx, body: BulkTrashIn) -> dict[str, int]:
    db, user = ctx
    count = service.bulk_trash(db, user, body.document_ids)
    return {"updated": count}


@router.post(
    "/documents/bulk-tag",
    status_code=status.HTTP_200_OK,
    summary="Assign or remove a tag on multiple documents",
)
def bulk_tag(ctx: _DbCtx, body: BulkTagIn) -> dict[str, int]:
    db, user = ctx
    tenant_id = uuid.UUID(user.tenant_id)
    if body.action == "assign":
        count = service.bulk_tag_assign(db, tenant_id, body.document_ids, body.tag_id)
    else:
        count = service.bulk_tag_remove(db, body.document_ids, body.tag_id)
    return {"updated": count}


@router.post(
    "/documents/bulk-set-type",
    status_code=status.HTTP_200_OK,
    summary="Set document_type on multiple documents",
)
def bulk_set_type(ctx: _DbCtx, body: BulkSetTypeIn) -> dict[str, int]:
    db, _ = ctx
    count = service.bulk_set_type(db, body.document_ids, body.document_type)
    return {"updated": count}


@router.patch(
    "/documents/{doc_id}",
    response_model=DocumentOut,
    response_model_by_alias=True,
    summary="Update editable metadata (title, document_type, document_date)",
)
def patch_document(
    ctx: _DbCtx, doc_id: uuid.UUID, patch: DocumentPatchIn
) -> DocumentOut:
    db, user = ctx
    return service.patch_document(db, user, doc_id, patch)


@router.delete(
    "/documents/{doc_id}",
    response_model=DocumentOut,
    response_model_by_alias=True,
    summary="Move a document to the trash (soft-delete)",
)
def trash_document(ctx: _DbCtx, doc_id: uuid.UUID) -> DocumentOut:
    db, user = ctx
    return service.trash_document(db, user, doc_id)


@router.post(
    "/documents/{doc_id}/restore",
    response_model=DocumentOut,
    response_model_by_alias=True,
    summary="Restore a trashed document",
)
def restore_document(ctx: _DbCtx, doc_id: uuid.UUID) -> DocumentOut:
    db, user = ctx
    return service.restore_document(db, user, doc_id)


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
