"""MyInvois / UBL 2.1 Invoice parser — Tier 2 deterministic extraction, no regex.

Malaysia's e-invoicing format (LHDN MyInvois) is UBL 2.1 XML — already fully
structured data, so this bypasses ``extract.py``'s regex entirely and builds
an :class:`ExtractionCandidate` directly from the XML tree. It feeds into the
exact same ``gate.score_extraction()`` / accept path as every other
deterministic source (see ``idp/jobs.py``) — this is not a parallel pipeline,
just a second way to produce the same candidate shape.

Only the standard UBL 2.1 namespaces/element names are targeted (``Invoice``
root, ``cac:AccountingSupplierParty``, ``cac:LegalMonetaryTotal``,
``cac:InvoiceLine``, ...). MyInvois-specific extensions (e.g. the LHDN
validation UUID/QR code, stored under ``cac:AdditionalDocumentReference`` in
the real MyInvois profile) are not read yet — a genuine follow-up once real
MyInvois sample files are available to verify exact field paths against, not
guessed at here. This is deliberately the "small first slice."
"""

import logging
import xml.etree.ElementTree as ET
from datetime import date

from app.modules.idp.extract import DOC_TYPE_INVOICE, ExtractionCandidate, LineItem

logger = logging.getLogger(__name__)

_NS = {
    "cbc": "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2",
    "cac": "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2",
}
_INVOICE_ROOT_TAG = "{urn:oasis:names:specification:ubl:schema:xsd:Invoice-2}Invoice"

# Cheap, effective mitigation for XXE/billion-laughs on untrusted uploads
# without adding a dependency (stdlib ElementTree is not hardened against
# these by default) — legitimate UBL invoices never declare a DTD/entity, so
# rejecting anything that does costs nothing real.
_UNSAFE_XML_MARKERS = (b"<!DOCTYPE", b"<!ENTITY")


def _looks_safe(data: bytes) -> bool:
    head = data[:4096]
    return not any(marker in head for marker in _UNSAFE_XML_MARKERS)


def is_ubl_invoice(data: bytes) -> bool:
    """Cheap, safe check: is this a well-formed UBL 2.1 Invoice document?"""
    if not _looks_safe(data):
        return False
    try:
        root = ET.fromstring(data)
    except ET.ParseError:
        return False
    return root.tag == _INVOICE_ROOT_TAG


def _text(el: ET.Element | None) -> str | None:
    if el is None or el.text is None:
        return None
    stripped = el.text.strip()
    return stripped or None


def _amount(el: ET.Element | None) -> float | None:
    raw = _text(el)
    if raw is None:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def _iso_date(el: ET.Element | None) -> date | None:
    raw = _text(el)
    if raw is None:
        return None
    try:
        return date.fromisoformat(raw[:10])
    except ValueError:
        return None


def _vendor_name(root: ET.Element) -> str | None:
    party = root.find("cac:AccountingSupplierParty/cac:Party", _NS)
    if party is None:
        return None
    name = _text(party.find("cac:PartyLegalEntity/cbc:RegistrationName", _NS))
    if name:
        return name
    return _text(party.find("cac:PartyName/cbc:Name", _NS))


def _line_items(root: ET.Element) -> list[LineItem]:
    items: list[LineItem] = []
    for line in root.findall("cac:InvoiceLine", _NS):
        items.append(
            LineItem(
                description=_text(line.find("cac:Item/cbc:Name", _NS)),
                quantity=_amount(line.find("cbc:InvoicedQuantity", _NS)),
                unit_price=_amount(line.find("cac:Price/cbc:PriceAmount", _NS)),
                amount=_amount(line.find("cbc:LineExtensionAmount", _NS)),
            )
        )
    return items


def parse_ubl_invoice(data: bytes) -> ExtractionCandidate | None:
    """Build an :class:`ExtractionCandidate` directly from UBL XML — no regex.

    Returns ``None`` (never raises) if the document isn't a well-formed UBL
    Invoice, matching ``extract.extract_candidate()``'s "no candidate"
    contract so callers (``idp/jobs.py``) don't need a separate code path.
    """
    if not _looks_safe(data):
        logger.warning("Rejected XML with DOCTYPE/ENTITY declaration (XXE guard)")
        return None
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        logger.warning("UBL invoice parse failed: %s", exc)
        return None
    if root.tag != _INVOICE_ROOT_TAG:
        return None

    return ExtractionCandidate(
        document_type=DOC_TYPE_INVOICE,
        vendor=_vendor_name(root),
        invoice_number=_text(root.find("cbc:ID", _NS)),
        invoice_date=_iso_date(root.find("cbc:IssueDate", _NS)),
        due_date=_iso_date(root.find("cbc:DueDate", _NS)),
        total_amount=_amount(root.find("cac:LegalMonetaryTotal/cbc:PayableAmount", _NS)),
        currency=_text(root.find("cbc:DocumentCurrencyCode", _NS)),
        line_items=_line_items(root),
    )


def extract_ubl_text(data: bytes) -> str:
    """Flatten every text node in the XML for full-text search.

    Broader than the structured fields alone — also captures addresses, tax
    breakdowns, remarks, etc. that ``parse_ubl_invoice`` doesn't map into
    ``ExtractionCandidate``. Returns "" (never raises) on malformed XML.
    """
    if not _looks_safe(data):
        return ""
    try:
        root = ET.fromstring(data)
    except ET.ParseError:
        return ""
    return " ".join(t.strip() for t in root.itertext() if t and t.strip())
