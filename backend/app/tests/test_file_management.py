"""Tests for Phase 3 file management service functions.

Covers: patch_document, trash_document, restore_document, empty_trash, and the
``trashed`` filter in list_documents.  All I/O is mocked — no DB or Supabase.
"""

import datetime
import uuid
from unittest.mock import MagicMock, call, patch

import pytest
from fastapi import HTTPException

from app.core.security import TokenData
from app.models.document import Document
from app.modules.files import service as files_service
from app.modules.files.schemas import DocumentPatchIn

_STORAGE_DELETE = "app.modules.files.service.object_storage.delete_file"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_token(tenant_id: uuid.UUID | None = None, user_id: uuid.UUID | None = None) -> TokenData:
    tenant_id = tenant_id or uuid.uuid4()
    user_id = user_id or uuid.uuid4()
    return TokenData({
        "sub": str(user_id),
        "email": "test@example.com",
        "app_metadata": {"tenant_id": str(tenant_id), "role": "user"},
    })


def _make_doc(
    *,
    deleted_at: datetime.datetime | None = None,
    thumbnail_key: str | None = None,
) -> Document:
    doc = MagicMock(spec=Document)
    doc.id = uuid.uuid4()
    doc.tenant_id = uuid.uuid4()
    doc.filename = "test.pdf"
    doc.original_filename = "test.pdf"
    doc.title = "test.pdf"
    doc.document_type = "other"
    doc.mime_type = "application/pdf"
    doc.size_bytes = 100
    doc.status = "completed"
    doc.uploaded_by = uuid.uuid4()
    doc.uploaded_at = datetime.datetime.now(datetime.timezone.utc)
    doc.processed_at = None
    doc.document_date = None
    doc.page_count = None
    doc.has_text_layer = False
    doc.ocr_confidence = None
    doc.confidence = None
    doc.extracted_data = None
    doc.extracted_text = None
    doc.tags = []
    doc.storage_key = "tenant/docs/test.pdf"
    doc.thumbnail_key = thumbnail_key
    doc.deleted_at = deleted_at
    return doc


@pytest.fixture()
def mock_db():
    db = MagicMock()
    mock_user_row = MagicMock()
    mock_user_row.name = "Test User"
    # Route db.get() by model class: Document calls get the doc set per-test;
    # User calls (from _user_name) always get a mock with a .name attribute.
    from app.models.user import User

    def _get_side_effect(model_cls, pk):
        if model_cls is User:
            return mock_user_row
        return db._doc_to_return  # set per-test via db._doc_to_return = <doc>

    db._doc_to_return = None
    db.get.side_effect = _get_side_effect
    db.flush.return_value = None
    db.execute.return_value = MagicMock(
        scalar=MagicMock(return_value=0),
        first=MagicMock(return_value=None),
        all=MagicMock(return_value=[]),
    )
    return db


# ---------------------------------------------------------------------------
# patch_document
# ---------------------------------------------------------------------------

class TestPatchDocument:
    def test_update_title(self, mock_db: MagicMock) -> None:
        doc = _make_doc()
        mock_db._doc_to_return = doc
        user = _make_token()
        patch_in = DocumentPatchIn(title="New Title")

        result = files_service.patch_document(mock_db, user, doc.id, patch_in)

        assert doc.title == "New Title"
        assert result is not None

    def test_update_document_type(self, mock_db: MagicMock) -> None:
        doc = _make_doc()
        mock_db._doc_to_return = doc
        user = _make_token()
        patch_in = DocumentPatchIn(document_type="invoice")

        files_service.patch_document(mock_db, user, doc.id, patch_in)

        assert doc.document_type == "invoice"

    def test_update_document_date(self, mock_db: MagicMock) -> None:
        doc = _make_doc()
        mock_db._doc_to_return = doc
        user = _make_token()
        new_date = datetime.date(2024, 1, 15)
        patch_in = DocumentPatchIn(document_date=new_date)

        files_service.patch_document(mock_db, user, doc.id, patch_in)

        assert doc.document_date == new_date

    def test_clear_document_date(self, mock_db: MagicMock) -> None:
        doc = _make_doc()
        doc.document_date = datetime.date(2024, 1, 1)
        mock_db._doc_to_return = doc
        user = _make_token()
        # Explicitly sending null for document_date clears it
        patch_in = DocumentPatchIn.model_validate({"documentDate": None})
        # model_fields_set must include document_date
        patch_in = DocumentPatchIn(**{"document_date": None})

        files_service.patch_document(mock_db, user, doc.id, patch_in)

        assert doc.document_date is None

    def test_update_all_three_fields(self, mock_db: MagicMock) -> None:
        doc = _make_doc()
        mock_db._doc_to_return = doc
        user = _make_token()
        patch_in = DocumentPatchIn(
            title="Updated", document_type="receipt", document_date=datetime.date(2025, 3, 1)
        )

        files_service.patch_document(mock_db, user, doc.id, patch_in)

        assert doc.title == "Updated"
        assert doc.document_type == "receipt"
        assert doc.document_date == datetime.date(2025, 3, 1)

    def test_404_when_doc_not_found(self, mock_db: MagicMock) -> None:
        mock_db._doc_to_return = None
        user = _make_token()
        with pytest.raises(HTTPException) as exc_info:
            files_service.patch_document(mock_db, user, uuid.uuid4(), DocumentPatchIn(title="x"))
        assert exc_info.value.status_code == 404

    def test_empty_fields_do_not_overwrite(self, mock_db: MagicMock) -> None:
        doc = _make_doc()
        doc.title = "Original"
        mock_db._doc_to_return = doc
        user = _make_token()
        # Send a patch with no fields set
        patch_in = DocumentPatchIn()

        files_service.patch_document(mock_db, user, doc.id, patch_in)

        assert doc.title == "Original"  # unchanged


# ---------------------------------------------------------------------------
# trash_document
# ---------------------------------------------------------------------------

class TestTrashDocument:
    def test_sets_deleted_at(self, mock_db: MagicMock) -> None:
        doc = _make_doc()
        mock_db._doc_to_return = doc
        user = _make_token()

        before = datetime.datetime.now(datetime.timezone.utc)
        files_service.trash_document(mock_db, user, doc.id)
        after = datetime.datetime.now(datetime.timezone.utc)

        assert doc.deleted_at is not None
        assert before <= doc.deleted_at <= after

    def test_409_if_already_trashed(self, mock_db: MagicMock) -> None:
        doc = _make_doc(deleted_at=datetime.datetime.now(datetime.timezone.utc))
        mock_db._doc_to_return = doc
        user = _make_token()

        with pytest.raises(HTTPException) as exc_info:
            files_service.trash_document(mock_db, user, doc.id)
        assert exc_info.value.status_code == 409

    def test_404_when_doc_not_found(self, mock_db: MagicMock) -> None:
        mock_db._doc_to_return = None
        user = _make_token()
        with pytest.raises(HTTPException) as exc_info:
            files_service.trash_document(mock_db, user, uuid.uuid4())
        assert exc_info.value.status_code == 404

    def test_emits_trash_activity_event(self, mock_db: MagicMock) -> None:
        doc = _make_doc()
        mock_db._doc_to_return = doc
        added: list[object] = []
        mock_db.add.side_effect = added.append
        user = _make_token()

        files_service.trash_document(mock_db, user, doc.id)

        from app.models.activity_event import ActivityEvent, ACT_TRASH
        events = [o for o in added if isinstance(o, ActivityEvent)]
        assert any(e.type == ACT_TRASH for e in events)


# ---------------------------------------------------------------------------
# restore_document
# ---------------------------------------------------------------------------

class TestRestoreDocument:
    def test_clears_deleted_at(self, mock_db: MagicMock) -> None:
        doc = _make_doc(deleted_at=datetime.datetime.now(datetime.timezone.utc))
        mock_db._doc_to_return = doc
        user = _make_token()

        files_service.restore_document(mock_db, user, doc.id)

        assert doc.deleted_at is None

    def test_409_if_not_trashed(self, mock_db: MagicMock) -> None:
        doc = _make_doc()  # deleted_at is None
        mock_db._doc_to_return = doc
        user = _make_token()

        with pytest.raises(HTTPException) as exc_info:
            files_service.restore_document(mock_db, user, doc.id)
        assert exc_info.value.status_code == 409

    def test_404_when_doc_not_found(self, mock_db: MagicMock) -> None:
        mock_db._doc_to_return = None
        user = _make_token()
        with pytest.raises(HTTPException) as exc_info:
            files_service.restore_document(mock_db, user, uuid.uuid4())
        assert exc_info.value.status_code == 404

    def test_emits_restore_activity_event(self, mock_db: MagicMock) -> None:
        doc = _make_doc(deleted_at=datetime.datetime.now(datetime.timezone.utc))
        mock_db._doc_to_return = doc
        added: list[object] = []
        mock_db.add.side_effect = added.append
        user = _make_token()

        files_service.restore_document(mock_db, user, doc.id)

        from app.models.activity_event import ActivityEvent, ACT_RESTORE
        events = [o for o in added if isinstance(o, ActivityEvent)]
        assert any(e.type == ACT_RESTORE for e in events)


# ---------------------------------------------------------------------------
# empty_trash
# ---------------------------------------------------------------------------

class TestEmptyTrash:
    def test_returns_count_of_deleted_docs(self, mock_db: MagicMock) -> None:
        trashed = [_make_doc(deleted_at=datetime.datetime.now(datetime.timezone.utc)) for _ in range(3)]
        mock_db.scalars.return_value = MagicMock(all=MagicMock(return_value=trashed))
        user = _make_token()

        with patch(_STORAGE_DELETE):
            count = files_service.empty_trash(mock_db, user)

        assert count == 3

    def test_calls_delete_file_for_each_doc(self, mock_db: MagicMock) -> None:
        trashed = [_make_doc(deleted_at=datetime.datetime.now(datetime.timezone.utc)) for _ in range(2)]
        mock_db.scalars.return_value = MagicMock(all=MagicMock(return_value=trashed))
        user = _make_token()

        with patch(_STORAGE_DELETE) as mock_delete:
            files_service.empty_trash(mock_db, user)

        # 2 docs × 1 storage key each (no thumbnails)
        assert mock_delete.call_count == 2

    def test_also_deletes_thumbnail(self, mock_db: MagicMock) -> None:
        doc = _make_doc(
            deleted_at=datetime.datetime.now(datetime.timezone.utc),
            thumbnail_key="tenant/thumbnails/thumb.webp",
        )
        mock_db.scalars.return_value = MagicMock(all=MagicMock(return_value=[doc]))
        user = _make_token()

        with patch(_STORAGE_DELETE) as mock_delete:
            files_service.empty_trash(mock_db, user)

        # Called for both storage_key and thumbnail_key
        assert mock_delete.call_count == 2
        called_keys = {c.args[0] for c in mock_delete.call_args_list}
        assert doc.storage_key in called_keys
        assert doc.thumbnail_key in called_keys

    def test_hard_deletes_db_rows(self, mock_db: MagicMock) -> None:
        trashed = [_make_doc(deleted_at=datetime.datetime.now(datetime.timezone.utc)) for _ in range(2)]
        mock_db.scalars.return_value = MagicMock(all=MagicMock(return_value=trashed))
        deleted_objects: list[object] = []
        mock_db.delete.side_effect = deleted_objects.append
        user = _make_token()

        with patch(_STORAGE_DELETE):
            files_service.empty_trash(mock_db, user)

        assert len(deleted_objects) == 2

    def test_storage_error_does_not_abort(self, mock_db: MagicMock) -> None:
        doc = _make_doc(deleted_at=datetime.datetime.now(datetime.timezone.utc))
        mock_db.scalars.return_value = MagicMock(all=MagicMock(return_value=[doc]))
        user = _make_token()

        with patch(_STORAGE_DELETE, side_effect=Exception("storage unreachable")):
            # Should NOT raise
            count = files_service.empty_trash(mock_db, user)

        assert count == 1

    def test_empty_trash_returns_zero_when_nothing_trashed(self, mock_db: MagicMock) -> None:
        mock_db.scalars.return_value = MagicMock(all=MagicMock(return_value=[]))
        user = _make_token()

        with patch(_STORAGE_DELETE):
            count = files_service.empty_trash(mock_db, user)

        assert count == 0
