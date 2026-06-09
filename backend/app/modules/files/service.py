"""Files module — business logic for document ingestion, retrieval, and dashboard."""

import uuid

from fastapi import HTTPException, UploadFile, status
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.core import storage as object_storage
from app.core.config import settings
from app.core.security import TokenData
from app.models.activity_event import ACT_DOWNLOAD, ACT_UPLOAD, ActivityEvent
from app.models.document import (
    STATUS_COMPLETED,
    STATUS_FAILED,
    STATUS_QUEUED,
    Document,
)
from app.models.processing_job import JOB_QUEUED, ProcessingJob
from app.models.tenant import Tenant
from app.models.user import User
from app.modules.files.schemas import (
    ActivityOut,
    DashboardOut,
    DashboardStats,
    DocumentListOut,
    DocumentOut,
)

ALLOWED_MIMES: dict[str, str] = {
    "application/pdf": "pdf",
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
    "image/tiff": "tif",
}

_PAGE_SIZE = 20


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _user_name(db: Session, user_id: uuid.UUID) -> str:
    """Return a user's display name; falls back to the UUID string on miss."""
    row = db.get(User, user_id)
    return row.name if row else str(user_id)


def _names_for_ids(db: Session, user_ids: set[uuid.UUID]) -> dict[uuid.UUID, str]:
    """Batch-fetch display names for a set of user UUIDs (single query)."""
    if not user_ids:
        return {}
    rows = db.execute(select(User.id, User.name).where(User.id.in_(user_ids))).all()
    return {row.id: row.name for row in rows}


def _doc_to_out(doc: Document, uploader_name: str) -> DocumentOut:
    return DocumentOut(
        id=doc.id,
        tenant_id=doc.tenant_id,
        filename=doc.filename,
        original_filename=doc.original_filename,
        document_type=doc.document_type,
        mime_type=doc.mime_type,
        size_bytes=doc.size_bytes,
        status=doc.status,
        uploaded_by=uploader_name,
        uploaded_at=doc.uploaded_at,
        processed_at=doc.processed_at,
        page_count=doc.page_count,
        has_text_layer=doc.has_text_layer,
        ocr_confidence=doc.ocr_confidence,
        extracted_data=doc.extracted_data,
        tags=doc.tags or [],
        storage_key=doc.storage_key,
    )


def _evt_to_out(evt: ActivityEvent) -> ActivityOut:
    return ActivityOut(
        id=evt.id,
        type=evt.type,
        document_id=evt.document_id,
        document_name=evt.document_name,
        user_id=evt.user_id,
        user_name=evt.user_name,
        timestamp=evt.timestamp,
        meta=evt.meta,
    )


# ---------------------------------------------------------------------------
# Service functions
# ---------------------------------------------------------------------------


def create_documents(
    db: Session,
    user: TokenData,
    uploads: list[UploadFile],
    type_hints: list[str],
) -> DocumentListOut:
    """Validate, store in object storage, and register uploaded files.

    Each file gets a ProcessingJob (queued) and an upload ActivityEvent.
    Worker enqueue is deferred to Milestone C; jobs stay queued until then.
    """
    max_bytes = settings.max_upload_mb * 1024 * 1024
    tenant_id = uuid.UUID(user.tenant_id)  # type: ignore[arg-type]
    uploader_id = uuid.UUID(user.user_id)
    uploader_name = _user_name(db, uploader_id)

    created: list[Document] = []
    total_size = 0

    for upload, type_hint in zip(uploads, type_hints):
        content_type = (upload.content_type or "").split(";")[0].strip()
        ext = ALLOWED_MIMES.get(content_type)
        if ext is None:
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail=(
                    f"File '{upload.filename}': unsupported type '{content_type}'. "
                    f"Allowed: {', '.join(ALLOWED_MIMES)}"
                ),
            )

        data = upload.file.read()
        if len(data) > max_bytes:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=(
                    f"File '{upload.filename}' exceeds the {settings.max_upload_mb} MB limit."
                ),
            )

        doc_id = uuid.uuid4()
        safe_name = upload.filename or f"document_{doc_id}.{ext}"
        storage_key = f"{tenant_id}/docs/{doc_id}.{ext}"

        object_storage.upload_file(storage_key, data, content_type)
        total_size += len(data)

        doc = Document(
            id=doc_id,
            tenant_id=tenant_id,
            filename=safe_name,
            original_filename=safe_name,
            mime_type=content_type,
            size_bytes=len(data),
            storage_key=storage_key,
            status=STATUS_QUEUED,
            document_type=type_hint or "other",
            uploaded_by=uploader_id,
        )
        db.add(doc)
        db.flush()  # populate doc.id for FK references

        db.add(ProcessingJob(
            tenant_id=tenant_id,
            document_id=doc.id,
            status=JOB_QUEUED,
        ))
        db.add(ActivityEvent(
            tenant_id=tenant_id,
            type=ACT_UPLOAD,
            document_id=doc.id,
            document_name=safe_name,
            user_id=uploader_id,
            user_name=uploader_name,
        ))
        created.append(doc)

    if total_size > 0:
        db.execute(
            update(Tenant)
            .where(Tenant.id == tenant_id)
            .values(storage_used_bytes=Tenant.storage_used_bytes + total_size)
        )
    db.flush()

    items = [_doc_to_out(doc, uploader_name) for doc in created]
    return DocumentListOut(items=items, total=len(items), page=1, page_size=len(items))


def list_documents(
    db: Session,
    *,
    status_filter: str | None = None,
    type_filter: str | None = None,
    q: str | None = None,
    sort: str = "date_desc",
    page: int = 1,
) -> DocumentListOut:
    """Return a paginated, filtered page of documents for the current tenant.

    RLS automatically scopes the query to the tenant set by the GUC.
    """
    stmt = select(Document)

    if status_filter:
        stmt = stmt.where(Document.status == status_filter)
    if type_filter:
        stmt = stmt.where(Document.document_type == type_filter)
    if q:
        stmt = stmt.where(Document.original_filename.ilike(f"%{q}%"))

    _sort_map = {
        "date_desc": Document.uploaded_at.desc(),
        "date_asc": Document.uploaded_at.asc(),
        "name_asc": Document.original_filename.asc(),
        "name_desc": Document.original_filename.desc(),
        "size_asc": Document.size_bytes.asc(),
        "size_desc": Document.size_bytes.desc(),
    }
    stmt = stmt.order_by(_sort_map.get(sort, Document.uploaded_at.desc()))

    total: int = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0

    offset = (page - 1) * _PAGE_SIZE
    rows = db.scalars(stmt.offset(offset).limit(_PAGE_SIZE)).all()

    names = _names_for_ids(db, {doc.uploaded_by for doc in rows})
    items = [_doc_to_out(doc, names.get(doc.uploaded_by, str(doc.uploaded_by))) for doc in rows]

    return DocumentListOut(items=items, total=total, page=page, page_size=_PAGE_SIZE)


def get_document(db: Session, doc_id: uuid.UUID) -> DocumentOut:
    """Fetch a single document. 404 if not found or belongs to another tenant (RLS)."""
    doc = db.get(Document, doc_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found.")
    return _doc_to_out(doc, _user_name(db, doc.uploaded_by))


def get_download_url(db: Session, user: TokenData, doc_id: uuid.UUID) -> str:
    """Return a signed download URL and record a download activity event."""
    doc = db.get(Document, doc_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found.")

    url = object_storage.create_signed_url(doc.storage_key)

    downloader_id = uuid.UUID(user.user_id)
    db.add(ActivityEvent(
        tenant_id=doc.tenant_id,
        type=ACT_DOWNLOAD,
        document_id=doc.id,
        document_name=doc.original_filename,
        user_id=downloader_id,
        user_name=_user_name(db, downloader_id),
    ))
    db.flush()
    return url


def retry_document(db: Session, doc_id: uuid.UUID) -> DocumentOut:
    """Reset a failed document back to queued. 400 if not in failed state."""
    doc = db.get(Document, doc_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found.")
    if doc.status != STATUS_FAILED:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot retry a document in status '{doc.status}'. Only 'failed' documents can be retried.",
        )
    doc.status = STATUS_QUEUED
    doc.error_message = None
    db.flush()
    return _doc_to_out(doc, _user_name(db, doc.uploaded_by))


def get_dashboard(db: Session) -> DashboardOut:
    """Aggregate dashboard data: counts, storage, recent docs, and activity feed."""
    # Status breakdown (RLS-scoped)
    count_rows = db.execute(
        select(Document.status, func.count(Document.id)).group_by(Document.status)
    ).all()
    by_status: dict[str, int] = {row[0]: row[1] for row in count_rows}
    total = sum(by_status.values())
    processed = by_status.get(STATUS_COMPLETED, 0)
    failed = by_status.get(STATUS_FAILED, 0)
    in_pipeline = total - processed - failed

    # Tenant storage — RLS returns only the current tenant's row
    tenant_row = db.execute(
        select(Tenant.storage_used_bytes, Tenant.storage_limit_bytes).limit(1)
    ).first()
    storage_used = int(tenant_row[0]) if tenant_row else 0
    storage_limit = int(tenant_row[1]) if tenant_row else Tenant.storage_limit_bytes.default.arg  # type: ignore[union-attr]

    # Recent 5 documents
    recent_docs = db.scalars(
        select(Document).order_by(Document.uploaded_at.desc()).limit(5)
    ).all()
    names = _names_for_ids(db, {doc.uploaded_by for doc in recent_docs})
    recent_out = [
        _doc_to_out(doc, names.get(doc.uploaded_by, str(doc.uploaded_by)))
        for doc in recent_docs
    ]

    # Latest 6 activity events
    events = db.scalars(
        select(ActivityEvent).order_by(ActivityEvent.timestamp.desc()).limit(6)
    ).all()

    return DashboardOut(
        stats=DashboardStats(
            total_documents=total,
            processed=processed,
            in_pipeline=in_pipeline,
            failed=failed,
            storage_used_bytes=storage_used,
            storage_limit_bytes=storage_limit,
            documents_count=total,
        ),
        recent_documents=recent_out,
        activity=[_evt_to_out(e) for e in events],
    )
