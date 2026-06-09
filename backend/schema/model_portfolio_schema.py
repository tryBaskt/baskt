# backend/schema/model_portfolio_route.py

# Python imports
from __future__ import annotations
from typing import List
from pydantic import BaseModel


class ModelPortfolioPositionRequest(BaseModel):
    symbol: str
    target_weight: float
    direction: int
    leverage: float


class CreateModelPortfolioRequest(BaseModel):
    name: str
    positions: List[ModelPortfolioPositionRequest]
    description: str | None = None


class UpdateModelPortfolioRequest(BaseModel):
    positions: List[ModelPortfolioPositionRequest]
    description: str | None = None