"""Files module response schemas (camelCase, ORM-friendly).

Field names mirror ``frontend/types/index.ts`` exactly once converted to camelCase
by ``CamelModel``. ``extracted_data`` is an opaque ``dict`` so novel document
structures pass through untouched and can never break serialization.
"""

import datetime
import uuid
from typing import Any

from app.core.camel import CamelModel
from app.modules.metadata.schemas import FieldValueOut  # noqa: F401 — re-exported for callers


class TagOut(CamelModel):
    """A tag as embedded in document responses (id + display fields only)."""

    id: uuid.UUID
    name: str
    color: str


class CorrespondentOut(CamelModel):
    """A correspondent as embedded in document responses."""

    id: uuid.UUID
    name: str


class DocumentPatchIn(CamelModel):
    """Editable fields on a document.

    All fields are optional — only those explicitly sent are updated.
    Send ``null`` to clear an optional field (e.g. remove a document_date).

    ``extracted_data_patch`` is a shallow-merge partial update for the
    ``extracted_data`` JSONB column: only the listed keys are overwritten;
    all other keys in the existing JSON are preserved.
    """

    title: str | None = None
    document_type: str | None = None
    document_date: datetime.date | None = None
    correspondent_id: uuid.UUID | None = None
    extracted_data_patch: dict[str, Any] | None = None


class DocumentOut(CamelModel):
    """A single document as the UI consumes it.

    ``uploaded_by`` is the uploader's **display name** (denormalised from the
    users table), not the raw user id — matching the frontend ``Document`` type.
    """

    id: uuid.UUID
    tenant_id: uuid.UUID
    filename: str
    original_filename: str
    title: str
    document_type: str
    mime_type: str
    size_bytes: int
    status: str
    uploaded_by: str
    uploaded_at: datetime.datetime
    processed_at: datetime.datetime | None
    document_date: datetime.date | None
    page_count: int | None
    has_text_layer: bool
    ocr_confidence: float | None
    confidence: float | None
    extracted_data: dict[str, Any] | None
    extracted_text: str | None
    tags: list[TagOut]
    correspondent: CorrespondentOut | None
    custom_field_values: list[FieldValueOut] = []
    storage_key: str
    has_thumbnail: bool
    deleted_at: datetime.datetime | None


class DocumentListOut(CamelModel):
    """A page of documents."""

    items: list[DocumentOut]
    total: int
    page: int
    page_size: int
    # Filenames skipped because their content already exists for this tenant
    # (sha256 dedup). Only ever non-empty on the upload response.
    duplicates: list[str] = []


class ActivityOut(CamelModel):
    """An activity-feed entry (matches frontend ``ActivityEvent``)."""

    id: uuid.UUID
    type: str
    document_id: uuid.UUID | None
    document_name: str | None
    user_id: uuid.UUID | None
    user_name: str
    timestamp: datetime.datetime
    meta: str | None


class DashboardStats(CamelModel):
    """Headline counts + storage accounting for the dashboard cards."""

    total_documents: int
    processed: int
    in_pipeline: int
    failed: int
    storage_used_bytes: int
    storage_limit_bytes: int
    documents_count: int


class DashboardOut(CamelModel):
    """Everything the dashboard page renders in one payload."""

    stats: DashboardStats
    recent_documents: list[DocumentOut]
    activity: list[ActivityOut]


# ---------------------------------------------------------------------------
# Bulk operation request bodies (Phase 6)
# ---------------------------------------------------------------------------


class BulkTrashIn(CamelModel):
    document_ids: list[uuid.UUID]


class BulkTagIn(CamelModel):
    document_ids: list[uuid.UUID]
    tag_id: uuid.UUID
    action: str  # "assign" | "remove"


class BulkSetTypeIn(CamelModel):
    document_ids: list[uuid.UUID]
    document_type: str
