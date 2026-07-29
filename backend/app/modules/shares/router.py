"""Document Share API endpoints."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.deps import get_tenant_db
from app.core.db import get_db
from app.core.security import TokenData
from app.modules.files.schemas import DocumentOut
from app.modules.shares import schemas, service

router = APIRouter(prefix="/shares", tags=["Document Shares"])

_DbCtx = Annotated[tuple[Session, TokenData], Depends(get_tenant_db)]


@router.post("", response_model=schemas.ShareOut, summary="Create a shareable token link for a document")
def create_share(body: schemas.ShareCreate, ctx: _DbCtx):
    """Generate a unique view-only token URL for sharing a document externally."""
    db, user = ctx
    try:
        share = service.create_share_link(
            db,
            tenant_id=uuid.UUID(user.tenant_id),
            user_id=uuid.UUID(user.user_id),
            document_id=body.document_id,
            expires_in_days=body.expires_in_days,
        )
        share_url = f"/shared/{share.token}"
        return schemas.ShareOut(
            id=share.id,
            document_id=share.document_id,
            token=share.token,
            share_url=share_url,
            created_at=share.created_at,
            expires_at=share.expires_at,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.get("/public/{token}", summary="Public view endpoint for shared documents (no auth required)")
def get_public_share(token: str, db: Session = Depends(get_db)):
    """Fetch shared document details and temporary signed URL by public token."""
    try:
        doc, signed_url = service.get_shared_document(db, token)
        doc_out = DocumentOut.model_validate(doc)
        return {"document": doc_out, "previewUrl": signed_url}
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
