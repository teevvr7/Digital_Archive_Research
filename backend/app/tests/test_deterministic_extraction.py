"""Deterministic extraction (Tier 2) + quality gate unit tests.

Covers ``idp/extract.py`` (doc-type keyword gate + regex/dateparser field
extraction) and ``idp/gate.py`` (the weighted 0.75 quality gate), plus the
new type-conditional structured-extraction branching in
``idp/jobs.py::process_document``. The eval harness (``python -m eval.run``)
covers the same modules end-to-end against real sample documents — these
tests are the fast, isolated, regression-focused complement.
"""

import datetime
from unittest.mock import MagicMock, patch

import pytest

from app.modules.idp.extract import (
    DOC_TYPE_INVOICE,
    DOC_TYPE_RECEIPT,
    ExtractionCandidate,
    LineItem,
    detect_candidate_type,
    extract_candidate,
)
from app.modules.idp.gate import PASS_THRESHOLD, score_extraction


# ---------------------------------------------------------------------------
# Doc-type keyword gate
# ---------------------------------------------------------------------------


def test_detect_invoice_keyword():
    assert detect_candidate_type("TAX INVOICE\nVendor: Acme\nTotal: 100.00") == DOC_TYPE_INVOICE


def test_detect_receipt_keyword():
    assert detect_candidate_type("OFFICIAL RECEIPT\nThank you for your payment") == DOC_TYPE_RECEIPT


def test_detect_neither_returns_none():
    """Contracts/reports/letters/quotes never become extraction candidates —
    structured extraction is type-conditional, not a default for every file."""
    assert detect_candidate_type("QUOTE\nQuote number: 1001\nQuote total: $500") is None
    assert detect_candidate_type("SERVICE AGREEMENT\nThis contract is entered into...") is None


def test_extract_candidate_returns_none_for_empty_text():
    assert extract_candidate("") is None
    assert extract_candidate("   \n  ") is None
    assert extract_candidate(None) is None


# ---------------------------------------------------------------------------
# Field extraction — regression tests for bugs caught during calibration
# ---------------------------------------------------------------------------


def test_invoice_number_requires_a_number_label_not_bare_invoice_word():
    """The bare document title 'Invoice' must never itself be captured as the
    invoice number just because some unrelated word follows it (a real
    calibration bug: 'Invoice\\nmike\\n...' must not yield invoice_number='mike')."""
    text = "Invoice\nmike\nBILL TO\nINVOICE #\n100\ncharles\nTOTAL\nRM 100.00"
    candidate = extract_candidate(text)
    assert candidate is not None
    assert candidate.invoice_number == "100"


def test_currency_rm_does_not_false_match_inside_terms():
    """Regression: 'RM' as a Ringgit symbol must be word-bounded — it must not
    match the substring inside ordinary words like 'TERMS & CONDITIONS'."""
    text = "INVOICE\nTERMS & CONDITIONS\nTotal: 50.00"
    candidate = extract_candidate(text)
    assert candidate is not None
    assert candidate.currency is None


def test_currency_rm_matches_as_a_real_standalone_token():
    text = "INVOICE\nTotal\nRM 100.00"
    candidate = extract_candidate(text)
    assert candidate.currency == "MYR"


def test_bare_date_label_does_not_match_inside_due_date():
    """Regression: a bare 'Date:' label elsewhere in the doc must still be
    found even when a 'Due Date'/'DueDate' label also exists — the exclusion
    must be positional (this specific match), not document-wide."""
    text = "INVOICE\nDate:Dec1,2023\nDueDate:Jan15,2024\nTotal: 50.00"
    candidate = extract_candidate(text)
    assert candidate.invoice_date == datetime.date(2023, 12, 1)
    assert candidate.due_date == datetime.date(2024, 1, 15)


def test_total_prefers_balance_due_and_grand_total_over_subtotal():
    text = (
        "INVOICE\nSubtotal: 90.00\nGST: 10.00\nGRAND TOTAL: 100.00"
    )
    candidate = extract_candidate(text)
    assert candidate.total_amount == 100.0


def test_vendor_skips_label_lines_ending_in_colon():
    text = "Order by:\nReal Vendor Co\nINVOICE\nTotal: 1.00"
    candidate = extract_candidate(text)
    assert candidate.vendor == "Real Vendor Co"


def test_line_items_simple_description_amount_pattern():
    text = "INVOICE\nConsulting services 250.00\nTotal: 250.00"
    candidate = extract_candidate(text)
    assert len(candidate.line_items) == 1
    item = candidate.line_items[0]
    assert item.amount == 250.0
    assert item.quantity == 1.0


def test_line_items_full_qty_price_amount_pattern():
    text = "INVOICE\nWidget 2 10.00 20.00\nTotal: 20.00"
    candidate = extract_candidate(text)
    assert len(candidate.line_items) == 1
    item = candidate.line_items[0]
    assert item.quantity == 2.0
    assert item.unit_price == 10.0
    assert item.amount == 20.0


def test_line_items_skip_total_label_lines():
    """A 'Subtotal 100.00'-shaped line must not be mistaken for a line item."""
    text = "INVOICE\nSubtotal 100.00\nTotal 100.00"
    candidate = extract_candidate(text)
    assert candidate.line_items == []


# ---------------------------------------------------------------------------
# Quality gate
# ---------------------------------------------------------------------------


def _full_candidate(**overrides) -> ExtractionCandidate:
    base = dict(
        document_type=DOC_TYPE_INVOICE,
        vendor="Acme Corp",
        invoice_number="INV-100",
        invoice_date=datetime.date(2026, 1, 1),
        due_date=datetime.date(2026, 1, 31),
        total_amount=100.0,
        currency="USD",
        line_items=[],
    )
    base.update(overrides)
    return ExtractionCandidate(**base)


def test_gate_passes_clean_candidate_with_no_ocr_uncertainty():
    result = score_extraction(_full_candidate(), ocr_confidence=None)
    assert result.passed is True
    assert result.score == 1.0


def test_gate_fails_empty_candidate():
    empty = ExtractionCandidate(document_type=DOC_TYPE_INVOICE)
    result = score_extraction(empty, ocr_confidence=None)
    assert result.passed is False
    assert result.score < PASS_THRESHOLD


def test_gate_low_ocr_confidence_can_drag_a_score_below_threshold():
    candidate = _full_candidate()
    high_conf_result = score_extraction(candidate, ocr_confidence=1.0)
    low_conf_result = score_extraction(candidate, ocr_confidence=0.1)
    assert low_conf_result.score < high_conf_result.score


def test_gate_invalid_invoice_number_lowers_format_validity():
    """A pure-alphabetic 'invoice number' (the OCR-column-bleed failure mode
    from real calibration) must score worse than a digit-bearing one, even
    if it doesn't always drop below threshold on its own."""
    valid = score_extraction(_full_candidate(invoice_number="INV-100"), ocr_confidence=None)
    invalid = score_extraction(_full_candidate(invoice_number="Scott"), ocr_confidence=None)
    assert invalid.breakdown["format_validity"] < valid.breakdown["format_validity"]
    assert invalid.score < valid.score


def test_gate_math_audit_neutral_when_no_line_items():
    """Never punish a document for this tier's known line-item limitation."""
    result = score_extraction(_full_candidate(line_items=[]), ocr_confidence=None)
    assert result.breakdown["math_audit"] == 1.0


def test_gate_math_audit_passes_when_items_reconcile():
    items = [LineItem(description="A", quantity=2, unit_price=50.0, amount=100.0)]
    result = score_extraction(_full_candidate(line_items=items, total_amount=100.0), ocr_confidence=None)
    assert result.breakdown["math_audit"] == 1.0


def test_gate_math_audit_penalises_when_items_do_not_reconcile():
    items = [LineItem(description="A", quantity=2, unit_price=50.0, amount=100.0)]
    result = score_extraction(_full_candidate(line_items=items, total_amount=999.0), ocr_confidence=None)
    assert result.breakdown["math_audit"] < 1.0


def test_gate_threshold_is_075():
    """The threshold itself — changing it requires explicit human sign-off
    per CLAUDE.md. This test exists to make an accidental change visible."""
    assert PASS_THRESHOLD == 0.75


# ---------------------------------------------------------------------------
# process_document — type-conditional gating between deterministic/VLM/skip
# ---------------------------------------------------------------------------


def _mock_job():
    job = MagicMock()
    job.attempts = 0
    return job


def test_process_document_skips_vlm_when_deterministic_gate_passes():
    """The core cost-saving behaviour: a clean deterministic extraction must
    never trigger a VLM call at all."""
    from app.models.document import Document, STATUS_COMPLETED

    doc = MagicMock(spec=Document)
    doc.id = "00000000-0000-0000-0000-000000000001"
    doc.mime_type = "application/pdf"
    doc.tenant_id = "00000000-0000-0000-0000-000000000002"
    doc.status = "queued"
    doc.original_filename = "test.pdf"
    doc.extracted_data = None

    mock_db = MagicMock()
    mock_db.get.return_value = doc
    mock_db.scalars.return_value.first.return_value = _mock_job()

    extraction_result = MagicMock(
        text="TAX INVOICE\nInvoice #: 100\nTotal: 100.00",
        page_count=1, has_text_layer=True, ocr_used=False, ocr_confidence=None,
    )

    with patch("app.modules.idp.jobs.tenant_session") as mock_ctx, \
         patch("app.modules.idp.jobs.object_storage") as mock_storage, \
         patch("app.modules.idp.jobs.run_extraction", return_value=extraction_result), \
         patch("app.modules.idp.jobs.run_ai_extraction") as mock_vlm, \
         patch("app.modules.idp.jobs.generate_thumbnail", return_value=None), \
         patch("app.modules.idp.jobs.ai_budget"):
        mock_ctx.return_value.__enter__.return_value = mock_db
        mock_ctx.return_value.__exit__.return_value = False
        mock_storage.download_file.return_value = b"fake bytes"

        from app.modules.idp.jobs import process_document
        process_document(doc.id, str(doc.tenant_id))

    mock_vlm.assert_not_called()
    assert doc.status == STATUS_COMPLETED
    assert doc.extracted_data is not None


def test_process_document_skips_both_tiers_for_non_candidate_content():
    """A contract/report/letter — VLM-eligible mime, but content doesn't look
    invoice/receipt-like — must never reach the deterministic OR VLM tier."""
    from app.models.document import Document, STATUS_COMPLETED

    doc = MagicMock(spec=Document)
    doc.id = "00000000-0000-0000-0000-000000000003"
    doc.mime_type = "application/pdf"
    doc.tenant_id = "00000000-0000-0000-0000-000000000004"
    doc.status = "queued"
    doc.original_filename = "test.pdf"
    doc.extracted_data = None

    mock_db = MagicMock()
    mock_db.get.return_value = doc
    mock_db.scalars.return_value.first.return_value = _mock_job()

    extraction_result = MagicMock(
        text="SERVICE AGREEMENT\nThis contract is entered into by both parties.",
        page_count=3, has_text_layer=True, ocr_used=False, ocr_confidence=None,
    )

    with patch("app.modules.idp.jobs.tenant_session") as mock_ctx, \
         patch("app.modules.idp.jobs.object_storage") as mock_storage, \
         patch("app.modules.idp.jobs.run_extraction", return_value=extraction_result), \
         patch("app.modules.idp.jobs.run_ai_extraction") as mock_vlm, \
         patch("app.modules.idp.jobs.generate_thumbnail", return_value=None), \
         patch("app.modules.idp.jobs.ai_budget"):
        mock_ctx.return_value.__enter__.return_value = mock_db
        mock_ctx.return_value.__exit__.return_value = False
        mock_storage.download_file.return_value = b"fake bytes"

        from app.modules.idp.jobs import process_document
        process_document(doc.id, str(doc.tenant_id))

    mock_vlm.assert_not_called()
    assert doc.status == STATUS_COMPLETED
    assert doc.extracted_data is None


def test_process_document_marks_needs_review_when_both_tiers_fail():
    """Content looks invoice-like, deterministic gate fails, AND the VLM
    fallback produces nothing usable -> needs_review, not a silent 'completed'."""
    from app.models.document import Document, STATUS_NEEDS_REVIEW

    doc = MagicMock(spec=Document)
    doc.id = "00000000-0000-0000-0000-000000000005"
    doc.mime_type = "application/pdf"
    doc.tenant_id = "00000000-0000-0000-0000-000000000006"
    doc.status = "queued"
    doc.original_filename = "test.pdf"
    doc.extracted_data = None

    mock_db = MagicMock()
    mock_db.get.return_value = doc
    mock_db.scalars.return_value.first.return_value = _mock_job()

    # "Invoice"-ish keyword present but no usable fields -> low gate score.
    extraction_result = MagicMock(
        text="INVOICE\n(no other readable content)",
        page_count=1, has_text_layer=True, ocr_used=False, ocr_confidence=None,
    )
    vlm_outcome = MagicMock(extraction=None, error="no usable output", total_tokens=0)

    with patch("app.modules.idp.jobs.tenant_session") as mock_ctx, \
         patch("app.modules.idp.jobs.object_storage") as mock_storage, \
         patch("app.modules.idp.jobs.run_extraction", return_value=extraction_result), \
         patch("app.modules.idp.jobs.run_ai_extraction", return_value=vlm_outcome), \
         patch("app.modules.idp.jobs.generate_thumbnail", return_value=None), \
         patch("app.modules.idp.jobs.ai_budget") as mock_budget:
        mock_ctx.return_value.__enter__.return_value = mock_db
        mock_ctx.return_value.__exit__.return_value = False
        mock_storage.download_file.return_value = b"fake bytes"
        mock_budget.llm_allowed.return_value = True

        from app.modules.idp.jobs import process_document
        process_document(doc.id, str(doc.tenant_id))

    assert doc.status == STATUS_NEEDS_REVIEW
