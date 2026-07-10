"""Export module request schemas (camelCase, ORM-friendly)."""

import uuid

from app.core.camel import CamelModel


class BulkDownloadIn(CamelModel):
    document_ids: list[uuid.UUID]
