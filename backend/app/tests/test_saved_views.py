"""Tests for Phase 6: saved views CRUD."""

import uuid
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from app.modules.views.schemas import SavedViewIn, SavedViewPatchIn
from app.modules.views.service import (
    create_saved_view,
    delete_saved_view,
    list_saved_views,
    patch_saved_view,
)

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

_TENANT_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
_VIEW_ID = uuid.UUID("00000000-0000-0000-0000-000000000002")

_FILTER = {"status": "completed", "type": "invoice", "sort": "date_desc"}


def _make_view(
    name: str = "Invoices",
    filter_state: dict | None = None,
    is_default: bool = False,
) -> MagicMock:
    v = MagicMock()
    v.id = _VIEW_ID
    v.tenant_id = _TENANT_ID
    v.name = name
    v.filter_state = filter_state or _FILTER
    v.is_default = is_default
    v.created_at = MagicMock()
    return v


def _scalars_all(items: list) -> MagicMock:
    return MagicMock(all=MagicMock(return_value=items))


def _scalars_first(item) -> MagicMock:
    return MagicMock(first=MagicMock(return_value=item))


# ---------------------------------------------------------------------------
# list_saved_views
# ---------------------------------------------------------------------------


class TestListSavedViews:
    def test_returns_empty_list(self):
        db = MagicMock()
        db.scalars.return_value = _scalars_all([])
        assert list_saved_views(db) == []

    def test_maps_view_to_out(self):
        db = MagicMock()
        db.scalars.return_value = _scalars_all([_make_view("Invoices")])
        result = list_saved_views(db)
        assert len(result) == 1
        assert result[0].name == "Invoices"
        assert result[0].filter_state == _FILTER
        assert result[0].is_default is False

    def test_returns_multiple_views(self):
        db = MagicMock()
        db.scalars.return_value = _scalars_all([
            _make_view("Invoices"),
            _make_view("Contracts"),
        ])
        result = list_saved_views(db)
        assert len(result) == 2


# ---------------------------------------------------------------------------
# create_saved_view
# ---------------------------------------------------------------------------


class TestCreateSavedView:
    def test_creates_view(self):
        db = MagicMock()
        db.scalars.return_value = _scalars_first(None)
        data = SavedViewIn(name="My View", filter_state=_FILTER)
        with patch("app.modules.views.service._to_out", return_value=MagicMock()):
            create_saved_view(db, _TENANT_ID, data)
        db.add.assert_called_once()
        db.flush.assert_called_once()

    def test_stores_filter_state(self):
        db = MagicMock()
        db.scalars.return_value = _scalars_first(None)
        custom_filter = {"status": "needs_review", "sort": "name_asc"}
        data = SavedViewIn(name="Review Queue", filter_state=custom_filter)
        with patch("app.modules.views.service._to_out", return_value=MagicMock()):
            create_saved_view(db, _TENANT_ID, data)
        added = db.add.call_args[0][0]
        assert added.filter_state == custom_filter

    def test_409_on_duplicate_name(self):
        db = MagicMock()
        db.scalars.return_value = _scalars_first(_make_view("Invoices"))
        data = SavedViewIn(name="Invoices", filter_state={})
        with pytest.raises(HTTPException) as exc:
            create_saved_view(db, _TENANT_ID, data)
        assert exc.value.status_code == 409

    def test_empty_filter_state_allowed(self):
        db = MagicMock()
        db.scalars.return_value = _scalars_first(None)
        data = SavedViewIn(name="All docs", filter_state={})
        with patch("app.modules.views.service._to_out", return_value=MagicMock()):
            create_saved_view(db, _TENANT_ID, data)
        db.add.assert_called_once()

    def test_is_default_flag_stored(self):
        db = MagicMock()
        db.scalars.return_value = _scalars_first(None)
        data = SavedViewIn(name="Default", filter_state={}, is_default=True)
        with patch("app.modules.views.service._to_out", return_value=MagicMock()):
            create_saved_view(db, _TENANT_ID, data)
        added = db.add.call_args[0][0]
        assert added.is_default is True


# ---------------------------------------------------------------------------
# patch_saved_view
# ---------------------------------------------------------------------------


class TestPatchSavedView:
    def test_updates_name(self):
        db = MagicMock()
        view = _make_view("Old Name")
        db.get.return_value = view
        patch_in = SavedViewPatchIn.model_construct(_fields_set={"name"}, name="New Name")
        patch_saved_view(db, _VIEW_ID, patch_in)
        assert view.name == "New Name"

    def test_updates_filter_state(self):
        db = MagicMock()
        view = _make_view()
        db.get.return_value = view
        new_filter = {"status": "failed"}
        patch_in = SavedViewPatchIn.model_construct(
            _fields_set={"filter_state"}, filter_state=new_filter
        )
        patch_saved_view(db, _VIEW_ID, patch_in)
        assert view.filter_state == new_filter

    def test_updates_is_default(self):
        db = MagicMock()
        view = _make_view()
        db.get.return_value = view
        patch_in = SavedViewPatchIn.model_construct(_fields_set={"is_default"}, is_default=True)
        patch_saved_view(db, _VIEW_ID, patch_in)
        assert view.is_default is True

    def test_404_if_not_found(self):
        db = MagicMock()
        db.get.return_value = None
        with pytest.raises(HTTPException) as exc:
            patch_saved_view(db, _VIEW_ID, SavedViewPatchIn())
        assert exc.value.status_code == 404


# ---------------------------------------------------------------------------
# delete_saved_view
# ---------------------------------------------------------------------------


class TestDeleteSavedView:
    def test_deletes_view(self):
        db = MagicMock()
        view = _make_view()
        db.get.return_value = view
        delete_saved_view(db, _VIEW_ID)
        db.delete.assert_called_once_with(view)

    def test_404_if_not_found(self):
        db = MagicMock()
        db.get.return_value = None
        with pytest.raises(HTTPException) as exc:
            delete_saved_view(db, _VIEW_ID)
        assert exc.value.status_code == 404
