"""Error monitoring (Sentry) — shared init for both the API process and the
worker process. A no-op whenever ``SENTRY_DSN`` is unset (local dev, or a
deployment that hasn't been given a DSN yet) so this never becomes a hard
dependency on an external service.

Never log secrets or document text (root CLAUDE.md). Two Sentry defaults would
violate that on their own, so both are explicitly overridden below:
- ``send_default_pii`` defaults to sending request headers/IPs — off here.
- ``include_local_variables`` defaults to True, meaning a crash inside e.g.
  the IDP pipeline would ship the local stack frame's variables (which can
  hold raw extracted document text or file bytes) to Sentry — off here too.
"""

import logging

from app.core.config import settings

logger = logging.getLogger(__name__)

_initialized = False


def init_sentry(component: str) -> None:
    """Initialize Sentry once per process. ``component`` tags events as
    originating from ``"api"`` or ``"worker"`` so they can be told apart in
    the Sentry UI. Safe to call multiple times — only the first call with a
    configured DSN takes effect."""
    global _initialized
    if _initialized or not settings.sentry_dsn:
        return

    import sentry_sdk

    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        environment=settings.env,
        # Conservative default — trace sampling is a cost knob, not a
        # correctness one; start low and raise it later if needed.
        traces_sample_rate=0.1,
        send_default_pii=False,
        include_local_variables=False,
    )
    sentry_sdk.set_tag("component", component)
    _initialized = True
    logger.info("Sentry initialized (component=%s, env=%s)", component, settings.env)
