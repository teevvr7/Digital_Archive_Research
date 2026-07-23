"""Tag and DocumentTag models — organization labels for documents."""

import datetime
import uuid

from sqlalchemy import Boolean, DateTime, ForeignKey, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, uuid_pk

# Matching algorithm constants (mirror frontend + correspondent model).
ALGO_NONE = "none"
ALGO_ANY = "any"
ALGO_ALL = "all"
ALGO_LITERAL = "literal"
ALGO_REGEX = "regex"


class Tag(Base):
    """A colored label that can be auto-assigned to documents via match rules."""

    __tablename__ = "tags"

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    color: Mapped[str] = mapped_column(
        Text, nullable=False, default="#6B7280"
    )  # hex color shown in the UI

    # Matching rules — empty match or algorithm=none means manual-only.
    match: Mapped[str] = mapped_column(Text, nullable=False, default="")
    matching_algorithm: Mapped[str] = mapped_column(Text, nullable=False, default=ALGO_ANY)
    is_insensitive: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_inbox_tag: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )  # the special "Inbox" tag

    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    # A tenant can't have two tags with the same name.
    __table_args__ = (UniqueConstraint("tenant_id", "name", name="uq_tags_tenant_name"),)


class DocumentTag(Base):
    """M2M join between a document and a tag (replaces the dead ARRAY column)."""

    __tablename__ = "document_tags"

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    tag_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tags.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # A given (document, tag) pair can only be assigned once — assigning the
    # same tag twice is a harmless no-op, enforced at the database level.
    __table_args__ = (UniqueConstraint("document_id", "tag_id", name="uq_document_tags_doc_tag"),)
