"""Domain objects produced by VectorBT portfolio simulations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional


@dataclass(frozen=True)
class VectorBTPortfolioSimulation:
    """Normalized performance results from a VectorBT simulation.

    All return and metric values are decimal fractions. For example, ``0.12``
    represents 12 percent. Timestamps retain the timezone from the input price
    index.
    """

    timestamps: List[datetime]
    cumulative_returns: List[float]
    final_cumulative_return: float
    cagr: Optional[float]
    annualized_volatility: Optional[float]
    leverage_adjusted_direction: Optional[float]
