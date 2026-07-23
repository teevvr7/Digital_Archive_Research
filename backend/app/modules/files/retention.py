"""Trash auto-retention — opportunistically purges documents past their
tenant's retention window.

There is no cross-tenant background sweep: the ``tenants`` table itself is
RLS-protected (``id = current GUC``), so nothing can enumerate "every tenant"
without either bypassing RLS at the Postgres role level (banned outright by
CLAUDE.md) or introducing a new elevated-access path. Instead,
``maybe_purge_expired_trash`` is called from places that already run inside a
given tenant's normal RLS-scoped session — viewing that tenant's Trash view
(``files/service.py::list_documents``) and finishing that tenant's own
document-processing job (``idp/jobs.py::process_document``) — so it never
needs a session or tenant context beyond what's already open. Rate-limited via
``Tenant.trash_last_purged_at`` so it's a cheap no-op on every other call.

Mirrors ``files/service.py::empty_trash`` (same swallow-storage-errors, same
``storage_used_bytes`` accounting) but scoped to *expired* trash only, and —
because this runs with nobody watching, unlike a user-clicked "Empty Trash" —
records one summary audit-trail entry when it actually purges something.
"""

import datetime
import uuid

from sqlalchemy import func, update
from sqlalchemy import select as sa_select
from sqlalchemy.orm import Session

from app.core import storage as object_storage
from app.core.config import settings
from app.models.activity_event import ACT_PERMANENT_DELETE, ActivityEvent
from app.models.document import Document
from app.models.tenant import Tenant

# How often to even check a tenant for expired trash. Deliberately coarse —
# this only needs to happen "roughly daily", not on every request.
_PURGE_CHECK_INTERVAL = datetime.timedelta(hours=24)


def effective_retention_days(tenant: Tenant) -> int:
    """This tenant's retention override, or the global default."""
    return (
        tenant.trash_retention_days
        if tenant.trash_retention_days is not None
        else settings.trash_retention_days_default
    )


def maybe_purge_expired_trash(db: Session, tenant_id: uuid.UUID) -> int:
    """Purge this tenant's expired trash, at most once per
    ``_PURGE_CHECK_INTERVAL``. Returns the number of documents purged (0 if
    the check was skipped or nothing was expired).
    """
    tenant = db.get(Tenant, tenant_id)
    if tenant is None:
        return 0

    now = datetime.datetime.now(datetime.timezone.utc)
    if (
        tenant.trash_last_purged_at is not None
        and now - tenant.trash_last_purged_at < _PURGE_CHECK_INTERVAL
    ):
        return 0

    days = effective_retention_days(tenant)
    cutoff = now - datetime.timedelta(days=days)

    rows = db.scalars(
        sa_select(Document).where(
            Document.deleted_at.is_not(None),
            Document.deleted_at < cutoff,
        )
    ).all()

    freed_bytes = 0
    for doc in rows:
        freed_bytes += doc.size_bytes
        for key in filter(None, [doc.storage_key, doc.thumbnail_key]):
            try:
                object_storage.delete_file(key)
            except Exception:
                pass
        db.delete(doc)

    tenant.trash_last_purged_at = now

    if freed_bytes > 0:
        db.execute(
            update(Tenant)
            .where(Tenant.id == tenant_id)
            .values(storage_used_bytes=func.greatest(Tenant.storage_used_bytes - freed_bytes, 0))
        )

    if rows:
        db.add(
            ActivityEvent(
                tenant_id=tenant_id,
                type=ACT_PERMANENT_DELETE,
                document_id=None,
                document_name=None,
                user_id=None,
                user_name="system",
                meta=f"Auto-purged {len(rows)} document(s) past the {days}-day retention period",
            )
        )

    db.flush()
    return len(rows)
