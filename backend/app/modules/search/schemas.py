"""Search module response schemas (camelCase, ORM-friendly).

Field names mirror ``frontend/types/index.ts`` (``SearchResult`` /
``SearchListResponse``) once converted to camelCase by ``CamelModel``.

``snippet`` is server-rendered HTML from Postgres ``ts_headline`` — it contains
only ``<mark>`` highlight tags around source text that ``ts_headline`` has
already escaped, so it is safe for the client to render.
"""

from app.core.camel import CamelModel
from app.modules.files.schemas import DocumentOut


class SearchResultOut(CamelModel):
    """A single ranked search hit."""

    document: DocumentOut
    score: float
    snippet: str | None
    matched_fields: list[str]  # any of: "content", "filename"


class SearchListOut(CamelModel):
    """A page of search results."""

    items: list[SearchResultOut]
    total: int
    page: int
    page_size: int
