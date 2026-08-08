from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict

import pytest

from conftest import OTHER_USER_ID, OWNER_USER_ID, fake_baskt_account
from core.authentication import get_current_baskt_account
from core.deps import (
    get_baskt_account_repository,
    get_model_portfolio_access_repository,
    get_model_portfolio_repository,
    get_trade_execution_queuing_service,
)
from domain.model_portfolio_domain import (
    ModelPortfolio,
    ModelPortfolioPosition,
    ModelPortfolioSnapshot,
)
from repository.model_portfolio_access_repository import (
    ModelPortfolioAccessUserIsFollowerError,
)
from repository.model_portfolio_repository import ModelPortfolioNotFoundError
from routes.model_portfolio_route import router as model_portfolio_router


class FakeBasktAccountRepository:
    def get_display_name(self, cognito_user_id: str) -> str:
        return f"display-{cognito_user_id}"


class FakeModelPortfolioRepository:
    def __init__(self, *, portfolio_visibility: str = "PUBLIC") -> None:
        now = datetime.now(timezone.utc)
        self.portfolio = ModelPortfolio(
            portfolio_id="portfolio-1",
            portfolio_owner_cognito_user_id=OWNER_USER_ID,
            portfolio_name="Owner Portfolio",
            position_history=[
                ModelPortfolioSnapshot(
                    snapshot_id="snapshot-1",
                    timestamp=now,
                    positions=[
                        ModelPortfolioPosition(
                            symbol="AAPL",
                            target_weight=1.0,
                            direction=1,
                            leverage=1.0,
                            model_filled_quantity=10.0,
                            model_filled_avg_price=100.0,
                        )
                    ],
                )
            ],
            created_at=now,
            updated_at=now,
            description="owned by owner-user",
        )
        object.__setattr__(self.portfolio, "visibility", portfolio_visibility)
        self.update_called = False
        self.create_calls: list[Dict[str, Any]] = []
        self.update_calls: list[Dict[str, Any]] = []

    def get_model_portfolio(
        self,
        portfolio_id: str,
        *args: Any,
        **kwargs: Any,
    ) -> ModelPortfolio:
        if portfolio_id != self.portfolio.portfolio_id:
            raise ModelPortfolioNotFoundError(portfolio_id=portfolio_id)
        return self.portfolio

    def calculate_positions_current_weight(
        self,
        model_portfolio_snapshot: ModelPortfolioSnapshot,
    ):
        return {"AAPL": 1.0}, 1000.0, {"AAPL": 100.0}

    def create_model_portfolio(self, *args: Any, **kwargs: Any):
        self.create_calls.append(kwargs)
        return "portfolio-created"

    def update_model_portfolio(self, *args: Any, **kwargs: Any):
        self.update_called = True
        self.update_calls.append(kwargs)
        return True, "snapshot-2"

    def get_model_portfolio_metadata_by_owner(self, portfolio_owner_cognito_user_id: str):
        if portfolio_owner_cognito_user_id != OWNER_USER_ID:
            return []
        return [self.get_model_portfolio_metadata_by_portfolio_id("portfolio-1")]

    def get_model_portfolio_metadata_by_portfolio_id(self, portfolio_id: str):
        if portfolio_id != self.portfolio.portfolio_id:
            raise ModelPortfolioNotFoundError(portfolio_id=portfolio_id)
        return {
            "portfolio_id": self.portfolio.portfolio_id,
            "portfolio_owner_cognito_user_id": (
                self.portfolio.portfolio_owner_cognito_user_id
            ),
            "portfolio_name": self.portfolio.portfolio_name,
            "created_at": self.portfolio.created_at.isoformat(),
            "updated_at": self.portfolio.updated_at.isoformat(),
            "description": self.portfolio.description,
            "visibility": self.portfolio.visibility,
        }


class FakeTradeExecutionQueuingService:
    def __init__(self) -> None:
        self.queue_update_called = False

    def queue_portfolio_update(self, *args: Any, **kwargs: Any) -> Dict[str, str]:
        self.queue_update_called = True
        return {}


class FakeModelPortfolioAccessRepository:
    def __init__(self) -> None:
        self.accesses = [
            {
                "portfolio_id": "portfolio-1",
                "portfolio_owner_cognito_user_id": OWNER_USER_ID,
                "shared_with_cognito_user_id": "shared-user",
                "shared_with_cognito_user_email": "shared@example.com",
            }
        ]
        self.add_calls: list[Dict[str, str]] = []
        self.remove_calls: list[Dict[str, str]] = []
        self.blocked_removals: set[tuple[str, str]] = set()

    def add_access_for_user(self, **kwargs: str) -> None:
        self.add_calls.append(kwargs)

    def remove_access_for_user(self, **kwargs: str) -> None:
        removal_key = (
            kwargs["shared_with_cognito_user_id"],
            kwargs["portfolio_id"],
        )
        if removal_key in self.blocked_removals:
            raise ModelPortfolioAccessUserIsFollowerError(
                portfolio_id=kwargs["portfolio_id"],
                shared_with_cognito_user_id=kwargs["shared_with_cognito_user_id"],
            )
        self.remove_calls.append(kwargs)

    def get_accesses_for_portfolio(self, *, portfolio_id: str):
        return [
            access
            for access in self.accesses
            if access["portfolio_id"] == portfolio_id
        ]

    def has_access(
        self,
        *,
        portfolio_id: str,
        shared_with_cognito_user_id: str,
    ) -> bool:
        return any(
            access["portfolio_id"] == portfolio_id
            and access["shared_with_cognito_user_id"] == shared_with_cognito_user_id
            for access in self.accesses
        )

    def get_accesses_shared_with_user(self, *, shared_with_cognito_user_id: str):
        return [
            access
            for access in self.accesses
            if access["shared_with_cognito_user_id"] == shared_with_cognito_user_id
        ]


@pytest.fixture
def model_portfolio_app(app_factory):
    app = app_factory(model_portfolio_router)
    repository = FakeModelPortfolioRepository()
    access_repository = FakeModelPortfolioAccessRepository()
    queuing_service = FakeTradeExecutionQueuingService()
    app.dependency_overrides[get_model_portfolio_repository] = lambda: repository
    app.dependency_overrides[get_model_portfolio_access_repository] = (
        lambda: access_repository
    )
    app.dependency_overrides[get_baskt_account_repository] = (
        lambda: FakeBasktAccountRepository()
    )
    app.dependency_overrides[get_trade_execution_queuing_service] = (
        lambda: queuing_service
    )
    return {
        "app": app,
        "repository": repository,
        "access_repository": access_repository,
        "queuing_service": queuing_service,
    }


@pytest.fixture
def model_portfolio_client(model_portfolio_app, client_for_app):
    with client_for_app(model_portfolio_app["app"]) as client:
        yield client


def test_non_owner_cannot_update_model_portfolio(
    model_portfolio_client,
    model_portfolio_app,
) -> None:
    response = model_portfolio_client.put(
        "/model-portfolios/portfolio-1",
        json={
            "positions": [
                {
                    "symbol": "AAPL",
                    "target_weight": 1.0,
                    "direction": 1,
                    "leverage": 1.0,
                }
            ],
            "description": "attempted cross-user update",
            "visibility": "PUBLIC",
        },
    )

    assert response.status_code == 403
    assert model_portfolio_app["repository"].update_called is False
    assert model_portfolio_app["queuing_service"].queue_update_called is False


def test_authenticated_user_can_fetch_public_model_portfolio(
    model_portfolio_client,
) -> None:
    response = model_portfolio_client.get("/model-portfolios/portfolio-1")

    assert response.status_code == 200, response.text
    assert response.json()["portfolio_id"] == "portfolio-1"
    assert response.json()["portfolio_owner_cognito_user_id"] == OWNER_USER_ID
    assert response.json()["visibility"] == "PUBLIC"


def test_owner_can_fetch_private_model_portfolio(
    model_portfolio_client,
    model_portfolio_app,
) -> None:
    model_portfolio_app["repository"].portfolio = FakeModelPortfolioRepository(
        portfolio_visibility="PRIVATE"
    ).portfolio
    model_portfolio_app["app"].dependency_overrides[get_current_baskt_account] = (
        lambda: fake_baskt_account(cognito_user_id=OWNER_USER_ID)
    )

    response = model_portfolio_client.get("/model-portfolios/portfolio-1")

    assert response.status_code == 200, response.text
    assert response.json()["visibility"] == "PRIVATE"


def test_authenticated_user_can_list_model_portfolios_shared_with_them(
    model_portfolio_client,
    model_portfolio_app,
) -> None:
    model_portfolio_app["access_repository"].accesses.append(
        {
            "portfolio_id": "portfolio-1",
            "portfolio_owner_cognito_user_id": OWNER_USER_ID,
            "shared_with_cognito_user_id": OTHER_USER_ID,
            "shared_with_cognito_user_email": "other@example.com",
        }
    )

    response = model_portfolio_client.get("/model-portfolios/shared-with-me")

    assert response.status_code == 200, response.text
    assert response.json() == [
        {
            "portfolio_id": "portfolio-1",
            "portfolio_owner_cognito_user_id": OWNER_USER_ID,
            "portfolio_name": "Owner Portfolio",
            "created_at": model_portfolio_app["repository"].portfolio.created_at.isoformat(),
            "updated_at": model_portfolio_app["repository"].portfolio.updated_at.isoformat(),
            "description": "owned by owner-user",
            "visibility": "PUBLIC",
        }
    ]


def test_owner_create_and_update_include_visibility(
    model_portfolio_client,
    model_portfolio_app,
) -> None:
    model_portfolio_app["app"].dependency_overrides[get_current_baskt_account] = (
        lambda: fake_baskt_account(cognito_user_id=OWNER_USER_ID)
    )

    create_response = model_portfolio_client.post(
        "/model-portfolios",
        json={
            "name": "Private Create",
            "positions": [
                {
                    "symbol": "AAPL",
                    "target_weight": 1.0,
                    "direction": 1,
                    "leverage": 1.0,
                }
            ],
            "description": "only shared users can see this",
            "visibility": "PRIVATE",
        },
    )
    assert create_response.status_code == 201, create_response.text
    assert model_portfolio_app["repository"].create_calls[-1]["visibility"] == "PRIVATE"
    assert (
        model_portfolio_app["repository"].create_calls[-1]["description"]
        == "only shared users can see this"
    )

    update_response = model_portfolio_client.put(
        "/model-portfolios/portfolio-1",
        json={
            "positions": [
                {
                    "symbol": "AAPL",
                    "target_weight": 1.0,
                    "direction": 1,
                    "leverage": 1.0,
                }
            ],
            "description": "back to public",
            "visibility": "PUBLIC",
        },
    )
    assert update_response.status_code == 201, update_response.text
    assert model_portfolio_app["repository"].update_calls[-1]["visibility"] == "PUBLIC"
    assert model_portfolio_app["queuing_service"].queue_update_called is True


def test_owner_can_add_remove_and_list_model_portfolio_accesses(
    model_portfolio_client,
    model_portfolio_app,
) -> None:
    model_portfolio_app["app"].dependency_overrides[get_current_baskt_account] = (
        lambda: fake_baskt_account(cognito_user_id=OWNER_USER_ID)
    )

    add_response = model_portfolio_client.post(
        "/model-portfolios/portfolio-1/accesses",
        json={"email_address": "new-share@example.com"},
    )
    assert add_response.status_code == 201, add_response.text
    assert model_portfolio_app["access_repository"].add_calls == [
        {
            "portfolio_id": "portfolio-1",
            "portfolio_owner_cognito_user_id": OWNER_USER_ID,
            "shared_with_email": "new-share@example.com",
        }
    ]

    list_response = model_portfolio_client.get(
        "/model-portfolios/portfolio-1/accesses"
    )
    assert list_response.status_code == 200, list_response.text
    assert list_response.json() == [
        {
            "cognito_user_id": "shared-user",
            "email_address": "shared@example.com",
        }
    ]

    remove_response = model_portfolio_client.request(
        "DELETE",
        "/model-portfolios/portfolio-1/accesses",
        json={"cognito_user_id": "shared-user"},
    )
    assert remove_response.status_code == 200, remove_response.text
    assert model_portfolio_app["access_repository"].remove_calls == [
        {
            "portfolio_id": "portfolio-1",
            "shared_with_cognito_user_id": "shared-user",
        }
    ]


def test_non_owner_cannot_manage_model_portfolio_accesses(
    model_portfolio_client,
    model_portfolio_app,
) -> None:
    response = model_portfolio_client.post(
        "/model-portfolios/portfolio-1/accesses",
        json={"email_address": "new-share@example.com"},
    )

    assert response.status_code == 403
    assert model_portfolio_app["access_repository"].add_calls == []


def test_owner_cannot_remove_access_for_invested_user(
    model_portfolio_client,
    model_portfolio_app,
) -> None:
    model_portfolio_app["app"].dependency_overrides[get_current_baskt_account] = (
        lambda: fake_baskt_account(cognito_user_id=OWNER_USER_ID)
    )
    model_portfolio_app["access_repository"].blocked_removals.add(
        ("shared-user", "portfolio-1")
    )

    response = model_portfolio_client.request(
        "DELETE",
        "/model-portfolios/portfolio-1/accesses",
        json={"cognito_user_id": "shared-user"},
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "MODEL_PORTFOLIO_ACCESS_USER_IS_FOLLOWER"
    assert model_portfolio_app["access_repository"].remove_calls == []


def test_authenticated_non_owner_cannot_fetch_private_model_portfolio(
    model_portfolio_client,
    model_portfolio_app,
) -> None:
    model_portfolio_app["repository"].portfolio = FakeModelPortfolioRepository(
        portfolio_visibility="PRIVATE"
    ).portfolio

    response = model_portfolio_client.get("/model-portfolios/portfolio-1")

    assert response.status_code == 403


def test_shared_user_can_fetch_private_model_portfolio(
    model_portfolio_client,
    model_portfolio_app,
) -> None:
    model_portfolio_app["repository"].portfolio = FakeModelPortfolioRepository(
        portfolio_visibility="PRIVATE"
    ).portfolio
    model_portfolio_app["access_repository"].accesses.append(
        {
            "portfolio_id": "portfolio-1",
            "portfolio_owner_cognito_user_id": OWNER_USER_ID,
            "shared_with_cognito_user_id": OTHER_USER_ID,
            "shared_with_cognito_user_email": "other@example.com",
        }
    )

    response = model_portfolio_client.get("/model-portfolios/portfolio-1")

    assert response.status_code == 200, response.text
    assert response.json()["visibility"] == "PRIVATE"
