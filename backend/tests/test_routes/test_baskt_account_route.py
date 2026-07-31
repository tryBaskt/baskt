from __future__ import annotations

import pytest

from conftest import OWNER_USER_ID, fake_baskt_account
from core.deps import get_baskt_account_repository, get_model_portfolio_repository
from repository.baskt_account_repository import BasktAccountNotFoundError
from routes.baskt_account_route import router as baskt_account_router


class FakeBasktAccountRepository:
    def __init__(self, *, missing: bool = False) -> None:
        self.missing = missing

    def get_baskt_account(self, cognito_user_id: str):
        if self.missing:
            raise BasktAccountNotFoundError(
                f"Baskt account not found for user {cognito_user_id}"
            )
        return fake_baskt_account(cognito_user_id=cognito_user_id)


class FakeModelPortfolioMetadataRepository:
    def get_model_portfolio_metadata_by_owner(self, portfolio_owner_cognito_user_id: str):
        return [
            {
                "portfolio_id": "portfolio-1",
                "portfolio_owner_cognito_user_id": portfolio_owner_cognito_user_id,
                "portfolio_name": "Growth",
                "created_at": "2024-01-01T00:00:00Z",
                "updated_at": "2024-01-02T00:00:00Z",
                "description": "Public growth portfolio",
            }
        ]


@pytest.fixture
def baskt_account_app(app_factory):
    app = app_factory(baskt_account_router)
    app.dependency_overrides[get_baskt_account_repository] = (
        lambda: FakeBasktAccountRepository()
    )
    app.dependency_overrides[get_model_portfolio_repository] = (
        lambda: FakeModelPortfolioMetadataRepository()
    )
    return app


@pytest.fixture
def baskt_account_client(baskt_account_app, client_for_app):
    with client_for_app(baskt_account_app) as client:
        yield client


def test_baskt_account_profile_route_returns_public_profile(
    baskt_account_client,
) -> None:
    response = baskt_account_client.get(f"/baskt-accounts/{OWNER_USER_ID}/profile")

    assert response.status_code == 200, response.text
    assert response.json()["baskt_account"]["cognito_user_id"] == OWNER_USER_ID
    assert response.json()["model_portfolios"][0]["portfolio_name"] == "Growth"


def test_baskt_account_profile_route_maps_missing_account(
    baskt_account_client,
    baskt_account_app,
) -> None:
    baskt_account_app.dependency_overrides[get_baskt_account_repository] = (
        lambda: FakeBasktAccountRepository(missing=True)
    )

    response = baskt_account_client.get(f"/baskt-accounts/{OWNER_USER_ID}/profile")

    assert response.status_code == 404
