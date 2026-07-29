"""FastAPI dependencies — the single chokepoint for auth + tenant context.

Every tenant-scoped router depends on ``get_tenant_db``. No router opens a raw
session. The tenant GUC is applied here and self-clears on transaction end.
"""

from collections.abc import Generator

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.db import SessionLocal, get_db
from app.core.security import TokenData, verify_token
from app.core.tenant_context import set_tenant


bearer_scheme = HTTPBearer()


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
) -> TokenData:
    """Verify the Bearer JWT and return parsed token data."""
    return verify_token(credentials.credentials)


def get_tenant_db(
    user: TokenData = Depends(get_current_user),
) -> Generator[tuple[Session, TokenData], None, None]:
    """Yield (db, user) with the tenant GUC applied inside a transaction.

    The GUC is transaction-local (SET LOCAL) so it is discarded automatically
    at commit/rollback — no leakage across pooled connections.
    """
    if not user.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account not associated with a tenant. Call /auth/bootstrap first.",
        )
    db = SessionLocal()
    try:
        db.begin()
        set_tenant(db, user.tenant_id)
        yield db, user
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def require_admin(
    ctx: tuple[Session, TokenData] = Depends(get_tenant_db),
) -> tuple[Session, TokenData]:
    """Raise 403 if the current user is not an admin."""
    db, user = ctx
    if user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required.",
        )
    return db, user
