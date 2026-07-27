"""Files module — business logic for document ingestion, retrieval, and dashboard."""

import datetime
import hashlib
import json
import logging
import uuid

from fastapi import HTTPException, UploadFile, status
from sqlalchemy import Date, Numeric, cast, delete, func, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.core import storage as object_storage
from app.core.config import settings
from app.core.security import TokenData
from app.models.activity_event import (
    ACT_DOWNLOAD,
    ACT_EDIT,
    ACT_PERMANENT_DELETE,
    ACT_RESTORE,
    ACT_TRASH,
    ACT_UPLOAD,
    ActivityEvent,
)
from app.models.document import (
    STATUS_COMPLETED,
    STATUS_FAILED,
    STATUS_NEEDS_REVIEW,
    STATUS_QUEUED,
    Document,
)
from app.models.custom_field import CustomField, DocumentFieldValue
from app.models.processing_job import JOB_QUEUED, ProcessingJob
from app.models.tenant import Tenant
from app.models.user import User
from app.models.correspondent import Correspondent
from app.models.tag import DocumentTag, Tag
from app.modules.files import retention
from app.modules.files.schemas import (
    ActivityListOut,
    ActivityOut,
    CorrespondentOut,
    DashboardOut,
    DashboardStats,
    DocumentListOut,
    DocumentOut,
    DocumentPatchIn,
    FieldValueOut,
    TagOut,
)
from app.modules.metadata.schemas import CustomFieldIn, FieldValueIn, PredefinedFieldIn
from app.modules.metadata.service import (
    add_predefined_field,
    create_custom_field,
    fetch_field_values_for_docs,
    set_field_value,
)
from app.modules.idp import mimetype
from app.modules.idp.queue import enqueue_ai_extraction, enqueue_document
from app.modules.search.query import apply_text_search, build_search_text

logger = logging.getLogger(__name__)

# Sniffed-mime -> storage extension. Source of truth lives in idp/mimetype.py
# so the worker's parser registry and the upload allow-list never drift apart.
ALLOWED_MIMES: dict[str, str] = mimetype.ALLOWED_MIMES

_PAGE_SIZE = 20
_EXTRACT_MISSING_BATCH_LIMIT = 100
# Per-request file-count cap (Level 1 production hardening). Generous enough
# for a real batch upload (e.g. a folder of a month's invoices) while bounding
# the cost of one request — per-file size + total storage quota are checked
# separately and don't protect against "many small files" flooding.
_MAX_FILES_PER_UPLOAD = 50


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


def _fetch_tags_for_docs(db: Session, doc_ids: list[uuid.UUID]) -> dict[uuid.UUID, list[TagOut]]:
    """Batch-fetch tag assignments for a list of doc IDs (single query, no N+1)."""
    if not doc_ids:
        return {}
    rows = db.execute(
        select(DocumentTag.document_id, Tag.id, Tag.name, Tag.color)
        .join(Tag, Tag.id == DocumentTag.tag_id)
        .where(DocumentTag.document_id.in_(doc_ids))
    ).all()
    result: dict[uuid.UUID, list[TagOut]] = {}
    for row in rows:
        result.setdefault(row.document_id, []).append(
            TagOut(id=row.id, name=row.name, color=row.color)
        )
    return result


def _fetch_correspondents_for_ids(
    db: Session, correspondent_ids: set[uuid.UUID]
) -> dict[uuid.UUID, CorrespondentOut]:
    """Batch-fetch correspondents by id (single query)."""
    if not correspondent_ids:
        return {}
    rows = db.execute(
        select(Correspondent.id, Correspondent.name).where(Correspondent.id.in_(correspondent_ids))
    ).all()
    return {row.id: CorrespondentOut(id=row.id, name=row.name) for row in rows}


def _check_storage_quota(db: Session, tenant_id: uuid.UUID, incoming_bytes: int) -> None:
    """Reject the batch if it would push the tenant over its storage quota.

    Free-tier tripwire: checked before any storage write or DB row for the
    batch, so a rejected upload never leaves an orphaned object or partial batch.
    """
    if incoming_bytes <= 0:
        return
    row = db.execute(
        select(Tenant.storage_used_bytes, Tenant.storage_limit_bytes).where(Tenant.id == tenant_id)
    ).first()
    if row is None:
        return
    used, limit = int(row[0]), int(row[1])
    if used + incoming_bytes > limit:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=(
                f"Storage quota exceeded: {used} of {limit} bytes used, "
                f"this upload needs {incoming_bytes} more."
            ),
        )


def _apply_upload_time_fields(
    db: Session,
    tenant_id: uuid.UUID,
    doc: Document,
    field_values_json: str,
    new_fields_json: str,
    attach_fields_json: str = "",
) -> None:
    """Create/attach ad-hoc fields and set values from the upload popup (Level 6).

    Best-effort by design: any parse/validation failure is logged and skipped,
    never raised — a bad field value must never prevent the document itself
    from archiving (CLAUDE.md's "ingestion never blocks" rule).
    """
    if attach_fields_json:
        try:
            to_attach = json.loads(attach_fields_json)
        except (json.JSONDecodeError, TypeError) as exc:
            logger.warning("doc=%s: could not parse attach_fields JSON: %s", doc.id, exc)
            to_attach = []
        for spec in to_attach:
            try:
                field_id = uuid.UUID(spec["fieldId"])
                try:
                    add_predefined_field(
                        db, tenant_id, doc.document_type, PredefinedFieldIn(field_id=field_id)
                    )
                except HTTPException as exc:
                    # 409 = already predefined for this type (e.g. picked twice,
                    # or attached by someone else meanwhile) — not an error, the
                    # field is attached either way, so still set its value below.
                    if exc.status_code != status.HTTP_409_CONFLICT:
                        raise
                if "value" in spec:
                    set_field_value(
                        db, tenant_id, doc.id, field_id, FieldValueIn(value=spec["value"])
                    )
            except (HTTPException, KeyError, TypeError, ValueError) as exc:
                logger.warning("doc=%s: could not attach existing field %r: %s", doc.id, spec, exc)

    if new_fields_json:
        try:
            new_fields = json.loads(new_fields_json)
        except (json.JSONDecodeError, TypeError) as exc:
            logger.warning("doc=%s: could not parse new_fields JSON: %s", doc.id, exc)
            new_fields = []
        for spec in new_fields:
            try:
                created = create_custom_field(
                    db,
                    tenant_id,
                    CustomFieldIn(
                        name=spec["name"],
                        field_type=spec["fieldType"],
                        options=spec.get("options", []),
                    ),
                )
                add_predefined_field(
                    db, tenant_id, doc.document_type, PredefinedFieldIn(field_id=created.id)
                )
                # The frontend can't know the new field's server-generated id
                # ahead of time to reference it in field_values, so a filled-in
                # value for a brand-new field rides along on the same spec.
                if "value" in spec:
                    set_field_value(
                        db, tenant_id, doc.id, created.id, FieldValueIn(value=spec["value"])
                    )
            except (HTTPException, KeyError, TypeError) as exc:
                logger.warning("doc=%s: could not create ad-hoc field %r: %s", doc.id, spec, exc)

    if field_values_json:
        try:
            values: dict[str, object] = json.loads(field_values_json)
        except (json.JSONDecodeError, TypeError) as exc:
            logger.warning("doc=%s: could not parse field_values JSON: %s", doc.id, exc)
            values = {}
        for field_id_str, value in values.items():
            try:
                field_id = uuid.UUID(field_id_str)
                set_field_value(db, tenant_id, doc.id, field_id, FieldValueIn(value=value))
            except (HTTPException, ValueError) as exc:
                logger.warning("doc=%s: could not set field %s: %s", doc.id, field_id_str, exc)


def _doc_to_out(
    doc: Document,
    uploader_name: str,
    tags: list[TagOut] | None = None,
    correspondent: CorrespondentOut | None = None,
    custom_field_values: list[FieldValueOut] | None = None,
) -> DocumentOut:
    return DocumentOut(
        id=doc.id,
        tenant_id=doc.tenant_id,
        filename=doc.filename,
        original_filename=doc.original_filename,
        title=doc.title or doc.original_filename,
        document_type=doc.document_type,
        mime_type=doc.mime_type,
        size_bytes=doc.size_bytes,
        status=doc.status,
        uploaded_by=uploader_name,
        uploaded_at=doc.uploaded_at,
        processed_at=doc.processed_at,
        document_date=doc.document_date,
        page_count=doc.page_count,
        has_text_layer=doc.has_text_layer,
        ocr_confidence=doc.ocr_confidence,
        confidence=doc.confidence,
        extracted_data=doc.extracted_data,
        extracted_text=doc.extracted_text,
        tags=tags or [],
        correspondent=correspondent,
        custom_field_values=custom_field_values or [],
        storage_key=doc.storage_key,
        has_thumbnail=doc.thumbnail_key is not None,
        deleted_at=doc.deleted_at,
        duplicate_of_document_id=doc.duplicate_of_document_id,
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
    field_values_raw: list[str] | None = None,
    new_fields_raw: list[str] | None = None,
    attach_fields_raw: list[str] | None = None,
) -> DocumentListOut:
    """Validate, store in object storage, and register uploaded files.

    Each file gets a ProcessingJob (queued) and an upload ActivityEvent.
    Jobs are enqueued on the IDP queue after the DB transaction commits, so
    the worker never races an uncommitted row.

    ``field_values_raw``/``new_fields_raw``/``attach_fields_raw`` are optional
    per-file JSON strings from the upload popup (Level 6 — predefined fields):
    the first a ``{field_id: value}`` object of values to set, the second a
    ``[{name, fieldType, options}]`` array of brand-new catalog fields to
    create and auto-attach as predefined for that file's document type, the
    third a ``[{fieldId, value}]`` array of already-existing catalog fields to
    attach as predefined and set a value for. All three are best-effort — a
    malformed entry is logged and skipped so a bad field value can never
    block the document itself from archiving.
    """
    if len(uploads) > _MAX_FILES_PER_UPLOAD:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=(
                f"Too many files in one request ({len(uploads)}). "
                f"Upload at most {_MAX_FILES_PER_UPLOAD} at a time."
            ),
        )

    max_bytes = settings.max_upload_mb * 1024 * 1024
    tenant_id = uuid.UUID(user.tenant_id)  # type: ignore[arg-type]
    uploader_id = uuid.UUID(user.user_id)
    uploader_name = _user_name(db, uploader_id)

    # Pad the per-file field extras to match uploads, same as type_hints.
    field_values_list = list(field_values_raw or [])
    if len(field_values_list) < len(uploads):
        field_values_list += [""] * (len(uploads) - len(field_values_list))
    new_fields_list = list(new_fields_raw or [])
    if len(new_fields_list) < len(uploads):
        new_fields_list += [""] * (len(uploads) - len(new_fields_list))
    attach_fields_list = list(attach_fields_raw or [])
    if len(attach_fields_list) < len(uploads):
        attach_fields_list += [""] * (len(uploads) - len(attach_fields_list))

    # Pass 1: sniff the real type from content (never the client-declared
    # content-type or filename — see idp/mimetype.py), validate size, and
    # compute a checksum for every file before writing anything, so a
    # rejection never leaves an orphaned storage object.
    validated: list[tuple[UploadFile, str, bytes, str, str, str, str, str, str]] = []
    for upload, type_hint, field_values_json, new_fields_json, attach_fields_json in zip(
        uploads, type_hints, field_values_list, new_fields_list, attach_fields_list
    ):
        data = upload.file.read()
        sniffed = mimetype.sniff_mime(data, upload.filename)
        ext = ALLOWED_MIMES.get(sniffed) if sniffed else None
        if ext is None:
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail=(
                    f"File '{upload.filename}': unrecognized or unsupported type. "
                    f"Allowed: {', '.join(sorted(set(ALLOWED_MIMES.values())))}"
                ),
            )
        if len(data) > max_bytes:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=(f"File '{upload.filename}' exceeds the {settings.max_upload_mb} MB limit."),
            )
        checksum = hashlib.sha256(data).hexdigest()
        validated.append(
            (
                upload,
                type_hint,
                data,
                sniffed,
                ext,
                checksum,
                field_values_json,
                new_fields_json,
                attach_fields_json,
            )
        )

    # Dedup against this tenant's existing documents AND within the same
    # batch (uploading the same file twice in one request). Duplicates are
    # skipped, not rejected — the rest of the batch still archives normally.
    checksums = [v[5] for v in validated]
    existing_checksums: set[str] = set()
    if checksums:
        rows = db.execute(
            select(Document.checksum).where(
                Document.tenant_id == tenant_id,
                Document.checksum.in_(checksums),
            )
        ).all()
        existing_checksums = {row[0] for row in rows}

    duplicates: list[str] = []
    deduped: list[tuple[UploadFile, str, bytes, str, str, str, str, str, str]] = []
    seen_in_batch: set[str] = set()
    for (
        upload,
        type_hint,
        data,
        sniffed,
        ext,
        checksum,
        field_values_json,
        new_fields_json,
        attach_fields_json,
    ) in validated:
        if checksum in existing_checksums or checksum in seen_in_batch:
            duplicates.append(upload.filename or "unnamed")
            continue
        seen_in_batch.add(checksum)
        deduped.append(
            (
                upload,
                type_hint,
                data,
                sniffed,
                ext,
                checksum,
                field_values_json,
                new_fields_json,
                attach_fields_json,
            )
        )

    incoming_total = sum(len(data) for _, _, data, *_ in deduped)
    _check_storage_quota(db, tenant_id, incoming_total)

    created: list[Document] = []
    total_size = 0

    for (
        upload,
        type_hint,
        data,
        sniffed,
        ext,
        checksum,
        field_values_json,
        new_fields_json,
        attach_fields_json,
    ) in deduped:
        doc_id = uuid.uuid4()
        safe_name = upload.filename or f"document_{doc_id}.{ext}"
        storage_key = f"{tenant_id}/docs/{doc_id}.{ext}"

        object_storage.upload_file(storage_key, data, sniffed)
        total_size += len(data)

        doc = Document(
            id=doc_id,
            tenant_id=tenant_id,
            filename=safe_name,
            original_filename=safe_name,
            title=safe_name,
            mime_type=sniffed,
            size_bytes=len(data),
            storage_key=storage_key,
            checksum=checksum,
            status=STATUS_QUEUED,
            document_type=type_hint or "other",
            uploaded_by=uploader_id,
        )
        db.add(doc)
        db.flush()  # populate doc.id for FK references
        _apply_upload_time_fields(
            db, tenant_id, doc, field_values_json, new_fields_json, attach_fields_json
        )

        db.add(
            ProcessingJob(
                tenant_id=tenant_id,
                document_id=doc.id,
                status=JOB_QUEUED,
            )
        )
        db.add(
            ActivityEvent(
                tenant_id=tenant_id,
                type=ACT_UPLOAD,
                document_id=doc.id,
                document_name=safe_name,
                user_id=uploader_id,
                user_name=uploader_name,
            )
        )
        created.append(doc)

    if total_size > 0:
        db.execute(
            update(Tenant)
            .where(Tenant.id == tenant_id)
            .values(storage_used_bytes=Tenant.storage_used_bytes + total_size)
        )
    db.flush()

    items = [_doc_to_out(doc, uploader_name) for doc in created]

    # Enqueue after building the response so any serialisation error can't
    # silently drop the job. RQ Retry(max=3) handles the upload→commit race
    # on the rare occasion the worker starts before the DB commits.
    for doc in created:
        enqueue_document(doc.id, tenant_id)

    return DocumentListOut(
        items=items, total=len(items), page=1, page_size=len(items), duplicates=duplicates
    )


def resolve_custom_field_type(db: Session, custom_field_id: uuid.UUID | None) -> str | None:
    """Look up a custom field's type for ``build_document_query``.

    Kept as a separate, caller-invoked step (not done inside the query
    builder) so ``build_document_query`` stays a pure, session-free builder —
    every other filter it applies is just column comparisons, no DB access.
    """
    if custom_field_id is None:
        return None
    field = db.get(CustomField, custom_field_id)
    return field.field_type if field else None


def build_document_query(
    *,
    status_filter: str | None = None,
    type_filter: str | None = None,
    tag_id: uuid.UUID | None = None,
    correspondent_id: uuid.UUID | None = None,
    date_from: datetime.date | None = None,
    date_to: datetime.date | None = None,
    amount_min: float | None = None,
    amount_max: float | None = None,
    vendor: str | None = None,
    inbox: bool = False,
    q: str | None = None,
    trashed: bool = False,
    custom_field_id: uuid.UUID | None = None,
    custom_field_type: str | None = None,
    custom_field_value: str | None = None,
    custom_field_min: float | None = None,
    custom_field_max: float | None = None,
    custom_field_date_from: datetime.date | None = None,
    custom_field_date_to: datetime.date | None = None,
):
    """Shared WHERE-clause builder for ``list_documents`` and the export
    endpoint (Level 3) — the two must never drift on what counts as
    "matching the filters". Returns ``(stmt, rank_order_or_None)``; callers
    apply their own ORDER BY/pagination on top.

    ``custom_field_type`` must be resolved by the caller via
    ``resolve_custom_field_type`` (never trust a client-supplied type — it
    decides exact-vs-partial matching, so it has to come from the DB)."""
    stmt = select(Document)

    if trashed:
        stmt = stmt.where(Document.deleted_at.is_not(None))
    else:
        stmt = stmt.where(Document.deleted_at.is_(None))

    if status_filter:
        stmt = stmt.where(Document.status == status_filter)
    if type_filter:
        stmt = stmt.where(Document.document_type == type_filter)
    if tag_id is not None:
        stmt = stmt.join(DocumentTag, DocumentTag.document_id == Document.id).where(
            DocumentTag.tag_id == tag_id
        )
    if correspondent_id is not None:
        stmt = stmt.where(Document.correspondent_id == correspondent_id)
    if date_from is not None or date_to is not None:
        # Filters on uploaded_at, not document_date: most documents never get
        # a detected document_date (non-invoice types, or the heuristic simply
        # found nothing), and uploaded_at is never null — a simpler, always-
        # reliable filter than trying to fall back between the two. Matches
        # the frontend list's date column, which shows uploaded_at only.
        effective_date = func.cast(Document.uploaded_at, Date)
        if date_from is not None:
            stmt = stmt.where(effective_date >= date_from)
        if date_to is not None:
            stmt = stmt.where(effective_date <= date_to)
    if amount_min is not None:
        stmt = stmt.where(Document.total_amount >= amount_min)
    if amount_max is not None:
        stmt = stmt.where(Document.total_amount <= amount_max)
    if vendor:
        stmt = stmt.where(Document.vendor.ilike(f"%{vendor}%"))
    if inbox:
        # Subquery avoids join conflict with tag_id filter
        inbox_subq = (
            select(DocumentTag.document_id)
            .join(Tag, Tag.id == DocumentTag.tag_id)
            .where(Tag.is_inbox_tag.is_(True))
        )
        stmt = stmt.where(Document.id.in_(inbox_subq))
    if custom_field_id is not None:
        # JSONB values need the Postgres "as text" extraction (#>>'{}') before
        # ILIKE/cast comparisons — .astext isn't available on a whole (un-indexed)
        # JSONB column in SQLAlchemy, only on an indexed sub-value.
        astext = DocumentFieldValue.value.op("#>>")(text("'{}'"))
        conditions = [DocumentFieldValue.field_id == custom_field_id]
        has_value_condition = False
        if custom_field_type in ("select", "boolean"):
            # Exact match — a blind ILIKE would let "Travel" match "International
            # Travel" for a fixed-option field, which is never the intent.
            if custom_field_value is not None:
                conditions.append(astext == custom_field_value)
                has_value_condition = True
        else:
            # text, number, or an unresolved/unknown type — partial "Contains"
            # match when a value is given. Also lets a reference-number-style
            # field (e.g. "Order Number") be found by typing a few remembered
            # digits, rather than forcing a min/max range on something that
            # isn't really a quantity.
            if custom_field_value is not None:
                conditions.append(astext.ilike(f"%{custom_field_value}%"))
                has_value_condition = True
            if custom_field_type == "number":
                if custom_field_min is not None:
                    conditions.append(cast(astext, Numeric) >= custom_field_min)
                    has_value_condition = True
                if custom_field_max is not None:
                    conditions.append(cast(astext, Numeric) <= custom_field_max)
                    has_value_condition = True
            elif custom_field_type == "date":
                if custom_field_date_from is not None:
                    conditions.append(cast(astext, Date) >= custom_field_date_from)
                    has_value_condition = True
                if custom_field_date_to is not None:
                    conditions.append(cast(astext, Date) <= custom_field_date_to)
                    has_value_condition = True
        if has_value_condition:
            subq = select(DocumentFieldValue.document_id).where(*conditions)
            stmt = stmt.where(Document.id.in_(subq))

    # When a query is present, match on full-text content OR fuzzy filename
    # (shared with /search so ranking is identical). Otherwise plain browse.
    rank_order = None
    if q and q.strip():
        stmt, rank_expr = apply_text_search(stmt, q.strip())
        rank_order = rank_expr.desc()

    return stmt, rank_order


def list_documents(
    db: Session,
    *,
    tenant_id: uuid.UUID | None = None,
    status_filter: str | None = None,
    type_filter: str | None = None,
    tag_id: uuid.UUID | None = None,
    correspondent_id: uuid.UUID | None = None,
    date_from: datetime.date | None = None,
    date_to: datetime.date | None = None,
    amount_min: float | None = None,
    amount_max: float | None = None,
    vendor: str | None = None,
    inbox: bool = False,
    q: str | None = None,
    sort: str = "date_desc",
    page: int = 1,
    trashed: bool = False,
    custom_field_id: uuid.UUID | None = None,
    custom_field_value: str | None = None,
    custom_field_min: float | None = None,
    custom_field_max: float | None = None,
    custom_field_date_from: datetime.date | None = None,
    custom_field_date_to: datetime.date | None = None,
) -> DocumentListOut:
    """Return a paginated, filtered page of documents for the current tenant.

    RLS automatically scopes the query to the tenant set by the GUC.
    By default only live (non-trashed) documents are returned; pass
    ``trashed=True`` to list the trash instead.

    Viewing the trash is also the opportunistic trigger point for auto-
    retention (see ``files/retention.py`` — rate-limited to ~once/day, so this
    is a no-op on almost every call).
    """
    if trashed and tenant_id is not None:
        retention.maybe_purge_expired_trash(db, tenant_id)

    stmt, rank_order = build_document_query(
        status_filter=status_filter,
        type_filter=type_filter,
        tag_id=tag_id,
        correspondent_id=correspondent_id,
        date_from=date_from,
        date_to=date_to,
        amount_min=amount_min,
        amount_max=amount_max,
        vendor=vendor,
        inbox=inbox,
        q=q,
        trashed=trashed,
        custom_field_id=custom_field_id,
        custom_field_type=resolve_custom_field_type(db, custom_field_id),
        custom_field_value=custom_field_value,
        custom_field_min=custom_field_min,
        custom_field_max=custom_field_max,
        custom_field_date_from=custom_field_date_from,
        custom_field_date_to=custom_field_date_to,
    )

    _sort_map = {
        "date_desc": Document.uploaded_at.desc(),
        "date_asc": Document.uploaded_at.asc(),
        "name_asc": Document.original_filename.asc(),
        "name_desc": Document.original_filename.desc(),
        "size_asc": Document.size_bytes.asc(),
        "size_desc": Document.size_bytes.desc(),
    }
    # A search with the default sort orders by relevance; an explicit sort wins.
    if rank_order is not None and sort == "date_desc":
        stmt = stmt.order_by(rank_order, Document.uploaded_at.desc())
    else:
        stmt = stmt.order_by(_sort_map.get(sort, Document.uploaded_at.desc()))

    total: int = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0

    offset = (page - 1) * _PAGE_SIZE
    rows = db.scalars(stmt.offset(offset).limit(_PAGE_SIZE)).all()

    names = _names_for_ids(db, {doc.uploaded_by for doc in rows})
    doc_ids = [doc.id for doc in rows]
    tags_by_doc = _fetch_tags_for_docs(db, doc_ids)
    corresp_ids = {doc.correspondent_id for doc in rows if doc.correspondent_id}
    corresp_by_id = _fetch_correspondents_for_ids(db, corresp_ids)
    field_values_by_doc = fetch_field_values_for_docs(db, doc_ids)

    items = [
        _doc_to_out(
            doc,
            names.get(doc.uploaded_by, str(doc.uploaded_by)),
            tags=tags_by_doc.get(doc.id, []),
            correspondent=corresp_by_id.get(doc.correspondent_id) if doc.correspondent_id else None,
            custom_field_values=field_values_by_doc.get(doc.id, []),
        )
        for doc in rows
    ]

    return DocumentListOut(items=items, total=total, page=page, page_size=_PAGE_SIZE)


def get_document(db: Session, doc_id: uuid.UUID) -> DocumentOut:
    """Fetch a single document. 404 if not found or belongs to another tenant (RLS)."""
    doc = db.get(Document, doc_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found.")
    tags_map = _fetch_tags_for_docs(db, [doc_id])
    corresp: CorrespondentOut | None = None
    if doc.correspondent_id:
        corresp_map = _fetch_correspondents_for_ids(db, {doc.correspondent_id})
        corresp = corresp_map.get(doc.correspondent_id)
    field_values_map = fetch_field_values_for_docs(db, [doc_id])
    return _doc_to_out(
        doc,
        _user_name(db, doc.uploaded_by),
        tags=tags_map.get(doc_id, []),
        correspondent=corresp,
        custom_field_values=field_values_map.get(doc_id, []),
    )


def get_download_url(db: Session, user: TokenData, doc_id: uuid.UUID) -> str:
    """Return a signed download URL and record a download activity event."""
    doc = db.get(Document, doc_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found.")

    url = object_storage.create_signed_url(doc.storage_key)

    downloader_id = uuid.UUID(user.user_id)
    db.add(
        ActivityEvent(
            tenant_id=doc.tenant_id,
            type=ACT_DOWNLOAD,
            document_id=doc.id,
            document_name=doc.original_filename,
            user_id=downloader_id,
            user_name=_user_name(db, downloader_id),
        )
    )
    db.flush()
    return url


def get_preview_url(db: Session, doc_id: uuid.UUID) -> str:
    """Return a signed URL for inline viewing — unlike get_download_url, does NOT
    record a download activity event. The document detail page fetches this on
    every page load just to render the inline preview; logging that as a
    "download" would falsely inflate the audit trail (a real PDPA-relevant
    concern) every time a document is merely viewed, not exported."""
    doc = db.get(Document, doc_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found.")
    return object_storage.create_signed_url(doc.storage_key)


def get_thumbnail_url(db: Session, doc_id: uuid.UUID) -> str:
    """Return a signed URL for a document's thumbnail. 404 if none was generated."""
    doc = db.get(Document, doc_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found.")
    if doc.thumbnail_key is None:
        raise HTTPException(status_code=404, detail="No thumbnail available for this document.")
    return object_storage.create_signed_url(doc.thumbnail_key)


def patch_document(
    db: Session, user: TokenData, doc_id: uuid.UUID, patch: DocumentPatchIn
) -> DocumentOut:
    """Update editable metadata fields on a document.

    Only fields present in the request body are written — absent fields are left
    unchanged.  Send an explicit ``null`` to clear an optional field such as
    ``document_date``.
    """
    doc = db.get(Document, doc_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found.")

    updated_fields = patch.model_fields_set
    if "title" in updated_fields and patch.title is not None:
        doc.title = patch.title
        # Rebuild the search index so the new title is findable and the doc
        # doesn't stay permanently indexed under its stale pre-rename title.
        doc.search_tsv = func.to_tsvector(
            "english",
            build_search_text(doc.title, doc.original_filename, doc.extracted_text),
        )
    if "document_type" in updated_fields and patch.document_type is not None:
        doc.document_type = patch.document_type
    if "document_date" in updated_fields:
        doc.document_date = patch.document_date  # may be None to clear
    if "correspondent_id" in updated_fields:
        if patch.correspondent_id is not None:
            correspondent = db.get(Correspondent, patch.correspondent_id)
            if correspondent is None:
                raise HTTPException(status_code=404, detail="Correspondent not found.")
        doc.correspondent_id = patch.correspondent_id  # may be None to clear
    if "extracted_data_patch" in updated_fields and patch.extracted_data_patch is not None:
        # Shallow-merge: only the supplied keys are overwritten; all other
        # keys in the existing JSONB are preserved.
        merged = dict(doc.extracted_data or {})
        merged.update(patch.extracted_data_patch)
        doc.extracted_data = merged

    editor_id = uuid.UUID(user.user_id)
    db.add(
        ActivityEvent(
            tenant_id=doc.tenant_id,
            type=ACT_EDIT,
            document_id=doc.id,
            document_name=doc.original_filename,
            user_id=editor_id,
            user_name=_user_name(db, editor_id),
        )
    )
    db.flush()
    tags_map = _fetch_tags_for_docs(db, [doc.id])
    corresp: CorrespondentOut | None = None
    if doc.correspondent_id:
        corresp_map = _fetch_correspondents_for_ids(db, {doc.correspondent_id})
        corresp = corresp_map.get(doc.correspondent_id)
    field_values_map = fetch_field_values_for_docs(db, [doc.id])
    return _doc_to_out(
        doc,
        _user_name(db, doc.uploaded_by),
        tags=tags_map.get(doc.id, []),
        correspondent=corresp,
        custom_field_values=field_values_map.get(doc.id, []),
    )


def trash_document(db: Session, user: TokenData, doc_id: uuid.UUID) -> DocumentOut:
    """Soft-delete a document by setting ``deleted_at``.

    409 if the document is already in the trash.
    """
    doc = db.get(Document, doc_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found.")
    if doc.deleted_at is not None:
        raise HTTPException(status_code=409, detail="Document is already in the trash.")

    doc.deleted_at = datetime.datetime.now(tz=datetime.timezone.utc)

    actor_id = uuid.UUID(user.user_id)
    db.add(
        ActivityEvent(
            tenant_id=doc.tenant_id,
            type=ACT_TRASH,
            document_id=doc.id,
            document_name=doc.original_filename,
            user_id=actor_id,
            user_name=_user_name(db, actor_id),
        )
    )
    db.flush()
    return _doc_to_out(doc, _user_name(db, doc.uploaded_by))  # no tag refresh needed for trash


def restore_document(db: Session, user: TokenData, doc_id: uuid.UUID) -> DocumentOut:
    """Restore a soft-deleted document by clearing ``deleted_at``.

    409 if the document is not in the trash.
    """
    doc = db.get(Document, doc_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found.")
    if doc.deleted_at is None:
        raise HTTPException(status_code=409, detail="Document is not in the trash.")

    doc.deleted_at = None

    actor_id = uuid.UUID(user.user_id)
    db.add(
        ActivityEvent(
            tenant_id=doc.tenant_id,
            type=ACT_RESTORE,
            document_id=doc.id,
            document_name=doc.original_filename,
            user_id=actor_id,
            user_name=_user_name(db, actor_id),
        )
    )
    db.flush()
    return _doc_to_out(doc, _user_name(db, doc.uploaded_by))


def permanent_delete_document(db: Session, user: TokenData, doc_id: uuid.UUID) -> None:
    """Hard-delete a single trashed document and its storage objects.

    404 if not found, 409 if it isn't already in the trash — permanent delete
    is only reachable from the trash view, never directly from the active list,
    mirroring the paperless-style soft-delete-first safety net.
    """
    doc = db.get(Document, doc_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found.")
    if doc.deleted_at is None:
        raise HTTPException(
            status_code=409, detail="Document must be trashed before it can be permanently deleted."
        )

    for key in filter(None, [doc.storage_key, doc.thumbnail_key]):
        try:
            object_storage.delete_file(key)
        except Exception:
            pass

    tenant_id = doc.tenant_id
    size_bytes = doc.size_bytes
    actor_id = uuid.UUID(user.user_id)
    db.add(
        ActivityEvent(
            tenant_id=tenant_id,
            type=ACT_PERMANENT_DELETE,
            document_id=doc.id,
            document_name=doc.original_filename,
            user_id=actor_id,
            user_name=_user_name(db, actor_id),
        )
    )
    db.delete(doc)

    if size_bytes > 0:
        db.execute(
            update(Tenant)
            .where(Tenant.id == tenant_id)
            .values(storage_used_bytes=func.greatest(Tenant.storage_used_bytes - size_bytes, 0))
        )
    db.flush()


def empty_trash(db: Session, user: TokenData) -> int:
    """Hard-delete all trashed documents for the current tenant.

    Storage objects are deleted first; any individual storage failure is
    swallowed so a single orphaned object can't block the whole operation.
    Returns the number of documents permanently deleted.
    """
    rows = db.scalars(select(Document).where(Document.deleted_at.is_not(None))).all()

    tenant_id = None
    freed_bytes = 0
    for doc in rows:
        tenant_id = doc.tenant_id
        freed_bytes += doc.size_bytes
        for key in filter(None, [doc.storage_key, doc.thumbnail_key]):
            try:
                object_storage.delete_file(key)
            except Exception:
                pass
        db.delete(doc)

    if freed_bytes > 0 and tenant_id is not None:
        db.execute(
            update(Tenant)
            .where(Tenant.id == tenant_id)
            .values(storage_used_bytes=func.greatest(Tenant.storage_used_bytes - freed_bytes, 0))
        )

    db.flush()
    return len(rows)


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

    enqueue_document(doc.id, doc.tenant_id)

    return _doc_to_out(doc, _user_name(db, doc.uploaded_by))


def extract_document(db: Session, doc_id: uuid.UUID) -> DocumentOut:
    """Enqueue a VLM-only re-extraction for one completed document.

    Returns the document as-is (the extraction runs async). 404 if not found.
    """
    doc = db.get(Document, doc_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found.")

    enqueue_ai_extraction(doc.id, doc.tenant_id)
    return _doc_to_out(doc, _user_name(db, doc.uploaded_by))


def extract_missing(db: Session) -> int:
    """Enqueue VLM re-extraction for docs without structured data.

    Covers both ``completed`` (extraction never attempted/ran clean) and
    ``needs_review`` (attempted, both tiers came up empty) — the latter are
    exactly the backlog this endpoint exists to retry. Bounded to
    ``_EXTRACT_MISSING_BATCH_LIMIT`` per call so a large backlog can't hold
    the request handler open enqueueing thousands of jobs in one go — call
    again to pick up the rest. RLS scopes the query to the current tenant.
    Returns the count enqueued.
    """
    rows = db.scalars(
        select(Document)
        .where(
            Document.status.in_((STATUS_COMPLETED, STATUS_NEEDS_REVIEW)),
            Document.extracted_data.is_(None),
            Document.mime_type.in_(mimetype.VLM_ELIGIBLE_MIMES),
        )
        .limit(_EXTRACT_MISSING_BATCH_LIMIT)
    ).all()
    for doc in rows:
        enqueue_ai_extraction(doc.id, doc.tenant_id)
    return len(rows)


# ---------------------------------------------------------------------------
# Bulk operations (Phase 6)
# ---------------------------------------------------------------------------


def bulk_trash(db: Session, user: TokenData, document_ids: list[uuid.UUID]) -> int:
    """Soft-delete multiple live documents in one call. Returns count trashed."""
    if not document_ids:
        return 0
    rows = db.scalars(
        select(Document).where(
            Document.id.in_(document_ids),
            Document.deleted_at.is_(None),
        )
    ).all()
    now = datetime.datetime.now(tz=datetime.timezone.utc)
    actor_id = uuid.UUID(user.user_id)
    actor_name = _user_name(db, actor_id)
    for doc in rows:
        doc.deleted_at = now
        db.add(
            ActivityEvent(
                tenant_id=doc.tenant_id,
                type=ACT_TRASH,
                document_id=doc.id,
                document_name=doc.original_filename,
                user_id=actor_id,
                user_name=actor_name,
            )
        )
    db.flush()
    return len(rows)


def bulk_tag_assign(
    db: Session,
    tenant_id: uuid.UUID,
    document_ids: list[uuid.UUID],
    tag_id: uuid.UUID,
) -> int:
    """Assign a tag to multiple documents (idempotent). Returns count attempted."""
    if not document_ids:
        return 0
    tag = db.get(Tag, tag_id)
    if tag is None:
        raise HTTPException(status_code=404, detail="Tag not found.")
    for doc_id in document_ids:
        stmt = (
            pg_insert(DocumentTag)
            .values(
                id=uuid.uuid4(),
                tenant_id=tenant_id,
                document_id=doc_id,
                tag_id=tag_id,
            )
            .on_conflict_do_nothing(index_elements=["document_id", "tag_id"])
        )
        db.execute(stmt)
    db.flush()
    return len(document_ids)


def bulk_tag_remove(
    db: Session,
    document_ids: list[uuid.UUID],
    tag_id: uuid.UUID,
) -> int:
    """Remove a tag from multiple documents. Returns count attempted."""
    if not document_ids:
        return 0
    db.execute(
        delete(DocumentTag).where(
            DocumentTag.document_id.in_(document_ids),
            DocumentTag.tag_id == tag_id,
        )
    )
    db.flush()
    return len(document_ids)


def bulk_set_type(
    db: Session,
    document_ids: list[uuid.UUID],
    document_type: str,
) -> int:
    """Set document_type on multiple documents. Returns count updated."""
    if not document_ids:
        return 0
    result = db.execute(
        update(Document).where(Document.id.in_(document_ids)).values(document_type=document_type)
    )
    db.flush()
    return result.rowcount


def list_activity(
    db: Session,
    document_id: uuid.UUID | None = None,
    page: int = 1,
) -> ActivityListOut:
    """Paginated audit-trail feed. Scoped to one document (History tab) when
    ``document_id`` is given, otherwise the org-wide feed (Settings)."""
    stmt = select(ActivityEvent)
    if document_id is not None:
        stmt = stmt.where(ActivityEvent.document_id == document_id)

    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0

    offset = (page - 1) * _PAGE_SIZE
    rows = db.scalars(
        stmt.order_by(ActivityEvent.timestamp.desc()).offset(offset).limit(_PAGE_SIZE)
    ).all()

    return ActivityListOut(
        items=[_evt_to_out(e) for e in rows],
        total=total,
        page=page,
        page_size=_PAGE_SIZE,
    )


def _mime_family(mime_type: str) -> str:
    """Bucket a sniffed mime type into a display family for the storage-breakdown
    widget. Mirrors the same families the upload flow already recognises
    (idp/mimetype.py) so this never drifts from what the parser registry knows."""
    if mime_type == mimetype.MIME_PDF:
        return "pdf"
    if mime_type in mimetype.IMAGE_MIMES:
        return "image"
    if mime_type in mimetype.OFFICE_MIMES:
        return "office"
    if mime_type in mimetype.TEXT_FAMILY_MIMES:
        return "text"
    if mime_type == mimetype.MIME_EML:
        return "email"
    return "other"


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

    # Mime-family breakdown for the Settings storage widget (only non-trashed docs).
    mime_rows = db.execute(
        select(Document.mime_type, func.count(Document.id))
        .where(Document.deleted_at.is_(None))
        .group_by(Document.mime_type)
    ).all()
    by_family: dict[str, int] = {}
    for mime_type, count in mime_rows:
        family = _mime_family(mime_type)
        by_family[family] = by_family.get(family, 0) + count

    # Tenant storage — RLS returns only the current tenant's row
    tenant_row = db.execute(
        select(Tenant.storage_used_bytes, Tenant.storage_limit_bytes).limit(1)
    ).first()
    storage_used = int(tenant_row[0]) if tenant_row else 0
    storage_limit = int(tenant_row[1]) if tenant_row else Tenant.storage_limit_bytes.default.arg  # type: ignore[union-attr]

    # Recent 5 documents
    recent_docs = db.scalars(select(Document).order_by(Document.uploaded_at.desc()).limit(5)).all()
    names = _names_for_ids(db, {doc.uploaded_by for doc in recent_docs})
    recent_out = [
        _doc_to_out(doc, names.get(doc.uploaded_by, str(doc.uploaded_by))) for doc in recent_docs
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
            documents_by_family=by_family,
        ),
        recent_documents=recent_out,
        activity=[_evt_to_out(e) for e in events],
    )
