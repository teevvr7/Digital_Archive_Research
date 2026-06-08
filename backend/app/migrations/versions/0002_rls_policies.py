"""Row-Level Security policies — the multi-tenancy enforcement layer.

ENABLE + FORCE ROW LEVEL SECURITY on every tenant-owned table, then a single
permissive policy keyed on the ``app.current_tenant`` GUC set by the API and worker.

``current_setting('app.current_tenant', true)`` returns NULL when the GUC is unset
(the second arg ``true`` = missing_ok). NULL cast to uuid fails the equality test →
zero rows returned → **fail-closed**. No GUC = no data. Ever.

Revision ID: 0002
Revises: 0001
Create Date: 2026-06-05
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Tables that have tenant_id and should be isolated.
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


def _tenant_policy(table: str) -> str:
    """Generate the RLS USING/WITH CHECK expression for a tenant-owned table."""
    return (
        f"tenant_id = current_setting('app.current_tenant', true)::uuid"
    )


def upgrade() -> None:
    for table in TENANT_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation_{table} ON {table} "
            f"USING ({_tenant_policy(table)}) "
            f"WITH CHECK ({_tenant_policy(table)})"
        )

    # tenants table: a user may only see their own tenant row.
    op.execute("ALTER TABLE tenants ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE tenants FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation_tenants ON tenants "
        "USING (id = current_setting('app.current_tenant', true)::uuid) "
        "WITH CHECK (id = current_setting('app.current_tenant', true)::uuid)"
    )


def downgrade() -> None:
    for table in TENANT_TABLES:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation_{table} ON {table}")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")

    op.execute("DROP POLICY IF EXISTS tenant_isolation_tenants ON tenants")
    op.execute("ALTER TABLE tenants DISABLE ROW LEVEL SECURITY")
