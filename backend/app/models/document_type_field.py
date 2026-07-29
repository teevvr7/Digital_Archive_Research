"""DocumentTypeField ORM model — predefined custom fields tied to specific document types."""

import datetime
import uuid

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, uuid_pk


class DocumentTypeField(Base):
    """Predefined custom field mapping for a DocumentType."""

    __tablename__ = "document_type_fields"

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    document_type_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("document_types.id", ondelete="CASCADE"), nullable=False, index=True
    )
    field_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("custom_fields.id", ondelete="CASCADE"), nullable=False, index=True
    )
    is_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
