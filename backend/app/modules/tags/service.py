"""Tag module — CRUD + document assignment business logic."""

import uuid

from fastapi import HTTPException, status
from sqlalchemy import insert, select
from sqlalchemy.orm import Session

from app.core.security import TokenData
from app.models.document import Document
from app.models.tag import DocumentTag, Tag
from app.modules.tags.schemas import TagIn, TagOut, TagPatchIn


def _tag_to_out(tag: Tag) -> TagOut:
    return TagOut(
        id=tag.id,
        tenant_id=tag.tenant_id,
        name=tag.name,
        color=tag.color,
        match=tag.match,
        matching_algorithm=tag.matching_algorithm,
        is_insensitive=tag.is_insensitive,
        is_inbox_tag=tag.is_inbox_tag,
        created_at=tag.created_at,
    )


def list_tags(db: Session) -> list[TagOut]:
    """List all tags for the current tenant (RLS-scoped)."""
    tags = db.scalars(select(Tag).order_by(Tag.name)).all()
    return [_tag_to_out(t) for t in tags]


def create_tag(db: Session, user: TokenData, data: TagIn) -> TagOut:
    """Create a new tag. 409 if a tag with the same name already exists."""
    tenant_id = uuid.UUID(user.tenant_id)  # type: ignore[arg-type]
    existing = db.scalars(
        select(Tag).where(Tag.tenant_id == tenant_id, Tag.name == data.name)
    ).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Tag '{data.name}' already exists.",
        )
    tag = Tag(
        tenant_id=tenant_id,
        name=data.name,
        color=data.color,
        match=data.match,
        matching_algorithm=data.matching_algorithm,
        is_insensitive=data.is_insensitive,
        is_inbox_tag=data.is_inbox_tag,
    )
    db.add(tag)
    db.flush()
    return _tag_to_out(tag)


def patch_tag(db: Session, tag_id: uuid.UUID, patch: TagPatchIn) -> TagOut:
    """Update tag fields. Only fields present in the request are written."""
    tag = db.get(Tag, tag_id)
    if tag is None:
        raise HTTPException(status_code=404, detail="Tag not found.")
    updated = patch.model_fields_set
    if "name" in updated and patch.name is not None:
        tag.name = patch.name
    if "color" in updated and patch.color is not None:
        tag.color = patch.color
    if "match" in updated and patch.match is not None:
        tag.match = patch.match
    if "matching_algorithm" in updated and patch.matching_algorithm is not None:
        tag.matching_algorithm = patch.matching_algorithm
    if "is_insensitive" in updated and patch.is_insensitive is not None:
        tag.is_insensitive = patch.is_insensitive
    if "is_inbox_tag" in updated and patch.is_inbox_tag is not None:
        tag.is_inbox_tag = patch.is_inbox_tag
    db.flush()
    return _tag_to_out(tag)


def delete_tag(db: Session, tag_id: uuid.UUID) -> None:
    """Delete a tag (document_tags cascade automatically). 404 if not found."""
    tag = db.get(Tag, tag_id)
    if tag is None:
        raise HTTPException(status_code=404, detail="Tag not found.")
    db.delete(tag)
    db.flush()


def assign_tag(db: Session, user: TokenData, doc_id: uuid.UUID, tag_id: uuid.UUID) -> None:
    """Assign a tag to a document (idempotent). 404 if doc or tag not found."""
    tenant_id = uuid.UUID(user.tenant_id)  # type: ignore[arg-type]
    doc = db.get(Document, doc_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found.")
    tag = db.get(Tag, tag_id)
    if tag is None:
        raise HTTPException(status_code=404, detail="Tag not found.")

    db.execute(
        insert(DocumentTag)
        .values(id=uuid.uuid4(), tenant_id=tenant_id, document_id=doc_id, tag_id=tag_id)
        .prefix_with("ON CONFLICT (document_id, tag_id) DO NOTHING")
    )
    db.flush()


def unassign_tag(db: Session, doc_id: uuid.UUID, tag_id: uuid.UUID) -> None:
    """Remove a tag assignment. 404 if the assignment does not exist."""
    dt = db.scalars(
        select(DocumentTag).where(
            DocumentTag.document_id == doc_id,
            DocumentTag.tag_id == tag_id,
        )
    ).first()
    if dt is None:
        raise HTTPException(status_code=404, detail="Tag is not assigned to this document.")
    db.delete(dt)
    db.flush()
