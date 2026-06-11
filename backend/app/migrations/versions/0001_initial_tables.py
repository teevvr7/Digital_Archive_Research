"""Initial tables and indexes.

Revision ID: 0001
Revises:
Create Date: 2026-06-05
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, TSVECTOR

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ---- Extensions ----
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    # ---- tenants ----
    op.create_table(
        "tenants",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("plan", sa.String(), nullable=False, server_default="starter"),
        sa.Column("storage_used_bytes", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("storage_limit_bytes", sa.BigInteger(), nullable=False,
                  server_default=str(10 * 1024 * 1024 * 1024)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                  nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_tenants"),
    )

    # ---- users ----
    op.create_table(
        "users",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("email", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("role", sa.String(), nullable=False, server_default="user"),
        sa.Column("avatar_initials", sa.String(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                  nullable=False),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE",
                                name="fk_users_tenant_id_tenants"),
        sa.PrimaryKeyConstraint("id", name="pk_users"),
        sa.UniqueConstraint("email", name="uq_users_email"),
    )
    op.create_index("ix_users_tenant_id", "users", ["tenant_id"])

    # ---- document_types ----
    op.create_table(
        "document_types",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("json_schema", JSONB, nullable=True),
        sa.Column("is_system", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                  nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE",
                                name="fk_document_types_tenant_id_tenants"),
        sa.PrimaryKeyConstraint("id", name="pk_document_types"),
    )
    op.create_index("ix_document_types_tenant_id", "document_types", ["tenant_id"])

    # ---- documents ----
    op.create_table(
        "documents",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("filename", sa.String(), nullable=False),
        sa.Column("original_filename", sa.String(), nullable=False),
        sa.Column("mime_type", sa.String(), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("storage_key", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="queued"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("document_type_id", sa.UUID(), nullable=True),
        sa.Column("template_id", sa.UUID(), nullable=True),
        sa.Column("document_type", sa.String(), nullable=False, server_default="other"),
        sa.Column("layout_fingerprint", sa.String(), nullable=True),
        sa.Column("page_count", sa.Integer(), nullable=True),
        sa.Column("has_text_layer", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("ocr_used", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("ocr_confidence", sa.REAL(), nullable=True),
        sa.Column("extracted_data", JSONB, nullable=True),
        sa.Column("extracted_text", sa.Text(), nullable=True),
        sa.Column("confidence", sa.REAL(), nullable=True),
        sa.Column("tags", ARRAY(sa.String()), nullable=False, server_default="{}"),
        sa.Column("search_tsv", TSVECTOR, nullable=True),
        sa.Column("uploaded_by", sa.UUID(), nullable=False),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                  nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE",
                                name="fk_documents_tenant_id_tenants"),
        sa.ForeignKeyConstraint(["document_type_id"], ["document_types.id"],
                                ondelete="SET NULL",
                                name="fk_documents_document_type_id_document_types"),
        sa.ForeignKeyConstraint(["uploaded_by"], ["users.id"], ondelete="RESTRICT",
                                name="fk_documents_uploaded_by_users"),
        sa.PrimaryKeyConstraint("id", name="pk_documents"),
    )
    # template_id FK added after document_templates table is created (below)

    # Scoping indexes
    op.create_index("ix_documents_tenant_id", "documents", ["tenant_id"])
    op.create_index("ix_documents_tenant_status", "documents", ["tenant_id", "status"])
    op.create_index("ix_documents_tenant_type", "documents", ["tenant_id", "document_type_id"])
    op.create_index("ix_documents_tenant_uploaded_at", "documents",
                    ["tenant_id", sa.text("uploaded_at DESC")])
    op.create_index("ix_documents_tenant_fingerprint", "documents",
                    ["tenant_id", "document_type_id", "layout_fingerprint"])

    # Search indexes
    op.create_index("ix_documents_search_tsv", "documents", ["search_tsv"],
                    postgresql_using="gin")
    op.create_index("ix_documents_filename_trgm", "documents", ["original_filename"],
                    postgresql_using="gin",
                    postgresql_ops={"original_filename": "gin_trgm_ops"})
    op.create_index("ix_documents_extracted_gin", "documents", ["extracted_data"],
                    postgresql_using="gin",
                    postgresql_ops={"extracted_data": "jsonb_path_ops"})
    op.create_index("ix_documents_tags_gin", "documents", ["tags"],
                    postgresql_using="gin")

    # ---- document_templates ----
    op.create_table(
        "document_templates",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("document_type_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("fingerprint", sa.String(), nullable=False),
        sa.Column("field_mappings", JSONB, nullable=False, server_default="{}"),
        sa.Column("status", sa.String(), nullable=False, server_default="candidate"),
        sa.Column("examples_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("confidence", sa.REAL(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("sample_document_id", sa.UUID(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                  nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                  nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE",
                                name="fk_document_templates_tenant_id_tenants"),
        sa.ForeignKeyConstraint(["document_type_id"], ["document_types.id"],
                                ondelete="CASCADE",
                                name="fk_document_templates_document_type_id_document_types"),
        sa.ForeignKeyConstraint(["sample_document_id"], ["documents.id"],
                                ondelete="SET NULL",
                                name="fk_document_templates_sample_document_id_documents"),
        sa.PrimaryKeyConstraint("id", name="pk_document_templates"),
    )
    op.create_index("ix_document_templates_tenant_id", "document_templates", ["tenant_id"])
    op.create_index("ix_document_templates_tenant_type_fingerprint", "document_templates",
                    ["tenant_id", "document_type_id", "fingerprint"])

    # Now add the documents.template_id FK (table exists now)
    op.create_foreign_key(
        "fk_documents_template_id_document_templates",
        "documents", "document_templates",
        ["template_id"], ["id"],
        ondelete="SET NULL",
    )

    # ---- extractions ----
    op.create_table(
        "extractions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("document_id", sa.UUID(), nullable=False),
        sa.Column("template_id", sa.UUID(), nullable=True),
        sa.Column("method", sa.String(), nullable=False),
        sa.Column("model_name", sa.String(), nullable=True),
        sa.Column("output", JSONB, nullable=True),
        sa.Column("confidence", sa.REAL(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                  nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE",
                                name="fk_extractions_tenant_id_tenants"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE",
                                name="fk_extractions_document_id_documents"),
        sa.ForeignKeyConstraint(["template_id"], ["document_templates.id"],
                                ondelete="SET NULL",
                                name="fk_extractions_template_id_document_templates"),
        sa.PrimaryKeyConstraint("id", name="pk_extractions"),
    )
    op.create_index("ix_extractions_tenant_id", "extractions", ["tenant_id"])
    op.create_index("ix_extractions_document_id", "extractions", ["document_id"])
    op.create_index("ix_extractions_tenant_template_status", "extractions",
                    ["tenant_id", "template_id", "status"])
    op.create_index("ix_extractions_tenant_status", "extractions", ["tenant_id", "status"])

    # ---- processing_jobs ----
    op.create_table(
        "processing_jobs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("document_id", sa.UUID(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="queued"),
        sa.Column("stage", sa.String(), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("enqueued_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                  nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE",
                                name="fk_processing_jobs_tenant_id_tenants"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE",
                                name="fk_processing_jobs_document_id_documents"),
        sa.PrimaryKeyConstraint("id", name="pk_processing_jobs"),
    )
    op.create_index("ix_processing_jobs_tenant_id", "processing_jobs", ["tenant_id"])
    op.create_index("ix_processing_jobs_document_id", "processing_jobs", ["document_id"])

    # ---- activity_events ----
    op.create_table(
        "activity_events",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("type", sa.String(), nullable=False),
        sa.Column("document_id", sa.UUID(), nullable=True),
        sa.Column("document_name", sa.String(), nullable=True),
        sa.Column("user_id", sa.UUID(), nullable=True),
        sa.Column("user_name", sa.String(), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), server_default=sa.func.now(),
                  nullable=False),
        sa.Column("meta", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE",
                                name="fk_activity_events_tenant_id_tenants"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="SET NULL",
                                name="fk_activity_events_document_id_documents"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL",
                                name="fk_activity_events_user_id_users"),
        sa.PrimaryKeyConstraint("id", name="pk_activity_events"),
    )
    op.create_index("ix_activity_events_tenant_id", "activity_events", ["tenant_id"])
    op.create_index("ix_activity_events_tenant_timestamp", "activity_events",
                    ["tenant_id", sa.text("timestamp DESC")])

    # ---- api_keys ----
    op.create_table(
        "api_keys",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("prefix", sa.String(), nullable=False),
        sa.Column("hashed_key", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                  nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE",
                                name="fk_api_keys_tenant_id_tenants"),
        sa.PrimaryKeyConstraint("id", name="pk_api_keys"),
    )
    op.create_index("ix_api_keys_tenant_id", "api_keys", ["tenant_id"])


def downgrade() -> None:
    op.drop_table("api_keys")
    op.drop_table("activity_events")
    op.drop_table("processing_jobs")
    op.drop_table("extractions")
    op.drop_constraint("fk_documents_template_id_document_templates", "documents",
                       type_="foreignkey")
    op.drop_table("document_templates")
    op.drop_table("documents")
    op.drop_table("document_types")
    op.drop_table("users")
    op.drop_table("tenants")
