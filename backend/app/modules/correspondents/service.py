"""Correspondent module — CRUD business logic."""

import uuid

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import TokenData
from app.models.correspondent import Correspondent
from app.modules.correspondents.schemas import CorrespondentIn, CorrespondentOut, CorrespondentPatchIn


def _to_out(c: Correspondent) -> CorrespondentOut:
    return CorrespondentOut(
        id=c.id,
        tenant_id=c.tenant_id,
        name=c.name,
        match=c.match,
        matching_algorithm=c.matching_algorithm,
        is_insensitive=c.is_insensitive,
        created_at=c.created_at,
    )


def list_correspondents(db: Session) -> list[CorrespondentOut]:
    """List all correspondents for the current tenant (RLS-scoped)."""
    rows = db.scalars(select(Correspondent).order_by(Correspondent.name)).all()
    return [_to_out(c) for c in rows]


def create_correspondent(db: Session, user: TokenData, data: CorrespondentIn) -> CorrespondentOut:
    """Create a new correspondent. 409 if a correspondent with the same name exists."""
    tenant_id = uuid.UUID(user.tenant_id)  # type: ignore[arg-type]
    existing = db.scalars(
        select(Correspondent).where(
            Correspondent.tenant_id == tenant_id,
            Correspondent.name == data.name,
        )
    ).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Correspondent '{data.name}' already exists.",
        )
    c = Correspondent(
        tenant_id=tenant_id,
        name=data.name,
        match=data.match,
        matching_algorithm=data.matching_algorithm,
        is_insensitive=data.is_insensitive,
    )
    db.add(c)
    db.flush()
    return _to_out(c)


def patch_correspondent(
    db: Session, correspondent_id: uuid.UUID, patch: CorrespondentPatchIn
) -> CorrespondentOut:
    """Update correspondent fields. Only fields present in the request are written."""
    c = db.get(Correspondent, correspondent_id)
    if c is None:
        raise HTTPException(status_code=404, detail="Correspondent not found.")
    updated = patch.model_fields_set
    if "name" in updated and patch.name is not None:
        c.name = patch.name
    if "match" in updated and patch.match is not None:
        c.match = patch.match
    if "matching_algorithm" in updated and patch.matching_algorithm is not None:
        c.matching_algorithm = patch.matching_algorithm
    if "is_insensitive" in updated and patch.is_insensitive is not None:
        c.is_insensitive = patch.is_insensitive
    db.flush()
    return _to_out(c)


def delete_correspondent(db: Session, correspondent_id: uuid.UUID) -> None:
    """Delete a correspondent (documents.correspondent_id SET NULL via DB constraint).

    404 if not found.
    """
    c = db.get(Correspondent, correspondent_id)
    if c is None:
        raise HTTPException(status_code=404, detail="Correspondent not found.")
    db.delete(c)
    db.flush()
