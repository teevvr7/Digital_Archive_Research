"""Tests for Phase 6: bulk operations (trash, tag assign/remove, set-type)."""

import uuid
from unittest.mock import MagicMock, call, patch

import pytest
from fastapi import HTTPException

from app.modules.files.service import (
    bulk_set_type,
    bulk_tag_assign,
    bulk_tag_remove,
    bulk_trash,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_TENANT_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
_TAG_ID = uuid.UUID("00000000-0000-0000-0000-000000000003")

_DOC_IDS = [
    uuid.UUID("00000000-0000-0000-0000-000000000010"),
    uuid.UUID("00000000-0000-0000-0000-000000000011"),
]


def _make_doc(doc_id: uuid.UUID) -> MagicMock:
    doc = MagicMock()
    doc.id = doc_id
    doc.tenant_id = _TENANT_ID
    doc.original_filename = f"doc_{doc_id}.pdf"
    doc.deleted_at = None
    return doc


def _make_user() -> MagicMock:
    user = MagicMock()
    user.user_id = str(uuid.uuid4())
    user.tenant_id = str(_TENANT_ID)
    return user


# ---------------------------------------------------------------------------
# bulk_trash
# ---------------------------------------------------------------------------


class TestBulkTrash:
    def test_trashes_multiple_docs(self):
        docs = [_make_doc(did) for did in _DOC_IDS]
        db = MagicMock()
        db.scalars.return_value.all.return_value = docs

        with patch("app.modules.files.service._user_name", return_value="Admin"):
            count = bulk_trash(db, _make_user(), _DOC_IDS)

        assert count == 2
        for doc in docs:
            assert doc.deleted_at is not None

    def test_returns_zero_for_empty_list(self):
        db = MagicMock()
        count = bulk_trash(db, _make_user(), [])
        assert count == 0
        db.scalars.assert_not_called()

    def test_skips_already_trashed_docs(self):
        trashed_doc = _make_doc(_DOC_IDS[0])
        trashed_doc.deleted_at = MagicMock()  # already trashed
        # Only returns live docs (WHERE deleted_at IS NULL)
        db = MagicMock()
        db.scalars.return_value.all.return_value = []  # none match the filter

        with patch("app.modules.files.service._user_name", return_value="Admin"):
            count = bulk_trash(db, _make_user(), [_DOC_IDS[0]])

        assert count == 0

    def test_adds_activity_events(self):
        docs = [_make_doc(_DOC_IDS[0])]
        db = MagicMock()
        db.scalars.return_value.all.return_value = docs

        with patch("app.modules.files.service._user_name", return_value="Admin"):
            bulk_trash(db, _make_user(), [_DOC_IDS[0]])

        db.add.assert_called_once()  # one ActivityEvent


# ---------------------------------------------------------------------------
# bulk_tag_assign
# ---------------------------------------------------------------------------


class TestBulkTagAssign:
    def test_assigns_tag_to_all_docs(self):
        db = MagicMock()
        db.get.return_value = MagicMock()  # tag exists
        count = bulk_tag_assign(db, _TENANT_ID, _DOC_IDS, _TAG_ID)
        assert count == 2
        assert db.execute.call_count == 2

    def test_returns_zero_for_empty_list(self):
        db = MagicMock()
        count = bulk_tag_assign(db, _TENANT_ID, [], _TAG_ID)
        assert count == 0
        db.get.assert_not_called()

    def test_404_if_tag_not_found(self):
        db = MagicMock()
        db.get.return_value = None
        with pytest.raises(HTTPException) as exc:
            bulk_tag_assign(db, _TENANT_ID, _DOC_IDS, _TAG_ID)
        assert exc.value.status_code == 404

    def test_uses_on_conflict_do_nothing(self):
        db = MagicMock()
        db.get.return_value = MagicMock()
        bulk_tag_assign(db, _TENANT_ID, [_DOC_IDS[0]], _TAG_ID)
        # Verify execute was called (upsert via pg_insert)
        db.execute.assert_called_once()


# ---------------------------------------------------------------------------
# bulk_tag_remove
# ---------------------------------------------------------------------------


class TestBulkTagRemove:
    def test_removes_tag_from_all_docs(self):
        db = MagicMock()
        count = bulk_tag_remove(db, _DOC_IDS, _TAG_ID)
        assert count == 2
        db.execute.assert_called_once()

    def test_returns_zero_for_empty_list(self):
        db = MagicMock()
        count = bulk_tag_remove(db, [], _TAG_ID)
        assert count == 0
        db.execute.assert_not_called()


# ---------------------------------------------------------------------------
# bulk_set_type
# ---------------------------------------------------------------------------


class TestBulkSetType:
    def test_updates_type_on_all_docs(self):
        db = MagicMock()
        db.execute.return_value.rowcount = 2
        count = bulk_set_type(db, _DOC_IDS, "invoice")
        assert count == 2
        db.execute.assert_called_once()

    def test_returns_zero_for_empty_list(self):
        db = MagicMock()
        count = bulk_set_type(db, [], "invoice")
        assert count == 0
        db.execute.assert_not_called()

    def test_updates_to_any_valid_type(self):
        for doc_type in ("invoice", "receipt", "contract", "report", "other"):
            db = MagicMock()
            db.execute.return_value.rowcount = 1
            count = bulk_set_type(db, [_DOC_IDS[0]], doc_type)
            assert count == 1
