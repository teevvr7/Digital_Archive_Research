"""Export module router — CSV/XLSX export and zip bulk-download."""

import datetime
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.core.deps import get_tenant_db
from app.core.security import TokenData
from app.modules.export import service
from app.modules.export.schemas import BulkDownloadIn

router = APIRouter(tags=["export"])

_DbCtx = Annotated[tuple[Session, TokenData], Depends(get_tenant_db)]


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
