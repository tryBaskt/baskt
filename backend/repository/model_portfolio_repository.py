# backend/repository/model_portfolio_repository.py

# Python imports
from __future__ import annotations
from datetime import datetime, timezone
from decimal import Decimal
from typing import List, Dict, Optional, Tuple
from uuid import uuid4
import time

# AWS imports
from boto3.dynamodb.conditions import Key

# Baskt imports 
from domain.model_portfolio_domain import ModelPortfolio, ModelPortfolioSnapshot, ModelPortfolioPosition
from repository.model_portfolio_update_lock_repository import (
    ModelPortfolioUpdateLockBadGatewayError,
    ModelPortfolioUpdateLockRepository,
    ModelPortfolioUpdateLockInternalServerError,
)
from repository.model_portfolio_follower_repository import (
    ModelPortfolioFollowerInternalServerError,
    ModelPortfolioFollowerNotFoundError,
    ModelPortfolioFollowerRepository,
)
from repository.model_portfolio_access_repository import (
    ModelPortfolioAccessRepository,
    ModelPortfolioAccessRepositoryError,
)
from clients.dynamodb_client import (
    DynamoDBClient,
    DynamoDBClientError,
    dataclass_to_dynamodb_item,
)
from clients.alpaca_broker_client import AlpacaBrokerClient, AlpacaBrokerClientError
from core.timeutils import to_utc_from_iso
from schema.model_portfolio_schema import ModelPortfolioPositionRequest

LOCK_LEASE_SECONDS = 30
READ_LOCK_POLL_SECONDS = 0.25


def _parse_model_portfolio_position(item: Dict) -> ModelPortfolioPosition:
    """Convert a stored position map into its domain model."""
    return ModelPortfolioPosition(
        **{
            **item,
            "symbol": str(item["symbol"]),
            "target_weight": float(item["target_weight"]),
            "direction": int(item["direction"]),
            "leverage": float(item["leverage"]),
            "model_filled_quantity": float(item["model_filled_quantity"]),
            "model_filled_avg_price": float(item["model_filled_avg_price"]),
        }
    )

class ModelPortfolioInternalServerError(Exception):
    def __init__(self, message: str, code: str = "MODEL_PORTFOLIO_INTERNAL_SERVER_ERROR") -> None:
        """
        Initialize a model portfolio repository exception.

        Args:
            message: Human-readable error details.
            code: Stable application error code identifying the failed operation.

        Returns:
            None.

        Raises:
            No exceptions are intentionally raised by this method.
        """
        super().__init__(message)
        self.code = code


class ModelPortfolioBadGatewayError(ModelPortfolioInternalServerError):
    def __init__(
        self,
        source: str,
        operation: str,
        *,
        portfolio_id: Optional[str] = None,
        owner_cognito_user_id: Optional[str] = None,
        cause: Optional[Exception] = None,
    ) -> None:
        """
        Initialize an upstream dependency failure for model portfolio operations.

        Args:
            source: Upstream dependency that failed, such as "DynamoDB" or
                "Alpaca".
            operation: Description of the operation that failed.
            portfolio_id: Optional model portfolio ID involved in the failure.
            owner_cognito_user_id: Optional owner Cognito user ID involved in
                the failure.
            cause: Optional upstream exception that caused the failure.

        Returns:
            None.

        Raises:
            No exceptions are intentionally raised by this method.
        """
        context = []
        if portfolio_id:
            context.append(f"model portfolio '{portfolio_id}'")
        if owner_cognito_user_id:
            context.append(f"owner '{owner_cognito_user_id}'")

        message = f"Upstream {source} client failed while {operation}"
        if context:
            message = f"{message} for {', '.join(context)}"
        if cause:
            message = f"{message}: {cause}"

        super().__init__(
            message=message,
            code="MODEL_PORTFOLIO_UPSTREAM_ERROR",
        )

class ModelPortfolioNotFoundError(ModelPortfolioInternalServerError):
    def __init__(self, portfolio_id: str) -> None:
        """
        Initialize a missing model portfolio exception.

        Args:
            portfolio_id: Model portfolio ID that was not found.

        Returns:
            None.

        Raises:
            No exceptions are intentionally raised by this method.
        """
        super().__init__(
            message=f"Model portfolio '{portfolio_id}' not found.",
            code="MODEL_PORTFOLIO_NOT_FOUND_ERROR",
        )

class ModelPortfolioUnprocessableEntityError(ModelPortfolioInternalServerError):
    def __init__(
        self,
        operation: str,
        *,
        portfolio_id: Optional[str] = None,
        cause: Optional[Exception] = None,
    ) -> None:
        """
        Initialize an invalid stored model portfolio data exception.

        Args:
            operation: Description of the parse or processing operation that
                failed.
            portfolio_id: Optional model portfolio ID involved in the failure.
            cause: Optional exception that caused the processing failure.

        Returns:
            None.

        Raises:
            No exceptions are intentionally raised by this method.
        """
        message = f"Failed to {operation}"
        if portfolio_id:
            message = f"{message} for model portfolio '{portfolio_id}'"
        if cause:
            message = f"{message}: {cause}"

        super().__init__(
            message=message,
            code="MODEL_PORTFOLIO_ENTITY_UNPROCESSABLE_ERROR",
        )


class ModelPortfolioInvalidPositionRequest(ModelPortfolioUnprocessableEntityError):
    def __init__(
        self,
        *,
        attribute: str,
        allowed: str,
        actual: object,
    ) -> None:
        super().__init__(
            operation=(
                "validating position request: "
                f"{attribute} must be {allowed}; got {actual!r}"
            ),
        )


class ModelPortfolioTooManyRequestsError(ModelPortfolioInternalServerError):
    def __init__(self, retry_after_seconds: int) -> None:
        """
        Initialize a model portfolio update cooldown exception.

        Args:
            retry_after_seconds: Number of seconds the caller should wait
                before retrying the update.

        Returns:
            None.

        Raises:
            No exceptions are intentionally raised by this method.
        """
        super().__init__(
            message=f"Updates allowed once per minute. Retry after {retry_after_seconds} seconds.",
            code="MODEL_PORTFOLIO_TOO_MANY_UPDATES_ERROR",
        )

class ModelPortfolioLockedError(ModelPortfolioInternalServerError):
    def __init__(
        self,
        portfolio_id: str,
        operation: str,
        *,
        cause: Optional[Exception] = None,
    ) -> None:
        """
        Initialize a model portfolio update lock exception.

        Args:
            portfolio_id: Model portfolio ID involved in the lock failure.
            operation: Lock operation or state that failed.
            cause: Optional lock repository exception that caused the failure.

        Returns:
            None.

        Raises:
            No exceptions are intentionally raised by this method.
        """
        message = f"Failed to {operation} for model portfolio '{portfolio_id}'"
        if cause:
            message = f"{message}: {cause}"

        super().__init__(
            message=message,
            code="MODEL_PORTFOLIO_UPDATE_LOCK_ERROR",
        )


class ModelPortfolioRepository:
    """
    Repository for managing model portfolios in DynamoDB.
    """

    def __init__(
        self,
        dynamodb_client: DynamoDBClient,
        alpaca_broker_client: AlpacaBrokerClient,
        model_portfolio_update_lock_repository: ModelPortfolioUpdateLockRepository,
        model_portfolio_follower_repository: ModelPortfolioFollowerRepository,
        model_portfolio_access_repository: ModelPortfolioAccessRepository
    ) -> None:
        """
        Initialize model portfolio repository dependencies.

        Args:
            dynamodb_client: DynamoDB client wrapper for model portfolio
                persistence.
            alpaca_broker_client: Alpaca broker client used for latest market
                prices.
            model_portfolio_update_lock_repository: Repository used to
                coordinate model portfolio update locks.
            model_portfolio_follower_repository: Repository used to clean up
                follower records when deleting model portfolios.

        Returns:
            None.

        Raises:
            No exceptions are intentionally raised by this method.
        """
        self.dynamodb = dynamodb_client
        self.alpaca_broker_client = alpaca_broker_client
        self.model_portfolio_update_lock_repository = model_portfolio_update_lock_repository
        self.model_portfolio_follower_repository = model_portfolio_follower_repository
        self.model_portfolio_access_repository = model_portfolio_access_repository

    @staticmethod
    def _validate_position_request(
        positions_request: List[ModelPortfolioPositionRequest],
    ) -> None:
        total_weight = 0.0
        for position_request in positions_request:
            if not isinstance(position_request.symbol, str):
                raise ModelPortfolioInvalidPositionRequest(
                    attribute="symbol",
                    allowed="a non-empty string",
                    actual=position_request.symbol,
                )

            symbol = position_request.symbol.strip()
            if not symbol:
                raise ModelPortfolioInvalidPositionRequest(
                    attribute="symbol",
                    allowed="a non-empty string",
                    actual=position_request.symbol,
                )

            try:
                direction = int(position_request.direction)
            except (TypeError, ValueError) as error:
                raise ModelPortfolioInvalidPositionRequest(
                    attribute=f"direction for symbol '{symbol}'",
                    allowed="1 or -1",
                    actual=position_request.direction,
                ) from error

            if direction not in (1, -1):
                raise ModelPortfolioInvalidPositionRequest(
                    attribute=f"direction for symbol '{symbol}'",
                    allowed="1 or -1",
                    actual=position_request.direction,
                )

            try:
                leverage = float(position_request.leverage)
            except (TypeError, ValueError) as error:
                raise ModelPortfolioInvalidPositionRequest(
                    attribute=f"leverage for symbol '{symbol}'",
                    allowed="1.0",
                    actual=position_request.leverage,
                ) from error

            if leverage != 1.0:
                raise ModelPortfolioInvalidPositionRequest(
                    attribute=f"leverage for symbol '{symbol}'",
                    allowed="1.0",
                    actual=position_request.leverage,
                )

            try:
                total_weight += float(position_request.target_weight)
            except (TypeError, ValueError) as error:
                raise ModelPortfolioInvalidPositionRequest(
                    attribute=f"target_weight for symbol '{symbol}'",
                    allowed="a number that contributes to a total of 1.0",
                    actual=position_request.target_weight,
                ) from error

        if abs(total_weight - 1.0) > 1e-9:
            raise ModelPortfolioInvalidPositionRequest(
                attribute="total target_weight",
                allowed="1.0",
                actual=total_weight,
            )

    def _wait_until_portfolio_update_lock_is_released(
        self,
        portfolio_id: str,
        wait_seconds: float = LOCK_LEASE_SECONDS,
    ) -> None:
        """
        Block reads while an active update lock exists for the portfolio.

        Args:
            portfolio_id: Model portfolio ID to wait on before reading or
                writing.
            wait_seconds: Maximum number of seconds to wait for the active lock
                to be released or expire.

        Returns:
            None.

        Raises:
            ModelPortfolioBadGatewayError: If DynamoDB fails while checking
            the portfolio lock.
            ModelPortfolioLockedError: If another update lock repository error
            occurs while checking the portfolio lock, or if the active lock is
            still held after wait_seconds.
        """
        deadline = time.monotonic() + max(0.0, float(wait_seconds))
        while True:
            try:
                lock = self.model_portfolio_update_lock_repository.get_lock(portfolio_id=portfolio_id)
            except ModelPortfolioUpdateLockBadGatewayError as e:
                raise ModelPortfolioBadGatewayError(
                    source="DynamoDB",
                    operation="checking model portfolio update lock",
                    portfolio_id=portfolio_id,
                    cause=e,
                ) from e
            except ModelPortfolioUpdateLockInternalServerError as e:
                raise ModelPortfolioLockedError(
                    portfolio_id=portfolio_id,
                    operation="check update lock",
                    cause=e,
                ) from e
            if not lock:
                return

            expires_at = int(lock.get("expires_at"))
            now = int(time.time())
            if expires_at <= now:
                return

            remaining_wait_seconds = deadline - time.monotonic()
            if remaining_wait_seconds <= 0:
                raise ModelPortfolioLockedError(
                    portfolio_id=portfolio_id,
                    operation="wait for update lock because portfolio is locked",
                )

            sleep_seconds = min(
                READ_LOCK_POLL_SECONDS,
                remaining_wait_seconds,
                max(0.0, float(expires_at - now)),
            )
            time.sleep(sleep_seconds)

    def get_portfolio_cognito_owner_id_by_portfolio(self, portfolio_id: str) -> str:
        """
        Retrieve the Cognito user ID of the owner of a model portfolio.

        Args:
            portfolio_id: Identifier of the model portfolio.

        Returns:
            str: Cognito user ID of the portfolio owner.

        Raises:
            ModelPortfolioBadGatewayError: If DynamoDB fails while reading the
            portfolio owner.
            ModelPortfolioNotFoundError: If the model portfolio does not exist.
            ModelPortfolioUnprocessableEntityError: If the portfolio record does
            not contain a valid owner Cognito user ID.
        """
        try:
            item = self.dynamodb.get_item(
                key={"portfolio_id": portfolio_id},
                projection_expression="portfolio_owner_cognito_user_id"
            )
        except DynamoDBClientError as e:
            raise ModelPortfolioBadGatewayError(
                source="DynamoDB",
                operation="get_portfolio_cognito_owner",
                portfolio_id=portfolio_id,
                cause=e,
            ) from e
        if not item:
            raise ModelPortfolioNotFoundError(
                portfolio_id=portfolio_id
            )

        try:
            portfolio_owner_cognito_user_id = item["portfolio_owner_cognito_user_id"]
            return portfolio_owner_cognito_user_id
        except Exception as e:
            raise ModelPortfolioUnprocessableEntityError(
                operation="failed to parse portfolio owner cognito user id",
                portfolio_id=portfolio_id,
                cause=e,
            ) from e


    def get_position_history(self, portfolio_id: str) -> List[ModelPortfolioSnapshot]:
        """
        Retrieve all historical snapshots for a model portfolio.

        Args:
            portfolio_id: Identifier of the portfolio.

        Returns:
            List[ModelPortfolioSnapshot]: Historical portfolio snapshots in
            stored order.

        Raises:
            ModelPortfolioLockedError: If lock state cannot be checked.
            ModelPortfolioBadGatewayError: If DynamoDB fails while loading
            position history.
            ModelPortfolioNotFoundError: If the model portfolio does not exist.
            ModelPortfolioUnprocessableEntityError: If position_history is
            missing or its stored contents cannot be parsed.
        """

        # Wait for update lock to release (if applicable)
        self._wait_until_portfolio_update_lock_is_released(portfolio_id=portfolio_id)

        # Only fetch position_history to reduce bandwidth
        try:
            item = self.dynamodb.get_item(
                key={"portfolio_id": portfolio_id},
                projection_expression="portfolio_id, position_history"
            )
        except DynamoDBClientError as e:
            raise ModelPortfolioBadGatewayError(
                source="DynamoDB",
                operation="loading position history",
                portfolio_id=portfolio_id,
                cause=e,
            ) from e

        # Ensure item is not None and has portfolio_history
        if not item:
            raise ModelPortfolioNotFoundError(
                portfolio_id=portfolio_id
            )
        if "position_history" not in item:
            raise ModelPortfolioUnprocessableEntityError(
                operation="get_position_history",
                portfolio_id=portfolio_id,
                cause=Exception(f"Position history not in model portfolio '{portfolio_id}'")
            )

        # Create position history
        result = []
        position_history = item["position_history"]
        for snap in position_history:

            try:
                positions = [
                    _parse_model_portfolio_position(position_item)
                    for position_item in snap["positions"]
                ]

                timestamp = to_utc_from_iso(snap["timestamp"])
                snapshot_id = str(snap["snapshot_id"])

            except Exception as e:
                raise ModelPortfolioUnprocessableEntityError(
                    operation="parse position history",
                    portfolio_id=portfolio_id,
                    cause=e,
                ) from e
            
            result.append(
                ModelPortfolioSnapshot(
                    positions=positions,
                    timestamp=timestamp,
                    snapshot_id=snapshot_id,
                )
            )
        
        return result

    def get_n_last_model_portfolio_snapshots(self, portfolio_id: str, n: int) -> List[ModelPortfolioSnapshot]:
        """
        Retrieve the most recent n snapshots for a model portfolio.

        Args:
            portfolio_id: Identifier of the portfolio.
            n: Number of recent snapshots to return.

        Returns:
            List[ModelPortfolioSnapshot]: Last n snapshots in chronological
            order.

        Raises:
            ModelPortfolioLockedError: If lock state cannot be checked.
            ValueError: If n is less than or equal to zero or greater than the
            number of stored snapshots.
            ModelPortfolioBadGatewayError: If DynamoDB fails while loading
            position history.
            ModelPortfolioNotFoundError: If the model portfolio does not exist.
            ModelPortfolioUnprocessableEntityError: If position history is
            missing or its stored contents cannot be parsed.
        """

        # Wait for update lock to release (if applicable)
        self._wait_until_portfolio_update_lock_is_released(portfolio_id=portfolio_id)

        # n is negative
        if n <= 0:
            raise ValueError(f"n argument '{n}' must be greater than 0.")

        # Get the last n snapshots
        position_history = self.get_position_history(portfolio_id=portfolio_id)
        if n > len(position_history):
            raise ValueError(f"n argument '{n}' equal to or less than number of snapshots '{len(position_history)}'")
        last_n_snapshots = position_history[-n:]
        
        return last_n_snapshots
    

    def calculate_positions_current_weight(
        self,
        model_portfolio_snapshot: ModelPortfolioSnapshot,
    ) -> tuple[Dict[str, float], float, Dict[str, float]]:
        """
        Calculate current normalized weights from latest market prices.

        Args:
            model_portfolio_snapshot: Snapshot containing modeled position quantities.

        Returns:
            tuple[Dict[str, float], float, Dict[str, float]]: Current
            normalized weights by symbol, total portfolio value, and latest
            quotes. When total value
            is zero, returns equivalent zero-weight values with total value and
            quotes.

        Raises:
            ModelPortfolioBadGatewayError: If Alpaca fails while fetching
            latest prices.
            KeyError: If a latest price is missing for a symbol in the
            snapshot.
        """

        # Get current positions latest prices
        curr_positions = model_portfolio_snapshot.positions
        symbols = [pos.symbol for pos in curr_positions]
        try:
            quotes = self.alpaca_broker_client.get_latest_price(symbols=symbols)
        except AlpacaBrokerClientError as e:
            raise ModelPortfolioBadGatewayError(
                source="Alpaca",
                operation="fetching latest prices to calculate current position weights",
                cause=e,
            ) from e

        # Create current position weight dict
        position_values: Dict[str, float] = {}
        for position in curr_positions:
            current_price = quotes[position.symbol]
            filled_quantity = position.model_filled_quantity
            entry_price = position.model_filled_avg_price

            # Long: value rises with price; short: value falls with price.
            position_values[position.symbol] = filled_quantity * (
                entry_price + position.direction * (current_price - entry_price)
            )

        # Total value
        total_value = sum(position_values.values())
        if total_value == 0:
            return {symbol: 0.0 for symbol in position_values}, 0.0, quotes


        return (
            {
                symbol: value / total_value
                for symbol, value in position_values.items()
            },
            total_value, 
            quotes
        )


    def create_model_portfolio(self, portfolio_owner_cognito_user_id: str, portfolio_name: str, positions_request: List[ModelPortfolioPositionRequest], visibility: str, creation_time: Optional[datetime] = None, description: Optional[str] = None) -> str:
        """
        Create and persist a new model portfolio with an initial snapshot.

        Args:
            portfolio_owner_cognito_user_id: Identifier of the portfolio owner.
            portfolio_name: Display name for the portfolio.
            positions_request: Initial target positions for the first snapshot.
            creation_time: Optional creation timestamp; defaults to now in UTC.
            description: Optional free-text description.

        Returns:
            str: Generated model portfolio ID.

        Raises:
            ModelPortfolioBadGatewayError: If Alpaca fails while fetching latest
            prices or DynamoDB fails while persisting the portfolio.
            ModelPortfolioUnprocessableEntityError: If the initial portfolio
            snapshot or DynamoDB item cannot be created.
        """

        self._validate_position_request(positions_request)

        # Generate new portfolio id
        portfolio_id = str(uuid4())

        # Generate creation_time
        if not creation_time:
            creation_time = datetime.now(timezone.utc)

        # Get model_filled_avg_price and model_filled_quantity
        symbols = [pos.symbol for pos in positions_request]
        try:
            quotes = self.alpaca_broker_client.get_latest_price(symbols=symbols)
        except AlpacaBrokerClientError as e:
            raise ModelPortfolioBadGatewayError(
                source="Alpaca",
                operation="fetching latest prices during creation",
                portfolio_id=portfolio_id,
                cause=e,
            ) from e
        
        try:
            # Create model portfolio positions
            model_portfolio_positions: List[ModelPortfolioPosition] = []
            model_allocation = 10000.00
            for position_request in positions_request:
                model_portfolio_positions.append(
                    ModelPortfolioPosition(
                        symbol=position_request.symbol,
                        target_weight=position_request.target_weight,
                        direction=position_request.direction,
                        leverage=position_request.leverage,
                        model_filled_avg_price=quotes[position_request.symbol],
                        model_filled_quantity=(position_request.target_weight * model_allocation) / quotes[position_request.symbol]    
                    )
                )

            # Create portfolio object
            snapshot = ModelPortfolioSnapshot(
                positions=model_portfolio_positions,
                timestamp=creation_time,
                snapshot_id=str(uuid4())
            )
            portfolio = ModelPortfolio(
                portfolio_id=portfolio_id,
                portfolio_owner_cognito_user_id=portfolio_owner_cognito_user_id,
                portfolio_name=portfolio_name,
                position_history=[snapshot],
                created_at=creation_time,
                updated_at=creation_time,
                description=description,
                visibility=visibility
            )

            # Write model portfolio object to dynamodb
            item = dataclass_to_dynamodb_item(portfolio)
        except Exception as e:
            raise ModelPortfolioUnprocessableEntityError(
                operation="creating new model portfolio",
                portfolio_id=portfolio_id,
                cause=e,
            ) from e

        try:
            self.dynamodb.put_item(item)
        except DynamoDBClientError as e:
            raise ModelPortfolioBadGatewayError(
                source="DynamoDB",
                operation="persisting during creation",
                portfolio_id=portfolio_id,
                cause=e,
            ) from e
        return portfolio_id


    def update_model_portfolio(self, portfolio_id: str, positions_request: List[ModelPortfolioPositionRequest], visibility: str, update_time: Optional[datetime] = None, description: Optional[str] = None) -> Tuple[bool, str | None]:
        """
        Append a new snapshot and persist updates to an existing model portfolio.

        Args:
            portfolio_id: Identifier of the portfolio.
            positions_request: Updated positions to store as a new snapshot.
            update_time: Optional update timestamp; defaults to now in UTC.
            description: Optional updated free-text description.

        Returns:
            Tuple[bool, Optional[str]]: A flag indicating whether anything was
            updated and the new snapshot ID when positions changed. The
            snapshot ID is None for description-only updates and no-op calls.

        Raises:
            ModelPortfolioNotFoundError: If the model portfolio does not exist.
            ModelPortfolioUnprocessableEntityError: If target weights do not
            total 100%.
            ModelPortfolioLockedError: If the portfolio lock cannot be acquired,
            is already held, or cannot be released.
            ModelPortfolioTooManyRequestsError: If the portfolio was updated
            less than one minute ago.
            ModelPortfolioBadGatewayError: If Alpaca fails while fetching latest
            prices or DynamoDB fails while persisting the update.
            ModelPortfolioUnprocessableEntityError: If the updated portfolio
            snapshot or DynamoDB item cannot be created.
        """
        self._validate_position_request(positions_request)

        # Ensure portfolio does exist
        existing: ModelPortfolio = self.get_model_portfolio(portfolio_id=portfolio_id, wait_seconds=0)
        if not existing:
            return False, None
        
        curr_model_portfolio_snapshot = existing.position_history[-1]
        curr_model_portfolio_positions = sorted(
            curr_model_portfolio_snapshot.positions,
            key=lambda position: position.symbol,
        )
        curr_model_portfolio_description = existing.description
        curr_model_portfolio_visibility = existing.visibility
        new_positions = sorted(
            positions_request,
            key=lambda position: position.symbol
        )
        positions_unchanged = (
            len(curr_model_portfolio_positions) == len(new_positions)
            and all(
                current_position.symbol == new_position.symbol
                and current_position.target_weight == new_position.target_weight
                and current_position.direction == new_position.direction
                and current_position.leverage == new_position.leverage
                for current_position, new_position in zip(
                    curr_model_portfolio_positions,
                    new_positions,
                )
            )
        )
        description_unchanged = curr_model_portfolio_description == description

        visibility_unchanged = curr_model_portfolio_visibility == visibility

        if (
            description_unchanged and 
            positions_unchanged and 
            visibility_unchanged
        ):
            return False, None

        # Acquire lock
        owner_token = str(uuid4())
        try:
            lock_acquired = self.model_portfolio_update_lock_repository.acquire_lock(
                portfolio_id=portfolio_id,
                owner_token=owner_token,
                lease_seconds=LOCK_LEASE_SECONDS
            )
        except ModelPortfolioUpdateLockBadGatewayError as e:
            raise ModelPortfolioBadGatewayError(
                source="DynamoDB",
                operation="acquiring model portfolio update lock",
                portfolio_id=portfolio_id,
                cause=e,
            ) from e
        except ModelPortfolioUpdateLockInternalServerError as e:
            raise ModelPortfolioLockedError(
                portfolio_id=portfolio_id,
                operation="acquire update lock",
                cause=e,
            ) from e
        
        if not lock_acquired:
            raise ModelPortfolioLockedError(
                portfolio_id=portfolio_id,
                operation="acquire update lock because portfolio is locked",
            )

        try:
            try:
                if not update_time:
                    update_time = datetime.now(timezone.utc)

                # Enforce 1-minute cooldown based on last updated_at.
                last_updated = existing.updated_at
                elapsed = (update_time - last_updated).total_seconds()
                if elapsed < 60:
                    raise ModelPortfolioTooManyRequestsError(
                        retry_after_seconds=int(60 - elapsed)
                    )

                new_snapshot_id: Optional[str] = None
                updated_history = existing.position_history

                if not positions_unchanged:
                    symbols = [position.symbol for position in positions_request]
                    try:
                        quotes = self.alpaca_broker_client.get_latest_price(
                            symbols=symbols
                        )
                    except AlpacaBrokerClientError as e:
                        raise ModelPortfolioBadGatewayError(
                            source="Alpaca",
                            operation="fetching latest prices during update",
                            portfolio_id=portfolio_id,
                            cause=e,
                        ) from e

                    model_portfolio_positions: List[ModelPortfolioPosition] = []
                    model_allocation = 10000.00
                    for position_request in positions_request:
                        model_portfolio_positions.append(
                            ModelPortfolioPosition(
                                symbol=position_request.symbol,
                                target_weight=position_request.target_weight,
                                direction=position_request.direction,
                                leverage=position_request.leverage,
                                model_filled_avg_price=quotes[position_request.symbol],
                                model_filled_quantity=(
                                    position_request.target_weight
                                    * model_allocation
                                )
                                / quotes[position_request.symbol],
                            )
                        )

                    new_snapshot_id = str(uuid4())
                    new_snapshot = ModelPortfolioSnapshot(
                        positions=model_portfolio_positions,
                        timestamp=update_time,
                        snapshot_id=new_snapshot_id,
                    )
                    updated_history = existing.position_history + [new_snapshot]

                portfolio = ModelPortfolio(
                    portfolio_id=portfolio_id,
                    portfolio_owner_cognito_user_id=existing.portfolio_owner_cognito_user_id,
                    portfolio_name=existing.portfolio_name,
                    position_history=updated_history,
                    created_at=existing.created_at,
                    updated_at=update_time,
                    description=description,
                    visibility=visibility,
                )

                item = dataclass_to_dynamodb_item(portfolio)
            except ModelPortfolioInternalServerError:
                raise
            except Exception as e:
                raise ModelPortfolioUnprocessableEntityError(
                    operation="creating updated model portfolio",
                    portfolio_id=portfolio_id,
                    cause=e,
                ) from e

            try:
                self.dynamodb.put_item(item)
            except DynamoDBClientError as e:
                raise ModelPortfolioBadGatewayError(
                    source="DynamoDB",
                    operation="persisting during update",
                    portfolio_id=portfolio_id,
                    cause=e,
                ) from e

            try:
                if visibility_unchanged is False and visibility == "PRIVATE":
                    self.model_portfolio_access_repository.batch_update_access_record(
                        portfolio_id=portfolio_id,
                        conditional_attributes={
                            "granted_access_by": "ALLOCATION",
                            "status": "ACTIVE",
                        },
                        value_attributes={"status": "TO_BE_DELETED"},
                        wait_for_lock=False,
                    )
                elif visibility_unchanged is False and visibility == "PUBLIC":
                    self.model_portfolio_access_repository.batch_update_access_record(
                        portfolio_id=portfolio_id,
                        conditional_attributes={
                            "granted_access_by": "ALLOCATION",
                            "status": "TO_BE_DELETED",
                        },
                        value_attributes={"status": "ACTIVE"},
                        wait_for_lock=False,
                    )
            except ModelPortfolioAccessRepositoryError as error:
                raise ModelPortfolioBadGatewayError(
                    source="DynamoDB/Cognito",
                    operation="syncing allocation model portfolio access status",
                    portfolio_id=portfolio_id,
                    owner_cognito_user_id=existing.portfolio_owner_cognito_user_id,
                    cause=error,
                ) from error
            except (KeyError, TypeError, ValueError) as error:
                raise ModelPortfolioUnprocessableEntityError(
                    operation="syncing allocation model portfolio access status",
                    portfolio_id=portfolio_id,
                    cause=error,
                ) from error

            return True, new_snapshot_id
        finally:
            # Release lock
            try:
                self.model_portfolio_update_lock_repository.release_lock(portfolio_id=portfolio_id, owner_token=owner_token)
            except ModelPortfolioUpdateLockBadGatewayError as e:
                raise ModelPortfolioBadGatewayError(
                    source="DynamoDB",
                    operation="releasing model portfolio update lock",
                    portfolio_id=portfolio_id,
                    cause=e,
                ) from e
            except ModelPortfolioUpdateLockInternalServerError as e:
                raise ModelPortfolioLockedError(
                    portfolio_id=portfolio_id,
                    operation="release update lock",
                    cause=e,
                ) from e


    def get_model_portfolio(
        self,
        portfolio_id: str,
        wait_seconds: float = LOCK_LEASE_SECONDS,
    ) -> ModelPortfolio:
        """
        Load a model portfolio by portfolio ID.

        Args:
            portfolio_id: Identifier of the portfolio.

        Returns:
            ModelPortfolio: Loaded model portfolio.

        Raises:
            ModelPortfolioLockedError: If lock state cannot be checked.
            ModelPortfolioBadGatewayError: If DynamoDB fails while loading the
            portfolio.
            ModelPortfolioNotFoundError: If the model portfolio does not exist.
            ModelPortfolioUnprocessableEntityError: If stored position history
            cannot be parsed.
        """

        # Wait for update (if applicable)
        self._wait_until_portfolio_update_lock_is_released(portfolio_id=portfolio_id, wait_seconds=wait_seconds)

        # Get model portfolio
        try:
            item = self.dynamodb.get_item(key={"portfolio_id": portfolio_id})
        except DynamoDBClientError as e:
            raise ModelPortfolioBadGatewayError(
                source="DynamoDB",
                operation="loading",
                portfolio_id=portfolio_id,
                cause=e,
            ) from e
        if not item:
            raise ModelPortfolioNotFoundError(
                portfolio_id=portfolio_id
            )

        # Create model portfolio object
        try:
            position_history = []
            for snap in item["position_history"]:
                positions = [
                    _parse_model_portfolio_position(position_item)
                    for position_item in snap["positions"]
                ]
                timestamp = to_utc_from_iso(snap["timestamp"])
                position_history.append(
                    ModelPortfolioSnapshot(
                        positions=positions,
                        timestamp=timestamp,
                        snapshot_id=str(snap["snapshot_id"]),
                    )
                )

            # Create model portfolio object
            model_portfolio = ModelPortfolio(
                portfolio_id=item["portfolio_id"],
                portfolio_owner_cognito_user_id=item["portfolio_owner_cognito_user_id"],
                portfolio_name=item["portfolio_name"],
                position_history=position_history,
                created_at=to_utc_from_iso(item["created_at"]),
                updated_at=to_utc_from_iso(item["updated_at"]),
                description=item.get("description"),
                visibility=item.get("visibility", "PRIVATE")
            )
        except Exception as e:
            raise ModelPortfolioUnprocessableEntityError(
                operation="failed to parse when getting model portfolio",
                portfolio_id=portfolio_id,
                cause=e,
            ) from e

        return model_portfolio
    

    def get_model_portfolio_metadata_by_owner(self, portfolio_owner_cognito_user_id: str) -> List[Dict]:
        """
        List portfolio IDs and names for one portfolio owner.

        Args:
            portfolio_owner_cognito_user_id: Identifier of the portfolio owner.

        Returns:
            List[Dict]: Portfolio metadata dictionaries containing portfolio_id,
            portfolio_name, and description.

        Raises:
            ModelPortfolioBadGatewayError: If DynamoDB fails while listing model
            portfolios for the owner.
        """

        # Get model portfolios by user
        try:
            items = self.dynamodb.query(
                key_condition=Key("portfolio_owner_cognito_user_id").eq(portfolio_owner_cognito_user_id),
                IndexName="portfolio_owner_cognito_user_id_index",
                ProjectionExpression=(
                    "portfolio_id, portfolio_owner_cognito_user_id, "
                    "portfolio_name, description, created_at, updated_at, "
                    "visibility"
                ),
            )
        except DynamoDBClientError as e:
            raise ModelPortfolioBadGatewayError(
                source="DynamoDB",
                operation="listing model portfolios",
                owner_cognito_user_id=portfolio_owner_cognito_user_id,
                cause=e,
            ) from e

        # Ensure user has model portfolios
        if not items:
            return []

        # Extract metadata of model portfolios
        try:
            portfolio_ids_names = [
                {
                    "portfolio_id": item["portfolio_id"], 
                    "portfolio_owner_cognito_user_id": item["portfolio_owner_cognito_user_id"],
                    "portfolio_name": item["portfolio_name"],
                    "created_at": item["created_at"],
                    "updated_at": item["updated_at"],
                    "description": item.get("description"),
                    "visibility": item.get("visibility", "PRIVATE")
                } 
                for item in items
            ]
            return portfolio_ids_names
        except Exception as e:
            raise ModelPortfolioUnprocessableEntityError(
                operation="Failed to parse list of user's model portfolios",
                portfolio_id=None,
                cause=e
            )

    def get_model_portfolio_metadata_by_portfolio_id(self, portfolio_id: str) -> Dict:
        """
        Load model portfolio metadata for one portfolio ID.

        Args:
            portfolio_id: Identifier of the portfolio to load.

        Returns:
            Dict: Portfolio metadata containing portfolio_id, owner, name,
            description, timestamps, and visibility.

        Raises:
            ModelPortfolioBadGatewayError: If DynamoDB fails while loading
            metadata.
            ModelPortfolioNotFoundError: If the portfolio does not exist.
            ModelPortfolioUnprocessableEntityError: If the stored metadata
            cannot be parsed.
        """
        try:
            item = self.dynamodb.get_item(
                key={"portfolio_id": portfolio_id},
                projection_expression=(
                    "portfolio_id, portfolio_owner_cognito_user_id, "
                    "portfolio_name, description, created_at, updated_at, "
                    "visibility"
                ),
            )
        except DynamoDBClientError as e:
            raise ModelPortfolioBadGatewayError(
                source="DynamoDB",
                operation="loading model portfolio metadata",
                portfolio_id=portfolio_id,
                cause=e,
            ) from e

        if not item:
            raise ModelPortfolioNotFoundError(portfolio_id=portfolio_id)

        try:
            return {
                "portfolio_id": item["portfolio_id"],
                "portfolio_owner_cognito_user_id": item[
                    "portfolio_owner_cognito_user_id"
                ],
                "portfolio_name": item["portfolio_name"],
                "created_at": item["created_at"],
                "updated_at": item["updated_at"],
                "description": item.get("description"),
                "visibility": item.get("visibility", "PRIVATE"),
            }
        except Exception as e:
            raise ModelPortfolioUnprocessableEntityError(
                operation="Failed to parse model portfolio metadata",
                portfolio_id=portfolio_id,
                cause=e,
            ) from e
