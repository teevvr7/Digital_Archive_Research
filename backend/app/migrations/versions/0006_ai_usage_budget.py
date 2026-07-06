"""Add ai_usage table + per-tenant LLM monthly token cap (Phase 0 budget gate).

Every VLM call is metered here so a per-tenant monthly token cap can be enforced
(``app.core.ai_budget.llm_allowed``). ``tenants.llm_monthly_token_cap`` is a nullable
per-tenant override; NULL means "use the global default" (``LLM_MONTHLY_TOKEN_CAP_DEFAULT``).

Revision ID: 0006
Revises: 0005
Create Date: 2026-06-23
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _guc_expr() -> str:
    return "NULLIF(current_setting('app.current_tenant', true), '')::uuid"


def upgrade() -> None:
    op.add_column(
        "tenants",
        sa.Column("llm_monthly_token_cap", sa.Integer(), nullable=True),
    )

    op.create_table(
        "ai_usage",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("document_id", sa.UUID(), nullable=True),
        sa.Column("model_name", sa.String(), nullable=True),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("completion_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                  nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE",
                                name="fk_ai_usage_tenant_id_tenants"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="SET NULL",
                                name="fk_ai_usage_document_id_documents"),
        sa.PrimaryKeyConstraint("id", name="pk_ai_usage"),
    )
    op.create_index("ix_ai_usage_tenant_id", "ai_usage", ["tenant_id"])
    op.create_index("ix_ai_usage_tenant_created", "ai_usage",
                    ["tenant_id", sa.text("created_at DESC")])

    op.execute("ALTER TABLE ai_usage ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE ai_usage FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation_ai_usage ON ai_usage "
        f"USING (tenant_id = {_guc_expr()}) "
        f"WITH CHECK (tenant_id = {_guc_expr()})"
    )

    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE ai_usage TO authenticated")


def downgrade() -> None:
    op.execute("REVOKE ALL ON TABLE ai_usage FROM authenticated")
    op.execute("DROP POLICY IF EXISTS tenant_isolation_ai_usage ON ai_usage")
    op.drop_table("ai_usage")
    op.drop_column("tenants", "llm_monthly_token_cap")
