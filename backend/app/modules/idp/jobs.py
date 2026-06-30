"""RQ job functions for the IDP pipeline.

``process_document`` is the entrypoint enqueued by the files module when a
document is uploaded or retried. It drives the document through its status
states, persists extraction results, and handles failures.

All DB access goes through ``tenant_session`` so RLS is enforced exactly as it
is in the API request path — no data-access shortcuts in the worker.
"""

import datetime
import logging
import time
import uuid

from sqlalchemy import func, select, update

from app.core import ai_budget
from app.core import storage as object_storage
from app.core.config import settings
from app.core.tenant_context import tenant_session
from app.modules.idp import extract, gate, mimetype
from app.modules.idp.thumbnails import generate_thumbnail
from app.models.activity_event import (
    ACT_PROCESSING_COMPLETE,
    ACT_PROCESSING_FAILED,
    ActivityEvent,
)
from app.models.document import (
    STATUS_AI,
    STATUS_COMPLETED,
    STATUS_EXTRACTING_TEXT,
    STATUS_FAILED,
    STATUS_NEEDS_REVIEW,
    STATUS_OCR,
    Document,
)
from app.models.extraction import (
    EXTRACTION_ACCEPTED,
    EXTRACTION_LOW_CONFIDENCE,
    EXTRACTION_SKIPPED_BUDGET,
    METHOD_DETERMINISTIC,
    METHOD_VLM,
    Extraction,
)
from app.models.processing_job import (
    JOB_COMPLETED,
    JOB_FAILED,
    JOB_RUNNING,
    ProcessingJob,
)
from app.modules.idp.pipeline import run_ai_extraction, run_extraction

logger = logging.getLogger(__name__)

_VLM_ELIGIBLE_MIMES = mimetype.VLM_ELIGIBLE_MIMES


def _guess_document_date(text: str | None) -> datetime.date | None:
    """Best-effort document date from content. Never raises, never blocks the doc."""
    if not text:
        return None
    try:
        import dateparser.search

        results = dateparser.search.search_dates(
            text[:2000], settings={"PREFER_DATES_FROM": "past"}
        )
        if not results:
            return None
        return results[0][1].date()
    except Exception:
        logger.debug("document_date heuristic failed", exc_info=True)
        return None


def _attach_thumbnail(db, doc: Document, file_bytes: bytes) -> None:
    """Generate + upload a thumbnail, isolated from the rest of the pipeline."""
    try:
        thumb = generate_thumbnail(file_bytes, doc.mime_type)
        if thumb is None:
            return
        thumb_key = f"{doc.tenant_id}/thumbnails/{doc.id}.png"
        object_storage.upload_file(thumb_key, thumb, "image/png")
        doc.thumbnail_key = thumb_key
    except Exception as exc:
        logger.warning("Thumbnail generation crashed (doc=%s): %s", doc.id, exc)


def process_document(doc_id: str, tenant_id: str) -> None:
    """Extract text from a stored document and persist the result.

    Status transitions:
        queued → extracting_text [→ ocr_processing] → completed
                                                     → failed (on error)

    Raises on unrecoverable errors so RQ can record the failure and schedule
    a retry (up to the ``Retry`` limit set in ``queue.py``).
    """
    doc_uuid = uuid.UUID(doc_id)
    tenant_uuid = uuid.UUID(tenant_id)
    t_start = time.perf_counter()

    logger.info("IDP start: doc=%s tenant=%s", doc_id, tenant_id)

    with tenant_session(str(tenant_id)) as db:
        doc = db.get(Document, doc_uuid)
        if doc is None:
            # Row not visible yet (upload→commit race) — raise so RQ retries.
            raise LookupError(f"Document {doc_id} not found under tenant {tenant_id}")

        job = db.scalars(
            select(ProcessingJob).where(ProcessingJob.document_id == doc_uuid)
        ).first()
        if job is None:
            raise LookupError(f"ProcessingJob for document {doc_id} not found")

        # --- Mark running ---
        job.status = JOB_RUNNING
        job.started_at = datetime.datetime.now(datetime.timezone.utc)
        job.attempts = (job.attempts or 0) + 1
        doc.status = STATUS_EXTRACTING_TEXT
        job.stage = "text_extraction"
        db.flush()

        try:
            file_bytes = object_storage.download_file(doc.storage_key)

            result = run_extraction(file_bytes, doc.mime_type)

            # Update status mid-pipeline so the UI shows "ocr_processing".
            if result.ocr_used:
                doc.status = STATUS_OCR
                job.stage = "ocr_processing"
                db.flush()

            # --- Structured extraction (isolated — never fails the document) ---
            # Type-conditional, two tiers: Tier 2 (deterministic, free) is tried
            # first; the VLM (Tier 4, metered) runs ONLY when Tier 2 doesn't pass
            # the gate. Neither tier is attempted at all unless the mime type is
            # VLM-eligible AND the content itself looks invoice/receipt-like —
            # contracts/reports/letters/office files never reach either tier,
            # they just get the universal baseline (text/thumbnail/metadata).
            deterministic_accepted = False
            extraction_attempted = False
            vlm_accepted = False

            if doc.mime_type in _VLM_ELIGIBLE_MIMES:
                job.stage = "deterministic_extraction"
                db.flush()

                candidate = extract.extract_candidate(result.text)
                if candidate is not None:
                    extraction_attempted = True
                    gate_result = gate.score_extraction(candidate, result.ocr_confidence)
                    db.add(Extraction(
                        tenant_id=tenant_uuid,
                        document_id=doc_uuid,
                        method=METHOD_DETERMINISTIC,
                        model_name=None,
                        output=candidate.to_fields(),
                        confidence=gate_result.score,
                        status=EXTRACTION_ACCEPTED if gate_result.passed else EXTRACTION_LOW_CONFIDENCE,
                    ))
                    if gate_result.passed:
                        doc.extracted_data = candidate.to_fields()
                        doc.confidence = gate_result.score
                        doc.document_type = candidate.document_type
                        deterministic_accepted = True
                        logger.info(
                            "Deterministic extraction accepted: doc=%s type=%s score=%.2f",
                            doc_id, candidate.document_type, gate_result.score,
                        )
                    else:
                        logger.info(
                            "Deterministic extraction gate-failed: doc=%s type=%s score=%.2f breakdown=%s",
                            doc_id, candidate.document_type, gate_result.score, gate_result.breakdown,
                        )

                if not deterministic_accepted and extraction_attempted:
                    doc.status = STATUS_AI
                    job.stage = "ai_extraction"
                    db.flush()

                    try:
                        if not ai_budget.llm_allowed(db, tenant_uuid):
                            logger.warning(
                                "LLM monthly token budget exceeded for tenant=%s — skipping VLM extraction (doc=%s)",
                                tenant_id, doc_id,
                            )
                            db.add(Extraction(
                                tenant_id=tenant_uuid,
                                document_id=doc_uuid,
                                method=METHOD_VLM,
                                model_name=settings.vlm_model or None,
                                output={"_error": "monthly LLM token budget exceeded", "_mode": "budget_blocked"},
                                confidence=None,
                                status=EXTRACTION_SKIPPED_BUDGET,
                            ))
                        else:
                            outcome = run_ai_extraction(
                                file_bytes, doc.mime_type, result.text or None, result.has_text_layer
                            )
                            if outcome.total_tokens:
                                ai_budget.record_ai_usage(
                                    db,
                                    tenant_id=tenant_uuid,
                                    document_id=doc_uuid,
                                    model_name=settings.vlm_model or None,
                                    prompt_tokens=outcome.prompt_tokens,
                                    completion_tokens=outcome.completion_tokens,
                                    total_tokens=outcome.total_tokens,
                                )
                            if outcome.extraction is not None:
                                ai = outcome.extraction
                                doc.extracted_data = ai.fields
                                doc.confidence = ai.confidence
                                doc.document_type = ai.document_type
                                ext_status = (
                                    EXTRACTION_ACCEPTED
                                    if ai.confidence >= settings.confidence_threshold
                                    else EXTRACTION_LOW_CONFIDENCE
                                )
                                vlm_accepted = ext_status == EXTRACTION_ACCEPTED
                                db.add(Extraction(
                                    tenant_id=tenant_uuid,
                                    document_id=doc_uuid,
                                    method=METHOD_VLM,
                                    model_name=ai.model_name,
                                    output=ai.fields,
                                    confidence=ai.confidence,
                                    status=ext_status,
                                ))
                                logger.info(
                                    "AI extraction persisted: doc=%s mode=%s type=%s confidence=%.2f status=%s",
                                    doc_id, outcome.mode, ai.document_type, ai.confidence, ext_status,
                                )
                            elif outcome.error:
                                # Failure (not a clean skip) — record the reason for the audit trail.
                                logger.warning(
                                    "AI extraction produced no data (doc=%s mode=%s): %s",
                                    doc_id, outcome.mode, outcome.error,
                                )
                                db.add(Extraction(
                                    tenant_id=tenant_uuid,
                                    document_id=doc_uuid,
                                    method=METHOD_VLM,
                                    model_name=settings.vlm_model or None,
                                    output={"_error": outcome.error, "_mode": outcome.mode},
                                    confidence=None,
                                    status=EXTRACTION_LOW_CONFIDENCE,
                                ))
                    except Exception as exc:
                        logger.warning(
                            "AI extraction crashed (doc=%s) — document will complete without structured data: %s",
                            doc_id, exc,
                        )
                        db.add(Extraction(
                            tenant_id=tenant_uuid,
                            document_id=doc_uuid,
                            method=METHOD_VLM,
                            model_name=settings.vlm_model or None,
                            output={"_error": f"{type(exc).__name__}: {exc}"[:500], "_mode": "crash"},
                            confidence=None,
                            status=EXTRACTION_LOW_CONFIDENCE,
                        ))
                elif not extraction_attempted:
                    logger.debug(
                        "Structured extraction skipped (doc=%s mime=%s) — content doesn't look like an invoice/receipt",
                        doc_id, doc.mime_type,
                    )
            else:
                logger.debug(
                    "Structured extraction skipped (doc=%s mime=%s) — not a structured-extraction candidate type",
                    doc_id, doc.mime_type,
                )

            needs_review = extraction_attempted and not deterministic_accepted and not vlm_accepted

            # Persist extraction results.
            doc.extracted_text = result.text or None
            doc.page_count = result.page_count
            doc.has_text_layer = result.has_text_layer
            doc.ocr_used = result.ocr_used
            doc.ocr_confidence = result.ocr_confidence
            doc.document_date = _guess_document_date(result.text)
            _attach_thumbnail(db, doc, file_bytes)

            # Populate full-text search index: filename + extracted text.
            combined = " ".join(filter(None, [doc.original_filename, result.text]))
            db.execute(
                update(Document)
                .where(Document.id == doc_uuid)
                .values(search_tsv=func.to_tsvector("english", combined))
            )

            now = datetime.datetime.now(datetime.timezone.utc)
            doc.status = STATUS_NEEDS_REVIEW if needs_review else STATUS_COMPLETED
            doc.processed_at = now

            # Auto-tag + auto-link correspondent (deterministic, never raises).
            try:
                from app.modules.tags.matching import run_document_matching
                run_document_matching(db, doc, result.text or "")
            except Exception as _exc:
                logger.warning("Auto-matching crashed (doc=%s): %s", doc_id, _exc)

            duration_ms = int((time.perf_counter() - t_start) * 1000)
            job.status = JOB_COMPLETED
            job.stage = None
            job.finished_at = now
            job.duration_ms = duration_ms

            db.add(ActivityEvent(
                tenant_id=tenant_uuid,
                type=ACT_PROCESSING_COMPLETE,
                document_id=doc_uuid,
                document_name=doc.original_filename,
                user_id=None,
                user_name="system",
            ))

            logger.info(
                "IDP complete: doc=%s duration=%dms ocr=%s pages=%d chars=%d",
                doc_id,
                duration_ms,
                result.ocr_used,
                result.page_count,
                len(result.text),
            )

        except Exception as exc:
            now = datetime.datetime.now(datetime.timezone.utc)
            error_msg = str(exc)

            doc.status = STATUS_FAILED
            doc.error_message = error_msg[:2000]  # guard against giant tracebacks

            duration_ms = int((time.perf_counter() - t_start) * 1000)
            job.status = JOB_FAILED
            job.finished_at = now
            job.duration_ms = duration_ms
            job.error = error_msg[:2000]

            db.add(ActivityEvent(
                tenant_id=tenant_uuid,
                type=ACT_PROCESSING_FAILED,
                document_id=doc_uuid,
                document_name=doc.original_filename,
                user_id=None,
                user_name="system",
                meta=error_msg[:500],
            ))

            logger.error("IDP failed: doc=%s error=%s", doc_id, error_msg)
            raise  # let RQ record the failure and schedule a retry


def ai_extract_document(doc_id: str, tenant_id: str) -> None:
    """Re-run only the VLM structured-extraction stage on an already-completed doc.

    Safe to enqueue multiple times (idempotent: overwrites ``extracted_data``).
    The document stays ``completed`` regardless of the VLM outcome — text search
    is unaffected. Used by the per-doc re-extract button and the bulk
    ``extract-missing`` endpoint.
    """
    doc_uuid = uuid.UUID(doc_id)
    t_start = time.perf_counter()
    logger.info("AI re-extract start: doc=%s tenant=%s", doc_id, tenant_id)

    with tenant_session(str(tenant_id)) as db:
        doc = db.get(Document, doc_uuid)
        if doc is None:
            raise LookupError(f"Document {doc_id} not found under tenant {tenant_id}")

        if not doc.extracted_text and doc.status != "completed":
            logger.warning(
                "AI re-extract skipped for doc=%s — not yet completed or no text", doc_id
            )
            return

        if doc.mime_type not in _VLM_ELIGIBLE_MIMES:
            logger.info(
                "AI re-extract skipped (doc=%s mime=%s) — not a structured-extraction candidate",
                doc_id, doc.mime_type,
            )
            return

        try:
            if not ai_budget.llm_allowed(db, doc.tenant_id):
                logger.warning(
                    "LLM monthly token budget exceeded for tenant=%s — skipping AI re-extract (doc=%s)",
                    doc.tenant_id, doc_id,
                )
                db.add(Extraction(
                    tenant_id=doc.tenant_id,
                    document_id=doc_uuid,
                    method=METHOD_VLM,
                    model_name=settings.vlm_model or None,
                    output={"_error": "monthly LLM token budget exceeded", "_mode": "budget_blocked"},
                    confidence=None,
                    status=EXTRACTION_SKIPPED_BUDGET,
                ))
                return

            file_bytes = object_storage.download_file(doc.storage_key)
            outcome = run_ai_extraction(
                file_bytes, doc.mime_type, doc.extracted_text, bool(doc.has_text_layer)
            )
            if outcome.total_tokens:
                ai_budget.record_ai_usage(
                    db,
                    tenant_id=doc.tenant_id,
                    document_id=doc_uuid,
                    model_name=settings.vlm_model or None,
                    prompt_tokens=outcome.prompt_tokens,
                    completion_tokens=outcome.completion_tokens,
                    total_tokens=outcome.total_tokens,
                )
            if outcome.extraction is not None:
                ai = outcome.extraction
                doc.extracted_data = ai.fields
                doc.confidence = ai.confidence
                doc.document_type = ai.document_type
                ext_status = (
                    EXTRACTION_ACCEPTED
                    if ai.confidence >= settings.confidence_threshold
                    else EXTRACTION_LOW_CONFIDENCE
                )
                # A manual re-extraction that succeeds resolves a needs_review flag.
                if ext_status == EXTRACTION_ACCEPTED and doc.status == STATUS_NEEDS_REVIEW:
                    doc.status = STATUS_COMPLETED
                db.add(Extraction(
                    tenant_id=doc.tenant_id,
                    document_id=doc_uuid,
                    method=METHOD_VLM,
                    model_name=ai.model_name,
                    output=ai.fields,
                    confidence=ai.confidence,
                    status=ext_status,
                ))
                logger.info(
                    "AI re-extract complete: doc=%s mode=%s type=%s confidence=%.2f duration=%dms",
                    doc_id,
                    outcome.mode,
                    ai.document_type,
                    ai.confidence,
                    int((time.perf_counter() - t_start) * 1000),
                )
            elif outcome.error:
                logger.warning("AI re-extract no data: doc=%s mode=%s error=%s", doc_id, outcome.mode, outcome.error)
                db.add(Extraction(
                    tenant_id=doc.tenant_id,
                    document_id=doc_uuid,
                    method=METHOD_VLM,
                    model_name=settings.vlm_model or None,
                    output={"_error": outcome.error, "_mode": outcome.mode},
                    confidence=None,
                    status=EXTRACTION_LOW_CONFIDENCE,
                ))
            else:
                logger.info("AI re-extract skipped (no endpoint): doc=%s", doc_id)
        except Exception as exc:
            logger.warning("AI re-extract crashed: doc=%s error=%s", doc_id, exc)
            db.add(Extraction(
                tenant_id=doc.tenant_id,
                document_id=doc_uuid,
                method=METHOD_VLM,
                model_name=settings.vlm_model or None,
                output={"_error": f"{type(exc).__name__}: {exc}"[:500], "_mode": "crash"},
                confidence=None,
                status=EXTRACTION_LOW_CONFIDENCE,
            ))
