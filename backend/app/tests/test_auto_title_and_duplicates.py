"""Tests for idp/jobs.py::_apply_auto_title_and_duplicate_check — the Level 3
auto-title + duplicate-invoice-detection step. Both advisory, never blocking
(CLAUDE.md: ingestion must never block)."""

import uuid
from unittest.mock import MagicMock

from app.models.activity_event import ACT_DUPLICATE_DETECTED
from app.models.document import Document
from app.modules.idp.jobs import _apply_auto_title_and_duplicate_check


def _make_doc(*, vendor=None, invoice_no=None, title="original.pdf") -> MagicMock:
    doc = MagicMock(spec=Document)
    doc.id = uuid.uuid4()
    doc.vendor = vendor
    doc.invoice_no = invoice_no
    doc.title = title
    doc.original_filename = "original.pdf"
    doc.duplicate_of_document_id = None
    return doc


class TestAutoTitle:
    def test_no_op_when_vendor_missing(self):
        db = MagicMock()
        doc = _make_doc(vendor=None, invoice_no="INV-1")
        _apply_auto_title_and_duplicate_check(db, doc, uuid.uuid4())
        assert doc.title == "original.pdf"
        db.scalars.assert_not_called()

    def test_no_op_when_invoice_no_missing(self):
        db = MagicMock()
        doc = _make_doc(vendor="Acme Corp", invoice_no=None)
        _apply_auto_title_and_duplicate_check(db, doc, uuid.uuid4())
        assert doc.title == "original.pdf"
        db.scalars.assert_not_called()

    def test_no_op_when_both_missing(self):
        db = MagicMock()
        doc = _make_doc()
        _apply_auto_title_and_duplicate_check(db, doc, uuid.uuid4())
        assert doc.title == "original.pdf"
        db.scalars.assert_not_called()

    def test_sets_title_from_vendor_and_invoice_no(self):
        db = MagicMock()
        db.scalars.return_value.first.return_value = None  # no duplicate
        doc = _make_doc(vendor="Acme Corp", invoice_no="INV-100")

        _apply_auto_title_and_duplicate_check(db, doc, uuid.uuid4())

        assert doc.title == "Acme Corp — INV-100"


class TestDuplicateDetection:
    def test_no_duplicate_flagged_when_no_match(self):
        db = MagicMock()
        db.scalars.return_value.first.return_value = None
        doc = _make_doc(vendor="Acme Corp", invoice_no="INV-100")

        _apply_auto_title_and_duplicate_check(db, doc, uuid.uuid4())

        assert doc.duplicate_of_document_id is None
        db.add.assert_not_called()

    def test_flags_duplicate_when_match_found(self):
        db = MagicMock()
        existing_id = uuid.uuid4()
        db.scalars.return_value.first.return_value = existing_id
        doc = _make_doc(vendor="Acme Corp", invoice_no="INV-100")
        tenant_id = uuid.uuid4()

        _apply_auto_title_and_duplicate_check(db, doc, tenant_id)

        assert doc.duplicate_of_document_id == existing_id
        db.add.assert_called_once()
        event = db.add.call_args[0][0]
        assert event.type == ACT_DUPLICATE_DETECTED
        assert event.tenant_id == tenant_id
        assert event.document_id == doc.id
        assert event.user_id is None
        assert event.user_name == "system"

    def test_duplicate_check_never_blocks_title_from_being_set(self):
        """Even when a duplicate is found, the title still gets set — this
        is advisory, not a rejection."""
        db = MagicMock()
        db.scalars.return_value.first.return_value = uuid.uuid4()
        doc = _make_doc(vendor="Acme Corp", invoice_no="INV-100")

        _apply_auto_title_and_duplicate_check(db, doc, uuid.uuid4())

        assert doc.title == "Acme Corp — INV-100"
