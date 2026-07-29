"""Reusable Postgres full-text + trigram search SQL builders.

Kept dependency-light (only the ``Document`` model + SQLAlchemy) so that both the
search service *and* the files list endpoint can share one matching/ranking
definition without creating an import cycle (``files.service`` imports from here;
``search.service`` imports from here and from ``files.service``).

All matching runs on indexes already in the schema (migration 0001):
``ix_documents_search_tsv`` (GIN on the tsvector) and ``ix_documents_filename_trgm``
(GIN trigram on ``original_filename``). No external search service — pure Postgres.
"""

import datetime
import html
import re

from sqlalchemy import Select, case, func, or_

from app.models.document import Document


def _prefix_tsquery_str(q: str) -> str | None:
    """Build 'tok1:* & tok2:*' so partial words like 'elec' match 'electricity'."""
    tokens = [t for t in re.split(r"[^a-zA-Z0-9]", q) if len(t) >= 2]
    if not tokens:
        return None
    return " & ".join(f"{t}:*" for t in tokens)


# ts_headline options: wrap matches in sentinel control characters (never legal
# in extracted text), return up to 2 short fragments. The sentinels — not
# literal <mark> tags — are what make snippet_html_safe() below sound: they
# survive html.escape() untouched (it only touches &, <, > and quotes) and are
# swapped for real <mark>/</mark> tags only *after* the rest of the string has
# been escaped, so nothing from the source document can inject markup.
_MARK_START = "\x01"
_MARK_END = "\x02"
_HEADLINE_OPTS = (
    f"StartSel={_MARK_START},StopSel={_MARK_END},MaxFragments=2,MinWords=5,MaxWords=24,ShortWord=2"
)


def snippet_html_safe(raw: str | None) -> str | None:
    """Turn a raw ``ts_headline`` result into HTML that is safe to render.

    ``ts_headline`` does NOT escape the source text it quotes — it only
    inserts the literal StartSel/StopSel strings around matched terms. Any
    ``<``, ``>``, or ``&`` present in a document's extracted text would
    otherwise pass straight into the client's ``dangerouslySetInnerHTML``
    (search/page.tsx), a stored-XSS vector. Escape the whole string first,
    then turn the (escape-proof) sentinel characters into real mark tags.
    """
    if raw is None:
        return None
    escaped = html.escape(raw, quote=False)
    return escaped.replace(_MARK_START, "<mark>").replace(_MARK_END, "</mark>")


def build_search_text(title: str, original_filename: str, extracted_text: str | None) -> str:
    """Combine title + original filename + extracted text for the ``search_tsv`` index.

    Title is included (not just ``original_filename``) so a document renamed via
    the correction UI stays findable by its new name; the original filename stays
    in the mix too so the pre-rename name remains searchable. Called both at
    initial pipeline processing and whenever ``patch_document`` changes the title,
    so the two never drift out of sync.
    """
    return " ".join(filter(None, [title, original_filename, extracted_text]))


def build_tsquery(q: str):
    """``websearch_to_tsquery``: handles quoted "phrases", OR, -exclude; never errors."""
    return func.websearch_to_tsquery("english", q)


def build_headline_tsquery(q: str):
    """Tsquery used only for ``ts_headline`` highlighting.

    Uses the prefix variant (``word:*``) so that partial words like ``elec``
    cause ``electricity`` to be highlighted in the snippet. Falls back to the
    websearch tsquery when no clean tokens can be extracted.
    """
    prefix_str = _prefix_tsquery_str(q)
    if prefix_str is None:
        return build_tsquery(q)
    return func.to_tsquery("english", prefix_str)


def content_match(q: str, tsquery):
    """True when the document's full-text index matches the query.

    ORs the exact websearch match with a prefix variant so partial words
    like 'elec' also match 'electricity'.
    """
    base = Document.search_tsv.op("@@")(tsquery)
    prefix_str = _prefix_tsquery_str(q)
    if prefix_str is None:
        return base
    return or_(base, Document.search_tsv.op("@@")(func.to_tsquery("english", prefix_str)))


def _name_similarity(q: str):
    """Best pg_trgm word_similarity against either the (possibly renamed) title
    or the original filename, so a document stays findable by both its current
    and its original name after a correction-UI rename."""
    effective_title = func.coalesce(Document.title, Document.original_filename)
    return func.greatest(
        func.word_similarity(q.lower(), func.lower(effective_title)),
        func.word_similarity(q.lower(), func.lower(Document.original_filename)),
    )


def filename_match(q: str):
    """Typo-tolerant title/filename match via pg_trgm word_similarity (case-insensitive, threshold 0.3).

    Uses ``word_similarity(q, name)`` directly so the threshold is explicit and
    not affected by the session-level GUC default (0.6 is too strict for real typos).
    Lowercases both sides so "Quarterly" matches "quartrly".
    """
    return _name_similarity(q) >= 0.2


def rank_expr(q: str, tsquery):
    """Combined relevance score: content rank + title/filename word-similarity (NULL-safe)."""
    return func.coalesce(func.ts_rank_cd(Document.search_tsv, tsquery), 0.0) + func.coalesce(
        _name_similarity(q), 0.0
    )


def snippet_expr(tsquery, matched):
    """``ts_headline`` snippet, only when content matched.

    Returns the **raw** ``ts_headline`` output — sentinel-wrapped, not yet
    HTML-safe. Callers must pass it through :func:`snippet_html_safe` before
    it ever reaches a client that renders it as HTML.
    """
    return case(
        (matched, func.ts_headline("english", Document.extracted_text, tsquery, _HEADLINE_OPTS)),
        else_=None,
    )


def apply_text_search(stmt: Select, q: str):
    """Filter a ``select(Document)`` to text/filename matches; return ``(stmt, rank)``.

    Shared by the ``/documents`` list and ``/search`` so both rank identically.
    A document surfaces when *either* its content or its filename matches.
    """
    tsquery = build_tsquery(q)
    stmt = stmt.where(or_(content_match(q, tsquery), filename_match(q)))
    return stmt, rank_expr(q, tsquery)


def date_cutoff(date_filter: str | None) -> datetime.datetime | None:
    """Map ``any|today|week|month`` → a UTC lower bound on ``uploaded_at`` (or None)."""
    if not date_filter or date_filter == "any":
        return None
    now = datetime.datetime.now(datetime.UTC)
    if date_filter == "today":
        return now.replace(hour=0, minute=0, second=0, microsecond=0)
    if date_filter == "week":
        return now - datetime.timedelta(days=7)
    if date_filter == "month":
        return now - datetime.timedelta(days=30)
    return None
