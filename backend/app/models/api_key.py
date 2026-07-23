"""API key model (settings). Only a hash of the key is stored — never the raw key."""

import datetime
import uuid

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, uuid_pk


class ApiKey(Base, TimestampMixin):
    """A tenant API key. ``prefix`` is shown in the UI; ``hashed_key`` is the secret."""

    __tablename__ = "api_keys"

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String, nullable=False)  # user-given label for the key
    # A short, non-secret prefix (e.g. "dw_abc123") safe to display in the UI
    # so the user can tell keys apart without ever seeing the full secret again.
    prefix: Mapped[str] = mapped_column(String, nullable=False)
    # Only a HASH of the actual key is stored — if this table were ever
    # leaked, no usable API key could be recovered from it.
    hashed_key: Mapped[str] = mapped_column(String, nullable=False)
    last_used_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
