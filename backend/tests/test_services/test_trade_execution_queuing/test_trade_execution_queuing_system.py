import uuid
from time import sleep

import pytest

from typing import List, Dict

from alpaca.trading.models import Order

from backend.tests.mock_alpaca.trading import MockSQSClient
from .conftest import (
    TestEngine, 
)


@pytest.fixture(autouse=True)
def pause_between_test_cases():
    yield
    sleep(5)


def _stock_asset_id(test_engine: TestEngine, symbol: str) -> str:
    """Use generated IDs for mocks and Alpaca's real asset ID for AWS tests."""
    if isinstance(test_engine.sqs_client, MockSQSClient):
        return str(uuid.uuid4())
    return test_engine.alpaca_broker_client.get_stock_by_symbol(
        symbol=symbol
    ).stock_id

def _create_portfolio(
    test_engine: TestEngine,
    portfolio_owner_cognito_user_id: str,
    *,
    portfolio_name_prefix: str,
    symbols: list[str],
    directions: list[int],
    target_weights: list[float],
    leverages: list[float],
) -> str:
    return test_engine.test_create_portfolio(
        symbols=symbols,
        directions=directions,
        target_weights=target_weights,
        leverages=leverages,
        portfolio_name=f"{portfolio_name_prefix}-{uuid.uuid4()}",
        portfolio_owner_cognito_user_id=portfolio_owner_cognito_user_id,
    )


def _deposit(
    test_engine: TestEngine, 
    alpaca_account_id: str,
    cognito_user_id: str,
    portfolio_owner_cognito_user_id: str,
    portfolio_id: str, 
    amount: float
) -> Dict:
    return test_engine.test_deposit(
        deposit_amount=amount,
        portfolio_id=portfolio_id,
        cognito_user_id=cognito_user_id,
        alpaca_account_id=alpaca_account_id,
        portfolio_owner_cognito_user_id=portfolio_owner_cognito_user_id
    )


def _update(
    test_engine: TestEngine,
    portfolio_owner_cognito_user_id: str,
    portfolio_id: str,
    *,
    symbols: list[str],
    directions: list[int],
    target_weights: list[float],
    leverages: list[float],
) -> Dict:
    updated_orders_dict = test_engine.test_update(
        portfolio_owner_cognito_user_id=portfolio_owner_cognito_user_id,
        portfolio_id=portfolio_id,
        new_symbols=symbols,
        new_directions=directions,
        new_target_weights=target_weights,
        new_leverages=leverages,
    )

    test_engine.test_update_effect(
        portfolio_owner_cognito_user_id=portfolio_owner_cognito_user_id,
        portfolio_id=portfolio_id,
        ud_orders_dict=updated_orders_dict,
    )

    return updated_orders_dict


def _withdraw(
    test_engine: TestEngine, 
    alpaca_account_id: str,
    cognito_user_id: str,
    portfolio_owner_cognito_user_id: str,
    portfolio_id: str, 
    amount: float
) -> Dict:
    return test_engine.test_withdraw(
        portfolio_owner_cognito_user_id=portfolio_owner_cognito_user_id,
        cognito_user_id=cognito_user_id,
        alpaca_account_id=alpaca_account_id,
        portfolio_id=portfolio_id,
        withdraw_amount=amount
    )


def _withdraw_all(
    test_engine: TestEngine, 
    alpaca_account_id: str,
    cognito_user_id: str,
    portfolio_owner_cognito_user_id: str,
    portfolio_id: str, 
) -> Dict:
    return test_engine.test_withdraw_all(
        portfolio_owner_cognito_user_id=portfolio_owner_cognito_user_id,
        cognito_user_id=cognito_user_id,
        alpaca_account_id=alpaca_account_id,
        portfolio_id=portfolio_id,
    )

def _buy(
    test_engine: TestEngine,
    alpaca_account_id: str,
    cognito_user_id: str,
    asset_id: str,
    symbol: str,
    amount: float,
) -> Dict:
    return test_engine.test_buy(
        symbol=symbol,
        asset_id=asset_id,
        deposit_amount=amount,
        cognito_user_id=cognito_user_id,
        alpaca_account_id=alpaca_account_id,
    )


def _sell(
    test_engine: TestEngine,
    alpaca_account_id: str,
    cognito_user_id: str,
    asset_id: str,
    symbol: str,
    amount: float,
    slippage_correction: int = 1,
) -> Dict:
    return test_engine.test_sell(
        cognito_user_id=cognito_user_id,
        alpaca_account_id=alpaca_account_id,
        symbol=symbol,
        asset_id=asset_id,
        withdraw_amount=amount,
        slippage_correction=slippage_correction,
    )


def _close(
    test_engine: TestEngine,
    alpaca_account_id: str,
    cognito_user_id: str,
    asset_id: str,
    symbol: str,
) -> Dict:
    return test_engine.test_close(
        symbol=symbol,
        asset_id=asset_id,
        alpaca_account_id=alpaca_account_id,
        cognito_user_id=cognito_user_id,
    )




def _cleanup(
        test_engine: TestEngine,
        traded_accounts: List[List[str]], # [[cognito_user_id, alpaca_account_id, portfolio_id],...,]
        portfolio_owner_model_portfolios: List[List[str]], # [[cognito_user_id, portfolio_id],...,]
        transaction_id_order_id_dict: Dict[str, List[Order]] # {transaction_id -> [order,...]}
    ) -> None:
    test_engine.test_clean_up(
        traded_accounts=traded_accounts,
        portfolio_owner_model_portfolios=portfolio_owner_model_portfolios,
        transaction_id_order_id_dict=transaction_id_order_id_dict
    )


def _record_order_response(
    transaction_id_order_id_dict: Dict[str, List[Order]],
    response: Dict | None,
) -> None:
    if response is not None:
        transaction_id_order_id_dict[response["transaction_id"]] = response["orders"]


def _record_update_order_response(
    transaction_id_order_id_dict: Dict[str, List[Order]],
    response: Dict | None,
) -> None:
    if response is not None:
        for follower_response in response.values():
            transaction_id_order_id_dict[follower_response["transaction_id"]] = follower_response["orders"]


def _cleanup_funded_test(
    test_engine: TestEngine,
    portfolio_id: str,
    transaction_id_order_id_dict: Dict[str, List[Order]],
) -> None:
    _cleanup(
        test_engine=test_engine,
        traded_accounts=[[test_engine.funded_50000_cognito_user_id, test_engine.funded_50000_alpaca_account_id, portfolio_id]],
        portfolio_owner_model_portfolios=[[test_engine.funded_50000_cognito_user_id, portfolio_id]],
        transaction_id_order_id_dict=transaction_id_order_id_dict,
    )


def _cleanup_cross_user_test(
    test_engine: TestEngine,
    portfolio_id: str,
    transaction_id_order_id_dict: Dict[str, List[Order]],
) -> None:
    _cleanup(
        test_engine=test_engine,
        traded_accounts=[[test_engine.funded_50000_cognito_user_id, test_engine.funded_50000_alpaca_account_id, portfolio_id]],
        portfolio_owner_model_portfolios=[[test_engine.portfolio_owner_cognito_user_id, portfolio_id]],
        transaction_id_order_id_dict=transaction_id_order_id_dict,
    )

def _cleanup_stock_test(
    test_engine: TestEngine,
    asset_id: str,
    transaction_id_order_id_dict: Dict[str, List[Order]],
    cognito_user_id: str | None = None,
    alpaca_account_id: str | None = None,
) -> None:
    test_engine.test_stock_clean_up(
        traded_accounts=[[
            cognito_user_id or test_engine.funded_50000_cognito_user_id,
            alpaca_account_id or test_engine.funded_50000_alpaca_account_id,
            asset_id,
        ]],
        transaction_id_order_id_dict=transaction_id_order_id_dict,
    )


def _cleanup_model_portfolio(
    test_engine: TestEngine,
    portfolio_owner_cognito_user_id: str,
    portfolio_id: str,
) -> None:
    _cleanup(
        test_engine=test_engine,
        traded_accounts=[],
        portfolio_owner_model_portfolios=[[portfolio_owner_cognito_user_id, portfolio_id]],
        transaction_id_order_id_dict={},
    )


@pytest.mark.integration
def test_stock_basic_buy(test_engine: TestEngine):
    """Test buying and recording a single stock position."""
    asset_id = _stock_asset_id(test_engine, "AAPL")
    buy_response = None

    try:
        buy_response = _buy(
            test_engine,
            test_engine.funded_50000_alpaca_account_id,
            test_engine.funded_50000_cognito_user_id,
            asset_id,
            "AAPL",
            100.00,
        )
    finally:
        transaction_id_order_id_dict = {}
        _record_order_response(transaction_id_order_id_dict, buy_response)
        _cleanup_stock_test(
            test_engine,
            asset_id,
            transaction_id_order_id_dict,
        )


@pytest.mark.integration
def test_stock_buy_and_partial_sell(test_engine: TestEngine):
    """Test partially selling a previously purchased stock."""
    asset_id = _stock_asset_id(test_engine, "AAPL")
    buy_response = None
    sell_response = None

    try:
        buy_response = _buy(
            test_engine,
            test_engine.funded_50000_alpaca_account_id,
            test_engine.funded_50000_cognito_user_id,
            asset_id,
            "AAPL",
            200.00,
        )
        sell_response = _sell(
            test_engine,
            test_engine.funded_50000_alpaca_account_id,
            test_engine.funded_50000_cognito_user_id,
            asset_id,
            "AAPL",
            50.00,
        )
    finally:
        transaction_id_order_id_dict = {}
        _record_order_response(transaction_id_order_id_dict, buy_response)
        _record_order_response(transaction_id_order_id_dict, sell_response)
        _cleanup_stock_test(
            test_engine,
            asset_id,
            transaction_id_order_id_dict,
        )


@pytest.mark.integration
def test_funded_1000_can_buy_and_sell_stock_but_not_short(test_engine: TestEngine):
    """Test a non-short-enabled account can sell long stock but cannot cross short."""
    asset_id = _stock_asset_id(test_engine, "AAPL")
    buy_response = None
    sell_response = None

    try:
        buy_response = _buy(
            test_engine,
            test_engine.funded_1000_alpaca_account_id,
            test_engine.funded_1000_cognito_user_id,
            asset_id,
            "AAPL",
            200.00,
        )
        sell_response = _sell(
            test_engine,
            test_engine.funded_1000_alpaca_account_id,
            test_engine.funded_1000_cognito_user_id,
            asset_id,
            "AAPL",
            50.00,
        )
        with pytest.raises(Exception) as exc_info:
            _sell(
                test_engine,
                test_engine.funded_1000_alpaca_account_id,
                test_engine.funded_1000_cognito_user_id,
                asset_id,
                "AAPL",
                500.00,
            )

        assert getattr(exc_info.value, "code", None) == "TRADE_EXECUTION_QUEUE_USER_NOT_SHORT_ENABLED"
    finally:
        transaction_id_order_id_dict = {}
        _record_order_response(transaction_id_order_id_dict, buy_response)
        _record_order_response(transaction_id_order_id_dict, sell_response)
        _cleanup_stock_test(
            test_engine,
            asset_id,
            transaction_id_order_id_dict,
            cognito_user_id=test_engine.funded_1000_cognito_user_id,
            alpaca_account_id=test_engine.funded_1000_alpaca_account_id,
        )


@pytest.mark.integration
def test_stock_buy_partial_sell_buy_and_close(test_engine: TestEngine):
    """Test buying, partially selling, buying again, and closing a stock."""
    asset_id = _stock_asset_id(test_engine, "AAPL")
    first_buy_response = None
    sell_response = None
    second_buy_response = None
    close_response = None

    try:
        first_buy_response = _buy(
            test_engine,
            test_engine.funded_50000_alpaca_account_id,
            test_engine.funded_50000_cognito_user_id,
            asset_id,
            "AAPL",
            200.00,
        )
        sell_response = _sell(
            test_engine,
            test_engine.funded_50000_alpaca_account_id,
            test_engine.funded_50000_cognito_user_id,
            asset_id,
            "AAPL",
            50.00,
        )
        second_buy_response = _buy(
            test_engine,
            test_engine.funded_50000_alpaca_account_id,
            test_engine.funded_50000_cognito_user_id,
            asset_id,
            "AAPL",
            100.00,
        )
        close_response = _close(
            test_engine,
            test_engine.funded_50000_alpaca_account_id,
            test_engine.funded_50000_cognito_user_id,
            asset_id,
            "AAPL",
        )
    finally:
        transaction_id_order_id_dict = {}
        _record_order_response(transaction_id_order_id_dict, first_buy_response)
        _record_order_response(transaction_id_order_id_dict, sell_response)
        _record_order_response(transaction_id_order_id_dict, second_buy_response)
        _record_order_response(transaction_id_order_id_dict, close_response)
        _cleanup_stock_test(
            test_engine,
            asset_id,
            transaction_id_order_id_dict,
        )


@pytest.mark.integration
def test_funded_1000_stock_short_errors(test_engine: TestEngine):
    """Test a non-short-enabled account cannot open a stock short."""
    asset_id = _stock_asset_id(test_engine, "AAPL")

    try:
        with pytest.raises(Exception) as exc_info:
            _sell(
                test_engine,
                test_engine.funded_1000_alpaca_account_id,
                test_engine.funded_1000_cognito_user_id,
                asset_id,
                "AAPL",
                30.00,
            )

        assert getattr(exc_info.value, "code", None) == "TRADE_EXECUTION_QUEUE_USER_NOT_SHORT_ENABLED"
    finally:
        _cleanup_stock_test(
            test_engine,
            asset_id,
            {},
            cognito_user_id=test_engine.funded_1000_cognito_user_id,
            alpaca_account_id=test_engine.funded_1000_alpaca_account_id,
        )


@pytest.mark.integration
def test_stock_short_under_minimum_errors(test_engine: TestEngine):
    """Test that opening a stock short below the minimum balance errors."""
    asset_id = _stock_asset_id(test_engine, "AAPL")

    try:
        with pytest.raises(Exception) as exc_info:
            _sell(
                test_engine,
                test_engine.funded_50000_alpaca_account_id,
                test_engine.funded_50000_cognito_user_id,
                asset_id,
                "AAPL",
                5.00,
            )

        assert getattr(exc_info.value, "code", None) == "TRADE_EXECUTION_QUEUE_AMOUNT_INVALID"
    finally:
        _cleanup_stock_test(
            test_engine,
            asset_id,
            {},
        )


@pytest.mark.integration
def test_stock_short_then_partial_cover(test_engine: TestEngine):
    """Test shorting a stock and partially covering while staying above the minimum."""
    asset_id = _stock_asset_id(test_engine, "AAPL")
    short_response = None
    cover_response = None

    try:
        short_response = _sell(
            test_engine,
            test_engine.funded_50000_alpaca_account_id,
            test_engine.funded_50000_cognito_user_id,
            asset_id,
            "AAPL",
            30.00,
        )
        cover_response = _buy(
            test_engine,
            test_engine.funded_50000_alpaca_account_id,
            test_engine.funded_50000_cognito_user_id,
            asset_id,
            "AAPL",
            10.00,
        )

        allocation = test_engine.allocation_repository.get_allocation(
            cognito_user_id=test_engine.funded_50000_cognito_user_id,
            allocation_id=asset_id,
        )
        latest_snapshot = allocation.position_history[-1]

        assert allocation.total_cost_basis > 10.00
        assert allocation.total_cost_basis < 30.00
        assert latest_snapshot.position is not None
        assert latest_snapshot.position.symbol == "AAPL"
        assert latest_snapshot.position.direction == -1
    finally:
        transaction_id_order_id_dict = {}
        _record_order_response(transaction_id_order_id_dict, short_response)
        _record_order_response(transaction_id_order_id_dict, cover_response)
        _cleanup_stock_test(
            test_engine,
            asset_id,
            transaction_id_order_id_dict,
        )


# @pytest.mark.integration
# def test_basic_deposit(test_engine: TestEngine):
#     portfolio_id = _create_portfolio(
#         test_engine,
#         test_engine.funded_50000_cognito_user_id,
#         portfolio_name_prefix="pytest-basic-deposit",
#         symbols=["AAPL"],
#         directions=[1],
#         target_weights=[1.00],
#         leverages=[1.0],
#     )

#     deposit_response = None
#     try:
#         deposit_response = _deposit(
#             test_engine=test_engine,
#             alpaca_account_id=test_engine.funded_50000_alpaca_account_id,
#             cognito_user_id=test_engine.funded_50000_cognito_user_id,
#             portfolio_owner_cognito_user_id=test_engine.funded_50000_cognito_user_id,
#             portfolio_id=portfolio_id,
#             amount=100.00,
#         )
#     finally:
#         transaction_id_order_id_dict = {}
#         _record_order_response(transaction_id_order_id_dict, deposit_response)
#         _cleanup_funded_test(test_engine, portfolio_id, transaction_id_order_id_dict)


# @pytest.mark.integration
# def test_multi_symbol_direction_switch(test_engine: TestEngine):
#     """Test multiple symbols switching directions simultaneously (long -> short)."""
#     portfolio_id = _create_portfolio(
#         test_engine,
#         test_engine.funded_50000_cognito_user_id,
#         portfolio_name_prefix="pytest-multi-dir-switch",
#         symbols=["AAPL", "GOOG", "MSFT"],
#         directions=[1, 1, 1],
#         target_weights=[0.33, 0.33, 0.34],
#         leverages=[1.0, 1.0, 1.0],
#     )

#     try:
#         deposit_response = None
#         update_response = None
#         withdraw_response = None
#         deposit_response = _deposit(test_engine, test_engine.funded_50000_alpaca_account_id, test_engine.funded_50000_cognito_user_id, test_engine.funded_50000_cognito_user_id, portfolio_id, 300.00)
#         update_response = _update(
#             test_engine,
#             test_engine.funded_50000_cognito_user_id,
#             portfolio_id,
#             symbols=["AAPL", "GOOG", "MSFT"],
#             directions=[-1, -1, -1],
#             target_weights=[0.33, 0.33, 0.34],
#             leverages=[1.0, 1.0, 1.0],
#         )
#         withdraw_response = _withdraw(test_engine, test_engine.funded_50000_alpaca_account_id, test_engine.funded_50000_cognito_user_id, test_engine.funded_50000_cognito_user_id, portfolio_id, 50.00)
#     finally:
#         transaction_id_order_id_dict = {}
#         _record_order_response(transaction_id_order_id_dict, deposit_response)
#         _record_order_response(transaction_id_order_id_dict, withdraw_response)
#         _record_update_order_response(transaction_id_order_id_dict, update_response)
#         _cleanup_funded_test(test_engine, portfolio_id, transaction_id_order_id_dict)


# @pytest.mark.integration
# def test_full_pos_rev_deposit_update_withdraw(test_engine: TestEngine):
#     portfolio_id = _create_portfolio(
#         test_engine,
#         test_engine.funded_50000_cognito_user_id,
#         portfolio_name_prefix="pytest-full-pos-rev",
#         symbols=["AAPL"],
#         directions=[1],
#         target_weights=[1.00],
#         leverages=[1.0],
#     )

#     deposit_response = None
#     update_response = None
#     withdraw_response = None
#     try:
#         deposit_response = _deposit(test_engine, test_engine.funded_50000_alpaca_account_id, test_engine.funded_50000_cognito_user_id, test_engine.funded_50000_cognito_user_id, portfolio_id, 150.00)
#         update_response = _update(
#             test_engine,
#             test_engine.funded_50000_cognito_user_id,
#             portfolio_id,
#             symbols=["AAPL"],
#             directions=[-1],
#             target_weights=[1.0],
#             leverages=[1.0],
#         )
#         withdraw_response = _withdraw(test_engine, test_engine.funded_50000_alpaca_account_id, test_engine.funded_50000_cognito_user_id, test_engine.funded_50000_cognito_user_id, portfolio_id, 20.00)
#     finally:
#         transaction_id_order_id_dict = {}
#         _record_order_response(transaction_id_order_id_dict, deposit_response)
#         _record_order_response(transaction_id_order_id_dict, withdraw_response)
#         _record_update_order_response(transaction_id_order_id_dict, update_response)
#         _cleanup_funded_test(test_engine, portfolio_id, transaction_id_order_id_dict)


# @pytest.mark.integration
# def test_add_new_symbols_keep_existing(test_engine: TestEngine):
#     """Test adding new symbols while keeping existing positions."""
#     portfolio_id = _create_portfolio(
#         test_engine,
#         test_engine.funded_50000_cognito_user_id,
#         portfolio_name_prefix="pytest-add-symbols",
#         symbols=["AAPL", "GOOG"],
#         directions=[1, 1],
#         target_weights=[0.50, 0.50],
#         leverages=[1.0, 1.0],
#     )

#     deposit_response = None
#     update_response = None
#     withdraw_response = None
#     try:
#         deposit_response = _deposit(test_engine, test_engine.funded_50000_alpaca_account_id, test_engine.funded_50000_cognito_user_id, test_engine.funded_50000_cognito_user_id, portfolio_id, 500.00)
#         update_response = _update(
#             test_engine,
#             test_engine.funded_50000_cognito_user_id,
#             portfolio_id,
#             symbols=["AAPL", "GOOG", "MSFT", "TSLA"],
#             directions=[1, 1, -1, 1],
#             target_weights=[0.25, 0.25, 0.25, 0.25],
#             leverages=[1.0, 1.0, 1.0, 1.0],
#         )
#         withdraw_response = _withdraw(test_engine, test_engine.funded_50000_alpaca_account_id, test_engine.funded_50000_cognito_user_id, test_engine.funded_50000_cognito_user_id, portfolio_id, 100.00)
#     finally:
#         transaction_id_order_id_dict = {}
#         _record_order_response(transaction_id_order_id_dict, deposit_response)
#         _record_order_response(transaction_id_order_id_dict, withdraw_response)
#         _record_update_order_response(transaction_id_order_id_dict, update_response)
#         _cleanup_funded_test(test_engine, portfolio_id, transaction_id_order_id_dict)


# @pytest.mark.integration
# def test_mixed_symbol_operations(test_engine: TestEngine):
#     """Test removing some symbols, keeping others, and adding new ones."""
#     portfolio_id = _create_portfolio(
#         test_engine,
#         test_engine.funded_50000_cognito_user_id,
#         portfolio_name_prefix="pytest-mixed-ops",
#         symbols=["AAPL", "GOOG", "MSFT", "TSLA"],
#         directions=[1, 1, 1, -1],
#         target_weights=[0.25, 0.25, 0.25, 0.25],
#         leverages=[1.0, 1.0, 1.0, 1.0],
#     )

#     deposit_response = None
#     update_response = None
#     withdraw_response = None
#     try:
#         deposit_response = _deposit(test_engine, test_engine.funded_50000_alpaca_account_id, test_engine.funded_50000_cognito_user_id, test_engine.funded_50000_cognito_user_id, portfolio_id, 600.00)
#         update_response = _update(
#             test_engine,
#             test_engine.funded_50000_cognito_user_id,
#             portfolio_id,
#             symbols=["AAPL", "MSFT", "UBER", "LLY"],
#             directions=[1, 1, -1, 1],
#             target_weights=[0.30, 0.30, 0.20, 0.20],
#             leverages=[1.0, 1.0, 1.0, 1.0],
#         )
#         withdraw_response = _withdraw(test_engine, test_engine.funded_50000_alpaca_account_id, test_engine.funded_50000_cognito_user_id, test_engine.funded_50000_cognito_user_id, portfolio_id, 150.00)
#     finally:
#         transaction_id_order_id_dict = {}
#         _record_order_response(transaction_id_order_id_dict, deposit_response)
#         _record_order_response(transaction_id_order_id_dict, withdraw_response)
#         _record_update_order_response(transaction_id_order_id_dict, update_response)
#         _cleanup_funded_test(test_engine, portfolio_id, transaction_id_order_id_dict)


# @pytest.mark.integration
# def test_rebalance_weights_only(test_engine: TestEngine):
#     """Test rebalancing weights only (same symbols, different allocations)."""
#     portfolio_id = _create_portfolio(
#         test_engine,
#         test_engine.funded_50000_cognito_user_id,
#         portfolio_name_prefix="pytest-rebalance-weights",
#         symbols=["AAPL", "GOOG", "MSFT"],
#         directions=[1, -1, 1],
#         target_weights=[0.33, 0.33, 0.34],
#         leverages=[1.0, 1.0, 1.0],
#     )

#     deposit_response = None
#     update_response = None
#     withdraw_response = None
#     try:
#         deposit_response = _deposit(test_engine, test_engine.funded_50000_alpaca_account_id, test_engine.funded_50000_cognito_user_id, test_engine.funded_50000_cognito_user_id, portfolio_id, 450.00)
#         update_response = _update(
#             test_engine,
#             test_engine.funded_50000_cognito_user_id,
#             portfolio_id,
#             symbols=["AAPL", "GOOG", "MSFT"],
#             directions=[1, -1, 1],
#             target_weights=[0.50, 0.20, 0.30],
#             leverages=[1.0, 1.0, 1.0],
#         )
#         withdraw_response = _withdraw(test_engine, test_engine.funded_50000_alpaca_account_id, test_engine.funded_50000_cognito_user_id, test_engine.funded_50000_cognito_user_id, portfolio_id, 100.00)
#     finally:
#         transaction_id_order_id_dict = {}
#         _record_order_response(transaction_id_order_id_dict, deposit_response)
#         _record_order_response(transaction_id_order_id_dict, withdraw_response)
#         _record_update_order_response(transaction_id_order_id_dict, update_response)
#         _cleanup_funded_test(test_engine, portfolio_id, transaction_id_order_id_dict)


# @pytest.mark.integration
# def test_change_everything_simultaneously(test_engine: TestEngine):
#     """Test changing symbols, weights, directions, and leverage simultaneously."""
#     portfolio_id = _create_portfolio(
#         test_engine,
#         test_engine.funded_50000_cognito_user_id,
#         portfolio_name_prefix="pytest-change-all",
#         symbols=["AAPL", "GOOG"],
#         directions=[1, -1],
#         target_weights=[0.60, 0.40],
#         leverages=[1.0, 1.0],
#     )

#     deposit_response = None
#     update_response = None
#     withdraw_response = None
#     try:
#         deposit_response = _deposit(test_engine, test_engine.funded_50000_alpaca_account_id, test_engine.funded_50000_cognito_user_id, test_engine.funded_50000_cognito_user_id, portfolio_id, 550.00)
#         update_response = _update(
#             test_engine,
#             test_engine.funded_50000_cognito_user_id,
#             portfolio_id,
#             symbols=["MSFT", "UBER", "LLY"],
#             directions=[-1, 1, -1],
#             target_weights=[0.40, 0.35, 0.25],
#             leverages=[1.0, 1.0, 1.0],
#         )
#         withdraw_response = _withdraw(test_engine, test_engine.funded_50000_alpaca_account_id, test_engine.funded_50000_cognito_user_id, test_engine.funded_50000_cognito_user_id, portfolio_id, 120.00)
#     finally:
#         transaction_id_order_id_dict = {}
#         _record_order_response(transaction_id_order_id_dict, deposit_response)
#         _record_order_response(transaction_id_order_id_dict, withdraw_response)
#         _record_update_order_response(transaction_id_order_id_dict, update_response)
#         _cleanup_funded_test(test_engine, portfolio_id, transaction_id_order_id_dict)


# @pytest.mark.integration
# def test_multiple_deposits_before_update(test_engine: TestEngine):
#     """Test multiple deposits to the same portfolio before any update."""
#     portfolio_id = _create_portfolio(
#         test_engine,
#         test_engine.funded_50000_cognito_user_id,
#         portfolio_name_prefix="pytest-multi-deposits",
#         symbols=["AAPL", "GOOG"],
#         directions=[1, -1],
#         target_weights=[0.60, 0.40],
#         leverages=[1.0, 1.0],
#     )

#     first_deposit_response = None
#     second_deposit_response = None
#     third_deposit_response = None
#     update_response = None
#     withdraw_response = None
#     try:
#         first_deposit_response = _deposit(test_engine, test_engine.funded_50000_alpaca_account_id, test_engine.funded_50000_cognito_user_id, test_engine.funded_50000_cognito_user_id, portfolio_id, 200.00)
#         second_deposit_response = _deposit(test_engine, test_engine.funded_50000_alpaca_account_id, test_engine.funded_50000_cognito_user_id, test_engine.funded_50000_cognito_user_id, portfolio_id, 150.00)
#         third_deposit_response = _deposit(test_engine, test_engine.funded_50000_alpaca_account_id, test_engine.funded_50000_cognito_user_id, test_engine.funded_50000_cognito_user_id, portfolio_id, 250.00)
#         update_response = _update(
#             test_engine,
#             test_engine.funded_50000_cognito_user_id,
#             portfolio_id,
#             symbols=["AAPL", "GOOG", "MSFT"],
#             directions=[1, -1, 1],
#             target_weights=[0.40, 0.30, 0.30],
#             leverages=[1.0, 1.0, 1.0],
#         )
#         withdraw_response = _withdraw(test_engine, test_engine.funded_50000_alpaca_account_id, test_engine.funded_50000_cognito_user_id, test_engine.funded_50000_cognito_user_id, portfolio_id, 100.00)
#     finally:
#         transaction_id_order_id_dict = {}
#         _record_order_response(transaction_id_order_id_dict, first_deposit_response)
#         _record_order_response(transaction_id_order_id_dict, second_deposit_response)
#         _record_order_response(transaction_id_order_id_dict, third_deposit_response)
#         _record_order_response(transaction_id_order_id_dict, withdraw_response)
#         _record_update_order_response(transaction_id_order_id_dict, update_response)
#         _cleanup_funded_test(test_engine, portfolio_id, transaction_id_order_id_dict)


# @pytest.mark.integration
# def test_deposit_after_partial_withdrawal(test_engine: TestEngine):
#     """Test deposit after partial withdrawal."""
#     portfolio_id = _create_portfolio(
#         test_engine,
#         test_engine.funded_50000_cognito_user_id,
#         portfolio_name_prefix="pytest-deposit-after-wd",
#         symbols=["AAPL", "MSFT", "GOOG"],
#         directions=[1, 1, -1],
#         target_weights=[0.40, 0.40, 0.20],
#         leverages=[1.0, 1.0, 1.0],
#     )

#     first_deposit_response = None
#     first_update_response = None
#     first_withdraw_response = None
#     second_deposit_response = None
#     second_update_response = None
#     second_withdraw_response = None
#     first_withdraw_all_response = None
#     try:
#         first_deposit_response = _deposit(test_engine, test_engine.funded_50000_alpaca_account_id, test_engine.funded_50000_cognito_user_id, test_engine.funded_50000_cognito_user_id, portfolio_id, 500.00)
#         first_update_response = _update(
#             test_engine,
#             test_engine.funded_50000_cognito_user_id,
#             portfolio_id,
#             symbols=["AAPL", "MSFT", "GOOG", "TSLA"],
#             directions=[1, 1, -1, 1],
#             target_weights=[0.30, 0.30, 0.20, 0.20],
#             leverages=[1.0, 1.0, 1.0, 1.0],
#         )
#         first_withdraw_response = _withdraw(test_engine, test_engine.funded_50000_alpaca_account_id, test_engine.funded_50000_cognito_user_id, test_engine.funded_50000_cognito_user_id, portfolio_id, 150.00)
#         second_deposit_response = _deposit(test_engine, test_engine.funded_50000_alpaca_account_id, test_engine.funded_50000_cognito_user_id, test_engine.funded_50000_cognito_user_id, portfolio_id, 300.00)
#         second_update_response = _update(
#             test_engine,
#             test_engine.funded_50000_cognito_user_id,
#             portfolio_id,
#             symbols=["AAPL", "MSFT", "LLY"],
#             directions=[-1, 1, 1],
#             target_weights=[0.50, 0.25, 0.25],
#             leverages=[1.0, 1.0, 1.0],
#         )
#         second_withdraw_response = _withdraw(test_engine, test_engine.funded_50000_alpaca_account_id, test_engine.funded_50000_cognito_user_id, test_engine.funded_50000_cognito_user_id, portfolio_id, 200.00)
#         first_withdraw_all_response = _withdraw_all(test_engine, test_engine.funded_50000_alpaca_account_id, test_engine.funded_50000_cognito_user_id, test_engine.funded_50000_cognito_user_id, portfolio_id,)
#     finally:
#         transaction_id_order_id_dict = {}
#         _record_order_response(transaction_id_order_id_dict, first_deposit_response)
#         _record_order_response(transaction_id_order_id_dict, first_withdraw_response)
#         _record_order_response(transaction_id_order_id_dict, second_deposit_response)
#         _record_order_response(transaction_id_order_id_dict, second_withdraw_response)
#         _record_order_response(transaction_id_order_id_dict, first_withdraw_all_response)
#         _record_update_order_response(transaction_id_order_id_dict, first_update_response)
#         _record_update_order_response(transaction_id_order_id_dict, second_update_response)
#         _cleanup_funded_test(test_engine, portfolio_id, transaction_id_order_id_dict)


# @pytest.mark.integration
# def test_deposit_partial_withdraw_deposit_withdraw_all(test_engine: TestEngine):
#     """Test the complete same-owner deposit and withdrawal sequence."""
#     portfolio_id = _create_portfolio(
#         test_engine,
#         test_engine.funded_50000_cognito_user_id,
#         portfolio_name_prefix="pytest-deposit-withdraw-sequence",
#         symbols=["AAPL", "MSFT"],
#         directions=[1, 1],
#         target_weights=[0.50, 0.50],
#         leverages=[1.0, 1.0],
#     )

#     first_deposit_response = None
#     partial_withdraw_response = None
#     second_deposit_response = None
#     withdraw_all_response = None
#     try:
#         first_deposit_response = _deposit(
#             test_engine,
#             test_engine.funded_50000_alpaca_account_id,
#             test_engine.funded_50000_cognito_user_id,
#             test_engine.funded_50000_cognito_user_id,
#             portfolio_id,
#             500.00,
#         )
#         partial_withdraw_response = _withdraw(
#             test_engine,
#             test_engine.funded_50000_alpaca_account_id,
#             test_engine.funded_50000_cognito_user_id,
#             test_engine.funded_50000_cognito_user_id,
#             portfolio_id,
#             150.00,
#         )
#         second_deposit_response = _deposit(
#             test_engine,
#             test_engine.funded_50000_alpaca_account_id,
#             test_engine.funded_50000_cognito_user_id,
#             test_engine.funded_50000_cognito_user_id,
#             portfolio_id,
#             200.00,
#         )
#         withdraw_all_response = _withdraw_all(
#             test_engine,
#             test_engine.funded_50000_alpaca_account_id,
#             test_engine.funded_50000_cognito_user_id,
#             test_engine.funded_50000_cognito_user_id,
#             portfolio_id,
#         )
#     finally:
#         transaction_id_order_id_dict = {}
#         _record_order_response(transaction_id_order_id_dict, first_deposit_response)
#         _record_order_response(transaction_id_order_id_dict, partial_withdraw_response)
#         _record_order_response(transaction_id_order_id_dict, second_deposit_response)
#         _record_order_response(transaction_id_order_id_dict, withdraw_all_response)
#         _cleanup_funded_test(test_engine, portfolio_id, transaction_id_order_id_dict)


@pytest.mark.integration
def test_cross_user_basic_deposit(test_engine: TestEngine):
    portfolio_id = _create_portfolio(
        test_engine,
        test_engine.portfolio_owner_cognito_user_id,
        portfolio_name_prefix="pytest-basic-deposit",
        symbols=["AAPL"],
        directions=[1],
        target_weights=[1.00],
        leverages=[1.0],
    )

    deposit_response = None
    try:
        deposit_response = _deposit(
            test_engine=test_engine,
            alpaca_account_id=test_engine.funded_50000_alpaca_account_id,
            cognito_user_id=test_engine.funded_50000_cognito_user_id,
            portfolio_owner_cognito_user_id=test_engine.portfolio_owner_cognito_user_id,
            portfolio_id=portfolio_id,
            amount=100.00,
        )
    finally:
        transaction_id_order_id_dict = {}
        _record_order_response(transaction_id_order_id_dict, deposit_response)
        _cleanup_cross_user_test(test_engine, portfolio_id, transaction_id_order_id_dict)


@pytest.mark.integration
def test_funded_1000_model_portfolio_deposit_errors(test_engine: TestEngine):
    """Test a non-short-enabled account cannot deposit into a model portfolio."""
    portfolio_id = _create_portfolio(
        test_engine,
        test_engine.portfolio_owner_cognito_user_id,
        portfolio_name_prefix="pytest-short-disabled-deposit",
        symbols=["AAPL"],
        directions=[1],
        target_weights=[1.00],
        leverages=[1.0],
    )

    try:
        with pytest.raises(Exception) as exc_info:
            _deposit(
                test_engine=test_engine,
                alpaca_account_id=test_engine.funded_1000_alpaca_account_id,
                cognito_user_id=test_engine.funded_1000_cognito_user_id,
                portfolio_owner_cognito_user_id=test_engine.portfolio_owner_cognito_user_id,
                portfolio_id=portfolio_id,
                amount=100.00,
            )

        assert getattr(exc_info.value, "code", None) == "TRADE_EXECUTION_QUEUE_USER_NOT_SHORT_ENABLED"
    finally:
        _cleanup_model_portfolio(
            test_engine,
            test_engine.portfolio_owner_cognito_user_id,
            portfolio_id,
        )


@pytest.mark.integration
def test_cross_user_multi_symbol_direction_switch(test_engine: TestEngine):
    """Test multiple symbols switching directions simultaneously (long -> short)."""
    portfolio_id = _create_portfolio(
        test_engine,
        test_engine.portfolio_owner_cognito_user_id,
        portfolio_name_prefix="pytest-multi-dir-switch",
        symbols=["AAPL", "GOOG", "MSFT"],
        directions=[1, 1, 1],
        target_weights=[0.33, 0.33, 0.34],
        leverages=[1.0, 1.0, 1.0],
    )

    try:
        deposit_response = None
        update_response = None
        withdraw_response = None
        deposit_response = _deposit(test_engine, test_engine.funded_50000_alpaca_account_id, test_engine.funded_50000_cognito_user_id, test_engine.portfolio_owner_cognito_user_id, portfolio_id, 300.00)
        update_response = _update(
            test_engine,
            test_engine.portfolio_owner_cognito_user_id,
            portfolio_id,
            symbols=["AAPL", "GOOG", "MSFT"],
            directions=[-1, -1, -1],
            target_weights=[0.33, 0.33, 0.34],
            leverages=[1.0, 1.0, 1.0],
        )
        withdraw_response = _withdraw(test_engine, test_engine.funded_50000_alpaca_account_id, test_engine.funded_50000_cognito_user_id, test_engine.portfolio_owner_cognito_user_id, portfolio_id, 50.00)
    finally:
        transaction_id_order_id_dict = {}
        _record_order_response(transaction_id_order_id_dict, deposit_response)
        _record_order_response(transaction_id_order_id_dict, withdraw_response)
        _record_update_order_response(transaction_id_order_id_dict, update_response)
        _cleanup_cross_user_test(test_engine, portfolio_id, transaction_id_order_id_dict)


@pytest.mark.integration
def test_cross_user_full_pos_rev_deposit_update_withdraw(test_engine: TestEngine):
    portfolio_id = _create_portfolio(
        test_engine,
        test_engine.portfolio_owner_cognito_user_id,
        portfolio_name_prefix="pytest-full-pos-rev",
        symbols=["AAPL"],
        directions=[1],
        target_weights=[1.00],
        leverages=[1.0],
    )

    deposit_response = None
    update_response = None
    withdraw_response = None
    try:
        deposit_response = _deposit(test_engine, test_engine.funded_50000_alpaca_account_id, test_engine.funded_50000_cognito_user_id, test_engine.portfolio_owner_cognito_user_id, portfolio_id, 150.00)
        update_response = _update(
            test_engine,
            test_engine.portfolio_owner_cognito_user_id,
            portfolio_id,
            symbols=["AAPL"],
            directions=[-1],
            target_weights=[1.0],
            leverages=[1.0],
        )
        withdraw_response = _withdraw(test_engine, test_engine.funded_50000_alpaca_account_id, test_engine.funded_50000_cognito_user_id, test_engine.portfolio_owner_cognito_user_id, portfolio_id, 20.00)
    finally:
        transaction_id_order_id_dict = {}
        _record_order_response(transaction_id_order_id_dict, deposit_response)
        _record_order_response(transaction_id_order_id_dict, withdraw_response)
        _record_update_order_response(transaction_id_order_id_dict, update_response)
        _cleanup_cross_user_test(test_engine, portfolio_id, transaction_id_order_id_dict)


@pytest.mark.integration
def test_cross_user_add_new_symbols_keep_existing(test_engine: TestEngine):
    """Test adding new symbols while keeping existing positions."""
    portfolio_id = _create_portfolio(
        test_engine,
        test_engine.portfolio_owner_cognito_user_id,
        portfolio_name_prefix="pytest-add-symbols",
        symbols=["AAPL", "GOOG"],
        directions=[1, 1],
        target_weights=[0.50, 0.50],
        leverages=[1.0, 1.0],
    )

    deposit_response = None
    update_response = None
    withdraw_response = None
    try:
        deposit_response = _deposit(test_engine, test_engine.funded_50000_alpaca_account_id, test_engine.funded_50000_cognito_user_id, test_engine.portfolio_owner_cognito_user_id, portfolio_id, 500.00)
        update_response = _update(
            test_engine,
            test_engine.portfolio_owner_cognito_user_id,
            portfolio_id,
            symbols=["AAPL", "GOOG", "MSFT", "TSLA"],
            directions=[1, 1, -1, 1],
            target_weights=[0.25, 0.25, 0.25, 0.25],
            leverages=[1.0, 1.0, 1.0, 1.0],
        )
        withdraw_response = _withdraw(test_engine, test_engine.funded_50000_alpaca_account_id, test_engine.funded_50000_cognito_user_id, test_engine.portfolio_owner_cognito_user_id, portfolio_id, 100.00)
    finally:
        transaction_id_order_id_dict = {}
        _record_order_response(transaction_id_order_id_dict, deposit_response)
        _record_order_response(transaction_id_order_id_dict, withdraw_response)
        _record_update_order_response(transaction_id_order_id_dict, update_response)
        _cleanup_cross_user_test(test_engine, portfolio_id, transaction_id_order_id_dict)


@pytest.mark.integration
def test_cross_user_mixed_symbol_operations(test_engine: TestEngine):
    """Test removing some symbols, keeping others, and adding new ones."""
    portfolio_id = _create_portfolio(
        test_engine,
        test_engine.portfolio_owner_cognito_user_id,
        portfolio_name_prefix="pytest-mixed-ops",
        symbols=["AAPL", "GOOG", "MSFT", "TSLA"],
        directions=[1, 1, 1, -1],
        target_weights=[0.25, 0.25, 0.25, 0.25],
        leverages=[1.0, 1.0, 1.0, 1.0],
    )

    deposit_response = None
    update_response = None
    withdraw_response = None
    try:
        deposit_response = _deposit(test_engine, test_engine.funded_50000_alpaca_account_id, test_engine.funded_50000_cognito_user_id, test_engine.portfolio_owner_cognito_user_id, portfolio_id, 600.00)
        update_response = _update(
            test_engine,
            test_engine.portfolio_owner_cognito_user_id,
            portfolio_id,
            symbols=["AAPL", "MSFT", "UBER", "LLY"],
            directions=[1, 1, -1, 1],
            target_weights=[0.30, 0.30, 0.20, 0.20],
            leverages=[1.0, 1.0, 1.0, 1.0],
        )
        withdraw_response = _withdraw(test_engine, test_engine.funded_50000_alpaca_account_id, test_engine.funded_50000_cognito_user_id, test_engine.portfolio_owner_cognito_user_id, portfolio_id, 150.00)
    finally:
        transaction_id_order_id_dict = {}
        _record_order_response(transaction_id_order_id_dict, deposit_response)
        _record_order_response(transaction_id_order_id_dict, withdraw_response)
        _record_update_order_response(transaction_id_order_id_dict, update_response)
        _cleanup_cross_user_test(test_engine, portfolio_id, transaction_id_order_id_dict)


@pytest.mark.integration
def test_cross_user_rebalance_weights_only(test_engine: TestEngine):
    """Test rebalancing weights only (same symbols, different allocations)."""
    portfolio_id = _create_portfolio(
        test_engine,
        test_engine.portfolio_owner_cognito_user_id,
        portfolio_name_prefix="pytest-rebalance-weights",
        symbols=["AAPL", "GOOG", "MSFT"],
        directions=[1, -1, 1],
        target_weights=[0.33, 0.33, 0.34],
        leverages=[1.0, 1.0, 1.0],
    )

    deposit_response = None
    update_response = None
    withdraw_response = None
    try:
        deposit_response = _deposit(test_engine, test_engine.funded_50000_alpaca_account_id, test_engine.funded_50000_cognito_user_id, test_engine.portfolio_owner_cognito_user_id, portfolio_id, 450.00)
        update_response = _update(
            test_engine,
            test_engine.portfolio_owner_cognito_user_id,
            portfolio_id,
            symbols=["AAPL", "GOOG", "MSFT"],
            directions=[1, -1, 1],
            target_weights=[0.50, 0.20, 0.30],
            leverages=[1.0, 1.0, 1.0],
        )
        withdraw_response = _withdraw(test_engine, test_engine.funded_50000_alpaca_account_id, test_engine.funded_50000_cognito_user_id, test_engine.portfolio_owner_cognito_user_id, portfolio_id, 100.00)
    finally:
        transaction_id_order_id_dict = {}
        _record_order_response(transaction_id_order_id_dict, deposit_response)
        _record_order_response(transaction_id_order_id_dict, withdraw_response)
        _record_update_order_response(transaction_id_order_id_dict, update_response)
        _cleanup_cross_user_test(test_engine, portfolio_id, transaction_id_order_id_dict)


@pytest.mark.integration
def test_cross_user_change_everything_simultaneously(test_engine: TestEngine):
    """Test changing symbols, weights, directions, and leverage simultaneously."""
    portfolio_id = _create_portfolio(
        test_engine,
        test_engine.portfolio_owner_cognito_user_id,
        portfolio_name_prefix="pytest-change-all",
        symbols=["AAPL", "GOOG"],
        directions=[1, -1],
        target_weights=[0.60, 0.40],
        leverages=[1.0, 1.0],
    )

    deposit_response = None
    update_response = None
    withdraw_response = None
    try:
        deposit_response = _deposit(test_engine, test_engine.funded_50000_alpaca_account_id, test_engine.funded_50000_cognito_user_id, test_engine.portfolio_owner_cognito_user_id, portfolio_id, 550.00)
        update_response = _update(
            test_engine,
            test_engine.portfolio_owner_cognito_user_id,
            portfolio_id,
            symbols=["MSFT", "UBER", "LLY"],
            directions=[-1, 1, -1],
            target_weights=[0.40, 0.35, 0.25],
            leverages=[1.0, 1.0, 1.0],
        )
        withdraw_response = _withdraw(test_engine, test_engine.funded_50000_alpaca_account_id, test_engine.funded_50000_cognito_user_id, test_engine.portfolio_owner_cognito_user_id, portfolio_id, 120.00)
    finally:
        transaction_id_order_id_dict = {}
        _record_order_response(transaction_id_order_id_dict, deposit_response)
        _record_order_response(transaction_id_order_id_dict, withdraw_response)
        _record_update_order_response(transaction_id_order_id_dict, update_response)
        _cleanup_cross_user_test(test_engine, portfolio_id, transaction_id_order_id_dict)


@pytest.mark.integration
def test_cross_user_multiple_deposits_before_update(test_engine: TestEngine):
    """Test multiple deposits to the same portfolio before any update."""
    portfolio_id = _create_portfolio(
        test_engine,
        test_engine.portfolio_owner_cognito_user_id,
        portfolio_name_prefix="pytest-multi-deposits",
        symbols=["AAPL", "GOOG"],
        directions=[1, -1],
        target_weights=[0.60, 0.40],
        leverages=[1.0, 1.0],
    )

    first_deposit_response = None
    second_deposit_response = None
    third_deposit_response = None
    update_response = None
    withdraw_response = None
    try:
        first_deposit_response = _deposit(test_engine, test_engine.funded_50000_alpaca_account_id, test_engine.funded_50000_cognito_user_id, test_engine.portfolio_owner_cognito_user_id, portfolio_id, 200.00)
        second_deposit_response = _deposit(test_engine, test_engine.funded_50000_alpaca_account_id, test_engine.funded_50000_cognito_user_id, test_engine.portfolio_owner_cognito_user_id, portfolio_id, 150.00)
        third_deposit_response = _deposit(test_engine, test_engine.funded_50000_alpaca_account_id, test_engine.funded_50000_cognito_user_id, test_engine.portfolio_owner_cognito_user_id, portfolio_id, 250.00)
        update_response = _update(
            test_engine,
            test_engine.portfolio_owner_cognito_user_id,
            portfolio_id,
            symbols=["AAPL", "GOOG", "MSFT"],
            directions=[1, -1, 1],
            target_weights=[0.40, 0.30, 0.30],
            leverages=[1.0, 1.0, 1.0],
        )
        withdraw_response = _withdraw(test_engine, test_engine.funded_50000_alpaca_account_id, test_engine.funded_50000_cognito_user_id, test_engine.portfolio_owner_cognito_user_id, portfolio_id, 100.00)
    finally:
        transaction_id_order_id_dict = {}
        _record_order_response(transaction_id_order_id_dict, first_deposit_response)
        _record_order_response(transaction_id_order_id_dict, second_deposit_response)
        _record_order_response(transaction_id_order_id_dict, third_deposit_response)
        _record_order_response(transaction_id_order_id_dict, withdraw_response)
        _record_update_order_response(transaction_id_order_id_dict, update_response)
        _cleanup_cross_user_test(test_engine, portfolio_id, transaction_id_order_id_dict)


@pytest.mark.integration
def test_cross_user_deposit_after_partial_withdrawal(test_engine: TestEngine):
    """Test deposit after partial withdrawal."""
    portfolio_id = _create_portfolio(
        test_engine,
        test_engine.portfolio_owner_cognito_user_id,
        portfolio_name_prefix="pytest-deposit-after-wd",
        symbols=["AAPL", "MSFT", "GOOG"],
        directions=[1, 1, -1],
        target_weights=[0.40, 0.40, 0.20],
        leverages=[1.0, 1.0, 1.0],
    )

    first_deposit_response = None
    first_update_response = None
    first_withdraw_response = None
    second_deposit_response = None
    second_update_response = None
    second_withdraw_response = None
    first_withdraw_all_response = None
    try:
        first_deposit_response = _deposit(test_engine, test_engine.funded_50000_alpaca_account_id, test_engine.funded_50000_cognito_user_id, test_engine.portfolio_owner_cognito_user_id, portfolio_id, 500.00)
        first_update_response = _update(
            test_engine,
            test_engine.portfolio_owner_cognito_user_id,
            portfolio_id,
            symbols=["AAPL", "MSFT", "GOOG", "TSLA"],
            directions=[1, 1, -1, 1],
            target_weights=[0.30, 0.30, 0.20, 0.20],
            leverages=[1.0, 1.0, 1.0, 1.0],
        )
        first_withdraw_response = _withdraw(test_engine, test_engine.funded_50000_alpaca_account_id, test_engine.funded_50000_cognito_user_id, test_engine.portfolio_owner_cognito_user_id, portfolio_id, 150.00)
        second_deposit_response = _deposit(test_engine, test_engine.funded_50000_alpaca_account_id, test_engine.funded_50000_cognito_user_id, test_engine.portfolio_owner_cognito_user_id, portfolio_id, 300.00)
        second_update_response = _update(
            test_engine,
            test_engine.portfolio_owner_cognito_user_id,
            portfolio_id,
            symbols=["AAPL", "MSFT", "LLY"],
            directions=[-1, 1, 1],
            target_weights=[0.50, 0.25, 0.25],
            leverages=[1.0, 1.0, 1.0],
        )
        second_withdraw_response = _withdraw(test_engine, test_engine.funded_50000_alpaca_account_id, test_engine.funded_50000_cognito_user_id, test_engine.portfolio_owner_cognito_user_id, portfolio_id, 200.00)
        first_withdraw_all_response = _withdraw_all(test_engine, test_engine.funded_50000_alpaca_account_id, test_engine.funded_50000_cognito_user_id, test_engine.portfolio_owner_cognito_user_id, portfolio_id,)
    finally:
        transaction_id_order_id_dict = {}
        _record_order_response(transaction_id_order_id_dict, first_deposit_response)
        _record_order_response(transaction_id_order_id_dict, first_withdraw_response)
        _record_order_response(transaction_id_order_id_dict, second_deposit_response)
        _record_order_response(transaction_id_order_id_dict, second_withdraw_response)
        _record_order_response(transaction_id_order_id_dict, first_withdraw_all_response)
        _record_update_order_response(transaction_id_order_id_dict, first_update_response)
        _record_update_order_response(transaction_id_order_id_dict, second_update_response)
        _cleanup_cross_user_test(test_engine, portfolio_id, transaction_id_order_id_dict)


@pytest.mark.integration
def test_cross_user_deposit_partial_withdraw_deposit_withdraw_all(
    test_engine: TestEngine,
):
    """Test the complete deposit and withdrawal sequence across two users."""
    portfolio_id = _create_portfolio(
        test_engine,
        test_engine.portfolio_owner_cognito_user_id,
        portfolio_name_prefix="pytest-cross-deposit-withdraw-sequence",
        symbols=["AAPL", "MSFT"],
        directions=[1, 1],
        target_weights=[0.50, 0.50],
        leverages=[1.0, 1.0],
    )

    first_deposit_response = None
    partial_withdraw_response = None
    second_deposit_response = None
    withdraw_all_response = None
    try:
        first_deposit_response = _deposit(
            test_engine,
            test_engine.funded_50000_alpaca_account_id,
            test_engine.funded_50000_cognito_user_id,
            test_engine.portfolio_owner_cognito_user_id,
            portfolio_id,
            500.00,
        )
        partial_withdraw_response = _withdraw(
            test_engine,
            test_engine.funded_50000_alpaca_account_id,
            test_engine.funded_50000_cognito_user_id,
            test_engine.portfolio_owner_cognito_user_id,
            portfolio_id,
            150.00,
        )
        second_deposit_response = _deposit(
            test_engine,
            test_engine.funded_50000_alpaca_account_id,
            test_engine.funded_50000_cognito_user_id,
            test_engine.portfolio_owner_cognito_user_id,
            portfolio_id,
            200.00,
        )
        withdraw_all_response = _withdraw_all(
            test_engine,
            test_engine.funded_50000_alpaca_account_id,
            test_engine.funded_50000_cognito_user_id,
            test_engine.portfolio_owner_cognito_user_id,
            portfolio_id,
        )
    finally:
        transaction_id_order_id_dict = {}
        _record_order_response(transaction_id_order_id_dict, first_deposit_response)
        _record_order_response(transaction_id_order_id_dict, partial_withdraw_response)
        _record_order_response(transaction_id_order_id_dict, second_deposit_response)
        _record_order_response(transaction_id_order_id_dict, withdraw_all_response)
        _cleanup_cross_user_test(test_engine, portfolio_id, transaction_id_order_id_dict)
