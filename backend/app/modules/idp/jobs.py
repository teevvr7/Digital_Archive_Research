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

from app.core import storage as object_storage
from app.core.tenant_context import tenant_session
from app.models.activity_event import (
    ACT_PROCESSING_COMPLETE,
    ACT_PROCESSING_FAILED,
    ActivityEvent,
)
from app.models.document import (
    STATUS_COMPLETED,
    STATUS_EXTRACTING_TEXT,
    STATUS_FAILED,
    STATUS_OCR,
    Document,
)
from app.models.processing_job import (
    JOB_COMPLETED,
    JOB_FAILED,
    JOB_RUNNING,
    ProcessingJob,
)
from app.modules.idp.pipeline import run_extraction

logger = logging.getLogger(__name__)


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

            # Persist extraction results.
            doc.extracted_text = result.text or None
            doc.page_count = result.page_count
            doc.has_text_layer = result.has_text_layer
            doc.ocr_used = result.ocr_used
            doc.ocr_confidence = result.ocr_confidence

            # Populate full-text search index: filename + extracted text.
            combined = " ".join(filter(None, [doc.original_filename, result.text]))
            db.execute(
                update(Document)
                .where(Document.id == doc_uuid)
                .values(search_tsv=func.to_tsvector("english", combined))
            )

            now = datetime.datetime.now(datetime.timezone.utc)
            doc.status = STATUS_COMPLETED
            doc.processed_at = now

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
