# backend/core/authorization.py

from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional

from fastapi import HTTPException, status

from clients.alpaca_broker_client import AlpacaBrokerClient, AlpacaBrokerClientError
from domain.model_portfolio_domain import ModelPortfolio
from domain.portfolio_allocation_domain import PortfolioAllocation
from repository.model_portfolio_repository import (
    ModelPortfolioBadGatewayError,
    ModelPortfolioInternalServerError,
    ModelPortfolioNotFoundError,
    ModelPortfolioRepository,
)
from repository.portfolio_allocation_repository import (
    PortfolioAllocationBadGatewayError,
    PortfolioAllocationInternalServerError,
    PortfolioAllocationNotFoundError,
    PortfolioAllocationRepository,
)


audit_logger = logging.getLogger("baskt.audit.authorization")


def _normalize_id(value: Any) -> str:
    return str(value or "").strip()


def _audit_denied_access(
    *,
    action: str,
    user_id: Optional[str],
    resource_type: str,
    resource_id: Optional[str],
    reason: str,
) -> None:
    """Emit a non-sensitive authorization denial audit event."""
    audit_logger.warning(
        "authorization_denied %s",
        json.dumps(
            {
                "action": action,
                "decision": "denied",
                "reason": reason,
                "resource_id": resource_id,
                "resource_type": resource_type,
                "user_id": user_id,
            },
            sort_keys=True,
        ),
    )


def require_cognito_user_id(user: Dict[str, Any]) -> str:
    """Return the authenticated Cognito user id from verified token claims."""
    cognito_user_id = _normalize_id(user.get("sub"))
    if not cognito_user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authenticated token is missing Cognito user id.",
        )
    return cognito_user_id


def require_current_user_alpaca_account_id(user: Dict[str, Any]) -> str:
    """Return the authenticated user's Alpaca account id from token claims."""
    alpaca_account_id = _normalize_id(user.get("custom:alpaca_acct_id"))
    if not alpaca_account_id:
        _audit_denied_access(
            action="alpaca_account.claim_required",
            user_id=_normalize_id(user.get("sub")) or None,
            resource_type="alpaca_account",
            resource_id=None,
            reason="missing_alpaca_account_claim",
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Authenticated user does not have an Alpaca account id.",
        )
    return alpaca_account_id


def require_alpaca_account_owner(
    *,
    user: Dict[str, Any],
    alpaca_account_id: str,
    alpaca_broker_client: Optional[AlpacaBrokerClient] = None,
    verify_account_exists: bool = False,
) -> str:
    """
    Ensure a requested Alpaca account id belongs to the authenticated user.

    Cognito's custom Alpaca account id claim is the local source of ownership.
    Set ``verify_account_exists`` when a route also needs to confirm the broker
    account is reachable before continuing.
    """
    cognito_user_id = require_cognito_user_id(user)
    current_alpaca_account_id = require_current_user_alpaca_account_id(user)
    requested_alpaca_account_id = _normalize_id(alpaca_account_id)

    if not requested_alpaca_account_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Alpaca account id is required.",
        )

    if requested_alpaca_account_id != current_alpaca_account_id:
        _audit_denied_access(
            action="alpaca_account.owner",
            user_id=cognito_user_id,
            resource_type="alpaca_account",
            resource_id=requested_alpaca_account_id,
            reason="alpaca_account_mismatch",
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Authenticated user is not allowed to access this Alpaca account.",
        )

    if verify_account_exists:
        if alpaca_broker_client is None:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Alpaca account verification requires an Alpaca broker client.",
            )
        try:
            alpaca_broker_client.get_alpaca_account_by_id(
                account_id=requested_alpaca_account_id,
                cognito_user_id=cognito_user_id,
            )
        except AlpacaBrokerClientError as err:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail={
                    "message": "Failed to verify Alpaca account ownership.",
                    "code": err.code,
                },
            ) from err

    return requested_alpaca_account_id


def require_model_portfolio_owner(
    *,
    portfolio_id: str,
    cognito_user_id: str,
    model_portfolio_repository: ModelPortfolioRepository,
) -> ModelPortfolio:
    """Load a model portfolio and ensure the Cognito user owns it."""
    try:
        model_portfolio = model_portfolio_repository.get_model_portfolio(
            portfolio_id=portfolio_id
        )
    except ModelPortfolioNotFoundError as err:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Model portfolio not found.",
        ) from err
    except ModelPortfolioBadGatewayError as err:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"message": str(err), "code": err.code},
        ) from err
    except ModelPortfolioInternalServerError as err:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"message": str(err), "code": err.code},
        ) from err

    if model_portfolio.portfolio_owner_cognito_user_id != cognito_user_id:
        _audit_denied_access(
            action="model_portfolio.owner",
            user_id=cognito_user_id,
            resource_type="model_portfolio",
            resource_id=portfolio_id,
            reason="model_portfolio_owner_mismatch",
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Authenticated user is not allowed to access this model portfolio.",
        )

    return model_portfolio


def require_model_portfolio_owner_match(
    *,
    portfolio_id: str,
    portfolio_owner_cognito_user_id: str,
    model_portfolio_repository: ModelPortfolioRepository,
    cognito_user_id: Optional[str] = None,
) -> ModelPortfolio:
    """Load a model portfolio and ensure the supplied owner id is truthful."""
    try:
        model_portfolio = model_portfolio_repository.get_model_portfolio(
            portfolio_id=portfolio_id
        )
    except ModelPortfolioNotFoundError as err:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Model portfolio not found.",
        ) from err
    except ModelPortfolioBadGatewayError as err:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"message": str(err), "code": err.code},
        ) from err
    except ModelPortfolioInternalServerError as err:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"message": str(err), "code": err.code},
        ) from err

    if (
        model_portfolio.portfolio_owner_cognito_user_id
        != portfolio_owner_cognito_user_id
    ):
        _audit_denied_access(
            action="model_portfolio.owner_match",
            user_id=cognito_user_id,
            resource_type="model_portfolio",
            resource_id=portfolio_id,
            reason="supplied_owner_does_not_match_portfolio",
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Portfolio owner does not match the requested model portfolio.",
        )

    return model_portfolio


def require_portfolio_allocation_owner(
    *,
    portfolio_id: str,
    cognito_user_id: str,
    portfolio_allocation_repository: PortfolioAllocationRepository,
) -> PortfolioAllocation:
    """Load a portfolio allocation owned by the Cognito user."""
    try:
        return portfolio_allocation_repository.get_portfolio_allocation(
            cognito_user_id=cognito_user_id,
            portfolio_id=portfolio_id,
        )
    except PortfolioAllocationNotFoundError as err:
        _audit_denied_access(
            action="portfolio_allocation.owner",
            user_id=cognito_user_id,
            resource_type="portfolio_allocation",
            resource_id=portfolio_id,
            reason="allocation_not_found_or_not_owned",
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Portfolio allocation not found.",
        ) from err
    except PortfolioAllocationBadGatewayError as err:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"message": str(err), "code": err.code},
        ) from err
    except PortfolioAllocationInternalServerError as err:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"message": str(err), "code": err.code},
        ) from err
