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

from supabase import create_client
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import SessionLocal
from app.core.security import TokenData
from app.models.tenant import Tenant
from app.models.user import User


def _supabase_admin():
    return create_client(settings.supabase_url, settings.supabase_service_role_key)


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

        if not token.tenant_id:
            # ---- Brand-new user: create tenant + sync app_metadata ----
            tenant = Tenant(name=_derive_tenant_name(token.email), plan="starter")
            db.add(tenant)
            db.flush()  # get tenant.id before inserting user

            # Update Supabase app_metadata so the JWT on next refresh has tenant_id + role.
            _supabase_admin().auth.admin.update_user_by_id(
                token.user_id,
                {"app_metadata": {"tenant_id": str(tenant.id), "role": "admin"}},
            )
            token.tenant_id = str(tenant.id)
            token.role = "admin"
        else:
            # Tenant already exists — fetch it (no RLS; direct by id).
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

        db.commit()
        # Refresh both objects while session is still open so all column
        # attributes are loaded into memory. They survive session.close()
        # without triggering DetachedInstanceError in the router.
        db.refresh(user)
        db.refresh(tenant)
        return user, tenant
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _derive_tenant_name(email: str) -> str:
    domain = email.split("@")[-1] if "@" in email else email
    return domain.split(".")[0].title()
