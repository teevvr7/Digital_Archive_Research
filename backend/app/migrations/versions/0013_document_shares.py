"""Shareable links (Level 3 — data value).

Creates ``document_shares`` — a time-limited, token-gated public link to one
document. The token column is globally unique (not per-tenant): the public
resolve endpoint has no tenant context to scope by, only the token itself.

RLS: standard NULLIF-GUC pattern, same as 0010/0011. This only governs the
authenticated create/list/revoke operations — the public resolve endpoint
bypasses RLS entirely via a raw session (no tenant JWT exists to derive the
GUC from), the same precedent as auth/service.py::bootstrap. The unguessable
token itself is that endpoint's authorization.

Revision ID: 0013
Revises: 0012
Create Date: 2026-07-10
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: Union[str, None] = "0012"
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
        "document_shares",
        sa.Column("id", sa.UUID(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
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
        sa.Column("token", sa.String(length=64), nullable=False),
        sa.Column(
            "created_by",
            sa.UUID(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_document_shares_tenant_id", "document_shares", ["tenant_id"])
    op.create_index("ix_document_shares_document_id", "document_shares", ["document_id"])
    op.create_unique_constraint("uq_document_shares_token", "document_shares", ["token"])
    _rls_and_grant("document_shares")


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation_document_shares ON document_shares")
    op.drop_table("document_shares")
