"""Files module response schemas (camelCase, ORM-friendly).

Field names mirror ``frontend/types/index.ts`` exactly once converted to camelCase
by ``CamelModel``. ``extracted_data`` is an opaque ``dict`` so novel document
structures pass through untouched and can never break serialization.
"""

import datetime
import uuid
from typing import Any

from app.core.camel import CamelModel


class DocumentOut(CamelModel):
    """A single document as the UI consumes it.

    ``uploaded_by`` is the uploader's **display name** (denormalised from the
    users table), not the raw user id — matching the frontend ``Document`` type.
    """

    id: uuid.UUID
    tenant_id: uuid.UUID
    filename: str
    original_filename: str
    document_type: str
    mime_type: str
    size_bytes: int
    status: str
    uploaded_by: str
    uploaded_at: datetime.datetime
    processed_at: datetime.datetime | None
    page_count: int | None
    has_text_layer: bool
    ocr_confidence: float | None
    confidence: float | None
    extracted_data: dict[str, Any] | None
    extracted_text: str | None
    tags: list[str]
    storage_key: str


class DocumentListOut(CamelModel):
    """A page of documents."""

    items: list[DocumentOut]
    total: int
    page: int
    page_size: int


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
