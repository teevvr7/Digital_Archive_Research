"""Custom fields catalog + per-document field values (Phase 5 — Metadata).

Creates:
- ``custom_fields``           — per-tenant typed field catalog (text/number/date/boolean/select)
- ``document_field_values``   — per-document field values (JSONB value column)

Both tables get ENABLE/FORCE RLS with the NULLIF-GUC policy + authenticated grants,
mirroring the pattern established in 0005_fix_rls_nullif.py and 0009_tags_correspondents.py.

Revision ID: 0010
Revises: 0009
Create Date: 2026-07-01
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0010"
down_revision: Union[str, None] = "0009"
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
    # ------------------------------------------------------------------ #
    # custom_fields — per-tenant field catalog                             #
    # ------------------------------------------------------------------ #
    op.create_table(
        "custom_fields",
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
        # text | number | date | boolean | select
        sa.Column("field_type", sa.Text(), nullable=False),
        # JSON array of string options (used only for field_type='select')
        sa.Column("options", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_custom_fields_tenant_id", "custom_fields", ["tenant_id"])
    op.create_unique_constraint(
        "uq_custom_fields_tenant_name", "custom_fields", ["tenant_id", "name"]
    )
    _rls_and_grant("custom_fields")

    # ------------------------------------------------------------------ #
    # document_field_values — one row per (document, field) pair           #
    # ------------------------------------------------------------------ #
    op.create_table(
        "document_field_values",
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
        sa.Column(
            "document_id",
            sa.UUID(),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "field_id",
            sa.UUID(),
            sa.ForeignKey("custom_fields.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # Stores any JSON-serialisable value: string, number, boolean, null.
        sa.Column("value", JSONB, nullable=True),
        sa.UniqueConstraint(
            "document_id", "field_id", name="uq_document_field_values_doc_field"
        ),
    )
    op.create_index(
        "ix_document_field_values_tenant_id", "document_field_values", ["tenant_id"]
    )
    op.create_index(
        "ix_document_field_values_document_id",
        "document_field_values",
        ["document_id"],
    )
    op.create_index(
        "ix_document_field_values_field_id", "document_field_values", ["field_id"]
    )
    _rls_and_grant("document_field_values")


def downgrade() -> None:
    op.execute(
        "DROP POLICY IF EXISTS tenant_isolation_document_field_values ON document_field_values"
    )
    op.drop_table("document_field_values")

    op.execute(
        "DROP POLICY IF EXISTS tenant_isolation_custom_fields ON custom_fields"
    )
    op.drop_table("custom_fields")
