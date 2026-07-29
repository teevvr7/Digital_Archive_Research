"""Document Share service business logic."""

import datetime
import secrets
import uuid

from sqlalchemy.orm import Session

from app.core import storage
from app.models.document import Document
from app.models.document_share import DocumentShare



def create_share_link(
    db: Session,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    document_id: uuid.UUID,
    expires_in_days: int | None = 7,
) -> DocumentShare:
    """Generate a shareable view token link for a document."""
    doc = db.get(Document, document_id)
    if not doc or doc.tenant_id != tenant_id or doc.deleted_at is not None:
        raise ValueError("Document not found or inaccessible")

    token = secrets.token_urlsafe(32)
    expires_at = None
    if expires_in_days:
        expires_at = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=expires_in_days)

    share = DocumentShare(
        tenant_id=tenant_id,
        document_id=document_id,
        token=token,
        created_by=user_id,
        expires_at=expires_at,
    )
    db.add(share)
    db.commit()
    db.refresh(share)
    return share


def get_shared_document(db: Session, token: str) -> tuple[Document, str]:
    """Retrieve document metadata and temporary signed preview URL by share token."""
    share = db.query(DocumentShare).filter(DocumentShare.token == token).first()
    if not share:
        raise ValueError("Invalid or expired share link")

    if share.expires_at and share.expires_at < datetime.datetime.now(datetime.timezone.utc):
        raise ValueError("Share link has expired")

    doc = db.get(Document, share.document_id)
    if not doc or doc.deleted_at is not None:
        raise ValueError("Shared document no longer exists")

    signed_url = storage.get_signed_url(doc.storage_key, expires_in=300)
    return doc, signed_url
