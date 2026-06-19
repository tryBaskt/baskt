# backend/schema/model_portfolio_schema.py

# Python imports
from __future__ import annotations
from typing import Dict, List, Optional
from pydantic import BaseModel, Field, RootModel


class ModelPortfolioPositionRequest(BaseModel):
    symbol: str
    target_weight: float = Field(ge=0, le=1)
    direction: int
    leverage: float


class CreateModelPortfolioRequest(BaseModel):
    name: str
    positions: List[ModelPortfolioPositionRequest]
    description: Optional[str] = None


class UpdateModelPortfolioRequest(BaseModel):
    positions: List[ModelPortfolioPositionRequest]
    description: Optional[str] = None

class ModelPortfolioPositionResponse(BaseModel):
    symbol: str
    target_weight: float
    direction: int
    leverage: float


class ModelPortfolioSnapshotResponse(BaseModel):
    positions: List[ModelPortfolioPositionResponse]
    timestamp: str


class ModelPortfolioResponse(BaseModel):
    portfolio_id: str
    portfolio_owner_cognito_user_id: str
    portfolio_name: str
    description: Optional[str] = None
    position_history: List[ModelPortfolioSnapshotResponse]
    created_at: str
    updated_at: str
    positions_current_weight: Dict[str, float]


class ModelPortfolioAnalyticsPeriodResponse(BaseModel):
    timeframe: str
    timestamp: List[str]
    cumulative_returns: List[float]
    cagr: Optional[float] = None
    annualized_volatility: Optional[float] = None
    leverage_adjusted_direction: Optional[float] = None


class ModelPortfolioAnalyticsResponse(RootModel[Dict[str, ModelPortfolioAnalyticsPeriodResponse]]):
    pass

class ModelPortfolioMetadataResponse(BaseModel):
    portfolio_id: str
    portfolio_name: str
    description: Optional[str] = None

class ListUserModelPortfoliosResponse(BaseModel):
    list_model_portfolio_metadata: List[ModelPortfolioMetadataResponse]
