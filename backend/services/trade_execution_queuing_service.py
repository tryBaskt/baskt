"""Service for queueing trade-execution work onto SQS."""

from __future__ import annotations

import json
from typing import Any, Dict

from botocore.exceptions import BotoCoreError, ClientError


class TradeExecutionQueuingServiceError(Exception):
    """Raised when trade-execution queue operations fail."""

    def __init__(
        self,
        message: str,
        code: str = "TRADE_EXECUTION_QUEUING_SERVICE_ERROR",
    ) -> None:
        """
        Initialize a trade execution queuing service exception.

        Args:
            message: Human-readable error details.
            code: Stable error code identifying the failure.

        Returns:
            None.
        """
        super().__init__(message)
        self.code = code


class TradeExecutionQueuingService:
    """Queue trade-execution actions for asynchronous Lambda processing."""

    def __init__(self, sqs_client: Any, queue_url: str) -> None:
        """
        Initialize the trade execution queuing service.

        Args:
            sqs_client: Boto3 SQS client used to send trade messages.
            queue_url: URL of the trade execution SQS queue.

        Returns:
            None.

        Raises:
            TradeExecutionQueuingServiceError: If queue_url is empty.
        """
        if not queue_url:
            raise TradeExecutionQueuingServiceError(
                message="Trade execution queue URL is required",
                code="TRADE_EXECUTION_QUEUE_URL_REQUIRED",
            )
        self.sqs_client = sqs_client
        self.queue_url = queue_url

    def _send_message(self, *, action: str, payload: Dict[str, Any]) -> str:
        """
        Send one trade-execution action message to SQS.

        Args:
            action: Action name understood by the trade execution Lambda
                worker.
            payload: JSON-serializable action payload.

        Returns:
            str: SQS message id.

        Raises:
            TradeExecutionQueuingServiceError: If SQS rejects the message or
            the payload cannot be serialized.
        """
        try:
            response = self.sqs_client.send_message(
                QueueUrl=self.queue_url,
                MessageBody=json.dumps(
                    {
                        "action": action,
                        "payload": payload,
                    },
                    separators=(",", ":"),
                ),
            )
            return str(response["MessageId"])
        except (TypeError, ValueError) as error:
            raise TradeExecutionQueuingServiceError(
                message=f"Failed to serialize trade execution queue message: {error}",
                code="TRADE_EXECUTION_QUEUE_MESSAGE_SERIALIZATION_FAILED",
            ) from error
        except (BotoCoreError, ClientError) as error:
            raise TradeExecutionQueuingServiceError(
                message=f"Failed to send trade execution queue message: {error}",
                code="TRADE_EXECUTION_QUEUE_SEND_FAILED",
            ) from error

    def queue_portfolio_deposit(
        self,
        *,
        portfolio_id: str,
        portfolio_owner_cognito_user_id: str,
        amount: float,
        cognito_user_id: str,
        alpaca_account_id: str,
    ) -> str:
        """
        Queue a deposit into a model portfolio allocation.

        Args:
            portfolio_id: Model portfolio identifier.
            portfolio_owner_cognito_user_id: Cognito user id of the portfolio
                owner.
            amount: Positive dollar amount to deposit.
            cognito_user_id: Cognito user id of the investing user.
            alpaca_account_id: Alpaca account id for the investing user.

        Returns:
            str: SQS message id.

        Raises:
            TradeExecutionQueuingServiceError: If required fields are missing,
            amount is not positive, payload serialization fails, or SQS fails.
        """
        self._validate_common_trade_fields(
            cognito_user_id=cognito_user_id,
            alpaca_account_id=alpaca_account_id,
        )
        self._validate_required("portfolio_id", portfolio_id)
        self._validate_required(
            "portfolio_owner_cognito_user_id",
            portfolio_owner_cognito_user_id,
        )
        self._validate_amount(amount)
        return self._send_message(
            action="portfolio_deposit",
            payload={
                "portfolio_id": portfolio_id,
                "portfolio_owner_cognito_user_id": portfolio_owner_cognito_user_id,
                "amount": amount,
                "cognito_user_id": cognito_user_id,
                "alpaca_account_id": alpaca_account_id,
            },
        )

    def queue_portfolio_withdrawal(
        self,
        *,
        portfolio_id: str,
        portfolio_owner_cognito_user_id: str,
        amount: float,
        cognito_user_id: str,
        alpaca_account_id: str,
    ) -> str:
        """
        Queue a withdrawal from a model portfolio allocation.

        Args:
            portfolio_id: Model portfolio identifier.
            portfolio_owner_cognito_user_id: Cognito user id of the portfolio
                owner.
            amount: Positive dollar amount to withdraw.
            cognito_user_id: Cognito user id of the investing user.
            alpaca_account_id: Alpaca account id for the investing user.

        Returns:
            str: SQS message id.

        Raises:
            TradeExecutionQueuingServiceError: If required fields are missing,
            amount is not positive, payload serialization fails, or SQS fails.
        """
        self._validate_common_trade_fields(
            cognito_user_id=cognito_user_id,
            alpaca_account_id=alpaca_account_id,
        )
        self._validate_required("portfolio_id", portfolio_id)
        self._validate_required(
            "portfolio_owner_cognito_user_id",
            portfolio_owner_cognito_user_id,
        )
        self._validate_amount(amount)
        return self._send_message(
            action="portfolio_withdraw",
            payload={
                "portfolio_id": portfolio_id,
                "portfolio_owner_cognito_user_id": portfolio_owner_cognito_user_id,
                "amount": amount,
                "cognito_user_id": cognito_user_id,
                "alpaca_account_id": alpaca_account_id,
            },
        )

    def queue_portfolio_withdraw_all(
        self,
        *,
        portfolio_id: str,
        portfolio_owner_cognito_user_id: str,
        cognito_user_id: str,
        alpaca_account_id: str,
    ) -> str:
        """
        Queue a full withdrawal from a model portfolio allocation.

        Args:
            portfolio_id: Model portfolio identifier.
            portfolio_owner_cognito_user_id: Cognito user id of the portfolio
                owner.
            cognito_user_id: Cognito user id of the investing user.
            alpaca_account_id: Alpaca account id for the investing user.

        Returns:
            str: SQS message id.

        Raises:
            TradeExecutionQueuingServiceError: If required fields are missing,
            payload serialization fails, or SQS fails.
        """
        self._validate_common_trade_fields(
            cognito_user_id=cognito_user_id,
            alpaca_account_id=alpaca_account_id,
        )
        self._validate_required("portfolio_id", portfolio_id)
        self._validate_required(
            "portfolio_owner_cognito_user_id",
            portfolio_owner_cognito_user_id,
        )
        return self._send_message(
            action="portfolio_withdraw_all",
            payload={
                "portfolio_id": portfolio_id,
                "portfolio_owner_cognito_user_id": portfolio_owner_cognito_user_id,
                "cognito_user_id": cognito_user_id,
                "alpaca_account_id": alpaca_account_id,
            },
        )

    def queue_stock_buy(
        self,
        *,
        symbol: str,
        asset_id: str,
        amount: float,
        cognito_user_id: str,
        alpaca_account_id: str,
    ) -> str:
        """
        Queue a stock buy.

        Args:
            symbol: Stock ticker symbol.
            asset_id: Asset identifier used as the allocation id.
            amount: Positive dollar amount to buy.
            cognito_user_id: Cognito user id of the trading user.
            alpaca_account_id: Alpaca account id for the trading user.

        Returns:
            str: SQS message id.

        Raises:
            TradeExecutionQueuingServiceError: If required fields are missing,
            amount is not positive, payload serialization fails, or SQS fails.
        """
        self._validate_common_stock_fields(
            symbol=symbol,
            asset_id=asset_id,
            cognito_user_id=cognito_user_id,
            alpaca_account_id=alpaca_account_id,
        )
        self._validate_amount(amount)
        return self._send_message(
            action="stock_buy",
            payload={
                "symbol": symbol.upper(),
                "asset_id": asset_id,
                "amount": amount,
                "cognito_user_id": cognito_user_id,
                "alpaca_account_id": alpaca_account_id,
            },
        )

    def queue_stock_sell(
        self,
        *,
        symbol: str,
        asset_id: str,
        amount: float,
        cognito_user_id: str,
        alpaca_account_id: str,
    ) -> str:
        """
        Queue a stock sell.

        Args:
            symbol: Stock ticker symbol.
            asset_id: Asset identifier used as the allocation id.
            amount: Positive dollar amount to sell.
            cognito_user_id: Cognito user id of the trading user.
            alpaca_account_id: Alpaca account id for the trading user.

        Returns:
            str: SQS message id.

        Raises:
            TradeExecutionQueuingServiceError: If required fields are missing,
            amount is not positive, payload serialization fails, or SQS fails.
        """
        self._validate_common_stock_fields(
            symbol=symbol,
            asset_id=asset_id,
            cognito_user_id=cognito_user_id,
            alpaca_account_id=alpaca_account_id,
        )
        self._validate_amount(amount)
        return self._send_message(
            action="stock_sell",
            payload={
                "symbol": symbol.upper(),
                "asset_id": asset_id,
                "amount": amount,
                "cognito_user_id": cognito_user_id,
                "alpaca_account_id": alpaca_account_id,
            },
        )

    def queue_stock_close(
        self,
        *,
        symbol: str,
        asset_id: str,
        cognito_user_id: str,
        alpaca_account_id: str,
    ) -> str:
        """
        Queue a full close of a stock allocation.

        Args:
            symbol: Stock ticker symbol.
            asset_id: Asset identifier used as the allocation id.
            cognito_user_id: Cognito user id of the trading user.
            alpaca_account_id: Alpaca account id for the trading user.

        Returns:
            str: SQS message id.

        Raises:
            TradeExecutionQueuingServiceError: If required fields are missing,
            payload serialization fails, or SQS fails.
        """
        self._validate_common_stock_fields(
            symbol=symbol,
            asset_id=asset_id,
            cognito_user_id=cognito_user_id,
            alpaca_account_id=alpaca_account_id,
        )
        return self._send_message(
            action="stock_close",
            payload={
                "symbol": symbol.upper(),
                "asset_id": asset_id,
                "cognito_user_id": cognito_user_id,
                "alpaca_account_id": alpaca_account_id,
            },
        )

    def _validate_common_stock_fields(
        self,
        *,
        symbol: str,
        asset_id: str,
        cognito_user_id: str,
        alpaca_account_id: str,
    ) -> None:
        """Validate fields common to stock queue messages."""
        self._validate_required("symbol", symbol)
        self._validate_required("asset_id", asset_id)
        self._validate_common_trade_fields(
            cognito_user_id=cognito_user_id,
            alpaca_account_id=alpaca_account_id,
        )

    def _validate_common_trade_fields(
        self,
        *,
        cognito_user_id: str,
        alpaca_account_id: str,
    ) -> None:
        """Validate fields common to all queue messages."""
        self._validate_required("cognito_user_id", cognito_user_id)
        self._validate_required("alpaca_account_id", alpaca_account_id)

    def _validate_required(self, field_name: str, value: str) -> None:
        """Raise when a required string field is empty."""
        if not isinstance(value, str) or not value.strip():
            raise TradeExecutionQueuingServiceError(
                message=f"Trade execution queue field '{field_name}' is required",
                code="TRADE_EXECUTION_QUEUE_FIELD_REQUIRED",
            )

    def _validate_amount(self, amount: float) -> None:
        """Raise when an amount is not positive."""
        if amount <= 0:
            raise TradeExecutionQueuingServiceError(
                message="Trade execution queue amount must be positive",
                code="TRADE_EXECUTION_QUEUE_AMOUNT_INVALID",
            )
