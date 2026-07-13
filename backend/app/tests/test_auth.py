"""Tests for Level-4 team-account additions: list/invite/role-change/remove users.

All Supabase Admin API calls are mocked via ``auth_service._supabase_admin`` —
no network I/O, matching the rest of this module's tests.
"""

import uuid
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from supabase_auth.errors import AuthApiError

from app.core.security import TokenData
from app.models.tag import Tag
from app.models.user import User
from app.modules.auth import service as auth_service


def _token(user_id: uuid.UUID | None = None, email: str = "admin@acme.test") -> TokenData:
    tok = MagicMock(spec=TokenData)
    tok.user_id = str(user_id or uuid.uuid4())
    tok.email = email
    tok.tenant_id = None
    tok.role = "admin"
    return tok


def _make_user(role: str = "user", tenant_id: uuid.UUID | None = None) -> User:
    u = MagicMock(spec=User)
    u.id = uuid.uuid4()
    u.tenant_id = tenant_id
    u.role = role
    u.email = "target@acme.test"
    u.name = "Target User"
    return u


# ---------------------------------------------------------------------------
# _seed_starter_tags (onboarding starter kit)
# ---------------------------------------------------------------------------

class TestSeedStarterTags:
    def test_adds_starter_tags_for_new_tenant(self) -> None:
        db = MagicMock()
        tenant_id = uuid.uuid4()

        auth_service._seed_starter_tags(db, tenant_id)

        db.add_all.assert_called_once()
        tags = list(db.add_all.call_args[0][0])
        assert len(tags) == len(auth_service._STARTER_TAGS)
        assert all(isinstance(t, Tag) for t in tags)
        assert all(t.tenant_id == tenant_id for t in tags)
        assert {t.name for t in tags} == {name for name, _ in auth_service._STARTER_TAGS}


# ---------------------------------------------------------------------------
# list_users
# ---------------------------------------------------------------------------

class TestListUsers:
    def test_returns_tenant_members(self) -> None:
        db = MagicMock()
        users = [_make_user(), _make_user()]
        db.scalars.return_value = users

        result = auth_service.list_users(db, uuid.uuid4())

        assert result == users


# ---------------------------------------------------------------------------
# invite_user
# ---------------------------------------------------------------------------

class TestInviteUser:
    def _mock_admin(self) -> MagicMock:
        admin = MagicMock()
        admin.auth.admin.invite_user_by_email.return_value = MagicMock(
            user=MagicMock(id=str(uuid.uuid4()))
        )
        return admin

    def test_invalid_role_rejected(self) -> None:
        db = MagicMock()
        with pytest.raises(HTTPException) as exc_info:
            auth_service.invite_user(
                db, uuid.uuid4(), email="a@b.com", name="A", role="owner", invited_by=_token()
            )
        assert exc_info.value.status_code == 400
        db.add.assert_not_called()

    def test_missing_name_rejected(self) -> None:
        db = MagicMock()
        with pytest.raises(HTTPException) as exc_info:
            auth_service.invite_user(
                db, uuid.uuid4(), email="a@b.com", name="   ", role="user", invited_by=_token()
            )
        assert exc_info.value.status_code == 400

    def test_invalid_email_rejected(self) -> None:
        db = MagicMock()
        with pytest.raises(HTTPException) as exc_info:
            auth_service.invite_user(
                db, uuid.uuid4(), email="not-an-email", name="A", role="user", invited_by=_token()
            )
        assert exc_info.value.status_code == 400

    @patch("app.modules.auth.service._supabase_admin")
    def test_happy_path_creates_local_row_and_sets_app_metadata(self, mock_admin_fn) -> None:
        db = MagicMock()
        db.get.return_value = None  # actor name lookup misses -> falls back to email
        admin = self._mock_admin()
        mock_admin_fn.return_value = admin
        tenant_id = uuid.uuid4()

        user = auth_service.invite_user(
            db, tenant_id, email="New@Example.com ", name=" Jane Doe ", role="admin",
            invited_by=_token(email="boss@acme.test"),
        )

        assert user.email == "new@example.com"
        assert user.name == "Jane Doe"
        assert user.role == "admin"
        assert user.tenant_id == tenant_id
        assert user.last_login_at is None
        admin.auth.admin.invite_user_by_email.assert_called_once()
        admin.auth.admin.update_user_by_id.assert_called_once()
        call_args = admin.auth.admin.update_user_by_id.call_args
        assert call_args[0][1]["app_metadata"] == {"tenant_id": str(tenant_id), "role": "admin"}
        db.add.assert_any_call(user)
        db.flush.assert_called()

    @patch("app.modules.auth.service._supabase_admin")
    def test_supabase_conflict_becomes_409(self, mock_admin_fn) -> None:
        db = MagicMock()
        admin = MagicMock()
        admin.auth.admin.invite_user_by_email.side_effect = AuthApiError(
            "User already registered", 422, None
        )
        mock_admin_fn.return_value = admin

        with pytest.raises(HTTPException) as exc_info:
            auth_service.invite_user(
                db, uuid.uuid4(), email="dup@acme.test", name="Dup", role="user",
                invited_by=_token(),
            )
        assert exc_info.value.status_code == 409
        db.add.assert_not_called()

    @patch("app.modules.auth.service._supabase_admin")
    def test_local_integrity_error_becomes_409(self, mock_admin_fn) -> None:
        db = MagicMock()
        db.flush.side_effect = IntegrityError("stmt", {}, Exception("dup"))
        admin = self._mock_admin()
        mock_admin_fn.return_value = admin

        with pytest.raises(HTTPException) as exc_info:
            auth_service.invite_user(
                db, uuid.uuid4(), email="race@acme.test", name="Race", role="user",
                invited_by=_token(),
            )
        assert exc_info.value.status_code == 409


# ---------------------------------------------------------------------------
# update_user_role
# ---------------------------------------------------------------------------

class TestUpdateUserRole:
    @patch("app.modules.auth.service._supabase_admin")
    def test_happy_path_promotes_user(self, mock_admin_fn) -> None:
        db = MagicMock()
        tenant_id = uuid.uuid4()
        target = _make_user(role="user", tenant_id=tenant_id)
        db.get.return_value = target
        db.scalars.return_value = [uuid.uuid4()]  # one existing admin elsewhere
        mock_admin_fn.return_value = MagicMock()

        result = auth_service.update_user_role(
            db, tenant_id, target.id, role="admin", actor=_token()
        )

        assert result.role == "admin"
        db.flush.assert_called()

    def test_invalid_role_rejected(self) -> None:
        db = MagicMock()
        with pytest.raises(HTTPException) as exc_info:
            auth_service.update_user_role(db, uuid.uuid4(), uuid.uuid4(), role="owner", actor=_token())
        assert exc_info.value.status_code == 400

    def test_missing_target_raises_404(self) -> None:
        db = MagicMock()
        db.get.return_value = None
        with pytest.raises(HTTPException) as exc_info:
            auth_service.update_user_role(db, uuid.uuid4(), uuid.uuid4(), role="admin", actor=_token())
        assert exc_info.value.status_code == 404

    def test_target_in_other_tenant_raises_404(self) -> None:
        db = MagicMock()
        target = _make_user(tenant_id=uuid.uuid4())
        db.get.return_value = target
        with pytest.raises(HTTPException) as exc_info:
            auth_service.update_user_role(db, uuid.uuid4(), target.id, role="admin", actor=_token())
        assert exc_info.value.status_code == 404

    def test_demoting_last_admin_rejected(self) -> None:
        db = MagicMock()
        tenant_id = uuid.uuid4()
        target = _make_user(role="admin", tenant_id=tenant_id)
        db.get.return_value = target
        db.scalars.return_value = [target.id]  # target is the only admin

        with pytest.raises(HTTPException) as exc_info:
            auth_service.update_user_role(db, tenant_id, target.id, role="user", actor=_token())
        assert exc_info.value.status_code == 400
        assert "last admin" in exc_info.value.detail.lower()


# ---------------------------------------------------------------------------
# remove_user
# ---------------------------------------------------------------------------

class TestRemoveUser:
    def test_self_removal_rejected(self) -> None:
        db = MagicMock()
        actor = _token()
        with pytest.raises(HTTPException) as exc_info:
            auth_service.remove_user(db, uuid.uuid4(), uuid.UUID(actor.user_id), actor=actor)
        assert exc_info.value.status_code == 400
        db.get.assert_not_called()

    def test_missing_target_raises_404(self) -> None:
        db = MagicMock()
        db.get.return_value = None
        with pytest.raises(HTTPException) as exc_info:
            auth_service.remove_user(db, uuid.uuid4(), uuid.uuid4(), actor=_token())
        assert exc_info.value.status_code == 404

    def test_removing_last_admin_rejected(self) -> None:
        db = MagicMock()
        tenant_id = uuid.uuid4()
        target = _make_user(role="admin", tenant_id=tenant_id)
        db.get.return_value = target
        db.scalars.return_value = [target.id]

        with pytest.raises(HTTPException) as exc_info:
            auth_service.remove_user(db, tenant_id, target.id, actor=_token())
        assert exc_info.value.status_code == 400
        assert "last admin" in exc_info.value.detail.lower()

    @patch("app.modules.auth.service._supabase_admin")
    def test_happy_path_deletes_local_row_and_supabase_identity(self, mock_admin_fn) -> None:
        db = MagicMock()
        tenant_id = uuid.uuid4()
        target = _make_user(role="user", tenant_id=tenant_id)
        db.get.return_value = target
        db.scalars.return_value = [uuid.uuid4()]  # some other admin exists
        admin = MagicMock()
        mock_admin_fn.return_value = admin

        auth_service.remove_user(db, tenant_id, target.id, actor=_token())

        admin.auth.admin.delete_user.assert_called_once_with(str(target.id))
        db.delete.assert_called_once_with(target)
        db.flush.assert_called()

    @patch("app.modules.auth.service._supabase_admin")
    def test_supabase_failure_becomes_502(self, mock_admin_fn) -> None:
        db = MagicMock()
        tenant_id = uuid.uuid4()
        target = _make_user(role="user", tenant_id=tenant_id)
        db.get.return_value = target
        db.scalars.return_value = [uuid.uuid4()]
        admin = MagicMock()
        admin.auth.admin.delete_user.side_effect = AuthApiError("boom", 500, None)
        mock_admin_fn.return_value = admin

        with pytest.raises(HTTPException) as exc_info:
            auth_service.remove_user(db, tenant_id, target.id, actor=_token())
        assert exc_info.value.status_code == 502
        db.delete.assert_not_called()
