"""Predefined custom fields per document type (Level 6 — Metadata)."""

import datetime
import uuid

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, uuid_pk

DOCUMENT_TYPE_INVOICE = "invoice"
DOCUMENT_TYPE_RECEIPT = "receipt"
DOCUMENT_TYPE_CONTRACT = "contract"
DOCUMENT_TYPE_REPORT = "report"
DOCUMENT_TYPE_LETTER = "letter"
DOCUMENT_TYPE_FORM = "form"
DOCUMENT_TYPE_OTHER = "other"
VALID_DOCUMENT_TYPES: frozenset[str] = frozenset(
    {
        DOCUMENT_TYPE_INVOICE,
        DOCUMENT_TYPE_RECEIPT,
        DOCUMENT_TYPE_CONTRACT,
        DOCUMENT_TYPE_REPORT,
        DOCUMENT_TYPE_LETTER,
        DOCUMENT_TYPE_FORM,
        DOCUMENT_TYPE_OTHER,
    }
)


class DocumentTypeField(Base):
    """Links a ``CustomField`` catalog entry to a document type as predefined.

    Document types are the fixed 7-value string set (``VALID_DOCUMENT_TYPES``)
    rather than a FK to ``document_types.id`` — that table's per-tenant/dynamic
    capability stays dormant until tenant-defined types are built as separate
    work. ``required`` only affects the upload-time popup (a soft prompt there
    becomes a hard block); it is never enforced by the API itself.
    """

    __tablename__ = "document_type_fields"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "document_type", "field_id",
            name="uq_document_type_fields_tenant_type_field",
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    document_type: Mapped[str] = mapped_column(Text, nullable=False)
    field_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("custom_fields.id", ondelete="CASCADE"), nullable=False, index=True
    )
    required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
