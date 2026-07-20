"""Predefined custom fields per document type.

Creates ``document_type_fields`` — links an existing ``custom_fields`` catalog
entry to one of the fixed document-type strings (invoice/receipt/contract/
report/letter/form/other) as "predefined" for that type, with an optional
``required`` flag and a display ``position``.

Also seeds a starter set of predefined fields (and the underlying catalog
fields, if not already present by name) for every existing tenant — fully
editable/removable afterward via the Custom Fields page. Runs as the Alembic
superuser connection, which bypasses RLS entirely (including FORCE ROW LEVEL
SECURITY, which only affects the table owner, never superusers), so no GUC
needs to be set during the seed loop — same precedent as 0012's typed-field
backfill.

Revision ID: 0015
Revises: 0014
Create Date: 2026-07-16
"""

import json
import uuid
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0015"
down_revision: Union[str, None] = "0014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_GUC = "NULLIF(current_setting('app.current_tenant', true), '')::uuid"

# document_type -> [(field_name, field_type, options), ...]
_STARTER_FIELDS: dict[str, list[tuple[str, str, list[str]]]] = {
    "invoice": [
        ("PO Number", "text", []),
        ("Payment Terms", "text", []),
    ],
    "receipt": [
        ("Expense Category", "select", ["Travel", "Meals", "Office", "Other"]),
    ],
    "contract": [
        ("Contract End Date", "date", []),
        ("Renewal Reminder", "boolean", []),
    ],
    "report": [
        ("Department", "text", []),
    ],
}


def _rls_and_grant(table: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenant_isolation_{table} ON {table} "
        f"USING (tenant_id = {_GUC}) "
        f"WITH CHECK (tenant_id = {_GUC})"
    )
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE {table} TO authenticated")


def upgrade() -> None:
    op.create_table(
        "document_type_fields",
        sa.Column(
            "id", sa.UUID(), primary_key=True, server_default=sa.text("gen_random_uuid()")
        ),
        sa.Column(
            "tenant_id",
            sa.UUID(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # One of: invoice | receipt | contract | report | letter | form | other
        # (VALID_DOCUMENT_TYPES in app.models.document_type_field) — validated
        # in the service layer, not a DB CHECK constraint, matching how
        # custom_field.field_type is validated.
        sa.Column("document_type", sa.Text(), nullable=False),
        sa.Column(
            "field_id",
            sa.UUID(),
            sa.ForeignKey("custom_fields.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("required", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "tenant_id", "document_type", "field_id",
            name="uq_document_type_fields_tenant_type_field",
        ),
    )
    op.create_index(
        "ix_document_type_fields_tenant_type",
        "document_type_fields",
        ["tenant_id", "document_type"],
    )
    op.create_index(
        "ix_document_type_fields_field_id", "document_type_fields", ["field_id"]
    )
    _rls_and_grant("document_type_fields")

    # ---- Seed starter fields for every existing tenant ----
    bind = op.get_bind()
    tenant_ids = [row[0] for row in bind.execute(sa.text("SELECT id FROM tenants")).fetchall()]

    for tenant_id in tenant_ids:
        for doc_type, fields in _STARTER_FIELDS.items():
            for name, field_type, options in fields:
                existing = bind.execute(
                    sa.text(
                        "SELECT id FROM custom_fields WHERE tenant_id = :tid AND name = :name"
                    ),
                    {"tid": tenant_id, "name": name},
                ).fetchone()
                if existing:
                    field_id = existing[0]
                else:
                    field_id = str(uuid.uuid4())
                    bind.execute(
                        sa.text(
                            "INSERT INTO custom_fields "
                            "(id, tenant_id, name, field_type, options, position) "
                            "VALUES (:id, :tid, :name, :ftype, CAST(:options AS jsonb), 0)"
                        ),
                        {
                            "id": field_id,
                            "tid": tenant_id,
                            "name": name,
                            "ftype": field_type,
                            "options": json.dumps(options),
                        },
                    )

                already_attached = bind.execute(
                    sa.text(
                        "SELECT id FROM document_type_fields "
                        "WHERE tenant_id = :tid AND document_type = :dtype AND field_id = :fid"
                    ),
                    {"tid": tenant_id, "dtype": doc_type, "fid": field_id},
                ).fetchone()
                if not already_attached:
                    bind.execute(
                        sa.text(
                            "INSERT INTO document_type_fields "
                            "(id, tenant_id, document_type, field_id, required, position) "
                            "VALUES (:id, :tid, :dtype, :fid, false, 0)"
                        ),
                        {
                            "id": str(uuid.uuid4()),
                            "tid": tenant_id,
                            "dtype": doc_type,
                            "fid": field_id,
                        },
                    )


def downgrade() -> None:
    op.execute(
        "DROP POLICY IF EXISTS tenant_isolation_document_type_fields ON document_type_fields"
    )
    op.drop_table("document_type_fields")
