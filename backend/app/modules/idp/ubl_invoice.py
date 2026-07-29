"""MyInvois UBL 2.1 XML Invoice Parser.

Parses OASIS Universal Business Language (UBL) 2.1 Invoice XML files
as specified by the Malaysian Inland Revenue Board (LHDN) MyInvois SDK.

Extracts top-level header fields and detailed line-item arrays into a standard
dict structure compatible with ``extracted_data``.
"""

import logging

from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


def parse_ubl_invoice(xml_bytes: bytes) -> dict:
    """Parse UBL 2.1 XML byte stream into a structured metadata dictionary."""
    soup = BeautifulSoup(xml_bytes, "xml")

    def _text(tag_name: str) -> str | None:
        tag = soup.find(tag_name)
        return tag.text.strip() if tag and tag.text else None

    def _float(tag_name: str) -> float | None:
        val = _text(tag_name)
        if val:
            try:
                return float(val)
            except ValueError:
                pass
        return None

    # Header fields
    invoice_number = _text("cbc:ID") or _text("ID")
    invoice_date = _text("cbc:IssueDate") or _text("IssueDate")
    currency = _text("cbc:DocumentCurrencyCode") or _text("DocumentCurrencyCode") or "MYR"

    # Supplier / Vendor
    supplier = soup.find("cac:AccountingSupplierParty") or soup.find("AccountingSupplierParty")
    supplier_name = None
    if supplier:
        name_tag = supplier.find("cbc:RegistrationName") or supplier.find("cbc:Name") or supplier.find("Name")
        if name_tag:
            supplier_name = name_tag.text.strip()

    # Customer / Buyer
    customer = soup.find("cac:AccountingCustomerParty") or soup.find("AccountingCustomerParty")
    customer_name = None
    if customer:
        name_tag = customer.find("cbc:RegistrationName") or customer.find("cbc:Name") or customer.find("Name")
        if name_tag:
            customer_name = name_tag.text.strip()

    # Totals
    tax_exclusive = _float("cbc:TaxExclusiveAmount")
    tax_inclusive = _float("cbc:TaxInclusiveAmount")
    payable_amount = _float("cbc:PayableAmount")
    tax_amount = _float("cbc:TaxAmount")

    total_amount = payable_amount or tax_inclusive or tax_exclusive

    # Line items
    line_items = []
    lines = soup.find_all("cac:InvoiceLine") or soup.find_all("InvoiceLine")
    for line in lines:
        item_id = None
        id_tag = line.find("cbc:ID")
        if id_tag:
            item_id = id_tag.text.strip()

        qty = None
        qty_tag = line.find("cbc:InvoicedQuantity")
        if qty_tag and qty_tag.text:
            try:
                qty = float(qty_tag.text.strip())
            except ValueError:
                pass

        amount = None
        amt_tag = line.find("cbc:LineExtensionAmount")
        if amt_tag and amt_tag.text:
            try:
                amount = float(amt_tag.text.strip())
            except ValueError:
                pass

        desc = None
        item_tag = line.find("cac:Item")
        if item_tag:
            name_tag = item_tag.find("cbc:Name") or item_tag.find("cbc:Description")
            if name_tag:
                desc = name_tag.text.strip()

        unit_price = None
        price_tag = line.find("cac:Price")
        if price_tag:
            amt_tag = price_tag.find("cbc:PriceAmount")
            if amt_tag and amt_tag.text:
                try:
                    unit_price = float(amt_tag.text.strip())
                except ValueError:
                    pass

        line_items.append({
            "item_id": item_id,
            "description": desc or f"Line item {len(line_items) + 1}",
            "quantity": qty,
            "unit_price": unit_price,
            "amount": amount,
        })

    result = {
        "invoice_number": invoice_number,
        "invoice_date": invoice_date,
        "vendor_name": supplier_name,
        "buyer_name": customer_name,
        "currency": currency,
        "total_amount": total_amount,
        "tax_amount": tax_amount,
        "line_items": line_items,
    }

    return result
