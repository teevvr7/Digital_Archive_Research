"""Document share — a time-limited, token-gated public link to one document.

The token itself is the authorization (unguessable, ``secrets.token_urlsafe(32)``
— see modules/shares/service.py) for the one public, unauthenticated resolve
endpoint. Every other operation on this table (create/list/revoke) goes
through the normal tenant-scoped RLS session like any other table.
"""

import datetime
import uuid

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, uuid_pk


class DocumentShare(Base, TimestampMixin):
    __tablename__ = "document_shares"

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    # Globally unique (not per-tenant) — the public lookup has no tenant
    # context to scope by, it can only filter on the token itself.
    token: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    # SET NULL — the share link keeps working even if the admin who created
    # it is later removed from the team.
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    # Required (not nullable) — every share MUST have an expiry, capped to
    # 1-30 days at creation time by the service layer.
    expires_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
