"""Soft-delete / trash support for documents (Phase 3).

Adds ``deleted_at TIMESTAMPTZ`` to the ``documents`` table.  A NULL value
means the document is live; a non-NULL value means it is in the trash.
The index on ``(tenant_id, deleted_at)`` makes the common filtered queries
(exclude trashed, list trashed) fast.

Revision ID: 0008
Revises: 0007
Create Date: 2026-06-29
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "documents",
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_documents_tenant_deleted_at",
        "documents",
        ["tenant_id", "deleted_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_documents_tenant_deleted_at", table_name="documents")
    op.drop_column("documents", "deleted_at")
