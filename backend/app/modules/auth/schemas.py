"""Auth module response schemas (camelCase, ORM-friendly)."""

import datetime
import uuid

from pydantic import Field, computed_field

from app.core.camel import CamelModel
from app.core.config import settings
from app.core.validation import EmailField


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
    # NULL = no override; effective_trash_retention_days resolves the actual value.
    trash_retention_days: int | None = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def effective_trash_retention_days(self) -> int:
        """Resolved retention window: this tenant's override, or the global
        default — mirrors ``files/retention.py::effective_retention_days``
        (that one takes the ORM object; this takes the already-validated
        pydantic field, so the one-line fallback is duplicated rather than
        shared across the module boundary for a single ``or``)."""
        return (
            self.trash_retention_days
            if self.trash_retention_days is not None
            else settings.trash_retention_days_default
        )


class MeOut(CamelModel):
    user: UserOut
    tenant: TenantOut


class TenantPatchIn(CamelModel):
    """Editable organisation profile fields."""

    name: str = Field(max_length=200)
    # None clears the override (falls back to the global default).
    trash_retention_days: int | None = Field(default=None, ge=1, le=3650)


class InviteUserIn(CamelModel):
    email: EmailField
    name: str = Field(max_length=200)
    role: str = "user"


class UpdateUserRoleIn(CamelModel):
    role: str
