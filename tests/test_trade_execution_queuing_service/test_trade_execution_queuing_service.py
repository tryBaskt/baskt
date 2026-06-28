import uuid

import pytest

from conftest import (
    FUNDED_ALPACA_ACCOUNT_ID,
    FUNDED_COGNITO_USER_ID,
    MockSQSClient,
    TestEngine,
)


@pytest.mark.integration
def test_queue_stock_buy_executes_and_cleans_up(test_engine: TestEngine):
    """Queue an AAPL buy, execute it through mock Lambda, and remove test data."""
    if not isinstance(test_engine.sqs_client, MockSQSClient):
        pytest.skip("Run with --mock_alpaca to use mock SQS and mock Lambda.")

    asset_id = str(uuid.uuid4())
    transaction_orders = {}

    try:
        test_engine.test_queue_stock_buy(
            symbol="AAPL",
            asset_id=asset_id,
            amount=10.0,
            cognito_user_id=FUNDED_COGNITO_USER_ID,
            alpaca_account_id=FUNDED_ALPACA_ACCOUNT_ID,
        )

        processed_message = test_engine.sqs_client.processed_messages[-1]
        transaction_id = processed_message["message"]["payload"]["transaction_id"]
        order_rows = test_engine.order_repository.get_orders_by_transaction(
            transaction_id=transaction_id
        )
        orders = [
            test_engine.alpaca_broker_client.get_order_by_id(
                alpaca_account_id=FUNDED_ALPACA_ACCOUNT_ID,
                cognito_user_id=FUNDED_COGNITO_USER_ID,
                order_id=row["order_id"],
            )
            for row in order_rows
        ]

        assert orders
        assert all(order.symbol == "AAPL" for order in orders)
        transaction_orders[transaction_id] = orders
    finally:
        test_engine.test_stock_clean_up(
            traded_accounts=[
                [
                    FUNDED_COGNITO_USER_ID,
                    FUNDED_ALPACA_ACCOUNT_ID,
                    asset_id,
                ]
            ],
            transaction_id_order_id_dict=transaction_orders,
        )
