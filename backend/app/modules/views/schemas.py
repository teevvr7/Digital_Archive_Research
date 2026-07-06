"""Schemas for saved views (Phase 6 — Retrieval & UX)."""

import datetime
import uuid
from typing import Any

from app.core.camel import CamelModel


class SavedViewIn(CamelModel):
    name: str
    filter_state: dict[str, Any] = {}
    is_default: bool = False


class SavedViewPatchIn(CamelModel):
    name: str | None = None
    filter_state: dict[str, Any] | None = None
    is_default: bool | None = None


class SavedViewOut(CamelModel):
    id: uuid.UUID
    name: str
    filter_state: dict[str, Any]
    is_default: bool
    created_at: datetime.datetime
