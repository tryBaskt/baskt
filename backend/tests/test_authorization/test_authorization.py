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
    get_optional_portfolio_allocation_owner,
    require_active_alpaca_account,
    require_model_portfolio_access,
    require_model_portfolio_owner,
    require_model_portfolio_owner_match,
    require_portfolio_allocation_owner,
)
from domain.baskt_account_domain import (
    AgreementData,
    BasktAccount,
    ContactData,
    DisclosuresData,
    IdentityData,
)
from domain.model_portfolio_domain import ModelPortfolio
from domain.allocation_domain import PortfolioAllocation
from repository.model_portfolio_repository import ModelPortfolioNotFoundError
from repository.allocation_repository import AllocationNotFoundError


AUDIT_LOGGER = "baskt.audit.authorization"


class FakeModelPortfolioRepository:
    def __init__(self, portfolios: dict[str, ModelPortfolio]) -> None:
        self.portfolios = portfolios

    def get_model_portfolio(self, portfolio_id: str) -> ModelPortfolio:
        try:
            return self.portfolios[portfolio_id]
        except KeyError as err:
            raise ModelPortfolioNotFoundError(portfolio_id=portfolio_id) from err


class FakeAllocationRepository:
    def __init__(self, allocations: dict[tuple[str, str], PortfolioAllocation]) -> None:
        self.allocations = allocations

    def get_allocation(
        self,
        cognito_user_id: str,
        allocation_id: str,
    ) -> PortfolioAllocation:
        try:
            return self.allocations[(cognito_user_id, allocation_id)]
        except KeyError as err:
            raise AllocationNotFoundError(
                cognito_user_id=cognito_user_id,
                allocation_id=allocation_id,
            ) from err


class FakeModelPortfolioAccessRepository:
    def __init__(self, *, has_access: bool = False) -> None:
        self._has_access = has_access

    def has_access(
        self,
        *,
        portfolio_id: str,
        shared_with_cognito_user_id: str,
    ) -> bool:
        return self._has_access


class FakeAccountStatus:
    name = "SUBMITTED"


class FakeAlpacaAccount:
    id = "alpaca-account-1"
    status = FakeAccountStatus()


def _model_portfolio(
    *,
    portfolio_id: str = "portfolio-1",
    owner_id: str = "owner-user",
    visibility: str = "PUBLIC",
) -> ModelPortfolio:
    now = datetime.now(timezone.utc)
    return ModelPortfolio(
        portfolio_id=portfolio_id,
        portfolio_owner_cognito_user_id=owner_id,
        portfolio_name="Security Test Portfolio",
        position_history=[],
        created_at=now,
        updated_at=now,
        visibility=visibility,
    )


def _portfolio_allocation(
    *,
    portfolio_id: str = "portfolio-1",
    cognito_user_id: str = "owner-user",
) -> PortfolioAllocation:
    return PortfolioAllocation(
        allocation_id=portfolio_id,
        cognito_user_id=cognito_user_id,
        position_history=[],
        transaction_history=[],
        total_cost_basis=0.0,
        open_positions=False,
        open_orders=False,
        allocation_type="STOCK",
        portfolio_name="Security Test Allocation",
    )


def _baskt_account(
    *,
    cognito_user_id: str = "owner-user",
    alpaca_account_id: str = "alpaca-account-1",
) -> BasktAccount:
    return BasktAccount(
        cognito_user_id=cognito_user_id,
        display_name="Security Test Account",
        alpaca_account_id=alpaca_account_id,
        alpaca_account_number="BASKT123",
        agreements_data=[
            AgreementData(
                agreement="customer_agreement",
                signed_at=datetime.now(timezone.utc).isoformat(),
                ip_address="127.0.0.1",
            )
        ],
        disclosures_data=DisclosuresData(immediate_family_exposed=False),
        identity_data=IdentityData(
            given_name="Security",
            family_name="Tester",
            country_of_tax_residence="USA",
        ),
        contact_data=ContactData(
            email_address="security@example.com",
            phone_number=None,
            street_address="123 Test St",
            unit=None,
            city="Test City",
            state="CA",
            postal_code="94105",
            country="USA",
        ),
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


def test_model_portfolio_access_allows_owner_public_and_shared_private() -> None:
    owner_private = _model_portfolio(owner_id="owner-user", visibility="PRIVATE")
    public_portfolio = _model_portfolio(owner_id="owner-user", visibility="PUBLIC")

    owner_result = require_model_portfolio_access(
        portfolio_id="portfolio-1",
        cognito_user_id="owner-user",
        model_portfolio_repository=FakeModelPortfolioRepository(
            {"portfolio-1": owner_private}
        ),
        model_portfolio_access_repository=FakeModelPortfolioAccessRepository(
            has_access=False
        ),
    )
    assert owner_result is owner_private

    public_result = require_model_portfolio_access(
        portfolio_id="portfolio-1",
        cognito_user_id="viewer-user",
        model_portfolio_repository=FakeModelPortfolioRepository(
            {"portfolio-1": public_portfolio}
        ),
        model_portfolio_access_repository=FakeModelPortfolioAccessRepository(
            has_access=False
        ),
    )
    assert public_result is public_portfolio

    shared_result = require_model_portfolio_access(
        portfolio_id="portfolio-1",
        cognito_user_id="shared-user",
        model_portfolio_repository=FakeModelPortfolioRepository(
            {"portfolio-1": owner_private}
        ),
        model_portfolio_access_repository=FakeModelPortfolioAccessRepository(
            has_access=True
        ),
    )
    assert shared_result is owner_private


def test_model_portfolio_access_denies_unshared_private_portfolio(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING, logger=AUDIT_LOGGER)

    with pytest.raises(HTTPException) as exc_info:
        require_model_portfolio_access(
            portfolio_id="portfolio-1",
            cognito_user_id="viewer-user",
            model_portfolio_repository=FakeModelPortfolioRepository(
                {
                    "portfolio-1": _model_portfolio(
                        owner_id="owner-user",
                        visibility="PRIVATE",
                    )
                }
            ),
            model_portfolio_access_repository=FakeModelPortfolioAccessRepository(
                has_access=False
            ),
        )

    assert exc_info.value.status_code == 403
    _assert_audit_denial(caplog, "private_model_portfolio_access_missing")


def test_inactive_alpaca_account_is_denied_and_audited(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING, logger=AUDIT_LOGGER)

    with pytest.raises(HTTPException) as exc_info:
        require_active_alpaca_account(
            baskt_account=_baskt_account(),
            alpaca_account=FakeAlpacaAccount(),
        )

    assert exc_info.value.status_code == 403
    _assert_audit_denial(caplog, "alpaca_account_not_active")


def test_cross_user_portfolio_allocation_is_hidden_and_audited(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING, logger=AUDIT_LOGGER)
    repository = FakeAllocationRepository(
        {
            ("owner-user", "portfolio-1"): _portfolio_allocation(
                cognito_user_id="owner-user",
                portfolio_id="portfolio-1",
            )
        }
    )

    with pytest.raises(HTTPException) as exc_info:
        require_portfolio_allocation_owner(
            allocation_id="portfolio-1",
            cognito_user_id="other-user",
            allocation_repository=repository,
        )

    assert exc_info.value.status_code == 404
    _assert_audit_denial(caplog, "allocation_not_found_or_not_owned")


def test_optional_portfolio_allocation_owner_returns_owned_allocation() -> None:
    allocation = _portfolio_allocation(
        cognito_user_id="owner-user",
        portfolio_id="portfolio-1",
    )
    repository = FakeAllocationRepository(
        {("owner-user", "portfolio-1"): allocation}
    )

    result = get_optional_portfolio_allocation_owner(
        allocation_id="portfolio-1",
        cognito_user_id="owner-user",
        allocation_repository=repository,
    )

    assert result is allocation


def test_optional_portfolio_allocation_owner_allows_missing_allocation(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING, logger=AUDIT_LOGGER)
    repository = FakeAllocationRepository({})

    result = get_optional_portfolio_allocation_owner(
        allocation_id="portfolio-1",
        cognito_user_id="viewer-user",
        allocation_repository=repository,
    )

    assert result is None
    assert not any("authorization_denied" in record.message for record in caplog.records)
