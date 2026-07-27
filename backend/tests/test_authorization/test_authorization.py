from __future__ import annotations

import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi import HTTPException

backend_dir = Path(__file__).resolve().parents[2]
repo_root = Path(__file__).resolve().parents[3]
for import_path in (str(backend_dir), str(repo_root)):
    if import_path not in sys.path:
        sys.path.insert(0, import_path)

from core.authorization import (
    require_alpaca_account_owner,
    require_model_portfolio_owner,
    require_model_portfolio_owner_match,
    require_portfolio_allocation_owner,
)
from domain.model_portfolio_domain import ModelPortfolio
from domain.portfolio_allocation_domain import PortfolioAllocation
from repository.model_portfolio_repository import ModelPortfolioNotFoundError
from repository.portfolio_allocation_repository import PortfolioAllocationNotFoundError


AUDIT_LOGGER = "baskt.audit.authorization"


class FakeModelPortfolioRepository:
    def __init__(self, portfolios: dict[str, ModelPortfolio]) -> None:
        self.portfolios = portfolios

    def get_model_portfolio(self, portfolio_id: str) -> ModelPortfolio:
        try:
            return self.portfolios[portfolio_id]
        except KeyError as err:
            raise ModelPortfolioNotFoundError(portfolio_id=portfolio_id) from err


class FakePortfolioAllocationRepository:
    def __init__(self, allocations: dict[tuple[str, str], PortfolioAllocation]) -> None:
        self.allocations = allocations

    def get_portfolio_allocation(
        self,
        cognito_user_id: str,
        portfolio_id: str,
    ) -> PortfolioAllocation:
        try:
            return self.allocations[(cognito_user_id, portfolio_id)]
        except KeyError as err:
            raise PortfolioAllocationNotFoundError(
                cognito_user_id=cognito_user_id,
                portfolio_id=portfolio_id,
            ) from err


def _model_portfolio(
    *,
    portfolio_id: str = "portfolio-1",
    owner_id: str = "owner-user",
) -> ModelPortfolio:
    now = datetime.now(timezone.utc)
    return ModelPortfolio(
        portfolio_id=portfolio_id,
        portfolio_owner_cognito_user_id=owner_id,
        portfolio_name="Security Test Portfolio",
        position_history=[],
        created_at=now,
        updated_at=now,
    )


def _portfolio_allocation(
    *,
    portfolio_id: str = "portfolio-1",
    cognito_user_id: str = "owner-user",
) -> PortfolioAllocation:
    return PortfolioAllocation(
        portfolio_id=portfolio_id,
        cognito_user_id=cognito_user_id,
        position_history=[],
        transaction_history=[],
        total_cost_basis=0.0,
        portfolio_allocation_type="STOCK",
        portfolio_name="Security Test Allocation",
    )


def _assert_audit_denial(caplog: pytest.LogCaptureFixture, reason: str) -> None:
    assert any(
        "authorization_denied" in record.message and reason in record.message
        for record in caplog.records
    )


def test_cross_user_model_portfolio_owner_is_denied_and_audited(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING, logger=AUDIT_LOGGER)
    repository = FakeModelPortfolioRepository(
        {"portfolio-1": _model_portfolio(owner_id="owner-user")}
    )

    with pytest.raises(HTTPException) as exc_info:
        require_model_portfolio_owner(
            portfolio_id="portfolio-1",
            cognito_user_id="other-user",
            model_portfolio_repository=repository,
        )

    assert exc_info.value.status_code == 403
    _assert_audit_denial(caplog, "model_portfolio_owner_mismatch")


def test_cross_user_model_portfolio_owner_claim_is_denied_and_audited(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING, logger=AUDIT_LOGGER)
    repository = FakeModelPortfolioRepository(
        {"portfolio-1": _model_portfolio(owner_id="owner-user")}
    )

    with pytest.raises(HTTPException) as exc_info:
        require_model_portfolio_owner_match(
            portfolio_id="portfolio-1",
            portfolio_owner_cognito_user_id="other-user",
            model_portfolio_repository=repository,
            cognito_user_id="caller-user",
        )

    assert exc_info.value.status_code == 403
    _assert_audit_denial(caplog, "supplied_owner_does_not_match_portfolio")


def test_cross_user_alpaca_account_is_denied_and_audited(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING, logger=AUDIT_LOGGER)

    with pytest.raises(HTTPException) as exc_info:
        require_alpaca_account_owner(
            user={
                "sub": "owner-user",
                "custom:alpaca_acct_id": "alpaca-account-1",
            },
            alpaca_account_id="alpaca-account-2",
        )

    assert exc_info.value.status_code == 403
    _assert_audit_denial(caplog, "alpaca_account_mismatch")


def test_cross_user_portfolio_allocation_is_hidden_and_audited(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING, logger=AUDIT_LOGGER)
    repository = FakePortfolioAllocationRepository(
        {
            ("owner-user", "portfolio-1"): _portfolio_allocation(
                cognito_user_id="owner-user",
                portfolio_id="portfolio-1",
            )
        }
    )

    with pytest.raises(HTTPException) as exc_info:
        require_portfolio_allocation_owner(
            portfolio_id="portfolio-1",
            cognito_user_id="other-user",
            portfolio_allocation_repository=repository,
        )

    assert exc_info.value.status_code == 404
    _assert_audit_denial(caplog, "allocation_not_found_or_not_owned")
