"""Activity events — the audit trail and dashboard activity feed."""

import datetime
import uuid

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, uuid_pk

# Must match frontend ActivityEvent.type exactly.
ACT_UPLOAD = "upload"
ACT_PROCESSING_COMPLETE = "processing_complete"
ACT_PROCESSING_FAILED = "processing_failed"
ACT_SEARCH = "search"
ACT_DOWNLOAD = "download"
ACT_USER_ADDED = "user_added"
ACT_EDIT = "edit"
ACT_TRASH = "trash"
ACT_RESTORE = "restore"


class ActivityEvent(Base):
    """A single audit/activity record. User/document names are denormalised for cheap feeds."""

    __tablename__ = "activity_events"

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    type: Mapped[str] = mapped_column(String, nullable=False)
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("documents.id", ondelete="SET NULL"), nullable=True
    )
    document_name: Mapped[str | None] = mapped_column(String, nullable=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    user_name: Mapped[str] = mapped_column(String, nullable=False)
    timestamp: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    meta: Mapped[str | None] = mapped_column(Text, nullable=True)
