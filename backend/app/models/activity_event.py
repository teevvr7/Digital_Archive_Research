"""Activity events — the audit trail and dashboard activity feed."""

import datetime
import uuid

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, uuid_pk

# Must match frontend ActivityEvent.type exactly.
# Each of these constants is a possible value for the `type` column below —
# used as string constants throughout the codebase instead of retyping the
# literal string (and risking a typo) every time an event is logged.
ACT_UPLOAD = "upload"
ACT_PROCESSING_COMPLETE = "processing_complete"
ACT_PROCESSING_FAILED = "processing_failed"
ACT_SEARCH = "search"
ACT_DOWNLOAD = "download"
ACT_USER_ADDED = "user_added"
ACT_EDIT = "edit"
ACT_TRASH = "trash"
ACT_RESTORE = "restore"
ACT_PERMANENT_DELETE = "permanent_delete"
ACT_DUPLICATE_DETECTED = "duplicate_detected"
ACT_USER_REMOVED = "user_removed"
ACT_USER_ROLE_CHANGED = "role_changed"


class ActivityEvent(Base):
    """A single audit/activity record. User/document names are denormalised for cheap feeds."""

    __tablename__ = "activity_events"

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Which kind of event this is — one of the ACT_* constants above.
    type: Mapped[str] = mapped_column(String, nullable=False)
    # SET NULL (not CASCADE) — if the document is later deleted, the activity
    # row survives (so the audit trail isn't erased), it just loses the link.
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("documents.id", ondelete="SET NULL"), nullable=True
    )
    # Snapshotted at event time — so the feed still reads correctly even if
    # the document is later renamed or permanently deleted.
    document_name: Mapped[str | None] = mapped_column(String, nullable=True)
    # SET NULL for the same reason as document_id — a removed teammate's past
    # activity should still show up in the history.
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    # Snapshotted display name, or "system" for automated events (e.g. an
    # automatic trash purge that no human user triggered).
    user_name: Mapped[str] = mapped_column(String, nullable=False)
    timestamp: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    # Free-text extra context — an error excerpt, "auto-purged N documents", etc.
    meta: Mapped[str | None] = mapped_column(Text, nullable=True)
