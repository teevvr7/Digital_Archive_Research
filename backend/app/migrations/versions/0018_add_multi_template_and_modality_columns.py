"""add multi template and modality columns

Revision ID: 0018
Revises: 0017
Create Date: 2026-07-01 16:03:04.493841
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0018'
down_revision: Union[str, None] = '0017'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('document_templates', sa.Column('is_default', sa.Boolean(), server_default='false', nullable=False))
    op.add_column('document_templates', sa.Column('use_image', sa.Boolean(), server_default='false', nullable=False))
    op.add_column('document_templates', sa.Column('use_ocr', sa.Boolean(), server_default='true', nullable=False))


def downgrade() -> None:
    op.drop_column('document_templates', 'use_ocr')
    op.drop_column('document_templates', 'use_image')
    op.drop_column('document_templates', 'is_default')
