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

try:
    from slowapi import Limiter
    from slowapi.util import get_remote_address
except ImportError:
    class DummyLimiter:
        def __init__(self, *args, **kwargs):
            pass
        def limit(self, *args, **kwargs):
            def decorator(func):
                return func
            return decorator

    Limiter = DummyLimiter
    get_remote_address = lambda request: "127.0.0.1"


from app.core.config import settings

# One shared Limiter instance, imported by main.py (to wire the middleware)
# and by every router that needs a stricter per-route limit via @limiter.limit(...).
limiter = Limiter(
    key_func=get_remote_address,  # rate-limit per client IP
    storage_uri=settings.redis_url,  # store counters in Redis, not just in-process memory
    default_limits=["200/minute"],  # fallback ceiling applied to every route by default
    swallow_errors=True,  # if Redis is down, skip the check instead of erroring the request
)
