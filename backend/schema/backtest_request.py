# backend/schema/backtest_request.py

# Python imports
from __future__ import annotations
from pydantic import BaseModel
from datetime import date
from typing import List

# Baskt imports
from model_portfolio_request import ModelPortfolioPositionRequest


class BacktestRequest(BaseModel):
    start_date: date
    end_date: date
    positions: List[ModelPortfolioPositionRequest]