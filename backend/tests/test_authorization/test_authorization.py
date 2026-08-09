from __future__ import annotations

import logging
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from dotenv import load_dotenv
from fastapi import HTTPException

backend_dir = Path(__file__).resolve().parents[2]
repo_root = Path(__file__).resolve().parents[3]
for import_path in (str(backend_dir), str(repo_root)):
    if import_path not in sys.path:
        sys.path.insert(0, import_path)

load_dotenv(repo_root / ".env")

from core.authorization import (
    get_optional_portfolio_allocation_owner,
    require_active_alpaca_account,
    require_model_portfolio_access,
    require_model_portfolio_owner,
)
from clients.alpaca_broker_client import AlpacaBrokerClient
from clients.cognito_client import CognitoClient
from core import deps as app_deps
from core.config import get_settings
from domain.allocation_domain import (
    PortfolioAllocation,
    PortfolioAllocationPosition,
    PortfolioAllocationPositionSnapshot,
    PortfolioAllocationTransactionSnapshot,
)
from repository.allocation_repository import AllocationRepository
from repository.baskt_account_repository import BasktAccountRepository
from repository.model_portfolio_access_repository import (
    ModelPortfolioAccessRepository,
)
from repository.model_portfolio_follower_repository import (
    ModelPortfolioFollowerRepository,
)
from repository.model_portfolio_repository import ModelPortfolioRepository
from repository.model_portfolio_update_lock_repository import (
    ModelPortfolioUpdateLockRepository,
)
from schema.model_portfolio_schema import ModelPortfolioPositionRequest
from services.account_lifecycle_service import AccountLifecycleService


AUDIT_LOGGER = "baskt.audit.authorization"
get_settings.cache_clear()


def _required_env_value(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is required for authorization tests.")
    return value


def _test_env_prefix() -> str:
    return get_settings().env.upper()


@dataclass(frozen=True)
class AuthorizationTestUser:
    cognito_user_id: str
    alpaca_account_id: str
    email_address: str


def _test_user(number: int) -> AuthorizationTestUser:
    env_prefix = _test_env_prefix()
    return AuthorizationTestUser(
        cognito_user_id=_required_env_value(
            f"{env_prefix}_TEST_USER_{number}_COGNITO_USER_ID"
        ),
        alpaca_account_id=_required_env_value(
            f"{env_prefix}_TEST_USER_{number}_ALPACA_ACCOUNT_ID"
        ),
        email_address=_required_env_value(
            f"{env_prefix}_TEST_USER_{number}_EMAIL_ADDRESS"
        ),
    )


@pytest.fixture(scope="session")
def owner_user() -> AuthorizationTestUser:
    return _test_user(2)


@pytest.fixture(scope="session")
def other_user() -> AuthorizationTestUser:
    return _test_user(1)


@pytest.fixture(scope="session")
def alpaca_broker_client() -> AlpacaBrokerClient:
    return app_deps.get_alpaca_broker_client()


@pytest.fixture(scope="session")
def cognito_client() -> CognitoClient:
    return app_deps.get_cognito_client()


@pytest.fixture(scope="session")
def model_portfolio_update_lock_repository() -> ModelPortfolioUpdateLockRepository:
    return app_deps.get_model_portfolio_update_lock_repository(
        model_portfolio_update_lock_dynamodb_client=(
            app_deps.get_model_portfolio_update_lock_dynamodb_client()
        )
    )


@pytest.fixture(scope="session")
def model_portfolio_follower_repository(
    alpaca_broker_client: AlpacaBrokerClient,
) -> ModelPortfolioFollowerRepository:
    return app_deps.get_model_portfolio_follower_repository(
        model_portfolio_follower_dynamodb_client=(
            app_deps.get_model_portfolio_follower_dynamodb_client()
        ),
        alpaca_broker_client=alpaca_broker_client,
    )


@pytest.fixture(scope="session")
def model_portfolio_access_repository(
    cognito_client: CognitoClient,
    model_portfolio_follower_repository: ModelPortfolioFollowerRepository,
    model_portfolio_update_lock_repository: ModelPortfolioUpdateLockRepository,
) -> ModelPortfolioAccessRepository:
    return app_deps.get_model_portfolio_access_repository(
        model_portfolio_access_dynamodb_client=(
            app_deps.get_model_portfolio_access_dynamodb_client()
        ),
        cognito_client=cognito_client,
        model_portfolio_follower_repository=model_portfolio_follower_repository,
        model_portfolio_update_lock_repository=model_portfolio_update_lock_repository,
    )


@pytest.fixture(scope="session")
def model_portfolio_repository(
    alpaca_broker_client: AlpacaBrokerClient,
    model_portfolio_update_lock_repository: ModelPortfolioUpdateLockRepository,
    model_portfolio_follower_repository: ModelPortfolioFollowerRepository,
    model_portfolio_access_repository: ModelPortfolioAccessRepository,
) -> ModelPortfolioRepository:
    return app_deps.get_model_portfolio_repository(
        dynamodb=app_deps.get_model_portfolio_dynamodb_client(),
        alpaca_broker_client=alpaca_broker_client,
        model_portfolio_update_lock_repository=model_portfolio_update_lock_repository,
        model_portfolio_follower_repository=model_portfolio_follower_repository,
        model_portfolio_access_repository=model_portfolio_access_repository,
    )


@pytest.fixture(scope="session")
def allocation_repository(
    alpaca_broker_client: AlpacaBrokerClient,
) -> AllocationRepository:
    return app_deps.get_allocation_repository(
        allocation_dynamodb_client=app_deps.get_allocation_dynamodb_client(),
        alpaca_broker_client=alpaca_broker_client,
    )


@pytest.fixture(scope="session")
def baskt_account_repository() -> BasktAccountRepository:
    return app_deps.get_baskt_account_repository(
        baskt_account_dynamodb_client=app_deps.get_baskt_account_dynamodb_client(),
    )


@pytest.fixture(scope="session")
def account_lifecycle_service(
    alpaca_broker_client: AlpacaBrokerClient,
    cognito_client: CognitoClient,
    baskt_account_repository: BasktAccountRepository,
) -> AccountLifecycleService:
    return AccountLifecycleService(
        alpaca_broker_client=alpaca_broker_client,
        cognito_client=cognito_client,
        baskt_account_repository=baskt_account_repository,
    )


def _create_model_portfolio(
    *,
    model_portfolio_repository: ModelPortfolioRepository,
    owner_id: str,
    visibility: str,
) -> str:
    return model_portfolio_repository.create_model_portfolio(
        portfolio_owner_cognito_user_id=owner_id,
        portfolio_name=f"Authorization Test Portfolio {uuid4()}",
        positions_request=[
            ModelPortfolioPositionRequest(
                symbol="AAPL",
                target_weight=1.0,
                direction=1,
                leverage=1.0,
            )
        ],
        visibility=visibility,
        creation_time=datetime(2024, 1, 2, 14, 0, tzinfo=timezone.utc),
        description="Created by authorization integration test.",
    )


def _delete_model_portfolio(
    *,
    model_portfolio_repository: ModelPortfolioRepository,
    portfolio_id: str,
) -> None:
    try:
        model_portfolio_repository.dynamodb.delete_item(
            key={"portfolio_id": portfolio_id}
        )
    except Exception:
        pass


def _portfolio_allocation(cognito_user_id: str) -> PortfolioAllocation:
    unique_suffix = uuid4().hex
    timestamp = datetime(2024, 1, 1, tzinfo=timezone.utc)
    return PortfolioAllocation(
        allocation_id=f"authorization-allocation-{unique_suffix}",
        cognito_user_id=cognito_user_id,
        position_history=[
            PortfolioAllocationPositionSnapshot(
                positions=[
                    PortfolioAllocationPosition(
                        symbol="AAPL",
                        filled_quantity=1,
                        direction=1,
                        filled_avg_price=100,
                    )
                ],
                timestamp=timestamp,
            )
        ],
        transaction_history=[
            PortfolioAllocationTransactionSnapshot(
                transaction_id=f"authorization-transaction-{unique_suffix}",
                created_at=timestamp,
                updated_at=timestamp,
                requested_amount=100,
                transaction_type="DEPOSIT",
                status="FULLY_FILLED",
                filled_at=timestamp,
                number_orders=1,
                cost_basis=100,
                order_fill_percent=100,
            )
        ],
        total_cost_basis=100,
        open_positions=True,
        open_orders=False,
        allocation_type="MODEL_PORTFOLIO",
        portfolio_name=f"Authorization Allocation Test {unique_suffix[:8]}",
    )


def _unique_account_payload() -> dict:
    unique_suffix = uuid4().hex
    return {
        "display_name": f"Authorization Test {unique_suffix[:12]}",
        "contact": {
            "email_address": f"baskt_authorization_test_{unique_suffix}@example.com",
            "phone_number": "+15555551234",
            "street_address": ["123 Market St"],
            "unit": "9A",
            "city": "San Francisco",
            "state": "CA",
            "postal_code": "94105",
            "country": "USA",
        },
        "identity": {
            "given_name": "Authorization",
            "middle_name": "Q",
            "family_name": "Tester",
            "date_of_birth": "1990-01-01",
            "tax_id": "999-99-1234",
            "tax_id_type": "USA_SSN",
            "country_of_citizenship": "USA",
            "country_of_birth": "USA",
            "country_of_tax_residence": "USA",
            "funding_source": ["employment_income", "savings"],
            "annual_income_min": 50000,
            "annual_income_max": 120000,
            "liquid_net_worth_min": 10000,
            "liquid_net_worth_max": 50000,
            "total_net_worth_min": 50000,
            "total_net_worth_max": 200000,
        },
        "disclosures": {
            "is_control_person": False,
            "is_affiliated_exchange_or_finra": False,
            "is_politically_exposed": False,
            "immediate_family_exposed": False,
            "employment_status": "EMPLOYED",
            "employer_name": "Baskt Authorization Test Employer",
            "employer_address": "123 Market St, San Francisco, CA 94105",
            "employment_position": "Software Engineer",
        },
        "agreements": [
            {
                "agreement": agreement,
                "signed_at": datetime.now(timezone.utc).isoformat(),
                "ip_address": "127.0.0.1",
            }
            for agreement in (
                "account_agreement",
                "customer_agreement",
                "margin_agreement",
                "crypto_agreement",
            )
        ],
    }


def _delete_portfolio_allocation(
    *,
    allocation_repository: AllocationRepository,
    allocation: PortfolioAllocation,
) -> None:
    try:
        allocation_repository.allocation_table_client.delete_item(
            key={
                "cognito_user_id": allocation.cognito_user_id,
                "allocation_id": allocation.allocation_id,
            }
        )
    except Exception:
        pass


def _assert_audit_denial(caplog: pytest.LogCaptureFixture, reason: str) -> None:
    assert any(
        "authorization_denied" in record.message and reason in record.message
        for record in caplog.records
    )


def test_cross_user_model_portfolio_owner_is_denied_and_audited(
    caplog: pytest.LogCaptureFixture,
    model_portfolio_repository: ModelPortfolioRepository,
    owner_user: AuthorizationTestUser,
    other_user: AuthorizationTestUser,
) -> None:
    """Deny and audit a non-owner attempting an owner-only portfolio action."""
    caplog.set_level(logging.WARNING, logger=AUDIT_LOGGER)
    portfolio_id = _create_model_portfolio(
        model_portfolio_repository=model_portfolio_repository,
        owner_id=owner_user.cognito_user_id,
        visibility="PRIVATE",
    )

    try:
        with pytest.raises(HTTPException) as exc_info:
            require_model_portfolio_owner(
                portfolio_id=portfolio_id,
                cognito_user_id=other_user.cognito_user_id,
                model_portfolio_repository=model_portfolio_repository,
            )
    finally:
        _delete_model_portfolio(
            model_portfolio_repository=model_portfolio_repository,
            portfolio_id=portfolio_id,
        )

    assert exc_info.value.status_code == 403
    _assert_audit_denial(caplog, "model_portfolio_owner_mismatch")


def test_model_portfolio_access_allows_owner_public_and_shared_private(
    model_portfolio_repository: ModelPortfolioRepository,
    model_portfolio_access_repository: ModelPortfolioAccessRepository,
    owner_user: AuthorizationTestUser,
    other_user: AuthorizationTestUser,
) -> None:
    """Allow model portfolio access for owners, public portfolios, and shared users."""
    private_portfolio_id = _create_model_portfolio(
        model_portfolio_repository=model_portfolio_repository,
        owner_id=owner_user.cognito_user_id,
        visibility="PRIVATE",
    )
    public_portfolio_id = _create_model_portfolio(
        model_portfolio_repository=model_portfolio_repository,
        owner_id=owner_user.cognito_user_id,
        visibility="PUBLIC",
    )

    access_granted = False
    try:
        model_portfolio_access_repository.add_access_for_user_by_cognito_user_id(
            portfolio_id=private_portfolio_id,
            portfolio_owner_cognito_user_id=owner_user.cognito_user_id,
            shared_with_cognito_user_id=other_user.cognito_user_id,
        )
        access_granted = True

        owner_result = require_model_portfolio_access(
            portfolio_id=private_portfolio_id,
            cognito_user_id=owner_user.cognito_user_id,
            model_portfolio_repository=model_portfolio_repository,
            model_portfolio_access_repository=model_portfolio_access_repository,
        )
        assert owner_result.portfolio_id == private_portfolio_id

        public_result = require_model_portfolio_access(
            portfolio_id=public_portfolio_id,
            cognito_user_id=other_user.cognito_user_id,
            model_portfolio_repository=model_portfolio_repository,
            model_portfolio_access_repository=model_portfolio_access_repository,
        )
        assert public_result.portfolio_id == public_portfolio_id

        shared_result = require_model_portfolio_access(
            portfolio_id=private_portfolio_id,
            cognito_user_id=other_user.cognito_user_id,
            model_portfolio_repository=model_portfolio_repository,
            model_portfolio_access_repository=model_portfolio_access_repository,
        )
        assert shared_result.portfolio_id == private_portfolio_id
    finally:
        if access_granted:
            model_portfolio_access_repository.remove_access_for_user(
                portfolio_id=private_portfolio_id,
                shared_with_cognito_user_id=other_user.cognito_user_id,
            )
        _delete_model_portfolio(
            model_portfolio_repository=model_portfolio_repository,
            portfolio_id=private_portfolio_id,
        )
        _delete_model_portfolio(
            model_portfolio_repository=model_portfolio_repository,
            portfolio_id=public_portfolio_id,
        )


def test_model_portfolio_access_denies_unshared_private_portfolio(
    caplog: pytest.LogCaptureFixture,
    model_portfolio_repository: ModelPortfolioRepository,
    model_portfolio_access_repository: ModelPortfolioAccessRepository,
    owner_user: AuthorizationTestUser,
    other_user: AuthorizationTestUser,
) -> None:
    """Deny and audit access when a private portfolio is not owned or shared."""
    caplog.set_level(logging.WARNING, logger=AUDIT_LOGGER)
    portfolio_id = _create_model_portfolio(
        model_portfolio_repository=model_portfolio_repository,
        owner_id=owner_user.cognito_user_id,
        visibility="PRIVATE",
    )

    try:
        with pytest.raises(HTTPException) as exc_info:
            require_model_portfolio_access(
                portfolio_id=portfolio_id,
                cognito_user_id=other_user.cognito_user_id,
                model_portfolio_repository=model_portfolio_repository,
                model_portfolio_access_repository=model_portfolio_access_repository,
            )
    finally:
        _delete_model_portfolio(
            model_portfolio_repository=model_portfolio_repository,
            portfolio_id=portfolio_id,
        )

    assert exc_info.value.status_code == 403
    _assert_audit_denial(caplog, "private_model_portfolio_access_missing")


def test_active_alpaca_account_is_allowed_with_real_account(
    baskt_account_repository: BasktAccountRepository,
    alpaca_broker_client: AlpacaBrokerClient,
    owner_user: AuthorizationTestUser,
) -> None:
    """Allow authorization to continue when the real Alpaca account is ACTIVE."""
    baskt_account = baskt_account_repository.get_baskt_account(
        owner_user.cognito_user_id
    )
    alpaca_account = alpaca_broker_client.get_alpaca_account_by_id(
        account_id=owner_user.alpaca_account_id,
        cognito_user_id=owner_user.cognito_user_id,
    )

    result = require_active_alpaca_account(
        baskt_account=baskt_account,
        alpaca_account=alpaca_account,
    )

    assert result is alpaca_account
    assert alpaca_account.status.name.upper() == "ACTIVE"


def test_inactive_new_alpaca_account_is_denied_and_audited(
    caplog: pytest.LogCaptureFixture,
    account_lifecycle_service: AccountLifecycleService,
    baskt_account_repository: BasktAccountRepository,
    alpaca_broker_client: AlpacaBrokerClient,
) -> None:
    """Deny and audit a newly created real Alpaca account that is not yet ACTIVE."""
    caplog.set_level(logging.WARNING, logger=AUDIT_LOGGER)
    create_account_response: dict[str, str] | None = None

    try:
        unique_suffix = uuid4().hex
        create_account_response = account_lifecycle_service.create_baskt_account(
            account_data=_unique_account_payload(),
            password=f"Test_9aA{unique_suffix[:16]}",
        )
        cognito_user_id = create_account_response["cognito_user_id"]
        alpaca_account_id = create_account_response["alpaca_account_id"]
        baskt_account = baskt_account_repository.get_baskt_account(cognito_user_id)
        alpaca_account = alpaca_broker_client.get_alpaca_account_by_id(
            account_id=alpaca_account_id,
            cognito_user_id=cognito_user_id,
        )

        with pytest.raises(HTTPException) as exc_info:
            require_active_alpaca_account(
                baskt_account=baskt_account,
                alpaca_account=alpaca_account,
            )
    finally:
        if create_account_response:
            try:
                account_lifecycle_service.permanently_close_baskt_account(
                    cognito_user_id=create_account_response["cognito_user_id"],
                    alpaca_account_id=create_account_response["alpaca_account_id"],
                )
            except Exception:
                pass

    assert exc_info.value.status_code == 403
    _assert_audit_denial(caplog, "alpaca_account_not_active")


def test_optional_portfolio_allocation_owner_returns_owned_allocation(
    allocation_repository: AllocationRepository,
    owner_user: AuthorizationTestUser,
) -> None:
    """Return an allocation when it exists for the authenticated owner."""
    allocation = _portfolio_allocation(cognito_user_id=owner_user.cognito_user_id)
    allocation_repository.set_allocation(allocation)

    try:
        result = get_optional_portfolio_allocation_owner(
            allocation_id=allocation.allocation_id,
            cognito_user_id=owner_user.cognito_user_id,
            allocation_repository=allocation_repository,
        )
    finally:
        _delete_portfolio_allocation(
            allocation_repository=allocation_repository,
            allocation=allocation,
        )

    assert result is not None
    assert result.allocation_id == allocation.allocation_id
    assert result.cognito_user_id == owner_user.cognito_user_id


def test_optional_portfolio_allocation_owner_allows_missing_allocation(
    caplog: pytest.LogCaptureFixture,
    allocation_repository: AllocationRepository,
    other_user: AuthorizationTestUser,
) -> None:
    """Return None without auditing a denial when the optional allocation is missing."""
    caplog.set_level(logging.WARNING, logger=AUDIT_LOGGER)

    result = get_optional_portfolio_allocation_owner(
        allocation_id=f"missing-authorization-allocation-{uuid4().hex}",
        cognito_user_id=other_user.cognito_user_id,
        allocation_repository=allocation_repository,
    )

    assert result is None
    assert not any("authorization_denied" in record.message for record in caplog.records)
