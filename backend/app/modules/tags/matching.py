"""Deterministic document-matching engine for tags and correspondents.

Algorithms (matching the paperless-ngx convention):
  none    — never auto-assign (manual only)
  any     — any word from the match pattern appears in the target text
  all     — all words from the match pattern appear in the target text
  literal — exact substring match (case-flag respected)
  regex   — treat the pattern as a regular expression

A bad regex never crashes the pipeline — it is swallowed with a warning.
"""

import logging
import re
import uuid

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models.correspondent import Correspondent
from app.models.document import Document
from app.models.tag import ALGO_ALL, ALGO_ANY, ALGO_LITERAL, ALGO_NONE, ALGO_REGEX, DocumentTag, Tag

logger = logging.getLogger(__name__)

# Characters to match against: title + first 5000 chars of extracted text.
_TEXT_CAP = 5000


def matches(pattern: str, algorithm: str, is_insensitive: bool, text: str) -> bool:
    """Return True if *text* satisfies the match rule defined by (*pattern*, *algorithm*)."""
    if algorithm == ALGO_NONE or not pattern:
        return False

    cmp_text = text.casefold() if is_insensitive else text
    cmp_pat = pattern.casefold() if is_insensitive else pattern

    if algorithm == ALGO_ANY:
        words = cmp_pat.split()
        return any(w in cmp_text for w in words) if words else False

    if algorithm == ALGO_ALL:
        words = cmp_pat.split()
        return all(w in cmp_text for w in words) if words else False

    if algorithm == ALGO_LITERAL:
        return cmp_pat in cmp_text

    if algorithm == ALGO_REGEX:
        flags = re.IGNORECASE if is_insensitive else 0
        try:
            return bool(re.search(pattern, text, flags))
        except re.error as exc:
            logger.warning("Invalid regex pattern %r: %s", pattern, exc)
            return False

    return False


def run_document_matching(db: Session, doc: Document, text: str) -> None:
    """Auto-assign tags and a correspondent to *doc* based on match rules.

    Called inside the IDP worker after extraction is complete. Any exception
    is swallowed so a rule crash never blocks the document pipeline.
    Must be called inside an open tenant_session (GUC already set).
    """
    combined = f"{doc.title or ''} {text}"[:_TEXT_CAP]

    # ---- Tags ---------------------------------------------------------------
    active_tags = db.scalars(
        select(Tag).where(
            Tag.tenant_id == doc.tenant_id,
            Tag.matching_algorithm != ALGO_NONE,
            Tag.match != "",
        )
    ).all()

    matched_tag_ids: list[uuid.UUID] = []
    for tag in active_tags:
        if matches(tag.match, tag.matching_algorithm, tag.is_insensitive, combined):
            matched_tag_ids.append(tag.id)

    if matched_tag_ids:
        for tag_id in matched_tag_ids:
            db.execute(
                insert(DocumentTag)
                .values(
                    id=uuid.uuid4(),
                    tenant_id=doc.tenant_id,
                    document_id=doc.id,
                    tag_id=tag_id,
                )
                .on_conflict_do_nothing(index_elements=["document_id", "tag_id"])
            )

    # ---- Correspondent ------------------------------------------------------
    if doc.correspondent_id is not None:
        # Already linked (e.g. from a previous run) — don't overwrite.
        return

    active_correspondents = db.scalars(
        select(Correspondent).where(
            Correspondent.tenant_id == doc.tenant_id,
            Correspondent.matching_algorithm != ALGO_NONE,
            Correspondent.match != "",
        )
    ).all()

    # Also check the extracted vendor name (exact case-folded equality) to
    # catch the common case where no match pattern was entered but the name
    # itself is the vendor string returned by extract.py.
    vendor_name: str | None = None
    if doc.extracted_data and isinstance(doc.extracted_data.get("vendor"), str):
        vendor_name = doc.extracted_data["vendor"].strip()

    for correspondent in active_correspondents:
        rule_hit = matches(
            correspondent.match,
            correspondent.matching_algorithm,
            correspondent.is_insensitive,
            combined,
        )
        name_hit = (
            vendor_name is not None
            and vendor_name.casefold() == correspondent.name.casefold()
        )
        if rule_hit or name_hit:
            doc.correspondent_id = correspondent.id
            break  # first match wins
