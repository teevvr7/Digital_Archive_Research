"""IDP worker tenant isolation test.

Verifies that ``process_document`` running under T1's tenant context cannot
read or update a document belonging to T2 — even though the worker uses the
same ``tenant_session`` mechanism as the API.

Reuses the same ``SET LOCAL ROLE authenticated`` + GUC pattern as
``test_tenant_isolation.py`` because the fix must hold for the worker path too.

Run: ``pytest app/tests/test_idp_tenant_isolation.py -v``

Requires ALEMBIC_DATABASE_URL. Skipped when absent.
"""

import os
import uuid
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

pytestmark = pytest.mark.skipif(
    not os.environ.get("ALEMBIC_DATABASE_URL"),
    reason="ALEMBIC_DATABASE_URL not set — skipping isolation tests",
)

DB_URL = os.environ.get("ALEMBIC_DATABASE_URL", "")


@pytest.fixture(scope="module")
def direct_engine():
    engine = create_engine(DB_URL, future=True)
    yield engine
    engine.dispose()


@pytest.fixture(scope="module")
def seeds(direct_engine):
    """Seed two tenants, users, and documents for isolation probing."""
    t1_id, t2_id = uuid.uuid4(), uuid.uuid4()
    u1_id, u2_id = uuid.uuid4(), uuid.uuid4()
    d1_id, d2_id = uuid.uuid4(), uuid.uuid4()

    with direct_engine.connect() as conn:
        conn.execute(text("SET session_replication_role = 'replica'"))
        for tid, name in [(t1_id, "IDP-T1"), (t2_id, "IDP-T2")]:
            conn.execute(
                text("INSERT INTO tenants (id, name) VALUES (:id, :name) ON CONFLICT DO NOTHING"),
                {"id": str(tid), "name": name},
            )
        for uid, tid, email in [(u1_id, t1_id, "idp1@t1.com"), (u2_id, t2_id, "idp2@t2.com")]:
            conn.execute(
                text(
                    "INSERT INTO users (id, tenant_id, email, name)"
                    " VALUES (:id, :tid, :email, :name) ON CONFLICT DO NOTHING"
                ),
                {"id": str(uid), "tid": str(tid), "email": email, "name": email},
            )
        for did, tid, uid, fname in [
            (d1_id, t1_id, u1_id, "idp_doc_t1.pdf"),
            (d2_id, t2_id, u2_id, "idp_doc_t2.pdf"),
        ]:
            conn.execute(
                text(
                    "INSERT INTO documents (id, tenant_id, uploaded_by, filename,"
                    " original_filename, mime_type, size_bytes, storage_key, document_type)"
                    " VALUES (:id, :tid, :uid, :fn, :fn, 'application/pdf', 1000, :sk, 'other')"
                    " ON CONFLICT DO NOTHING"
                ),
                {"id": str(did), "tid": str(tid), "uid": str(uid), "fn": fname,
                 "sk": f"{tid}/docs/{did}.pdf"},
            )
        conn.execute(text("SET session_replication_role = 'origin'"))
        conn.commit()

    yield {"t1": t1_id, "t2": t2_id, "u1": u1_id, "u2": u2_id, "d1": d1_id, "d2": d2_id}

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


def test_worker_cannot_see_other_tenant_document(direct_engine, seeds):
    """tenant_session(T1) + SELECT on T2's doc id → None (RLS blocks it)."""
    from sqlalchemy import select
    from app.models.document import Document

    Session = sessionmaker(bind=direct_engine, autocommit=False)
    db = Session()
    db.begin()
    db.execute(text("SET LOCAL ROLE authenticated"))
    db.execute(
        text("SELECT set_config('app.current_tenant', :tid, true)"),
        {"tid": str(seeds["t1"])},
    )
    doc = db.get(Document, seeds["d2"])
    assert doc is None, "RLS should have hidden T2's document from T1"
    db.rollback()
    db.close()


def test_worker_update_t2_doc_under_t1_guc_affects_zero_rows(direct_engine, seeds):
    """UPDATE on T2's document under T1 GUC silently affects 0 rows."""
    Session = sessionmaker(bind=direct_engine, autocommit=False)
    db = Session()
    db.begin()
    db.execute(text("SET LOCAL ROLE authenticated"))
    db.execute(
        text("SELECT set_config('app.current_tenant', :tid, true)"),
        {"tid": str(seeds["t1"])},
    )
    result = db.execute(
        text("UPDATE documents SET status = 'completed' WHERE id = :id"),
        {"id": str(seeds["d2"])},
    )
    assert result.rowcount == 0
    db.rollback()
    db.close()


def test_process_document_raises_when_doc_not_found(seeds):
    """process_document raises LookupError for an unknown doc_id (not in tenant)."""
    from app.modules.idp.jobs import process_document

    fake_doc_id = str(uuid.uuid4())

    # We don't actually connect to DB in this test — we patch tenant_session to
    # simulate the "document not visible under this tenant" outcome.
    mock_db = MagicMock()
    mock_db.get.return_value = None  # simulates RLS returning no row

    with patch("app.modules.idp.jobs.tenant_session") as mock_ctx:
        mock_ctx.return_value.__enter__.return_value = mock_db
        mock_ctx.return_value.__exit__.return_value = False

        with pytest.raises(LookupError):
            process_document(fake_doc_id, str(seeds["t1"]))
