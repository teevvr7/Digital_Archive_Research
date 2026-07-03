"""Saved views service — CRUD for per-tenant filter presets (Phase 6)."""

import uuid

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.saved_view import SavedView
from app.modules.views.schemas import SavedViewIn, SavedViewOut, SavedViewPatchIn


def _to_out(v: SavedView) -> SavedViewOut:
    return SavedViewOut(
        id=v.id,
        name=v.name,
        filter_state=v.filter_state,
        is_default=v.is_default,
        created_at=v.created_at,
    )


def list_saved_views(db: Session) -> list[SavedViewOut]:
    views = db.scalars(select(SavedView).order_by(SavedView.name)).all()
    return [_to_out(v) for v in views]


def create_saved_view(
    db: Session, tenant_id: uuid.UUID, data: SavedViewIn
) -> SavedViewOut:
    existing = db.scalars(
        select(SavedView).where(SavedView.name == data.name)
    ).first()
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A saved view named '{data.name}' already exists.",
        )
    view = SavedView(
        tenant_id=tenant_id,
        name=data.name,
        filter_state=data.filter_state,
        is_default=data.is_default,
    )
    db.add(view)
    db.flush()
    return _to_out(view)


def patch_saved_view(
    db: Session, view_id: uuid.UUID, data: SavedViewPatchIn
) -> SavedViewOut:
    view = db.get(SavedView, view_id)
    if view is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Saved view not found.")
    updated = data.model_fields_set
    if "name" in updated and data.name is not None:
        view.name = data.name
    if "filter_state" in updated and data.filter_state is not None:
        view.filter_state = data.filter_state
    if "is_default" in updated and data.is_default is not None:
        view.is_default = data.is_default
    db.flush()
    return _to_out(view)


def delete_saved_view(db: Session, view_id: uuid.UUID) -> None:
    view = db.get(SavedView, view_id)
    if view is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Saved view not found.")
    db.delete(view)
    db.flush()
