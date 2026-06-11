"""Search module router — full-text content + fuzzy filename search."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.deps import get_tenant_db
from app.core.security import TokenData
from app.modules.search import service
from app.modules.search.schemas import SearchListOut

router = APIRouter(tags=["search"])

_DbCtx = Annotated[tuple[Session, TokenData], Depends(get_tenant_db)]


@router.get(
    "/search",
    response_model=SearchListOut,
    response_model_by_alias=True,
    summary="Full-text content + fuzzy filename search",
)
def search(
    ctx: _DbCtx,
    q: Annotated[str | None, Query(description="Search terms")] = None,
    type_q: Annotated[str | None, Query(alias="type")] = None,
    date_q: Annotated[str | None, Query(alias="date")] = None,
    status_q: Annotated[str | None, Query(alias="status")] = None,
    page: int = 1,
) -> SearchListOut:
    db, _ = ctx
    return service.search_documents(
        db,
        q=q,
        type_filter=type_q,
        date_filter=date_q,
        status_filter=status_q,
        page=max(1, page),
    )
