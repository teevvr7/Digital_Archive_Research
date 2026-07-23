"""Tests for Level-1 production-readiness additions:

- ``list_activity`` — the paginated audit-trail read endpoint (org-wide feed for
  Settings, or scoped to one document for the detail page's History tab).
- ``_mime_family`` — the mime-type bucketing used by the Settings storage widget.
- ``update_tenant_settings`` — the real (non-mock) organisation settings service call.

All I/O is mocked — no DB or Supabase, matching the rest of this module's tests.
"""

import uuid
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from app.models.activity_event import ACT_UPLOAD, ActivityEvent
from app.models.tenant import Tenant
from app.modules.auth import service as auth_service
from app.modules.files import service as files_service
from app.modules.idp import mimetype

# ---------------------------------------------------------------------------
# list_activity
# ---------------------------------------------------------------------------


def _make_event(document_id: uuid.UUID | None = None) -> ActivityEvent:
    evt = MagicMock(spec=ActivityEvent)
    evt.id = uuid.uuid4()
    evt.type = ACT_UPLOAD
    evt.document_id = document_id
    evt.document_name = "test.pdf"
    evt.user_id = uuid.uuid4()
    evt.user_name = "Test User"
    evt.timestamp = "2026-07-09T00:00:00Z"
    evt.meta = None
    return evt


class TestListActivity:
    def test_org_wide_feed_returns_paginated_shape(self) -> None:
        db = MagicMock()
        events = [_make_event(), _make_event()]
        db.scalars.return_value.all.return_value = events
        db.scalar.return_value = 2

        result = files_service.list_activity(db)

        assert result.total == 2
        assert result.page == 1
        assert len(result.items) == 2

    def test_scoped_to_document_still_paginates(self) -> None:
        db = MagicMock()
        doc_id = uuid.uuid4()
        db.scalars.return_value.all.return_value = [_make_event(document_id=doc_id)]
        db.scalar.return_value = 1

        result = files_service.list_activity(db, document_id=doc_id)

        assert result.total == 1
        assert result.items[0].document_id == doc_id

    def test_empty_feed(self) -> None:
        db = MagicMock()
        db.scalars.return_value.all.return_value = []
        db.scalar.return_value = 0

        result = files_service.list_activity(db)

        assert result.items == []
        assert result.total == 0

    def test_page_2_uses_offset(self) -> None:
        """Not asserting SQL directly (matches this module's existing test depth) —
        just that page=2 is threaded through to the response unchanged."""
        db = MagicMock()
        db.scalars.return_value.all.return_value = []
        db.scalar.return_value = 0

        result = files_service.list_activity(db, page=2)

        assert result.page == 2


# ---------------------------------------------------------------------------
# _mime_family — the Settings storage-breakdown bucketing
# ---------------------------------------------------------------------------


class TestMimeFamily:
    def test_pdf(self) -> None:
        assert files_service._mime_family(mimetype.MIME_PDF) == "pdf"

    def test_image(self) -> None:
        assert files_service._mime_family(mimetype.MIME_PNG) == "image"
        assert files_service._mime_family(mimetype.MIME_JPEG) == "image"

    def test_office(self) -> None:
        assert files_service._mime_family(mimetype.MIME_DOCX) == "office"
        assert files_service._mime_family(mimetype.MIME_XLSX) == "office"

    def test_text_family(self) -> None:
        assert files_service._mime_family(mimetype.MIME_TXT) == "text"
        assert files_service._mime_family(mimetype.MIME_CSV) == "text"

    def test_email(self) -> None:
        assert files_service._mime_family(mimetype.MIME_EML) == "email"

    def test_unknown_falls_back_to_other(self) -> None:
        assert files_service._mime_family("application/x-nonsense") == "other"


# ---------------------------------------------------------------------------
# update_tenant_settings
# ---------------------------------------------------------------------------


class TestUpdateTenantSettings:
    def test_renames_tenant(self) -> None:
        db = MagicMock()
        tenant = MagicMock(spec=Tenant)
        tenant.name = "Old Name"
        db.get.return_value = tenant
        tenant_id = uuid.uuid4()

        result = auth_service.update_tenant_settings(db, tenant_id, "New Name", None)

        assert tenant.name == "New Name"
        assert result is tenant
        db.flush.assert_called_once()

    def test_strips_whitespace(self) -> None:
        db = MagicMock()
        tenant = MagicMock(spec=Tenant)
        db.get.return_value = tenant

        auth_service.update_tenant_settings(db, uuid.uuid4(), "  Padded Name  ", None)

        assert tenant.name == "Padded Name"

    def test_empty_name_rejected(self) -> None:
        db = MagicMock()

        with pytest.raises(HTTPException) as exc_info:
            auth_service.update_tenant_settings(db, uuid.uuid4(), "   ", None)

        assert exc_info.value.status_code == 400
        db.get.assert_not_called()

    def test_missing_tenant_raises_404(self) -> None:
        db = MagicMock()
        db.get.return_value = None

        with pytest.raises(HTTPException) as exc_info:
            auth_service.update_tenant_settings(db, uuid.uuid4(), "New Name", None)

        assert exc_info.value.status_code == 404

    def test_sets_trash_retention_override(self) -> None:
        db = MagicMock()
        tenant = MagicMock(spec=Tenant)
        db.get.return_value = tenant

        auth_service.update_tenant_settings(db, uuid.uuid4(), "Name", 7)

        assert tenant.trash_retention_days == 7

    def test_none_clears_trash_retention_override(self) -> None:
        db = MagicMock()
        tenant = MagicMock(spec=Tenant)
        tenant.trash_retention_days = 7
        db.get.return_value = tenant

        auth_service.update_tenant_settings(db, uuid.uuid4(), "Name", None)

        assert tenant.trash_retention_days is None
