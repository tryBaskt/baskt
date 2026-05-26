# backend/api/routes/model_portfolio_route.py

from __future__ import annotations

from typing import Dict, List

from fastapi import APIRouter, Depends, HTTPException
from starlette import status
from schema.model_portfolio_request import CreateModelPortfolioRequest, UpdateModelPortfolioRequest
from core.deps import get_current_user, get_model_portfolio_repository
from domain.model_portfolio import ModelPortfolio, ModelPortfolioSnapshot
from repository.model_portfolio_repository import (ModelPortfolioRepository,
                                                   ModelPortfolioNotFoundError, 
                                                   ModelPortfolioPositionHistoryNotFoundError,
                                                   ModelPortfolioInternalServerError,
                                                   ModelPortfolioUnprocessableEntityError,
                                                   ModelPortfolioTooManyRequestsError,
                                                   ModelPortfolioBadGatewayError,
                                                   ModelPortfolioLockedError)


router = APIRouter()


@router.get("/model-portfolio/{portfolio_id}")
def get_model_portfolio(
    portfolio_id: str,
    user: Dict[str, str] = Depends(get_current_user),
    service: ModelPortfolioRepository = Depends(get_model_portfolio_repository),
):
    """
    Retrieve a single model portfolio and its latest computed current weights.

    Args:
        portfolio_id: Identifier of the model portfolio to fetch.
        user: Authenticated user claims resolved by dependency injection.
        service: Repository dependency for model portfolio operations.

    Returns:
        Dict: Portfolio payload including metadata, full position history,
        and `positions_current_weight` for the latest snapshot.
    """
    try:
        model_portfolio = service.get_model_portfolio(portfolio_id=portfolio_id)
        model_portfolio_current_snapshot: ModelPortfolioSnapshot = model_portfolio.position_history[-1]
        positions_current_weight,_,_ = service.calculate_positions_current_weight(model_portfolio_snapshot=model_portfolio_current_snapshot)
    except ModelPortfolioNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except ModelPortfolioPositionHistoryNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except ModelPortfolioLockedError as e:
        raise HTTPException(status_code=status.HTTP_423_LOCKED, detail=str(e))
    except ModelPortfolioTooManyRequestsError as e:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(e))
    except ModelPortfolioUnprocessableEntityError as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))
    except ModelPortfolioInternalServerError as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))
    except ModelPortfolioBadGatewayError as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Unexpected model portfolio error: {str(e)}")
    
    return {
        "portfolio_id": model_portfolio.portfolio_id,
        "portfolio_owner_id": model_portfolio.portfolio_owner_id,
        "portfolio_name": model_portfolio.portfolio_name,
        "description": model_portfolio.description,
        "position_history": [
            {
                "positions": [
                    {
                        "symbol": pos.symbol,
                        "target_weight": pos.target_weight,
                        "direction": pos.direction,
                        "leverage": pos.leverage
                    }
                    for pos in snap.positions
                ],
                "timestamp": snap.timestamp.isoformat(),
            }
            for snap in model_portfolio.position_history
        ],
        "created_at": model_portfolio.created_at.isoformat(),
        "updated_at": model_portfolio.updated_at.isoformat(),
        "positions_current_weight": positions_current_weight
    }


@router.post("/model-portfolio", response_model=Dict[str, str])
def create_model_portfolio(
    request: CreateModelPortfolioRequest,
    user: Dict[str, str] = Depends(get_current_user),
    service: ModelPortfolioRepository = Depends(get_model_portfolio_repository),
):
    """
    Create a new model portfolio for the authenticated user.

    Args:
        request: Request body containing portfolio name, description, and positions.
        user: Authenticated user claims resolved by dependency injection.
        service: Repository dependency for model portfolio operations.

    Returns:
        Dict[str, str]: Newly created portfolio identifier in the form
        `{ "portfolio_id": "..." }`.
    """

    user_id = user["sub"]

    try:
        portfolio_id = service.create_model_portfolio(
            portfolio_owner_id=user_id, 
            portfolio_name=request.name, 
            positions_request=request.positions,
            description=request.description
        )
        return {"portfolio_id": portfolio_id}
    except ModelPortfolioNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except ModelPortfolioPositionHistoryNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except ModelPortfolioLockedError as e:
        raise HTTPException(status_code=status.HTTP_423_LOCKED, detail=str(e))
    except ModelPortfolioTooManyRequestsError as e:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(e))
    except ModelPortfolioUnprocessableEntityError as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))
    except ModelPortfolioInternalServerError as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))
    except ModelPortfolioBadGatewayError as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Unexpected model portfolio error: {str(e)}")


@router.put("/model-portfolio/{portfolio_id}", response_model=Dict[str, str])
def update_model_portfolio(
    portfolio_id: str,
    request: UpdateModelPortfolioRequest,
    user: Dict[str, str] = Depends(get_current_user),
    service: ModelPortfolioRepository = Depends(get_model_portfolio_repository),
):
    """
    Update an existing model portfolio by appending a new snapshot.

    Args:
        portfolio_id: Identifier of the portfolio to update.
        request: Request body containing the updated positions.
        user: Authenticated user claims resolved by dependency injection.
        service: Repository dependency for model portfolio operations.

    Returns:
        Dict[str, str]: Success message in the form
        `{ "message": "Portfolio updated" }`.
    """
    # Check ownership
    user_id = user["sub"]
    try:
        portfolio: ModelPortfolio = service.get_model_portfolio(portfolio_id=portfolio_id)
    except ModelPortfolioNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except ModelPortfolioPositionHistoryNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except ModelPortfolioLockedError as e:
        raise HTTPException(status_code=status.HTTP_423_LOCKED, detail=str(e))
    except ModelPortfolioTooManyRequestsError as e:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(e))
    except ModelPortfolioUnprocessableEntityError as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))
    except ModelPortfolioInternalServerError as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))
    except ModelPortfolioBadGatewayError as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Unexpected model portfolio error: {str(e)}")
    
    if portfolio.portfolio_owner_id != user["sub"]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")

    try:
        updated = service.update_model_portfolio(portfolio_id=portfolio_id, positions_request=request.positions)
        if not updated:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Portfolio not found")
        return {"message": "Portfolio updated"}
    except ModelPortfolioNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except ModelPortfolioPositionHistoryNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except ModelPortfolioLockedError as e:
        raise HTTPException(status_code=status.HTTP_423_LOCKED, detail=str(e))
    except ModelPortfolioTooManyRequestsError as e:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(e))
    except ModelPortfolioUnprocessableEntityError as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))
    except ModelPortfolioInternalServerError as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))
    except ModelPortfolioBadGatewayError as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Unexpected model portfolio error: {str(e)}")


@router.get("/user-model-portfolios", response_model=List[Dict])
def list_user_model_portfolios(
    user: Dict[str, str] = Depends(get_current_user),
    service: ModelPortfolioRepository = Depends(get_model_portfolio_repository),
):
    """
    List all model portfolios owned by the authenticated user.

    Args:
        user: Authenticated user claims resolved by dependency injection.
        service: Repository dependency for model portfolio operations.

    Returns:
        List[Dict]: Collection of user portfolio summaries.
    """
    user_id = user["sub"]
    try:
        portfolio_ids_names = service.list_user_model_portfolio_names(portfolio_owner_id=user_id)
        return portfolio_ids_names
    except ModelPortfolioNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except ModelPortfolioPositionHistoryNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except ModelPortfolioLockedError as e:
        raise HTTPException(status_code=status.HTTP_423_LOCKED, detail=str(e))
    except ModelPortfolioTooManyRequestsError as e:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(e))
    except ModelPortfolioUnprocessableEntityError as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))
    except ModelPortfolioInternalServerError as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))
    except ModelPortfolioBadGatewayError as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Unexpected model portfolio error: {str(e)}")


@router.delete("/model-portfolio/{portfolio_id}")
def delete_model_portfolio(
    portfolio_id: str,
    user: Dict[str, str] = Depends(get_current_user),
    service: ModelPortfolioRepository = Depends(get_model_portfolio_repository),
):
    """
    Delete a model portfolio owned by the authenticated user.

    Args:
        portfolio_id: Identifier of the portfolio to delete.
        user: Authenticated user claims resolved by dependency injection.
        service: Repository dependency for model portfolio operations.

    Returns:
        Dict[str, str]: Success message in the form
        `{ "message": "Portfolio deleted" }`.
    """
    user_id = user["sub"]  # Assuming Cognito sub as user_id
    # First, get the portfolio to check ownership
    try:
        model_portfolio: ModelPortfolio = service.get_model_portfolio(portfolio_id=portfolio_id)
    except ModelPortfolioNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except ModelPortfolioPositionHistoryNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except ModelPortfolioLockedError as e:
        raise HTTPException(status_code=status.HTTP_423_LOCKED, detail=str(e))
    except ModelPortfolioTooManyRequestsError as e:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(e))
    except ModelPortfolioUnprocessableEntityError as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))
    except ModelPortfolioInternalServerError as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))
    except ModelPortfolioBadGatewayError as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Unexpected model portfolio error: {str(e)}")
    
    if model_portfolio.portfolio_owner_id != user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
    deleted = service.delete_model_portfolio(portfolio_id=portfolio_id, portfolio_owner_id=user_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Unexpected model portfolio error: {str(e)}")
    return {"message": "Portfolio deleted"}
