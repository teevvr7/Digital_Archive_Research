"""JWT verification for Supabase Auth tokens.

Supabase signs access tokens one of two ways depending on project age/config:

* **Legacy** — HS256, signed with the project *JWT Secret*
  (Project Settings > API > JWT Secret).
* **Modern** — asymmetric (ES256 / RS256) via *JWT Signing Keys*. The public keys
  are published at ``{SUPABASE_URL}/auth/v1/.well-known/jwks.json``.

This module verifies both: HS256 with the shared secret, asymmetric algorithms
against the project's JWKS. No network call for HS256; JWKS is fetched and cached
by PyJWT for asymmetric tokens.

``tenant_id`` and ``role`` live in ``app_metadata`` (admin-set, not user-editable)
and are included in every Supabase access token.
"""

# Any is used because JWT claim values can be of many different JSON types.
from typing import Any

# PyJWT — the library that actually decodes/verifies JSON Web Tokens.
import jwt
from fastapi import HTTPException, status

from app.core.config import settings

# The two algorithm families Supabase might use to sign a token.
HS_ALGORITHM = "HS256"  # symmetric — verified with a shared secret
ASYMMETRIC_ALGORITHMS = ("ES256", "RS256")  # verified with a public key from JWKS
# The JWT "aud" (audience) claim Supabase always sets for logged-in-user tokens.
AUDIENCE = "authenticated"

# Module-level singleton, lazily created on first use — a PyJWKClient caches
# the fetched public keys internally, so we only want ONE of these per
# process rather than re-fetching the JWKS document on every request.
_jwk_client: jwt.PyJWKClient | None = None


def _get_jwk_client() -> jwt.PyJWKClient:
    """Return a cached PyJWKClient pointed at the Supabase JWKS endpoint."""
    # `global` lets this function reassign the module-level variable above.
    global _jwk_client
    if _jwk_client is None:
        # Build the well-known JWKS URL from the configured Supabase project URL.
        jwks_url = f"{settings.supabase_url}/auth/v1/.well-known/jwks.json"
        # Create it once; PyJWKClient itself handles caching/refreshing keys.
        _jwk_client = jwt.PyJWKClient(jwks_url)
    return _jwk_client


class TokenData:
    """Parsed + verified JWT claims for a Supabase user."""

    def __init__(self, payload: dict[str, Any]) -> None:
        # "sub" (subject) is the standard JWT claim for "who is this token about" —
        # for Supabase that's the user's UUID.
        self.user_id: str = payload["sub"]
        # Fall back to an empty string if the email claim is somehow missing.
        self.email: str = payload.get("email", "")
        # app_metadata is where Supabase stores admin-controlled (not
        # user-editable) custom claims — that's where we stash tenant_id/role.
        app_meta: dict[str, Any] = payload.get("app_metadata", {})
        # None here means "this user hasn't been bootstrapped into a tenant yet".
        self.tenant_id: str | None = app_meta.get("tenant_id")
        # Default to the least-privileged role if it's somehow missing.
        self.role: str = app_meta.get("role", "user")


def _unauthorized(detail: str) -> HTTPException:
    # A small helper so every 401 response is built the exact same way,
    # including the WWW-Authenticate header browsers/clients expect.
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def verify_token(token: str) -> TokenData:
    """Decode and verify a Supabase JWT (HS256 or asymmetric). Raises 401 on failure."""
    try:
        # Read the header WITHOUT verifying the signature yet — we only need
        # the "alg" field to know which verification path to take next.
        header = jwt.get_unverified_header(token)
    except jwt.DecodeError as exc:
        # The token isn't even valid base64/JSON — reject immediately.
        raise _unauthorized(f"Malformed token: {exc}")

    alg = header.get("alg", "")

    if alg == HS_ALGORITHM:
        # Symmetric verification: the "key" is just the shared secret string.
        key: Any = settings.supabase_jwt_secret
    elif alg in ASYMMETRIC_ALGORITHMS:
        try:
            # Ask the JWKS client to look up (by the token's "kid" header) the
            # correct public key to verify this specific token with.
            key = _get_jwk_client().get_signing_key_from_jwt(token).key
        except Exception as exc:  # JWKS fetch / key lookup failure
            raise _unauthorized(f"Could not resolve signing key from JWKS: {exc}")
    else:
        # Any algorithm we don't explicitly support is rejected outright —
        # never silently trust an unexpected signing algorithm.
        raise _unauthorized(
            f"Unsupported token algorithm '{alg}'. Expected HS256 or {ASYMMETRIC_ALGORITHMS}."
        )

    try:
        # This is where the actual cryptographic signature check happens,
        # plus standard claim validation (expiry, audience).
        payload = jwt.decode(
            token,
            key,
            algorithms=[alg],  # only accept the ONE algorithm we resolved above
            audience=AUDIENCE,  # reject tokens not intended for "authenticated" use
        )
    except jwt.ExpiredSignatureError:
        # The token was valid once but its "exp" claim has passed.
        raise _unauthorized("Token has expired")
    except jwt.InvalidTokenError as exc:
        # Catches every other verification failure (bad signature, wrong
        # audience, malformed claims, etc.) under one umbrella.
        raise _unauthorized(f"Invalid token: {exc}")

    # Only reached if verification succeeded — wrap the raw claims dict in
    # our typed TokenData so callers get clean attribute access.
    return TokenData(payload)
