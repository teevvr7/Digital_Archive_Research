"""Trash auto-retention (Level 5 — SME growth & differentiators).

Adds a nullable per-tenant ``trash_retention_days`` override on ``tenants``,
mirroring the existing ``llm_monthly_token_cap`` pattern: NULL means "use
``settings.trash_retention_days_default``". Also adds ``trash_last_purged_at``
so the opportunistic purge check (``files/retention.py``) can rate-limit
itself to roughly once a day per tenant. No RLS changes needed — the table's
existing policies already cover all columns.

Revision ID: 0016
Revises: 0015
Create Date: 2026-07-23
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0016"
down_revision: Union[str, None] = "0015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("tenants", sa.Column("trash_retention_days", sa.Integer(), nullable=True))
    op.add_column(
        "tenants", sa.Column("trash_last_purged_at", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("tenants", "trash_last_purged_at")
    op.drop_column("tenants", "trash_retention_days")
