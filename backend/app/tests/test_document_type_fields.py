"""Tests for predefined custom fields per document type (Level 6 — Metadata)."""

import json
import uuid
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from app.modules.metadata.schemas import (
    PredefinedFieldIn,
    PredefinedFieldPatchIn,
)
from app.modules.metadata.service import (
    add_predefined_field,
    list_predefined_fields,
    patch_predefined_field,
    remove_predefined_field,
)

_TENANT_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
_FIELD_ID = uuid.UUID("00000000-0000-0000-0000-000000000003")
_LINK_ID = uuid.UUID("00000000-0000-0000-0000-000000000004")


def _make_field(name: str = "PO Number", field_type: str = "text", options=None) -> MagicMock:
    f = MagicMock()
    f.id = _FIELD_ID
    f.name = name
    f.field_type = field_type
    f.options = options or []
    return f


def _make_link(document_type: str = "invoice", required: bool = False, position: int = 0) -> MagicMock:
    link = MagicMock()
    link.id = _LINK_ID
    link.document_type = document_type
    link.field_id = _FIELD_ID
    link.required = required
    link.position = position
    return link


def _scalar_first(return_value: Any) -> MagicMock:
    return MagicMock(first=MagicMock(return_value=return_value))


# ---------------------------------------------------------------------------
# list_predefined_fields
# ---------------------------------------------------------------------------


class TestListPredefinedFields:
    def test_returns_all_types_even_when_empty(self):
        db = MagicMock()
        db.execute.return_value.all.return_value = []
        result = list_predefined_fields(db)
        assert set(result.keys()) == {
            "invoice", "receipt", "contract", "report", "letter", "form", "other",
        }
        assert all(v == [] for v in result.values())

    def test_groups_by_document_type(self):
        db = MagicMock()
        link = _make_link(document_type="invoice")
        field = _make_field()
        db.execute.return_value.all.return_value = [(link, field)]
        result = list_predefined_fields(db)
        assert len(result["invoice"]) == 1
        assert result["invoice"][0].field_name == "PO Number"
        assert result["receipt"] == []


# ---------------------------------------------------------------------------
# add_predefined_field
# ---------------------------------------------------------------------------


class TestAddPredefinedField:
    def test_attaches_field(self):
        db = MagicMock()
        db.get.return_value = _make_field()
        db.scalars.return_value = _scalar_first(None)
        # link.id is a Python-side ORM default only applied on a real flush —
        # mocked out here exactly like test_custom_fields.py does for
        # create_custom_field, since db.flush() is a no-op MagicMock.
        with patch("app.modules.metadata.service._predefined_to_out") as mock_out:
            mock_out.return_value = MagicMock(document_type="invoice", field_name="PO Number")
            result = add_predefined_field(
                db, _TENANT_ID, "invoice", PredefinedFieldIn(field_id=_FIELD_ID)
            )
        db.add.assert_called_once()
        assert result.document_type == "invoice"
        assert result.field_name == "PO Number"

    def test_422_on_invalid_document_type(self):
        db = MagicMock()
        with pytest.raises(HTTPException) as exc_info:
            add_predefined_field(
                db, _TENANT_ID, "not-a-type", PredefinedFieldIn(field_id=_FIELD_ID)
            )
        assert exc_info.value.status_code == 422

    def test_404_on_unknown_field(self):
        db = MagicMock()
        db.get.return_value = None
        with pytest.raises(HTTPException) as exc_info:
            add_predefined_field(
                db, _TENANT_ID, "invoice", PredefinedFieldIn(field_id=_FIELD_ID)
            )
        assert exc_info.value.status_code == 404

    def test_409_on_duplicate_attachment(self):
        db = MagicMock()
        db.get.return_value = _make_field()
        db.scalars.return_value = _scalar_first(_make_link())
        with pytest.raises(HTTPException) as exc_info:
            add_predefined_field(
                db, _TENANT_ID, "invoice", PredefinedFieldIn(field_id=_FIELD_ID)
            )
        assert exc_info.value.status_code == 409


# ---------------------------------------------------------------------------
# patch_predefined_field
# ---------------------------------------------------------------------------


class TestPatchPredefinedField:
    def test_updates_required(self):
        db = MagicMock()
        link = _make_link(required=False)
        db.scalars.return_value = _scalar_first(link)
        db.get.return_value = _make_field()
        patch_in = PredefinedFieldPatchIn.model_construct(_fields_set={"required"}, required=True)
        result = patch_predefined_field(db, "invoice", _FIELD_ID, patch_in)
        assert link.required is True
        assert result.field_name == "PO Number"

    def test_updates_position(self):
        db = MagicMock()
        link = _make_link(position=0)
        db.scalars.return_value = _scalar_first(link)
        db.get.return_value = _make_field()
        patch_in = PredefinedFieldPatchIn.model_construct(_fields_set={"position"}, position=3)
        patch_predefined_field(db, "invoice", _FIELD_ID, patch_in)
        assert link.position == 3

    def test_404_if_not_attached(self):
        db = MagicMock()
        db.scalars.return_value = _scalar_first(None)
        with pytest.raises(HTTPException) as exc_info:
            patch_predefined_field(db, "invoice", _FIELD_ID, PredefinedFieldPatchIn())
        assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# remove_predefined_field
# ---------------------------------------------------------------------------


class TestRemovePredefinedField:
    def test_detaches(self):
        db = MagicMock()
        link = _make_link()
        db.scalars.return_value = _scalar_first(link)
        remove_predefined_field(db, "invoice", _FIELD_ID)
        db.delete.assert_called_once_with(link)

    def test_404_if_not_attached(self):
        db = MagicMock()
        db.scalars.return_value = _scalar_first(None)
        with pytest.raises(HTTPException) as exc_info:
            remove_predefined_field(db, "invoice", _FIELD_ID)
        assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# _apply_upload_time_fields (files.service) — never blocks the document
# ---------------------------------------------------------------------------


class TestApplyUploadTimeFields:
    def _make_doc(self):
        doc = MagicMock()
        doc.id = uuid.uuid4()
        doc.document_type = "invoice"
        return doc

    def test_noop_on_empty_strings(self):
        from app.modules.files.service import _apply_upload_time_fields

        db = MagicMock()
        doc = self._make_doc()
        with (
            patch("app.modules.files.service.create_custom_field") as mock_create,
            patch("app.modules.files.service.add_predefined_field") as mock_attach,
            patch("app.modules.files.service.set_field_value") as mock_set,
        ):
            _apply_upload_time_fields(db, _TENANT_ID, doc, "", "")
        mock_create.assert_not_called()
        mock_attach.assert_not_called()
        mock_set.assert_not_called()

    def test_creates_and_attaches_new_field(self):
        from app.modules.files.service import _apply_upload_time_fields

        db = MagicMock()
        doc = self._make_doc()
        new_field_out = MagicMock(id=_FIELD_ID)
        new_fields_json = json.dumps([{"name": "PO Number", "fieldType": "text", "options": []}])
        with (
            patch("app.modules.files.service.create_custom_field", return_value=new_field_out) as mock_create,
            patch("app.modules.files.service.add_predefined_field") as mock_attach,
        ):
            _apply_upload_time_fields(db, _TENANT_ID, doc, "", new_fields_json)
        mock_create.assert_called_once()
        mock_attach.assert_called_once()
        # auto-attached to the document's own type, per the confirmed design decision
        assert mock_attach.call_args.args[2] == "invoice"

    def test_new_field_with_inline_value_is_set(self):
        """A brand-new field's filled-in value rides along on the same spec,
        since the frontend can't know its server-generated id in advance."""
        from app.modules.files.service import _apply_upload_time_fields

        db = MagicMock()
        doc = self._make_doc()
        new_field_out = MagicMock(id=_FIELD_ID)
        new_fields_json = json.dumps(
            [{"name": "PO Number", "fieldType": "text", "options": [], "value": "PO-999"}]
        )
        with (
            patch("app.modules.files.service.create_custom_field", return_value=new_field_out),
            patch("app.modules.files.service.add_predefined_field"),
            patch("app.modules.files.service.set_field_value") as mock_set,
        ):
            _apply_upload_time_fields(db, _TENANT_ID, doc, "", new_fields_json)
        mock_set.assert_called_once()
        assert mock_set.call_args.args[3] == _FIELD_ID
        assert mock_set.call_args.args[4].value == "PO-999"

    def test_sets_field_values(self):
        from app.modules.files.service import _apply_upload_time_fields

        db = MagicMock()
        doc = self._make_doc()
        field_values_json = json.dumps({str(_FIELD_ID): "PO-123"})
        with patch("app.modules.files.service.set_field_value") as mock_set:
            _apply_upload_time_fields(db, _TENANT_ID, doc, field_values_json, "")
        mock_set.assert_called_once()
        # set_field_value(db, tenant_id, doc_id, field_id, data)
        assert mock_set.call_args.args[3] == _FIELD_ID
        assert mock_set.call_args.args[4].value == "PO-123"

    def test_malformed_new_fields_json_does_not_raise(self):
        from app.modules.files.service import _apply_upload_time_fields

        db = MagicMock()
        doc = self._make_doc()
        _apply_upload_time_fields(db, _TENANT_ID, doc, "", "not-json{{{")  # must not raise

    def test_malformed_field_values_json_does_not_raise(self):
        from app.modules.files.service import _apply_upload_time_fields

        db = MagicMock()
        doc = self._make_doc()
        _apply_upload_time_fields(db, _TENANT_ID, doc, "not-json{{{", "")  # must not raise

    def test_bad_field_id_in_values_is_skipped_not_raised(self):
        from app.modules.files.service import _apply_upload_time_fields

        db = MagicMock()
        doc = self._make_doc()
        field_values_json = json.dumps({"not-a-uuid": "value"})
        with patch("app.modules.files.service.set_field_value") as mock_set:
            _apply_upload_time_fields(db, _TENANT_ID, doc, field_values_json, "")  # must not raise
        mock_set.assert_not_called()

    def test_duplicate_field_creation_is_skipped_not_raised(self):
        """create_custom_field raising 409 (name collision) must not block the document."""
        from app.modules.files.service import _apply_upload_time_fields

        db = MagicMock()
        doc = self._make_doc()
        new_fields_json = json.dumps([{"name": "PO Number", "fieldType": "text", "options": []}])
        with (
            patch(
                "app.modules.files.service.create_custom_field",
                side_effect=HTTPException(status_code=409, detail="dup"),
            ),
            patch("app.modules.files.service.add_predefined_field") as mock_attach,
        ):
            _apply_upload_time_fields(db, _TENANT_ID, doc, "", new_fields_json)  # must not raise
        mock_attach.assert_not_called()

    def test_one_bad_value_does_not_block_other_valid_values(self):
        from app.modules.files.service import _apply_upload_time_fields

        db = MagicMock()
        doc = self._make_doc()
        good_id = uuid.uuid4()
        field_values_json = json.dumps({"not-a-uuid": "bad", str(good_id): "good"})
        with patch("app.modules.files.service.set_field_value") as mock_set:
            _apply_upload_time_fields(db, _TENANT_ID, doc, field_values_json, "")
        mock_set.assert_called_once()
        # set_field_value(db, tenant_id, doc_id, field_id, data)
        assert mock_set.call_args.args[3] == good_id


# ---------------------------------------------------------------------------
# _apply_upload_time_fields — attach_fields ("use an existing field")
# ---------------------------------------------------------------------------


class TestApplyUploadTimeFieldsAttachExisting:
    def _make_doc(self):
        doc = MagicMock()
        doc.id = uuid.uuid4()
        doc.document_type = "invoice"
        return doc

    def test_attaches_existing_field_and_sets_value(self):
        from app.modules.files.service import _apply_upload_time_fields

        db = MagicMock()
        doc = self._make_doc()
        attach_json = json.dumps([{"fieldId": str(_FIELD_ID), "value": "Travel"}])
        with (
            patch("app.modules.files.service.add_predefined_field") as mock_attach,
            patch("app.modules.files.service.set_field_value") as mock_set,
        ):
            _apply_upload_time_fields(db, _TENANT_ID, doc, "", "", attach_json)
        mock_attach.assert_called_once()
        assert mock_attach.call_args.args[2] == "invoice"
        assert mock_attach.call_args.args[3].field_id == _FIELD_ID
        mock_set.assert_called_once()
        assert mock_set.call_args.args[3] == _FIELD_ID
        assert mock_set.call_args.args[4].value == "Travel"

    def test_tolerates_409_already_predefined_and_still_sets_value(self):
        """A 409 (already attached) must not block the value from being set."""
        from app.modules.files.service import _apply_upload_time_fields

        db = MagicMock()
        doc = self._make_doc()
        attach_json = json.dumps([{"fieldId": str(_FIELD_ID), "value": "Meals"}])
        with (
            patch(
                "app.modules.files.service.add_predefined_field",
                side_effect=HTTPException(status_code=409, detail="already attached"),
            ),
            patch("app.modules.files.service.set_field_value") as mock_set,
        ):
            _apply_upload_time_fields(db, _TENANT_ID, doc, "", "", attach_json)  # must not raise
        mock_set.assert_called_once()
        assert mock_set.call_args.args[4].value == "Meals"

    def test_non_409_error_skips_without_setting_value(self):
        """A real error (e.g. 404 unknown field) skips the whole entry — no orphaned value."""
        from app.modules.files.service import _apply_upload_time_fields

        db = MagicMock()
        doc = self._make_doc()
        attach_json = json.dumps([{"fieldId": str(_FIELD_ID), "value": "x"}])
        with (
            patch(
                "app.modules.files.service.add_predefined_field",
                side_effect=HTTPException(status_code=404, detail="not found"),
            ),
            patch("app.modules.files.service.set_field_value") as mock_set,
        ):
            _apply_upload_time_fields(db, _TENANT_ID, doc, "", "", attach_json)  # must not raise
        mock_set.assert_not_called()

    def test_malformed_attach_fields_json_does_not_raise(self):
        from app.modules.files.service import _apply_upload_time_fields

        db = MagicMock()
        doc = self._make_doc()
        _apply_upload_time_fields(db, _TENANT_ID, doc, "", "", "not-json{{{")  # must not raise

    def test_bad_field_id_is_skipped_not_raised(self):
        from app.modules.files.service import _apply_upload_time_fields

        db = MagicMock()
        doc = self._make_doc()
        attach_json = json.dumps([{"fieldId": "not-a-uuid", "value": "x"}])
        with (
            patch("app.modules.files.service.add_predefined_field") as mock_attach,
            patch("app.modules.files.service.set_field_value") as mock_set,
        ):
            _apply_upload_time_fields(db, _TENANT_ID, doc, "", "", attach_json)  # must not raise
        mock_attach.assert_not_called()
        mock_set.assert_not_called()

    def test_empty_string_is_noop(self):
        from app.modules.files.service import _apply_upload_time_fields

        db = MagicMock()
        doc = self._make_doc()
        with (
            patch("app.modules.files.service.add_predefined_field") as mock_attach,
            patch("app.modules.files.service.set_field_value") as mock_set,
        ):
            _apply_upload_time_fields(db, _TENANT_ID, doc, "", "", "")
        mock_attach.assert_not_called()
        mock_set.assert_not_called()
