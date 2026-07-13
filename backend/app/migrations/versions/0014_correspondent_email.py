"""Correspondent email column (Level 5 — email-sender to correspondent linking).

Adds a nullable ``email`` column to ``correspondents`` plus a per-tenant unique
constraint (NULLs don't collide under Postgres unique-constraint semantics, so
manually-created correspondents without an email are unaffected). Populated by
``tags/matching.py::find_or_create_by_sender`` when an .eml document's From:
address is parsed and auto-linked; also settable manually via the existing
correspondents CRUD. No RLS changes needed — the table's existing policies
already cover all columns.

Revision ID: 0014
Revises: 0013
Create Date: 2026-07-13
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0014"
down_revision: Union[str, None] = "0013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("correspondents", sa.Column("email", sa.Text(), nullable=True))
    op.create_unique_constraint(
        "uq_correspondents_tenant_email", "correspondents", ["tenant_id", "email"]
    )


def downgrade() -> None:
    op.drop_constraint("uq_correspondents_tenant_email", "correspondents", type_="unique")
    op.drop_column("correspondents", "email")
