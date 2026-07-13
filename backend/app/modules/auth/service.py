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
from supabase_auth.errors import AuthApiError
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import SessionLocal
from app.core.security import TokenData
from app.core.tenant_context import set_tenant
from app.models.activity_event import (
    ACT_USER_ADDED,
    ACT_USER_REMOVED,
    ACT_USER_ROLE_CHANGED,
    ActivityEvent,
)
from app.models.tag import Tag
from app.models.tenant import Tenant
from app.models.user import User

_VALID_ROLES = {"admin", "user"}

# Onboarding starter kit — a handful of generic, broadly-useful tags so a brand-new
# tenant isn't staring at a completely empty archive. Colors match the frontend's
# PRESET_COLORS swatches. No starter correspondents: a real tenant's vendors/clients
# can't be guessed, unlike a few generic organizational tags.
_STARTER_TAGS = [
    ("Paid", "#10B981"),
    ("Unpaid", "#EF4444"),
    ("Important", "#F59E0B"),
    ("Needs Review", "#8B5CF6"),
]


def _seed_starter_tags(db: Session, tenant_id: uuid.UUID) -> None:
    db.add_all(Tag(tenant_id=tenant_id, name=name, color=color) for name, color in _STARTER_TAGS)


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
            _seed_starter_tags(db, tenant.id)

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


def _actor_name(db: Session, actor: TokenData) -> str:
    """Display name for the acting user; falls back to email on miss."""
    row = db.get(User, uuid.UUID(actor.user_id))
    return row.name if row else actor.email


def list_users(db: Session, tenant_id: uuid.UUID) -> list[User]:
    """All members of the current tenant, oldest first."""
    return list(
        db.scalars(
            select(User).where(User.tenant_id == tenant_id).order_by(User.created_at.asc())
        )
    )


def invite_user(
    db: Session,
    tenant_id: uuid.UUID,
    *,
    email: str,
    name: str,
    role: str,
    invited_by: TokenData,
) -> User:
    """Invite a teammate via Supabase Auth's admin invite email.

    ``app_metadata`` (tenant_id/role) is set immediately after the Supabase user
    is created, before they ever log in — so the JWT minted when they accept the
    invite (set their password) already carries the right tenant, mirroring how
    ``bootstrap()`` sets it for self-signup. The local ``users`` row is created
    now too (not deferred to first login) so admins can see pending invites;
    ``last_login_at IS NULL`` is the "pending" signal.
    """
    email = email.strip().lower()
    name = name.strip()
    if role not in _VALID_ROLES:
        raise HTTPException(status_code=400, detail="Role must be 'admin' or 'user'.")
    if not name:
        raise HTTPException(status_code=400, detail="Name is required.")
    if not email or "@" not in email:
        raise HTTPException(status_code=400, detail="A valid email is required.")

    frontend_origin = settings.cors_origins_list[0] if settings.cors_origins_list else ""
    try:
        resp = _supabase_admin().auth.admin.invite_user_by_email(
            email,
            {"data": {"name": name}, "redirect_to": f"{frontend_origin}/accept-invite"},
        )
    except AuthApiError as exc:
        # In practice this is almost always "email already registered".
        raise HTTPException(status_code=409, detail=exc.message) from exc

    new_user_id = uuid.UUID(resp.user.id)
    _supabase_admin().auth.admin.update_user_by_id(
        str(new_user_id), {"app_metadata": {"tenant_id": str(tenant_id), "role": role}}
    )

    user = User(
        id=new_user_id,
        tenant_id=tenant_id,
        email=email,
        name=name,
        role=role,
        avatar_initials=_initials(name),
        last_login_at=None,
    )
    db.add(user)
    try:
        db.flush()
    except IntegrityError as exc:
        # Extremely unlikely (would mean Supabase Auth and our local `users`
        # table disagree), but `email` is globally unique — fail cleanly.
        raise HTTPException(
            status_code=409, detail="This email is already associated with an existing account."
        ) from exc

    db.add(
        ActivityEvent(
            tenant_id=tenant_id,
            type=ACT_USER_ADDED,
            user_id=uuid.UUID(invited_by.user_id),
            user_name=_actor_name(db, invited_by),
            meta=f"{email} as {role}",
        )
    )
    db.flush()
    db.refresh(user)
    return user


def _admin_count(db: Session, tenant_id: uuid.UUID) -> int:
    return len(
        list(
            db.scalars(
                select(User.id).where(User.tenant_id == tenant_id, User.role == "admin")
            )
        )
    )


def update_user_role(
    db: Session,
    tenant_id: uuid.UUID,
    target_user_id: uuid.UUID,
    *,
    role: str,
    actor: TokenData,
) -> User:
    """Change a teammate's role. Refuses to demote the tenant's last admin."""
    if role not in _VALID_ROLES:
        raise HTTPException(status_code=400, detail="Role must be 'admin' or 'user'.")
    target = db.get(User, target_user_id)
    if target is None or target.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="User not found.")

    if target.role == "admin" and role != "admin" and _admin_count(db, tenant_id) <= 1:
        raise HTTPException(status_code=400, detail="Cannot demote the last admin.")

    target.role = role
    db.flush()
    # Keep the JWT claim in sync — role checks (`require_admin`) read app_metadata,
    # not this table, so a stale token would otherwise keep the old permission.
    _supabase_admin().auth.admin.update_user_by_id(
        str(target.id), {"app_metadata": {"tenant_id": str(tenant_id), "role": role}}
    )

    db.add(
        ActivityEvent(
            tenant_id=tenant_id,
            type=ACT_USER_ROLE_CHANGED,
            user_id=uuid.UUID(actor.user_id),
            user_name=_actor_name(db, actor),
            meta=f"{target.email} → {role}",
        )
    )
    db.flush()
    db.refresh(target)
    return target


def remove_user(
    db: Session,
    tenant_id: uuid.UUID,
    target_user_id: uuid.UUID,
    *,
    actor: TokenData,
) -> None:
    """Remove a teammate from the tenant and delete their Supabase Auth identity.

    Note: an already-issued, unexpired access token remains valid until it
    naturally expires (JWTs are verified locally by signature, not looked up
    per-request) — this revokes future logins/refreshes, not any live session.
    """
    if str(target_user_id) == actor.user_id:
        raise HTTPException(status_code=400, detail="You cannot remove yourself.")
    target = db.get(User, target_user_id)
    if target is None or target.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="User not found.")
    if target.role == "admin" and _admin_count(db, tenant_id) <= 1:
        raise HTTPException(status_code=400, detail="Cannot remove the last admin.")

    try:
        _supabase_admin().auth.admin.delete_user(str(target.id))
    except AuthApiError as exc:
        raise HTTPException(status_code=502, detail=exc.message) from exc

    target_email = target.email
    actor_name = _actor_name(db, actor)
    db.delete(target)
    db.add(
        ActivityEvent(
            tenant_id=tenant_id,
            type=ACT_USER_REMOVED,
            user_id=uuid.UUID(actor.user_id),
            user_name=actor_name,
            meta=target_email,
        )
    )
    db.flush()
