"""LLM monthly token budget gate (Phase 0 cost guardrail).

Every VLM call must be preceded by ``llm_allowed()`` and followed (when the call
actually ran) by ``record_ai_usage()``, so spend is capped and auditable per
tenant. Only the monthly token cap is enforced for now — the
``docs_llm/docs_total`` ratio circuit breaker from the long-term plan is
deferred until Phase 2 ships deterministic extraction (today 100% of documents
reach the VLM, so that ratio would always read ~100% and isn't yet meaningful).
"""

import datetime
import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.ai_usage import AiUsage
from app.models.tenant import Tenant


def _month_start(now: datetime.datetime | None = None) -> datetime.datetime:
    now = now or datetime.datetime.now(datetime.timezone.utc)
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def llm_allowed(db: Session, tenant_id: uuid.UUID) -> bool:
    """True if *tenant_id* still has monthly LLM token budget remaining."""
    cap = db.scalar(select(Tenant.llm_monthly_token_cap).where(Tenant.id == tenant_id))
    if cap is None:
        cap = settings.llm_monthly_token_cap_default
    if cap <= 0:
        return False

    used = db.scalar(
        select(func.coalesce(func.sum(AiUsage.total_tokens), 0)).where(
            AiUsage.tenant_id == tenant_id,
            AiUsage.created_at >= _month_start(),
        )
    )
    return (used or 0) < cap


def record_ai_usage(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    document_id: uuid.UUID | None,
    model_name: str | None,
    prompt_tokens: int,
    completion_tokens: int,
    total_tokens: int,
) -> None:
    """Record one metered VLM call. Caller's transaction commits it."""
    db.add(
        AiUsage(
            tenant_id=tenant_id,
            document_id=document_id,
            model_name=model_name,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
        )
    )
