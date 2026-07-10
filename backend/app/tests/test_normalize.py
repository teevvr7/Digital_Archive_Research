"""Tests for idp/normalize.py — the typed-field mapper that reads both
extraction schemas (deterministic camelCase vs VLM snake_case)."""

from app.modules.idp.normalize import extract_typed_fields


class TestExtractTypedFields:
    def test_none_input(self) -> None:
        result = extract_typed_fields(None)
        assert result == {"vendor": None, "invoice_no": None, "total_amount": None, "currency": None}

    def test_empty_dict(self) -> None:
        result = extract_typed_fields({})
        assert result == {"vendor": None, "invoice_no": None, "total_amount": None, "currency": None}

    def test_deterministic_camelcase_schema(self) -> None:
        data = {
            "vendor": "Tenaga Nasional Berhad",
            "invoiceNumber": "INV-2026-0512345",
            "invoiceDate": "2026-05-31",
            "dueDate": "2026-06-15",
            "totalAmount": 1284.50,
            "currency": "MYR",
            "lineItems": [],
        }
        result = extract_typed_fields(data)
        assert result == {
            "vendor": "Tenaga Nasional Berhad",
            "invoice_no": "INV-2026-0512345",
            "total_amount": 1284.50,
            "currency": "MYR",
        }

    def test_vlm_snake_case_schema(self) -> None:
        data = {
            "vendor": "ACME Corp Ltd",
            "invoice_number": "INV-2026-PADDLE",
            "invoice_date": "2026-06-22",
            "total_amount": 1000.0,
            "currency": "MYR",
            "buyer": "DataWiz Corp",
        }
        result = extract_typed_fields(data)
        assert result == {
            "vendor": "ACME Corp Ltd",
            "invoice_no": "INV-2026-PADDLE",
            "total_amount": 1000.0,
            "currency": "MYR",
        }

    def test_vlm_grand_total_fallback(self) -> None:
        """Some VLM output uses grand_total instead of total_amount."""
        data = {"vendor": "X", "invoice_number": "1", "grand_total": 500.0, "currency": "USD"}
        result = extract_typed_fields(data)
        assert result["total_amount"] == 500.0

    def test_total_amount_priority_over_grand_total(self) -> None:
        data = {"total_amount": 100.0, "grand_total": 999.0}
        result = extract_typed_fields(data)
        assert result["total_amount"] == 100.0

    def test_amount_as_string_with_comma(self) -> None:
        """LLM output is occasionally non-conforming — must not raise."""
        data = {"total_amount": "1,234.50"}
        result = extract_typed_fields(data)
        assert result["total_amount"] == 1234.50

    def test_amount_as_garbage_string_returns_none(self) -> None:
        data = {"total_amount": "not a number"}
        result = extract_typed_fields(data)
        assert result["total_amount"] is None

    def test_amount_as_int(self) -> None:
        data = {"total_amount": 500}
        result = extract_typed_fields(data)
        assert result["total_amount"] == 500.0

    def test_blank_string_fields_become_none(self) -> None:
        data = {"vendor": "  ", "invoice_number": "", "currency": None}
        result = extract_typed_fields(data)
        assert result["vendor"] is None
        assert result["invoice_no"] is None
        assert result["currency"] is None

    def test_non_string_vendor_ignored(self) -> None:
        """Malformed VLM output could put a dict/list where a string is expected."""
        data = {"vendor": {"nested": "object"}}
        result = extract_typed_fields(data)
        assert result["vendor"] is None

    def test_camelcase_takes_priority_when_both_present(self) -> None:
        """Shouldn't normally happen, but camelCase wins if both keys exist."""
        data = {"invoiceNumber": "CAMEL-1", "invoice_number": "SNAKE-1"}
        result = extract_typed_fields(data)
        assert result["invoice_no"] == "CAMEL-1"
