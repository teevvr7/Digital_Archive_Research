"""Universal ingestion baseline columns (Phase 1).

Adds the metadata every archived file gets regardless of type:
``checksum`` (sha256, dedup), ``title`` (editable, defaults to the original
filename), ``document_date`` (best-effort, extracted from content), and
``thumbnail_key`` (object-storage pointer, set only when a thumbnail could
be generated). The checksum uniqueness is a *partial* index — only rows
that have a checksum participate, so pre-existing documents (uploaded
before this migration) never collide with NULL.

Revision ID: 0007
Revises: 0006
Create Date: 2026-06-24
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("documents", sa.Column("checksum", sa.String(length=64), nullable=True))
    op.add_column("documents", sa.Column("title", sa.String(), nullable=True))
    op.add_column("documents", sa.Column("document_date", sa.Date(), nullable=True))
    op.add_column("documents", sa.Column("thumbnail_key", sa.String(), nullable=True))

    # Backfill title for documents that predate this column.
    op.execute("UPDATE documents SET title = original_filename WHERE title IS NULL")

    op.create_index(
        "uq_documents_tenant_checksum",
        "documents",
        ["tenant_id", "checksum"],
        unique=True,
        postgresql_where=sa.text("checksum IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_documents_tenant_checksum", table_name="documents")
    op.drop_column("documents", "thumbnail_key")
    op.drop_column("documents", "document_date")
    op.drop_column("documents", "title")
    op.drop_column("documents", "checksum")
