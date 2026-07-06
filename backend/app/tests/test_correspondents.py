"""Tests for the correspondents module — CRUD."""

import uuid
from unittest.mock import MagicMock

import pytest

from app.modules.correspondents.schemas import CorrespondentIn, CorrespondentPatchIn
from app.modules.correspondents.service import (
    create_correspondent,
    delete_correspondent,
    list_correspondents,
    patch_correspondent,
)


def _make_user(tenant_id: str = "00000000-0000-0000-0000-000000000001") -> MagicMock:
    user = MagicMock()
    user.tenant_id = tenant_id
    return user


def _make_corresp(name: str = "Acme Corp") -> MagicMock:
    c = MagicMock()
    c.id = uuid.uuid4()
    c.tenant_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
    c.name = name
    c.match = "acme"
    c.matching_algorithm = "any"
    c.is_insensitive = True
    c.created_at = MagicMock()
    return c


class TestListCorrespondents:
    def test_returns_list(self):
        db = MagicMock()
        c = _make_corresp()
        db.scalars.return_value = MagicMock(all=MagicMock(return_value=[c]))
        result = list_correspondents(db)
        assert len(result) == 1
        assert result[0].name == "Acme Corp"


class TestCreateCorrespondent:
    def test_creates_successfully(self):
        from unittest.mock import patch as mpatch
        db = MagicMock()
        db.scalars.return_value = MagicMock(first=MagicMock(return_value=None))
        user = _make_user()
        data = CorrespondentIn(name="Acme Corp", match="acme", matching_algorithm="any")
        expected = _make_corresp("Acme Corp")

        with mpatch("app.modules.correspondents.service._to_out", return_value=expected):
            result = create_correspondent(db, user, data)

        db.add.assert_called_once()
        db.flush.assert_called_once()
        assert result.name == "Acme Corp"

    def test_409_on_duplicate_name(self):
        from fastapi import HTTPException
        db = MagicMock()
        existing = _make_corresp()
        db.scalars.return_value = MagicMock(first=MagicMock(return_value=existing))
        user = _make_user()
        data = CorrespondentIn(name="Acme Corp")
        with pytest.raises(HTTPException) as exc_info:
            create_correspondent(db, user, data)
        assert exc_info.value.status_code == 409


class TestPatchCorrespondent:
    def test_updates_name(self):
        db = MagicMock()
        c = _make_corresp()
        db.get.return_value = c
        patch_in = CorrespondentPatchIn.model_construct(_fields_set={"name"}, name="New Name")
        result = patch_correspondent(db, c.id, patch_in)
        assert c.name == "New Name"

    def test_404_if_not_found(self):
        from fastapi import HTTPException
        db = MagicMock()
        db.get.return_value = None
        with pytest.raises(HTTPException) as exc_info:
            patch_correspondent(db, uuid.uuid4(), CorrespondentPatchIn())
        assert exc_info.value.status_code == 404


class TestDeleteCorrespondent:
    def test_deletes(self):
        db = MagicMock()
        c = _make_corresp()
        db.get.return_value = c
        delete_correspondent(db, c.id)
        db.delete.assert_called_once_with(c)

    def test_404_if_not_found(self):
        from fastapi import HTTPException
        db = MagicMock()
        db.get.return_value = None
        with pytest.raises(HTTPException) as exc_info:
            delete_correspondent(db, uuid.uuid4())
        assert exc_info.value.status_code == 404
