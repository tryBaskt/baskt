# backend/api/routes/model_portfolio_route.py

from __future__ import annotations

from typing import Any, Dict, Type

from fastapi import APIRouter, Depends, HTTPException
from starlette import status
from starlette.status import HTTP_200_OK, HTTP_201_CREATED
from core.deps import (
    get_current_user,
    get_model_portfolio_performance_service,
    get_model_portfolio_repository,
)
from domain.model_portfolio import ModelPortfolio, ModelPortfolioSnapshot
from repository.model_portfolio_repository import (
    ModelPortfolioRepository,
    ModelPortfolioNotFoundError, 
    ModelPortfolioPositionHistoryNotFoundError,
    ModelPortfolioInternalServerError,
    ModelPortfolioUnprocessableEntityError,
    ModelPortfolioTooManyRequestsError,
    ModelPortfolioBadGatewayError,
    ModelPortfolioLockedError
)
from schema.model_portfolio_schema import (
    CreateModelPortfolioRequest, 
    UpdateModelPortfolioRequest,
    ModelPortfolioResponse,
    ModelPortfolioPerformanceResponse,
    ModelPortfolioPositionResponse,
    ModelPortfolioSnapshotResponse,
    ModelPortfolioMetadataResponse,
    ListUserModelPortfoliosResponse
)
from services.model_portfolio_performance_service import (
    ModelPortfolioPerformanceService,
    ModelPortfolioPerformanceServiceError,
)


router = APIRouter(prefix="/model-portfolios", tags=["model-portfolios"])


MODEL_PORTFOLIO_ERROR_STATUS_MAP: tuple[tuple[Type[Exception], int], ...] = (
    (ModelPortfolioNotFoundError, status.HTTP_404_NOT_FOUND),
    (ModelPortfolioPositionHistoryNotFoundError, status.HTTP_404_NOT_FOUND),
    (ModelPortfolioLockedError, status.HTTP_423_LOCKED),
    (ModelPortfolioTooManyRequestsError, status.HTTP_429_TOO_MANY_REQUESTS),
    (ModelPortfolioUnprocessableEntityError, status.HTTP_422_UNPROCESSABLE_CONTENT),
    (ModelPortfolioBadGatewayError, status.HTTP_502_BAD_GATEWAY),
    (ModelPortfolioInternalServerError, status.HTTP_500_INTERNAL_SERVER_ERROR),
    (ModelPortfolioPerformanceServiceError, status.HTTP_500_INTERNAL_SERVER_ERROR),
)


def _raise_model_portfolio_http_exception(err: Exception) -> None:
    if isinstance(err, HTTPException):
        raise err

    for exception_type, status_code in MODEL_PORTFOLIO_ERROR_STATUS_MAP:
        if isinstance(err, exception_type):
            raise HTTPException(status_code=status_code, detail=str(err)) from err

    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail=f"Unexpected model portfolio error: {err}",
    ) from err


@router.get("/{portfolio_id}", response_model=ModelPortfolioResponse, status_code=HTTP_200_OK)
def get_model_portfolio(
    portfolio_id: str,
    user: Dict[str, Any] = Depends(get_current_user),
    service: ModelPortfolioRepository = Depends(get_model_portfolio_repository),
) -> ModelPortfolioResponse:
    """
    Retrieve a single model portfolio and its latest computed current weights.

    Args:
        portfolio_id: Identifier of the model portfolio to fetch.
        user: Authenticated user claims resolved by dependency injection.
        service: Repository dependency for model portfolio operations.

    Returns:
        ModelPortfolioResponse: Portfolio payload including metadata, full
        position history, and current weights for the latest snapshot.
    """
    try:
        model_portfolio = service.get_model_portfolio(portfolio_id=portfolio_id)
        model_portfolio_current_snapshot: ModelPortfolioSnapshot = model_portfolio.position_history[-1]
        positions_current_weight,_,_ = service.calculate_positions_current_weight(model_portfolio_snapshot=model_portfolio_current_snapshot)
    except Exception as e:
        _raise_model_portfolio_http_exception(e)
    
    return ModelPortfolioResponse(
        portfolio_id=model_portfolio.portfolio_id,
        portfolio_owner_cognito_user_id=model_portfolio.portfolio_owner_cognito_user_id,
        portfolio_name=model_portfolio.portfolio_name,
        description=model_portfolio.description,
        position_history=[
            ModelPortfolioSnapshotResponse(
                positions=[
                    ModelPortfolioPositionResponse(
                        symbol=pos.symbol,
                        target_weight=pos.target_weight,
                        direction=pos.direction,
                        leverage=pos.leverage,
                    )
                    for pos in snap.positions
                ],
                timestamp=snap.timestamp.isoformat(),
            )
            for snap in model_portfolio.position_history
        ],
        created_at=model_portfolio.created_at.isoformat(),
        updated_at=model_portfolio.updated_at.isoformat(),
        positions_current_weight=positions_current_weight,
    )


@router.get("/{portfolio_id}/performance", response_model=ModelPortfolioPerformanceResponse, status_code=HTTP_200_OK)
def get_model_portfolio_performance(
    portfolio_id: str,
    user: Dict[str, Any] = Depends(get_current_user),
    service: ModelPortfolioPerformanceService = Depends(get_model_portfolio_performance_service),
) -> ModelPortfolioPerformanceResponse:
    """
    Retrieve snapshot-aware performance for one model portfolio.

    Args:
        portfolio_id: Identifier of the model portfolio to evaluate.
        user: Authenticated user claims resolved by dependency injection.
        service: Performance service dependency.

    Returns:
        Dict: Performance keyed by account-performance-style periods. Each
        period contains graph timestamps, cumulative return percentages, and
        model portfolio performance metrics.
    """
    try:
        return ModelPortfolioPerformanceResponse(
            service.get_model_portfolio_performance(portfolio_id=portfolio_id)
        )
    except Exception as e:
        _raise_model_portfolio_http_exception(e)


@router.post("", response_model=None, status_code=HTTP_201_CREATED)
def create_model_portfolio(
    request: CreateModelPortfolioRequest,
    user: Dict[str, Any] = Depends(get_current_user),
    service: ModelPortfolioRepository = Depends(get_model_portfolio_repository),
) -> None:
    """
    Create a new model portfolio for the authenticated user.

    Args:
        request: Request body containing portfolio name, description, and positions.
        user: Authenticated user claims resolved by dependency injection.
        service: Repository dependency for model portfolio operations.

    Returns:
        None.
    """

    cognito_user_id = user["sub"]

    try:
        service.create_model_portfolio(
            portfolio_owner_cognito_user_id=cognito_user_id, 
            portfolio_name=request.name, 
            positions_request=request.positions,
            description=request.description
        )
        return
    except Exception as e:
        _raise_model_portfolio_http_exception(e)


@router.put("/{portfolio_id}", response_model=None, status_code=HTTP_201_CREATED)
def update_model_portfolio(
    portfolio_id: str,
    request: UpdateModelPortfolioRequest,
    user: Dict[str, Any] = Depends(get_current_user),
    service: ModelPortfolioRepository = Depends(get_model_portfolio_repository),
) -> None:
    """
    Update an existing model portfolio by appending a new snapshot.

    Args:
        portfolio_id: Identifier of the portfolio to update.
        request: Request body containing the updated positions.
        user: Authenticated user claims resolved by dependency injection.
        service: Repository dependency for model portfolio operations.

    Returns:
        None.
    """
    # Check ownership
    cognito_user_id = user["sub"]
    try:
        portfolio: ModelPortfolio = service.get_model_portfolio(portfolio_id=portfolio_id)
    except Exception as e:
        _raise_model_portfolio_http_exception(e)
    
    if portfolio.portfolio_owner_cognito_user_id != cognito_user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")

    try:
        updated = service.update_model_portfolio(
            portfolio_id=portfolio_id,
            positions_request=request.positions,
            description=request.description,
        )
        if not updated:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Portfolio not found")
        return
    except HTTPException:
        raise
    except Exception as e:
        _raise_model_portfolio_http_exception(e)


@router.get("", response_model=ListUserModelPortfoliosResponse, status_code=HTTP_200_OK)
def list_user_model_portfolios(
    user: Dict[str, Any] = Depends(get_current_user),
    service: ModelPortfolioRepository = Depends(get_model_portfolio_repository),
) -> ListUserModelPortfoliosResponse:
    """
    List all model portfolios owned by the authenticated user.

    Args:
        user: Authenticated user claims resolved by dependency injection.
        service: Repository dependency for model portfolio operations.

    Returns:
        ListUserModelPortfoliosResponse: Collection of user portfolio
        summaries.
    """
    cognito_user_id = user["sub"]
    try:
        portfolios_meta_data = service.list_user_model_portfolio_names(portfolio_owner_cognito_user_id=cognito_user_id)
        return ListUserModelPortfoliosResponse(
            list_model_portfolio_metadata=[
                ModelPortfolioMetadataResponse(
                    portfolio_id=portfolio_metadata["portfolio_id"],
                    portfolio_name=portfolio_metadata["portfolio_name"],
                    description=portfolio_metadata.get("description"),
                )
                for portfolio_metadata in portfolios_meta_data
            ]
        )
    except Exception as e:
        _raise_model_portfolio_http_exception(e)
