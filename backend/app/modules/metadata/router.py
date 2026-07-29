"""Metadata Custom Fields API endpoints."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.deps import get_tenant_db
from app.core.security import TokenData
from app.modules.metadata import schemas, service

router = APIRouter(prefix="/metadata", tags=["Custom Metadata Fields"])

_DbCtx = Annotated[tuple[Session, TokenData], Depends(get_tenant_db)]


@router.get("/fields", response_model=list[schemas.CustomFieldOut], summary="List custom field definitions")
def get_custom_fields(ctx: _DbCtx):
    db, user = ctx
    fields = service.list_custom_fields(db, uuid.UUID(user.tenant_id))
    return fields


@router.post("/fields", response_model=schemas.CustomFieldOut, summary="Create a custom field definition")
def create_custom_field(body: schemas.CustomFieldCreate, ctx: _DbCtx):
    db, user = ctx
    field = service.create_custom_field(
        db,
        tenant_id=uuid.UUID(user.tenant_id),
        name=body.name,
        field_type=body.field_type,
        options=body.options,
        position=body.position,
    )
    return field


@router.post("/type-fields", response_model=schemas.TypeFieldOut, summary="Assign a custom field to a Document Type")
def assign_type_field(body: schemas.TypeFieldAssign, ctx: _DbCtx):
    db, user = ctx
    mapping = service.assign_field_to_type(
        db,
        tenant_id=uuid.UUID(user.tenant_id),
        document_type_id=body.document_type_id,
        field_id=body.field_id,
        is_required=body.is_required,
        position=body.position,
    )
    return mapping


@router.get("/type-fields/{doc_type_id}", response_model=list[schemas.TypeFieldOut], summary="Get custom fields for a Document Type")
def get_type_fields(doc_type_id: uuid.UUID, ctx: _DbCtx):
    db, user = ctx
    return service.list_type_fields(db, uuid.UUID(user.tenant_id), doc_type_id)
