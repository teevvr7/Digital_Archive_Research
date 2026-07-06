"""Tag module schemas."""

import datetime
import uuid

from app.core.camel import CamelModel


class TagIn(CamelModel):
    name: str
    color: str = "#6B7280"
    match: str = ""
    matching_algorithm: str = "any"
    is_insensitive: bool = True
    is_inbox_tag: bool = False


class TagPatchIn(CamelModel):
    name: str | None = None
    color: str | None = None
    match: str | None = None
    matching_algorithm: str | None = None
    is_insensitive: bool | None = None
    is_inbox_tag: bool | None = None


class TagOut(CamelModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    name: str
    color: str
    match: str
    matching_algorithm: str
    is_insensitive: bool
    is_inbox_tag: bool
    created_at: datetime.datetime
