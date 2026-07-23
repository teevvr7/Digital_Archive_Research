"""Tenant (organisation) model."""

import datetime
import uuid

from sqlalchemy import BigInteger, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, uuid_pk

# Default storage quota given to every new tenant: 10 gibibytes.
TEN_GB = 10 * 1024 * 1024 * 1024


class Tenant(Base, TimestampMixin):
    """A customer organisation. The root of multi-tenancy."""

    __tablename__ = "tenants"

    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(String, nullable=False)  # organisation display name
    # Subscription tier — reserved for future billing; not yet enforced anywhere.
    plan: Mapped[str] = mapped_column(String, nullable=False, default="starter")
    # Running total of bytes stored — incremented on upload, decremented on
    # permanent delete, so quota checks never need to re-scan every document.
    storage_used_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    storage_limit_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, default=TEN_GB)
    # NULL = use settings.llm_monthly_token_cap_default
    # Lets a specific tenant have a custom AI spending cap without touching code.
    llm_monthly_token_cap: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # NULL = use settings.trash_retention_days_default
    # Same idea as above, but for how many days trash is kept before auto-purge.
    trash_retention_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Rate-limits the opportunistic purge check in files/retention.py to ~once/day.
    # Purely internal bookkeeping — never shown to the user.
    trash_last_purged_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
