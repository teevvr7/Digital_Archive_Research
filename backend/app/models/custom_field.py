"""Custom field catalog and per-document field values (Phase 5 — Metadata)."""

import datetime
import uuid
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Integer, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, uuid_pk

# The 5 supported custom-field types. "select" is the only one that uses the
# `options` list below — every other type stores a bare scalar value.
FIELD_TYPE_TEXT = "text"
FIELD_TYPE_NUMBER = "number"
FIELD_TYPE_DATE = "date"
FIELD_TYPE_BOOLEAN = "boolean"
FIELD_TYPE_SELECT = "select"
# A frozenset (immutable set) so "is this a valid field_type?" is a fast O(1)
# membership check, and the set itself can never be accidentally mutated.
VALID_FIELD_TYPES: frozenset[str] = frozenset(
    {FIELD_TYPE_TEXT, FIELD_TYPE_NUMBER, FIELD_TYPE_DATE, FIELD_TYPE_BOOLEAN, FIELD_TYPE_SELECT}
)


class CustomField(Base):
    """Per-tenant typed field catalog entry.

    ``options`` holds a list of allowed string values for ``field_type='select'``.
    For all other types it stays an empty list.
    """

    __tablename__ = "custom_fields"

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)  # e.g. "PO Number"
    field_type: Mapped[str] = mapped_column(Text, nullable=False)  # one of VALID_FIELD_TYPES
    options: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list
    )  # for "select" only
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)  # display order
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class DocumentFieldValue(Base):
    """A single custom field value for one document.

    ``value`` is stored as JSONB to accommodate any field type (string, number,
    boolean, null). There is at most one row per ``(document_id, field_id)`` pair,
    enforced by a unique constraint.
    """

    __tablename__ = "document_field_values"

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    field_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("custom_fields.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # JSONB (not a typed column) because the actual value's shape depends on
    # field_type — could be a string, a number, a boolean, or null.
    value: Mapped[Any] = mapped_column(JSONB, nullable=True)
