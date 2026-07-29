"""Export module router.

Two independent feature sets share this module (kept side by side — neither
replaces the other):

- CSV/XLSX export + zip bulk-download of originals, under ``/documents/...``
  (the original export feature).
- Spreadsheet Center, under ``/export/...``: a column-picker / preview /
  streaming-CSV builder over ``extracted_data``.

GET  /documents/export           → CSV/XLSX export of filtered documents
POST /documents/bulk-download    → zip of selected documents' originals
GET  /export/meta                → doc types + templates for filter dropdowns
POST /export/fields              → available column names for the selected filters
POST /export/spreadsheet         → preview JSON or downloadable CSV
"""

import csv
import datetime
import io
import json
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response, StreamingResponse
from sqlalchemy.orm import Session

from app.core.camel import CamelModel
from app.core.deps import get_tenant_db
from app.core.security import TokenData
from app.modules.export import service
from app.modules.export.schemas import BulkDownloadIn

router = APIRouter(tags=["export"])

_DbCtx = Annotated[tuple[Session, TokenData], Depends(get_tenant_db)]


# ---------------------------------------------------------------------------
# CSV/XLSX export + zip bulk-download
# ---------------------------------------------------------------------------


@router.get(
    "/documents/export",
    summary="Export filtered documents as CSV or XLSX",
)
def export_documents(
    ctx: _DbCtx,
    format: Annotated[str, Query()] = "csv",
    status_q: Annotated[str | None, Query(alias="status")] = None,
    type_q: Annotated[str | None, Query(alias="type")] = None,
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
) -> Response:
    db, _ = ctx
    content, media_type, filename, truncated = service.export_documents(
        db,
        fmt=format,
        status_filter=status_q,
        type_filter=type_q,
        tag_id=tag_id,
        correspondent_id=correspondent_id,
        date_from=date_from,
        date_to=date_to,
        amount_min=amount_min,
        amount_max=amount_max,
        vendor=vendor,
        inbox=inbox,
        q=q,
        custom_field_id=custom_field_id,
        custom_field_value=custom_field_value,
        custom_field_min=custom_field_min,
        custom_field_max=custom_field_max,
        custom_field_date_from=custom_field_date_from,
        custom_field_date_to=custom_field_date_to,
    )
    headers = {
        "Content-Disposition": f'attachment; filename="{filename}"',
        "X-Export-Truncated": "true" if truncated else "false",
    }
    return Response(content=content, media_type=media_type, headers=headers)


@router.post(
    "/documents/bulk-download",
    summary="Download selected documents as a zip archive",
)
def bulk_download(ctx: _DbCtx, body: BulkDownloadIn) -> Response:
    db, _ = ctx
    content = service.bulk_download_zip(db, body.document_ids)
    today = datetime.date.today().isoformat()
    headers = {"Content-Disposition": f'attachment; filename="documents-{today}.zip"'}
    return Response(content=content, media_type="application/zip", headers=headers)


# ---------------------------------------------------------------------------
# Spreadsheet Center
# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------


class ExportFilters(CamelModel):
    """Shared filter body used by both /fields and /spreadsheet.

    Inherits from CamelModel so that frontend camelCase requests map automatically
    to Pythonic snake_case attributes, with automatic type parsing for UUIDs and dates.
    """

    document_type: str | None = None
    template_id: uuid.UUID | None = None
    status: str | None = None
    date_from: datetime.date | None = None
    date_to: datetime.date | None = None


class SpreadsheetRequest(ExportFilters):
    """Request body for /export/spreadsheet."""

    columns: list[str] = []
    mode: str = "summary"  # "summary" | "expanded"


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/export/meta",
    summary="Dropdown data for Spreadsheet Center filters",
)
def get_export_meta(ctx: _DbCtx) -> dict:
    """Return available document types (with counts) and promoted templates."""
    db, user = ctx
    return service.get_export_meta(db, uuid.UUID(user.tenant_id))


@router.post(
    "/export/fields",
    summary="Discover available column names for the selected filters",
)
def get_export_fields(body: ExportFilters, ctx: _DbCtx) -> list[str]:
    """Return distinct canonical column names found in extracted_data for the given filters.

    The columns are loaded from defined schemas (template mapping or type schemas)
    and unioned with database keys.
    """
    db, user = ctx
    return service.discover_fields(
        db,
        uuid.UUID(user.tenant_id),
        doc_type=body.document_type,
        template_id=body.template_id,
        status=body.status,
        date_from=body.date_from,
        date_to=body.date_to,
    )


@router.post(
    "/export/spreadsheet",
    summary="Build spreadsheet data — preview (JSON) or download (CSV)",
)
def export_spreadsheet(
    body: SpreadsheetRequest,
    ctx: _DbCtx,
    format: Annotated[str, Query(description="'preview' returns JSON; 'csv' returns a downloadable file")] = "preview",
) -> Any:
    """Build the spreadsheet rows and return them as JSON (preview) or CSV (download).

    - ``?format=preview`` (default) → ``{ rows: [...], total: N }``
    - ``?format=csv`` → streaming ``text/csv`` attachment
    """
    db, user = ctx

    if format not in ("preview", "csv"):
        raise HTTPException(status_code=400, detail="format must be 'preview' or 'csv'")

    if body.mode not in ("summary", "expanded"):
        raise HTTPException(status_code=400, detail="mode must be 'summary' or 'expanded'")

    rows = service.build_spreadsheet(
        db,
        uuid.UUID(user.tenant_id),
        doc_type=body.document_type,
        template_id=body.template_id,
        status=body.status,
        date_from=body.date_from,
        date_to=body.date_to,
        columns=body.columns,
        mode=body.mode,
    )

    if format == "csv":
        output = io.StringIO()
        if rows:
            # Collect all unique keys across all rows to handle sparse columns
            all_keys: list[str] = []
            seen_keys: set[str] = set()
            for row in rows:
                for k in row:
                    if k not in seen_keys:
                        seen_keys.add(k)
                        all_keys.append(k)

            writer = csv.DictWriter(output, fieldnames=all_keys, extrasaction="ignore")
            writer.writeheader()
            for row in rows:
                row_out = {}
                for k in all_keys:
                    val = row.get(k)
                    if val is None:
                        row_out[k] = ""
                    elif isinstance(val, (dict, list)):
                        # Serialize complex sub-structures to valid JSON strings in the cell
                        row_out[k] = json.dumps(val)
                    else:
                        row_out[k] = str(val)
                writer.writerow(row_out)

        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=export.csv"},
        )

    # JSON preview
    return {"rows": rows, "total": len(rows)}
