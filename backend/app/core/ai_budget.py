"""LLM monthly token budget gate (Phase 0 cost guardrail).

Every VLM call must be preceded by ``llm_allowed()`` and followed (when the call
actually ran) by ``record_ai_usage()``, so spend is capped and auditable per
tenant. Only the monthly token cap is enforced for now — the
``docs_llm/docs_total`` ratio circuit breaker from the long-term plan is
deferred until Phase 2 ships deterministic extraction (today 100% of documents
reach the VLM, so that ratio would always read ~100% and isn't yet meaningful).
"""

# datetime for computing "the start of this calendar month".
import datetime
import uuid

# func gives access to SQL functions like SUM()/COALESCE(); select builds queries.
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.ai_usage import AiUsage
from app.models.tenant import Tenant


def _month_start(now: datetime.datetime | None = None) -> datetime.datetime:
    # Defaults to the real current time if the caller doesn't pass one in
    # (only overridden in tests, to make "the current month" deterministic).
    now = now or datetime.datetime.now(datetime.timezone.utc)
    # Zero out everything smaller than "day" and set day=1 — this is how we
    # compute "midnight on the 1st of the current month" for the budget window.
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def llm_allowed(db: Session, tenant_id: uuid.UUID) -> bool:
    """True if *tenant_id* still has monthly LLM token budget remaining."""
    # Look up this tenant's OWN override of the monthly cap, if they have one.
    cap = db.scalar(select(Tenant.llm_monthly_token_cap).where(Tenant.id == tenant_id))
    if cap is None:
        # No per-tenant override set — fall back to the global default.
        cap = settings.llm_monthly_token_cap_default
    if cap <= 0:
        # A cap of zero (or negative) means "never allowed" — an explicit kill switch.
        return False

    # Sum every token spent by this tenant since the start of the current
    # calendar month. COALESCE(...,0) handles the case of zero rows (SUM of
    # nothing is NULL in SQL, not 0) so the comparison below always works.
    used = db.scalar(
        select(func.coalesce(func.sum(AiUsage.total_tokens), 0)).where(
            AiUsage.tenant_id == tenant_id,
            AiUsage.created_at >= _month_start(),
        )
    )
    # Allowed only if usage so far is strictly less than the cap.
    return (used or 0) < cap


def record_ai_usage(
    db: Session,
    *,  # everything after this must be passed as a keyword argument, never positionally
    tenant_id: uuid.UUID,
    document_id: uuid.UUID | None,
    model_name: str | None,
    prompt_tokens: int,
    completion_tokens: int,
    total_tokens: int,
) -> None:
    """Record one metered VLM call. Caller's transaction commits it."""
    # Just stages a new row in the session — it isn't written to the database
    # until the CALLER's own transaction commits (this function never commits
    # itself, matching how every other write function in this codebase behaves).
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
