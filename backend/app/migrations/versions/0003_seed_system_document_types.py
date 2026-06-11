"""Seed the system document types (tenant_id NULL = global/shared).

These are the types the frontend UI dropdown enumerates. Adding new system types
is a migration; adding tenant-specific types is an INSERT at runtime.

Revision ID: 0003
Revises: 0002
Create Date: 2026-06-05
"""

from typing import Sequence, Union
import uuid

from alembic import op
import sqlalchemy as sa

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SYSTEM_TYPES = [
    ("invoice",  "Tax invoices, vendor invoices, billing statements"),
    ("receipt",  "Payment receipts, petty cash receipts"),
    ("contract", "Service agreements, vendor contracts, NDAs"),
    ("report",   "Financial reports, audit reports, management reports"),
    ("letter",   "Official correspondence, government notices"),
    ("form",     "HRDF levy forms, tax forms, regulatory submissions"),
    ("other",    "Uncategorised or unrecognised document types"),
]


def upgrade() -> None:
    doc_types = sa.table(
        "document_types",
        sa.column("id", sa.UUID()),
        sa.column("tenant_id", sa.UUID()),
        sa.column("name", sa.String()),
        sa.column("description", sa.Text()),
        sa.column("is_system", sa.Boolean()),
    )
    op.bulk_insert(
        doc_types,
        [
            {
                "id": str(uuid.uuid4()),
                "tenant_id": None,
                "name": name,
                "description": desc,
                "is_system": True,
            }
            for name, desc in SYSTEM_TYPES
        ],
    )


def downgrade() -> None:
    op.execute("DELETE FROM document_types WHERE is_system = true AND tenant_id IS NULL")
