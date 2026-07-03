"""Validate trade requests and publish executable transactions to SQS."""

from __future__ import annotations

import json
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from functools import wraps
from inspect import signature
from typing import Any, Dict, Optional
from botocore.exceptions import BotoCoreError, ClientError

from clients.alpaca_broker_client import AlpacaBrokerClient
from domain.portfolio_allocation_domain import (
    PortfolioAllocation,
    PortfolioAllocationTransactionSnapshot,
)
from repository.model_portfolio_repository import ModelPortfolioRepository
from repository.portfolio_allocation_repository import PortfolioAllocationRepository
from repository.user_trade_lock_repository import UserTradeLockRepository
from repository.model_portfolio_follower_repository import ModelPortfolioFollowerRepository

MINIMUM_PORTFOLIO_BALANCE = 1.0
MINIMUM_STOCK_BALANCE = 1.0
TRADE_AMOUNT_MIN = 10.0
QUEUE_LOCK_LEASE_SECONDS = 30


def _with_user_trade_lock(method: Any) -> Any:
    """Serialize one public queue operation for its Cognito user."""
    method_signature = signature(method)

    @wraps(method)
    def wrapped(self: "TradeExecutionQueuingService", *args: Any, **kwargs: Any) -> Any:
        bound = method_signature.bind(self, *args, **kwargs)
        cognito_user_id = bound.arguments["cognito_user_id"]
        with self._user_trade_lock(cognito_user_id=cognito_user_id):
            return method(self, *args, **kwargs)

    return wrapped


class TradeExecutionQueuingInternalServerError(Exception):
    """Raised when a trade request cannot be validated or queued."""

    def __init__(
        self,
        message: str,
        code: str = "TRADE_EXECUTION_QUEUING_SERVICE_ERROR",
    ) -> None:
        super().__init__(message)
        self.code = code


class TradeExecutionQueuingService:
    """Create queued allocation transactions and publish them for execution."""

    def __init__(
        self,
        sqs_client: Any,
        queue_url: str,
        model_portfolio_repository: ModelPortfolioRepository,
        portfolio_allocation_repository: PortfolioAllocationRepository,
        alpaca_broker_client: AlpacaBrokerClient,
        user_trade_lock_repository: UserTradeLockRepository,
        model_portfolio_follower_repository: ModelPortfolioFollowerRepository
    ) -> None:
        if not queue_url:
            raise TradeExecutionQueuingInternalServerError(
                message="Trade execution queue URL is required.",
                code="TRADE_EXECUTION_QUEUE_URL_REQUIRED",
            )
        self.sqs_client = sqs_client
        self.queue_url = queue_url
        self.model_portfolio_repository = model_portfolio_repository
        self.portfolio_allocation_repository = portfolio_allocation_repository
        self.alpaca_broker_client = alpaca_broker_client
        self.user_trade_lock_repository = user_trade_lock_repository
        self.model_portfolio_follower_repository = model_portfolio_follower_repository

    def _send_message(self, *, action: str, payload: Dict[str, Any]) -> str:
        """Publish one JSON trade message and return its SQS message ID."""
        try:
            response = self.sqs_client.send_message(
                QueueUrl=self.queue_url,
                MessageBody=json.dumps(
                    {"action": action, "payload": payload},
                    separators=(",", ":"),
                ),
            )
            return str(response["MessageId"])
        except (TypeError, ValueError) as error:
            raise TradeExecutionQueuingInternalServerError(
                message=f"Failed to serialize trade execution message: {error}",
                code="TRADE_EXECUTION_QUEUE_MESSAGE_SERIALIZATION_FAILED",
            ) from error
        except (BotoCoreError, ClientError, KeyError) as error:
            raise TradeExecutionQueuingInternalServerError(
                message=f"Failed to publish trade execution message: {error}",
                code="TRADE_EXECUTION_QUEUE_SEND_FAILED",
            ) from error

    def _queue_transaction(
        self,
        *,
        portfolio_allocation: PortfolioAllocation,
        transaction: PortfolioAllocationTransactionSnapshot,
        action: str,
        payload: Dict[str, Any],
    ) -> str:
        """Persist a transaction before publishing the message that executes it."""
        if self.portfolio_allocation_repository.is_exists_portfolio_allocation_for_user(
            cognito_user_id=portfolio_allocation.cognito_user_id,
            portfolio_id=portfolio_allocation.portfolio_id,
        ):
            portfolio_allocation = self.portfolio_allocation_repository.get_portfolio_allocation(
                cognito_user_id=portfolio_allocation.cognito_user_id,
                portfolio_id=portfolio_allocation.portfolio_id,
            )

        portfolio_allocation.transaction_history.append(transaction)
        self.portfolio_allocation_repository.set_portfolio_allocation(
            portfolio_allocation=portfolio_allocation
        )
        try:
            return self._send_message(action=action, payload=payload)
        except Exception:
            transaction.status = "FAILED"
            transaction.updated_at = datetime.now(timezone.utc)
            transaction.status_explanation = (
                "The trade passed validation but could not be added to the execution queue."
            )
            self.portfolio_allocation_repository.set_portfolio_allocation(
                portfolio_allocation=portfolio_allocation
            )
            raise

    @contextmanager
    def _user_trade_lock(self, *, cognito_user_id: str):
        """Acquire and always release the queue mutation lock for one user."""
        owner_token = str(uuid.uuid4())
        acquired = self.user_trade_lock_repository.acquire_lock(
            cognito_user_id=cognito_user_id,
            owner_token=owner_token,
            lease_seconds=QUEUE_LOCK_LEASE_SECONDS,
        )
        if not acquired:
            raise TradeExecutionQueuingInternalServerError(
                message="Another queue operation is currently writing trades for this user.",
                code="TRADE_EXECUTION_QUEUE_LOCKED",
            )
        try:
            yield
        finally:
            self.user_trade_lock_repository.release_lock(
                cognito_user_id=cognito_user_id,
                owner_token=owner_token,
            )

    @staticmethod
    def _new_transaction(
        *,
        requested_amount: Optional[float],
        transaction_type: str,
        model_portfolio_snapshot_id: Optional[str] = None
    ) -> PortfolioAllocationTransactionSnapshot:
        """Build the initial transaction state owned by the queuing service."""
        queued_at = datetime.now(timezone.utc)
        return PortfolioAllocationTransactionSnapshot(
            transaction_id=str(uuid.uuid4()),
            created_at=queued_at,
            updated_at=queued_at,
            requested_amount=requested_amount,
            transaction_type=transaction_type,
            status="QUEUED",
            model_portfolio_snapshot_id=model_portfolio_snapshot_id
        )

    def _allocation_equity(self, allocation: PortfolioAllocation) -> float:
        """Return the current absolute market value of an allocation."""
        if not allocation.position_history or not allocation.position_history[-1].positions:
            return 0.0
        _, equity, _ = self.portfolio_allocation_repository.calculate_positions_current_value(
            portfolio_allocation_position_snapshot=allocation.position_history[-1]
        )
        return float(equity)

    @staticmethod
    def _stock_direction(allocation: PortfolioAllocation) -> Optional[int]:
        """Return the current stock direction, or None for an empty allocation."""
        if not allocation.position_history or not allocation.position_history[-1].positions:
            return None
        return int(allocation.position_history[-1].positions[0].direction)

    @staticmethod
    def _project_stock_equity(
        *,
        current_equity: float,
        current_direction: Optional[int],
        amount: float,
        trade_direction: int,
    ) -> float:
        """Project absolute stock exposure after a buy or sell dollar trade."""
        if current_direction is None or current_direction == trade_direction:
            return current_equity + amount
        return abs(current_equity - amount)

    @staticmethod
    def _validate_required(field_name: str, value: str) -> None:
        if not isinstance(value, str) or not value.strip():
            raise TradeExecutionQueuingInternalServerError(
                message=f"Trade execution field '{field_name}' is required.",
                code="TRADE_EXECUTION_QUEUE_FIELD_REQUIRED",
            )

    def _validate_common_trade_fields(
        self,
        *,
        cognito_user_id: str,
        alpaca_account_id: str,
    ) -> None:
        self._validate_required("cognito_user_id", cognito_user_id)
        self._validate_required("alpaca_account_id", alpaca_account_id)

    def _validate_common_stock_fields(
        self,
        *,
        symbol: str,
        asset_id: str,
        cognito_user_id: str,
        alpaca_account_id: str,
    ) -> None:
        self._validate_required("symbol", symbol)
        self._validate_required("asset_id", asset_id)
        self._validate_common_trade_fields(
            cognito_user_id=cognito_user_id,
            alpaca_account_id=alpaca_account_id,
        )

    @staticmethod
    def _validate_amount(amount: float) -> None:
        if not isinstance(amount, (int, float)) or isinstance(amount, bool):
            raise TradeExecutionQueuingInternalServerError(
                message="Trade amount must be numeric.",
                code="TRADE_EXECUTION_QUEUE_AMOUNT_INVALID",
            )
        if amount < TRADE_AMOUNT_MIN:
            raise TradeExecutionQueuingInternalServerError(
                message=f"Trade amount must be at least ${TRADE_AMOUNT_MIN:.2f}.",
                code="TRADE_EXECUTION_QUEUE_AMOUNT_INVALID",
            )

    def queue_portfolio_update(
        self,
        *,
        portfolio_id: str,
        model_portfolio_snapshot_id: str,
    ) -> Dict[str, str]:
        """Queue an update transaction for every current portfolio follower."""
        cognito_user_id = "unknown"
        alpaca_account_id = "unknown"
        try:
            self._validate_required("portfolio_id", portfolio_id)
            self._validate_required(
                "model_portfolio_snapshot_id", model_portfolio_snapshot_id
            )
            model_portfolio = self.model_portfolio_repository.get_model_portfolio(
                portfolio_id=portfolio_id
            )
            if not any(
                snapshot.snapshot_id == model_portfolio_snapshot_id
                for snapshot in model_portfolio.position_history
            ):
                raise TradeExecutionQueuingInternalServerError(
                    message=(
                        f"Model portfolio snapshot '{model_portfolio_snapshot_id}' "
                        f"does not exist for portfolio '{portfolio_id}'."
                    ),
                    code="TRADE_EXECUTION_QUEUE_MODEL_PORTFOLIO_SNAPSHOT_NOT_FOUND",
                )

            model_portfolio_followers_dict = self.model_portfolio_follower_repository.get_model_portfolio_followers(portfolio_id=portfolio_id)
            message_ids: Dict[str, str] = {}

            for follower_dict in model_portfolio_followers_dict:
                cognito_user_id = follower_dict["cognito_user_id"]
                alpaca_account_id = follower_dict["alpaca_account_id"]
                with self._user_trade_lock(cognito_user_id=cognito_user_id):

                    portfolio_allocation = self.portfolio_allocation_repository.get_portfolio_allocation(
                        cognito_user_id=cognito_user_id,
                        portfolio_id=portfolio_id,
                        with_wait=True
                    )
                    already_targets_snapshot = any(
                        transaction.model_portfolio_snapshot_id
                        == model_portfolio_snapshot_id
                        and transaction.transaction_type.upper() in {"DEPOSIT", "UPDATE"}
                        and transaction.status.upper() not in {"FAILED", "CANCELLED"}
                        for transaction in portfolio_allocation.transaction_history
                    )
                    if already_targets_snapshot:
                        continue

                    transaction = self._new_transaction(
                        requested_amount=None,
                        transaction_type="UPDATE",
                        model_portfolio_snapshot_id=model_portfolio_snapshot_id
                    )

                    message_ids[cognito_user_id] = self._queue_transaction(
                        portfolio_allocation=portfolio_allocation,
                        transaction=transaction,
                        action="portfolio_update",
                        payload={
                            "portfolio_id": portfolio_id,
                            "portfolio_owner_cognito_user_id": model_portfolio.portfolio_owner_cognito_user_id,
                            "model_portfolio_snapshot_id": model_portfolio_snapshot_id,
                            "transaction_id": transaction.transaction_id,
                            "cognito_user_id": cognito_user_id,
                            "alpaca_account_id": alpaca_account_id,
                        }
                    )
            return message_ids
        except TradeExecutionQueuingInternalServerError:
            raise
        except Exception as error:
            raise TradeExecutionQueuingInternalServerError(
                message=(
                    f"Failed to queue portfolio update for portfolio '{portfolio_id}', "
                    f"user '{cognito_user_id}', and account '{alpaca_account_id}': {error}"
                ),
                code="TRADE_EXECUTION_QUEUE_PORTFOLIO_UPDATE_FAILED",
            ) from error

    @_with_user_trade_lock
    def queue_portfolio_deposit(
        self,
        *,
        portfolio_id: str,
        portfolio_owner_cognito_user_id: str,
        amount: float,
        cognito_user_id: str,
        alpaca_account_id: str,
    ) -> str:
        """Validate and queue a model-portfolio deposit."""
        try:
            self._validate_common_trade_fields(
                cognito_user_id=cognito_user_id,
                alpaca_account_id=alpaca_account_id,
            )
            self._validate_required("portfolio_id", portfolio_id)
            self._validate_required(
                "portfolio_owner_cognito_user_id", portfolio_owner_cognito_user_id
            )
            self._validate_amount(amount)

            model_portfolio = self.model_portfolio_repository.get_model_portfolio(
                portfolio_id=portfolio_id
            )
            allocation = PortfolioAllocation(
                portfolio_id=portfolio_id,
                cognito_user_id=cognito_user_id,
                position_history=[],
                transaction_history=[],
                total_cost_basis=0.0,
                portfolio_allocation_type="MODEL_PORTFOLIO",
                portfolio_name=model_portfolio.portfolio_name,
            )
            if self.portfolio_allocation_repository.is_exists_portfolio_allocation_for_user(
                cognito_user_id=cognito_user_id,
                portfolio_id=portfolio_id,
            ):
                allocation = self.portfolio_allocation_repository.get_portfolio_allocation(
                    cognito_user_id=cognito_user_id,
                    portfolio_id=portfolio_id,
                )

            projected_equity = self._allocation_equity(allocation) + amount
            if projected_equity < MINIMUM_PORTFOLIO_BALANCE:
                raise TradeExecutionQueuingInternalServerError(
                    message=(
                        f"Deposit would result in ${projected_equity:.2f}; the minimum "
                        f"portfolio balance is ${MINIMUM_PORTFOLIO_BALANCE:.2f}."
                    ),
                    code="TRADE_EXECUTION_QUEUE_MINIMUM_BALANCE",
                )

            transaction = self._new_transaction(
                requested_amount=float(amount), transaction_type="DEPOSIT"
            )
            return self._queue_transaction(
                portfolio_allocation=allocation,
                transaction=transaction,
                action="portfolio_deposit",
                payload={
                    "portfolio_id": portfolio_id,
                    "portfolio_owner_cognito_user_id": portfolio_owner_cognito_user_id,
                    "amount": float(amount),
                    "transaction_id": transaction.transaction_id,
                    "cognito_user_id": cognito_user_id,
                    "alpaca_account_id": alpaca_account_id,
                },
            )
        except TradeExecutionQueuingInternalServerError:
            raise
        except Exception as error:
            raise TradeExecutionQueuingInternalServerError(
                message=(
                    f"Failed to queue portfolio deposit for portfolio '{portfolio_id}', "
                    f"user '{cognito_user_id}', and account '{alpaca_account_id}': {error}"
                ),
                code="TRADE_EXECUTION_QUEUE_PORTFOLIO_DEPOSIT_FAILED",
            ) from error

    @_with_user_trade_lock
    def queue_portfolio_withdrawal(
        self,
        *,
        portfolio_id: str,
        portfolio_owner_cognito_user_id: str,
        amount: float,
        cognito_user_id: str,
        alpaca_account_id: str,
    ) -> str:
        """Validate and queue a partial model-portfolio withdrawal."""
        try:
            self._validate_common_trade_fields(
                cognito_user_id=cognito_user_id,
                alpaca_account_id=alpaca_account_id,
            )
            self._validate_required("portfolio_id", portfolio_id)
            self._validate_required(
                "portfolio_owner_cognito_user_id", portfolio_owner_cognito_user_id
            )
            self._validate_amount(amount)
            allocation = self.portfolio_allocation_repository.get_portfolio_allocation(
                cognito_user_id=cognito_user_id,
                portfolio_id=portfolio_id,
            )
            equity = self._allocation_equity(allocation)
            if amount > equity:
                raise TradeExecutionQueuingInternalServerError(
                    message=f"Withdrawal ${amount:.2f} exceeds allocation equity ${equity:.2f}.",
                    code="TRADE_EXECUTION_QUEUE_AMOUNT_EXCEEDS_EQUITY",
                )
            remaining_equity = equity - amount
            if remaining_equity < MINIMUM_PORTFOLIO_BALANCE:
                raise TradeExecutionQueuingInternalServerError(
                    message=(
                        f"Withdrawal would leave ${remaining_equity:.2f}; use withdraw-all "
                        f"or retain at least ${MINIMUM_PORTFOLIO_BALANCE:.2f}."
                    ),
                    code="TRADE_EXECUTION_QUEUE_MINIMUM_BALANCE",
                )

            transaction = self._new_transaction(
                requested_amount=float(amount), transaction_type="WITHDRAW"
            )
            return self._queue_transaction(
                portfolio_allocation=allocation,
                transaction=transaction,
                action="portfolio_withdraw",
                payload={
                    "portfolio_id": portfolio_id,
                    "portfolio_owner_cognito_user_id": portfolio_owner_cognito_user_id,
                    "amount": float(amount),
                    "transaction_id": transaction.transaction_id,
                    "cognito_user_id": cognito_user_id,
                    "alpaca_account_id": alpaca_account_id,
                },
            )
        except TradeExecutionQueuingInternalServerError:
            raise
        except Exception as error:
            raise TradeExecutionQueuingInternalServerError(
                message=(
                    f"Failed to queue portfolio withdrawal for portfolio '{portfolio_id}', "
                    f"user '{cognito_user_id}', and account '{alpaca_account_id}': {error}"
                ),
                code="TRADE_EXECUTION_QUEUE_PORTFOLIO_WITHDRAWAL_FAILED",
            ) from error

    @_with_user_trade_lock
    def queue_portfolio_withdraw_all(
        self,
        *,
        portfolio_id: str,
        portfolio_owner_cognito_user_id: str,
        cognito_user_id: str,
        alpaca_account_id: str,
    ) -> str:
        """Validate and queue liquidation of a model-portfolio allocation."""
        try:
            self._validate_common_trade_fields(
                cognito_user_id=cognito_user_id,
                alpaca_account_id=alpaca_account_id,
            )
            self._validate_required("portfolio_id", portfolio_id)
            self._validate_required(
                "portfolio_owner_cognito_user_id", portfolio_owner_cognito_user_id
            )
            allocation = self.portfolio_allocation_repository.get_portfolio_allocation(
                cognito_user_id=cognito_user_id,
                portfolio_id=portfolio_id,
            )
            if not allocation.position_history or not allocation.position_history[-1].positions:
                raise TradeExecutionQueuingInternalServerError(
                    message=f"Portfolio '{portfolio_id}' has no positions to withdraw.",
                    code="TRADE_EXECUTION_QUEUE_NO_POSITIONS",
                )

            transaction = self._new_transaction(
                requested_amount=None, transaction_type="WITHDRAW_ALL"
            )
            return self._queue_transaction(
                portfolio_allocation=allocation,
                transaction=transaction,
                action="portfolio_withdraw_all",
                payload={
                    "portfolio_id": portfolio_id,
                    "portfolio_owner_cognito_user_id": portfolio_owner_cognito_user_id,
                    "transaction_id": transaction.transaction_id,
                    "cognito_user_id": cognito_user_id,
                    "alpaca_account_id": alpaca_account_id,
                },
            )
        except TradeExecutionQueuingInternalServerError:
            raise
        except Exception as error:
            raise TradeExecutionQueuingInternalServerError(
                message=(
                    f"Failed to queue withdraw-all for portfolio '{portfolio_id}', "
                    f"user '{cognito_user_id}', and account '{alpaca_account_id}': {error}"
                ),
                code="TRADE_EXECUTION_QUEUE_PORTFOLIO_WITHDRAW_ALL_FAILED",
            ) from error

    def _stock_allocation(
        self,
        *,
        symbol: str,
        asset_id: str,
        cognito_user_id: str,
    ) -> PortfolioAllocation:
        """Load a stock allocation or create its initial in-memory aggregate."""
        if self.portfolio_allocation_repository.is_exists_portfolio_allocation_for_user(
            cognito_user_id=cognito_user_id,
            portfolio_id=asset_id,
        ):
            allocation = self.portfolio_allocation_repository.get_portfolio_allocation(
                cognito_user_id=cognito_user_id,
                portfolio_id=asset_id,
            )
            return allocation
        return PortfolioAllocation(
            portfolio_id=asset_id,
            cognito_user_id=cognito_user_id,
            position_history=[],
            transaction_history=[],
            total_cost_basis=0.0,
            portfolio_allocation_type="STOCK",
            portfolio_name=symbol.upper(),
        )

    def _queue_stock_trade(
        self,
        *,
        symbol: str,
        asset_id: str,
        amount: float,
        cognito_user_id: str,
        alpaca_account_id: str,
        trade_direction: int,
    ) -> str:
        action_name = "buy" if trade_direction == 1 else "sell"
        transaction_type = action_name.upper()
        self._validate_common_stock_fields(
            symbol=symbol,
            asset_id=asset_id,
            cognito_user_id=cognito_user_id,
            alpaca_account_id=alpaca_account_id,
        )
        self._validate_amount(amount)
        stock = self.alpaca_broker_client.get_stock_by_asset_id(asset_id=asset_id)
        if stock.symbol.upper() != symbol.upper():
            raise TradeExecutionQueuingInternalServerError(
                message=(
                    f"Stock ID '{asset_id}' belongs to '{stock.symbol}', not "
                    f"'{symbol.upper()}'."
                ),
                code="TRADE_EXECUTION_QUEUE_STOCK_MISMATCH",
            )
        if not stock.tradable or not stock.fractionable:
            raise TradeExecutionQueuingInternalServerError(
                message=f"Stock '{stock.symbol}' must be tradable and fractionable.",
                code="TRADE_EXECUTION_QUEUE_STOCK_NOT_TRADABLE",
            )
        allocation = self._stock_allocation(
            symbol=symbol,
            asset_id=asset_id,
            cognito_user_id=cognito_user_id,
        )
        current_equity = self._allocation_equity(allocation)
        current_direction = self._stock_direction(allocation)
        opens_or_increases_short = trade_direction == -1 and (
            current_direction in {None, -1} or amount > current_equity
        )
        if opens_or_increases_short and not stock.shortable:
            raise TradeExecutionQueuingInternalServerError(
                message=f"Stock '{stock.symbol}' is not shortable.",
                code="TRADE_EXECUTION_QUEUE_STOCK_NOT_SHORTABLE",
            )

        projected_equity = self._project_stock_equity(
            current_equity=current_equity,
            current_direction=current_direction,
            amount=float(amount),
            trade_direction=trade_direction,
        )
        if projected_equity < MINIMUM_STOCK_BALANCE:
            raise TradeExecutionQueuingInternalServerError(
                message=(
                    f"{transaction_type.title()} would leave ${projected_equity:.2f}; close "
                    f"the position or retain at least ${MINIMUM_STOCK_BALANCE:.2f}."
                ),
                code="TRADE_EXECUTION_QUEUE_MINIMUM_BALANCE",
            )

        transaction = self._new_transaction(
            requested_amount=float(amount),
            transaction_type=transaction_type,
        )
        return self._queue_transaction(
            portfolio_allocation=allocation,
            transaction=transaction,
            action=f"stock_{action_name}",
            payload={
                "symbol": symbol.upper(),
                "asset_id": asset_id,
                "amount": float(amount),
                "transaction_id": transaction.transaction_id,
                "cognito_user_id": cognito_user_id,
                "alpaca_account_id": alpaca_account_id,
            },
        )

    @_with_user_trade_lock
    def queue_stock_buy(
        self,
        *,
        symbol: str,
        asset_id: str,
        amount: float,
        cognito_user_id: str,
        alpaca_account_id: str,
    ) -> str:
        """Validate and queue a stock buy."""
        try:
            return self._queue_stock_trade(
                symbol=symbol,
                asset_id=asset_id,
                amount=amount,
                cognito_user_id=cognito_user_id,
                alpaca_account_id=alpaca_account_id,
                trade_direction=1,
            )
        except TradeExecutionQueuingInternalServerError:
            raise
        except Exception as error:
            raise TradeExecutionQueuingInternalServerError(
                message=(
                    f"Failed to queue stock buy for asset '{asset_id}', user "
                    f"'{cognito_user_id}', and account '{alpaca_account_id}': {error}"
                ),
                code="TRADE_EXECUTION_QUEUE_STOCK_BUY_FAILED",
            ) from error

    @_with_user_trade_lock
    def queue_stock_sell(
        self,
        *,
        symbol: str,
        asset_id: str,
        amount: float,
        cognito_user_id: str,
        alpaca_account_id: str,
    ) -> str:
        """Validate and queue a stock sell, including opening a short position."""
        try:
            return self._queue_stock_trade(
                symbol=symbol,
                asset_id=asset_id,
                amount=amount,
                cognito_user_id=cognito_user_id,
                alpaca_account_id=alpaca_account_id,
                trade_direction=-1,
            )
        except TradeExecutionQueuingInternalServerError:
            raise
        except Exception as error:
            raise TradeExecutionQueuingInternalServerError(
                message=(
                    f"Failed to queue stock sell for asset '{asset_id}', user "
                    f"'{cognito_user_id}', and account '{alpaca_account_id}': {error}"
                ),
                code="TRADE_EXECUTION_QUEUE_STOCK_SELL_FAILED",
            ) from error

    @_with_user_trade_lock
    def queue_stock_close(
        self,
        *,
        symbol: str,
        asset_id: str,
        cognito_user_id: str,
        alpaca_account_id: str,
    ) -> str:
        """Validate and queue a full stock-position close."""
        try:
            self._validate_common_stock_fields(
                symbol=symbol,
                asset_id=asset_id,
                cognito_user_id=cognito_user_id,
                alpaca_account_id=alpaca_account_id,
            )
            allocation = self.portfolio_allocation_repository.get_portfolio_allocation(
                cognito_user_id=cognito_user_id,
                portfolio_id=asset_id,
            )
            if not allocation.position_history or not allocation.position_history[-1].positions:
                raise TradeExecutionQueuingInternalServerError(
                    message=f"Stock allocation '{asset_id}' has no position to close.",
                    code="TRADE_EXECUTION_QUEUE_NO_POSITIONS",
                )

            transaction = self._new_transaction(
                requested_amount=None, transaction_type="CLOSE"
            )
            return self._queue_transaction(
                portfolio_allocation=allocation,
                transaction=transaction,
                action="stock_close",
                payload={
                    "symbol": symbol.upper(),
                    "asset_id": asset_id,
                    "transaction_id": transaction.transaction_id,
                    "cognito_user_id": cognito_user_id,
                    "alpaca_account_id": alpaca_account_id,
                },
            )
        except TradeExecutionQueuingInternalServerError:
            raise
        except Exception as error:
            raise TradeExecutionQueuingInternalServerError(
                message=(
                    f"Failed to queue stock close for asset '{asset_id}', user "
                    f"'{cognito_user_id}', and account '{alpaca_account_id}': {error}"
                ),
                code="TRADE_EXECUTION_QUEUE_STOCK_CLOSE_FAILED",
            ) from error
