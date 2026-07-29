"""Remove layout_fingerprint and tags columns from documents

Revision ID: 0019
Revises: 0018
Create Date: 2026-07-08 13:20:59.453879
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '0019'
down_revision: Union[str, None] = '0018'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Drop indices depending on the columns first
    op.drop_index('ix_documents_tenant_fingerprint', table_name='documents')
    op.drop_index('ix_documents_tags_gin', table_name='documents')
    
    # Drop columns
    op.drop_column('documents', 'layout_fingerprint')
    op.drop_column('documents', 'tags')


def downgrade() -> None:
    # Restore columns
    op.add_column('documents', sa.Column('layout_fingerprint', sa.String(), nullable=True))
    op.add_column('documents', sa.Column('tags', postgresql.ARRAY(sa.String()), server_default='{}', nullable=False))
    
    # Restore indices
    op.create_index('ix_documents_tenant_fingerprint', 'documents', ['tenant_id', 'document_type_id', 'layout_fingerprint'], unique=False)
    op.create_index('ix_documents_tags_gin', 'documents', ['tags'], unique=False, postgresql_using='gin')
