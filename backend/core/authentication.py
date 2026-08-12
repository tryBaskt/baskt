# backend/core/authentication.py

from __future__ import annotations

from functools import lru_cache
from typing import Any, Dict, Optional

from alpaca.broker.models import Account
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from clients.alpaca_broker_client import AlpacaBrokerClient, AlpacaBrokerClientError
from clients.cognito_client import CognitoClientCognitoUserNotFound, CognitoClientError
from core.config import get_settings
from core.security import CognitoTokenVerifier
from core.deps import (
    get_baskt_account_dynamodb_client,
    get_baskt_account_repository,
    get_cognito_client,
)
from repository.baskt_account_repository import (
    BasktAccountBadGatewayError,
    BasktAccountNotFoundError,
    BasktAccountRepository,
    BasktAccountRepositoryError,
    BasktAccountUnprocessableEntityError,
)
from domain.baskt_account_domain import BasktAccount


bearer_scheme = HTTPBearer(auto_error=False)


@lru_cache
def get_token_verifier() -> CognitoTokenVerifier:
    """
    Cache verifier globally. Do NOT accept Settings as an argument (unhashable).
    """
    settings = get_settings()
    return CognitoTokenVerifier(
        user_pool_id=settings.cognito_user_pool_id,
        app_client_id=settings.cognito_app_client_id,
        region=settings.cognito_region,
    )

def _get_cognito_user_id_from_claims(user: Dict[str, Any]) -> str:
    """Return the authenticated Cognito user id from verified token claims."""
    cognito_user_id = str(user.get("sub") or "").strip()
    if not cognito_user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authenticated token is missing Cognito user id.",
        )
    return cognito_user_id


def _get_alpaca_account_id_from_claims(user: Dict[str, Any]) -> str:
    """Return the authenticated user's Alpaca account id from token claims."""
    alpaca_account_id = str(user.get("custom:alpaca_acct_id") or "").strip()
    if not alpaca_account_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Authenticated user does not have an Alpaca account id.",
        )
    return alpaca_account_id


def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
) -> Dict[str, Any]:
    if credentials is None or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid Authorization header",
        )

    token = credentials.credentials.strip()
    verifier = get_token_verifier()
    return verifier.verify(token)


def get_current_baskt_account(
    user: Dict[str, str] = Depends(get_current_user),
    baskt_account_repository: BasktAccountRepository = Depends(get_baskt_account_repository),
) -> BasktAccount:
    """Return the authenticated user's persisted Baskt account after claim checks."""
    cognito_user_id = _get_cognito_user_id_from_claims(user)
    token_alpaca_account_id = _get_alpaca_account_id_from_claims(user)

    try:
        baskt_account = baskt_account_repository.get_baskt_account(
            cognito_user_id=cognito_user_id
        )
    except BasktAccountNotFoundError as err:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Authenticated user does not have a Baskt account.",
        ) from err
    except BasktAccountBadGatewayError as err:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to verify Baskt account.",
        ) from err
    except BasktAccountUnprocessableEntityError as err:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Stored Baskt account is invalid.",
        ) from err
    except BasktAccountRepositoryError as err:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to verify Baskt account.",
        ) from err

    persisted_alpaca_account_id = str(baskt_account.alpaca_account_id or "").strip()
    if persisted_alpaca_account_id != token_alpaca_account_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Authenticated user's Alpaca account does not match Baskt account.",
        )

    return baskt_account


def get_cognito_user_id(baskt_account: BasktAccount) -> str:
    """Return the authenticated Cognito user id from a verified Baskt account."""
    cognito_user_id = str(baskt_account.cognito_user_id or "").strip()
    if not cognito_user_id:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Verified Baskt account is missing Cognito user id.",
        )
    return cognito_user_id


def get_alpaca_account_id(baskt_account: BasktAccount) -> str:
    """Return the authenticated Alpaca account id from a verified Baskt account."""
    alpaca_account_id = str(baskt_account.alpaca_account_id or "").strip()
    if not alpaca_account_id:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Verified Baskt account is missing Alpaca account id.",
        )
    return alpaca_account_id


def _get_alpaca_broker_client() -> AlpacaBrokerClient:
    from core.deps import get_alpaca_broker_client

    return get_alpaca_broker_client()


def get_current_alpaca_account(
    baskt_account: BasktAccount = Depends(get_current_baskt_account),
    alpaca_broker_client: AlpacaBrokerClient = Depends(_get_alpaca_broker_client),
) -> Account:
    cognito_user_id = get_cognito_user_id(baskt_account)
    alpaca_account_id = get_alpaca_account_id(baskt_account)

    try:
        return alpaca_broker_client.get_alpaca_account_by_id(
            account_id=alpaca_account_id,
            cognito_user_id=cognito_user_id,
        )
    except AlpacaBrokerClientError as err:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to verify Alpaca account: {err}",
        ) from err

def authenticate_email(
    email_address: str,
) -> str:
    """Verify email belongs to a persisted Baskt account."""
    cognito_client = get_cognito_client()
    baskt_account_repository = get_baskt_account_repository(
        baskt_account_dynamodb_client=get_baskt_account_dynamodb_client()
    )

    if not email_address:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="email_address is required.",
        )

    try:
        cognito_user_dict = cognito_client.get_cognito_user_by_email_address(email_address=email_address)
        baskt_account_repository.get_baskt_account(cognito_user_id=cognito_user_dict["cognito_user_id"])
        return cognito_user_dict["email_address"]
    except CognitoClientCognitoUserNotFound as err:
        raise BasktAccountNotFoundError(
            message="Authenticated user does not have a Baskt account.",
        ) from err
    except CognitoClientError as err:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to verify Cognito user.",
        ) from err
    except BasktAccountNotFoundError as err:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Authenticated user does not have a Baskt account.",
        ) from err
    except BasktAccountBadGatewayError as err:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to verify Baskt account.",
        ) from err
    except BasktAccountUnprocessableEntityError as err:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Stored Baskt account is invalid.",
        ) from err
    except BasktAccountRepositoryError as err:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to verify Baskt account.",
        ) from err

def authenticate_cognito_user_id(
    cognito_user_id: str,
) -> str:
    cognito_client = get_cognito_client()
    baskt_account_repository = get_baskt_account_repository(
        baskt_account_dynamodb_client=get_baskt_account_dynamodb_client()
    )

    if not cognito_user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="cognito_user_id to be removed is required.",
        )

    try:
        cognito_client.get_cognito_user_by_cognito_user_id(
            cognito_user_id=cognito_user_id
        )
        baskt_account = baskt_account_repository.get_baskt_account(cognito_user_id=cognito_user_id)
        return baskt_account.cognito_user_id
    except CognitoClientCognitoUserNotFound as err:
        raise BasktAccountNotFoundError(
            message="Authenticated user does not have a Baskt account.",
        ) from err
    except CognitoClientError as err:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to verify Cognito user.",
        ) from err
    except BasktAccountNotFoundError as err:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Authenticated user does not have a Baskt account.",
        ) from err
    except BasktAccountBadGatewayError as err:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to verify Baskt account.",
        ) from err
    except BasktAccountUnprocessableEntityError as err:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Stored Baskt account is invalid.",
        ) from err
    except BasktAccountRepositoryError as err:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to verify Baskt account.",
        ) from err
