"""Rate limiting — a thin slowapi wrapper shared by every limited endpoint.

Redis-backed (reuses the same ``settings.redis_url`` the job queue already
requires) so limits hold across multiple API processes/replicas, not just
per-process memory. This doesn't introduce a new single point of failure:
the upload endpoint already depends on Redis to enqueue the processing job,
so a Redis outage affects it identically with or without rate limiting.

Keyed by client IP. Deliberately targeted, not global — only the endpoints
named in the production-hardening plan (signup, upload) are limited, so
normal polling/list/search traffic is never at risk of being throttled.
"""

from slowapi import Limiter
from slowapi.util import get_remote_address

from app.core.config import settings

limiter = Limiter(key_func=get_remote_address, storage_uri=settings.redis_url)
