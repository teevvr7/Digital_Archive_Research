"""Regression test for a real route-collision bug found via live QA (2026-07-27).

``GET /documents/export`` and ``GET /documents/{doc_id}`` are both GET routes
under the same prefix, defined in two different router modules
(export/router.py and files/router.py). Starlette matches routes in
registration order, so whichever router is ``include_router``-ed first wins
any literal-vs-path-param collision. With files_router registered before
export_router, every export request was silently swallowed by
``get_document(doc_id="export")``, which failed UUID parsing and returned a
misleading 422 — the export feature was completely broken with no test
catching it, because every existing export test calls the service layer
directly and never resolves a route through the real app.

Uses a real TestClient against the actual app import (no DB) — this only
needs to prove which handler matches, not exercise its logic.
"""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_documents_export_route_does_not_collide_with_doc_id_route():
    # No Authorization header: if this resolves to export_documents(), the
    # auth dependency rejects it with 401. If it were swallowed by
    # get_document(doc_id=...) instead, "export" would fail UUID parsing
    # first and return 422 — the exact bug this test guards against.
    resp = client.get("/api/documents/export")
    assert resp.status_code == 401, (
        f"expected 401 (reached export_documents' auth check), got "
        f"{resp.status_code}: {resp.text} — /documents/export may be "
        f"colliding with /documents/{{doc_id}} again"
    )
