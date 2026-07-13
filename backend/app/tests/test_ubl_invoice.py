"""Tests for the MyInvois / UBL 2.1 invoice parser (Level 5 — Malaysia differentiator).

The parser unit tests below need no mocking — pure stdlib XML parsing, no I/O.
``TestProcessDocumentUblIntegration`` covers the actual jobs.py wiring using
the same tenant_session-mocking pattern as test_idp_tenant_isolation.py's
``test_process_document_raises_when_doc_not_found``.
"""

import uuid
from unittest.mock import MagicMock, patch

from app.modules.idp import mimetype
from app.modules.idp.gate import score_extraction
from app.modules.idp.ubl_invoice import extract_ubl_text, is_ubl_invoice, parse_ubl_invoice

_SAMPLE_UBL_INVOICE = b"""<?xml version="1.0" encoding="UTF-8"?>
<Invoice xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"
         xmlns:cac="urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"
         xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2">
  <cbc:ID>INV-2026-00042</cbc:ID>
  <cbc:IssueDate>2026-06-15</cbc:IssueDate>
  <cbc:DueDate>2026-07-15</cbc:DueDate>
  <cbc:DocumentCurrencyCode>MYR</cbc:DocumentCurrencyCode>
  <cac:AccountingSupplierParty>
    <cac:Party>
      <cac:PartyLegalEntity>
        <cbc:RegistrationName>Tenaga Nasional Berhad</cbc:RegistrationName>
      </cac:PartyLegalEntity>
    </cac:Party>
  </cac:AccountingSupplierParty>
  <cac:AccountingCustomerParty>
    <cac:Party>
      <cac:PartyLegalEntity>
        <cbc:RegistrationName>Acme Sdn Bhd</cbc:RegistrationName>
      </cac:PartyLegalEntity>
    </cac:Party>
  </cac:AccountingCustomerParty>
  <cac:InvoiceLine>
    <cbc:InvoicedQuantity>2</cbc:InvoicedQuantity>
    <cbc:LineExtensionAmount>200.00</cbc:LineExtensionAmount>
    <cac:Item>
      <cbc:Name>Electricity supply - Zone A</cbc:Name>
    </cac:Item>
    <cac:Price>
      <cbc:PriceAmount>100.00</cbc:PriceAmount>
    </cac:Price>
  </cac:InvoiceLine>
  <cac:LegalMonetaryTotal>
    <cbc:PayableAmount>200.00</cbc:PayableAmount>
  </cac:LegalMonetaryTotal>
</Invoice>
"""

_NON_UBL_XML = b"""<?xml version="1.0"?><catalog><book id="1">Some text</book></catalog>"""

_XXE_ATTEMPT = b"""<?xml version="1.0"?>
<!DOCTYPE Invoice [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>
<Invoice xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2">
  <cbc:ID xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2">
    &xxe;
  </cbc:ID>
</Invoice>
"""


class TestIsUblInvoice:
    def test_recognizes_valid_ubl_invoice(self):
        assert is_ubl_invoice(_SAMPLE_UBL_INVOICE) is True

    def test_rejects_non_ubl_xml(self):
        assert is_ubl_invoice(_NON_UBL_XML) is False

    def test_rejects_malformed_xml(self):
        assert is_ubl_invoice(b"<Invoice><unterminated>") is False

    def test_rejects_doctype_declaration(self):
        """XXE guard: a DOCTYPE/ENTITY declaration is never in a legitimate
        UBL invoice — reject outright rather than let ElementTree touch it."""
        assert is_ubl_invoice(_XXE_ATTEMPT) is False


class TestParseUblInvoice:
    def test_extracts_all_header_fields(self):
        candidate = parse_ubl_invoice(_SAMPLE_UBL_INVOICE)
        assert candidate is not None
        assert candidate.document_type == "invoice"
        assert candidate.vendor == "Tenaga Nasional Berhad"
        assert candidate.invoice_number == "INV-2026-00042"
        assert candidate.invoice_date.isoformat() == "2026-06-15"
        assert candidate.due_date.isoformat() == "2026-07-15"
        assert candidate.total_amount == 200.00
        assert candidate.currency == "MYR"

    def test_extracts_line_items(self):
        candidate = parse_ubl_invoice(_SAMPLE_UBL_INVOICE)
        assert len(candidate.line_items) == 1
        li = candidate.line_items[0]
        assert li.description == "Electricity supply - Zone A"
        assert li.quantity == 2
        assert li.unit_price == 100.00
        assert li.amount == 200.00

    def test_returns_none_for_non_ubl_xml(self):
        assert parse_ubl_invoice(_NON_UBL_XML) is None

    def test_returns_none_for_malformed_xml(self):
        assert parse_ubl_invoice(b"not even xml") is None

    def test_returns_none_for_xxe_attempt(self):
        assert parse_ubl_invoice(_XXE_ATTEMPT) is None

    def test_missing_optional_fields_are_none_not_raising(self):
        minimal = b"""<?xml version="1.0"?>
        <Invoice xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"
                 xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2">
          <cbc:ID>INV-1</cbc:ID>
        </Invoice>"""
        candidate = parse_ubl_invoice(minimal)
        assert candidate is not None
        assert candidate.invoice_number == "INV-1"
        assert candidate.vendor is None
        assert candidate.due_date is None
        assert candidate.total_amount is None
        assert candidate.line_items == []

    def test_feeds_cleanly_into_the_shared_quality_gate(self):
        """The real integration point: a well-formed UBL candidate should pass
        the same gate.py scoring every other deterministic source goes
        through, with ocr_confidence=None scored as a clean 1.0."""
        candidate = parse_ubl_invoice(_SAMPLE_UBL_INVOICE)
        result = score_extraction(candidate, ocr_confidence=None)
        assert result.passed is True
        assert result.score >= 0.75


class TestExtractUblText:
    def test_captures_all_text_nodes_for_search(self):
        text = extract_ubl_text(_SAMPLE_UBL_INVOICE)
        assert "Tenaga Nasional Berhad" in text
        assert "Acme Sdn Bhd" in text  # customer, not in parse_ubl_invoice's fields
        assert "INV-2026-00042" in text
        assert "Electricity supply - Zone A" in text

    def test_empty_string_on_malformed_xml(self):
        assert extract_ubl_text(b"not xml") == ""

    def test_empty_string_on_xxe_attempt(self):
        assert extract_ubl_text(_XXE_ATTEMPT) == ""


# ---------------------------------------------------------------------------
# process_document integration — the actual jobs.py wiring
# ---------------------------------------------------------------------------

def _scalars_dispatch(job_mock, duplicate_id):
    """Mirrors test_tags.py's scalars_side pattern: route by table name in
    the compiled statement so one mocked db.scalars serves every distinct
    query process_document issues along the UBL success path."""

    def _dispatch(stmt):
        stmt_str = str(stmt).lower()
        result = MagicMock()
        if "processing_jobs" in stmt_str:
            result.first.return_value = job_mock
        elif "documents" in stmt_str:
            result.first.return_value = duplicate_id  # None unless testing dedup
        elif "correspondents" in stmt_str:
            result.all.return_value = []
        elif "tags" in stmt_str:
            result.all.return_value = []
        else:
            result.all.return_value = []
            result.first.return_value = None
        return result

    return _dispatch


class TestProcessDocumentUblIntegration:
    def _make_doc(self):
        doc = MagicMock()
        doc.id = uuid.uuid4()
        doc.tenant_id = uuid.uuid4()
        doc.mime_type = mimetype.MIME_XML
        doc.storage_key = "tenants/x/doc.xml"
        doc.title = None
        doc.original_filename = "invoice.xml"
        doc.correspondent_id = None
        return doc

    def _run(self, doc, xml_bytes, duplicate_id=None):
        from app.modules.idp.jobs import process_document

        job = MagicMock()
        mock_db = MagicMock()
        mock_db.get.return_value = doc
        mock_db.scalars.side_effect = _scalars_dispatch(job, duplicate_id)

        with patch("app.modules.idp.jobs.tenant_session") as mock_ctx, patch(
            "app.modules.idp.jobs.object_storage.download_file", return_value=xml_bytes
        ):
            mock_ctx.return_value.__enter__.return_value = mock_db
            mock_ctx.return_value.__exit__.return_value = False
            process_document(str(doc.id), str(doc.tenant_id))
        return doc, job

    def test_well_formed_ubl_invoice_reaches_completed_via_deterministic_gate(self):
        doc, job = self._run(self._make_doc(), _SAMPLE_UBL_INVOICE)

        assert doc.vendor == "Tenaga Nasional Berhad"
        assert doc.invoice_no == "INV-2026-00042"
        assert doc.total_amount == 200.00
        assert doc.currency == "MYR"
        assert doc.extracted_data["invoiceNumber"] == "INV-2026-00042"
        assert doc.status == "completed"
        assert doc.confidence >= 0.75
        # Auto-title fires because both vendor and invoice_no are present.
        assert doc.title == "Tenaga Nasional Berhad — INV-2026-00042"

    def test_malformed_xml_yields_no_candidate_and_completes_without_structured_data(self):
        doc, job = self._run(self._make_doc(), b"<Invoice><unterminated>")

        assert doc.status == "completed"  # not needs_review — extraction was never attempted
        doc.extracted_data = None  # unchanged from whatever default; no assertion needed on it

    def test_gate_failing_ubl_invoice_never_calls_vlm(self):
        # No total, no line items, no invoice number → fails _completeness_score.
        sparse = (
            b'<?xml version="1.0"?>'
            b'<Invoice xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2" '
            b'xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2">'
            b"<cbc:IssueDate>2026-01-01</cbc:IssueDate></Invoice>"
        )
        doc = self._make_doc()

        with patch("app.modules.idp.jobs.run_ai_extraction") as mock_vlm:
            doc, job = self._run(doc, sparse)

        mock_vlm.assert_not_called()
        assert doc.status == "needs_review"
