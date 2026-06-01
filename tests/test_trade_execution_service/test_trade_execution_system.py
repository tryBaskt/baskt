import uuid

import pytest

from conftest import TestEngine

from backend.domain.baskt import BasktAccount

"""
$10000 - {account_id: 27b7f59d-8f35-4330-93f7-45d5d0db57a5, email_address: baskt_testuser_160fb99f@example.com}
$100 - {account_id: 22b3e5ec-d4ae-48ea-a071-1f89b5c5640e, email_address: baskt_testuser_4f751c38@example.com}
$0 - {account_id: 9e67bd91-098b-41b8-9ea3-4e8b8b487b5c, email_address: baskt_testuser_b4f6bfa6@example.com}
"""

FUNDED_ACCOUNT_EMAIL = "baskt_testuser_160fb99f@example.com"


def _get_funded_baskt_account(test_engine: TestEngine):
    return test_engine.account_lifecycle_service.get_baskt_account_by_email_address(
        email_address=FUNDED_ACCOUNT_EMAIL
    )


def _create_portfolio(
    test_engine: TestEngine,
    baskt_account: BasktAccount,
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
        portfolio_owner_cognito_user_id=baskt_account.cognito_user_id,
    )


def _deposit(test_engine: TestEngine, baskt_account, portfolio_id: str, amount: float) -> None:
    test_engine.test_deposit(
        deposit_amount=amount,
        portfolio_id=portfolio_id,
        cognito_user_id=baskt_account.cognito_user_id,
        alpaca_account_id=baskt_account.alpaca_account_id,
        portfolio_owner_cognito_user_id=baskt_account.cognito_user_id,
    )


def _update(
    test_engine: TestEngine,
    baskt_account: BasktAccount,
    portfolio_id: str,
    *,
    symbols: list[str],
    directions: list[int],
    target_weights: list[float],
    leverages: list[float],
) -> dict:
    updated_orders_dict = test_engine.test_update(
        portfolio_owner_cognito_user_id=baskt_account.cognito_user_id,
        portfolio_id=portfolio_id,
        new_symbols=symbols,
        new_directions=directions,
        new_target_weights=target_weights,
        new_leverages=leverages,
    )

    test_engine.test_update_effect(
        portfolio_owner_cognito_user_id=baskt_account.cognito_user_id,
        portfolio_id=portfolio_id,
        ud_orders_dict=updated_orders_dict,
    )

    return updated_orders_dict


def _withdraw(
        test_engine: TestEngine, 
        baskt_account: BasktAccount, 
        portfolio_id: str, 
        amount: float
    ) -> None:
    test_engine.test_withdraw(
        portfolio_owner_cognito_user_id=baskt_account.cognito_user_id,
        cognito_user_id=baskt_account.cognito_user_id,
        alpaca_account_id=baskt_account.alpaca_account_id,
        portfolio_id=portfolio_id,
        withdraw_amount=amount,
    )


def _cleanup(
        test_engine: TestEngine, 
        baskt_account: BasktAccount, 
        portfolio_id: str
    ) -> None:
    test_engine.alpaca_broker_client.execute_close_all_position(
        alpaca_account_id=baskt_account.alpaca_account_id,
        cognito_user_id=baskt_account.cognito_user_id,
    )
    test_engine.model_portfolio_repository.dynamodb.delete_item(
        key={"portfolio_id": portfolio_id}
    )
    test_engine.model_portfolio_follower_repository.delete_model_portfolio_follower(
        cognito_user_id=baskt_account.cognito_user_id,
        portfolio_id=portfolio_id,
    )
    test_engine.portfolio_allocation_repository.portfolio_allocation_table_client.delete_item(
        key={
            "cognito_user_id": baskt_account.cognito_user_id,
            "portfolio_id": portfolio_id,
        }
    )


# @pytest.mark.integration
# def test_basic_deposit(test_engine: TestEngine):
#     baskt_account = _get_funded_baskt_account(test_engine)
#     portfolio_id = _create_portfolio(
#         test_engine,
#         baskt_account,
#         portfolio_name_prefix="pytest-basic-deposit",
#         symbols=["AAPL"],
#         directions=[1],
#         target_weights=[1.00],
#         leverages=[1.0],
#     )

#     try:
#         _deposit(test_engine, baskt_account, portfolio_id, 100.00)
#     finally:
#         _cleanup(test_engine, baskt_account, portfolio_id)


@pytest.mark.integration
def test_multi_symbol_direction_switch(test_engine: TestEngine):
    """Test multiple symbols switching directions simultaneously (long -> short)."""
    baskt_account = _get_funded_baskt_account(test_engine)
    portfolio_id = _create_portfolio(
        test_engine,
        baskt_account,
        portfolio_name_prefix="pytest-multi-dir-switch",
        symbols=["AAPL", "GOOG", "MSFT"],
        directions=[1, 1, 1],
        target_weights=[0.33, 0.33, 0.34],
        leverages=[1.0, 1.0, 1.0],
    )

    try:
        _deposit(test_engine, baskt_account, portfolio_id, 300.00)
        _update(
            test_engine,
            baskt_account,
            portfolio_id,
            symbols=["AAPL", "GOOG", "MSFT"],
            directions=[-1, -1, -1],
            target_weights=[0.33, 0.33, 0.34],
            leverages=[1.0, 1.0, 1.0],
        )
        _withdraw(test_engine, baskt_account, portfolio_id, 50.00)
    finally:
        _cleanup(test_engine, baskt_account, portfolio_id)


# @pytest.mark.integration
# def test_full_pos_rev_deposit_update_withdraw(test_engine: TestEngine):
#     baskt_account = _get_funded_baskt_account(test_engine)
#     portfolio_id = _create_portfolio(
#         test_engine,
#         baskt_account,
#         portfolio_name_prefix="pytest-full-pos-rev",
#         symbols=["AAPL"],
#         directions=[1],
#         target_weights=[1.00],
#         leverages=[1.0],
#     )

#     try:
#         _deposit(test_engine, baskt_account, portfolio_id, 150.00)
#         _update(
#             test_engine,
#             baskt_account,
#             portfolio_id,
#             symbols=["AAPL"],
#             directions=[-1],
#             target_weights=[1.0],
#             leverages=[1.0],
#         )
#         _withdraw(test_engine, baskt_account, portfolio_id, 20.00)
#     finally:
#         _cleanup(test_engine, baskt_account, portfolio_id)


# @pytest.mark.integration
# def test_add_new_symbols_keep_existing(test_engine: TestEngine):
#     """Test adding new symbols while keeping existing positions."""
#     baskt_account = _get_funded_baskt_account(test_engine)
#     portfolio_id = _create_portfolio(
#         test_engine,
#         baskt_account,
#         portfolio_name_prefix="pytest-add-symbols",
#         symbols=["AAPL", "GOOG"],
#         directions=[1, 1],
#         target_weights=[0.50, 0.50],
#         leverages=[1.0, 1.0],
#     )

#     try:
#         _deposit(test_engine, baskt_account, portfolio_id, 500.00)
#         _update(
#             test_engine,
#             baskt_account,
#             portfolio_id,
#             symbols=["AAPL", "GOOG", "MSFT", "TSLA"],
#             directions=[1, 1, -1, 1],
#             target_weights=[0.25, 0.25, 0.25, 0.25],
#             leverages=[1.0, 1.0, 1.0, 1.0],
#         )
#         _withdraw(test_engine, baskt_account, portfolio_id, 100.00)
#     finally:
#         _cleanup(test_engine, baskt_account, portfolio_id)


# @pytest.mark.integration
# def test_mixed_symbol_operations(test_engine: TestEngine):
#     """Test removing some symbols, keeping others, and adding new ones."""
#     baskt_account = _get_funded_baskt_account(test_engine)
#     portfolio_id = _create_portfolio(
#         test_engine,
#         baskt_account,
#         portfolio_name_prefix="pytest-mixed-ops",
#         symbols=["AAPL", "GOOG", "MSFT", "TSLA"],
#         directions=[1, 1, 1, -1],
#         target_weights=[0.25, 0.25, 0.25, 0.25],
#         leverages=[1.0, 1.0, 1.0, 1.0],
#     )

#     try:
#         _deposit(test_engine, baskt_account, portfolio_id, 600.00)
#         _update(
#             test_engine,
#             baskt_account,
#             portfolio_id,
#             symbols=["AAPL", "MSFT", "NVDA", "META"],
#             directions=[1, 1, -1, 1],
#             target_weights=[0.30, 0.30, 0.20, 0.20],
#             leverages=[1.0, 1.0, 1.0, 1.0],
#         )
#         _withdraw(test_engine, baskt_account, portfolio_id, 150.00)
#     finally:
#         _cleanup(test_engine, baskt_account, portfolio_id)


# @pytest.mark.integration
# def test_rebalance_weights_only(test_engine: TestEngine):
#     """Test rebalancing weights only (same symbols, different allocations)."""
#     baskt_account = _get_funded_baskt_account(test_engine)
#     portfolio_id = _create_portfolio(
#         test_engine,
#         baskt_account,
#         portfolio_name_prefix="pytest-rebalance-weights",
#         symbols=["AAPL", "GOOG", "MSFT"],
#         directions=[1, -1, 1],
#         target_weights=[0.33, 0.33, 0.34],
#         leverages=[1.0, 1.0, 1.0],
#     )

#     try:
#         _deposit(test_engine, baskt_account, portfolio_id, 450.00)
#         _update(
#             test_engine,
#             baskt_account,
#             portfolio_id,
#             symbols=["AAPL", "GOOG", "MSFT"],
#             directions=[1, -1, 1],
#             target_weights=[0.50, 0.20, 0.30],
#             leverages=[1.0, 1.0, 1.0],
#         )
#         _withdraw(test_engine, baskt_account, portfolio_id, 100.00)
#     finally:
#         _cleanup(test_engine, baskt_account, portfolio_id)


# @pytest.mark.integration
# def test_change_everything_simultaneously(test_engine: TestEngine):
#     """Test changing symbols, weights, directions, and leverage simultaneously."""
#     baskt_account = _get_funded_baskt_account(test_engine)
#     portfolio_id = _create_portfolio(
#         test_engine,
#         baskt_account,
#         portfolio_name_prefix="pytest-change-all",
#         symbols=["AAPL", "GOOG"],
#         directions=[1, -1],
#         target_weights=[0.60, 0.40],
#         leverages=[1.0, 1.0],
#     )

#     try:
#         _deposit(test_engine, baskt_account, portfolio_id, 550.00)
#         _update(
#             test_engine,
#             baskt_account,
#             portfolio_id,
#             symbols=["MSFT", "NVDA", "TSLA"],
#             directions=[-1, 1, -1],
#             target_weights=[0.40, 0.35, 0.25],
#             leverages=[1.0, 1.0, 1.0],
#         )
#         _withdraw(test_engine, baskt_account, portfolio_id, 120.00)
#     finally:
#         _cleanup(test_engine, baskt_account, portfolio_id)


# @pytest.mark.integration
# def test_multiple_deposits_before_update(test_engine: TestEngine):
#     """Test multiple deposits to the same portfolio before any update."""
#     baskt_account = _get_funded_baskt_account(test_engine)
#     portfolio_id = _create_portfolio(
#         test_engine,
#         baskt_account,
#         portfolio_name_prefix="pytest-multi-deposits",
#         symbols=["AAPL", "GOOG"],
#         directions=[1, -1],
#         target_weights=[0.60, 0.40],
#         leverages=[1.0, 1.0],
#     )

#     try:
#         _deposit(test_engine, baskt_account, portfolio_id, 200.00)
#         _deposit(test_engine, baskt_account, portfolio_id, 150.00)
#         _deposit(test_engine, baskt_account, portfolio_id, 250.00)
#         _update(
#             test_engine,
#             baskt_account,
#             portfolio_id,
#             symbols=["AAPL", "GOOG", "MSFT"],
#             directions=[1, -1, 1],
#             target_weights=[0.40, 0.30, 0.30],
#             leverages=[1.0, 1.0, 1.0],
#         )
#         _withdraw(test_engine, baskt_account, portfolio_id, 100.00)
#     finally:
#         _cleanup(test_engine, baskt_account, portfolio_id)


# @pytest.mark.integration
# def test_deposit_after_partial_withdrawal(test_engine: TestEngine):
#     """Test deposit after partial withdrawal."""
#     baskt_account = _get_funded_baskt_account(test_engine)
#     portfolio_id = _create_portfolio(
#         test_engine,
#         baskt_account,
#         portfolio_name_prefix="pytest-deposit-after-wd",
#         symbols=["AAPL", "MSFT", "GOOG"],
#         directions=[1, 1, -1],
#         target_weights=[0.40, 0.40, 0.20],
#         leverages=[1.0, 1.0, 1.0],
#     )

#     try:
#         _deposit(test_engine, baskt_account, portfolio_id, 500.00)
#         _update(
#             test_engine,
#             baskt_account,
#             portfolio_id,
#             symbols=["AAPL", "MSFT", "GOOG", "TSLA"],
#             directions=[1, 1, -1, 1],
#             target_weights=[0.30, 0.30, 0.20, 0.20],
#             leverages=[1.0, 1.0, 1.0, 1.0],
#         )
#         _withdraw(test_engine, baskt_account, portfolio_id, 150.00)
#         _deposit(test_engine, baskt_account, portfolio_id, 300.00)
#         _update(
#             test_engine,
#             baskt_account,
#             portfolio_id,
#             symbols=["AAPL", "MSFT", "NVDA"],
#             directions=[-1, 1, 1],
#             target_weights=[0.50, 0.25, 0.25],
#             leverages=[1.0, 1.0, 1.0],
#         )
#         _withdraw(test_engine, baskt_account, portfolio_id, 200.00)
#     finally:
#         _cleanup(test_engine, baskt_account, portfolio_id)
