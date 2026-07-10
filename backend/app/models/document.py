"""Document model — the central archive record."""

import datetime
import uuid
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    REAL,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, uuid_pk

# UI processing states (must match frontend ProcessingStatus exactly).
STATUS_QUEUED = "queued"
STATUS_EXTRACTING_TEXT = "extracting_text"
STATUS_OCR = "ocr_processing"
STATUS_AI = "ai_extraction"
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"
# Pipeline finished (text/thumbnail/search all populated) but structured
# extraction was attempted (content looked invoice/receipt-like) and NEITHER
# the deterministic gate nor the VLM fallback produced an accepted result.
# Never set for documents where structured extraction was never attempted
# (e.g. contracts/letters/office files) — those are simply `completed`.
STATUS_NEEDS_REVIEW = "needs_review"


class Document(Base):
    """A stored file plus its metadata and current extraction result.

    File bytes live ONLY in object storage (``storage_key``); this table holds
    metadata and the current accepted ``extracted_data`` (free-form JSONB).
    """

    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # File metadata
    filename: Mapped[str] = mapped_column(String, nullable=False)
    original_filename: Mapped[str] = mapped_column(String, nullable=False)
    mime_type: Mapped[str] = mapped_column(String, nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    storage_key: Mapped[str] = mapped_column(String, nullable=False)

    # Pipeline state
    status: Mapped[str] = mapped_column(String, nullable=False, default=STATUS_QUEUED)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Classification / template resolution (nullable until resolved)
    document_type_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("document_types.id", ondelete="SET NULL"), nullable=True
    )
    template_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("document_templates.id", ondelete="SET NULL"), nullable=True
    )
    # Denormalised type name for the UI dropdown enum (invoice|receipt|...). "other" by default.
    document_type: Mapped[str] = mapped_column(String, nullable=False, default="other")
    layout_fingerprint: Mapped[str | None] = mapped_column(String, nullable=True)

    # Parsing results
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    has_text_layer: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    ocr_used: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    ocr_confidence: Mapped[float | None] = mapped_column(REAL, nullable=True)

    # Extraction results
    extracted_data: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    extracted_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[float | None] = mapped_column(REAL, nullable=True)

    # Organisation
    tags: Mapped[list[str]] = mapped_column(ARRAY(String), nullable=False, default=list)
    search_tsv: Mapped[str | None] = mapped_column(TSVECTOR, nullable=True)

    # Universal ingestion baseline (Phase 1) — every file gets these regardless of type.
    checksum: Mapped[str | None] = mapped_column(String(64), nullable=True)
    title: Mapped[str | None] = mapped_column(String, nullable=True)
    document_date: Mapped[datetime.date | None] = mapped_column(Date, nullable=True)
    thumbnail_key: Mapped[str | None] = mapped_column(String, nullable=True)

    # Organisation (Phase 4)
    correspondent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("correspondents.id", ondelete="SET NULL"), nullable=True
    )

    # Typed extraction fields (Level 3 data-value pass) — mirrors of the
    # relevant extracted_data JSONB values, populated via idp/normalize.py so
    # amount/vendor filters and export don't have to reach into JSONB. Kept in
    # sync at write time in idp/jobs.py; backfilled for pre-existing rows in
    # migration 0012.
    vendor: Mapped[str | None] = mapped_column(String, nullable=True)
    invoice_no: Mapped[str | None] = mapped_column(String, nullable=True)
    total_amount: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    currency: Mapped[str | None] = mapped_column(String(8), nullable=True)
    # Advisory only (CLAUDE.md: never block ingestion) — set when another
    # non-trashed document in the tenant shares the same vendor+invoice_no.
    duplicate_of_document_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("documents.id", ondelete="SET NULL"), nullable=True
    )

    # Soft-delete / trash (Phase 3): NULL = live, non-NULL = in trash
    deleted_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Ownership / timing
    uploaded_by: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    uploaded_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    processed_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
