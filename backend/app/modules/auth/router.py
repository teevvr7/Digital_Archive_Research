"""Auth routes.

``/auth/signup``     — create account (for local testing, uses admin API).
``/auth/bootstrap`` — idempotent first-login setup (no tenant GUC needed).
``/auth/me``        — current user + tenant (requires a valid tenant context).
"""

import uuid

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.deps import get_current_user, get_tenant_db, require_admin
from app.core.rate_limit import limiter
from app.core.security import TokenData
from app.core.validation import EmailField
from app.modules.auth import schemas, service

router = APIRouter(prefix="/auth", tags=["auth"])


class SignupRequest(BaseModel):
    email: EmailField
    password: str = Field(min_length=1, max_length=128)


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
            detail = (
                body.get("msg") or body.get("error_description") or body.get("message") or detail
            )
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
    """Update organisation settings (name, trash retention).

    Admin-only (Settings > Organisation)."""
    db, user = ctx
    tenant = service.update_tenant_settings(
        db, uuid.UUID(user.tenant_id), patch.name, patch.trash_retention_days
    )
    return schemas.TenantOut.model_validate(tenant)


@router.get("/users", response_model=list[schemas.UserOut], response_model_by_alias=True)
def list_users(ctx: tuple[Session, TokenData] = Depends(get_tenant_db)):
    """List every member of the current tenant. Any authenticated member can view."""
    db, user = ctx
    rows = service.list_users(db, uuid.UUID(user.tenant_id))
    return [schemas.UserOut.model_validate(row) for row in rows]


@router.post("/users/invite", response_model=schemas.UserOut, response_model_by_alias=True)
def invite_user(
    body: schemas.InviteUserIn,
    ctx: tuple[Session, TokenData] = Depends(require_admin),
):
    """Invite a teammate by email. Admin-only."""
    db, user = ctx
    new_user = service.invite_user(
        db,
        uuid.UUID(user.tenant_id),
        email=body.email,
        name=body.name,
        role=body.role,
        invited_by=user,
    )
    return schemas.UserOut.model_validate(new_user)


@router.patch(
    "/users/{target_user_id}/role", response_model=schemas.UserOut, response_model_by_alias=True
)
def update_user_role(
    target_user_id: uuid.UUID,
    body: schemas.UpdateUserRoleIn,
    ctx: tuple[Session, TokenData] = Depends(require_admin),
):
    """Change a teammate's role. Admin-only; refuses to demote the last admin."""
    db, user = ctx
    target = service.update_user_role(
        db, uuid.UUID(user.tenant_id), target_user_id, role=body.role, actor=user
    )
    return schemas.UserOut.model_validate(target)


@router.delete("/users/{target_user_id}", status_code=204)
def remove_user(
    target_user_id: uuid.UUID,
    ctx: tuple[Session, TokenData] = Depends(require_admin),
):
    """Remove a teammate from the tenant. Admin-only; refuses to remove self or the last admin."""
    db, user = ctx
    service.remove_user(db, uuid.UUID(user.tenant_id), target_user_id, actor=user)
