"""Tests for the Sentry init guard.

The pipeline must never depend on an external monitoring service being
configured (root CLAUDE.md: "degrade gracefully, don't error"), so the no-DSN
no-op path is the one behavior worth locking down here — everything else is
sentry_sdk's own responsibility.
"""

from unittest.mock import MagicMock, patch

from app.core import monitoring


def test_noop_when_dsn_unset(monkeypatch):
    monkeypatch.setattr(monitoring.settings, "sentry_dsn", "")
    monitoring._initialized = False

    with patch("sentry_sdk.init") as mock_init:
        monitoring.init_sentry("api")

    mock_init.assert_not_called()
    assert monitoring._initialized is False


def test_initializes_once_when_dsn_set(monkeypatch):
    monkeypatch.setattr(monitoring.settings, "sentry_dsn", "https://example@sentry.io/1")
    monitoring._initialized = False

    with patch("sentry_sdk.init") as mock_init, patch("sentry_sdk.set_tag") as mock_tag:
        monitoring.init_sentry("worker")
        monitoring.init_sentry("worker")  # second call must be a no-op

    mock_init.assert_called_once()
    kwargs = mock_init.call_args.kwargs
    assert kwargs["send_default_pii"] is False
    assert kwargs["include_local_variables"] is False
    mock_tag.assert_called_once_with("component", "worker")
    assert monitoring._initialized is True

    # Reset shared module state so this test doesn't leak into others.
    monitoring._initialized = False
