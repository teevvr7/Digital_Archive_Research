"""Correspondent module — CRUD business logic."""

import uuid

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.security import TokenData
from app.models.correspondent import Correspondent
from app.modules.correspondents.schemas import CorrespondentIn, CorrespondentOut, CorrespondentPatchIn


def _to_out(c: Correspondent) -> CorrespondentOut:
    return CorrespondentOut(
        id=c.id,
        tenant_id=c.tenant_id,
        name=c.name,
        email=c.email,
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
    if data.email:
        existing_email = db.scalars(
            select(Correspondent).where(
                Correspondent.tenant_id == tenant_id,
                Correspondent.email == data.email,
            )
        ).first()
        if existing_email:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"A correspondent with email '{data.email}' already exists.",
            )
    c = Correspondent(
        tenant_id=tenant_id,
        name=data.name,
        email=data.email,
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
    if "email" in updated:
        c.email = patch.email
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


def find_or_create_by_sender(
    db: Session, tenant_id: uuid.UUID, name: str | None, email: str
) -> Correspondent:
    """Get-or-create a correspondent for a parsed email sender.

    Called from the auto-matching engine (tags/matching.py) for .eml documents —
    never raises on a name collision (unlike the public create_correspondent 409):
    if a correspondent with this display name already exists but has no email
    yet, that gap is backfilled rather than creating a duplicate. Deterministic,
    swallowed by the caller on any unexpected error — auto-linking must never
    block document ingestion.
    """
    by_email = db.scalars(
        select(Correspondent).where(
            Correspondent.tenant_id == tenant_id, Correspondent.email == email
        )
    ).first()
    if by_email is not None:
        return by_email

    display_name = (name or email).strip()
    by_name = db.scalars(
        select(Correspondent).where(
            Correspondent.tenant_id == tenant_id, Correspondent.name == display_name
        )
    ).first()
    if by_name is not None:
        if by_name.email is None:
            by_name.email = email
            db.flush()
        return by_name

    try:
        # SAVEPOINT, not the outer transaction: this runs deep inside the
        # worker's larger per-document transaction (alongside status updates,
        # tag matching, etc.) — a plain db.rollback() here would wipe out all
        # of that, not just this insert attempt.
        with db.begin_nested():
            c = Correspondent(tenant_id=tenant_id, name=display_name, email=email)
            db.add(c)
            db.flush()
    except IntegrityError:
        # Race: another process created the same name/email between our checks
        # and this insert. Re-query and use whichever now exists.
        existing = db.scalars(
            select(Correspondent).where(
                Correspondent.tenant_id == tenant_id,
                (Correspondent.email == email) | (Correspondent.name == display_name),
            )
        ).first()
        if existing is not None:
            return existing
        raise
    return c
