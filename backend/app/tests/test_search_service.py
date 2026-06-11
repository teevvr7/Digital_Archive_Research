"""Search service tests — full-text content + fuzzy filename ranking.

Runs ``search_documents`` under the same ``SET LOCAL ROLE authenticated`` + tenant
GUC path the API uses, against a real Postgres (RLS enforced). Seeds two completed
documents with known ``extracted_text`` and a populated ``search_tsv``.

Requires ALEMBIC_DATABASE_URL (loaded from .env by conftest). Skipped when absent.
Run: ``pytest app/tests/test_search_service.py -v``
"""

import os
import uuid

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

pytestmark = pytest.mark.skipif(
    not os.environ.get("ALEMBIC_DATABASE_URL"),
    reason="ALEMBIC_DATABASE_URL not set — skipping DB-backed search tests",
)

DB_URL = os.environ.get("ALEMBIC_DATABASE_URL", "")

# Doc A — filename words: quarterly/revenue/report; content: electricity/consumption/schedule
_A_FILENAME = "Quarterly Revenue Report.pdf"
_A_TEXT = "Total electricity consumption rose; final schedule attached."
# Doc B — filename words: vendor/contract/agreement; content has "schedule" twice
# (denser than doc A) so it outranks doc A on a "schedule" query.
_B_FILENAME = "Vendor Contract Agreement.pdf"
_B_TEXT = "The maintenance schedule and the cleaning schedule are reviewed weekly."


@pytest.fixture(scope="module")
def direct_engine():
    engine = create_engine(DB_URL, future=True)
    yield engine
    engine.dispose()


@pytest.fixture(scope="module")
def seeds(direct_engine):
    """Seed one tenant + user + two completed docs with populated search_tsv."""
    t_id = uuid.uuid4()
    u_id = uuid.uuid4()
    a_id, b_id = uuid.uuid4(), uuid.uuid4()

    insert_doc = text(
        "INSERT INTO documents (id, tenant_id, uploaded_by, filename, original_filename,"
        " mime_type, size_bytes, storage_key, document_type, status, extracted_text, search_tsv)"
        " VALUES (:id, :tid, :uid, :fn, :ofn, 'application/pdf', 1000, :sk, :dtype, 'completed',"
        " :etext, to_tsvector('english', :tsv)) ON CONFLICT DO NOTHING"
    )

    with direct_engine.connect() as conn:
        conn.execute(text("SET session_replication_role = 'replica'"))
        conn.execute(
            text("INSERT INTO tenants (id, name) VALUES (:id, :name) ON CONFLICT DO NOTHING"),
            {"id": str(t_id), "name": "Search-T"},
        )
        conn.execute(
            text(
                "INSERT INTO users (id, tenant_id, email, name)"
                " VALUES (:id, :tid, :email, :name) ON CONFLICT DO NOTHING"
            ),
            {"id": str(u_id), "tid": str(t_id), "email": "s@t.com", "name": "Search User"},
        )
        for did, ofn, dtype, etext in [
            (a_id, _A_FILENAME, "report", _A_TEXT),
            (b_id, _B_FILENAME, "contract", _B_TEXT),
        ]:
            conn.execute(
                insert_doc,
                {
                    "id": str(did),
                    "tid": str(t_id),
                    "uid": str(u_id),
                    "fn": ofn,
                    "ofn": ofn,
                    "sk": f"{t_id}/docs/{did}.pdf",
                    "dtype": dtype,
                    "etext": etext,
                    "tsv": f"{ofn} {etext}",
                },
            )
        conn.execute(text("SET session_replication_role = 'origin'"))
        conn.commit()

    yield {"t": t_id, "u": u_id, "a": a_id, "b": b_id}

    with direct_engine.connect() as conn:
        conn.execute(text("SET session_replication_role = 'replica'"))
        for did in (a_id, b_id):
            conn.execute(text("DELETE FROM documents WHERE id = :id"), {"id": str(did)})
        conn.execute(text("DELETE FROM users WHERE id = :id"), {"id": str(u_id)})
        conn.execute(text("DELETE FROM tenants WHERE id = :id"), {"id": str(t_id)})
        conn.execute(text("SET session_replication_role = 'origin'"))
        conn.commit()


def _search_session(engine, tenant_id: uuid.UUID):
    """A session with the authenticated role + tenant GUC set (RLS enforced)."""
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
    return {str(item.document.id) for item in out.items}


def test_content_search_matches_extracted_text(direct_engine, seeds):
    """A word that lives only in the extracted text returns that doc with a snippet."""
    from app.modules.search import service

    db = _search_session(direct_engine, seeds["t"])
    out = service.search_documents(db, q="electricity consumption")
    ids = _ids(out)
    assert str(seeds["a"]) in ids
    assert str(seeds["b"]) not in ids
    hit = next(i for i in out.items if str(i.document.id) == str(seeds["a"]))
    assert "content" in hit.matched_fields
    assert hit.snippet and "<mark>" in hit.snippet
    db.rollback()
    db.close()


def test_fuzzy_filename_typo_matches(direct_engine, seeds):
    """A misspelled filename word matches via pg_trgm word similarity (not FTS).

    Threshold is lowered for a deterministic assertion; production uses the
    pg_trgm default. 'quartrly' is a typo of 'quarterly' (in doc A's filename
    only) and is not a valid FTS lexeme for it, so this exercises the trigram path.
    """
    from app.modules.search import service

    db = _search_session(direct_engine, seeds["t"])
    db.execute(text("SET LOCAL pg_trgm.word_similarity_threshold = 0.2"))
    out = service.search_documents(db, q="quartrly")
    ids = _ids(out)
    assert str(seeds["a"]) in ids
    hit = next(i for i in out.items if str(i.document.id) == str(seeds["a"]))
    assert "filename" in hit.matched_fields
    db.rollback()
    db.close()


def test_ranking_orders_stronger_match_first(direct_engine, seeds):
    """Both docs contain 'schedule'; doc B has it twice → B ranks first."""
    from app.modules.search import service

    db = _search_session(direct_engine, seeds["t"])
    out = service.search_documents(db, q="schedule")
    ids = _ids(out)
    assert {str(seeds["a"]), str(seeds["b"])} <= ids
    assert str(out.items[0].document.id) == str(seeds["b"])
    db.rollback()
    db.close()


def test_type_filter_narrows_results(direct_engine, seeds):
    """'schedule' matches both docs; type=report keeps only doc A."""
    from app.modules.search import service

    db = _search_session(direct_engine, seeds["t"])
    out = service.search_documents(db, q="schedule", type_filter="report")
    ids = _ids(out)
    assert ids == {str(seeds["a"])}
    db.rollback()
    db.close()


def test_empty_query_returns_no_results(direct_engine, seeds):
    """A blank query short-circuits to an empty result set."""
    from app.modules.search import service

    db = _search_session(direct_engine, seeds["t"])
    out = service.search_documents(db, q="   ")
    assert out.total == 0 and out.items == []
    db.rollback()
    db.close()


def test_no_match_returns_empty(direct_engine, seeds):
    """A term present in neither filename nor content returns nothing."""
    from app.modules.search import service

    db = _search_session(direct_engine, seeds["t"])
    out = service.search_documents(db, q="zxqwvnomatchxyz")
    assert out.total == 0
    db.rollback()
    db.close()
