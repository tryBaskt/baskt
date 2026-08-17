from __future__ import annotations

import os
from datetime import datetime, timezone
from time import monotonic, sleep
from uuid import uuid4

from conftest import OWNER_ALPACA_ACCOUNT_ID, OWNER_USER_ID, OTHER_USER_ID
from core import deps as app_deps
from routes.model_portfolio_route import router as model_portfolio_router
from schema.model_portfolio_schema import ModelPortfolioPositionRequest


def _model_portfolio_repositories():
    alpaca_broker_client = app_deps.get_alpaca_broker_client()
    update_lock_repository = app_deps.get_model_portfolio_update_lock_repository(
        model_portfolio_update_lock_dynamodb_client=(
            app_deps.get_model_portfolio_update_lock_dynamodb_client()
        )
    )
    follower_repository = app_deps.get_model_portfolio_follower_repository(
        model_portfolio_follower_dynamodb_client=(
            app_deps.get_model_portfolio_follower_dynamodb_client()
        ),
        alpaca_broker_client=alpaca_broker_client,
    )
    access_repository = app_deps.get_model_portfolio_access_repository(
        model_portfolio_access_dynamodb_client=(
            app_deps.get_model_portfolio_access_dynamodb_client()
        ),
        cognito_client=app_deps.get_cognito_client(),
        model_portfolio_follower_repository=follower_repository,
        model_portfolio_update_lock_repository=update_lock_repository,
    )
    model_portfolio_repository = app_deps.get_model_portfolio_repository(
        dynamodb=app_deps.get_model_portfolio_dynamodb_client(),
        alpaca_broker_client=alpaca_broker_client,
        model_portfolio_update_lock_repository=update_lock_repository,
        model_portfolio_follower_repository=follower_repository,
        model_portfolio_access_repository=access_repository,
    )
    return model_portfolio_repository, access_repository


def _create_private_owner_portfolio(portfolio_name: str) -> str:
    model_portfolio_repository, _ = _model_portfolio_repositories()
    return model_portfolio_repository.create_model_portfolio(
        portfolio_owner_cognito_user_id=OWNER_USER_ID,
        portfolio_name=portfolio_name,
        positions_request=[
            ModelPortfolioPositionRequest(
                symbol="AAPL",
                target_weight=1.0,
                direction=1,
                leverage=1.0,
            )
        ],
        visibility="PRIVATE",
        creation_time=datetime(2024, 1, 2, 14, 0, tzinfo=timezone.utc),
        description="Created by model portfolio route integration test.",
    )


def _delete_model_portfolio(portfolio_id: str) -> None:
    model_portfolio_repository, _ = _model_portfolio_repositories()
    try:
        model_portfolio_repository.dynamodb.delete_item(
            key={"portfolio_id": portfolio_id}
        )
    except Exception:
        pass


def _test_user_email(number: int) -> str:
    env_prefix = os.getenv("ENV", "dev").strip().upper()
    email_address = os.getenv(f"{env_prefix}_TEST_USER_{number}_EMAIL_ADDRESS", "")
    if not email_address.strip():
        raise RuntimeError(
            f"{env_prefix}_TEST_USER_{number}_EMAIL_ADDRESS is required for route tests"
        )
    return email_address.strip()


def _get_shared_portfolio_from_route(client, portfolio_id: str) -> dict:
    deadline = monotonic() + 5
    last_response_text = ""

    while monotonic() < deadline:
        response = client.get("/model-portfolios/shared-with-me")
        last_response_text = response.text
        assert response.status_code == 200, response.text

        for portfolio in response.json():
            if portfolio["portfolio_id"] == portfolio_id:
                return portfolio

        sleep(0.25)

    raise AssertionError(
        f"Shared portfolio {portfolio_id} was not returned: {last_response_text}"
    )


def test_owned_model_portfolios_route_uses_real_dependencies(
    app_factory,
    client_for_app,
) -> None:
    app = app_factory(
        model_portfolio_router,
        cognito_user_id=OWNER_USER_ID,
        alpaca_account_id=OWNER_ALPACA_ACCOUNT_ID,
    )

    with client_for_app(app) as client:
        response = client.get("/model-portfolios")

    assert response.status_code == 200, response.text
    assert isinstance(response.json(), list)


def test_shared_with_me_route_uses_real_dependencies(
    app_factory,
    client_for_app,
) -> None:
    app = app_factory(model_portfolio_router)

    with client_for_app(app) as client:
        response = client.get("/model-portfolios/shared-with-me")

    assert response.status_code == 200, response.text
    assert isinstance(response.json(), list)


def test_authenticated_owner_can_create_model_portfolio(
    app_factory,
    client_for_app,
) -> None:
    portfolio_name = f"Route Owner Create {uuid4()}"
    created_portfolio_id = None

    try:
        app = app_factory(
            model_portfolio_router,
            cognito_user_id=OWNER_USER_ID,
            alpaca_account_id=OWNER_ALPACA_ACCOUNT_ID,
        )

        with client_for_app(app) as client:
            create_response = client.post(
                "/model-portfolios",
                json={
                    "name": portfolio_name,
                    "positions": [
                        {
                            "symbol": "AAPL",
                            "target_weight": 1.0,
                            "direction": 1,
                            "leverage": 1.0,
                        }
                    ],
                    "description": "Created through the model portfolio route test.",
                    "visibility": "PRIVATE",
                },
            )
            list_response = client.get("/model-portfolios")

        assert create_response.status_code == 201, create_response.text
        assert list_response.status_code == 200, list_response.text
        created_portfolio = next(
            portfolio
            for portfolio in list_response.json()
            if portfolio["portfolio_name"] == portfolio_name
        )
        created_portfolio_id = created_portfolio["portfolio_id"]
        assert created_portfolio["portfolio_owner_cognito_user_id"] == OWNER_USER_ID
        assert created_portfolio["description"] == (
            "Created through the model portfolio route test."
        )
        assert created_portfolio["visibility"] == "PRIVATE"
    finally:
        if created_portfolio_id is not None:
            _delete_model_portfolio(created_portfolio_id)


def test_authenticated_user_can_list_model_portfolios_shared_with_them(
    app_factory,
    client_for_app,
) -> None:
    _, access_repository = _model_portfolio_repositories()
    portfolio_id = _create_private_owner_portfolio(
        f"Route Shared With Me {uuid4()}"
    )
    access_granted = False

    try:
        access_repository.add_access_via_cognito_user_id(
            portfolio_id=portfolio_id,
            portfolio_owner_cognito_user_id=OWNER_USER_ID,
            shared_with_cognito_user_id=OTHER_USER_ID,
            granted_access_by="PORTFOLIO_OWNER",
        )
        access_granted = True
        app = app_factory(model_portfolio_router)

        with client_for_app(app) as client:
            shared_portfolio = _get_shared_portfolio_from_route(
                client,
                portfolio_id,
            )

        assert shared_portfolio["portfolio_owner_cognito_user_id"] == OWNER_USER_ID
        assert shared_portfolio["visibility"] == "PRIVATE"
    finally:
        if access_granted:
            access_repository.remove_access_via_cognito_user_id(
                portfolio_id=portfolio_id,
                shared_with_cognito_user_id=OTHER_USER_ID,
            )
        _delete_model_portfolio(portfolio_id)


def test_authenticated_owner_can_fetch_model_portfolio_with_display_name(
    app_factory,
    client_for_app,
) -> None:
    portfolio_id = _create_private_owner_portfolio(
        f"Route Owner Fetch {uuid4()}"
    )

    try:
        app = app_factory(
            model_portfolio_router,
            cognito_user_id=OWNER_USER_ID,
            alpaca_account_id=OWNER_ALPACA_ACCOUNT_ID,
        )

        with client_for_app(app) as client:
            response = client.get(f"/model-portfolios/{portfolio_id}")

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["portfolio_id"] == portfolio_id
        assert body["portfolio_owner_cognito_user_id"] == OWNER_USER_ID
        assert "portfolio_owner_display_name" in body
        assert body["visibility"] == "PRIVATE"
        assert body["position_history"]
    finally:
        _delete_model_portfolio(portfolio_id)


def test_authenticated_owner_can_update_model_portfolio(
    app_factory,
    client_for_app,
) -> None:
    portfolio_id = _create_private_owner_portfolio(
        f"Route Owner Update {uuid4()}"
    )

    try:
        app = app_factory(
            model_portfolio_router,
            cognito_user_id=OWNER_USER_ID,
            alpaca_account_id=OWNER_ALPACA_ACCOUNT_ID,
        )

        with client_for_app(app) as client:
            response = client.put(
                f"/model-portfolios/{portfolio_id}",
                json={
                    "positions": [
                        {
                            "symbol": "AAPL",
                            "target_weight": 0.6,
                            "direction": 1,
                            "leverage": 1.0,
                        },
                        {
                            "symbol": "MSFT",
                            "target_weight": 0.4,
                            "direction": 1,
                            "leverage": 1.0,
                        },
                    ],
                    "description": "Updated by model portfolio route test.",
                    "visibility": "PUBLIC",
                },
            )
            get_response = client.get(f"/model-portfolios/{portfolio_id}")

        assert response.status_code == 201, response.text
        assert get_response.status_code == 200, get_response.text
        body = get_response.json()
        assert body["description"] == "Updated by model portfolio route test."
        assert body["visibility"] == "PUBLIC"
        assert len(body["position_history"]) == 2
        latest_positions = body["position_history"][-1]["positions"]
        assert {position["symbol"] for position in latest_positions} == {
            "AAPL",
            "MSFT",
        }
    finally:
        _delete_model_portfolio(portfolio_id)


def test_authenticated_owner_can_add_and_get_model_portfolio_accesses(
    app_factory,
    client_for_app,
) -> None:
    _, access_repository = _model_portfolio_repositories()
    portfolio_id = _create_private_owner_portfolio(
        f"Route Owner Accesses {uuid4()}"
    )
    access_granted = False

    try:
        app = app_factory(
            model_portfolio_router,
            cognito_user_id=OWNER_USER_ID,
            alpaca_account_id=OWNER_ALPACA_ACCOUNT_ID,
        )
        shared_with_email = _test_user_email(1)

        with client_for_app(app) as client:
            add_response = client.post(
                f"/model-portfolios/{portfolio_id}/accesses",
                json={"email_address": shared_with_email},
            )
            access_granted = add_response.status_code == 201
            get_response = client.get(f"/model-portfolios/{portfolio_id}/accesses")

        assert add_response.status_code == 201, add_response.text
        assert get_response.status_code == 200, get_response.text
        accesses = get_response.json()
        assert {
            "cognito_user_id": OTHER_USER_ID,
            "email_address": shared_with_email,
        } in accesses
    finally:
        if access_granted:
            access_repository.remove_access_via_cognito_user_id(
                portfolio_id=portfolio_id,
                shared_with_cognito_user_id=OTHER_USER_ID,
            )
        _delete_model_portfolio(portfolio_id)


def test_authenticated_non_owner_cannot_fetch_private_model_portfolio(
    app_factory,
    client_for_app,
) -> None:
    portfolio_id = _create_private_owner_portfolio(
        f"Route Private No Access {uuid4()}"
    )

    try:
        app = app_factory(model_portfolio_router)

        with client_for_app(app) as client:
            response = client.get(f"/model-portfolios/{portfolio_id}")

        assert response.status_code == 403
    finally:
        _delete_model_portfolio(portfolio_id)
