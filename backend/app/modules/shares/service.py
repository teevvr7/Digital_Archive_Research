"""Shares module — time-limited public document links.

Create/list/revoke run through the normal tenant-scoped RLS session like any
other table. ``resolve_share_token`` is the one deliberate exception: it's
called from a fully public, unauthenticated endpoint, so there is no tenant
JWT to derive the RLS GUC from. It uses a raw session instead — the same
precedent as ``auth/service.py::bootstrap`` — and the unguessable token
itself (43 chars, ``secrets.token_urlsafe(32)``) is the authorization.
"""

import datetime
import secrets
import uuid

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import storage as object_storage
from app.core.db import SessionLocal
from app.core.security import TokenData
from app.models.document import Document
from app.models.document_share import DocumentShare
from app.modules.shares.schemas import ResolvedShareOut, ShareOut

_MIN_EXPIRY_DAYS = 1
_MAX_EXPIRY_DAYS = 30


def _share_to_out(share: DocumentShare) -> ShareOut:
    return ShareOut(
        id=share.id,
        document_id=share.document_id,
        token=share.token,
        created_at=share.created_at,
        expires_at=share.expires_at,
    )


def create_share(
    db: Session, user: TokenData, doc_id: uuid.UUID, expires_in_days: int
) -> ShareOut:
    """Create a new share link. 404 if the document doesn't exist or is
    trashed — sharing a trashed document makes no sense."""
    doc = db.get(Document, doc_id)
    if doc is None or doc.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Document not found.")

    expires_in_days = max(_MIN_EXPIRY_DAYS, min(expires_in_days, _MAX_EXPIRY_DAYS))
    share = DocumentShare(
        tenant_id=uuid.UUID(user.tenant_id),  # type: ignore[arg-type]
        document_id=doc_id,
        token=secrets.token_urlsafe(32),
        created_by=uuid.UUID(user.user_id),
        expires_at=datetime.datetime.now(datetime.timezone.utc)
        + datetime.timedelta(days=expires_in_days),
    )
    db.add(share)
    db.flush()
    return _share_to_out(share)


def list_shares(db: Session, doc_id: uuid.UUID) -> list[ShareOut]:
    """List all share links for a document (active and expired — the
    frontend can show expiry status; revoked ones are simply gone)."""
    rows = db.scalars(
        select(DocumentShare)
        .where(DocumentShare.document_id == doc_id)
        .order_by(DocumentShare.created_at.desc())
    ).all()
    return [_share_to_out(s) for s in rows]


def revoke_share(db: Session, share_id: uuid.UUID) -> None:
    share = db.get(DocumentShare, share_id)
    if share is None:
        raise HTTPException(status_code=404, detail="Share not found.")
    db.delete(share)
    db.flush()


def resolve_share_token(token: str) -> ResolvedShareOut:
    """Public, unauthenticated resolve — see module docstring for the RLS
    bypass rationale. Never streams file bytes; brokers a signed URL only,
    same pattern as every authenticated download path."""
    db = SessionLocal()
    try:
        share = db.scalars(
            select(DocumentShare).where(DocumentShare.token == token)
        ).first()
        if share is None:
            raise HTTPException(status_code=404, detail="This link is invalid.")
        if share.expires_at < datetime.datetime.now(datetime.timezone.utc):
            raise HTTPException(status_code=status.HTTP_410_GONE, detail="This link has expired.")

        doc = db.get(Document, share.document_id)
        if doc is None or doc.deleted_at is not None:
            raise HTTPException(status_code=404, detail="This document is no longer available.")

        url = object_storage.create_signed_url(doc.storage_key, expires_in=300)
        return ResolvedShareOut(url=url, filename=doc.original_filename, mime_type=doc.mime_type)
    finally:
        db.close()
