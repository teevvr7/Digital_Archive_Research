"""Spreadsheet Center — API endpoints.

Three routes all under the ``/export`` prefix:

GET  /export/meta              → doc types + templates for filter dropdowns
POST /export/fields            → available column names for the selected filters
POST /export/spreadsheet       → preview JSON or downloadable CSV
"""

import csv
import datetime
import io
import json
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.core.camel import CamelModel
from app.core.deps import get_tenant_db
from app.core.security import TokenData
from app.modules.export import service

router = APIRouter(prefix="/export", tags=["Spreadsheet Export"])

_DbCtx = Annotated[tuple[Session, TokenData], Depends(get_tenant_db)]


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
    "/meta",
    summary="Dropdown data for Spreadsheet Center filters",
)
def get_export_meta(ctx: _DbCtx) -> dict:
    """Return available document types (with counts) and promoted templates."""
    db, user = ctx
    return service.get_export_meta(db, uuid.UUID(user.tenant_id))


@router.post(
    "/fields",
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
    "/spreadsheet",
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
