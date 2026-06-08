"""Tenant (organisation) model."""

import uuid

from sqlalchemy import BigInteger, String
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
