"""Metadata module schemas — custom field catalog and document field values."""

import datetime
import uuid
from typing import Any

from app.core.camel import CamelModel


class CustomFieldIn(CamelModel):
    """Input for creating a custom field definition."""

    name: str
    field_type: str  # text | number | date | boolean | select
    options: list[str] = []  # populated only for field_type='select'
    position: int = 0


class CustomFieldPatchIn(CamelModel):
    """Partial update for a custom field. Absent fields are left unchanged."""

    name: str | None = None
    options: list[str] | None = None
    position: int | None = None


class CustomFieldOut(CamelModel):
    """A custom field definition as returned by the API."""

    id: uuid.UUID
    name: str
    field_type: str
    options: list[str]
    position: int
    created_at: datetime.datetime


class FieldValueIn(CamelModel):
    """Input for setting (upserting) a custom field value on a document."""

    value: Any


class FieldValueOut(CamelModel):
    """A resolved custom field value embedded in document responses.

    Includes the field's display metadata so the frontend does not need a
    second call to look up the field definition.
    """

    field_id: uuid.UUID
    field_name: str
    field_type: str
    value: Any
