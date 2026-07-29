"""Document Share schemas."""

import datetime
import uuid

from app.core.camel import CamelModel


class ShareCreate(CamelModel):
    """Payload for generating a shareable token link."""

    document_id: uuid.UUID
    expires_in_days: int | None = 7


class ShareOut(CamelModel):
    """Share link output representation."""

    id: uuid.UUID
    document_id: uuid.UUID
    token: str
    share_url: str
    created_at: datetime.datetime
    expires_at: datetime.datetime | None
