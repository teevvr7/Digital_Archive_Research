"""Saved views — per-tenant persistent filter presets (Phase 6 — Retrieval & UX).

Creates:
- ``saved_views`` — stores a name + JSONB filter_state per tenant

RLS: standard NULLIF-GUC pattern, same as 0010_custom_fields.py.

Revision ID: 0011
Revises: 0010
Create Date: 2026-07-01
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0011"
down_revision: Union[str, None] = "0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_GUC = "NULLIF(current_setting('app.current_tenant', true), '')::uuid"


def _rls_and_grant(table: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenant_isolation_{table} ON {table} "
        f"USING (tenant_id = {_GUC}) "
        f"WITH CHECK (tenant_id = {_GUC})"
    )
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE {table} TO authenticated")


def upgrade() -> None:
    op.create_table(
        "saved_views",
        sa.Column(
            "id",
            sa.UUID(),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "tenant_id",
            sa.UUID(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("filter_state", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.text("FALSE")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_saved_views_tenant_id", "saved_views", ["tenant_id"])
    op.create_unique_constraint(
        "uq_saved_views_tenant_name", "saved_views", ["tenant_id", "name"]
    )
    _rls_and_grant("saved_views")


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation_saved_views ON saved_views")
    op.drop_table("saved_views")
