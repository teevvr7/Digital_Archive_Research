"""Export module — business logic for two independent feature sets.

1. CSV/XLSX of a filtered document set, and zip bulk-download of selected
   originals. Row export reuses ``files.service.build_document_query`` so the
   export never drifts from what the Documents page filter bar actually
   matches. Capped at ``_EXPORT_ROW_LIMIT`` rows — flagged via a response
   header, never silently truncated (see export/router.py).
2. Spreadsheet Center — three public functions consumed by the router:
   ``get_export_meta`` (doc types + templates for filter dropdowns),
   ``discover_fields`` (distinct canonical column names present in
   ``extracted_data`` for matching documents), ``build_spreadsheet`` (the
   actual rows, normalised, ready for CSV serialisation or JSON preview).
"""

import csv
import datetime
import io
import uuid
import zipfile
from typing import Any

from fastapi import HTTPException, status
from openpyxl import Workbook
from sqlalchemy import Date, cast, func, select
from sqlalchemy.orm import Session

from app.core import storage as object_storage
from app.models.document import Document
from app.models.document_template import TEMPLATE_PROMOTED, DocumentTemplate
from app.models.document_type import DocumentType
from app.modules.export.normalise import (
    ARRAY_KEYS,
    FIELD_ALIASES,
    normalise_keys,
    parse_amount,
)
from app.modules.files.service import build_document_query, resolve_custom_field_type
from app.modules.idp.config_router import split_schema_payload

_EXPORT_ROW_LIMIT = 5000
# Zip bulk-download is synchronous in the request handler (CLAUDE.md: keep
# handlers fast) — capped modestly so one request never takes more than a
# few seconds. A true background export would be a separate job-queue
# feature; out of scope here.
_MAX_BULK_DOWNLOAD = 100

_COLUMNS = [
    "Title",
    "Vendor",
    "Invoice No",
    "Total Amount",
    "Currency",
    "Document Type",
    "Status",
    "Document Date",
    "Uploaded At",
]


def _row_for(doc: Document) -> list[str]:
    return [
        doc.title or doc.original_filename,
        doc.vendor or "",
        doc.invoice_no or "",
        f"{doc.total_amount:.2f}" if doc.total_amount is not None else "",
        doc.currency or "",
        doc.document_type,
        doc.status,
        doc.document_date.isoformat() if doc.document_date else "",
        doc.uploaded_at.isoformat() if doc.uploaded_at else "",
    ]


def export_documents(
    db: Session,
    *,
    fmt: str,
    status_filter: str | None = None,
    type_filter: str | None = None,
    tag_id: uuid.UUID | None = None,
    correspondent_id: uuid.UUID | None = None,
    date_from: datetime.date | None = None,
    date_to: datetime.date | None = None,
    amount_min: float | None = None,
    amount_max: float | None = None,
    vendor: str | None = None,
    inbox: bool = False,
    q: str | None = None,
    custom_field_id: uuid.UUID | None = None,
    custom_field_value: str | None = None,
    custom_field_min: float | None = None,
    custom_field_max: float | None = None,
    custom_field_date_from: datetime.date | None = None,
    custom_field_date_to: datetime.date | None = None,
) -> tuple[bytes, str, str, bool]:
    """Returns ``(content, media_type, filename, truncated)``. ``fmt`` is
    ``"csv"`` or ``"xlsx"``; anything else raises 400."""
    if fmt not in ("csv", "xlsx"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="format must be 'csv' or 'xlsx'.",
        )

    stmt, _ = build_document_query(
        status_filter=status_filter,
        type_filter=type_filter,
        tag_id=tag_id,
        correspondent_id=correspondent_id,
        date_from=date_from,
        date_to=date_to,
        amount_min=amount_min,
        amount_max=amount_max,
        vendor=vendor,
        inbox=inbox,
        q=q,
        trashed=False,
        custom_field_id=custom_field_id,
        custom_field_type=resolve_custom_field_type(db, custom_field_id),
        custom_field_value=custom_field_value,
        custom_field_min=custom_field_min,
        custom_field_max=custom_field_max,
        custom_field_date_from=custom_field_date_from,
        custom_field_date_to=custom_field_date_to,
    )
    stmt = stmt.order_by(Document.uploaded_at.desc())

    # Fetch one extra row to detect truncation without a separate COUNT query.
    rows = db.scalars(stmt.limit(_EXPORT_ROW_LIMIT + 1)).all()
    truncated = len(rows) > _EXPORT_ROW_LIMIT
    rows = rows[:_EXPORT_ROW_LIMIT]

    today = datetime.date.today().isoformat()
    if fmt == "csv":
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(_COLUMNS)
        for doc in rows:
            writer.writerow(_row_for(doc))
        return (
            buffer.getvalue().encode("utf-8-sig"),  # BOM so Excel opens UTF-8 cleanly
            "text/csv",
            f"documents-{today}.csv",
            truncated,
        )

    wb = Workbook()
    ws = wb.active
    ws.title = "Documents"
    ws.append(_COLUMNS)
    for doc in rows:
        ws.append(_row_for(doc))
    out = io.BytesIO()
    wb.save(out)
    return (
        out.getvalue(),
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        f"documents-{today}.xlsx",
        truncated,
    )


def bulk_download_zip(db: Session, document_ids: list[uuid.UUID]) -> bytes:
    """Zip the original files for the given documents. Skips any single file
    that fails to download rather than aborting the whole archive."""
    if not document_ids:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No documents selected.")
    if len(document_ids) > _MAX_BULK_DOWNLOAD:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Too many files ({len(document_ids)}). Download at most {_MAX_BULK_DOWNLOAD} at a time.",
        )

    docs = db.scalars(
        select(Document).where(
            Document.id.in_(document_ids),
            Document.deleted_at.is_(None),
        )
    ).all()

    buffer = io.BytesIO()
    seen_names: dict[str, int] = {}
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for doc in docs:
            name = doc.original_filename or f"{doc.id}"
            if name in seen_names:
                seen_names[name] += 1
                stem, _, ext = name.rpartition(".")
                name = f"{stem or name} ({seen_names[name]}).{ext}" if ext else f"{name} ({seen_names[name]})"
            else:
                seen_names[name] = 0

            try:
                data = object_storage.download_file(doc.storage_key)
            except Exception:
                continue
            zf.writestr(name, data)

    buffer.seek(0)
    return buffer.getvalue()


# ---------------------------------------------------------------------------
# Spreadsheet Center
# ---------------------------------------------------------------------------
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
