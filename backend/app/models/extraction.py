"""Extraction attempts — history behind each document's current result.

Every attempt (deterministic / vlm / manual) is recorded here. This powers the
exception queue (``status='low_confidence'``), promote-after-N (counting accepted
extractions per template), manual corrections, and full auditability.
"""

import datetime
import uuid
from typing import Any

from sqlalchemy import DateTime, ForeignKey, REAL, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, uuid_pk

# Which stage of the pipeline produced this attempt.
METHOD_DETERMINISTIC = "deterministic"  # regex/rules (free, no AI)
METHOD_VLM = "vlm"  # the AI vision-language-model fallback
METHOD_MANUAL = "manual"  # a human corrected the extraction by hand

# The outcome of this particular attempt.
EXTRACTION_ACCEPTED = "accepted"  # passed the quality gate / confidence threshold
EXTRACTION_LOW_CONFIDENCE = "low_confidence"  # attempted but not confident enough
EXTRACTION_CORRECTED = "corrected"  # a human fixed it afterward
EXTRACTION_SKIPPED_BUDGET = "skipped_budget"  # tenant over its monthly LLM token cap


class Extraction(Base):
    """One extraction attempt for a document."""

    __tablename__ = "extractions"

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    template_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("document_templates.id", ondelete="SET NULL"), nullable=True
    )
    method: Mapped[str] = mapped_column(String, nullable=False)  # deterministic|vlm|manual
    model_name: Mapped[str | None] = mapped_column(
        String, nullable=True
    )  # only set when method=vlm
    # The fields this attempt produced, or {"_error": ..., "_mode": ...} on failure.
    output: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    confidence: Mapped[float | None] = mapped_column(REAL, nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False)  # accepted|low_confidence|corrected
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
