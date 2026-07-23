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

# A standard Python logger for this module, named after it (app.core.monitoring).
logger = logging.getLogger(__name__)

# Module-level flag so init_sentry() can be called many times (both main.py
# and worker.py call it) without actually re-initializing Sentry more than once.
_initialized = False


def init_sentry(component: str) -> None:
    """Initialize Sentry once per process. ``component`` tags events as
    originating from ``"api"`` or ``"worker"`` so they can be told apart in
    the Sentry UI. Safe to call multiple times — only the first call with a
    configured DSN takes effect."""
    # `global` so we can update the module-level flag from inside this function.
    global _initialized
    # Bail out immediately if Sentry is already set up, OR if no DSN was
    # configured at all (meaning the operator doesn't want Sentry enabled).
    if _initialized or not settings.sentry_dsn:
        return

    # Imported lazily (only when actually needed) rather than at module load
    # time, so importing this file never requires sentry_sdk to be usable.
    import sentry_sdk

    sentry_sdk.init(
        dsn=settings.sentry_dsn,  # where to send error reports
        environment=settings.env,  # tags events as "development" or "production"
        # Conservative default — trace sampling is a cost knob, not a
        # correctness one; start low and raise it later if needed.
        traces_sample_rate=0.1,  # only trace/sample 10% of requests for performance data
        send_default_pii=False,  # don't send IP addresses/headers by default
        include_local_variables=False,  # don't send local variable values from stack frames
    )
    # Tag every event from this process with which component sent it, so the
    # Sentry dashboard can filter "api" errors separately from "worker" ones.
    sentry_sdk.set_tag("component", component)
    # Remember that we've already initialized, so a second call becomes a no-op.
    _initialized = True
    logger.info("Sentry initialized (component=%s, env=%s)", component, settings.env)
