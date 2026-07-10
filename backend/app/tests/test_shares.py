"""Tests for the shares module — create/list/revoke (authenticated) and the
public token-resolve endpoint (deliberately unauthenticated — see
modules/shares/service.py's docstring for the RLS-bypass rationale).

All I/O is mocked — no DB, no Supabase.
"""

import datetime
import uuid
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from app.core.security import TokenData
from app.models.document import Document
from app.models.document_share import DocumentShare
from app.modules.shares import service


def _make_token(tenant_id: uuid.UUID | None = None, user_id: uuid.UUID | None = None) -> TokenData:
    tenant_id = tenant_id or uuid.uuid4()
    user_id = user_id or uuid.uuid4()
    return TokenData({
        "sub": str(user_id),
        "email": "test@example.com",
        "app_metadata": {"tenant_id": str(tenant_id), "role": "user"},
    })


def _make_doc(*, deleted_at=None) -> MagicMock:
    doc = MagicMock(spec=Document)
    doc.id = uuid.uuid4()
    doc.storage_key = "tenant/docs/test.pdf"
    doc.original_filename = "test.pdf"
    doc.mime_type = "application/pdf"
    doc.deleted_at = deleted_at
    return doc


def _make_share(*, token: str = "abc123", expires_in_hours: float = 24) -> MagicMock:
    share = MagicMock(spec=DocumentShare)
    share.id = uuid.uuid4()
    share.document_id = uuid.uuid4()
    share.token = token
    share.created_at = datetime.datetime.now(datetime.timezone.utc)
    share.expires_at = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=expires_in_hours)
    return share


# ---------------------------------------------------------------------------
# create_share
# ---------------------------------------------------------------------------

class TestCreateShare:
    def test_404_when_document_not_found(self):
        db = MagicMock()
        db.get.return_value = None
        with pytest.raises(HTTPException) as exc_info:
            service.create_share(db, _make_token(), uuid.uuid4(), 7)
        assert exc_info.value.status_code == 404

    def test_404_when_document_trashed(self):
        db = MagicMock()
        db.get.return_value = _make_doc(deleted_at=datetime.datetime.now(datetime.timezone.utc))
        with pytest.raises(HTTPException) as exc_info:
            service.create_share(db, _make_token(), uuid.uuid4(), 7)
        assert exc_info.value.status_code == 404

    def test_creates_share_and_persists(self):
        # _share_to_out serializes real ORM-generated fields (id, created_at)
        # that only a live DB flush populates — a bare MagicMock db never
        # does, so it's patched here, matching the existing create_tag test
        # convention (test_tags.py::TestCreateTag).
        db = MagicMock()
        db.get.return_value = _make_doc()
        user = _make_token()
        expected = _make_share()

        with patch("app.modules.shares.service._share_to_out", return_value=expected):
            result = service.create_share(db, user, uuid.uuid4(), 7)

        db.add.assert_called_once()
        db.flush.assert_called_once()
        assert result.token == expected.token

    def test_expiry_clamped_to_max_30_days(self):
        db = MagicMock()
        db.get.return_value = _make_doc()
        captured = {}
        db.add.side_effect = lambda obj: captured.setdefault("share", obj)

        with patch("app.modules.shares.service._share_to_out", return_value=_make_share()):
            service.create_share(db, _make_token(), uuid.uuid4(), 9999)

        share = captured["share"]
        max_expected = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=30)
        assert abs((share.expires_at - max_expected).total_seconds()) < 5

    def test_expiry_clamped_to_min_1_day(self):
        db = MagicMock()
        db.get.return_value = _make_doc()
        captured = {}
        db.add.side_effect = lambda obj: captured.setdefault("share", obj)

        with patch("app.modules.shares.service._share_to_out", return_value=_make_share()):
            service.create_share(db, _make_token(), uuid.uuid4(), -5)

        share = captured["share"]
        min_expected = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=1)
        assert abs((share.expires_at - min_expected).total_seconds()) < 5

    def test_token_is_url_safe_and_long(self):
        db = MagicMock()
        db.get.return_value = _make_doc()
        captured = {}
        db.add.side_effect = lambda obj: captured.setdefault("share", obj)

        with patch("app.modules.shares.service._share_to_out", return_value=_make_share()):
            service.create_share(db, _make_token(), uuid.uuid4(), 7)

        assert len(captured["share"].token) >= 32


# ---------------------------------------------------------------------------
# list_shares / revoke_share
# ---------------------------------------------------------------------------

class TestListShares:
    def test_returns_mapped_list(self):
        db = MagicMock()
        shares = [_make_share(), _make_share(token="def456")]
        db.scalars.return_value.all.return_value = shares
        result = service.list_shares(db, uuid.uuid4())
        assert len(result) == 2
        assert result[0].token == shares[0].token

    def test_empty_list(self):
        db = MagicMock()
        db.scalars.return_value.all.return_value = []
        assert service.list_shares(db, uuid.uuid4()) == []


class TestRevokeShare:
    def test_404_if_not_found(self):
        db = MagicMock()
        db.get.return_value = None
        with pytest.raises(HTTPException) as exc_info:
            service.revoke_share(db, uuid.uuid4())
        assert exc_info.value.status_code == 404

    def test_deletes_and_flushes(self):
        db = MagicMock()
        share = _make_share()
        db.get.return_value = share
        service.revoke_share(db, share.id)
        db.delete.assert_called_once_with(share)
        db.flush.assert_called_once()


# ---------------------------------------------------------------------------
# resolve_share_token — the public, unauthenticated path
# ---------------------------------------------------------------------------

class TestResolveShareToken:
    def test_404_when_token_not_found(self):
        db = MagicMock()
        db.scalars.return_value.first.return_value = None
        with patch("app.modules.shares.service.SessionLocal", return_value=db):
            with pytest.raises(HTTPException) as exc_info:
                service.resolve_share_token("nonexistent")
        assert exc_info.value.status_code == 404
        db.close.assert_called_once()

    def test_410_when_expired(self):
        db = MagicMock()
        expired_share = _make_share(expires_in_hours=-1)
        db.scalars.return_value.first.return_value = expired_share
        with patch("app.modules.shares.service.SessionLocal", return_value=db):
            with pytest.raises(HTTPException) as exc_info:
                service.resolve_share_token(expired_share.token)
        assert exc_info.value.status_code == 410

    def test_404_when_document_gone(self):
        db = MagicMock()
        share = _make_share()
        db.scalars.return_value.first.return_value = share
        db.get.return_value = None
        with patch("app.modules.shares.service.SessionLocal", return_value=db):
            with pytest.raises(HTTPException) as exc_info:
                service.resolve_share_token(share.token)
        assert exc_info.value.status_code == 404

    def test_404_when_document_trashed(self):
        db = MagicMock()
        share = _make_share()
        db.scalars.return_value.first.return_value = share
        db.get.return_value = _make_doc(deleted_at=datetime.datetime.now(datetime.timezone.utc))
        with patch("app.modules.shares.service.SessionLocal", return_value=db):
            with pytest.raises(HTTPException) as exc_info:
                service.resolve_share_token(share.token)
        assert exc_info.value.status_code == 404

    def test_valid_token_returns_signed_url(self):
        db = MagicMock()
        share = _make_share()
        doc = _make_doc()
        db.scalars.return_value.first.return_value = share
        db.get.return_value = doc

        with patch("app.modules.shares.service.SessionLocal", return_value=db), \
             patch(
                 "app.modules.shares.service.object_storage.create_signed_url",
                 return_value="https://signed.example/url",
             ) as mock_signed:
            result = service.resolve_share_token(share.token)

        mock_signed.assert_called_once_with(doc.storage_key, expires_in=300)
        assert result.url == "https://signed.example/url"
        assert result.filename == doc.original_filename
        assert result.mime_type == doc.mime_type
        db.close.assert_called_once()

    def test_session_closed_even_on_error(self):
        db = MagicMock()
        db.scalars.side_effect = RuntimeError("db exploded")
        with patch("app.modules.shares.service.SessionLocal", return_value=db):
            with pytest.raises(RuntimeError):
                service.resolve_share_token("any-token")
        db.close.assert_called_once()
