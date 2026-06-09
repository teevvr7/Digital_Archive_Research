"""Fix RLS policies to handle empty-string GUC.

In Supabase PostgreSQL, ``current_setting('app.current_tenant', true)`` returns
an empty string ``""`` (not NULL) when the GUC was never set in the current
session. Casting ``""`` to uuid raises an error rather than returning NULL, which
breaks the fail-closed guarantee.

Fix: wrap the GUC read in ``NULLIF(..., '')`` so an unset GUC converts to NULL.
NULL cast to uuid is NULL; NULL = tenant_id is NULL (false) → zero rows returned.

Revision ID: 0005
Revises: 0004
Create Date: 2026-06-09
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TENANT_TABLES = [
    "users",
    "documents",
    "document_types",
    "document_templates",
    "extractions",
    "processing_jobs",
    "activity_events",
    "api_keys",
]


def _guc_expr() -> str:
    return "NULLIF(current_setting('app.current_tenant', true), '')::uuid"


def upgrade() -> None:
    for table in TENANT_TABLES:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation_{table} ON {table}")
        op.execute(
            f"CREATE POLICY tenant_isolation_{table} ON {table} "
            f"USING (tenant_id = {_guc_expr()}) "
            f"WITH CHECK (tenant_id = {_guc_expr()})"
        )

    op.execute("DROP POLICY IF EXISTS tenant_isolation_tenants ON tenants")
    op.execute(
        "CREATE POLICY tenant_isolation_tenants ON tenants "
        f"USING (id = {_guc_expr()}) "
        f"WITH CHECK (id = {_guc_expr()})"
    )


def downgrade() -> None:
    _old = "current_setting('app.current_tenant', true)::uuid"
    for table in TENANT_TABLES:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation_{table} ON {table}")
        op.execute(
            f"CREATE POLICY tenant_isolation_{table} ON {table} "
            f"USING (tenant_id = {_old}) "
            f"WITH CHECK (tenant_id = {_old})"
        )
    op.execute("DROP POLICY IF EXISTS tenant_isolation_tenants ON tenants")
    op.execute(
        f"CREATE POLICY tenant_isolation_tenants ON tenants "
        f"USING (id = {_old}) "
        f"WITH CHECK (id = {_old})"
    )
