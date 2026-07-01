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

from typing import Any

import jwt
from fastapi import HTTPException, status

from app.core.config import settings

HS_ALGORITHM = "HS256"
ASYMMETRIC_ALGORITHMS = ("ES256", "RS256")
AUDIENCE = "authenticated"

# Cached JWKS client (created on first asymmetric token; reused thereafter).
_jwk_client: jwt.PyJWKClient | None = None


def _get_jwk_client() -> jwt.PyJWKClient:
    """Return a cached PyJWKClient pointed at the Supabase JWKS endpoint."""
    global _jwk_client
    if _jwk_client is None:
        jwks_url = f"{settings.supabase_url}/auth/v1/.well-known/jwks.json"
        _jwk_client = jwt.PyJWKClient(jwks_url)
    return _jwk_client


class TokenData:
    """Parsed + verified JWT claims for a Supabase user."""

    def __init__(self, payload: dict[str, Any]) -> None:
        self.user_id: str = payload["sub"]
        self.email: str = payload.get("email", "")
        app_meta: dict[str, Any] = payload.get("app_metadata", {})
        self.tenant_id: str | None = app_meta.get("tenant_id")
        self.role: str = app_meta.get("role", "user")


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def verify_token(token: str) -> TokenData:
    """Decode and verify a Supabase JWT (HS256 or asymmetric). Raises 401 on failure."""
    try:
        header = jwt.get_unverified_header(token)
    except jwt.DecodeError as exc:
        raise _unauthorized(f"Malformed token: {exc}")

    alg = header.get("alg", "")

    if alg == HS_ALGORITHM:
        key: Any = settings.supabase_jwt_secret
    elif alg in ASYMMETRIC_ALGORITHMS:
        try:
            key = _get_jwk_client().get_signing_key_from_jwt(token).key
        except Exception as exc:  # JWKS fetch / key lookup failure
            raise _unauthorized(f"Could not resolve signing key from JWKS: {exc}")
    else:
        raise _unauthorized(
            f"Unsupported token algorithm '{alg}'. Expected HS256 or {ASYMMETRIC_ALGORITHMS}."
        )

    try:
        payload = jwt.decode(
            token,
            key,
            algorithms=[alg],
            audience=AUDIENCE,
            leeway=60,
        )
    except jwt.ExpiredSignatureError:
        raise _unauthorized("Token has expired")
    except jwt.InvalidTokenError as exc:
        raise _unauthorized(f"Invalid token: {exc}")

    return TokenData(payload)
