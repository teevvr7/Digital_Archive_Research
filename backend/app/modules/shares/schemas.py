"""Shares module schemas (camelCase, ORM-friendly)."""

import datetime
import uuid

from app.core.camel import CamelModel


class ShareCreateIn(CamelModel):
    expires_in_days: int = 7


class ShareOut(CamelModel):
    id: uuid.UUID
    document_id: uuid.UUID
    token: str
    created_at: datetime.datetime
    expires_at: datetime.datetime


class ResolvedShareOut(CamelModel):
    """What the public, unauthenticated endpoint returns — a signed URL to
    broker the download, never the file bytes themselves."""

    url: str
    filename: str
    mime_type: str
