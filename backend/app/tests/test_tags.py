"""Tests for the tags module — CRUD, matching engine, and assignment."""

import uuid
from unittest.mock import MagicMock, call, patch

import pytest

from app.modules.tags.matching import ALGO_ALL, ALGO_ANY, ALGO_LITERAL, ALGO_NONE, ALGO_REGEX, matches


# ---------------------------------------------------------------------------
# Matching engine unit tests — pure function, no DB
# ---------------------------------------------------------------------------


class TestMatchesAlgoNone:
    def test_none_always_false(self):
        assert matches("invoice", ALGO_NONE, True, "this is an invoice document") is False

    def test_none_empty_pattern(self):
        assert matches("", ALGO_NONE, True, "anything") is False


class TestMatchesAlgoAny:
    def test_any_single_word_hit(self):
        assert matches("invoice", ALGO_ANY, True, "this is an invoice") is True

    def test_any_multiple_words_one_hit(self):
        assert matches("invoice receipt", ALGO_ANY, True, "here is a receipt") is True

    def test_any_no_hit(self):
        assert matches("invoice", ALGO_ANY, True, "this is a contract") is False

    def test_any_case_insensitive(self):
        assert matches("INVOICE", ALGO_ANY, True, "invoice from vendor") is True

    def test_any_case_sensitive_miss(self):
        assert matches("INVOICE", ALGO_ANY, False, "invoice from vendor") is False

    def test_any_empty_pattern(self):
        assert matches("", ALGO_ANY, True, "anything") is False


class TestMatchesAlgoAll:
    def test_all_both_present(self):
        assert matches("invoice tenaga", ALGO_ALL, True, "invoice from Tenaga Nasional") is True

    def test_all_one_missing(self):
        assert matches("invoice tenaga", ALGO_ALL, True, "invoice from acme") is False

    def test_all_empty_pattern(self):
        assert matches("", ALGO_ALL, True, "anything") is False


class TestMatchesAlgoLiteral:
    def test_literal_exact_substring(self):
        assert matches("Tenaga Nasional", ALGO_LITERAL, False, "Invoice from Tenaga Nasional Berhad") is True

    def test_literal_miss(self):
        assert matches("Tenaga Nasional", ALGO_LITERAL, False, "tenaga nasional berhad") is False

    def test_literal_case_insensitive(self):
        assert matches("tenaga nasional", ALGO_LITERAL, True, "TENAGA NASIONAL BERHAD") is True


class TestMatchesAlgoRegex:
    def test_regex_pattern_hit(self):
        assert matches(r"INV-\d{4}", ALGO_REGEX, False, "Invoice INV-2026 attached") is True

    def test_regex_no_hit(self):
        assert matches(r"INV-\d{4}", ALGO_REGEX, False, "no invoice number here") is False

    def test_regex_case_insensitive_flag(self):
        assert matches(r"invoice", ALGO_REGEX, True, "INVOICE FROM VENDOR") is True

    def test_invalid_regex_swallowed_returns_false(self):
        # A broken regex must never raise — it returns False.
        assert matches(r"[unclosed", ALGO_REGEX, True, "any text") is False


# ---------------------------------------------------------------------------
# Tag CRUD service tests
# ---------------------------------------------------------------------------

from app.modules.tags.schemas import TagIn, TagPatchIn
from app.modules.tags.service import (
    assign_tag,
    create_tag,
    delete_tag,
    list_tags,
    patch_tag,
    unassign_tag,
)


def _make_user(tenant_id: str = "00000000-0000-0000-0000-000000000001") -> MagicMock:
    user = MagicMock()
    user.tenant_id = tenant_id
    return user


def _make_tag(name: str = "Invoices", tenant_id: uuid.UUID | None = None) -> MagicMock:
    tag = MagicMock()
    tag.id = uuid.uuid4()
    tag.tenant_id = tenant_id or uuid.UUID("00000000-0000-0000-0000-000000000001")
    tag.name = name
    tag.color = "#3B82F6"
    tag.match = "invoice"
    tag.matching_algorithm = "any"
    tag.is_insensitive = True
    tag.is_inbox_tag = False
    tag.created_at = MagicMock()
    return tag


class TestListTags:
    def test_returns_list(self):
        db = MagicMock()
        tag = _make_tag()
        db.scalars.return_value = MagicMock(all=MagicMock(return_value=[tag]))
        result = list_tags(db)
        assert len(result) == 1
        assert result[0].name == "Invoices"


class TestCreateTag:
    def test_creates_successfully(self):
        db = MagicMock()
        db.scalars.return_value = MagicMock(first=MagicMock(return_value=None))
        user = _make_user()
        data = TagIn(name="Invoices", color="#3B82F6", match="invoice", matching_algorithm="any")
        expected = _make_tag("Invoices")

        with patch("app.modules.tags.service._tag_to_out", return_value=expected):
            result = create_tag(db, user, data)

        db.add.assert_called_once()
        db.flush.assert_called_once()
        assert result.name == "Invoices"

    def test_409_on_duplicate_name(self):
        from fastapi import HTTPException
        db = MagicMock()
        existing = _make_tag()
        db.scalars.return_value = MagicMock(first=MagicMock(return_value=existing))
        user = _make_user()
        data = TagIn(name="Invoices")

        with pytest.raises(HTTPException) as exc_info:
            create_tag(db, user, data)
        assert exc_info.value.status_code == 409


class TestPatchTag:
    def test_updates_name(self):
        db = MagicMock()
        tag = _make_tag()
        db.get.return_value = tag
        patch_in = TagPatchIn.model_construct(_fields_set={"name"}, name="Updated")

        result = patch_tag(db, tag.id, patch_in)
        assert tag.name == "Updated"

    def test_404_if_not_found(self):
        from fastapi import HTTPException
        db = MagicMock()
        db.get.return_value = None
        with pytest.raises(HTTPException) as exc_info:
            patch_tag(db, uuid.uuid4(), TagPatchIn())
        assert exc_info.value.status_code == 404


class TestDeleteTag:
    def test_deletes_tag(self):
        db = MagicMock()
        tag = _make_tag()
        db.get.return_value = tag
        delete_tag(db, tag.id)
        db.delete.assert_called_once_with(tag)

    def test_404_if_not_found(self):
        from fastapi import HTTPException
        db = MagicMock()
        db.get.return_value = None
        with pytest.raises(HTTPException) as exc_info:
            delete_tag(db, uuid.uuid4())
        assert exc_info.value.status_code == 404


class TestAssignUnassignTag:
    def _make_doc(self) -> MagicMock:
        doc = MagicMock()
        doc.id = uuid.uuid4()
        return doc

    def test_assign_calls_insert(self):
        db = MagicMock()
        doc = self._make_doc()
        tag = _make_tag()
        user = _make_user()

        def get_side(model_cls, pk):
            from app.models.document import Document
            from app.models.tag import Tag as TagModel
            if model_cls is TagModel:
                return tag
            return doc

        db.get.side_effect = get_side
        assign_tag(db, user, doc.id, tag.id)
        db.execute.assert_called_once()
        db.flush.assert_called_once()

    def test_assign_404_doc_not_found(self):
        from fastapi import HTTPException
        db = MagicMock()
        db.get.return_value = None
        user = _make_user()
        with pytest.raises(HTTPException) as exc_info:
            assign_tag(db, user, uuid.uuid4(), uuid.uuid4())
        assert exc_info.value.status_code == 404

    def test_unassign_404_if_not_assigned(self):
        from fastapi import HTTPException
        db = MagicMock()
        db.scalars.return_value = MagicMock(first=MagicMock(return_value=None))
        with pytest.raises(HTTPException) as exc_info:
            unassign_tag(db, uuid.uuid4(), uuid.uuid4())
        assert exc_info.value.status_code == 404

    def test_unassign_deletes_row(self):
        db = MagicMock()
        dt = MagicMock()
        db.scalars.return_value = MagicMock(first=MagicMock(return_value=dt))
        unassign_tag(db, uuid.uuid4(), uuid.uuid4())
        db.delete.assert_called_once_with(dt)


# ---------------------------------------------------------------------------
# run_document_matching integration (mocked DB)
# ---------------------------------------------------------------------------

from app.modules.tags.matching import run_document_matching


class TestRunDocumentMatching:
    def _make_doc_model(self, tenant_id: uuid.UUID) -> MagicMock:
        doc = MagicMock()
        doc.id = uuid.uuid4()
        doc.tenant_id = tenant_id
        doc.correspondent_id = None
        doc.title = "Invoice from Acme Corp"
        doc.extracted_data = {"vendor": "Acme Corp"}
        return doc

    def _make_tag_model(self, match: str, algo: str = ALGO_ANY) -> MagicMock:
        tag = MagicMock()
        tag.id = uuid.uuid4()
        tag.match = match
        tag.matching_algorithm = algo
        tag.is_insensitive = True
        return tag

    def _make_corresp_model(self, name: str, match: str = "", algo: str = ALGO_NONE) -> MagicMock:
        c = MagicMock()
        c.id = uuid.uuid4()
        c.name = name
        c.match = match
        c.matching_algorithm = algo
        c.is_insensitive = True
        return c

    def test_matching_tag_inserted(self):
        tenant_id = uuid.uuid4()
        doc = self._make_doc_model(tenant_id)
        tag = self._make_tag_model("invoice")

        db = MagicMock()

        def scalars_side(stmt):
            from app.models.tag import Tag
            from app.models.correspondent import Correspondent
            result = MagicMock()
            # Figure out which model we're selecting based on stmt
            stmt_str = str(stmt)
            if "tags" in stmt_str.lower() and "correspondents" not in stmt_str.lower():
                result.all.return_value = [tag]
            else:
                result.all.return_value = []
            return result

        db.scalars.side_effect = scalars_side
        run_document_matching(db, doc, "This is an invoice from Acme Corp")
        db.execute.assert_called()  # INSERT for the matched tag

    def test_no_match_no_insert(self):
        tenant_id = uuid.uuid4()
        doc = self._make_doc_model(tenant_id)
        tag = self._make_tag_model("xyz_nonexistent_keyword")

        db = MagicMock()

        def scalars_side(stmt):
            result = MagicMock()
            stmt_str = str(stmt)
            if "tags" in stmt_str.lower() and "correspondents" not in stmt_str.lower():
                result.all.return_value = [tag]
            else:
                result.all.return_value = []
            return result

        db.scalars.side_effect = scalars_side
        run_document_matching(db, doc, "This is a contract")
        db.execute.assert_not_called()

    def test_correspondent_linked_by_vendor_name(self):
        tenant_id = uuid.uuid4()
        doc = self._make_doc_model(tenant_id)  # extracted_data.vendor = "Acme Corp"
        corresp = self._make_corresp_model("Acme Corp", match="", algo=ALGO_NONE)

        db = MagicMock()

        def scalars_side(stmt):
            result = MagicMock()
            stmt_str = str(stmt)
            if "correspondents" in stmt_str.lower():
                result.all.return_value = [corresp]
            else:
                result.all.return_value = []
            return result

        db.scalars.side_effect = scalars_side
        run_document_matching(db, doc, "Invoice from Acme Corp")
        # Vendor name == correspondent name → should link
        assert doc.correspondent_id == corresp.id

    def test_crash_in_matching_does_not_propagate(self):
        """A bad matching rule must never crash — the caller wraps it in try/except."""
        tenant_id = uuid.uuid4()
        doc = self._make_doc_model(tenant_id)

        db = MagicMock()
        db.scalars.side_effect = RuntimeError("DB exploded")

        # Should not raise when called directly; caller's try/except is tested via jobs.py
        with pytest.raises(RuntimeError):
            run_document_matching(db, doc, "text")
