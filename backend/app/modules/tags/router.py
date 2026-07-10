"""Tags module router."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.deps import get_tenant_db
from app.core.security import TokenData
from app.modules.tags import service
from app.modules.tags.schemas import ApplyRulesOut, TagIn, TagOut, TagPatchIn

router = APIRouter(tags=["tags"])

_DbCtx = Annotated[tuple[Session, TokenData], Depends(get_tenant_db)]


@router.get("/tags", response_model=list[TagOut], response_model_by_alias=True)
def list_tags(ctx: _DbCtx) -> list[TagOut]:
    db, _ = ctx
    return service.list_tags(db)


@router.post(
    "/tags",
    response_model=TagOut,
    response_model_by_alias=True,
    status_code=status.HTTP_201_CREATED,
)
def create_tag(ctx: _DbCtx, data: TagIn) -> TagOut:
    db, user = ctx
    return service.create_tag(db, user, data)


@router.patch("/tags/{tag_id}", response_model=TagOut, response_model_by_alias=True)
def patch_tag(ctx: _DbCtx, tag_id: uuid.UUID, patch: TagPatchIn) -> TagOut:
    db, _ = ctx
    return service.patch_tag(db, tag_id, patch)


@router.delete("/tags/{tag_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_tag(ctx: _DbCtx, tag_id: uuid.UUID) -> None:
    db, _ = ctx
    service.delete_tag(db, tag_id)


@router.post(
    "/documents/{doc_id}/tags/{tag_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Assign a tag to a document",
)
def assign_tag(ctx: _DbCtx, doc_id: uuid.UUID, tag_id: uuid.UUID) -> None:
    db, user = ctx
    service.assign_tag(db, user, doc_id, tag_id)


@router.delete(
    "/documents/{doc_id}/tags/{tag_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove a tag from a document",
)
def unassign_tag(ctx: _DbCtx, doc_id: uuid.UUID, tag_id: uuid.UUID) -> None:
    db, _ = ctx
    service.unassign_tag(db, doc_id, tag_id)


@router.post(
    "/tags/apply-rules",
    response_model=ApplyRulesOut,
    response_model_by_alias=True,
    summary="Retroactively apply tag/correspondent match rules to existing documents",
)
def apply_rules_to_existing(ctx: _DbCtx, page: int = 1) -> ApplyRulesOut:
    db, _ = ctx
    return service.apply_rules_to_existing(db, page=page)
