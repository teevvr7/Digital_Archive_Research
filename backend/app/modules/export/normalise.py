"""Field normalisation utilities for the Spreadsheet Center export module.

Two responsibilities:
- ``normalise_keys``: collapses the inconsistent VLM / deterministic key naming
  (e.g. ``vendor_name``, ``vendor``, ``supplier`` → ``vendor``) into a single
  canonical camelCase key, so the column picker and CSV always show one column
  per concept regardless of which pipeline extracted the document.
- ``parse_amount``: coerces currency strings like ``"$ 1,200.50"`` or ``"RM
  500"`` to a Python float so the spreadsheet can sort and sum numeric columns.
"""

import re

# ---------------------------------------------------------------------------
# Alias map — raw key → canonical camelCase key
# ---------------------------------------------------------------------------

FIELD_ALIASES: dict[str, str] = {
    # ── Vendor / supplier ──────────────────────────────────────────────────
    "vendor_name": "vendor",
    "supplier": "vendor",
    "company_name": "vendor",
    "seller_name": "vendor",
    "biller": "vendor",
    # ── Invoice / document number ──────────────────────────────────────────
    "invoice_no": "invoiceNumber",
    "invoice_number": "invoiceNumber",
    "doc_number": "invoiceNumber",
    "document_number": "invoiceNumber",
    "receipt_no": "invoiceNumber",
    "receipt_number": "invoiceNumber",
    "reference_number": "invoiceNumber",
    "ref_no": "invoiceNumber",
    # ── Grand total / total amount ─────────────────────────────────────────
    "grand_total": "totalAmount",
    "total_amount": "totalAmount",
    "total": "totalAmount",
    "amount_due": "totalAmount",
    "balance_due": "totalAmount",
    "amount_payable": "totalAmount",
    "net_total": "totalAmount",
    # ── Sub-total ─────────────────────────────────────────────────────────
    "sub_total": "subtotal",
    "subtotal_amount": "subtotal",
    "sub_total_amount": "subtotal",
    # ── Tax ───────────────────────────────────────────────────────────────
    "tax_amount": "tax",
    "gst": "tax",
    "vat": "tax",
    "tax_rate": "taxRate",
    "gst_rate": "taxRate",
    # ── Dates ─────────────────────────────────────────────────────────────
    "invoice_date": "invoiceDate",
    "date": "invoiceDate",
    "document_date": "invoiceDate",
    "receipt_date": "invoiceDate",
    "issue_date": "invoiceDate",
    "due_date": "dueDate",
    "payment_due_date": "dueDate",
    # ── Currency ──────────────────────────────────────────────────────────
    "currency_code": "currency",
    # ── Customer / client ─────────────────────────────────────────────────
    "customer_name": "customerName",
    "client_name": "customerName",
    "bill_to": "customerName",
    "sold_to": "customerName",
    "customer_address": "customerAddress",
    "client_address": "customerAddress",
    "vendor_address": "vendorAddress",
    "supplier_address": "vendorAddress",
    # ── Line items ────────────────────────────────────────────────────────
    "line_items": "lineItems",
    "items": "lineItems",
    "products": "lineItems",
    # ── Document type ─────────────────────────────────────────────────────
    "document_type": "documentType",
    "doc_type": "documentType",
    "type": "documentType",
}

# Columns that are arrays/objects and should not appear as top-level scalar columns.
# They are handled separately (expanded mode) or suppressed (summary mode).
ARRAY_KEYS: frozenset[str] = frozenset({"lineItems", "line_items", "items", "products"})


def normalise_keys(data: dict) -> dict:
    """Remap known aliases to canonical keys. Unknown keys pass through as-is.

    When two raw keys resolve to the same canonical key, the first encountered
    value wins (dict ordering is insertion-ordered in Python 3.7+).
    """
    if not data:
        return {}
    out: dict = {}
    for k, v in data.items():
        canonical = FIELD_ALIASES.get(k, k)
        if canonical not in out:
            out[canonical] = v
    return out


def parse_amount(val: object) -> float | None:
    """Coerce a numeric-looking value to float, stripping currency symbols.

    Handles:
    - ``None`` → ``None``
    - ``int`` / ``float`` → ``float``
    - ``"$ 1,200.50"`` → ``1200.5``
    - ``"RM 250"`` → ``250.0``
    - Anything unrecognisable → ``None``
    """
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return float(val)
    if isinstance(val, str):
        cleaned = re.sub(r"[^\d.]", "", val)
        if not cleaned:
            return None
        try:
            return float(cleaned)
        except ValueError:
            return None
    return None
