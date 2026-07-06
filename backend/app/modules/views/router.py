"""Saved views router (Phase 6 — Retrieval & UX)."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.deps import get_tenant_db
from app.core.security import TokenData
from app.modules.views import service
from app.modules.views.schemas import SavedViewIn, SavedViewOut, SavedViewPatchIn

router = APIRouter(prefix="/saved-views", tags=["saved-views"])

_DbCtx = Annotated[tuple[Session, TokenData], Depends(get_tenant_db)]


@router.get("", response_model=list[SavedViewOut], response_model_by_alias=True)
def list_saved_views(ctx: _DbCtx) -> list[SavedViewOut]:
    db, _ = ctx
    return service.list_saved_views(db)


@router.post(
    "",
    response_model=SavedViewOut,
    response_model_by_alias=True,
    status_code=status.HTTP_201_CREATED,
)
def create_saved_view(ctx: _DbCtx, data: SavedViewIn) -> SavedViewOut:
    db, user = ctx
    return service.create_saved_view(db, uuid.UUID(user.tenant_id), data)


@router.patch(
    "/{view_id}",
    response_model=SavedViewOut,
    response_model_by_alias=True,
)
def patch_saved_view(ctx: _DbCtx, view_id: uuid.UUID, data: SavedViewPatchIn) -> SavedViewOut:
    db, _ = ctx
    return service.patch_saved_view(db, view_id, data)


@router.delete("/{view_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_saved_view(ctx: _DbCtx, view_id: uuid.UUID) -> None:
    db, _ = ctx
    service.delete_saved_view(db, view_id)
