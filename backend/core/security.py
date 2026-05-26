# backend/core/security.py

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import requests
from fastapi import HTTPException, status
from jose import jwk, jwt
from jose.utils import base64url_decode


@dataclass
class JWKSCache:
    keys: List[Dict[str, Any]]
    fetched_at: float


class CognitoTokenVerifier:
    """
    Verifies JWTs issued by AWS Cognito User Pools using the pool's JWKS.

    - Fetches JWKS lazily (first request)
    - Caches JWKS for jwks_ttl_seconds
    - If 'kid' is missing from cached keys, refreshes JWKS once and retries
    """

    def __init__(
        self,
        *,
        user_pool_id: str,
        app_client_id: str,
        region: str,
        jwks_ttl_seconds: int = 3600,
        http_timeout_seconds: int = 5,
        clock_skew_leeway_seconds: int = 60,
        allowed_token_uses: Optional[List[str]] = None,  # e.g. ["access", "id"]
    ) -> None:
        self.user_pool_id = user_pool_id
        self.app_client_id = app_client_id
        self.region = region

        self.jwks_ttl_seconds = jwks_ttl_seconds
        self.http_timeout_seconds = http_timeout_seconds
        self.clock_skew_leeway_seconds = clock_skew_leeway_seconds

        self.allowed_token_uses = allowed_token_uses or ["access", "id"]

        self._cache: Optional[JWKSCache] = None

    @property
    def jwks_url(self) -> str:
        return (
            f"https://cognito-idp.{self.region}.amazonaws.com/"
            f"{self.user_pool_id}/.well-known/jwks.json"
        )

    @property
    def issuer(self) -> str:
        return f"https://cognito-idp.{self.region}.amazonaws.com/{self.user_pool_id}"

    def _cache_is_valid(self) -> bool:
        if self._cache is None:
            return False
        age = time.time() - self._cache.fetched_at
        return age < self.jwks_ttl_seconds

    def _fetch_jwks(self) -> List[Dict[str, Any]]:
        try:
            resp = requests.get(self.jwks_url, timeout=self.http_timeout_seconds)
            resp.raise_for_status()
            payload = resp.json()
            keys = payload.get("keys", [])
            if not isinstance(keys, list) or not keys:
                raise ValueError("JWKS payload missing 'keys'")
            return keys
        except Exception:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Unable to fetch Cognito JWKS",
            )

    def _get_jwks(self, *, force_refresh: bool = False) -> List[Dict[str, Any]]:
        if force_refresh or not self._cache_is_valid():
            keys = self._fetch_jwks()
            self._cache = JWKSCache(keys=keys, fetched_at=time.time())
        return self._cache.keys  # type: ignore[union-attr]

    def _find_key(self, kid: str, *, force_refresh: bool = False) -> Optional[Dict[str, Any]]:
        keys = self._get_jwks(force_refresh=force_refresh)
        return next((k for k in keys if k.get("kid") == kid), None)

    def verify(self, token: str) -> Dict[str, Any]:
        # 1) Parse header
        try:
            headers = jwt.get_unverified_header(token)
        except Exception:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid auth token header",
            )

        kid = headers.get("kid")
        if not kid:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token: missing 'kid'",
            )

        # 2) Find the JWK (refresh once if needed)
        key = self._find_key(kid, force_refresh=False)
        if key is None:
            key = self._find_key(kid, force_refresh=True)

        if key is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Public key not found for token",
            )

        # 3) Verify signature
        public_key = jwk.construct(key)

        try:
            message, encoded_sig = token.rsplit(".", 1)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token format",
            )

        decoded_sig = base64url_decode(encoded_sig.encode("utf-8"))
        if not public_key.verify(message.encode("utf-8"), decoded_sig):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token signature verification failed",
            )

        # 4) Validate claims (exp, aud/client_id, issuer/token_use)
        claims = jwt.get_unverified_claims(token)

        now = time.time()
        exp = claims.get("exp", 0)
        if (now - self.clock_skew_leeway_seconds) > exp:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token is expired",
            )

        # Optional issuer check (recommended)
        iss = claims.get("iss")
        if iss and iss != self.issuer:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token issuer mismatch",
            )

        # Cognito: ID token uses 'aud', access token uses 'client_id'
        aud = claims.get("aud") or claims.get("client_id")
        if aud != self.app_client_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token was not issued for this client",
            )

        token_use = claims.get("token_use")
        if token_use and token_use not in self.allowed_token_uses:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token type not allowed",
            )

        return claims


def verify_jwt_token(token: str) -> str | None:
    """
    Verify JWT token and return user_id (sub claim).
    Used for WebSocket authentication.
    Returns None if token is invalid.
    """
    from core.deps import get_token_verifier
    
    try:
        verifier = get_token_verifier()
        claims = verifier.verify(token)
        return claims.get("sub")  # 'sub' is the user_id in Cognito
    except Exception:
        return None
