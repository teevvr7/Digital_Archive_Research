"""Correspondent module schemas."""

import datetime
import uuid

from pydantic import Field

from app.core.camel import CamelModel
from app.core.validation import EmailField


class CorrespondentIn(CamelModel):
    name: str = Field(max_length=200)
    email: EmailField | None = None
    match: str = Field(default="", max_length=1000)
    matching_algorithm: str = "any"
    is_insensitive: bool = True


class CorrespondentPatchIn(CamelModel):
    name: str | None = Field(default=None, max_length=200)
    email: EmailField | None = None
    match: str | None = Field(default=None, max_length=1000)
    matching_algorithm: str | None = None
    is_insensitive: bool | None = None


class CorrespondentOut(CamelModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    name: str
    email: str | None
    match: str
    matching_algorithm: str
    is_insensitive: bool
    created_at: datetime.datetime
