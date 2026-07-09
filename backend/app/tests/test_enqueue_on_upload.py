"""Enqueue-on-upload test.

Verifies that ``create_documents`` calls ``enqueue_document`` once per uploaded
file, and that ``retry_document`` calls it once on retry.

No DB, no Supabase, no Redis required — all I/O is mocked.

Patch target: ``app.modules.files.service.enqueue_document`` — service binds the
name at import time so that's where the patch must live.
"""

import io
import uuid
from unittest.mock import MagicMock, patch

import pytest

from app.core.security import TokenData
from app.modules.files import service as files_service

# Correct patch target — where the name is bound in the caller's module.
_ENQUEUE_TARGET = "app.modules.files.service.enqueue_document"


def _make_upload(filename: str = "test.pdf", content: bytes = b"%PDF-1.4 test") -> MagicMock:
    upload = MagicMock()
    upload.filename = filename
    upload.content_type = "application/pdf"
    upload.file = MagicMock()
    upload.file.read = MagicMock(return_value=content)
    return upload


def _make_token(tenant_id: uuid.UUID, user_id: uuid.UUID) -> TokenData:
    """Build a TokenData from a synthesised payload dict (matches real constructor)."""
    return TokenData({
        "sub": str(user_id),
        "email": "test@example.com",
        "app_metadata": {
            "tenant_id": str(tenant_id),
            "role": "user",
        },
    })


def _dummy_doc_out():
    """Minimal DocumentOut for patching _doc_to_out in serialisation-agnostic tests."""
    from app.modules.files.schemas import DocumentOut
    import datetime
    return DocumentOut(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        filename="test.pdf",
        original_filename="test.pdf",
        title="test.pdf",
        document_type="other",
        mime_type="application/pdf",
        size_bytes=100,
        status="queued",
        uploaded_by="Tester",
        uploaded_at=datetime.datetime.now(datetime.timezone.utc),
        processed_at=None,
        document_date=None,
        page_count=None,
        has_text_layer=False,
        ocr_confidence=None,
        confidence=None,
        extracted_data=None,
        extracted_text=None,
        tags=[],
        correspondent=None,
        storage_key="tenant/docs/id.pdf",
        has_thumbnail=False,
        deleted_at=None,
    )


@pytest.fixture()
def mock_db():
    """Minimal SQLAlchemy Session mock."""
    db = MagicMock()
    mock_user = MagicMock()
    mock_user.name = "Test User"
    db.get.return_value = mock_user
    added = []
    db.add.side_effect = lambda obj: added.append(obj)
    db.flush.return_value = None
    # .first() -> None means "no Tenant row found", which is accurate here (these
    # tests never create one) and makes _check_storage_quota's lookup a no-op.
    # .all() -> [] means "no existing checksums for this tenant", so the new
    # dedup query in create_documents never spuriously flags a test file as
    # a duplicate (a bare MagicMock() is not iterable and would crash here).
    db.execute.return_value = MagicMock(
        scalar=MagicMock(return_value=0),
        first=MagicMock(return_value=None),
        all=MagicMock(return_value=[]),
    )
    db._added = added
    return db


def test_enqueue_called_once_per_uploaded_file(mock_db):
    """create_documents must call enqueue_document exactly once per file."""
    tenant_id = uuid.uuid4()
    user_id = uuid.uuid4()
    token = _make_token(tenant_id, user_id)

    # Distinct content: two genuinely different files, not a dedup-candidate pair.
    upload1 = _make_upload("invoice.pdf", content=b"%PDF-1.4 invoice")
    upload2 = _make_upload("receipt.pdf", content=b"%PDF-1.4 receipt")

    dummy = _dummy_doc_out()

    with patch(_ENQUEUE_TARGET) as mock_enqueue, \
         patch("app.core.storage.upload_file"), \
         patch.object(files_service, "_doc_to_out", return_value=dummy):

        files_service.create_documents(mock_db, token, [upload1, upload2], ["invoice", "receipt"])

    assert mock_enqueue.call_count == 2, (
        f"Expected enqueue_document called twice, got {mock_enqueue.call_count}"
    )


def test_enqueue_not_called_when_no_files(mock_db):
    """create_documents with an empty list → no enqueue calls."""
    tenant_id = uuid.uuid4()
    user_id = uuid.uuid4()
    token = _make_token(tenant_id, user_id)

    with patch(_ENQUEUE_TARGET) as mock_enqueue, \
         patch("app.core.storage.upload_file"):
        files_service.create_documents(mock_db, token, [], [])

    mock_enqueue.assert_not_called()


def test_batch_over_limit_rejected_with_413(mock_db):
    """The per-request file-count cap (Level 1 hardening) rejects an oversized
    batch before reading any file bytes — no I/O, no enqueue, no partial writes."""
    from fastapi import HTTPException

    tenant_id = uuid.uuid4()
    user_id = uuid.uuid4()
    token = _make_token(tenant_id, user_id)

    too_many = [_make_upload(f"file{i}.pdf") for i in range(files_service._MAX_FILES_PER_UPLOAD + 1)]

    with patch(_ENQUEUE_TARGET) as mock_enqueue:
        with pytest.raises(HTTPException) as exc_info:
            files_service.create_documents(mock_db, token, too_many, ["other"] * len(too_many))

    assert exc_info.value.status_code == 413
    mock_enqueue.assert_not_called()
    # Rejected before pass 1 even starts reading — no file's .read() was touched.
    for upload in too_many:
        upload.file.read.assert_not_called()


def test_batch_at_exact_limit_is_allowed(mock_db):
    """Exactly the cap (not cap+1) must still succeed — an off-by-one guard."""
    tenant_id = uuid.uuid4()
    user_id = uuid.uuid4()
    token = _make_token(tenant_id, user_id)

    exactly_max = [
        _make_upload(f"file{i}.pdf", content=f"%PDF-1.4 {i}".encode())
        for i in range(files_service._MAX_FILES_PER_UPLOAD)
    ]
    dummy = _dummy_doc_out()

    with patch(_ENQUEUE_TARGET) as mock_enqueue, \
         patch("app.core.storage.upload_file"), \
         patch.object(files_service, "_doc_to_out", return_value=dummy):
        files_service.create_documents(
            mock_db, token, exactly_max, ["other"] * len(exactly_max)
        )

    assert mock_enqueue.call_count == files_service._MAX_FILES_PER_UPLOAD


def test_retry_calls_enqueue_once(mock_db):
    """retry_document must call enqueue_document exactly once."""
    from app.models.document import STATUS_FAILED, Document

    doc_id = uuid.uuid4()
    tenant_id = uuid.uuid4()

    doc = MagicMock(spec=Document)
    doc.id = doc_id
    doc.tenant_id = tenant_id
    doc.status = STATUS_FAILED
    doc.error_message = "parse error"
    doc.uploaded_by = uuid.uuid4()

    mock_db.get.return_value = doc

    dummy = _dummy_doc_out()

    with patch(_ENQUEUE_TARGET) as mock_enqueue, \
         patch.object(files_service, "_doc_to_out", return_value=dummy), \
         patch.object(files_service, "_user_name", return_value="Test User"):
        files_service.retry_document(mock_db, doc_id)

    mock_enqueue.assert_called_once()


def test_retry_raises_400_when_not_failed(mock_db):
    """retry_document raises 400 (HTTPException) if document is not in 'failed' state."""
    from fastapi import HTTPException
    from app.models.document import STATUS_QUEUED, Document

    doc = MagicMock(spec=Document)
    doc.id = uuid.uuid4()
    doc.status = STATUS_QUEUED
    mock_db.get.return_value = doc

    with patch(_ENQUEUE_TARGET):
        with pytest.raises(HTTPException) as exc_info:
            files_service.retry_document(mock_db, doc.id)

    assert exc_info.value.status_code == 400
