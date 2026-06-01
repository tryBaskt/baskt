# backend/repository/model_portfolio_repository.py

# Python imports
from __future__ import annotations
from datetime import datetime, timezone
from typing import List, Optional, Dict
from uuid import uuid4
from decimal import Decimal
import time

# AWS imports
from boto3.dynamodb.conditions import Key

# Baskt imports 
from domain.model_portfolio import ModelPortfolio, ModelPortfolioSnapshot, ModelPortfolioPosition
from repository.model_portfolio_update_lock_repository import (
    ModelPortfolioUpdateLockBadGatewayError,
    ModelPortfolioUpdateLockRepository,
    ModelPortfolioUpdateLockInternalServerError,
    ModelPortfolioUpdateLockUnprocessableEntityError,
)
from repository.model_portfolio_follower_repository import (
    ModelPortfolioFollowerBadGatewayError,
    ModelPortfolioFollowerInternalServerError,
    ModelPortfolioFollowerRepository,
    ModelPortfolioFollowerUnprocessableEntityError,
)
from clients.dynamodb_client import DynamoDBClient, DynamoDBClientError
from clients.alpaca_broker_client import AlpacaBrokerClient, AlpacaBrokerClientError
from core.timeutils import to_utc_from_iso
from schema.model_portfolio_request import ModelPortfolioPositionRequest

LOCK_LEASE_SECONDS = 30
READ_LOCK_POLL_SECONDS = 0.25

class ModelPortfolioInternalServerError(Exception):
    def __init__(self, message: str, code: str = "MODEL_PORTFOLIO_INTERNAL_SERVER_ERROR"):
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
        portfolio_id: str | None = None,
        owner_cognito_user_id: str | None = None,
        cause: Exception | None = None,
    ):
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
    def __init__(self, portfolio_id: str):
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
        portfolio_id: str | None = None,
        cause: Exception | None = None,
    ):
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

class ModelPortfolioTooManyRequestsError(ModelPortfolioInternalServerError):
    def __init__(self, retry_after_seconds: int):
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

class ModelPortfolioPositionHistoryNotFoundError(ModelPortfolioInternalServerError):
    def __init__(self, portfolio_id: str):
        """
        Initialize a missing position history exception.

        Args:
            portfolio_id: Model portfolio ID whose position history was not
                found.

        Returns:
            None.

        Raises:
            No exceptions are intentionally raised by this method.
        """
        super().__init__(
            message=f"Position history not found for model portfolio '{portfolio_id}'.",
            code="MODEL_PORTFOLIO_POSITION_HISTORY_NOT_FOUND",
        )

class ModelPortfolioLockedError(ModelPortfolioInternalServerError):
    def __init__(
        self,
        portfolio_id: str,
        operation: str,
        *,
        cause: Exception | None = None,
    ):
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
    Service for managing model portfolios in DynamoDB.
    """

    def __init__(
        self,
        dynamodb_client: DynamoDBClient,
        alpaca_broker_client: AlpacaBrokerClient,
        model_portfolio_update_lock_repository: ModelPortfolioUpdateLockRepository,
        model_portfolio_follower_repository: ModelPortfolioFollowerRepository | None = None,
    ):
        """
        Initialize model portfolio repository dependencies.

        Args:
            dynamodb_client: DynamoDB client wrapper for model portfolio
                persistence.
            alpaca_broker_client: Alpaca broker client used for latest market
                prices.
            model_portfolio_update_lock_repository: Repository used to
                coordinate model portfolio update locks.
            model_portfolio_follower_repository: Optional repository used to
                clean up follower records when deleting model portfolios.

        Returns:
            None.

        Raises:
            No exceptions are intentionally raised by this method.
        """
        self.dynamodb = dynamodb_client
        self.alpaca_broker_client = alpaca_broker_client
        self.model_portfolio_update_lock_repository = model_portfolio_update_lock_repository
        self.model_portfolio_follower_repository = model_portfolio_follower_repository

    def _wait_until_portfolio_update_lock_is_released(self, portfolio_id: str) -> None:
        """
        Block reads while an active update lock exists for the portfolio.

        Args:
            portfolio_id: Model portfolio ID to wait on before reading or
                writing.

        Returns:
            None.

        Raises:
            ModelPortfolioLockedError: If the update lock repository fails
            while checking the portfolio lock.
        """
        while True:
            try:
                lock = self.model_portfolio_update_lock_repository.get_lock(portfolio_id=portfolio_id)
            except (ModelPortfolioUpdateLockInternalServerError, ModelPortfolioUpdateLockUnprocessableEntityError) as e:
                raise ModelPortfolioLockedError(
                    portfolio_id=portfolio_id,
                    operation="check update lock",
                    cause=e,
                ) from e
            if not lock:
                return

            expires_at = int(lock.get("expires_at", 0))
            now = int(time.time())
            if expires_at < now:
                return

            sleep_seconds = min(READ_LOCK_POLL_SECONDS, max(0.0, float(expires_at - now)))
            time.sleep(sleep_seconds)

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
            ModelPortfolioPositionHistoryNotFoundError: If the stored item does
            not include position_history.
            ModelPortfolioUnprocessableEntityError: If stored position history
            cannot be parsed.
        """

        # Wait for update lock to release (if applicable)
        self._wait_until_portfolio_update_lock_is_released(portfolio_id=portfolio_id)

        # Only fetch position_history to reduce bandwidth
        try:
            item = self.dynamodb.get_item(
                key={"portfolio_id": portfolio_id},
                projection_expression="position_history"
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
            raise ModelPortfolioPositionHistoryNotFoundError(
                portfolio_id=portfolio_id
            )

        # Create position history
        result = []
        position_history = item["position_history"]
        for snap in position_history:

            try:
                positions = [
                    ModelPortfolioPosition(
                        symbol=str(pos["symbol"]),
                        target_weight=float(pos["target_weight"]),
                        direction=int(pos["direction"]),
                        leverage=float(pos["leverage"]),
                        model_filled_quantity=float(pos["model_filled_quantity"]),
                        model_filled_avg_price=float(pos["model_filled_avg_price"])
                    )
                    for pos in snap["positions"]
                ]
            except Exception as e:
                raise ModelPortfolioUnprocessableEntityError(
                    operation="parse position history",
                    portfolio_id=portfolio_id,
                    cause=e,
                ) from e

            timestamp = to_utc_from_iso(snap["timestamp"])
            
            result.append(
                ModelPortfolioSnapshot(
                    positions=positions,
                    timestamp=timestamp
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
            ModelPortfolioPositionHistoryNotFoundError: If position history is
            missing.
            ModelPortfolioUnprocessableEntityError: If stored position history
            cannot be parsed.
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
    

    def calculate_positions_current_weight(self, model_portfolio_snapshot: ModelPortfolioSnapshot) -> List[Dict[str, float] | float]:
        """
        Calculate current normalized weights from latest market prices.

        Args:
            model_portfolio_snapshot: Snapshot containing modeled position quantities.

        Returns:
            List[Dict[str, float] | float]: Current normalized weights by
            symbol, total portfolio value, and latest quotes. When total value
            is zero, returns equivalent zero-weight values with total value and
            quotes.

        Raises:
            ModelPortfolioBadGatewayError: If Alpaca fails while fetching
            latest prices.
            ModelPortfolioInternalServerError: If a latest price is missing for
            a symbol in the snapshot.
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

            current_price = quotes.get(position.symbol)
            if current_price is None:
                raise ModelPortfolioInternalServerError(
                    message=f"Missing latest price for symbol '{position.symbol}' while calculating current position weights."
                )
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


        return [
            {
                symbol: value / total_value
                for symbol, value in position_values.items()
            },
            total_value, 
            quotes
        ]


    def create_model_portfolio(self, portfolio_owner_cognito_user_id: str, portfolio_name: str, positions_request: List[ModelPortfolioPositionRequest], creation_time = None, description: str = None) -> str:
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
            ModelPortfolioInternalServerError: If a latest price is missing for
            a requested position symbol.
        """

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
        
        # Create model portfolio positions
        model_portfolio_positions: List[ModelPortfolioPosition] = []
        model_allocation = 10000.00
        for i in range(len(positions_request)):
            position_request = positions_request[i]
            if position_request.symbol not in quotes:
                raise ModelPortfolioInternalServerError(
                    message=f"Missing latest price for symbol '{position_request.symbol}' for model portfolio '{portfolio_id}' during creation."
                )

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
        snapshot = ModelPortfolioSnapshot(positions=model_portfolio_positions, timestamp=creation_time)
        portfolio = ModelPortfolio(
            portfolio_id=portfolio_id,
            portfolio_owner_cognito_user_id=portfolio_owner_cognito_user_id,
            portfolio_name=portfolio_name,
            position_history=[snapshot],
            created_at=creation_time,
            updated_at=creation_time,
            description=description
        )

        # Write model portfolio object to dynamodb
        item = {
            "portfolio_id": portfolio.portfolio_id,
            "portfolio_owner_cognito_user_id": portfolio.portfolio_owner_cognito_user_id,
            "portfolio_name": portfolio.portfolio_name,
            "description": portfolio.description,
            "position_history": [
                {
                    "positions": [
                        {
                            "symbol": pos.symbol,
                            "target_weight": Decimal(str(pos.target_weight)),
                            "direction": pos.direction,
                            "leverage": Decimal(str(pos.leverage)),
                            "model_filled_quantity": Decimal(str(pos.model_filled_quantity)),
                            "model_filled_avg_price": Decimal(str(pos.model_filled_avg_price)),
                        }
                        for pos in snap.positions
                    ],
                    "timestamp": snap.timestamp.isoformat(),
                }
                for snap in portfolio.position_history
            ],
            "created_at": portfolio.created_at.isoformat(),
            "updated_at": portfolio.updated_at.isoformat(),
        }

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


    def update_model_portfolio(self, portfolio_id: str, positions_request: List[ModelPortfolioPositionRequest], update_time = None, description: str = None) -> bool:
        """
        Append a new snapshot and persist updates to an existing model portfolio.

        Args:
            portfolio_id: Identifier of the portfolio.
            positions_request: Updated positions to store as a new snapshot.
            update_time: Optional update timestamp; defaults to now in UTC.
            description: Optional updated free-text description.

        Returns:
            bool: True if the portfolio is updated, otherwise False.

        Raises:
            ModelPortfolioNotFoundError: If the model portfolio does not exist.
            ModelPortfolioLockedError: If the portfolio lock cannot be acquired,
            is already held, or cannot be released.
            ModelPortfolioTooManyRequestsError: If the portfolio was updated
            less than one minute ago.
            ModelPortfolioBadGatewayError: If Alpaca fails while fetching latest
            prices or DynamoDB fails while persisting the update.
            ModelPortfolioInternalServerError: If a latest price is missing for
            a requested position symbol.
            ModelPortfolioUnprocessableEntityError: If the stored portfolio
            data cannot be parsed.
        """
        # Ensure portfolio does exist
        existing: ModelPortfolio = self.get_model_portfolio(portfolio_id=portfolio_id)
        if not existing:
            return False
        
        # Acquire lock
        owner_token = str(uuid4())
        try:
            lock_acquired = self.model_portfolio_update_lock_repository.acquire_lock(
                portfolio_id=portfolio_id,
                owner_token=owner_token,
                lease_seconds=LOCK_LEASE_SECONDS
            )
        except (ModelPortfolioUpdateLockInternalServerError, ModelPortfolioUpdateLockUnprocessableEntityError) as e:
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
            if not update_time:
                update_time = datetime.now(timezone.utc)

            # Enforce 1-minute cooldown based on last updated_at
            last_updated = existing.updated_at
            elapsed = (update_time - last_updated).total_seconds()
            if elapsed < 60:
                raise ModelPortfolioTooManyRequestsError(
                    retry_after_seconds=int(60 - elapsed)
                )
            
            # Get latest prices
            symbols = [pos.symbol for pos in positions_request]
            try:
                quotes = self.alpaca_broker_client.get_latest_price(symbols=symbols)
            except AlpacaBrokerClientError as e:
                raise ModelPortfolioBadGatewayError(
                    source="Alpaca",
                    operation="fetching latest prices during update",
                    portfolio_id=portfolio_id,
                    cause=e,
                ) from e
            
            # Build model portfolio positions
            model_portfolio_positions: List[ModelPortfolioPosition] = []
            model_allocation = 10000.00
            for i in range(len(positions_request)):
                position_request = positions_request[i]
                if position_request.symbol not in quotes:
                    raise ModelPortfolioInternalServerError(
                        message=f"Missing latest price for symbol '{position_request.symbol}' for model portfolio '{portfolio_id}' during update."
                    )
                
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

            # Create new snapshot
            new_snapshot = ModelPortfolioSnapshot(positions=model_portfolio_positions, timestamp=update_time)
            updated_history = existing.position_history + [new_snapshot]
            portfolio = ModelPortfolio(
                portfolio_id=portfolio_id,
                portfolio_owner_cognito_user_id=existing.portfolio_owner_cognito_user_id,
                portfolio_name=existing.portfolio_name,  # Name cannot be changed
                position_history=updated_history,
                created_at=existing.created_at,
                updated_at=update_time,
                description=description
            )

            # Write item to dynamodb
            item = {
                "portfolio_id": portfolio.portfolio_id,
                "portfolio_owner_cognito_user_id": portfolio.portfolio_owner_cognito_user_id,
                "portfolio_name": portfolio.portfolio_name,
                "position_history": [
                    {
                        "positions": [
                            {
                                "symbol": pos.symbol,
                                "target_weight": Decimal(str(pos.target_weight)),
                                "direction": pos.direction,
                                "leverage": Decimal(str(pos.leverage)),
                                "model_filled_quantity": Decimal(str(pos.model_filled_quantity)),
                                "model_filled_avg_price": Decimal(str(pos.model_filled_avg_price)),
                            }
                            for pos in snap.positions
                        ],
                        "timestamp": snap.timestamp.isoformat(),
                    }
                    for snap in portfolio.position_history
                ],
                "description": portfolio.description,
                "created_at": portfolio.created_at.isoformat(),
                "updated_at": portfolio.updated_at.isoformat(),
            }

            try:
                self.dynamodb.put_item(item)
            except DynamoDBClientError as e:
                raise ModelPortfolioBadGatewayError(
                    source="DynamoDB",
                    operation="persisting during update",
                    portfolio_id=portfolio_id,
                    cause=e,
                ) from e
            return True
        finally:
            # Release lock
            try:
                self.model_portfolio_update_lock_repository.release_lock(portfolio_id=portfolio_id, owner_token=owner_token)
            except (ModelPortfolioUpdateLockInternalServerError, ModelPortfolioUpdateLockUnprocessableEntityError) as e:
                raise ModelPortfolioLockedError(
                    portfolio_id=portfolio_id,
                    operation="release update lock",
                    cause=e,
                ) from e


    def get_model_portfolio(self, portfolio_id: str) -> Optional[ModelPortfolio]:
        """
        Load a model portfolio by portfolio ID.

        Args:
            portfolio_id: Identifier of the portfolio.

        Returns:
            Optional[ModelPortfolio]: Loaded model portfolio.

        Raises:
            ModelPortfolioLockedError: If lock state cannot be checked.
            ModelPortfolioBadGatewayError: If DynamoDB fails while loading the
            portfolio.
            ModelPortfolioNotFoundError: If the model portfolio does not exist.
            ModelPortfolioUnprocessableEntityError: If stored position history
            cannot be parsed.
        """

        # Wait for update (if applicable)
        self._wait_until_portfolio_update_lock_is_released(portfolio_id=portfolio_id)

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
        position_history = []
        try:
            for snap in item["position_history"]:
                positions = [
                    ModelPortfolioPosition(
                        symbol=pos["symbol"],
                        target_weight=float(pos["target_weight"]),
                        direction=int(pos["direction"]),
                        leverage=float(pos["leverage"]),
                        model_filled_quantity=float(pos["model_filled_quantity"]),
                        model_filled_avg_price=float(pos["model_filled_avg_price"]),
                    )
                    for pos in snap["positions"]
                ]
                timestamp = to_utc_from_iso(snap["timestamp"])
                position_history.append(ModelPortfolioSnapshot(positions=positions, timestamp=timestamp))
        except Exception as e:
            raise ModelPortfolioUnprocessableEntityError(
                operation="parse stored position history",
                portfolio_id=portfolio_id,
                cause=e,
            ) from e

        # Create model portfolio object
        model_portfolio = ModelPortfolio(
            portfolio_id=item["portfolio_id"],
            portfolio_owner_cognito_user_id=item["portfolio_owner_cognito_user_id"],
            portfolio_name=item["portfolio_name"],
            position_history=position_history,
            created_at=to_utc_from_iso(item["created_at"]),
            updated_at=to_utc_from_iso(item["updated_at"]),
            description=item.get("description"),
        )

        return model_portfolio
    

    def list_user_model_portfolio_names(self, portfolio_owner_cognito_user_id: str) -> List[Dict]:
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
                ProjectionExpression="portfolio_id, portfolio_name, description",
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
        portfolio_ids_names = [
            {
                "portfolio_id": item["portfolio_id"], 
                "portfolio_name": item["portfolio_name"],
                "description": item.get("description")
            } 
            for item in items
        ]
        return portfolio_ids_names
