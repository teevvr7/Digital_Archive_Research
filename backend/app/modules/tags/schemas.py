"""Tag module schemas."""

import datetime
import uuid

from pydantic import Field

from app.core.camel import CamelModel


class TagIn(CamelModel):
    name: str = Field(max_length=100)
    color: str = "#6B7280"
    match: str = Field(default="", max_length=1000)
    matching_algorithm: str = "any"
    is_insensitive: bool = True
    is_inbox_tag: bool = False


class TagPatchIn(CamelModel):
    name: str | None = Field(default=None, max_length=100)
    color: str | None = None
    match: str | None = Field(default=None, max_length=1000)
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


class ApplyRulesOut(CamelModel):
    """Result of one page of the retroactive rule-backfill run — call again
    with the next page while ``has_more`` is true."""

    processed: int
    total: int
    has_more: bool
