"""Public Baskt account profile routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from starlette import status

from core.authentication import get_current_baskt_account
from core.deps import (
    get_baskt_account_repository,
    get_model_portfolio_repository,
)
from repository.baskt_account_repository import (
    BasktAccountNotFoundError,
    BasktAccountRepository,
    BasktAccountRepositoryError,
)
from repository.model_portfolio_repository import (
    ModelPortfolioInternalServerError,
    ModelPortfolioRepository,
)
from schema.baskt_account_schema import (
    BasktAccountMetadataResponse,
    BasktAccountProfileResponse,
)
from schema.model_portfolio_schema import (
    ModelPortfolioMetadataResponse,
    ModelPortfoliosMetadataResponse,
)
from domain.baskt_account_domain import BasktAccount


router = APIRouter(prefix="/baskt-accounts", tags=["baskt-accounts"])


@router.get(
    "/{profile_cognito_user_id}/profile",
    response_model=BasktAccountProfileResponse,
    status_code=status.HTTP_200_OK,
)
def get_baskt_account_profile(
    profile_cognito_user_id: str,
    baskt_account: BasktAccount = Depends(get_current_baskt_account),
    baskt_account_repository: BasktAccountRepository = Depends(
        get_baskt_account_repository
    ),
    model_portfolio_repository: ModelPortfolioRepository = Depends(
        get_model_portfolio_repository
    ),
) -> BasktAccountProfileResponse:
    """Return a Baskt account's public metadata and owned portfolios."""
    del baskt_account
    try:
        profile_cognito_user_id = str(profile_cognito_user_id).strip()
        if not profile_cognito_user_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="profile_cognito_user_id is required.",
            )

        profile_baskt_account = baskt_account_repository.get_baskt_account(
            cognito_user_id=profile_cognito_user_id
        )
        portfolios = model_portfolio_repository.get_model_portfolio_metadata_by_owner(
            portfolio_owner_cognito_user_id=profile_cognito_user_id
        )
        return BasktAccountProfileResponse(
            baskt_account=BasktAccountMetadataResponse(
                cognito_user_id=profile_baskt_account.cognito_user_id,
                display_name=profile_baskt_account.display_name,
                description=profile_baskt_account.description,
            ),
            model_portfolios=ModelPortfoliosMetadataResponse(
                root=[
                    ModelPortfolioMetadataResponse(
                        portfolio_id=portfolio["portfolio_id"],
                        portfolio_owner_cognito_user_id=portfolio[
                            "portfolio_owner_cognito_user_id"
                        ],
                        portfolio_name=portfolio["portfolio_name"],
                        created_at=portfolio["created_at"],
                        updated_at=portfolio["updated_at"],
                        description=portfolio.get("description"),
                        visibility=portfolio.get("visibility"),
                    )
                    for portfolio in portfolios
                ]
            )
        )
    except BasktAccountNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(error),
        ) from error
    except (BasktAccountRepositoryError, ModelPortfolioInternalServerError) as error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(error),
        ) from error
