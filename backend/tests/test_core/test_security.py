from __future__ import annotations

import time
from pathlib import Path
import sys

from dotenv import load_dotenv
from fastapi import HTTPException
from jose.utils import base64url_encode
import pytest

repo_root = Path(__file__).resolve().parents[3]
backend_dir = Path(__file__).resolve().parents[2]
for import_path in (str(backend_dir), str(repo_root)):
    if import_path not in sys.path:
        sys.path.insert(0, import_path)

from core.config import get_settings
from core.security import CognitoTokenVerifier, JWKSCache, verify_jwt_token

load_dotenv(repo_root / ".env")
get_settings.cache_clear()


def _verifier() -> CognitoTokenVerifier:
    settings = get_settings()
    return CognitoTokenVerifier(
        user_pool_id=settings.cognito_user_pool_id,
        app_client_id=settings.cognito_app_client_id,
        region=settings.cognito_region,
        jwks_ttl_seconds=3600,
        http_timeout_seconds=5,
        clock_skew_leeway_seconds=60,
    )


def _token_with_unknown_kid() -> str:
    header = base64url_encode(
        b'{"alg":"RS256","typ":"JWT","kid":"missing-security-test-kid"}'
    ).decode("utf-8")
    claims = base64url_encode(b'{"sub":"security-test"}').decode("utf-8")
    signature = base64url_encode(b"signature").decode("utf-8")
    return f"{header}.{claims}.{signature}"


def test_cognito_token_verifier_constructor_and_properties() -> None:
    verifier = CognitoTokenVerifier(
        user_pool_id="pool-id",
        app_client_id="app-client-id",
        region="us-east-1",
        jwks_ttl_seconds=123,
        http_timeout_seconds=7,
        clock_skew_leeway_seconds=9,
        allowed_token_uses=["access"],
    )

    assert verifier.user_pool_id == "pool-id"
    assert verifier.app_client_id == "app-client-id"
    assert verifier.region == "us-east-1"
    assert verifier.jwks_ttl_seconds == 123
    assert verifier.http_timeout_seconds == 7
    assert verifier.clock_skew_leeway_seconds == 9
    assert verifier.allowed_token_uses == ["access"]
    assert verifier._cache is None
    assert verifier.jwks_url == (
        "https://cognito-idp.us-east-1.amazonaws.com/"
        "pool-id/.well-known/jwks.json"
    )
    assert verifier.issuer == (
        "https://cognito-idp.us-east-1.amazonaws.com/pool-id"
    )


def test_cognito_token_verifier_cache_validity() -> None:
    verifier = CognitoTokenVerifier(
        user_pool_id="pool-id",
        app_client_id="app-client-id",
        region="us-east-1",
        jwks_ttl_seconds=60,
    )

    assert verifier._cache_is_valid() is False

    verifier._cache = JWKSCache(
        keys=[{"kid": "fresh"}],
        fetched_at=time.time(),
    )
    assert verifier._cache_is_valid() is True

    verifier._cache = JWKSCache(
        keys=[{"kid": "expired"}],
        fetched_at=time.time() - 61,
    )
    assert verifier._cache_is_valid() is False


@pytest.mark.integration
def test_cognito_token_verifier_fetches_and_caches_real_jwks() -> None:
    verifier = _verifier()

    fetched_keys = verifier._fetch_jwks()
    assert fetched_keys
    assert any(key.get("kid") for key in fetched_keys)

    cached_keys = verifier._get_jwks(force_refresh=True)
    assert cached_keys
    assert verifier._cache is not None
    assert verifier._cache.keys == cached_keys
    assert verifier._get_jwks() == cached_keys

    first_key = cached_keys[0]
    assert verifier._find_key(first_key["kid"]) == first_key
    assert verifier._find_key("missing-security-test-kid") is None


def test_cognito_token_verifier_rejects_invalid_token_header() -> None:
    with pytest.raises(HTTPException) as exc_info:
        _verifier().verify("not-a-jwt")

    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "Invalid auth token header"


def test_cognito_token_verifier_rejects_token_missing_kid() -> None:
    header = base64url_encode(b'{"alg":"RS256","typ":"JWT"}').decode("utf-8")
    claims = base64url_encode(b'{"sub":"security-test"}').decode("utf-8")
    signature = base64url_encode(b"signature").decode("utf-8")

    with pytest.raises(HTTPException) as exc_info:
        _verifier().verify(f"{header}.{claims}.{signature}")

    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "Invalid token: missing 'kid'"


@pytest.mark.integration
def test_cognito_token_verifier_rejects_unknown_kid_after_real_jwks_lookup() -> None:
    with pytest.raises(HTTPException) as exc_info:
        _verifier().verify(_token_with_unknown_kid())

    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "Public key not found for token"


def test_verify_jwt_token_returns_none_for_invalid_token() -> None:
    assert verify_jwt_token("not-a-jwt") is None
