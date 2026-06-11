"""Search module — full-text content + fuzzy filename search business logic.

RLS scopes every query to the tenant set by the GUC (the router depends on
``get_tenant_db``), so no tenant filtering is needed here — identical safety to
the files/list path.
"""

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models.document import Document
from app.modules.files.service import _PAGE_SIZE, _doc_to_out, _names_for_ids
from app.modules.search import query as q_builders
from app.modules.search.schemas import SearchListOut, SearchResultOut


def search_documents(
    db: Session,
    *,
    q: str | None,
    type_filter: str | None = None,
    date_filter: str | None = None,
    status_filter: str | None = None,
    page: int = 1,
) -> SearchListOut:
    """Return a ranked, paginated page of documents matching ``q``.

    Matches on full-text content (``search_tsv``) OR fuzzy filename (pg_trgm),
    ordered by combined relevance. Each hit carries a highlighted ``snippet``
    (when the content matched) and the ``matched_fields`` that fired. An empty
    query yields no results so the UI can show its empty state.
    """
    term = (q or "").strip()
    if not term:
        return SearchListOut(items=[], total=0, page=1, page_size=_PAGE_SIZE)

    tsquery = q_builders.build_tsquery(term)
    hl_tsquery = q_builders.build_headline_tsquery(term)
    content = q_builders.content_match(term, tsquery)
    fname = q_builders.filename_match(term)
    rank = q_builders.rank_expr(term, tsquery)
    snippet = q_builders.snippet_expr(hl_tsquery, content)

    stmt = select(
        Document,
        rank.label("score"),
        snippet.label("snippet"),
        content.label("content_match"),
        fname.label("filename_match"),
    ).where(or_(content, fname))

    if type_filter:
        stmt = stmt.where(Document.document_type == type_filter)
    if status_filter:
        stmt = stmt.where(Document.status == status_filter)
    cutoff = q_builders.date_cutoff(date_filter)
    if cutoff is not None:
        stmt = stmt.where(Document.uploaded_at >= cutoff)

    stmt = stmt.order_by(rank.desc(), Document.uploaded_at.desc())

    total: int = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0

    offset = (page - 1) * _PAGE_SIZE
    rows = db.execute(stmt.offset(offset).limit(_PAGE_SIZE)).all()

    names = _names_for_ids(db, {row[0].uploaded_by for row in rows})
    items: list[SearchResultOut] = []
    for doc, score, snip, content_m, fname_m in rows:
        matched: list[str] = []
        if content_m:
            matched.append("content")
        if fname_m:
            matched.append("filename")
        items.append(
            SearchResultOut(
                document=_doc_to_out(doc, names.get(doc.uploaded_by, str(doc.uploaded_by))),
                score=float(score or 0.0),
                snippet=snip,
                matched_fields=matched,
            )
        )

    return SearchListOut(items=items, total=total, page=page, page_size=_PAGE_SIZE)
