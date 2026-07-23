"""Search module response schemas (camelCase, ORM-friendly).

Field names mirror ``frontend/types/index.ts`` (``SearchResult`` /
``SearchListResponse``) once converted to camelCase by ``CamelModel``.

``snippet`` is server-rendered HTML: source text is HTML-escaped in Python
(``search/query.py::snippet_html_safe``) before ``<mark>`` highlight tags are
reinserted, so it is safe for the client to render via
``dangerouslySetInnerHTML``. ``ts_headline`` itself does NOT escape the
source text — only ``snippet_html_safe`` makes this safe.
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
