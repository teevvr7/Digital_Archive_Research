"""Trash auto-retention tests (critical — includes a tenant-isolation check).

Runs the opportunistic purge (``files/retention.py::maybe_purge_expired_trash``)
against a real Postgres (RLS enforced), the same way ``test_search_tenant_isolation.py``
proves search stays fenced. T1 has a 10-day retention override, T2 uses the
global default — each owns one trashed doc old enough to be expired under ANY
plausible retention window (400 days) and one recent enough to survive any
plausible window (1 day), so the assertions don't couple to whatever
``settings.trash_retention_days_default`` happens to resolve to in this env.

Requires ALEMBIC_DATABASE_URL (loaded from .env by conftest). Skipped when absent.
Run: ``pytest app/tests/test_trash_retention.py -v``
"""

import datetime
import os
import uuid
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import sessionmaker

pytestmark = pytest.mark.skipif(
    not os.environ.get("ALEMBIC_DATABASE_URL"),
    reason="ALEMBIC_DATABASE_URL not set — skipping DB-backed retention tests",
)

DB_URL = os.environ.get("ALEMBIC_DATABASE_URL", "")

_NOW = datetime.datetime.now(datetime.timezone.utc)
_VERY_EXPIRED = _NOW - datetime.timedelta(days=400)  # past any plausible retention window
_RECENT = _NOW - datetime.timedelta(days=1)  # within any plausible retention window
_DOC_SIZE = 5000

_INSERT_DOC = text(
    "INSERT INTO documents (id, tenant_id, uploaded_by, filename, original_filename,"
    " title, mime_type, size_bytes, storage_key, document_type, status, deleted_at)"
    " VALUES (:id, :tid, :uid, :fn, :fn, :fn, 'application/pdf', :size, :sk, 'other',"
    " 'completed', :deleted_at) ON CONFLICT DO NOTHING"
)


def _seed_tenant(conn, tenant_id: uuid.UUID, name: str, *, retention_override: int | None) -> None:
    conn.execute(
        text(
            "INSERT INTO tenants (id, name, storage_used_bytes, trash_retention_days)"
            " VALUES (:id, :name, :used, :override) ON CONFLICT DO NOTHING"
        ),
        {"id": str(tenant_id), "name": name, "used": _DOC_SIZE * 2, "override": retention_override},
    )


def _seed_user(conn, user_id: uuid.UUID, tenant_id: uuid.UUID, email: str) -> None:
    conn.execute(
        text(
            "INSERT INTO users (id, tenant_id, email, name)"
            " VALUES (:id, :tid, :email, :name) ON CONFLICT DO NOTHING"
        ),
        {"id": str(user_id), "tid": str(tenant_id), "email": email, "name": email},
    )


def _seed_doc(conn, doc_id, tenant_id, user_id, filename: str, deleted_at) -> None:
    conn.execute(
        _INSERT_DOC,
        {
            "id": str(doc_id),
            "tid": str(tenant_id),
            "uid": str(user_id),
            "fn": filename,
            "size": _DOC_SIZE,
            "sk": f"{tenant_id}/docs/{doc_id}.pdf",
            "deleted_at": deleted_at,
        },
    )


def _tenant_session(engine, tenant_id: uuid.UUID):
    Session = sessionmaker(bind=engine, autocommit=False)
    db = Session()
    db.begin()
    db.execute(text("SET LOCAL ROLE authenticated"))
    db.execute(
        text("SELECT set_config('app.current_tenant', :tid, true)"),
        {"tid": str(tenant_id)},
    )
    return db


def _existing_doc_ids(db) -> set[str]:
    from app.models.document import Document

    return {str(row) for row in db.scalars(select(Document.id))}


@pytest.fixture(scope="module")
def direct_engine():
    engine = create_engine(DB_URL, future=True)
    yield engine
    engine.dispose()


@pytest.fixture(scope="module")
def seeds(direct_engine):
    """Two tenants, each with one expired-trash doc and one recent-trash doc.
    T1 gets a 10-day override; T2 is left NULL (uses the global default).
    Every test in this module rolls back its own mutations, so this shared
    seed data stays pristine across tests."""
    t1_id, t2_id = uuid.uuid4(), uuid.uuid4()
    u1_id, u2_id = uuid.uuid4(), uuid.uuid4()
    d1_expired, d1_recent = uuid.uuid4(), uuid.uuid4()
    d2_expired, d2_recent = uuid.uuid4(), uuid.uuid4()

    with direct_engine.connect() as conn:
        conn.execute(text("SET session_replication_role = 'replica'"))
        _seed_tenant(conn, t1_id, "Retention-T1", retention_override=10)
        _seed_tenant(conn, t2_id, "Retention-T2", retention_override=None)
        _seed_user(conn, u1_id, t1_id, "ret1@t1.com")
        _seed_user(conn, u2_id, t2_id, "ret2@t2.com")
        _seed_doc(conn, d1_expired, t1_id, u1_id, "t1_expired.pdf", _VERY_EXPIRED)
        _seed_doc(conn, d1_recent, t1_id, u1_id, "t1_recent.pdf", _RECENT)
        _seed_doc(conn, d2_expired, t2_id, u2_id, "t2_expired.pdf", _VERY_EXPIRED)
        _seed_doc(conn, d2_recent, t2_id, u2_id, "t2_recent.pdf", _RECENT)
        conn.execute(text("SET session_replication_role = 'origin'"))
        conn.commit()

    yield {
        "t1": t1_id,
        "t2": t2_id,
        "d1_expired": d1_expired,
        "d1_recent": d1_recent,
        "d2_expired": d2_expired,
        "d2_recent": d2_recent,
    }

    with direct_engine.connect() as conn:
        conn.execute(text("SET session_replication_role = 'replica'"))
        for did in (d1_expired, d1_recent, d2_expired, d2_recent):
            conn.execute(text("DELETE FROM documents WHERE id = :id"), {"id": str(did)})
        conn.execute(
            text("DELETE FROM activity_events WHERE tenant_id IN (:t1, :t2)"),
            {"t1": str(t1_id), "t2": str(t2_id)},
        )
        for uid in (u1_id, u2_id):
            conn.execute(text("DELETE FROM users WHERE id = :id"), {"id": str(uid)})
        for tid in (t1_id, t2_id):
            conn.execute(text("DELETE FROM tenants WHERE id = :id"), {"id": str(tid)})
        conn.execute(text("SET session_replication_role = 'origin'"))
        conn.commit()


@patch("app.modules.files.retention.object_storage.delete_file")
def test_purges_expired_and_keeps_recent(mock_delete, direct_engine, seeds):
    from app.modules.files import retention

    db = _tenant_session(direct_engine, seeds["t1"])
    purged = retention.maybe_purge_expired_trash(db, seeds["t1"])
    db.flush()

    assert purged == 1
    remaining = _existing_doc_ids(db)
    assert str(seeds["d1_expired"]) not in remaining
    assert str(seeds["d1_recent"]) in remaining
    db.rollback()
    db.close()


@patch("app.modules.files.retention.object_storage.delete_file")
def test_decrements_storage_used_bytes(mock_delete, direct_engine, seeds):
    from app.models.tenant import Tenant
    from app.modules.files import retention

    db = _tenant_session(direct_engine, seeds["t2"])
    before = db.scalar(select(Tenant.storage_used_bytes).where(Tenant.id == seeds["t2"]))
    retention.maybe_purge_expired_trash(db, seeds["t2"])
    db.flush()
    after = db.scalar(select(Tenant.storage_used_bytes).where(Tenant.id == seeds["t2"]))

    assert after == before - _DOC_SIZE
    db.rollback()
    db.close()


@patch("app.modules.files.retention.object_storage.delete_file")
def test_records_one_summary_activity_event(mock_delete, direct_engine, seeds):
    from app.models.activity_event import ACT_PERMANENT_DELETE, ActivityEvent
    from app.modules.files import retention

    db = _tenant_session(direct_engine, seeds["t1"])
    retention.maybe_purge_expired_trash(db, seeds["t1"])
    db.flush()

    events = db.scalars(
        select(ActivityEvent).where(
            ActivityEvent.tenant_id == seeds["t1"], ActivityEvent.type == ACT_PERMANENT_DELETE
        )
    ).all()
    assert len(events) == 1
    assert events[0].user_id is None
    assert events[0].user_name == "system"
    assert "1 document" in events[0].meta
    db.rollback()
    db.close()


@patch("app.modules.files.retention.object_storage.delete_file")
def test_rate_limited_second_call_is_a_noop(mock_delete, direct_engine, seeds):
    from app.modules.files import retention

    db = _tenant_session(direct_engine, seeds["t1"])
    first = retention.maybe_purge_expired_trash(db, seeds["t1"])
    second = retention.maybe_purge_expired_trash(db, seeds["t1"])

    assert first == 1
    assert second == 0  # trash_last_purged_at was just set — too soon to check again
    db.rollback()
    db.close()


def test_effective_retention_days_resolves_override_and_default(direct_engine, seeds):
    from app.core.config import settings
    from app.models.tenant import Tenant
    from app.modules.files import retention

    db = _tenant_session(direct_engine, seeds["t1"])
    t1 = db.scalars(select(Tenant).where(Tenant.id == seeds["t1"])).first()
    assert retention.effective_retention_days(t1) == 10
    db.rollback()
    db.close()

    db = _tenant_session(direct_engine, seeds["t2"])
    t2 = db.scalars(select(Tenant).where(Tenant.id == seeds["t2"])).first()
    assert retention.effective_retention_days(t2) == settings.trash_retention_days_default
    db.rollback()
    db.close()


@patch("app.modules.files.retention.object_storage.delete_file")
def test_sweeping_one_tenant_never_touches_the_other(mock_delete, direct_engine):
    """Critical: purging one tenant's expired trash must never delete another
    tenant's documents — even though both have expired trash waiting.

    Uses its own dedicated, COMMITTED seed data (rather than the shared
    ``seeds`` fixture) because proving a negative here requires the mutation
    to actually persist: a rollback-based check can't distinguish "the bug
    never happened" from "the bug happened and rollback erased the evidence".
    RLS also means tenant A's session can't just query tenant B's rows to
    check them — visibility itself is denied — so verification goes through
    a superuser bypass connection instead, the same trick the fixtures use
    for setup/teardown.
    """
    from app.modules.files import retention

    engine = create_engine(DB_URL, future=True)
    a_id, b_id = uuid.uuid4(), uuid.uuid4()
    ua_id, ub_id = uuid.uuid4(), uuid.uuid4()
    doc_a, doc_b = uuid.uuid4(), uuid.uuid4()

    try:
        with engine.connect() as conn:
            conn.execute(text("SET session_replication_role = 'replica'"))
            _seed_tenant(conn, a_id, "Isolation-A", retention_override=1)
            _seed_tenant(conn, b_id, "Isolation-B", retention_override=1)
            _seed_user(conn, ua_id, a_id, "isoa@a.com")
            _seed_user(conn, ub_id, b_id, "isob@b.com")
            _seed_doc(conn, doc_a, a_id, ua_id, "a_expired.pdf", _VERY_EXPIRED)
            _seed_doc(conn, doc_b, b_id, ub_id, "b_expired.pdf", _VERY_EXPIRED)
            conn.execute(text("SET session_replication_role = 'origin'"))
            conn.commit()

        db_a = _tenant_session(engine, a_id)
        purged = retention.maybe_purge_expired_trash(db_a, a_id)
        db_a.commit()
        db_a.close()
        assert purged == 1

        with engine.connect() as conn:
            conn.execute(text("SET session_replication_role = 'replica'"))
            still_there = conn.execute(
                text("SELECT id FROM documents WHERE id = :id"), {"id": str(doc_b)}
            ).first()
            assert still_there is not None, "Tenant A's sweep must not delete Tenant B's document"
            conn.execute(text("SET session_replication_role = 'origin'"))
    finally:
        with engine.connect() as conn:
            conn.execute(text("SET session_replication_role = 'replica'"))
            for did in (doc_a, doc_b):
                conn.execute(text("DELETE FROM documents WHERE id = :id"), {"id": str(did)})
            conn.execute(
                text("DELETE FROM activity_events WHERE tenant_id IN (:a, :b)"),
                {"a": str(a_id), "b": str(b_id)},
            )
            for uid in (ua_id, ub_id):
                conn.execute(text("DELETE FROM users WHERE id = :id"), {"id": str(uid)})
            for tid in (a_id, b_id):
                conn.execute(text("DELETE FROM tenants WHERE id = :id"), {"id": str(tid)})
            conn.execute(text("SET session_replication_role = 'origin'"))
            conn.commit()
        engine.dispose()
