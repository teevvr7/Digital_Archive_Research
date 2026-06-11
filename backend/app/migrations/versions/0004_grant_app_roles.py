"""Grant table-level access to authenticated role.

The ``postgres`` Supabase role has ``bypassrls = true``, which means RLS policies
are never enforced for it — even with ``FORCE ROW LEVEL SECURITY``. The ``authenticated``
role does NOT have bypassrls, so RLS is fully enforced for it.

These grants allow:
- Tests: switch to ``authenticated`` role inside a transaction to verify RLS isolation.
- Future: migrate the FastAPI backend to connect as ``authenticated`` (Milestone E) so
  RLS is enforced in production, not just at the service-layer query level.

The ``service_role`` key is used for Supabase storage and admin operations — it keeps
bypassrls, which is intentional for those administrative paths.

Revision ID: 0004
Revises: 0003
Create Date: 2026-06-09
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TENANT_TABLES = [
    "tenants",
    "users",
    "documents",
    "document_types",
    "document_templates",
    "extractions",
    "processing_jobs",
    "activity_events",
    "api_keys",
]


def upgrade() -> None:
    op.execute("GRANT USAGE ON SCHEMA public TO authenticated")
    for table in TENANT_TABLES:
        op.execute(
            f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE {table} TO authenticated"
        )


def downgrade() -> None:
    for table in TENANT_TABLES:
        op.execute(f"REVOKE ALL ON TABLE {table} FROM authenticated")
    op.execute("REVOKE USAGE ON SCHEMA public FROM authenticated")
