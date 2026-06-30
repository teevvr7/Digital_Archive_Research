"""Correspondent model — vendor/sender entity for auto-linking documents."""

import datetime
import uuid

from sqlalchemy import Boolean, DateTime, ForeignKey, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, uuid_pk

# Matching algorithm constants (same set as Tag — shared by the matching engine).
ALGO_NONE = "none"
ALGO_ANY = "any"
ALGO_ALL = "all"
ALGO_LITERAL = "literal"
ALGO_REGEX = "regex"


class Correspondent(Base):
    """A vendor/sender entity that can be auto-linked to documents via match rules."""

    __tablename__ = "correspondents"

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)

    # Matching rules — empty match or algorithm=none means manual-only.
    match: Mapped[str] = mapped_column(Text, nullable=False, default="")
    matching_algorithm: Mapped[str] = mapped_column(Text, nullable=False, default=ALGO_ANY)
    is_insensitive: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_correspondents_tenant_name"),
    )
