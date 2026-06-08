"""Tenant isolation test — the non-negotiable RLS gate.

Seeds two tenants (T1, T2) each with a user and a document via a direct
(owner/bypass) connection, then verifies that every read/write path through the
app-role GUC mechanism correctly isolates them.

Run: ``pytest app/tests/test_tenant_isolation.py -v``

Requires ALEMBIC_DATABASE_URL to point at a real Postgres instance with the
migrations applied. Skipped automatically when the env var is absent so CI
environments that don't have a DB still pass.
"""

import os
import uuid

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

# Skip entirely if no DB is configured.
pytestmark = pytest.mark.skipif(
    not os.environ.get("ALEMBIC_DATABASE_URL"),
    reason="ALEMBIC_DATABASE_URL not set — skipping isolation tests",
)

DB_URL = os.environ.get("ALEMBIC_DATABASE_URL", "")


@pytest.fixture(scope="module")
def direct_engine():
    """A direct DB connection that bypasses RLS (owner role) for seeding/teardown."""
    engine = create_engine(DB_URL, future=True)
    yield engine
    engine.dispose()


@pytest.fixture(scope="module")
def seeds(direct_engine):
    """Seed T1 and T2 with one user and one document each. Clean up after."""
    t1_id, t2_id = uuid.uuid4(), uuid.uuid4()
    u1_id, u2_id = uuid.uuid4(), uuid.uuid4()
    d1_id, d2_id = uuid.uuid4(), uuid.uuid4()

    with direct_engine.connect() as conn:
        conn.execute(text("SET session_replication_role = 'replica'"))  # skip FK checks for seed
        for tid, name in [(t1_id, "Tenant One"), (t2_id, "Tenant Two")]:
            conn.execute(text(
                "INSERT INTO tenants (id, name) VALUES (:id, :name) ON CONFLICT DO NOTHING"
            ), {"id": str(tid), "name": name})
        for uid, tid, email in [
            (u1_id, t1_id, "user1@t1.com"),
            (u2_id, t2_id, "user2@t2.com"),
        ]:
            conn.execute(text(
                "INSERT INTO users (id, tenant_id, email, name) VALUES (:id, :tid, :email, :name)"
                " ON CONFLICT DO NOTHING"
            ), {"id": str(uid), "tid": str(tid), "email": email, "name": email})
        for did, tid, uid, fname in [
            (d1_id, t1_id, u1_id, "doc_t1.pdf"),
            (d2_id, t2_id, u2_id, "doc_t2.pdf"),
        ]:
            conn.execute(text(
                "INSERT INTO documents (id, tenant_id, uploaded_by, filename, original_filename,"
                " mime_type, size_bytes, storage_key, document_type)"
                " VALUES (:id, :tid, :uid, :fn, :fn, 'application/pdf', 1000,"
                " :sk, 'other') ON CONFLICT DO NOTHING"
            ), {"id": str(did), "tid": str(tid), "uid": str(uid), "fn": fname,
                "sk": f"{tid}/docs/{did}.pdf"})
        conn.execute(text("SET session_replication_role = 'origin'"))
        conn.commit()

    yield {"t1": t1_id, "t2": t2_id, "u1": u1_id, "u2": u2_id, "d1": d1_id, "d2": d2_id}

    # Cleanup
    with direct_engine.connect() as conn:
        conn.execute(text("SET session_replication_role = 'replica'"))
        for did in (d1_id, d2_id):
            conn.execute(text("DELETE FROM documents WHERE id = :id"), {"id": str(did)})
        for uid in (u1_id, u2_id):
            conn.execute(text("DELETE FROM users WHERE id = :id"), {"id": str(uid)})
        for tid in (t1_id, t2_id):
            conn.execute(text("DELETE FROM tenants WHERE id = :id"), {"id": str(tid)})
        conn.execute(text("SET session_replication_role = 'origin'"))
        conn.commit()


def _session_with_guc(engine, tenant_id: uuid.UUID | None):
    """Return a session with the tenant GUC set (or not set if tenant_id is None)."""
    Session = sessionmaker(bind=engine, autocommit=False)
    db = Session()
    db.begin()
    if tenant_id is not None:
        db.execute(
            text("SELECT set_config('app.current_tenant', :tid, true)"),
            {"tid": str(tenant_id)},
        )
    return db


def test_t1_sees_only_own_docs(direct_engine, seeds):
    """T1 GUC → only T1's document is visible."""
    db = _session_with_guc(direct_engine, seeds["t1"])
    rows = db.execute(text("SELECT id FROM documents")).fetchall()
    ids = {str(r[0]) for r in rows}
    assert str(seeds["d1"]) in ids
    assert str(seeds["d2"]) not in ids
    db.rollback(); db.close()


def test_t2_doc_invisible_under_t1(direct_engine, seeds):
    """T1 GUC → T2's document id returns no rows."""
    db = _session_with_guc(direct_engine, seeds["t1"])
    row = db.execute(
        text("SELECT id FROM documents WHERE id = :id"), {"id": str(seeds["d2"])}
    ).fetchone()
    assert row is None
    db.rollback(); db.close()


def test_insert_wrong_tenant_rejected(direct_engine, seeds):
    """WITH CHECK: inserting a document with T2's tenant_id under T1's GUC must fail."""
    db = _session_with_guc(direct_engine, seeds["t1"])
    try:
        db.execute(text(
            "INSERT INTO documents (id, tenant_id, uploaded_by, filename, original_filename,"
            " mime_type, size_bytes, storage_key, document_type)"
            " VALUES (:id, :bad_tid, :uid, 'bad.pdf', 'bad.pdf',"
            " 'application/pdf', 1, 'bad', 'other')"
        ), {"id": str(uuid.uuid4()), "bad_tid": str(seeds["t2"]), "uid": str(seeds["u1"])})
        db.flush()
        pytest.fail("Expected RLS WITH CHECK to reject cross-tenant INSERT")
    except Exception as exc:
        assert "policy" in str(exc).lower() or "check" in str(exc).lower() or "rls" in str(exc).lower(), str(exc)
    finally:
        db.rollback(); db.close()


def test_update_t2_doc_under_t1_affects_zero_rows(direct_engine, seeds):
    """UPDATE on T2's doc under T1's GUC silently affects 0 rows."""
    db = _session_with_guc(direct_engine, seeds["t1"])
    result = db.execute(
        text("UPDATE documents SET filename = 'hacked.pdf' WHERE id = :id"),
        {"id": str(seeds["d2"])},
    )
    assert result.rowcount == 0
    db.rollback(); db.close()


def test_no_guc_returns_zero_rows(direct_engine, seeds):
    """No GUC set → every tenant table returns 0 rows (fail-closed)."""
    db = _session_with_guc(direct_engine, None)
    for table in ("documents", "users", "tenants", "activity_events"):
        count = db.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar()  # noqa: S608
        assert count == 0, f"{table} returned rows with no GUC set"
    db.rollback(); db.close()


def test_t2_sees_only_own_docs(direct_engine, seeds):
    """T2 GUC → only T2's document is visible."""
    db = _session_with_guc(direct_engine, seeds["t2"])
    rows = db.execute(text("SELECT id FROM documents")).fetchall()
    ids = {str(r[0]) for r in rows}
    assert str(seeds["d2"]) in ids
    assert str(seeds["d1"]) not in ids
    db.rollback(); db.close()
