"""Dynamic document-type catalog.

Types are DATA, not code: adding a new type (invoice, receipt, PO, agreement,
law, ...) is an INSERT, never a migration. ``json_schema`` is an OPTIONAL soft
schema used only to score extraction confidence — never to gate serialisation.
"""

import uuid
from typing import Any

from sqlalchemy import Boolean, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, uuid_pk


class DocumentType(Base, TimestampMixin):
    """A known document type. ``tenant_id`` NULL = system/global type."""

    __tablename__ = "document_types"

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    json_schema: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    is_system: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
