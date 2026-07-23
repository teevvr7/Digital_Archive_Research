"""Tests for the security-headers middleware (app/core/security_headers.py).

Uses a real TestClient against the actual app import, hitting the
dependency-free ``/api/health`` route — no DB needed.
"""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_security_headers_present_on_every_response():
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.headers["x-content-type-options"] == "nosniff"
    assert resp.headers["x-frame-options"] == "DENY"
    assert resp.headers["referrer-policy"] == "strict-origin-when-cross-origin"
    assert resp.headers["cross-origin-opener-policy"] == "same-origin"
    assert "camera=()" in resp.headers["permissions-policy"]
    assert resp.headers["content-security-policy"] == "default-src 'none'; frame-ancestors 'none'"


def test_hsts_only_set_in_production(monkeypatch):
    from app.core import security_headers

    monkeypatch.setattr(security_headers.settings, "env", "production")
    resp = client.get("/api/health")
    assert "strict-transport-security" in resp.headers

    monkeypatch.setattr(security_headers.settings, "env", "development")
    resp = client.get("/api/health")
    assert "strict-transport-security" not in resp.headers


def test_docs_path_is_exempt_from_the_strict_csp():
    """Swagger UI loads its own JS/CSS from a CDN — a locked-down CSP would
    break it, so the docs paths are deliberately excluded (main.py gates them
    off entirely in production, so this only matters in dev)."""
    resp = client.get("/api/docs")
    assert resp.status_code == 200
    assert "content-security-policy" not in resp.headers
