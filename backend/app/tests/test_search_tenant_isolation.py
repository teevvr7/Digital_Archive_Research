"""Search tenant-isolation test (critical).

Two tenants each own a document whose extracted text contains the *same* search
term. Searching under T1's context must return only T1's document — never T2's —
even though both match the query. Proves RLS fences the search path exactly like
list/upload.

Requires ALEMBIC_DATABASE_URL (loaded from .env by conftest). Skipped when absent.
Run: ``pytest app/tests/test_search_tenant_isolation.py -v``
"""

import os
import uuid

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

pytestmark = pytest.mark.skipif(
    not os.environ.get("ALEMBIC_DATABASE_URL"),
    reason="ALEMBIC_DATABASE_URL not set — skipping isolation tests",
)

DB_URL = os.environ.get("ALEMBIC_DATABASE_URL", "")

# Both tenants' docs share this term — only RLS keeps them apart.
_SHARED_TEXT = "Confidential acquisition memorandum for internal review only."


@pytest.fixture(scope="module")
def direct_engine():
    engine = create_engine(DB_URL, future=True)
    yield engine
    engine.dispose()


@pytest.fixture(scope="module")
def seeds(direct_engine):
    t1_id, t2_id = uuid.uuid4(), uuid.uuid4()
    u1_id, u2_id = uuid.uuid4(), uuid.uuid4()
    d1_id, d2_id = uuid.uuid4(), uuid.uuid4()

    insert_doc = text(
        "INSERT INTO documents (id, tenant_id, uploaded_by, filename, original_filename,"
        " mime_type, size_bytes, storage_key, document_type, status, extracted_text, search_tsv)"
        " VALUES (:id, :tid, :uid, :fn, :fn, 'application/pdf', 1000, :sk, 'other', 'completed',"
        " :etext, to_tsvector('english', :tsv)) ON CONFLICT DO NOTHING"
    )

    with direct_engine.connect() as conn:
        conn.execute(text("SET session_replication_role = 'replica'"))
        for tid, name in [(t1_id, "Search-Iso-T1"), (t2_id, "Search-Iso-T2")]:
            conn.execute(
                text("INSERT INTO tenants (id, name) VALUES (:id, :name) ON CONFLICT DO NOTHING"),
                {"id": str(tid), "name": name},
            )
        for uid, tid, email in [(u1_id, t1_id, "siso1@t1.com"), (u2_id, t2_id, "siso2@t2.com")]:
            conn.execute(
                text(
                    "INSERT INTO users (id, tenant_id, email, name)"
                    " VALUES (:id, :tid, :email, :name) ON CONFLICT DO NOTHING"
                ),
                {"id": str(uid), "tid": str(tid), "email": email, "name": email},
            )
        for did, tid, uid, fname in [
            (d1_id, t1_id, u1_id, "memo_t1.pdf"),
            (d2_id, t2_id, u2_id, "memo_t2.pdf"),
        ]:
            conn.execute(
                insert_doc,
                {
                    "id": str(did),
                    "tid": str(tid),
                    "uid": str(uid),
                    "fn": fname,
                    "sk": f"{tid}/docs/{did}.pdf",
                    "etext": _SHARED_TEXT,
                    "tsv": f"{fname} {_SHARED_TEXT}",
                },
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


def _search_session(engine, tenant_id: uuid.UUID):
    Session = sessionmaker(bind=engine, autocommit=False)
    db = Session()
    db.begin()
    db.execute(text("SET LOCAL ROLE authenticated"))
    db.execute(
        text("SELECT set_config('app.current_tenant', :tid, true)"),
        {"tid": str(tenant_id)},
    )
    return db


def test_search_returns_only_own_tenant_docs(direct_engine, seeds):
    """T1 searching the shared term sees its own doc, never T2's."""
    from app.modules.search import service

    db = _search_session(direct_engine, seeds["t1"])
    out = service.search_documents(db, q="confidential acquisition")
    ids = {str(item.document.id) for item in out.items}
    assert str(seeds["d1"]) in ids, "T1 should find its own matching document"
    assert str(seeds["d2"]) not in ids, "RLS must hide T2's document from T1's search"
    db.rollback()
    db.close()
