"""Metadata Custom Fields schemas."""

import datetime
import uuid
from typing import Any

from app.core.camel import CamelModel


class CustomFieldCreate(CamelModel):
    name: str
    field_type: str  # text | number | date | boolean | select
    options: list[Any] = []
    position: int = 0


class CustomFieldIn(CamelModel):
    name: str
    field_type: str
    options: list[Any] = []
    position: int = 0


class CustomFieldPatchIn(CamelModel):
    name: str | None = None
    field_type: str | None = None
    options: list[Any] | None = None
    position: int | None = None


class CustomFieldOut(CamelModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    name: str
    field_type: str
    options: list[Any]
    position: int
    created_at: datetime.datetime


class FieldValueIn(CamelModel):
    value: Any


class FieldValueSet(CamelModel):
    field_id: uuid.UUID
    value: Any


class FieldValueOut(CamelModel):
    id: uuid.UUID
    document_id: uuid.UUID
    field_id: uuid.UUID
    value: Any
    field: CustomFieldOut | None = None


class TypeFieldAssign(CamelModel):
    document_type_id: uuid.UUID
    field_id: uuid.UUID
    is_required: bool = False
    position: int = 0


class TypeFieldOut(CamelModel):
    id: uuid.UUID
    document_type_id: uuid.UUID
    field_id: uuid.UUID
    is_required: bool
    position: int
    field: CustomFieldOut
