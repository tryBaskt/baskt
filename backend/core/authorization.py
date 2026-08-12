# backend/core/authorization.py

from __future__ import annotations

import json
import logging
from typing import Any, Optional

from alpaca.broker.models import Account
from fastapi import HTTPException, status

from core.authentication import get_cognito_user_id
from domain.baskt_account_domain import BasktAccount
from domain.model_portfolio_domain import ModelPortfolio
from domain.allocation_domain import PortfolioAllocation, StockAllocation
from repository.model_portfolio_repository import (
    ModelPortfolioBadGatewayError,
    ModelPortfolioInternalServerError,
    ModelPortfolioNotFoundError,
    ModelPortfolioRepository,
)
from repository.model_portfolio_access_repository import (
    ModelPortfolioAccessBadGatewayError,
    ModelPortfolioAccessRepository,
    ModelPortfolioAccessRepositoryError,
)
from repository.allocation_repository import (
    AllocationBadGatewayError,
    AllocationNotFoundError,
    AllocationRepository,
    AllocationRepositoryError,
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


def require_active_alpaca_account(
    *,
    baskt_account: BasktAccount,
    alpaca_account: Account
) -> Account:
    """
    Ensure a requested Alpaca account id belongs to the authenticated user and is active.
    """

    if alpaca_account is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Active Alpaca account authorization requires an Alpaca account.",
        )

    account_status = alpaca_account.status.name.upper()
    if account_status != "ACTIVE":
        _audit_denied_access(
            action="alpaca_account.active",
            user_id=get_cognito_user_id(baskt_account),
            resource_type="alpaca_account",
            resource_id=_normalize_id(getattr(alpaca_account, "id", None)) or None,
            reason="alpaca_account_not_active",
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Alpaca account must be ACTIVE. Current status is '{account_status}'.",
        )

    return alpaca_account


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


def require_model_portfolio_access(
    *,
    portfolio_id: str,
    cognito_user_id: str,
    model_portfolio_repository: ModelPortfolioRepository,
    model_portfolio_access_repository: ModelPortfolioAccessRepository,
) -> ModelPortfolio:
    """Load a model portfolio and ensure the Cognito user can view/use it or is the owner."""
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

    if model_portfolio.portfolio_owner_cognito_user_id == cognito_user_id:
        return model_portfolio

    visibility = str(getattr(model_portfolio, "visibility", "PRIVATE")).upper()
    if visibility == "PUBLIC":
        return model_portfolio

    try:
        has_access = model_portfolio_access_repository.has_access(
            portfolio_id=portfolio_id,
            shared_with_cognito_user_id=cognito_user_id,
        )
    except ModelPortfolioAccessBadGatewayError as err:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"message": str(err), "code": err.code},
        ) from err
    except ModelPortfolioAccessRepositoryError as err:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"message": str(err), "code": err.code},
        ) from err

    if has_access:
        return model_portfolio

    _audit_denied_access(
        action="model_portfolio.access",
        user_id=cognito_user_id,
        resource_type="model_portfolio",
        resource_id=portfolio_id,
        reason="private_model_portfolio_access_missing",
    )
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Authenticated user is not allowed to access this model portfolio.",
    )


def get_optional_allocation_owner(
    *,
    allocation_id: str,
    cognito_user_id: str,
    allocation_repository: AllocationRepository,
) -> Optional[PortfolioAllocation | StockAllocation]:
    """
    Load a Cognito user's allocation when it exists.

    Missing allocations are a normal state for public Baskt/stock pages: users can
    inspect a page before investing. Upstream failures still become HTTP errors.
    """
    try:
        return allocation_repository.get_allocation(
            cognito_user_id=cognito_user_id,
            allocation_id=allocation_id,
        )
    except AllocationNotFoundError:
        return None
    except AllocationBadGatewayError as err:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"message": str(err), "code": err.code},
        ) from err
    except AllocationRepositoryError as err:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"message": str(err), "code": err.code},
        ) from err


def get_optional_portfolio_allocation_owner(
    *,
    allocation_id: str,
    cognito_user_id: str,
    allocation_repository: AllocationRepository,
) -> Optional[PortfolioAllocation | StockAllocation]:
    """Backward-compatible alias for allocation ownership checks."""
    return get_optional_allocation_owner(
        allocation_id=allocation_id,
        cognito_user_id=cognito_user_id,
        allocation_repository=allocation_repository,
    )
