"""Tenant context for Row-Level Security.

Postgres RLS policies key off a custom GUC ``app.current_tenant``. We set it
transaction-locally with ``set_config(..., is_local=true)`` so it is automatically
discarded at commit/rollback — correct and leak-free even on Supabase's transaction
pooler. This single mechanism is shared by the API request path and the worker.

If the GUC is never set, ``current_setting('app.current_tenant', true)`` returns
NULL and every RLS policy matches zero rows (fail-closed).
"""

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.db import SessionLocal


def _apply_tenant(db: Session, tenant_id: str) -> None:
    """Set the transaction-local tenant GUC that RLS policies read."""
    db.execute(
        text("SELECT set_config('app.current_tenant', :tid, true)"),
        {"tid": str(tenant_id)},
    )


@contextmanager
def tenant_session(tenant_id: str) -> Iterator[Session]:
    """Yield a session bound to ``tenant_id`` within a single transaction.

    Commits on success, rolls back on error. Used by the worker and anywhere
    outside the FastAPI dependency graph.
    """
    db = SessionLocal()
    try:
        db.begin()
        _apply_tenant(db, tenant_id)
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def set_tenant(db: Session, tenant_id: str) -> None:
    """Apply the tenant GUC on an existing session/transaction (used by FastAPI deps)."""
    _apply_tenant(db, tenant_id)
