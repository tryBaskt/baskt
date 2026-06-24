# backend/domain/backtest.py

# Python imports
from __future__ import annotations
from dataclasses import dataclass

@dataclass(frozen=True)
class BacktestPosition:
    """Domain representation of a single backtest position."""
    symbol: str
    weight: float
    direction: int   # +1 long, -1 short
    leverage: float = 1
