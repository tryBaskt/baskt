import uuid

import pytest

from typing import List, Dict

from alpaca.trading.models import Order

from conftest import TestEngine

FUNDED_ALPACA_ACCOUNT_ID = "0bc4fb65-515c-41f7-a2ea-392ba5626c1e"
FUNDED_COGNITO_USER_ID = "f408a4e8-60f1-70d0-4c17-2377bf12babf"

PORTFOLIO_OWNER_ALPACA_ACCOUNT_ID = "004989ae-a5eb-4ea1-b525-3eab8bf5a5aa"
PORTFOLIO_OWNER_COGNITO_USER_ID = "c46894f8-e091-7088-e0fd-35d1d15bffb7"

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
        traded_accounts=[[FUNDED_COGNITO_USER_ID, FUNDED_ALPACA_ACCOUNT_ID, portfolio_id]],
        portfolio_owner_model_portfolios=[[FUNDED_COGNITO_USER_ID, portfolio_id]],
        transaction_id_order_id_dict=transaction_id_order_id_dict,
    )


def _cleanup_cross_user_test(
    test_engine: TestEngine,
    portfolio_id: str,
    transaction_id_order_id_dict: Dict[str, List[Order]],
) -> None:
    _cleanup(
        test_engine=test_engine,
        traded_accounts=[[FUNDED_COGNITO_USER_ID, FUNDED_ALPACA_ACCOUNT_ID, portfolio_id]],
        portfolio_owner_model_portfolios=[[PORTFOLIO_OWNER_COGNITO_USER_ID, portfolio_id]],
        transaction_id_order_id_dict=transaction_id_order_id_dict,
    )

def _cleanup_stock_test(
    test_engine: TestEngine,
    asset_id: str,
    transaction_id_order_id_dict: Dict[str, List[Order]],
) -> None:
    test_engine.test_stock_clean_up(
        traded_accounts=[[
            FUNDED_COGNITO_USER_ID,
            FUNDED_ALPACA_ACCOUNT_ID,
            asset_id,
        ]],
        transaction_id_order_id_dict=transaction_id_order_id_dict,
    )


@pytest.mark.integration
def test_stock_basic_buy(test_engine: TestEngine):
    """Test buying and recording a single stock position."""
    asset_id = str(uuid.uuid4())
    buy_response = None

    try:
        buy_response = _buy(
            test_engine,
            FUNDED_ALPACA_ACCOUNT_ID,
            FUNDED_COGNITO_USER_ID,
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
    asset_id = str(uuid.uuid4())
    buy_response = None
    sell_response = None

    try:
        buy_response = _buy(
            test_engine,
            FUNDED_ALPACA_ACCOUNT_ID,
            FUNDED_COGNITO_USER_ID,
            asset_id,
            "AAPL",
            200.00,
        )
        sell_response = _sell(
            test_engine,
            FUNDED_ALPACA_ACCOUNT_ID,
            FUNDED_COGNITO_USER_ID,
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
def test_stock_buy_partial_sell_buy_and_close(test_engine: TestEngine):
    """Test buying, partially selling, buying again, and closing a stock."""
    asset_id = str(uuid.uuid4())
    first_buy_response = None
    sell_response = None
    second_buy_response = None
    close_response = None

    try:
        first_buy_response = _buy(
            test_engine,
            FUNDED_ALPACA_ACCOUNT_ID,
            FUNDED_COGNITO_USER_ID,
            asset_id,
            "AAPL",
            200.00,
        )
        sell_response = _sell(
            test_engine,
            FUNDED_ALPACA_ACCOUNT_ID,
            FUNDED_COGNITO_USER_ID,
            asset_id,
            "AAPL",
            50.00,
        )
        second_buy_response = _buy(
            test_engine,
            FUNDED_ALPACA_ACCOUNT_ID,
            FUNDED_COGNITO_USER_ID,
            asset_id,
            "AAPL",
            100.00,
        )
        close_response = _close(
            test_engine,
            FUNDED_ALPACA_ACCOUNT_ID,
            FUNDED_COGNITO_USER_ID,
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
def test_basic_deposit(test_engine: TestEngine):
    portfolio_id = _create_portfolio(
        test_engine,
        FUNDED_COGNITO_USER_ID,
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
            alpaca_account_id=FUNDED_ALPACA_ACCOUNT_ID,
            cognito_user_id=FUNDED_COGNITO_USER_ID,
            portfolio_owner_cognito_user_id=FUNDED_COGNITO_USER_ID,
            portfolio_id=portfolio_id,
            amount=100.00,
        )
    finally:
        transaction_id_order_id_dict = {}
        _record_order_response(transaction_id_order_id_dict, deposit_response)
        _cleanup_funded_test(test_engine, portfolio_id, transaction_id_order_id_dict)


@pytest.mark.integration
def test_multi_symbol_direction_switch(test_engine: TestEngine):
    """Test multiple symbols switching directions simultaneously (long -> short)."""
    portfolio_id = _create_portfolio(
        test_engine,
        FUNDED_COGNITO_USER_ID,
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
        deposit_response = _deposit(test_engine, FUNDED_ALPACA_ACCOUNT_ID, FUNDED_COGNITO_USER_ID, FUNDED_COGNITO_USER_ID, portfolio_id, 300.00)
        update_response = _update(
            test_engine,
            FUNDED_COGNITO_USER_ID,
            portfolio_id,
            symbols=["AAPL", "GOOG", "MSFT"],
            directions=[-1, -1, -1],
            target_weights=[0.33, 0.33, 0.34],
            leverages=[1.0, 1.0, 1.0],
        )
        withdraw_response = _withdraw(test_engine, FUNDED_ALPACA_ACCOUNT_ID, FUNDED_COGNITO_USER_ID, FUNDED_COGNITO_USER_ID, portfolio_id, 50.00)
    finally:
        transaction_id_order_id_dict = {}
        _record_order_response(transaction_id_order_id_dict, deposit_response)
        _record_order_response(transaction_id_order_id_dict, withdraw_response)
        _record_update_order_response(transaction_id_order_id_dict, update_response)
        _cleanup_funded_test(test_engine, portfolio_id, transaction_id_order_id_dict)


@pytest.mark.integration
def test_full_pos_rev_deposit_update_withdraw(test_engine: TestEngine):
    portfolio_id = _create_portfolio(
        test_engine,
        FUNDED_COGNITO_USER_ID,
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
        deposit_response = _deposit(test_engine, FUNDED_ALPACA_ACCOUNT_ID, FUNDED_COGNITO_USER_ID, FUNDED_COGNITO_USER_ID, portfolio_id, 150.00)
        update_response = _update(
            test_engine,
            FUNDED_COGNITO_USER_ID,
            portfolio_id,
            symbols=["AAPL"],
            directions=[-1],
            target_weights=[1.0],
            leverages=[1.0],
        )
        withdraw_response = _withdraw(test_engine, FUNDED_ALPACA_ACCOUNT_ID, FUNDED_COGNITO_USER_ID, FUNDED_COGNITO_USER_ID, portfolio_id, 20.00)
    finally:
        transaction_id_order_id_dict = {}
        _record_order_response(transaction_id_order_id_dict, deposit_response)
        _record_order_response(transaction_id_order_id_dict, withdraw_response)
        _record_update_order_response(transaction_id_order_id_dict, update_response)
        _cleanup_funded_test(test_engine, portfolio_id, transaction_id_order_id_dict)


@pytest.mark.integration
def test_add_new_symbols_keep_existing(test_engine: TestEngine):
    """Test adding new symbols while keeping existing positions."""
    portfolio_id = _create_portfolio(
        test_engine,
        FUNDED_COGNITO_USER_ID,
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
        deposit_response = _deposit(test_engine, FUNDED_ALPACA_ACCOUNT_ID, FUNDED_COGNITO_USER_ID, FUNDED_COGNITO_USER_ID, portfolio_id, 500.00)
        update_response = _update(
            test_engine,
            FUNDED_COGNITO_USER_ID,
            portfolio_id,
            symbols=["AAPL", "GOOG", "MSFT", "TSLA"],
            directions=[1, 1, -1, 1],
            target_weights=[0.25, 0.25, 0.25, 0.25],
            leverages=[1.0, 1.0, 1.0, 1.0],
        )
        withdraw_response = _withdraw(test_engine, FUNDED_ALPACA_ACCOUNT_ID, FUNDED_COGNITO_USER_ID, FUNDED_COGNITO_USER_ID, portfolio_id, 100.00)
    finally:
        transaction_id_order_id_dict = {}
        _record_order_response(transaction_id_order_id_dict, deposit_response)
        _record_order_response(transaction_id_order_id_dict, withdraw_response)
        _record_update_order_response(transaction_id_order_id_dict, update_response)
        _cleanup_funded_test(test_engine, portfolio_id, transaction_id_order_id_dict)


@pytest.mark.integration
def test_mixed_symbol_operations(test_engine: TestEngine):
    """Test removing some symbols, keeping others, and adding new ones."""
    portfolio_id = _create_portfolio(
        test_engine,
        FUNDED_COGNITO_USER_ID,
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
        deposit_response = _deposit(test_engine, FUNDED_ALPACA_ACCOUNT_ID, FUNDED_COGNITO_USER_ID, FUNDED_COGNITO_USER_ID, portfolio_id, 600.00)
        update_response = _update(
            test_engine,
            FUNDED_COGNITO_USER_ID,
            portfolio_id,
            symbols=["AAPL", "MSFT", "UBER", "LLY"],
            directions=[1, 1, -1, 1],
            target_weights=[0.30, 0.30, 0.20, 0.20],
            leverages=[1.0, 1.0, 1.0, 1.0],
        )
        withdraw_response = _withdraw(test_engine, FUNDED_ALPACA_ACCOUNT_ID, FUNDED_COGNITO_USER_ID, FUNDED_COGNITO_USER_ID, portfolio_id, 150.00)
    finally:
        transaction_id_order_id_dict = {}
        _record_order_response(transaction_id_order_id_dict, deposit_response)
        _record_order_response(transaction_id_order_id_dict, withdraw_response)
        _record_update_order_response(transaction_id_order_id_dict, update_response)
        _cleanup_funded_test(test_engine, portfolio_id, transaction_id_order_id_dict)


@pytest.mark.integration
def test_rebalance_weights_only(test_engine: TestEngine):
    """Test rebalancing weights only (same symbols, different allocations)."""
    portfolio_id = _create_portfolio(
        test_engine,
        FUNDED_COGNITO_USER_ID,
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
        deposit_response = _deposit(test_engine, FUNDED_ALPACA_ACCOUNT_ID, FUNDED_COGNITO_USER_ID, FUNDED_COGNITO_USER_ID, portfolio_id, 450.00)
        update_response = _update(
            test_engine,
            FUNDED_COGNITO_USER_ID,
            portfolio_id,
            symbols=["AAPL", "GOOG", "MSFT"],
            directions=[1, -1, 1],
            target_weights=[0.50, 0.20, 0.30],
            leverages=[1.0, 1.0, 1.0],
        )
        withdraw_response = _withdraw(test_engine, FUNDED_ALPACA_ACCOUNT_ID, FUNDED_COGNITO_USER_ID, FUNDED_COGNITO_USER_ID, portfolio_id, 100.00)
    finally:
        transaction_id_order_id_dict = {}
        _record_order_response(transaction_id_order_id_dict, deposit_response)
        _record_order_response(transaction_id_order_id_dict, withdraw_response)
        _record_update_order_response(transaction_id_order_id_dict, update_response)
        _cleanup_funded_test(test_engine, portfolio_id, transaction_id_order_id_dict)


@pytest.mark.integration
def test_change_everything_simultaneously(test_engine: TestEngine):
    """Test changing symbols, weights, directions, and leverage simultaneously."""
    portfolio_id = _create_portfolio(
        test_engine,
        FUNDED_COGNITO_USER_ID,
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
        deposit_response = _deposit(test_engine, FUNDED_ALPACA_ACCOUNT_ID, FUNDED_COGNITO_USER_ID, FUNDED_COGNITO_USER_ID, portfolio_id, 550.00)
        update_response = _update(
            test_engine,
            FUNDED_COGNITO_USER_ID,
            portfolio_id,
            symbols=["MSFT", "UBER", "LLY"],
            directions=[-1, 1, -1],
            target_weights=[0.40, 0.35, 0.25],
            leverages=[1.0, 1.0, 1.0],
        )
        withdraw_response = _withdraw(test_engine, FUNDED_ALPACA_ACCOUNT_ID, FUNDED_COGNITO_USER_ID, FUNDED_COGNITO_USER_ID, portfolio_id, 120.00)
    finally:
        transaction_id_order_id_dict = {}
        _record_order_response(transaction_id_order_id_dict, deposit_response)
        _record_order_response(transaction_id_order_id_dict, withdraw_response)
        _record_update_order_response(transaction_id_order_id_dict, update_response)
        _cleanup_funded_test(test_engine, portfolio_id, transaction_id_order_id_dict)


@pytest.mark.integration
def test_multiple_deposits_before_update(test_engine: TestEngine):
    """Test multiple deposits to the same portfolio before any update."""
    portfolio_id = _create_portfolio(
        test_engine,
        FUNDED_COGNITO_USER_ID,
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
        first_deposit_response = _deposit(test_engine, FUNDED_ALPACA_ACCOUNT_ID, FUNDED_COGNITO_USER_ID, FUNDED_COGNITO_USER_ID, portfolio_id, 200.00)
        second_deposit_response = _deposit(test_engine, FUNDED_ALPACA_ACCOUNT_ID, FUNDED_COGNITO_USER_ID, FUNDED_COGNITO_USER_ID, portfolio_id, 150.00)
        third_deposit_response = _deposit(test_engine, FUNDED_ALPACA_ACCOUNT_ID, FUNDED_COGNITO_USER_ID, FUNDED_COGNITO_USER_ID, portfolio_id, 250.00)
        update_response = _update(
            test_engine,
            FUNDED_COGNITO_USER_ID,
            portfolio_id,
            symbols=["AAPL", "GOOG", "MSFT"],
            directions=[1, -1, 1],
            target_weights=[0.40, 0.30, 0.30],
            leverages=[1.0, 1.0, 1.0],
        )
        withdraw_response = _withdraw(test_engine, FUNDED_ALPACA_ACCOUNT_ID, FUNDED_COGNITO_USER_ID, FUNDED_COGNITO_USER_ID, portfolio_id, 100.00)
    finally:
        transaction_id_order_id_dict = {}
        _record_order_response(transaction_id_order_id_dict, first_deposit_response)
        _record_order_response(transaction_id_order_id_dict, second_deposit_response)
        _record_order_response(transaction_id_order_id_dict, third_deposit_response)
        _record_order_response(transaction_id_order_id_dict, withdraw_response)
        _record_update_order_response(transaction_id_order_id_dict, update_response)
        _cleanup_funded_test(test_engine, portfolio_id, transaction_id_order_id_dict)


@pytest.mark.integration
def test_deposit_after_partial_withdrawal(test_engine: TestEngine):
    """Test deposit after partial withdrawal."""
    portfolio_id = _create_portfolio(
        test_engine,
        FUNDED_COGNITO_USER_ID,
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
        first_deposit_response = _deposit(test_engine, FUNDED_ALPACA_ACCOUNT_ID, FUNDED_COGNITO_USER_ID, FUNDED_COGNITO_USER_ID, portfolio_id, 500.00)
        first_update_response = _update(
            test_engine,
            FUNDED_COGNITO_USER_ID,
            portfolio_id,
            symbols=["AAPL", "MSFT", "GOOG", "TSLA"],
            directions=[1, 1, -1, 1],
            target_weights=[0.30, 0.30, 0.20, 0.20],
            leverages=[1.0, 1.0, 1.0, 1.0],
        )
        first_withdraw_response = _withdraw(test_engine, FUNDED_ALPACA_ACCOUNT_ID, FUNDED_COGNITO_USER_ID, FUNDED_COGNITO_USER_ID, portfolio_id, 150.00)
        second_deposit_response = _deposit(test_engine, FUNDED_ALPACA_ACCOUNT_ID, FUNDED_COGNITO_USER_ID, FUNDED_COGNITO_USER_ID, portfolio_id, 300.00)
        second_update_response = _update(
            test_engine,
            FUNDED_COGNITO_USER_ID,
            portfolio_id,
            symbols=["AAPL", "MSFT", "LLY"],
            directions=[-1, 1, 1],
            target_weights=[0.50, 0.25, 0.25],
            leverages=[1.0, 1.0, 1.0],
        )
        second_withdraw_response = _withdraw(test_engine, FUNDED_ALPACA_ACCOUNT_ID, FUNDED_COGNITO_USER_ID, FUNDED_COGNITO_USER_ID, portfolio_id, 200.00)
        first_withdraw_all_response = _withdraw_all(test_engine, FUNDED_ALPACA_ACCOUNT_ID, FUNDED_COGNITO_USER_ID, FUNDED_COGNITO_USER_ID, portfolio_id,)
    finally:
        transaction_id_order_id_dict = {}
        _record_order_response(transaction_id_order_id_dict, first_deposit_response)
        _record_order_response(transaction_id_order_id_dict, first_withdraw_response)
        _record_order_response(transaction_id_order_id_dict, second_deposit_response)
        _record_order_response(transaction_id_order_id_dict, second_withdraw_response)
        _record_order_response(transaction_id_order_id_dict, first_withdraw_all_response)
        _record_update_order_response(transaction_id_order_id_dict, first_update_response)
        _record_update_order_response(transaction_id_order_id_dict, second_update_response)
        _cleanup_funded_test(test_engine, portfolio_id, transaction_id_order_id_dict)


@pytest.mark.integration
def test_deposit_partial_withdraw_deposit_withdraw_all(test_engine: TestEngine):
    """Test the complete same-owner deposit and withdrawal sequence."""
    portfolio_id = _create_portfolio(
        test_engine,
        FUNDED_COGNITO_USER_ID,
        portfolio_name_prefix="pytest-deposit-withdraw-sequence",
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
            FUNDED_ALPACA_ACCOUNT_ID,
            FUNDED_COGNITO_USER_ID,
            FUNDED_COGNITO_USER_ID,
            portfolio_id,
            500.00,
        )
        partial_withdraw_response = _withdraw(
            test_engine,
            FUNDED_ALPACA_ACCOUNT_ID,
            FUNDED_COGNITO_USER_ID,
            FUNDED_COGNITO_USER_ID,
            portfolio_id,
            150.00,
        )
        second_deposit_response = _deposit(
            test_engine,
            FUNDED_ALPACA_ACCOUNT_ID,
            FUNDED_COGNITO_USER_ID,
            FUNDED_COGNITO_USER_ID,
            portfolio_id,
            200.00,
        )
        withdraw_all_response = _withdraw_all(
            test_engine,
            FUNDED_ALPACA_ACCOUNT_ID,
            FUNDED_COGNITO_USER_ID,
            FUNDED_COGNITO_USER_ID,
            portfolio_id,
        )
    finally:
        transaction_id_order_id_dict = {}
        _record_order_response(transaction_id_order_id_dict, first_deposit_response)
        _record_order_response(transaction_id_order_id_dict, partial_withdraw_response)
        _record_order_response(transaction_id_order_id_dict, second_deposit_response)
        _record_order_response(transaction_id_order_id_dict, withdraw_all_response)
        _cleanup_funded_test(test_engine, portfolio_id, transaction_id_order_id_dict)


@pytest.mark.integration
def test_cross_user_basic_deposit(test_engine: TestEngine):
    portfolio_id = _create_portfolio(
        test_engine,
        PORTFOLIO_OWNER_COGNITO_USER_ID,
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
            alpaca_account_id=FUNDED_ALPACA_ACCOUNT_ID,
            cognito_user_id=FUNDED_COGNITO_USER_ID,
            portfolio_owner_cognito_user_id=PORTFOLIO_OWNER_COGNITO_USER_ID,
            portfolio_id=portfolio_id,
            amount=100.00,
        )
    finally:
        transaction_id_order_id_dict = {}
        _record_order_response(transaction_id_order_id_dict, deposit_response)
        _cleanup_cross_user_test(test_engine, portfolio_id, transaction_id_order_id_dict)


@pytest.mark.integration
def test_cross_user_multi_symbol_direction_switch(test_engine: TestEngine):
    """Test multiple symbols switching directions simultaneously (long -> short)."""
    portfolio_id = _create_portfolio(
        test_engine,
        PORTFOLIO_OWNER_COGNITO_USER_ID,
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
        deposit_response = _deposit(test_engine, FUNDED_ALPACA_ACCOUNT_ID, FUNDED_COGNITO_USER_ID, PORTFOLIO_OWNER_COGNITO_USER_ID, portfolio_id, 300.00)
        update_response = _update(
            test_engine,
            PORTFOLIO_OWNER_COGNITO_USER_ID,
            portfolio_id,
            symbols=["AAPL", "GOOG", "MSFT"],
            directions=[-1, -1, -1],
            target_weights=[0.33, 0.33, 0.34],
            leverages=[1.0, 1.0, 1.0],
        )
        withdraw_response = _withdraw(test_engine, FUNDED_ALPACA_ACCOUNT_ID, FUNDED_COGNITO_USER_ID, PORTFOLIO_OWNER_COGNITO_USER_ID, portfolio_id, 50.00)
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
        PORTFOLIO_OWNER_COGNITO_USER_ID,
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
        deposit_response = _deposit(test_engine, FUNDED_ALPACA_ACCOUNT_ID, FUNDED_COGNITO_USER_ID, PORTFOLIO_OWNER_COGNITO_USER_ID, portfolio_id, 150.00)
        update_response = _update(
            test_engine,
            PORTFOLIO_OWNER_COGNITO_USER_ID,
            portfolio_id,
            symbols=["AAPL"],
            directions=[-1],
            target_weights=[1.0],
            leverages=[1.0],
        )
        withdraw_response = _withdraw(test_engine, FUNDED_ALPACA_ACCOUNT_ID, FUNDED_COGNITO_USER_ID, PORTFOLIO_OWNER_COGNITO_USER_ID, portfolio_id, 20.00)
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
        PORTFOLIO_OWNER_COGNITO_USER_ID,
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
        deposit_response = _deposit(test_engine, FUNDED_ALPACA_ACCOUNT_ID, FUNDED_COGNITO_USER_ID, PORTFOLIO_OWNER_COGNITO_USER_ID, portfolio_id, 500.00)
        update_response = _update(
            test_engine,
            PORTFOLIO_OWNER_COGNITO_USER_ID,
            portfolio_id,
            symbols=["AAPL", "GOOG", "MSFT", "TSLA"],
            directions=[1, 1, -1, 1],
            target_weights=[0.25, 0.25, 0.25, 0.25],
            leverages=[1.0, 1.0, 1.0, 1.0],
        )
        withdraw_response = _withdraw(test_engine, FUNDED_ALPACA_ACCOUNT_ID, FUNDED_COGNITO_USER_ID, PORTFOLIO_OWNER_COGNITO_USER_ID, portfolio_id, 100.00)
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
        PORTFOLIO_OWNER_COGNITO_USER_ID,
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
        deposit_response = _deposit(test_engine, FUNDED_ALPACA_ACCOUNT_ID, FUNDED_COGNITO_USER_ID, PORTFOLIO_OWNER_COGNITO_USER_ID, portfolio_id, 600.00)
        update_response = _update(
            test_engine,
            PORTFOLIO_OWNER_COGNITO_USER_ID,
            portfolio_id,
            symbols=["AAPL", "MSFT", "UBER", "LLY"],
            directions=[1, 1, -1, 1],
            target_weights=[0.30, 0.30, 0.20, 0.20],
            leverages=[1.0, 1.0, 1.0, 1.0],
        )
        withdraw_response = _withdraw(test_engine, FUNDED_ALPACA_ACCOUNT_ID, FUNDED_COGNITO_USER_ID, PORTFOLIO_OWNER_COGNITO_USER_ID, portfolio_id, 150.00)
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
        PORTFOLIO_OWNER_COGNITO_USER_ID,
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
        deposit_response = _deposit(test_engine, FUNDED_ALPACA_ACCOUNT_ID, FUNDED_COGNITO_USER_ID, PORTFOLIO_OWNER_COGNITO_USER_ID, portfolio_id, 450.00)
        update_response = _update(
            test_engine,
            PORTFOLIO_OWNER_COGNITO_USER_ID,
            portfolio_id,
            symbols=["AAPL", "GOOG", "MSFT"],
            directions=[1, -1, 1],
            target_weights=[0.50, 0.20, 0.30],
            leverages=[1.0, 1.0, 1.0],
        )
        withdraw_response = _withdraw(test_engine, FUNDED_ALPACA_ACCOUNT_ID, FUNDED_COGNITO_USER_ID, PORTFOLIO_OWNER_COGNITO_USER_ID, portfolio_id, 100.00)
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
        PORTFOLIO_OWNER_COGNITO_USER_ID,
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
        deposit_response = _deposit(test_engine, FUNDED_ALPACA_ACCOUNT_ID, FUNDED_COGNITO_USER_ID, PORTFOLIO_OWNER_COGNITO_USER_ID, portfolio_id, 550.00)
        update_response = _update(
            test_engine,
            PORTFOLIO_OWNER_COGNITO_USER_ID,
            portfolio_id,
            symbols=["MSFT", "UBER", "LLY"],
            directions=[-1, 1, -1],
            target_weights=[0.40, 0.35, 0.25],
            leverages=[1.0, 1.0, 1.0],
        )
        withdraw_response = _withdraw(test_engine, FUNDED_ALPACA_ACCOUNT_ID, FUNDED_COGNITO_USER_ID, PORTFOLIO_OWNER_COGNITO_USER_ID, portfolio_id, 120.00)
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
        PORTFOLIO_OWNER_COGNITO_USER_ID,
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
        first_deposit_response = _deposit(test_engine, FUNDED_ALPACA_ACCOUNT_ID, FUNDED_COGNITO_USER_ID, PORTFOLIO_OWNER_COGNITO_USER_ID, portfolio_id, 200.00)
        second_deposit_response = _deposit(test_engine, FUNDED_ALPACA_ACCOUNT_ID, FUNDED_COGNITO_USER_ID, PORTFOLIO_OWNER_COGNITO_USER_ID, portfolio_id, 150.00)
        third_deposit_response = _deposit(test_engine, FUNDED_ALPACA_ACCOUNT_ID, FUNDED_COGNITO_USER_ID, PORTFOLIO_OWNER_COGNITO_USER_ID, portfolio_id, 250.00)
        update_response = _update(
            test_engine,
            PORTFOLIO_OWNER_COGNITO_USER_ID,
            portfolio_id,
            symbols=["AAPL", "GOOG", "MSFT"],
            directions=[1, -1, 1],
            target_weights=[0.40, 0.30, 0.30],
            leverages=[1.0, 1.0, 1.0],
        )
        withdraw_response = _withdraw(test_engine, FUNDED_ALPACA_ACCOUNT_ID, FUNDED_COGNITO_USER_ID, PORTFOLIO_OWNER_COGNITO_USER_ID, portfolio_id, 100.00)
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
        PORTFOLIO_OWNER_COGNITO_USER_ID,
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
        first_deposit_response = _deposit(test_engine, FUNDED_ALPACA_ACCOUNT_ID, FUNDED_COGNITO_USER_ID, PORTFOLIO_OWNER_COGNITO_USER_ID, portfolio_id, 500.00)
        first_update_response = _update(
            test_engine,
            PORTFOLIO_OWNER_COGNITO_USER_ID,
            portfolio_id,
            symbols=["AAPL", "MSFT", "GOOG", "TSLA"],
            directions=[1, 1, -1, 1],
            target_weights=[0.30, 0.30, 0.20, 0.20],
            leverages=[1.0, 1.0, 1.0, 1.0],
        )
        first_withdraw_response = _withdraw(test_engine, FUNDED_ALPACA_ACCOUNT_ID, FUNDED_COGNITO_USER_ID, PORTFOLIO_OWNER_COGNITO_USER_ID, portfolio_id, 150.00)
        second_deposit_response = _deposit(test_engine, FUNDED_ALPACA_ACCOUNT_ID, FUNDED_COGNITO_USER_ID, PORTFOLIO_OWNER_COGNITO_USER_ID, portfolio_id, 300.00)
        second_update_response = _update(
            test_engine,
            PORTFOLIO_OWNER_COGNITO_USER_ID,
            portfolio_id,
            symbols=["AAPL", "MSFT", "LLY"],
            directions=[-1, 1, 1],
            target_weights=[0.50, 0.25, 0.25],
            leverages=[1.0, 1.0, 1.0],
        )
        second_withdraw_response = _withdraw(test_engine, FUNDED_ALPACA_ACCOUNT_ID, FUNDED_COGNITO_USER_ID, PORTFOLIO_OWNER_COGNITO_USER_ID, portfolio_id, 200.00)
        first_withdraw_all_response = _withdraw_all(test_engine, FUNDED_ALPACA_ACCOUNT_ID, FUNDED_COGNITO_USER_ID, PORTFOLIO_OWNER_COGNITO_USER_ID, portfolio_id,)
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
        PORTFOLIO_OWNER_COGNITO_USER_ID,
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
            FUNDED_ALPACA_ACCOUNT_ID,
            FUNDED_COGNITO_USER_ID,
            PORTFOLIO_OWNER_COGNITO_USER_ID,
            portfolio_id,
            500.00,
        )
        partial_withdraw_response = _withdraw(
            test_engine,
            FUNDED_ALPACA_ACCOUNT_ID,
            FUNDED_COGNITO_USER_ID,
            PORTFOLIO_OWNER_COGNITO_USER_ID,
            portfolio_id,
            150.00,
        )
        second_deposit_response = _deposit(
            test_engine,
            FUNDED_ALPACA_ACCOUNT_ID,
            FUNDED_COGNITO_USER_ID,
            PORTFOLIO_OWNER_COGNITO_USER_ID,
            portfolio_id,
            200.00,
        )
        withdraw_all_response = _withdraw_all(
            test_engine,
            FUNDED_ALPACA_ACCOUNT_ID,
            FUNDED_COGNITO_USER_ID,
            PORTFOLIO_OWNER_COGNITO_USER_ID,
            portfolio_id,
        )
    finally:
        transaction_id_order_id_dict = {}
        _record_order_response(transaction_id_order_id_dict, first_deposit_response)
        _record_order_response(transaction_id_order_id_dict, partial_withdraw_response)
        _record_order_response(transaction_id_order_id_dict, second_deposit_response)
        _record_order_response(transaction_id_order_id_dict, withdraw_all_response)
        _cleanup_cross_user_test(test_engine, portfolio_id, transaction_id_order_id_dict)
