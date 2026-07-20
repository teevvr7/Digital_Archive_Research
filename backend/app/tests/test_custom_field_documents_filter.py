"""Custom-field filter on ``list_documents`` (Documents page, type-gated).

Runs against a real Postgres (RLS enforced via ``SET LOCAL ROLE authenticated``
+ tenant GUC), same pattern as ``test_search_service.py`` — needed because this
exercises real JSONB "as text" extraction (``#>>'{}'``) and numeric/date casts
that a mocked session can't verify.

Requires ALEMBIC_DATABASE_URL (loaded from .env by conftest). Skipped when absent.
Run: ``pytest app/tests/test_custom_field_documents_filter.py -v``
"""

import datetime
import json
import os
import uuid

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

pytestmark = pytest.mark.skipif(
    not os.environ.get("ALEMBIC_DATABASE_URL"),
    reason="ALEMBIC_DATABASE_URL not set — skipping DB-backed filter tests",
)

DB_URL = os.environ.get("ALEMBIC_DATABASE_URL", "")


@pytest.fixture(scope="module")
def direct_engine():
    engine = create_engine(DB_URL, future=True)
    yield engine
    engine.dispose()


@pytest.fixture(scope="module")
def seeds(direct_engine):
    """Seed a tenant with invoice/contract docs carrying custom field values
    of every type: text, select (with a deliberate substring-collision pair
    to catch over-matching), boolean, number, date."""
    t_id = uuid.uuid4()
    u_id = uuid.uuid4()
    inv1, inv2 = uuid.uuid4(), uuid.uuid4()
    con1, con2 = uuid.uuid4(), uuid.uuid4()

    f_cost_center = uuid.uuid4()  # text
    f_priority = uuid.uuid4()  # select — options include a substring collision
    f_renewal = uuid.uuid4()  # boolean
    f_amount = uuid.uuid4()  # number
    f_end_date = uuid.uuid4()  # date

    insert_doc = text(
        "INSERT INTO documents (id, tenant_id, uploaded_by, filename, original_filename,"
        " title, mime_type, size_bytes, storage_key, document_type, status)"
        " VALUES (:id, :tid, :uid, :fn, :fn, :fn, 'application/pdf', 1000, :sk, :dtype,"
        " 'completed') ON CONFLICT DO NOTHING"
    )
    insert_field = text(
        "INSERT INTO custom_fields (id, tenant_id, name, field_type, options, position)"
        " VALUES (:id, :tid, :name, :ftype, CAST(:options AS jsonb), 0) ON CONFLICT DO NOTHING"
    )
    insert_value = text(
        "INSERT INTO document_field_values (id, tenant_id, document_id, field_id, value)"
        " VALUES (:id, :tid, :did, :fid, CAST(:value AS jsonb)) ON CONFLICT DO NOTHING"
    )

    with direct_engine.connect() as conn:
        conn.execute(text("SET session_replication_role = 'replica'"))
        conn.execute(
            text("INSERT INTO tenants (id, name) VALUES (:id, :name) ON CONFLICT DO NOTHING"),
            {"id": str(t_id), "name": "CustomFieldFilter-T"},
        )
        conn.execute(
            text(
                "INSERT INTO users (id, tenant_id, email, name)"
                " VALUES (:id, :tid, :email, :name) ON CONFLICT DO NOTHING"
            ),
            {"id": str(u_id), "tid": str(t_id), "email": "cf@t.com", "name": "CF User"},
        )
        for did, fn, dtype in [
            (inv1, "Invoice One.pdf", "invoice"),
            (inv2, "Invoice Two.pdf", "invoice"),
            (con1, "Contract One.pdf", "contract"),
            (con2, "Contract Two.pdf", "contract"),
        ]:
            conn.execute(
                insert_doc,
                {
                    "id": str(did), "tid": str(t_id), "uid": str(u_id),
                    "fn": fn, "sk": f"{t_id}/docs/{did}.pdf", "dtype": dtype,
                },
            )

        for fid, name, ftype, options in [
            (f_cost_center, "Cost Center", "text", []),
            (f_priority, "Priority", "select", ["Travel", "International Travel"]),
            (f_renewal, "Renewal", "boolean", []),
            (f_amount, "Amount", "number", []),
            (f_end_date, "End Date", "date", []),
        ]:
            conn.execute(
                insert_field,
                {
                    "id": str(fid), "tid": str(t_id), "name": name,
                    "ftype": ftype, "options": json.dumps(options),
                },
            )

        values = [
            (inv1, f_cost_center, "Marketing Team"),
            (inv2, f_cost_center, "Sales Team"),
            (inv1, f_priority, "Travel"),
            (inv2, f_priority, "International Travel"),
            (con1, f_renewal, True),
            (con2, f_renewal, False),
            (con1, f_amount, 5000),
            (con2, f_amount, 1000),
            (con1, f_end_date, "2026-12-31"),
            (con2, f_end_date, "2025-06-01"),
        ]
        for did, fid, value in values:
            conn.execute(
                insert_value,
                {
                    "id": str(uuid.uuid4()), "tid": str(t_id),
                    "did": str(did), "fid": str(fid), "value": json.dumps(value),
                },
            )
        conn.execute(text("SET session_replication_role = 'origin'"))
        conn.commit()

    yield {
        "t": t_id, "inv1": inv1, "inv2": inv2, "con1": con1, "con2": con2,
        "cost_center": f_cost_center, "priority": f_priority,
        "renewal": f_renewal, "amount": f_amount, "end_date": f_end_date,
    }

    with direct_engine.connect() as conn:
        conn.execute(text("SET session_replication_role = 'replica'"))
        for did in (inv1, inv2, con1, con2):
            conn.execute(text("DELETE FROM documents WHERE id = :id"), {"id": str(did)})
        for fid in (f_cost_center, f_priority, f_renewal, f_amount, f_end_date):
            conn.execute(text("DELETE FROM custom_fields WHERE id = :id"), {"id": str(fid)})
        conn.execute(text("DELETE FROM users WHERE id = :id"), {"id": str(u_id)})
        conn.execute(text("DELETE FROM tenants WHERE id = :id"), {"id": str(t_id)})
        conn.execute(text("SET session_replication_role = 'origin'"))
        conn.commit()


def _session(engine, tenant_id: uuid.UUID):
    Session = sessionmaker(bind=engine, autocommit=False)
    db = Session()
    db.begin()
    db.execute(text("SET LOCAL ROLE authenticated"))
    db.execute(
        text("SELECT set_config('app.current_tenant', :tid, true)"),
        {"tid": str(tenant_id)},
    )
    return db


def _ids(out):
    return {str(item.id) for item in out.items}


def test_text_field_partial_match(direct_engine, seeds):
    from app.modules.files.service import list_documents

    db = _session(direct_engine, seeds["t"])
    out = list_documents(db, custom_field_id=seeds["cost_center"], custom_field_value="Market")
    ids = _ids(out)
    assert str(seeds["inv1"]) in ids
    assert str(seeds["inv2"]) not in ids
    db.rollback()
    db.close()


def test_select_field_exact_match_no_substring_overmatch(direct_engine, seeds):
    """'Travel' must not also match 'International Travel' — the whole point
    of resolving field_type server-side to use exact equality, not ILIKE."""
    from app.modules.files.service import list_documents

    db = _session(direct_engine, seeds["t"])
    out = list_documents(db, custom_field_id=seeds["priority"], custom_field_value="Travel")
    ids = _ids(out)
    assert str(seeds["inv1"]) in ids
    assert str(seeds["inv2"]) not in ids
    db.rollback()
    db.close()


def test_boolean_field_exact_match(direct_engine, seeds):
    from app.modules.files.service import list_documents

    db = _session(direct_engine, seeds["t"])
    out = list_documents(db, custom_field_id=seeds["renewal"], custom_field_value="true")
    ids = _ids(out)
    assert str(seeds["con1"]) in ids
    assert str(seeds["con2"]) not in ids
    db.rollback()
    db.close()


def test_number_field_contains_match(direct_engine, seeds):
    """The 'Contains' mode — find a reference-number-style field by typing
    remembered digits, without needing to know (or guess) a min/max range."""
    from app.modules.files.service import list_documents

    db = _session(direct_engine, seeds["t"])
    out = list_documents(db, custom_field_id=seeds["amount"], custom_field_value="500")
    ids = _ids(out)
    assert str(seeds["con1"]) in ids  # 5000 contains "500"
    assert str(seeds["con2"]) not in ids  # 1000 does not
    db.rollback()
    db.close()


def test_number_field_range(direct_engine, seeds):
    from app.modules.files.service import list_documents

    db = _session(direct_engine, seeds["t"])
    out = list_documents(db, custom_field_id=seeds["amount"], custom_field_min=2000)
    ids = _ids(out)
    assert str(seeds["con1"]) in ids
    assert str(seeds["con2"]) not in ids
    db.rollback()
    db.close()


def test_date_field_range_expiring_soon_use_case(direct_engine, seeds):
    """The concrete 'contracts expiring after this date' use case."""
    from app.modules.files.service import list_documents

    db = _session(direct_engine, seeds["t"])
    out = list_documents(
        db, custom_field_id=seeds["end_date"], custom_field_date_from=datetime.date(2026, 1, 1)
    )
    ids = _ids(out)
    assert str(seeds["con1"]) in ids
    assert str(seeds["con2"]) not in ids
    db.rollback()
    db.close()


def test_no_match_returns_empty(direct_engine, seeds):
    from app.modules.files.service import list_documents

    db = _session(direct_engine, seeds["t"])
    out = list_documents(
        db, custom_field_id=seeds["cost_center"], custom_field_value="Nonexistent Team XYZ"
    )
    assert out.items == []
    db.rollback()
    db.close()


def test_combined_with_type_filter(direct_engine, seeds):
    """The actual UI flow: Type=Invoice narrows first, then the custom field filter."""
    from app.modules.files.service import list_documents

    db = _session(direct_engine, seeds["t"])
    out = list_documents(
        db,
        type_filter="invoice",
        custom_field_id=seeds["cost_center"],
        custom_field_value="Sales",
    )
    ids = _ids(out)
    assert str(seeds["inv2"]) in ids
    assert str(seeds["inv1"]) not in ids
    assert str(seeds["con1"]) not in ids
    db.rollback()
    db.close()
