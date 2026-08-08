from __future__ import annotations

from time import monotonic, sleep
from typing import Any
from uuid import uuid4

import pytest

from backend.tests.test_services.test_trade_execution_queuing.conftest import (
    TestEngine,
)
from backend.tests.mock_alpaca.trading import MockSQSClient
from routes.trade_execution_route import router as trade_execution_router
from routes.trade_execution_route import (
    buy_stock,
    close_stock,
    deposit_into_portfolio,
    sell_all_from_portfolio,
    sell_stock,
    withdraw_from_portfolio,
)
from schema.model_portfolio_schema import ModelPortfolioPositionRequest
from schema.trade_execution_schema import (
    BuyStockRequest,
    DepositIntoPortfolioRequest,
    SellStockRequest,
    WithdrawFromPortfolioRequest,
)


pytest_plugins = (
    "backend.tests.test_services.test_trade_execution_queuing.conftest",
)


@pytest.fixture
def route_trade_test_engine(request) -> TestEngine:
    return request.getfixturevalue("test_engine")


def _create_public_portfolio(test_engine: TestEngine) -> str:
    return test_engine.model_portfolio_repository.create_model_portfolio(
        portfolio_owner_cognito_user_id=test_engine.portfolio_owner_cognito_user_id,
        portfolio_name=f"Route Trade Execution {uuid4()}",
        positions_request=[
            ModelPortfolioPositionRequest(
                symbol="AAPL",
                target_weight=1.0,
                direction=1,
                leverage=1.0,
            )
        ],
        visibility="PUBLIC",
    )


def _delete_portfolio(test_engine: TestEngine, portfolio_id: str) -> None:
    try:
        test_engine.model_portfolio_repository.dynamodb.delete_item(
            key={"portfolio_id": portfolio_id}
        )
    except Exception:
        pass


def _baskt_account_and_alpaca_account(test_engine: TestEngine):
    baskt_account = test_engine.account_lifecycle_service.get_baskt_account(
        test_engine.funded_50000_cognito_user_id
    )
    alpaca_account = test_engine.alpaca_broker_client.get_alpaca_account_by_id(
        account_id=test_engine.funded_50000_alpaca_account_id,
        cognito_user_id=test_engine.funded_50000_cognito_user_id,
    )
    return baskt_account, alpaca_account


def _is_mock_alpaca(test_engine: TestEngine) -> bool:
    return isinstance(test_engine.sqs_client, MockSQSClient)


def _stock_asset_id(test_engine: TestEngine, symbol: str) -> str:
    if _is_mock_alpaca(test_engine):
        return str(uuid4())
    return test_engine.alpaca_broker_client.get_stock_by_symbol(
        symbol=symbol
    ).stock_id


def _previous_transaction_ids(
    test_engine: TestEngine,
    *,
    cognito_user_id: str,
    allocation_id: str,
) -> set[str]:
    if not test_engine.allocation_repository.is_exists_allocation_for_user(
        cognito_user_id=cognito_user_id,
        allocation_id=allocation_id,
    ):
        return set()

    allocation = test_engine.allocation_repository.get_allocation(
        cognito_user_id=cognito_user_id,
        allocation_id=allocation_id,
    )
    return {
        transaction.transaction_id
        for transaction in allocation.transaction_history
    }


def _wait_for_route_trade_execution(
    test_engine: TestEngine,
    *,
    route_action: Any,
    expected_action: str,
    cognito_user_id: str,
    alpaca_account_id: str,
    allocation_id: str,
) -> dict[str, Any]:
    previous_transaction_ids = _previous_transaction_ids(
        test_engine,
        cognito_user_id=cognito_user_id,
        allocation_id=allocation_id,
    )
    processed_message_count = (
        len(test_engine.sqs_client.processed_messages)
        if _is_mock_alpaca(test_engine)
        else 0
    )

    route_response = route_action()
    assert route_response.success is True

    if _is_mock_alpaca(test_engine):
        test_engine.sqs_client.wait_until_idle()
        processed_message = next(
            message
            for message in test_engine.sqs_client.processed_messages[
                processed_message_count:
            ]
            if message["message"]["action"] == expected_action
        )
        transaction_id = processed_message["message"]["payload"]["transaction_id"]
    else:
        transaction_id = test_engine._wait_for_new_transaction(
            cognito_user_id=cognito_user_id,
            portfolio_id=allocation_id,
            previous_transaction_ids=previous_transaction_ids,
            timeout_seconds=60.0,
        )

    transaction = test_engine._wait_for_transaction_execution(
        cognito_user_id=cognito_user_id,
        portfolio_id=allocation_id,
        transaction_id=transaction_id,
        timeout_seconds=60.0,
    )
    order_rows = test_engine._wait_for_transaction_orders(
        transaction_id=transaction_id,
        expected_order_count=int(transaction.number_orders or 0),
        timeout_seconds=60.0,
    )
    orders = [
        test_engine.alpaca_broker_client.get_order_by_id(
            alpaca_account_id=alpaca_account_id,
            cognito_user_id=cognito_user_id,
            order_id=str(row["order_id"]),
        )
        for row in order_rows
    ]
    return {"transaction_id": transaction_id, "orders": orders}


def _realize_filled_orders(
    test_engine: TestEngine,
    *,
    cognito_user_id: str,
    alpaca_account_id: str,
    allocation_id: str,
) -> None:
    deadline = monotonic() + 60.0
    while monotonic() < deadline:
        test_engine.trade_execution_service.realize_filled_orders(
            cognito_user_id=cognito_user_id,
            alpaca_account_id=alpaca_account_id,
            allocation_id=allocation_id,
        )
        rows = test_engine.order_repository.get_orders_by_allocation(
            cognito_user_id=cognito_user_id,
            allocation_id=allocation_id,
        )
        if rows and all(row["status"] == "FILLED" for row in rows):
            return
        sleep(0.25)
    raise TimeoutError(f"Orders for allocation '{allocation_id}' were not filled.")


def _record_order_response(
    transaction_id_order_id_dict: dict[str, list[Any]],
    response: dict[str, Any] | None,
) -> None:
    if response is not None:
        transaction_id_order_id_dict[response["transaction_id"]] = response["orders"]


def test_trade_execution_deposit_route_validates_request_with_real_dependencies(
    app_factory,
    client_for_app,
) -> None:
    app = app_factory(trade_execution_router)

    with client_for_app(app) as client:
        response = client.post(
            "/trade-execution/portfolios/portfolio-1/deposit",
            json={},
        )

    assert response.status_code == 422


@pytest.mark.integration
def test_trade_execution_portfolio_route_functions(
    route_trade_test_engine: TestEngine,
) -> None:
    test_engine = route_trade_test_engine
    portfolio_id: str | None = None
    transaction_id_order_id_dict: dict[str, list[Any]] = {}

    try:
        portfolio_id = _create_public_portfolio(test_engine)
        baskt_account, alpaca_account = _baskt_account_and_alpaca_account(test_engine)

        deposit_response = _wait_for_route_trade_execution(
            test_engine,
            expected_action="portfolio_deposit",
            cognito_user_id=test_engine.funded_50000_cognito_user_id,
            alpaca_account_id=test_engine.funded_50000_alpaca_account_id,
            allocation_id=portfolio_id,
            route_action=lambda: deposit_into_portfolio(
                portfolio_id=portfolio_id,
                request=DepositIntoPortfolioRequest(amount=100.0),
                queuing_service=test_engine.trade_execution_queuing_service,
                baskt_account=baskt_account,
                alpaca_account=alpaca_account,
                model_portfolio_repository=test_engine.model_portfolio_repository,
                model_portfolio_access_repository=None,
            ),
        )
        _record_order_response(transaction_id_order_id_dict, deposit_response)
        _realize_filled_orders(
            test_engine,
            cognito_user_id=test_engine.funded_50000_cognito_user_id,
            alpaca_account_id=test_engine.funded_50000_alpaca_account_id,
            allocation_id=portfolio_id,
        )

        withdraw_response = _wait_for_route_trade_execution(
            test_engine,
            expected_action="portfolio_withdraw",
            cognito_user_id=test_engine.funded_50000_cognito_user_id,
            alpaca_account_id=test_engine.funded_50000_alpaca_account_id,
            allocation_id=portfolio_id,
            route_action=lambda: withdraw_from_portfolio(
                portfolio_id=portfolio_id,
                request=WithdrawFromPortfolioRequest(amount=25.0),
                queuing_service=test_engine.trade_execution_queuing_service,
                baskt_account=baskt_account,
                alpaca_account=alpaca_account,
                model_portfolio_repository=test_engine.model_portfolio_repository,
                model_portfolio_access_repository=None,
            ),
        )
        _record_order_response(transaction_id_order_id_dict, withdraw_response)
        _realize_filled_orders(
            test_engine,
            cognito_user_id=test_engine.funded_50000_cognito_user_id,
            alpaca_account_id=test_engine.funded_50000_alpaca_account_id,
            allocation_id=portfolio_id,
        )

        withdraw_all_response = _wait_for_route_trade_execution(
            test_engine,
            expected_action="portfolio_withdraw_all",
            cognito_user_id=test_engine.funded_50000_cognito_user_id,
            alpaca_account_id=test_engine.funded_50000_alpaca_account_id,
            allocation_id=portfolio_id,
            route_action=lambda: sell_all_from_portfolio(
                portfolio_id=portfolio_id,
                queuing_service=test_engine.trade_execution_queuing_service,
                baskt_account=baskt_account,
                alpaca_account=alpaca_account,
                model_portfolio_repository=test_engine.model_portfolio_repository,
                model_portfolio_access_repository=None,
            ),
        )
        _record_order_response(transaction_id_order_id_dict, withdraw_all_response)
        _realize_filled_orders(
            test_engine,
            cognito_user_id=test_engine.funded_50000_cognito_user_id,
            alpaca_account_id=test_engine.funded_50000_alpaca_account_id,
            allocation_id=portfolio_id,
        )
    finally:
        if portfolio_id is not None:
            try:
                test_engine.test_clean_up(
                    traded_accounts=[
                        [
                            test_engine.funded_50000_cognito_user_id,
                            test_engine.funded_50000_alpaca_account_id,
                            portfolio_id,
                        ]
                    ],
                    portfolio_owner_model_portfolios=[],
                    transaction_id_order_id_dict=transaction_id_order_id_dict,
                )
            finally:
                _delete_portfolio(test_engine, portfolio_id)


@pytest.mark.integration
def test_trade_execution_stock_route_functions(
    route_trade_test_engine: TestEngine,
) -> None:
    test_engine = route_trade_test_engine
    asset_id = _stock_asset_id(test_engine, "AAPL")
    baskt_account, alpaca_account = _baskt_account_and_alpaca_account(test_engine)
    transaction_id_order_id_dict: dict[str, list[Any]] = {}

    try:
        buy_response = _wait_for_route_trade_execution(
            test_engine,
            expected_action="stock_buy",
            cognito_user_id=test_engine.funded_50000_cognito_user_id,
            alpaca_account_id=test_engine.funded_50000_alpaca_account_id,
            allocation_id=asset_id,
            route_action=lambda: buy_stock(
                asset_id=asset_id,
                request=BuyStockRequest(amount=100.0),
                queuing_service=test_engine.trade_execution_queuing_service,
                baskt_account=baskt_account,
                alpaca_account=alpaca_account,
            ),
        )
        _record_order_response(transaction_id_order_id_dict, buy_response)
        _realize_filled_orders(
            test_engine,
            cognito_user_id=test_engine.funded_50000_cognito_user_id,
            alpaca_account_id=test_engine.funded_50000_alpaca_account_id,
            allocation_id=asset_id,
        )

        sell_response = _wait_for_route_trade_execution(
            test_engine,
            expected_action="stock_sell",
            cognito_user_id=test_engine.funded_50000_cognito_user_id,
            alpaca_account_id=test_engine.funded_50000_alpaca_account_id,
            allocation_id=asset_id,
            route_action=lambda: sell_stock(
                asset_id=asset_id,
                request=SellStockRequest(amount=25.0),
                queuing_service=test_engine.trade_execution_queuing_service,
                baskt_account=baskt_account,
                alpaca_account=alpaca_account,
            ),
        )
        _record_order_response(transaction_id_order_id_dict, sell_response)
        _realize_filled_orders(
            test_engine,
            cognito_user_id=test_engine.funded_50000_cognito_user_id,
            alpaca_account_id=test_engine.funded_50000_alpaca_account_id,
            allocation_id=asset_id,
        )

        close_response = _wait_for_route_trade_execution(
            test_engine,
            expected_action="stock_close",
            cognito_user_id=test_engine.funded_50000_cognito_user_id,
            alpaca_account_id=test_engine.funded_50000_alpaca_account_id,
            allocation_id=asset_id,
            route_action=lambda: close_stock(
                asset_id=asset_id,
                queuing_service=test_engine.trade_execution_queuing_service,
                baskt_account=baskt_account,
                alpaca_account=alpaca_account,
            ),
        )
        _record_order_response(transaction_id_order_id_dict, close_response)
        _realize_filled_orders(
            test_engine,
            cognito_user_id=test_engine.funded_50000_cognito_user_id,
            alpaca_account_id=test_engine.funded_50000_alpaca_account_id,
            allocation_id=asset_id,
        )
    finally:
        test_engine.test_stock_clean_up(
            traded_accounts=[
                [
                    test_engine.funded_50000_cognito_user_id,
                    test_engine.funded_50000_alpaca_account_id,
                    asset_id,
                ]
            ],
            transaction_id_order_id_dict=transaction_id_order_id_dict,
        )
