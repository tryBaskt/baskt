# backend/api/routes/model_portfolio_route.py

from __future__ import annotations

from typing import Type

from fastapi import APIRouter, Depends, HTTPException
from starlette import status
from starlette.status import HTTP_200_OK, HTTP_201_CREATED
from core.authorization import require_active_alpaca_account, require_model_portfolio_owner
from core.authentication import (
	get_current_alpaca_account,
	get_current_baskt_account,
	get_alpaca_account_id,
	get_cognito_user_id

)
from core.deps import (
    get_baskt_account_repository,
    get_model_portfolio_analytics_service,
    get_model_portfolio_repository,
    get_trade_execution_queuing_service,
)
from domain.model_portfolio_domain import ModelPortfolioSnapshot
from domain.baskt_account_domain import BasktAccount
from repository.baskt_account_repository import (
    BasktAccountRepository,
    BasktAccountRepositoryError,
)
from repository.model_portfolio_repository import (
    ModelPortfolioRepository,
    ModelPortfolioNotFoundError, 
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
    ModelPortfolioAnalyticsResponse,
    ModelPortfolioPositionResponse,
    ModelPortfolioSnapshotResponse,
    ModelPortfolioMetadataResponse,
    ModelPortfoliosMetadataResponse,
)
from services.model_portfolio_analytics_service import (
    ModelPortfolioAnalyticsInternalServerError,
    ModelPortfolioAnalyticsService,
)
from services.trade_execution_queuing_service import (
    TradeExecutionQueuingInternalServerError,
    TradeExecutionQueuingService,
)


router = APIRouter(prefix="/model-portfolios", tags=["model-portfolios"])


MODEL_PORTFOLIO_ERROR_STATUS_MAP: tuple[tuple[Type[Exception], int], ...] = (
    (ModelPortfolioNotFoundError, status.HTTP_404_NOT_FOUND),
    (ModelPortfolioLockedError, status.HTTP_423_LOCKED),
    (ModelPortfolioTooManyRequestsError, status.HTTP_429_TOO_MANY_REQUESTS),
    (ModelPortfolioUnprocessableEntityError, status.HTTP_422_UNPROCESSABLE_CONTENT),
    (ModelPortfolioBadGatewayError, status.HTTP_502_BAD_GATEWAY),
    (ModelPortfolioInternalServerError, status.HTTP_500_INTERNAL_SERVER_ERROR),
    (ModelPortfolioAnalyticsInternalServerError, status.HTTP_500_INTERNAL_SERVER_ERROR),
)


def _raise_model_portfolio_http_exception(err: Exception) -> None:
    if isinstance(err, HTTPException):
        raise err

    if isinstance(err, TradeExecutionQueuingInternalServerError):
        if err.code == "TRADE_EXECUTION_QUEUE_LOCKED":
            status_code = status.HTTP_409_CONFLICT
        elif err.code == "TRADE_EXECUTION_QUEUE_MODEL_PORTFOLIO_SNAPSHOT_NOT_FOUND":
            status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
        elif err.code == "TRADE_EXECUTION_QUEUE_SEND_FAILED":
            status_code = status.HTTP_502_BAD_GATEWAY
        else:
            status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
        raise HTTPException(
            status_code=status_code,
            detail={"message": str(err), "code": err.code},
        ) from err

    for exception_type, status_code in MODEL_PORTFOLIO_ERROR_STATUS_MAP:
        if isinstance(err, exception_type):
            raise HTTPException(
                status_code=status_code,
                detail={
                    "message": str(err),
                    "code": getattr(err, "code", "MODEL_PORTFOLIO_ERROR"),
                },
            ) from err

    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail={
            "message": f"Unexpected model portfolio error: {err}",
            "code": "MODEL_PORTFOLIO_UNEXPECTED_ERROR",
        },
    ) from err


@router.get("/{portfolio_id}", response_model=ModelPortfolioResponse, status_code=HTTP_200_OK)
def get_model_portfolio(
    portfolio_id: str,
    baskt_account: BasktAccount = Depends(get_current_baskt_account),
    service: ModelPortfolioRepository = Depends(get_model_portfolio_repository),
    baskt_account_repository: BasktAccountRepository = Depends(
        get_baskt_account_repository
    ),
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
    
    try:
        portfolio_owner_display_name = baskt_account_repository.get_display_name(
            cognito_user_id=model_portfolio.portfolio_owner_cognito_user_id
        )
    except BasktAccountRepositoryError:
        portfolio_owner_display_name = None

    return ModelPortfolioResponse(
        portfolio_id=model_portfolio.portfolio_id,
        portfolio_owner_cognito_user_id=model_portfolio.portfolio_owner_cognito_user_id,
        portfolio_owner_display_name=portfolio_owner_display_name,
        portfolio_name=model_portfolio.portfolio_name,
        description=model_portfolio.description,
        position_history=[
            ModelPortfolioSnapshotResponse(
                snapshot_id=snap.snapshot_id,
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


@router.post("", response_model=None, status_code=HTTP_201_CREATED)
def create_model_portfolio(
    request: CreateModelPortfolioRequest,
    baskt_account: BasktAccount = Depends(get_current_baskt_account),
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

    try:
        cognito_user_id = get_cognito_user_id(baskt_account)
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
    baskt_account: BasktAccount = Depends(get_current_baskt_account),
    service: ModelPortfolioRepository = Depends(get_model_portfolio_repository),
    queuing_service: TradeExecutionQueuingService = Depends(
        get_trade_execution_queuing_service
    )
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

    try:
        cognito_user_id = get_cognito_user_id(baskt_account)
        require_model_portfolio_owner(
            portfolio_id=portfolio_id,
            cognito_user_id=cognito_user_id,
            model_portfolio_repository=service,

        )

        updated, new_snapshot_id = service.update_model_portfolio(
            portfolio_id=portfolio_id,
            positions_request=request.positions,
            description=request.description,
        )
        if not updated:
            return
        if new_snapshot_id is not None:
            queuing_service.queue_portfolio_update(
                portfolio_id=portfolio_id,
                portfolio_snapshot_id=new_snapshot_id,
            )
        return
    except HTTPException:
        raise
    except Exception as e:
        _raise_model_portfolio_http_exception(e)


@router.get("", response_model=ModelPortfoliosMetadataResponse, status_code=HTTP_200_OK)
def get_model_portfolio_metadata_by_owner(
    baskt_account: BasktAccount = Depends(get_current_baskt_account),
    service: ModelPortfolioRepository = Depends(get_model_portfolio_repository),
) -> ModelPortfoliosMetadataResponse:
    """
    List all model portfolios owned by the authenticated user.

    Args:
        user: Authenticated user claims resolved by dependency injection.
        service: Repository dependency for model portfolio operations.

    Returns:
        ModelPortfoliosMetadataResponse: Collection of user portfolio
        summaries.
    """

    try:
        cognito_user_id = get_cognito_user_id(baskt_account)
        portfolios_meta_data = service.get_model_portfolio_metadata_by_owner(portfolio_owner_cognito_user_id=cognito_user_id)
        return ModelPortfoliosMetadataResponse(
            root=[
                ModelPortfolioMetadataResponse(
                    portfolio_id=portfolio_metadata["portfolio_id"],
                    portfolio_owner_cognito_user_id=portfolio_metadata["portfolio_owner_cognito_user_id"],
                    portfolio_name=portfolio_metadata["portfolio_name"],
                    created_at=portfolio_metadata["created_at"],
                    updated_at=portfolio_metadata["updated_at"],
                    description=portfolio_metadata.get("description"),
                )
                for portfolio_metadata in portfolios_meta_data
            ]
        )
    except Exception as e:
        _raise_model_portfolio_http_exception(e)


@router.get("/{portfolio_id}/analytics", response_model=ModelPortfolioAnalyticsResponse, status_code=HTTP_200_OK)
def get_model_portfolio_analytics(
    portfolio_id: str,
    baskt_account: BasktAccount = Depends(get_current_baskt_account),
    service: ModelPortfolioAnalyticsService = Depends(get_model_portfolio_analytics_service),
) -> ModelPortfolioAnalyticsResponse:
    """
    Get model portfolio cumulative return series for standard periods.

    Args:
        portfolio_id: Identifier of the model portfolio to analyze.
        user: Authenticated user claims resolved by dependency injection.
        service: Analytics service dependency for model portfolio returns.

    Returns:
        ModelPortfolioAnalyticsResponse: Return series keyed by period.
    """
    try:
        return ModelPortfolioAnalyticsResponse(
            root=service.get_model_portfolio_bars(portfolio_id=portfolio_id)
        )
    except Exception as e:
        _raise_model_portfolio_http_exception(e)
