"""Tag module — CRUD + document assignment business logic."""

import uuid

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.security import TokenData
from app.models.document import Document
from app.models.tag import DocumentTag, Tag
from app.modules.tags.matching import run_document_matching
from app.modules.tags.schemas import ApplyRulesOut, TagIn, TagOut, TagPatchIn

# Cheap in-memory string matching against already-fetched extracted_text, no
# external calls — unlike extract_missing's VLM-enqueue batches, this can
# afford a larger page. Ordered oldest-first so repeated calls (page=1, 2, …)
# eventually cover every document rather than re-processing the same newest
# batch forever.
_APPLY_RULES_PAGE_SIZE = 200


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
        .on_conflict_do_nothing(index_elements=["document_id", "tag_id"])
    )
    db.flush()


def unassign_tag(db: Session, doc_id: uuid.UUID, tag_id: uuid.UUID) -> None:
    """Remove a tag assignment (idempotent — a no-op if already unassigned).

    Mirrors ``assign_tag``'s idempotency so a rapid double-click (two DELETE
    requests in flight) never surfaces a 404 to the user.
    """
    dt = db.scalars(
        select(DocumentTag).where(
            DocumentTag.document_id == doc_id,
            DocumentTag.tag_id == tag_id,
        )
    ).first()
    if dt is None:
        return
    db.delete(dt)
    db.flush()


def apply_rules_to_existing(db: Session, page: int = 1) -> ApplyRulesOut:
    """Retroactively run the tag/correspondent match engine over already-
    ingested documents — the rule engine only ever runs at ingest today, so
    a rule added or edited later never applies to existing documents without
    this. Idempotent (tag insert is ON CONFLICT DO NOTHING; correspondent is
    only set if unset), safe to call repeatedly. Paginated like the rest of
    the app — the frontend calls page=1, 2, … while ``has_more`` is true."""
    page = max(1, page)
    base = select(Document).where(Document.deleted_at.is_(None))

    total: int = db.scalar(select(func.count()).select_from(base.subquery())) or 0

    offset = (page - 1) * _APPLY_RULES_PAGE_SIZE
    rows = db.scalars(
        base.order_by(Document.uploaded_at.asc()).offset(offset).limit(_APPLY_RULES_PAGE_SIZE)
    ).all()

    for doc in rows:
        run_document_matching(db, doc, doc.extracted_text or "")
    db.flush()

    return ApplyRulesOut(
        processed=len(rows),
        total=total,
        has_more=offset + len(rows) < total,
    )
