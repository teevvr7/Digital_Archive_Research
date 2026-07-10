"""Tests for Phase 5: custom field CRUD, document field values, and extracted_data correction."""

import uuid
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from app.modules.metadata.schemas import CustomFieldIn, CustomFieldPatchIn, FieldValueIn
from app.modules.metadata.service import (
    create_custom_field,
    delete_custom_field,
    delete_field_value,
    fetch_field_values_for_docs,
    list_custom_fields,
    patch_custom_field,
    set_field_value,
)


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

_TENANT_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
_DOC_ID = uuid.UUID("00000000-0000-0000-0000-000000000002")
_FIELD_ID = uuid.UUID("00000000-0000-0000-0000-000000000003")


def _make_field(
    name: str = "Project Code",
    field_type: str = "text",
    options: list[str] | None = None,
    position: int = 0,
) -> MagicMock:
    f = MagicMock()
    f.id = _FIELD_ID
    f.tenant_id = _TENANT_ID
    f.name = name
    f.field_type = field_type
    f.options = options or []
    f.position = position
    f.created_at = MagicMock()
    return f


def _make_doc() -> MagicMock:
    doc = MagicMock()
    doc.id = _DOC_ID
    doc.tenant_id = _TENANT_ID
    doc.filename = "invoice.pdf"
    doc.original_filename = "invoice.pdf"
    doc.title = "invoice.pdf"
    doc.document_type = "invoice"
    doc.mime_type = "application/pdf"
    doc.size_bytes = 1024
    doc.status = "completed"
    doc.uploaded_at = MagicMock()
    doc.processed_at = None
    doc.document_date = None
    doc.page_count = 1
    doc.has_text_layer = True
    doc.ocr_confidence = None
    doc.confidence = 0.91
    doc.extracted_data = {"vendor": "Acme", "total_amount": 100.0}
    doc.extracted_text = None
    doc.correspondent_id = None
    doc.thumbnail_key = None
    doc.storage_key = "tenant/docs/file.pdf"
    doc.deleted_at = None
    doc.duplicate_of_document_id = None
    return doc


def _make_value_row(value: Any = "PROJ-001") -> MagicMock:
    row = MagicMock()
    row.document_id = _DOC_ID
    row.field_id = _FIELD_ID
    row.value = value
    return row


def _scalar_first(return_value: Any) -> MagicMock:
    return MagicMock(first=MagicMock(return_value=return_value))


def _scalars_all(return_value: list) -> MagicMock:
    return MagicMock(all=MagicMock(return_value=return_value))


# ---------------------------------------------------------------------------
# list_custom_fields
# ---------------------------------------------------------------------------


class TestListCustomFields:
    def test_returns_empty_when_none(self):
        db = MagicMock()
        db.scalars.return_value = _scalars_all([])
        assert list_custom_fields(db) == []

    def test_returns_mapped_fields(self):
        db = MagicMock()
        db.scalars.return_value = _scalars_all([_make_field("Invoice Ref")])
        result = list_custom_fields(db)
        assert len(result) == 1
        assert result[0].name == "Invoice Ref"
        assert result[0].field_type == "text"


# ---------------------------------------------------------------------------
# create_custom_field
# ---------------------------------------------------------------------------


class TestCreateCustomField:
    def test_creates_text_field(self):
        db = MagicMock()
        db.scalars.return_value = _scalar_first(None)
        data = CustomFieldIn(name="Project Code", field_type="text")
        with patch("app.modules.metadata.service._field_to_out") as mock_out:
            mock_out.return_value = MagicMock(name="Project Code", field_type="text")
            create_custom_field(db, _TENANT_ID, data)
        db.add.assert_called_once()
        db.flush.assert_called_once()

    def test_creates_select_field_with_options(self):
        db = MagicMock()
        db.scalars.return_value = _scalar_first(None)
        data = CustomFieldIn(
            name="Department",
            field_type="select",
            options=["Engineering", "Finance", "HR"],
        )
        with patch("app.modules.metadata.service._field_to_out") as mock_out:
            mock_out.return_value = MagicMock()
            create_custom_field(db, _TENANT_ID, data)
        db.add.assert_called_once()

    def test_422_on_invalid_field_type(self):
        db = MagicMock()
        data = CustomFieldIn(name="Bad", field_type="jsonb")
        with pytest.raises(HTTPException) as exc_info:
            create_custom_field(db, _TENANT_ID, data)
        assert exc_info.value.status_code == 422

    def test_409_on_duplicate_name(self):
        db = MagicMock()
        db.scalars.return_value = _scalar_first(_make_field())
        data = CustomFieldIn(name="Project Code", field_type="text")
        with pytest.raises(HTTPException) as exc_info:
            create_custom_field(db, _TENANT_ID, data)
        assert exc_info.value.status_code == 409

    def test_all_valid_field_types_accepted(self):
        for ftype in ("text", "number", "date", "boolean", "select"):
            db = MagicMock()
            db.scalars.return_value = _scalar_first(None)
            data = CustomFieldIn(name=f"Field {ftype}", field_type=ftype)
            with patch("app.modules.metadata.service._field_to_out"):
                create_custom_field(db, _TENANT_ID, data)  # must not raise


# ---------------------------------------------------------------------------
# patch_custom_field
# ---------------------------------------------------------------------------


class TestPatchCustomField:
    def test_updates_name(self):
        db = MagicMock()
        field = _make_field()
        db.get.return_value = field
        patch_in = CustomFieldPatchIn.model_construct(_fields_set={"name"}, name="Renamed")
        patch_custom_field(db, _FIELD_ID, patch_in)
        assert field.name == "Renamed"

    def test_updates_options(self):
        db = MagicMock()
        field = _make_field(field_type="select")
        db.get.return_value = field
        patch_in = CustomFieldPatchIn.model_construct(
            _fields_set={"options"}, options=["A", "B"]
        )
        patch_custom_field(db, _FIELD_ID, patch_in)
        assert field.options == ["A", "B"]

    def test_updates_position(self):
        db = MagicMock()
        field = _make_field()
        db.get.return_value = field
        patch_in = CustomFieldPatchIn.model_construct(_fields_set={"position"}, position=5)
        patch_custom_field(db, _FIELD_ID, patch_in)
        assert field.position == 5

    def test_404_if_not_found(self):
        db = MagicMock()
        db.get.return_value = None
        with pytest.raises(HTTPException) as exc_info:
            patch_custom_field(db, _FIELD_ID, CustomFieldPatchIn())
        assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# delete_custom_field
# ---------------------------------------------------------------------------


class TestDeleteCustomField:
    def test_deletes_field(self):
        db = MagicMock()
        field = _make_field()
        db.get.return_value = field
        delete_custom_field(db, _FIELD_ID)
        db.delete.assert_called_once_with(field)

    def test_404_if_not_found(self):
        db = MagicMock()
        db.get.return_value = None
        with pytest.raises(HTTPException) as exc_info:
            delete_custom_field(db, _FIELD_ID)
        assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# set_field_value
# ---------------------------------------------------------------------------


class TestSetFieldValue:
    def _db_with_doc_and_field(self) -> MagicMock:
        db = MagicMock()
        # db.get called twice: first for Document, then for CustomField
        db.get.side_effect = [_make_doc(), _make_field()]
        # db.execute() for the upsert; db.flush()
        db.scalars.return_value = _scalar_first(_make_value_row("PROJ-001"))
        return db

    def test_upserts_text_value(self):
        db = self._db_with_doc_and_field()
        result = set_field_value(db, _TENANT_ID, _DOC_ID, _FIELD_ID, FieldValueIn(value="PROJ-001"))
        assert result.value == "PROJ-001"
        assert result.field_type == "text"
        db.execute.assert_called_once()

    def test_upserts_number_value(self):
        db = MagicMock()
        db.get.side_effect = [_make_doc(), _make_field(field_type="number")]
        result = set_field_value(db, _TENANT_ID, _DOC_ID, _FIELD_ID, FieldValueIn(value=42.5))
        assert result.value == 42.5

    def test_upserts_boolean_value(self):
        db = MagicMock()
        db.get.side_effect = [_make_doc(), _make_field(field_type="boolean")]
        result = set_field_value(db, _TENANT_ID, _DOC_ID, _FIELD_ID, FieldValueIn(value=True))
        assert result.value is True

    def test_404_unknown_document(self):
        db = MagicMock()
        db.get.return_value = None
        with pytest.raises(HTTPException) as exc_info:
            set_field_value(db, _TENANT_ID, _DOC_ID, _FIELD_ID, FieldValueIn(value="x"))
        assert exc_info.value.status_code == 404

    def test_404_unknown_field(self):
        db = MagicMock()
        db.get.side_effect = [_make_doc(), None]
        with pytest.raises(HTTPException) as exc_info:
            set_field_value(db, _TENANT_ID, _DOC_ID, _FIELD_ID, FieldValueIn(value="x"))
        assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# delete_field_value
# ---------------------------------------------------------------------------


class TestDeleteFieldValue:
    def test_deletes_existing_value(self):
        db = MagicMock()
        row = _make_value_row()
        db.scalars.return_value = _scalar_first(row)
        delete_field_value(db, _DOC_ID, _FIELD_ID)
        db.delete.assert_called_once_with(row)

    def test_404_if_no_value_set(self):
        db = MagicMock()
        db.scalars.return_value = _scalar_first(None)
        with pytest.raises(HTTPException) as exc_info:
            delete_field_value(db, _DOC_ID, _FIELD_ID)
        assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# fetch_field_values_for_docs (batch helper)
# ---------------------------------------------------------------------------


class TestFetchFieldValuesForDocs:
    def test_returns_empty_for_no_doc_ids(self):
        db = MagicMock()
        result = fetch_field_values_for_docs(db, [])
        assert result == {}
        db.execute.assert_not_called()

    def test_groups_values_by_doc_id(self):
        doc_id_a = uuid.uuid4()
        doc_id_b = uuid.uuid4()
        field_id = uuid.uuid4()

        row_a = MagicMock()
        row_a.document_id = doc_id_a
        row_a.field_id = field_id
        row_a.value = "alpha"
        row_a.name = "Code"
        row_a.field_type = "text"

        row_b = MagicMock()
        row_b.document_id = doc_id_b
        row_b.field_id = field_id
        row_b.value = "beta"
        row_b.name = "Code"
        row_b.field_type = "text"

        db = MagicMock()
        db.execute.return_value.all.return_value = [row_a, row_b]

        result = fetch_field_values_for_docs(db, [doc_id_a, doc_id_b])
        assert len(result[doc_id_a]) == 1
        assert result[doc_id_a][0].value == "alpha"
        assert len(result[doc_id_b]) == 1
        assert result[doc_id_b][0].value == "beta"


# ---------------------------------------------------------------------------
# extracted_data_patch via patch_document (service integration)
# ---------------------------------------------------------------------------


class TestExtractedDataPatch:
    """Verify the shallow-merge logic in files.service.patch_document."""

    def test_merges_keys_without_replacing_existing(self):
        from app.modules.files.schemas import DocumentPatchIn
        from app.modules.files.service import patch_document

        doc = _make_doc()
        doc.extracted_data = {"vendor": "Acme", "total_amount": 100.0, "currency": "MYR"}

        db = MagicMock()
        db.get.return_value = doc
        db.scalars.return_value = _scalar_first(None)
        db.execute.return_value.all.return_value = []

        user = MagicMock()
        user.user_id = str(uuid.uuid4())
        user.tenant_id = str(_TENANT_ID)

        patch_in = DocumentPatchIn.model_construct(
            _fields_set={"extracted_data_patch"},
            extracted_data_patch={"vendor": "Corrected Vendor"},
        )

        with (
            patch("app.modules.files.service._user_name", return_value="Test User"),
            patch("app.modules.files.service._fetch_tags_for_docs", return_value={}),
            patch("app.modules.files.service._fetch_correspondents_for_ids", return_value={}),
            patch("app.modules.files.service.fetch_field_values_for_docs", return_value={}),
        ):
            patch_document(db, user, _DOC_ID, patch_in)

        assert doc.extracted_data["vendor"] == "Corrected Vendor"
        assert doc.extracted_data["total_amount"] == 100.0
        assert doc.extracted_data["currency"] == "MYR"

    def test_patch_without_extracted_data_patch_leaves_data_unchanged(self):
        from app.modules.files.schemas import DocumentPatchIn
        from app.modules.files.service import patch_document

        doc = _make_doc()
        doc.extracted_data = {"vendor": "Acme"}

        db = MagicMock()
        db.get.return_value = doc
        db.scalars.return_value = _scalar_first(None)
        db.execute.return_value.all.return_value = []

        user = MagicMock()
        user.user_id = str(uuid.uuid4())
        user.tenant_id = str(_TENANT_ID)

        patch_in = DocumentPatchIn.model_construct(
            _fields_set={"title"},
            title="New Title",
        )

        with (
            patch("app.modules.files.service._user_name", return_value="Test User"),
            patch("app.modules.files.service._fetch_tags_for_docs", return_value={}),
            patch("app.modules.files.service._fetch_correspondents_for_ids", return_value={}),
            patch("app.modules.files.service.fetch_field_values_for_docs", return_value={}),
        ):
            patch_document(db, user, _DOC_ID, patch_in)

        assert doc.extracted_data == {"vendor": "Acme"}  # unchanged
