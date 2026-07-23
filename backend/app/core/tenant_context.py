"""Tenant context for Row-Level Security.

Postgres RLS policies key off a custom GUC ``app.current_tenant``. We set it
transaction-locally with ``set_config(..., is_local=true)`` so it is automatically
discarded at commit/rollback — correct and leak-free even on Supabase's transaction
pooler. This single mechanism is shared by the API request path and the worker.

If the GUC is never set, ``current_setting('app.current_tenant', true)`` returns
NULL and every RLS policy matches zero rows (fail-closed).
"""

# Iterator types the generator that @contextmanager wraps.
from collections.abc import Iterator

# contextmanager turns a generator function into something usable in a
# `with ... as ...:` block — that's what makes tenant_session() work below.
from contextlib import contextmanager

# text() lets us write a raw parameterized SQL statement instead of using the
# ORM query builder — needed here because "SET config" isn't a normal query.
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.db import SessionLocal


def _apply_tenant(db: Session, tenant_id: str) -> None:
    """Set the transaction-local tenant GUC that RLS policies read."""
    # set_config('app.current_tenant', tenant_id, true) — the third argument
    # "true" means "local to this transaction", so it clears itself
    # automatically at COMMIT or ROLLBACK. Every RLS policy in the database
    # reads this exact variable to decide which rows are visible.
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
    # Open a fresh session (the worker isn't inside a FastAPI dependency, so
    # it can't reuse get_tenant_db — this is the equivalent for background jobs).
    db = SessionLocal()
    try:
        # Start the transaction the GUC below will be scoped to.
        db.begin()
        # Apply the tenant GUC so every query inside this "with" block is
        # correctly RLS-scoped to tenant_id.
        _apply_tenant(db, tenant_id)
        # Hand control to the caller's "with tenant_session(...) as db:" block.
        yield db
        # If the caller's code didn't raise, persist whatever it changed.
        db.commit()
    except Exception:
        # Any error inside the "with" block rolls everything back — no
        # partial writes ever survive a crash mid-job.
        db.rollback()
        raise
    finally:
        # Always release the connection back to the pool.
        db.close()


def set_tenant(db: Session, tenant_id: str) -> None:
    """Apply the tenant GUC on an existing session/transaction (used by FastAPI deps)."""
    # A thin public wrapper — FastAPI's get_tenant_db already manages its own
    # session/transaction lifecycle, so it just needs to call this to apply
    # the GUC, without needing the full session-open/close ceremony above.
    _apply_tenant(db, tenant_id)
