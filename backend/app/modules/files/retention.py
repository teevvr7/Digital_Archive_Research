"""Opportunistic Trash Auto-Retention module.

Purges soft-deleted documents in the trash past the retention policy threshold
(e.g., 30 days old). Also removes underlying storage files from Supabase S3 bucket.
"""

import datetime
import logging
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import storage
from app.models.document import Document


logger = logging.getLogger(__name__)

DEFAULT_RETENTION_DAYS = 30


def purge_expired_trash(db: Session, tenant_id: uuid.UUID, retention_days: int = DEFAULT_RETENTION_DAYS) -> int:
    """Find soft-deleted documents past retention_days threshold and permanently delete them."""
    cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=retention_days)

    expired_docs = db.scalars(
        select(Document).where(
            Document.tenant_id == tenant_id,
            Document.deleted_at.is_not(None),
            Document.deleted_at <= cutoff,
        )
    ).all()

    if not expired_docs:
        return 0

    count = 0
    for doc in expired_docs:
        try:
            # Delete S3 object file
            if doc.storage_key:
                storage.delete_file(doc.storage_key)
            if doc.thumbnail_key:
                storage.delete_file(doc.thumbnail_key)

            # Delete DB record
            db.delete(doc)
            count += 1
        except Exception as exc:
            logger.error("Failed auto-retention purge for document %s: %s", doc.id, exc)

    if count > 0:
        db.commit()

    return count
