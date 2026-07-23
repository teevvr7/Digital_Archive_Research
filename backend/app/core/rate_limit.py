"""Rate limiting — a thin slowapi wrapper shared by every limited endpoint.

Redis-backed (reuses the same ``settings.redis_url`` the job queue already
requires) so limits hold across multiple API processes/replicas, not just
per-process memory.

Keyed by client IP. Endpoints named in the production-hardening plan
(signup, upload, public share resolve) carry their own stricter
``@limiter.limit(...)``. Every other route falls back to ``default_limits``
below — a generous ceiling that only exists to bound abuse/DoS on routes that
were never explicitly rate-limited, so normal polling/list/search traffic is
in no danger of being throttled.

``default_limits`` applies globally, unlike the per-endpoint decorators — so
unlike before, a Redis outage would now affect every route, not just
upload/signup (which already depended on Redis for the job queue and so were
never at risk of a *new* failure mode). ``swallow_errors=True`` keeps that
CLAUDE.md "degrade gracefully, don't error" property: if Redis is unreachable,
slowapi logs it and skips the check rather than raising — the app fails open
on this defense-in-depth ceiling instead of 500ing every request.
"""

from slowapi import Limiter
from slowapi.util import get_remote_address

from app.core.config import settings

limiter = Limiter(
    key_func=get_remote_address,
    storage_uri=settings.redis_url,
    default_limits=["200/minute"],
    swallow_errors=True,
)
