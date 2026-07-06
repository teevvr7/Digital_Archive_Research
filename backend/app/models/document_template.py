"""Learned layout templates — the heart of the self-learning loop.

A template captures a recognised layout for a document type: a ``fingerprint`` to
match future documents and ``field_mappings`` describing how to extract fields
deterministically (CPU, no GPU). Templates start as ``candidate`` and are
``promoted`` after N confirmed examples (Phase 2).
"""

import datetime
import uuid
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, REAL, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, uuid_pk

TEMPLATE_CANDIDATE = "candidate"
TEMPLATE_PROMOTED = "promoted"
TEMPLATE_DISABLED = "disabled"


class DocumentTemplate(Base):
    """A learned extraction template for a (tenant, document_type, layout)."""

    __tablename__ = "document_templates"

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    document_type_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("document_types.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    fingerprint: Mapped[str] = mapped_column(String, nullable=False)
    field_mappings: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String, nullable=False, default=TEMPLATE_CANDIDATE)
    examples_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    confidence: Mapped[float | None] = mapped_column(REAL, nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    extraction_method: Mapped[str] = mapped_column(String, nullable=False, default="default")
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    use_image: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    use_ocr: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    sample_document_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("documents.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
