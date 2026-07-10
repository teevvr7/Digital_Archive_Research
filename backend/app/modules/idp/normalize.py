"""Typed-field mapper — reads either extraction schema currently in play.

``documents.extracted_data`` holds two different JSON shapes depending on
which tier produced it: the deterministic tier (``extract.py``) writes
camelCase keys (``vendor``, ``invoiceNumber``, ``totalAmount``, ``currency``),
the VLM tier (``extraction.py``) writes snake_case keys (``vendor``,
``invoice_number``, ``total_amount``/``grand_total``, ``currency``). This
module is the one place that knows both spellings, so every typed-column
consumer (the pipeline, the migration backfill, tests) reads through it
instead of re-deriving the key list.

A third schema (nested, from the ``paddle_qwen`` engine) is expected to land
later — extend :func:`extract_typed_fields` with one more branch then, not a
rewrite.
"""

from typing import Any


def _coerce_amount(value: Any) -> float | None:
    """Best-effort float parse. VLM output is LLM-sourced and occasionally
    non-conforming (e.g. ``"1,234.50"``) — never raise, just return None."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        cleaned = value.replace(",", "").strip()
        try:
            return float(cleaned)
        except ValueError:
            return None
    return None


def extract_typed_fields(data: dict[str, Any] | None) -> dict[str, Any]:
    """Map either extraction schema to the typed-column shape:
    ``{vendor, invoice_no, total_amount, currency}``. Missing/unparseable
    values come back as None rather than raising, so this is always safe to
    call on real-world (including malformed VLM) data."""
    if not data:
        return {"vendor": None, "invoice_no": None, "total_amount": None, "currency": None}

    vendor = data.get("vendor")
    invoice_no = data.get("invoiceNumber") or data.get("invoice_number")
    total_amount = _coerce_amount(
        data.get("totalAmount") or data.get("total_amount") or data.get("grand_total")
    )
    currency = data.get("currency")

    return {
        "vendor": vendor if isinstance(vendor, str) and vendor.strip() else None,
        "invoice_no": invoice_no if isinstance(invoice_no, str) and invoice_no.strip() else None,
        "total_amount": total_amount,
        "currency": currency if isinstance(currency, str) and currency.strip() else None,
    }
