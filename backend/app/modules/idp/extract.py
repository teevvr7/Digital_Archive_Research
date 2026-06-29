"""Deterministic field extraction — Tier 2 of the cost cascade.

Keyword-gated, regex + dateparser. No ML, no GPU, no network call — this is
the cheapest tier and the product's economic core. Generic across vendors
(works without a pre-learned template); ``document_templates`` is the future
seam for promoting per-vendor overrides once a layout fingerprint repeats
(self-learning loop, not built yet — this module is fully functional without
it: every document starts on the generic path).

Structured extraction is **type-conditional**: :func:`extract_candidate`
returns ``None`` for anything that doesn't look like an invoice or receipt
(contracts, reports, letters, forms, generic text). Those documents still get
full text/thumbnail/metadata — they just never reach this tier or the VLM
fallback, per the "never call the LLM on the default path" rule.
"""

import re
from dataclasses import dataclass, field
from datetime import date

import dateparser

DOC_TYPE_INVOICE = "invoice"
DOC_TYPE_RECEIPT = "receipt"

_INVOICE_KEYWORDS = (
    "tax invoice", "proforma invoice", "invoice no", "invoice number",
    "invoice #", "invoice#", "invoice", "bill to",
)
_RECEIPT_KEYWORDS = (
    "official receipt", "cash receipt", "payment received", "receipt no",
    "receipt",
)

_CURRENCY_CODES = ("MYR", "USD", "SGD", "EUR", "GBP", "AUD")
# "RM" (Ringgit Malaysia) is checked separately with a word boundary, not as
# a substring symbol — "RM" appears inside ordinary words (e.g. "TERMS").
_CURRENCY_SYMBOLS = {"$": "USD", "€": "EUR", "£": "GBP"}

_AMOUNT_RE = r"[\d][\d,]*\.\d{2}"

_INVOICE_NUM_RE = re.compile(
    r"(?:invoice|inv|receipt)\s*(?:no\.?|number|#)\s*[:\-]?\s*\n?\s*"
    r"([A-Za-z0-9][A-Za-z0-9\-/]{1,19})",
    re.IGNORECASE,
)

# Ordered most- to least-authoritative; the first label that matches wins.
_TOTAL_LABELS = (
    r"balance\s*due",
    r"grand\s*total",
    r"amount\s*due",
    r"total\s*amount",
    r"(?<!sub\s)(?<!sub)total",  # "total" but not "subtotal"/"sub total"
)

_DUE_DATE_LABEL = r"due\s*date"
# Bare "date" must not match as part of "due date"/"duedate" — fixed-width
# negative lookbehinds (Python's re requires fixed width, both qualify here).
_BARE_DATE_LABEL = r"(?<!due\s)(?<!due)\bdate\b"
_INVOICE_DATE_LABELS = (r"invoice\s*date", _BARE_DATE_LABEL)


@dataclass
class LineItem:
    description: str | None = None
    quantity: float | None = None
    unit_price: float | None = None
    amount: float | None = None

    def to_dict(self) -> dict:
        return {
            "description": self.description,
            "quantity": self.quantity,
            "unitPrice": self.unit_price,
            "amount": self.amount,
        }


@dataclass
class ExtractionCandidate:
    document_type: str
    vendor: str | None = None
    invoice_number: str | None = None
    invoice_date: date | None = None
    due_date: date | None = None
    total_amount: float | None = None
    currency: str | None = None
    line_items: list[LineItem] = field(default_factory=list)

    def to_fields(self) -> dict:
        """JSON-serialisable dict for ``documents.extracted_data``."""
        return {
            "vendor": self.vendor,
            "invoiceNumber": self.invoice_number,
            "invoiceDate": self.invoice_date.isoformat() if self.invoice_date else None,
            "dueDate": self.due_date.isoformat() if self.due_date else None,
            "totalAmount": self.total_amount,
            "currency": self.currency,
            "lineItems": [li.to_dict() for li in self.line_items],
        }


def detect_candidate_type(text: str) -> str | None:
    """Keyword gate: does this text look like an invoice or receipt?

    Receipts are checked first since "receipt" documents rarely also say
    "invoice", but some invoices mention "received" in boilerplate — invoice
    keywords are the more specific/common signal so they're checked second
    and win on a tie via the order below.
    """
    low = text.lower()
    has_invoice = any(k in low for k in _INVOICE_KEYWORDS)
    has_receipt = any(k in low for k in _RECEIPT_KEYWORDS)
    if has_invoice:
        return DOC_TYPE_INVOICE
    if has_receipt:
        return DOC_TYPE_RECEIPT
    return None


def _find_invoice_number(text: str) -> str | None:
    m = _INVOICE_NUM_RE.search(text)
    return m.group(1).strip() if m else None


def _find_amount_near_label(text: str, label_pattern: str) -> float | None:
    pattern = re.compile(
        rf"{label_pattern}\s*[:\-]?\s*\n?\s*(?:{'|'.join(_CURRENCY_CODES)}|\$|RM)?\s*({_AMOUNT_RE})",
        re.IGNORECASE,
    )
    m = pattern.search(text)
    if not m:
        return None
    return float(m.group(1).replace(",", ""))


def _find_total_amount(text: str) -> float | None:
    for label in _TOTAL_LABELS:
        amount = _find_amount_near_label(text, label)
        if amount is not None:
            return amount
    return None


def _find_date_near_label(text: str, label_pattern: str) -> date | None:
    pattern = re.compile(
        rf"{label_pattern}\s*[:\-]?\s*\n?\s*([A-Za-z0-9 ,/\-]{{6,24}})",
        re.IGNORECASE,
    )
    m = pattern.search(text)
    if not m:
        return None
    parsed = dateparser.parse(m.group(1).strip(), settings={"STRICT_PARSING": False})
    return parsed.date() if parsed else None


def _find_due_date(text: str) -> date | None:
    return _find_date_near_label(text, _DUE_DATE_LABEL)


def _find_invoice_date(text: str) -> date | None:
    for label in _INVOICE_DATE_LABELS:
        found = _find_date_near_label(text, label)
        if found is not None:
            return found
    return None


def _find_currency(text: str) -> str | None:
    upper = text.upper()
    for code in _CURRENCY_CODES:
        if re.search(rf"\b{code}\b", upper):
            return code
    if re.search(r"\bRM\b", upper):
        return "MYR"
    for symbol, code in _CURRENCY_SYMBOLS.items():
        if symbol in text:
            return code
    return None


# Lines that are structural labels, never a vendor name.
_VENDOR_STOPWORDS = (
    "invoice", "receipt", "bill to", "ship to", "date", "terms",
    "description", "amount", "quantity", "total", "powered by",
)


def _find_vendor(lines: list[str]) -> str | None:
    """Best-effort: the first short, non-label line near the top.

    Text-only extraction has no layout/bbox info, so vendor position varies
    by template (sometimes top-left, sometimes top-right of the page) —
    this is a heuristic, not a guarantee, and is weighted accordingly in
    the gate (never a hard requirement to pass).
    """
    for line in lines[:8]:
        low = line.lower()
        if any(stop in low for stop in _VENDOR_STOPWORDS):
            continue
        if len(line) < 2 or len(line) > 60:
            continue
        if re.fullmatch(r"[\d\s.,\-/]+", line):
            continue
        if line.rstrip().endswith(":"):  # a label line ("Order by:"), not a name
            continue
        return line
    return None


_LINE_ITEM_RE = re.compile(
    r"^(?P<description>.+?)\s+"
    r"(?P<qty>\d+(?:\.\d+)?)\s+"
    r"(?P<price>" + _AMOUNT_RE + r")\s+"
    r"(?P<amount>" + _AMOUNT_RE + r")$"
)

# Fallback for simple receipts/invoices with no separate qty/price column —
# just "description  amount" (qty assumed 1, unit_price == amount).
_LINE_ITEM_SIMPLE_RE = re.compile(
    r"^(?P<description>[A-Za-z][^\d]{2,60}?)\s+(?P<amount>" + _AMOUNT_RE + r")$"
)
_LINE_ITEM_LABEL_WORDS = ("total", "subtotal", "tax", "gst", "sst", "balance", "amount due")


def _find_line_items(lines: list[str]) -> list[LineItem]:
    """Regex-anchored row detection for simple, single-column item tables.

    Only catches the common "description [qty price] amount" single-line
    layout (the OCR/text-layer reading order for most simple invoices and
    receipts). Multi-column tables that PyMuPDF/OCR break into separate
    per-cell lines are NOT reconstructed here — that's Tier 3 (table
    structure models) territory; this tier intentionally stays cheap.
    """
    items: list[LineItem] = []
    for line in lines:
        m = _LINE_ITEM_RE.match(line)
        if m:
            items.append(LineItem(
                description=m.group("description").strip(),
                quantity=float(m.group("qty")),
                unit_price=float(m.group("price")),
                amount=float(m.group("amount")),
            ))
            continue

        m = _LINE_ITEM_SIMPLE_RE.match(line)
        if m and not any(w in m.group("description").lower() for w in _LINE_ITEM_LABEL_WORDS):
            amount = float(m.group("amount"))
            items.append(LineItem(
                description=m.group("description").strip(),
                quantity=1.0,
                unit_price=amount,
                amount=amount,
            ))
    return items


def extract_candidate(text: str) -> ExtractionCandidate | None:
    """Run the full deterministic extraction. ``None`` if not a candidate type."""
    if not text or not text.strip():
        return None

    doc_type = detect_candidate_type(text)
    if doc_type is None:
        return None

    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]

    return ExtractionCandidate(
        document_type=doc_type,
        vendor=_find_vendor(lines),
        invoice_number=_find_invoice_number(text),
        invoice_date=_find_invoice_date(text),
        due_date=_find_due_date(text),
        total_amount=_find_total_amount(text),
        currency=_find_currency(text),
        line_items=_find_line_items(lines),
    )
