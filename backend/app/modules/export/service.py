"""Spreadsheet Center — business logic.

Three public functions consumed by the router:

- ``get_export_meta``: returns available document types and templates so the
  frontend can populate filter dropdowns.
- ``discover_fields``: given a set of filters, returns the distinct canonical
  column names present in ``extracted_data`` for matching documents.
- ``build_spreadsheet``: returns the actual rows (``list[dict]``) ready for CSV
  serialisation or JSON preview, applying normalisation and optional line-item
  expansion.
"""

import uuid
import datetime
from typing import Any

from sqlalchemy import func, select, cast, Date
from sqlalchemy.orm import Session

from app.models.document import Document
from app.models.document_type import DocumentType
from app.models.document_template import DocumentTemplate, TEMPLATE_PROMOTED
from app.modules.idp.config_router import split_schema_payload
from app.modules.export.normalise import (
    ARRAY_KEYS,
    FIELD_ALIASES,
    normalise_keys,
    parse_amount,
)

# ---------------------------------------------------------------------------
# Meta endpoint helper
# ---------------------------------------------------------------------------



def get_export_meta(db: Session, tenant_id: uuid.UUID) -> dict:
    """Return doc-type names (with doc counts) and templates for filter dropdowns."""
    tenant_uuid = tenant_id

    # Document types available to this tenant (system + tenant-owned)
    doc_types_q = db.query(DocumentType).filter(
        (DocumentType.tenant_id == tenant_uuid) | (DocumentType.tenant_id.is_(None))
    ).all()

    # Count documents per doc_type string for UI display
    count_rows = db.execute(
        select(Document.document_type, func.count(Document.id))
        .where(
            Document.tenant_id == tenant_uuid,
            Document.deleted_at.is_(None),
            Document.extracted_data.is_not(None),
        )
        .group_by(Document.document_type)
    ).all()
    count_map = {row[0]: row[1] for row in count_rows}

    doc_types_out = []
    for dt in doc_types_q:
        doc_types_out.append({
            "name": dt.name,
            "count": count_map.get(dt.name, 0),
        })

    # Add the raw document_type enum values that exist in the DB
    # (some docs may have a type not in the document_types catalog)
    existing_types = set(row[0] for row in count_rows)
    catalog_names = {dt.name for dt in doc_types_q}
    for extra_type in existing_types - catalog_names:
        doc_types_out.append({
            "name": extra_type,
            "count": count_map.get(extra_type, 0),
        })

    # Promoted templates for this tenant
    templates_q = db.query(DocumentTemplate, DocumentType).join(
        DocumentType, DocumentType.id == DocumentTemplate.document_type_id
    ).filter(
        DocumentTemplate.tenant_id == tenant_uuid,
        DocumentTemplate.status == TEMPLATE_PROMOTED,
    ).all()

    templates_out = [
        {
            "id": str(tpl.id),
            "name": tpl.name,
            "documentType": dt.name,
        }
        for tpl, dt in templates_q
    ]

    return {
        "documentTypes": doc_types_out,
        "templates": templates_out,
    }


# ---------------------------------------------------------------------------
# Field discovery
# ---------------------------------------------------------------------------


def discover_fields(
    db: Session,
    tenant_id: uuid.UUID,
    *,
    doc_type: str | None = None,
    template_id: uuid.UUID | None = None,
    status: str | None = None,
    date_from: datetime.date | None = None,
    date_to: datetime.date | None = None,
) -> list[str]:
    """Return distinct canonical column names present in matching documents or defined schemas.

    If a template is selected, we parse its field mappings.
    If a document type is selected, we parse its json_schema or active template mappings.
    These schema keys are unioned with the actual keys found in the database.
    """
    schema_keys: set[str] = set()

    if template_id:
        tpl = db.get(DocumentTemplate, template_id)
        if tpl and tpl.tenant_id == tenant_id:
            clean_schema, _, _ = split_schema_payload(tpl.field_mappings)
            if clean_schema:
                schema_keys.update(clean_schema.keys())
    elif doc_type:
        # Find active promoted template for this doc type
        tpl = db.query(DocumentTemplate).join(
            DocumentType, DocumentType.id == DocumentTemplate.document_type_id
        ).filter(
            DocumentTemplate.tenant_id == tenant_id,
            DocumentType.name == doc_type,
            DocumentTemplate.status == TEMPLATE_PROMOTED,
        ).first()
        if tpl:
            clean_schema, _, _ = split_schema_payload(tpl.field_mappings)
            if clean_schema:
                schema_keys.update(clean_schema.keys())
        else:
            # Fallback to doc type json_schema
            dt = db.query(DocumentType).filter(
                (DocumentType.tenant_id == tenant_id) | (DocumentType.tenant_id.is_(None)),
                DocumentType.name == doc_type
            ).first()
            if dt and dt.json_schema:
                clean_schema, _, _ = split_schema_payload(dt.json_schema)
                if clean_schema:
                    schema_keys.update(clean_schema.keys())

    # Always fetch existing keys in DB documents matching the filters to handle custom user edits/VLM discrepancies
    stmt = select(func.distinct(func.jsonb_object_keys(Document.extracted_data))).where(
        Document.tenant_id == tenant_id,
        Document.extracted_data.is_not(None),
        Document.deleted_at.is_(None),
    )
    stmt = _apply_filters(stmt, doc_type=doc_type, template_id=template_id, status=status, date_from=date_from, date_to=date_to)

    db_keys = db.scalars(stmt).all()

    # Union schema keys and existing db keys
    all_raw_keys = schema_keys.union(db_keys)

    # Normalise and deduplicate
    seen: set[str] = set()
    canonical: list[str] = []
    for k in all_raw_keys:
        c = FIELD_ALIASES.get(k, k)
        # Skip raw array keys — they are presented as special modes, not columns
        if c in ARRAY_KEYS:
            continue
        if c not in seen:
            seen.add(c)
            canonical.append(c)

    return sorted(canonical)



# ---------------------------------------------------------------------------
# Spreadsheet builder
# ---------------------------------------------------------------------------


def build_spreadsheet(
    db: Session,
    tenant_id: uuid.UUID,
    *,
    doc_type: str | None = None,
    template_id: uuid.UUID | None = None,
    status: str | None = None,
    date_from: datetime.date | None = None,
    date_to: datetime.date | None = None,
    columns: list[str],
    mode: str = "summary",
) -> list[dict[str, Any]]:
    """Return rows ready for CSV or JSON preview.

    ``mode="summary"`` → 1 row per document, lineItems collapsed to a count.
    ``mode="expanded"`` → 1 row per line item; document header fields repeat.
    """
    stmt = select(Document).where(
        Document.tenant_id == tenant_id,
        Document.deleted_at.is_(None),
        Document.extracted_data.is_not(None),
    )
    stmt = _apply_filters(stmt, doc_type=doc_type, template_id=template_id, status=status, date_from=date_from, date_to=date_to)
    stmt = stmt.order_by(Document.uploaded_at.desc())

    docs = db.scalars(stmt).all()

    all_rows: list[dict[str, Any]] = []
    for doc in docs:
        normalised = normalise_keys(doc.extracted_data or {})
        if mode == "expanded":
            rows = _expand_rows(doc, normalised, columns)
        else:
            rows = [_summary_row(doc, normalised, columns)]
        all_rows.extend(rows)

    return all_rows


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _apply_filters(stmt, *, doc_type, template_id, status, date_from, date_to):
    if doc_type:
        stmt = stmt.where(Document.document_type == doc_type)
    if template_id:
        stmt = stmt.where(Document.template_id == template_id)
    if status:
        stmt = stmt.where(Document.status == status)
    if date_from is not None:
        stmt = stmt.where(func.cast(Document.uploaded_at, Date) >= date_from)
    if date_to is not None:
        stmt = stmt.where(func.cast(Document.uploaded_at, Date) <= date_to)
    return stmt


def _base_doc_fields(doc: Document, normalised: dict, columns: list[str]) -> dict[str, Any]:
    """Build the document-level portion of a row — metadata + selected scalar columns."""
    row: dict[str, Any] = {
        "filename": doc.original_filename,
        "documentType": doc.document_type,
        "status": doc.status,
        "uploadedAt": doc.uploaded_at.strftime("%Y-%m-%d") if doc.uploaded_at else None,
        "documentDate": doc.document_date.isoformat() if doc.document_date else None,
    }
    for col in columns:
        if col in ("filename", "documentType", "status", "uploadedAt", "documentDate"):
            continue
        val = normalised.get(col)
        # Coerce amounts for numeric-looking canonical keys
        if col in {"totalAmount", "subtotal", "tax", "discount"} and val is not None:
            val = parse_amount(val)
        row[col] = val
    return row


def _summary_row(doc: Document, normalised: dict, columns: list[str]) -> dict[str, Any]:
    row = _base_doc_fields(doc, normalised, columns)
    line_items = normalised.get("lineItems") or []
    if isinstance(line_items, list):
        row["itemCount"] = len(line_items)
    return row


def _expand_rows(doc: Document, normalised: dict, columns: list[str]) -> list[dict[str, Any]]:
    """1 row per line item; doc header fields repeat. Sub-items get depth=1."""
    base = _base_doc_fields(doc, normalised, columns)
    line_items = normalised.get("lineItems") or []
    if not isinstance(line_items, list) or not line_items:
        # No items — still emit one doc row with blank item columns
        base.update({"itemDescription": None, "itemQuantity": None, "itemUnitPrice": None, "itemAmount": None, "depth": 0})
        return [base]

    rows: list[dict[str, Any]] = []
    for item in line_items:
        if not isinstance(item, dict):
            continue
        parent_row = {**base}
        parent_row["depth"] = 0
        # Resolve parent item fields — handle both flat and parent_item_ prefixed keys
        parent_row["itemDescription"] = (
            item.get("description")
            or item.get("parent_item_description")
            or item.get("item_description")
            or item.get("name")
        )
        parent_row["itemQuantity"] = (
            item.get("quantity")
            or item.get("parent_quantity")
            or item.get("qty")
        )
        parent_row["itemUnitPrice"] = parse_amount(
            item.get("unit_price")
            or item.get("parent_unit_price")
            or item.get("unitPrice")
        )
        parent_row["itemAmount"] = parse_amount(
            item.get("amount")
            or item.get("parent_total_amount")
            or item.get("total_amount")
            or item.get("totalAmount")
        )
        rows.append(parent_row)

        # Sub-items (depth=1)
        sub_items = item.get("sub_items") or item.get("subItems") or []
        for sub in sub_items:
            if not isinstance(sub, dict):
                continue
            sub_row = {**base}
            sub_row["depth"] = 1
            sub_row["itemDescription"] = (
                sub.get("sub_item_description")
                or sub.get("description")
                or sub.get("name")
            )
            sub_row["itemQuantity"] = sub.get("sub_quantity") or sub.get("quantity")
            sub_row["itemUnitPrice"] = parse_amount(sub.get("sub_unit_price") or sub.get("unit_price"))
            sub_row["itemAmount"] = parse_amount(sub.get("sub_total_amount") or sub.get("amount"))
            rows.append(sub_row)

    return rows
