"""Auth routes.

``/auth/bootstrap`` — idempotent first-login setup (no tenant GUC needed).
``/auth/me``        — current user + tenant (requires a valid tenant context).
"""

from fastapi import APIRouter, Depends

from app.core.deps import get_current_user
from app.core.security import TokenData
from app.modules.auth import schemas, service

router = APIRouter(prefix="/auth", tags=["auth"])


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
