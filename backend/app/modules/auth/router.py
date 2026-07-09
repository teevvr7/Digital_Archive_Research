"""Auth routes.

``/auth/signup``     — create account (for local testing, uses admin API).
``/auth/bootstrap`` — idempotent first-login setup (no tenant GUC needed).
``/auth/me``        — current user + tenant (requires a valid tenant context).
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
import httpx
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.deps import get_current_user, require_admin
from app.core.rate_limit import limiter
from app.core.security import TokenData
from app.modules.auth import schemas, service

router = APIRouter(prefix="/auth", tags=["auth"])


class SignupRequest(BaseModel):
    email: str
    password: str


@router.post("/signup")
@limiter.limit("10/hour")
async def signup(request: Request, req: SignupRequest):
    """Create a pre-confirmed account via the Supabase admin API (local testing).

    Uses the service-role key with ``email_confirm=True`` so the user can sign in
    immediately without the email-verification round-trip. Rate-limited (10/hour
    per IP) — this is an unauthenticated endpoint, the obvious abuse target.
    """
    if not settings.supabase_service_role_key:
        raise HTTPException(status_code=500, detail="SUPABASE_SERVICE_ROLE_KEY not configured")

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                f"{settings.supabase_url}/auth/v1/admin/users",
                headers={
                    "apikey": settings.supabase_service_role_key,
                    "Authorization": f"Bearer {settings.supabase_service_role_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "email": req.email,
                    "password": req.password,
                    "email_confirm": True,
                },
            )
    except httpx.RequestError as e:
        raise HTTPException(status_code=502, detail=f"Could not reach Supabase: {e}")

    if response.status_code >= 400:
        # Surface Supabase's own message (e.g. "email already registered") cleanly.
        detail = response.text
        try:
            body = response.json()
            detail = body.get("msg") or body.get("error_description") or body.get("message") or detail
        except Exception:
            pass
        raise HTTPException(status_code=response.status_code, detail=detail)

    return {"message": "Account created. You can now sign in."}


@router.post("/bootstrap", response_model=schemas.MeOut, response_model_by_alias=True)
def bootstrap(user: TokenData = Depends(get_current_user)):
    """Create/sync tenant + user rows on first login. Safe to call on every login."""
    db_user, db_tenant = service.bootstrap(user)
    return schemas.MeOut(
        user=schemas.UserOut.model_validate(db_user),
        tenant=schemas.TenantOut.model_validate(db_tenant),
    )


@router.get("/me", response_model=schemas.MeOut, response_model_by_alias=True)
def me(user: TokenData = Depends(get_current_user)):
    """Return the current user's profile + tenant. Also updates last_login_at."""
    db_user, db_tenant = service.bootstrap(user)  # bootstrap is idempotent
    return schemas.MeOut(
        user=schemas.UserOut.model_validate(db_user),
        tenant=schemas.TenantOut.model_validate(db_tenant),
    )


@router.patch("/tenant", response_model=schemas.TenantOut, response_model_by_alias=True)
def update_tenant(
    patch: schemas.TenantPatchIn,
    ctx: tuple[Session, TokenData] = Depends(require_admin),
):
    """Rename the organisation. Admin-only (Settings > Organisation)."""
    db, user = ctx
    tenant = service.update_tenant_name(db, uuid.UUID(user.tenant_id), patch.name)
    return schemas.TenantOut.model_validate(tenant)
