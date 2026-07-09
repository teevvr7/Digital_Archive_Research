"""Auth service — first-login tenant/user sync.

On first login (no ``tenant_id`` in the JWT ``app_metadata``), we:
1. Create a ``tenants`` row.
2. Set ``app_metadata.tenant_id`` and ``role='admin'`` on the Supabase Auth user
   (so the next token includes those claims).
3. Create the ``users`` row.

On subsequent logins (tenant already in JWT): ensure the local ``users`` row exists
and update ``last_login_at``.

We bypass RLS for this bootstrap path using a direct session (no GUC needed because
we're INSERTing the very rows that RLS would otherwise gate).
"""

import datetime
import uuid

from fastapi import HTTPException
from supabase import create_client
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import SessionLocal
from app.core.security import TokenData
from app.core.tenant_context import set_tenant
from app.models.tenant import Tenant
from app.models.user import User


def _supabase_admin():
    return create_client(settings.supabase_url, settings.supabase_service_role_key)


def _admin_tenant_id(user_id: str) -> dict | None:
    """Return ``{'tenant_id', 'role'}`` from Supabase app_metadata, or None if unset.

    The source of truth for an already-bootstrapped user. Used to guard against a
    stale token (issued in the first-login window, before app_metadata was set)
    re-triggering tenant creation.
    """
    resp = _supabase_admin().auth.admin.get_user_by_id(user_id)
    meta = getattr(resp.user, "app_metadata", None) or {}
    tid = meta.get("tenant_id")
    if tid:
        return {"tenant_id": str(tid), "role": meta.get("role", "user")}
    return None


def _initials(name: str) -> str:
    parts = name.strip().split()
    return "".join(p[0].upper() for p in parts[:2]) if parts else "?"


def bootstrap(token: TokenData) -> tuple[User, Tenant]:
    """Idempotent: ensure tenant + user rows exist for this Supabase auth user.

    Uses a raw session (NOT via get_tenant_db) because the tenant row may not
    exist yet, meaning the GUC + RLS would return zero rows on the first call.
    This function runs outside RLS by design — it is the bootstrap path.
    """
    # Use a direct session that bypasses RLS (or sets the GUC after creation).
    db: Session = SessionLocal()
    try:
        db.begin()

        # A token minted in the first-login window carries no tenant_id yet. Before
        # treating this as a brand-new user, consult Supabase so a stale/replayed
        # token can never spawn a second tenant for an already-bootstrapped user.
        if not token.tenant_id:
            existing = _admin_tenant_id(token.user_id)
            if existing:
                token.tenant_id = existing["tenant_id"]
                token.role = existing["role"]

        if not token.tenant_id:
            # ---- Brand-new user: create tenant + sync app_metadata ----
            # Pre-generate the id and set the GUC BEFORE the INSERT so the tenants
            # RLS WITH CHECK (id = app.current_tenant) passes on the insert itself.
            # (uuid_pk uses a column default, so tenant.id is otherwise only
            # populated at flush — too late for the WITH CHECK.)
            new_tenant_id = uuid.uuid4()
            set_tenant(db, str(new_tenant_id))
            tenant = Tenant(
                id=new_tenant_id, name=_derive_tenant_name(token.email), plan="starter"
            )
            db.add(tenant)
            db.flush()

            # Update Supabase app_metadata so the JWT on next refresh has tenant_id + role.
            _supabase_admin().auth.admin.update_user_by_id(
                token.user_id,
                {"app_metadata": {"tenant_id": str(tenant.id), "role": "admin"}},
            )
            token.tenant_id = str(tenant.id)
            token.role = "admin"
        else:
            # Tenant already exists — fetch it (no RLS; direct by id).
            # Set GUC first so SELECT + any INSERT both pass RLS.
            set_tenant(db, token.tenant_id)
            tenant = db.get(Tenant, uuid.UUID(token.tenant_id))
            if tenant is None:
                # Edge case: app_metadata set but tenant row missing (e.g. manual cleanup).
                tenant = Tenant(
                    id=uuid.UUID(token.tenant_id),
                    name=_derive_tenant_name(token.email),
                    plan="starter",
                )
                db.add(tenant)
                db.flush()

        # ---- Upsert local users row ----
        user = db.get(User, uuid.UUID(token.user_id))
        if user is None:
            display_name = token.email.split("@")[0].replace(".", " ").title()
            user = User(
                id=uuid.UUID(token.user_id),
                tenant_id=tenant.id,
                email=token.email,
                name=display_name,
                role=token.role,
                avatar_initials=_initials(display_name),
                last_login_at=datetime.datetime.now(datetime.timezone.utc),
            )
            db.add(user)
        else:
            user.last_login_at = datetime.datetime.now(datetime.timezone.utc)
            user.role = token.role  # keep in sync with app_metadata

        # Capture the tenant id before commit — SQLAlchemy expires all attributes
        # on commit, so accessing tenant.id after commit would re-query without
        # the GUC and hit the RLS guard.
        final_tenant_id = str(tenant.id)
        db.commit()
        # Re-apply GUC: the transaction-local GUC reset at commit, so refresh
        # SELECTs below need it set again to pass RLS.
        set_tenant(db, final_tenant_id)
        db.refresh(user)
        db.refresh(tenant)
        return user, tenant
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def update_tenant_name(db: Session, tenant_id: uuid.UUID, name: str) -> Tenant:
    """Rename the current tenant. Runs under the normal RLS-scoped session
    (unlike ``bootstrap``, the tenant row is guaranteed to already exist)."""
    name = name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Organisation name cannot be empty.")
    tenant = db.get(Tenant, tenant_id)
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found.")
    tenant.name = name
    db.flush()
    db.refresh(tenant)
    return tenant


def _derive_tenant_name(email: str) -> str:
    domain = email.split("@")[-1] if "@" in email else email
    return domain.split(".")[0].title()
