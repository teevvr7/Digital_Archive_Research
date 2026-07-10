"""Typed extraction fields on documents (Level 3 — data value).

Promotes vendor/invoice_no/total_amount/currency out of the ``extracted_data``
JSONB column into real, indexed columns so amount-range and vendor filters,
export, and duplicate-invoice detection can query them directly instead of
reaching into JSON on every request. Also adds ``duplicate_of_document_id``
(advisory, never enforced — CLAUDE.md: ingestion must never block).

Two extraction schemas are live today and disagree on key casing/names:
deterministic (``vendor``, ``invoiceNumber``, ``totalAmount``, ``currency``)
vs VLM (``vendor``, ``invoice_number``, ``total_amount``/``grand_total``,
``currency``). The backfill below reads both. Kept intentionally
self-contained (not importing ``app.modules.idp.normalize``) per this
project's existing convention of migrations never importing application
code — see idp/normalize.py for the live version the pipeline actually uses
going forward; this is a frozen snapshot of the same logic for one-time use.

Done as a Python loop rather than a raw SQL ``::numeric`` cast: VLM output is
LLM-sourced and occasionally non-conforming (e.g. ``"1,234.50"``), and a
single bad value in a raw-SQL UPDATE would abort the whole migration
transaction. Per-row coercion here never raises.

Revision ID: 0012
Revises: 0011
Create Date: 2026-07-10
"""

from typing import Any, Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: Union[str, None] = "0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _coerce_amount(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        cleaned = value.replace(",", "").strip()
        try:
            return float(cleaned)
        except ValueError:
            return None
    return None


def upgrade() -> None:
    op.add_column("documents", sa.Column("vendor", sa.String(), nullable=True))
    op.add_column("documents", sa.Column("invoice_no", sa.String(), nullable=True))
    op.add_column("documents", sa.Column("total_amount", sa.Numeric(12, 2), nullable=True))
    op.add_column("documents", sa.Column("currency", sa.String(length=8), nullable=True))
    op.add_column(
        "documents",
        sa.Column(
            "duplicate_of_document_id",
            sa.UUID(),
            sa.ForeignKey("documents.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("ix_documents_tenant_total_amount", "documents", ["tenant_id", "total_amount"])
    op.create_index("ix_documents_tenant_vendor", "documents", ["tenant_id", "vendor"])

    # --- Backfill existing rows from extracted_data JSONB ---
    documents = sa.table(
        "documents",
        sa.column("id", sa.UUID()),
        sa.column("extracted_data", sa.JSON()),
        sa.column("vendor", sa.String()),
        sa.column("invoice_no", sa.String()),
        sa.column("total_amount", sa.Numeric(12, 2)),
        sa.column("currency", sa.String(length=8)),
    )
    bind = op.get_bind()
    rows = bind.execute(
        sa.select(documents.c.id, documents.c.extracted_data).where(
            documents.c.extracted_data.isnot(None)
        )
    ).fetchall()

    for row_id, data in rows:
        if not data:
            continue
        vendor = data.get("vendor")
        invoice_no = data.get("invoiceNumber") or data.get("invoice_number")
        total_amount = _coerce_amount(
            data.get("totalAmount") or data.get("total_amount") or data.get("grand_total")
        )
        currency = data.get("currency")

        values: dict[str, Any] = {
            "vendor": vendor if isinstance(vendor, str) and vendor.strip() else None,
            "invoice_no": invoice_no if isinstance(invoice_no, str) and invoice_no.strip() else None,
            "total_amount": total_amount,
            "currency": currency if isinstance(currency, str) and currency.strip() else None,
        }
        if not any(values.values()):
            continue
        bind.execute(documents.update().where(documents.c.id == row_id).values(**values))


def downgrade() -> None:
    op.drop_index("ix_documents_tenant_vendor", table_name="documents")
    op.drop_index("ix_documents_tenant_total_amount", table_name="documents")
    op.drop_column("documents", "duplicate_of_document_id")
    op.drop_column("documents", "currency")
    op.drop_column("documents", "total_amount")
    op.drop_column("documents", "invoice_no")
    op.drop_column("documents", "vendor")
