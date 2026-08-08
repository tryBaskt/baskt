from __future__ import annotations

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
    model_portfolio_repository.dynamodb.delete_item(
        key={"portfolio_id": portfolio_id}
    )


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
        access_repository.add_access_for_user_by_cognito_user_id(
            portfolio_id=portfolio_id,
            portfolio_owner_cognito_user_id=OWNER_USER_ID,
            shared_with_cognito_user_id=OTHER_USER_ID,
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
            access_repository.remove_access_for_user(
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
