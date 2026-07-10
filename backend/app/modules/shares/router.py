"""Shares module router.

Two routers: ``router`` (authenticated, tenant-scoped create/list/revoke)
and ``public_router`` (the one deliberately unauthenticated resolve
endpoint — see service.py's module docstring). Registered separately in
main.py so the split is visible at the wiring level, not just in code
comments.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.core.deps import get_tenant_db
from app.core.rate_limit import limiter
from app.core.security import TokenData
from app.modules.shares import service
from app.modules.shares.schemas import ResolvedShareOut, ShareCreateIn, ShareOut

router = APIRouter(tags=["shares"])
public_router = APIRouter(tags=["shares-public"])

_DbCtx = Annotated[tuple[Session, TokenData], Depends(get_tenant_db)]


@router.post(
    "/documents/{doc_id}/share",
    response_model=ShareOut,
    response_model_by_alias=True,
    summary="Create a time-limited public share link for a document",
)
def create_share(ctx: _DbCtx, doc_id: uuid.UUID, body: ShareCreateIn) -> ShareOut:
    db, user = ctx
    return service.create_share(db, user, doc_id, body.expires_in_days)


@router.get(
    "/documents/{doc_id}/shares",
    response_model=list[ShareOut],
    response_model_by_alias=True,
    summary="List share links for a document",
)
def list_shares(ctx: _DbCtx, doc_id: uuid.UUID) -> list[ShareOut]:
    db, _ = ctx
    return service.list_shares(db, doc_id)


@router.delete(
    "/shares/{share_id}",
    status_code=204,
    summary="Revoke a share link",
)
def revoke_share(ctx: _DbCtx, share_id: uuid.UUID) -> None:
    db, _ = ctx
    service.revoke_share(db, share_id)


@public_router.get(
    "/share/{token}",
    response_model=ResolvedShareOut,
    response_model_by_alias=True,
    summary="Public: resolve a share token to a signed download URL",
)
@limiter.limit("30/minute")
def resolve_share(request: Request, token: str) -> ResolvedShareOut:
    return service.resolve_share_token(token)
