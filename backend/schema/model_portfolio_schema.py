# backend/schema/model_portfolio_schema.py

# Python imports
from __future__ import annotations
from typing import Dict, List, Optional
from pydantic import BaseModel, Field, RootModel
from datetime import datetime


class ModelPortfolioPositionRequest(BaseModel):
    symbol: str
    target_weight: float = Field(ge=0, le=1)
    direction: int
    leverage: float


class CreateModelPortfolioRequest(BaseModel):
    name: str
    positions: List[ModelPortfolioPositionRequest]
    description: Optional[str] = None
    visibility: str


class UpdateModelPortfolioRequest(BaseModel):
    positions: List[ModelPortfolioPositionRequest]
    description: Optional[str] = None
    visibility: str


class AddAccessModelPortfolioRequest(BaseModel):
    email_address: str

class RemoveAccessModelPortfolioRequest(BaseModel):
    cognito_user_id: str

class SharedWithUserModelPortfolioResponse(BaseModel):
    cognito_user_id: str
    email_address: str

class SharedWithUsersModelPortfolioResponse(RootModel[List[SharedWithUserModelPortfolioResponse]]):
    pass

class ModelPortfolioPositionResponse(BaseModel):
    symbol: str
    target_weight: float
    direction: int
    leverage: float


class ModelPortfolioSnapshotResponse(BaseModel):
    snapshot_id: str
    positions: List[ModelPortfolioPositionResponse]
    timestamp: str


class ModelPortfolioResponse(BaseModel):
    portfolio_id: str
    portfolio_owner_cognito_user_id: str
    portfolio_owner_display_name: Optional[str] = None
    portfolio_name: str
    description: Optional[str] = None
    visibility: str
    position_history: List[ModelPortfolioSnapshotResponse]
    created_at: str
    updated_at: str
    positions_current_weight: Dict[str, float]


class ModelPortfolioAnalyticsPeriodResponse(BaseModel):
    timeframe: str
    timestamp: List[datetime]
    cumulative_returns: List[float]
    final_cumulative_return: float
    cagr: Optional[float] = None
    annualized_volatility: Optional[float] = None
    leverage_adjusted_direction: Optional[float] = None
    alpha: Optional[float] = None
    beta: Optional[float] = None
    sharpe_ratio: Optional[float] = None
    maximum_drawdown: Optional[float] = None
    maximum_drawdown_duration: Optional[float] = None


class ModelPortfolioAnalyticsResponse(RootModel[Dict[str, ModelPortfolioAnalyticsPeriodResponse]]):
    pass


class ModelPortfolioMetadataResponse(BaseModel):
    portfolio_id: str
    portfolio_owner_cognito_user_id: str
    portfolio_name: str
    created_at: str
    updated_at: str
    description: Optional[str] = None
    visibility: Optional[str] = None


class ModelPortfoliosMetadataResponse(RootModel[List[ModelPortfolioMetadataResponse]]):
    pass
