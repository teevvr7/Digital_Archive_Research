"""Auth module response schemas (camelCase, ORM-friendly)."""

import datetime
import uuid

from app.core.camel import CamelModel


class UserOut(CamelModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    email: str
    name: str
    role: str
    avatar_initials: str
    created_at: datetime.datetime
    last_login_at: datetime.datetime | None


class TenantOut(CamelModel):
    id: uuid.UUID
    name: str
    plan: str
    storage_used_bytes: int
    storage_limit_bytes: int
    created_at: datetime.datetime


class MeOut(CamelModel):
    user: UserOut
    tenant: TenantOut


class TenantPatchIn(CamelModel):
    """Editable organisation profile fields. Only ``name`` is real today —
    no timezone/locale columns exist yet, so we don't fake fields that don't
    persist anywhere."""

    name: str


class InviteUserIn(CamelModel):
    email: str
    name: str
    role: str = "user"


class UpdateUserRoleIn(CamelModel):
    role: str
