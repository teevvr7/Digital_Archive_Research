"""Tags, document_tags, and correspondents (Phase 4 — Organization).

Creates:
- ``correspondents`` — vendor/sender entity with match rules
- ``tags`` — label entity with color and match rules
- ``document_tags`` — M2M join between documents and tags
- ``documents.correspondent_id`` FK → correspondents

All three new tables get ENABLE/FORCE RLS with the NULLIF-GUC policy
(matching the fix introduced in 0005_fix_rls_nullif.py) and the
authenticated-role grants from 0004_grant_app_roles.py.

Revision ID: 0009
Revises: 0008
Create Date: 2026-06-29
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: Union[str, None] = "0008"
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
    # correspondents                                                        #
    # ------------------------------------------------------------------ #
    op.create_table(
        "correspondents",
        sa.Column("id", sa.UUID(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", sa.UUID(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("match", sa.Text(), nullable=False, server_default=""),
        sa.Column("matching_algorithm", sa.Text(), nullable=False, server_default="any"),
        sa.Column("is_insensitive", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_correspondents_tenant_id", "correspondents", ["tenant_id"])
    op.create_unique_constraint("uq_correspondents_tenant_name", "correspondents", ["tenant_id", "name"])
    _rls_and_grant("correspondents")

    # ------------------------------------------------------------------ #
    # tags                                                                  #
    # ------------------------------------------------------------------ #
    op.create_table(
        "tags",
        sa.Column("id", sa.UUID(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", sa.UUID(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("color", sa.Text(), nullable=False, server_default="#6B7280"),
        sa.Column("match", sa.Text(), nullable=False, server_default=""),
        sa.Column("matching_algorithm", sa.Text(), nullable=False, server_default="any"),
        sa.Column("is_insensitive", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("is_inbox_tag", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_tags_tenant_id", "tags", ["tenant_id"])
    op.create_unique_constraint("uq_tags_tenant_name", "tags", ["tenant_id", "name"])
    _rls_and_grant("tags")

    # ------------------------------------------------------------------ #
    # document_tags (M2M)                                                   #
    # ------------------------------------------------------------------ #
    op.create_table(
        "document_tags",
        sa.Column("id", sa.UUID(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", sa.UUID(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("document_id", sa.UUID(), sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("tag_id", sa.UUID(), sa.ForeignKey("tags.id", ondelete="CASCADE"), nullable=False),
        sa.UniqueConstraint("document_id", "tag_id", name="uq_document_tags_doc_tag"),
    )
    op.create_index("ix_document_tags_tenant_id", "document_tags", ["tenant_id"])
    op.create_index("ix_document_tags_document_id", "document_tags", ["document_id"])
    op.create_index("ix_document_tags_tag_id", "document_tags", ["tag_id"])
    _rls_and_grant("document_tags")

    # ------------------------------------------------------------------ #
    # documents.correspondent_id FK                                         #
    # ------------------------------------------------------------------ #
    op.add_column(
        "documents",
        sa.Column(
            "correspondent_id",
            sa.UUID(),
            sa.ForeignKey("correspondents.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("ix_documents_correspondent_id", "documents", ["correspondent_id"])


def downgrade() -> None:
    op.drop_index("ix_documents_correspondent_id", table_name="documents")
    op.drop_column("documents", "correspondent_id")

    op.execute("DROP POLICY IF EXISTS tenant_isolation_document_tags ON document_tags")
    op.drop_table("document_tags")

    op.execute("DROP POLICY IF EXISTS tenant_isolation_tags ON tags")
    op.drop_table("tags")

    op.execute("DROP POLICY IF EXISTS tenant_isolation_correspondents ON correspondents")
    op.drop_table("correspondents")
