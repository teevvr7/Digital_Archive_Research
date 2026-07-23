"""Metadata module schemas — custom field catalog and document field values."""

import datetime
import uuid
from typing import Any

from pydantic import Field, field_validator

from app.core.camel import CamelModel

# Custom-field text VALUES aren't name-like labels — they can be a genuine
# user-entered note — so they get a much more generous cap than the 100-char
# field NAME, just enough to bound a pathological payload.
_MAX_FIELD_VALUE_LENGTH = 5000


class CustomFieldIn(CamelModel):
    """Input for creating a custom field definition."""

    name: str = Field(max_length=100)
    field_type: str  # text | number | date | boolean | select
    options: list[str] = []  # populated only for field_type='select'
    position: int = 0


class CustomFieldPatchIn(CamelModel):
    """Partial update for a custom field. Absent fields are left unchanged."""

    name: str | None = Field(default=None, max_length=100)
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

    @field_validator("value")
    @classmethod
    def _cap_string_length(cls, v: Any) -> Any:
        # `Any` bypasses pydantic's normal str constraints, so a text-type
        # value needs its own explicit length cap.
        if isinstance(v, str) and len(v) > _MAX_FIELD_VALUE_LENGTH:
            raise ValueError(
                f"Value exceeds maximum length of {_MAX_FIELD_VALUE_LENGTH} characters"
            )
        return v


class FieldValueOut(CamelModel):
    """A resolved custom field value embedded in document responses.

    Includes the field's display metadata so the frontend does not need a
    second call to look up the field definition.
    """

    field_id: uuid.UUID
    field_name: str
    field_type: str
    value: Any


class PredefinedFieldIn(CamelModel):
    """Input for attaching an existing custom field as predefined for a document type."""

    field_id: uuid.UUID
    required: bool = False
    position: int = 0


class PredefinedFieldPatchIn(CamelModel):
    """Partial update for a predefined-field attachment."""

    required: bool | None = None
    position: int | None = None


class PredefinedFieldOut(CamelModel):
    """A custom field predefined for a document type, with its display metadata."""

    id: uuid.UUID
    document_type: str
    field_id: uuid.UUID
    field_name: str
    field_type: str
    options: list[str]
    required: bool
    position: int
