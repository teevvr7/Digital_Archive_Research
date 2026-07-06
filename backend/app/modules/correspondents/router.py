"""Correspondents module router."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.deps import get_tenant_db
from app.core.security import TokenData
from app.modules.correspondents import service
from app.modules.correspondents.schemas import CorrespondentIn, CorrespondentOut, CorrespondentPatchIn

router = APIRouter(tags=["correspondents"])

_DbCtx = Annotated[tuple[Session, TokenData], Depends(get_tenant_db)]


@router.get(
    "/correspondents",
    response_model=list[CorrespondentOut],
    response_model_by_alias=True,
)
def list_correspondents(ctx: _DbCtx) -> list[CorrespondentOut]:
    db, _ = ctx
    return service.list_correspondents(db)


@router.post(
    "/correspondents",
    response_model=CorrespondentOut,
    response_model_by_alias=True,
    status_code=status.HTTP_201_CREATED,
)
def create_correspondent(ctx: _DbCtx, data: CorrespondentIn) -> CorrespondentOut:
    db, user = ctx
    return service.create_correspondent(db, user, data)


@router.patch(
    "/correspondents/{correspondent_id}",
    response_model=CorrespondentOut,
    response_model_by_alias=True,
)
def patch_correspondent(
    ctx: _DbCtx, correspondent_id: uuid.UUID, patch: CorrespondentPatchIn
) -> CorrespondentOut:
    db, _ = ctx
    return service.patch_correspondent(db, correspondent_id, patch)


@router.delete(
    "/correspondents/{correspondent_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_correspondent(ctx: _DbCtx, correspondent_id: uuid.UUID) -> None:
    db, _ = ctx
    service.delete_correspondent(db, correspondent_id)
