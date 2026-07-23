"""FastAPI dependencies — the single chokepoint for auth + tenant context.

Every tenant-scoped router depends on ``get_tenant_db``. No router opens a raw
session. The tenant GUC is applied here and self-clears on transaction end.
"""

# Generator is the typing annotation for a function that uses `yield` — every
# FastAPI dependency that needs cleanup-after-the-request uses this shape.
from collections.abc import Generator

# Depends declares "this parameter's value comes from calling another
# function/dependency first". HTTPException/status build error responses.
from fastapi import Depends, HTTPException, status

# HTTPBearer is FastAPI's built-in helper for reading an "Authorization: Bearer
# <token>" header; HTTPAuthorizationCredentials is the parsed result it returns.
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.db import SessionLocal
from app.core.security import TokenData, verify_token
from app.core.tenant_context import set_tenant

# A single shared HTTPBearer instance — FastAPI uses this to know how to
# extract the bearer token out of incoming requests (and to document it in
# the OpenAPI/Swagger schema as a security requirement).
bearer_scheme = HTTPBearer()


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
) -> TokenData:
    """Verify the Bearer JWT and return parsed token data."""
    # credentials.credentials is just the raw token string (without "Bearer ").
    # verify_token does the actual signature/expiry verification and raises
    # a 401 HTTPException if anything is wrong.
    return verify_token(credentials.credentials)


def get_tenant_db(
    user: TokenData = Depends(get_current_user),
) -> Generator[tuple[Session, TokenData], None, None]:
    """Yield (db, user) with the tenant GUC applied inside a transaction.

    The GUC is transaction-local (SET LOCAL) so it is discarded automatically
    at commit/rollback — no leakage across pooled connections.
    """
    # A user whose JWT has no tenant_id yet (first-ever login, before
    # /auth/bootstrap has run) can't use any tenant-scoped route.
    if not user.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account not associated with a tenant. Call /auth/bootstrap first.",
        )
    # Open a brand-new database session for this one request.
    db = SessionLocal()
    try:
        # Start an explicit transaction so the tenant GUC we're about to set
        # is scoped to it (and therefore self-clears at commit/rollback).
        db.begin()
        # This is the actual RLS enforcement hook: it sets the Postgres
        # session variable every tenant-owned table's RLS policy checks.
        set_tenant(db, user.tenant_id)
        # Hand control back to the route handler, passing both the session
        # and the verified user/tenant info it might need.
        yield db, user
        # If the route handler didn't raise, commit whatever it changed.
        db.commit()
    except Exception:
        # Any exception anywhere in the route handler rolls back the whole
        # transaction — no partial writes ever survive an error.
        db.rollback()
        # Re-raise so FastAPI's normal error handling still reports it.
        raise
    finally:
        # Always return the connection to the pool, success or failure.
        db.close()


def require_admin(
    ctx: tuple[Session, TokenData] = Depends(get_tenant_db),
) -> tuple[Session, TokenData]:
    """Raise 403 if the current user is not an admin."""
    # Unpack the (db, user) tuple that get_tenant_db already set up.
    db, user = ctx
    # Only "admin" role users may pass this dependency — used on routes like
    # inviting teammates, changing roles, or renaming the organisation.
    if user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required.",
        )
    # Return the same (db, user) tuple unchanged so admin-only routes can use
    # it exactly like a normal get_tenant_db route.
    return db, user
