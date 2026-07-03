"""Metadata module router — custom field catalog and document field values."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.deps import get_tenant_db
from app.core.security import TokenData
from app.modules.metadata import service
from app.modules.metadata.schemas import (
    CustomFieldIn,
    CustomFieldOut,
    CustomFieldPatchIn,
    FieldValueIn,
    FieldValueOut,
)

router = APIRouter(tags=["metadata"])

_DbCtx = Annotated[tuple[Session, TokenData], Depends(get_tenant_db)]


# ---- Custom field catalog ------------------------------------------------


@router.get(
    "/custom-fields",
    response_model=list[CustomFieldOut],
    response_model_by_alias=True,
    summary="List all custom field definitions for the current tenant",
)
def list_custom_fields(ctx: _DbCtx) -> list[CustomFieldOut]:
    db, _ = ctx
    return service.list_custom_fields(db)


@router.post(
    "/custom-fields",
    response_model=CustomFieldOut,
    response_model_by_alias=True,
    status_code=status.HTTP_201_CREATED,
    summary="Create a custom field definition",
)
def create_custom_field(ctx: _DbCtx, data: CustomFieldIn) -> CustomFieldOut:
    db, user = ctx
    tenant_id = uuid.UUID(user.tenant_id)  # type: ignore[arg-type]
    return service.create_custom_field(db, tenant_id, data)


@router.patch(
    "/custom-fields/{field_id}",
    response_model=CustomFieldOut,
    response_model_by_alias=True,
    summary="Update a custom field definition",
)
def patch_custom_field(
    ctx: _DbCtx, field_id: uuid.UUID, patch: CustomFieldPatchIn
) -> CustomFieldOut:
    db, _ = ctx
    return service.patch_custom_field(db, field_id, patch)


@router.delete(
    "/custom-fields/{field_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a custom field and all its document values",
)
def delete_custom_field(ctx: _DbCtx, field_id: uuid.UUID) -> None:
    db, _ = ctx
    service.delete_custom_field(db, field_id)


# ---- Document field values ----------------------------------------------


@router.post(
    "/documents/{doc_id}/fields/{field_id}",
    response_model=FieldValueOut,
    response_model_by_alias=True,
    status_code=status.HTTP_200_OK,
    summary="Set (upsert) a custom field value on a document",
)
def set_field_value(
    ctx: _DbCtx, doc_id: uuid.UUID, field_id: uuid.UUID, data: FieldValueIn
) -> FieldValueOut:
    db, user = ctx
    tenant_id = uuid.UUID(user.tenant_id)  # type: ignore[arg-type]
    return service.set_field_value(db, tenant_id, doc_id, field_id, data)


@router.delete(
    "/documents/{doc_id}/fields/{field_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Clear a custom field value from a document",
)
def delete_field_value(
    ctx: _DbCtx, doc_id: uuid.UUID, field_id: uuid.UUID
) -> None:
    db, _ = ctx
    service.delete_field_value(db, doc_id, field_id)
