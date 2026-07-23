"""Tenant (organisation) model."""

import datetime
import uuid

from sqlalchemy import BigInteger, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, uuid_pk

TEN_GB = 10 * 1024 * 1024 * 1024


class Tenant(Base, TimestampMixin):
    """A customer organisation. The root of multi-tenancy."""

    __tablename__ = "tenants"

    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(String, nullable=False)
    plan: Mapped[str] = mapped_column(String, nullable=False, default="starter")
    storage_used_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    storage_limit_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, default=TEN_GB)
    # NULL = use settings.llm_monthly_token_cap_default
    llm_monthly_token_cap: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # NULL = use settings.trash_retention_days_default
    trash_retention_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Rate-limits the opportunistic purge check in files/retention.py to ~once/day.
    trash_last_purged_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
