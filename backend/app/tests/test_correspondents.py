"""Tests for the correspondents module — CRUD."""

import uuid
from unittest.mock import MagicMock

import pytest

from sqlalchemy.exc import IntegrityError

from app.modules.correspondents.schemas import CorrespondentIn, CorrespondentPatchIn
from app.modules.correspondents.service import (
    create_correspondent,
    delete_correspondent,
    find_or_create_by_sender,
    list_correspondents,
    patch_correspondent,
)


def _make_user(tenant_id: str = "00000000-0000-0000-0000-000000000001") -> MagicMock:
    user = MagicMock()
    user.tenant_id = tenant_id
    return user


def _make_corresp(name: str = "Acme Corp", email: str | None = None) -> MagicMock:
    c = MagicMock()
    c.id = uuid.uuid4()
    c.tenant_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
    c.name = name
    c.email = email
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

    def test_409_on_duplicate_email(self):
        from fastapi import HTTPException
        db = MagicMock()
        no_name_match = MagicMock(first=MagicMock(return_value=None))
        existing = _make_corresp(email="dup@example.com")
        email_match = MagicMock(first=MagicMock(return_value=existing))
        db.scalars.side_effect = [no_name_match, email_match]
        user = _make_user()
        data = CorrespondentIn(name="New Co", email="dup@example.com")
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


class TestFindOrCreateBySender:
    def test_returns_existing_match_by_email(self):
        db = MagicMock()
        existing = _make_corresp(name="Alice", email="alice@example.com")
        db.scalars.return_value = MagicMock(first=MagicMock(return_value=existing))

        result = find_or_create_by_sender(
            db, existing.tenant_id, "Alice Example", "alice@example.com"
        )

        assert result is existing
        db.add.assert_not_called()

    def test_backfills_email_onto_existing_name_match(self):
        db = MagicMock()
        by_email = MagicMock(first=MagicMock(return_value=None))
        existing = _make_corresp(name="Alice Example", email=None)
        by_name = MagicMock(first=MagicMock(return_value=existing))
        db.scalars.side_effect = [by_email, by_name]

        result = find_or_create_by_sender(
            db, existing.tenant_id, "Alice Example", "alice@example.com"
        )

        assert result is existing
        assert existing.email == "alice@example.com"
        db.flush.assert_called_once()
        db.add.assert_not_called()

    def test_creates_new_correspondent_when_no_match(self):
        db = MagicMock()
        no_match = MagicMock(first=MagicMock(return_value=None))
        db.scalars.side_effect = [no_match, no_match]
        tenant_id = uuid.uuid4()

        result = find_or_create_by_sender(db, tenant_id, "Bob", "bob@example.com")

        db.begin_nested.assert_called_once()
        db.add.assert_called_once()
        added = db.add.call_args[0][0]
        assert added.tenant_id == tenant_id
        assert added.name == "Bob"
        assert added.email == "bob@example.com"
        assert result is added

    def test_falls_back_to_email_when_no_display_name(self):
        db = MagicMock()
        no_match = MagicMock(first=MagicMock(return_value=None))
        db.scalars.side_effect = [no_match, no_match]

        find_or_create_by_sender(db, uuid.uuid4(), None, "bob@example.com")

        added = db.add.call_args[0][0]
        assert added.name == "bob@example.com"

    def test_race_condition_recovers_via_requery(self):
        db = MagicMock()
        no_match = MagicMock(first=MagicMock(return_value=None))
        winner = _make_corresp(name="Bob", email="bob@example.com")
        found_after_race = MagicMock(first=MagicMock(return_value=winner))
        db.scalars.side_effect = [no_match, no_match, found_after_race]
        db.flush.side_effect = IntegrityError("stmt", {}, Exception("dup"))
        # A real SAVEPOINT propagates the exception out of `with`; a bare
        # MagicMock's __exit__ would otherwise swallow it (truthy return).
        db.begin_nested.return_value.__exit__.return_value = False

        result = find_or_create_by_sender(db, uuid.uuid4(), "Bob", "bob@example.com")

        assert result is winner


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
