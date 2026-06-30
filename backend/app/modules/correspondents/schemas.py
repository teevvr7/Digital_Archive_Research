"""Correspondent module schemas."""

import datetime
import uuid

from app.core.camel import CamelModel


class CorrespondentIn(CamelModel):
    name: str
    match: str = ""
    matching_algorithm: str = "any"
    is_insensitive: bool = True


class CorrespondentPatchIn(CamelModel):
    name: str | None = None
    match: str | None = None
    matching_algorithm: str | None = None
    is_insensitive: bool | None = None


class CorrespondentOut(CamelModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    name: str
    match: str
    matching_algorithm: str
    is_insensitive: bool
    created_at: datetime.datetime
