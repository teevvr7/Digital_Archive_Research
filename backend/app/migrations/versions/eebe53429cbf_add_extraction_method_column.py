"""add extraction_method column

Revision ID: eebe53429cbf
Revises: 0005
Create Date: 2026-06-22 10:06:53.316929
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


"""add extraction_method column

Revision ID: eebe53429cbf
Revises: 0005
Create Date: 2026-06-22 10:06:53.316929
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'eebe53429cbf'
down_revision: Union[str, None] = '0005'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Adding extraction_method with a default 'default' value for existing rows
    op.add_column('document_templates', sa.Column('extraction_method', sa.String(), server_default='default', nullable=False))
    op.add_column('document_types', sa.Column('extraction_method', sa.String(), server_default='default', nullable=False))


def downgrade() -> None:
    op.drop_column('document_types', 'extraction_method')
    op.drop_column('document_templates', 'extraction_method')
