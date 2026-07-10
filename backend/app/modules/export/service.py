"""Export module — CSV/XLSX of a filtered document set, and zip bulk-download
of selected originals.

Row export reuses ``files.service.build_document_query`` so the export never
drifts from what the Documents page filter bar actually matches. Capped at
``_EXPORT_ROW_LIMIT`` rows — flagged via a response header, never silently
truncated (see export/router.py).
"""

import csv
import datetime
import io
import uuid
import zipfile

from fastapi import HTTPException, status
from openpyxl import Workbook
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import storage as object_storage
from app.models.document import Document
from app.modules.files.service import build_document_query

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
