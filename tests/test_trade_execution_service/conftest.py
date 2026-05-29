import os
import sys
from pathlib import Path
import pytest
from dotenv import load_dotenv

repo_root = Path(__file__).resolve().parents[2]
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

from backend.core import deps as app_deps
from backend.core.config import get_settings
from backend.clients.alpaca_broker_client import AlpacaBrokerClient
from backend.clients.cognito_client import CognitoClient
from backend.repository.user_account_repository import UserAccountRepository
from backend.services.account_lifecycle_service import AccountLifecycleService
from backend.clients.dynamodb_client import DynamoDBClient
from backend.repository.model_portfolio_follower_repository import ModelPortfolioFollowerRepository
from backend.repository.model_portfolio_repository import ModelPortfolioRepository
from backend.repository.portfolio_allocation_repository import PortfolioAllocationRepository
from backend.repository.order_repository import OrderRepository
from backend.repository.user_trade_lock_repository import UserTradeLockRepository
from backend.repository.model_portfolio_update_lock_repository import ModelPortfolioUpdateLockRepository
from backend.services.trade_execution_service import TradeExecutionService
# from backend.clients.alpaca_client import AlpacaClient
from backend.clients.alpaca_broker_client import AlpacaBrokerClient
from backend.domain.baskt import BasktPosition


load_dotenv()
os.environ["ENV"] = "dev"
get_settings.cache_clear()

#######################################
############### CLIENTS ###############
#######################################
@pytest.fixture(scope="session")
def alpaca_broker_client() -> AlpacaBrokerClient:
    app_deps.get_alpaca_broker_client.cache_clear()
    return app_deps.get_alpaca_broker_client()

@pytest.fixture(scope="session")
def cognito_client() -> CognitoClient:
    return app_deps.get_cognito_client()

@pytest.fixture(scope="session")
def dynamodb_client() -> DynamoDBClient:
    return app_deps.get_dynamodb_resource_cached()

@pytest.fixture(scope="session")
def user_account_repository() -> UserAccountRepository:
    app_deps.get_user_account_dynamodb_client.cache_clear()
    user_account_dynamodb_client = app_deps.get_user_account_dynamodb_client()
    return app_deps.get_user_account_repository(
        user_account_dynamodb_client=user_account_dynamodb_client
    )

########################################
############## REPOSITORY ##############
########################################
pytest.fixture(scope="session")
def model_portfolio_follower_repository() -> ModelPortfolioFollowerRepository:

    app_deps.get_model_portfolio_follower_dynamodb_client.cache_clear()
    model_portfolio_follower_dynamodb_client = app_deps.get_model_portfolio_follower_dynamodb_client()

    app_deps.get_alpaca_broker_client.cache_clear()
    alpaca_broker_client = app_deps.get_alpaca_broker_client()

    return app_deps.get_model_portfolio_follower_repository(
        model_protfolio_follower_dynamodb_client=model_portfolio_follower_dynamodb_client,
        alpaca_broker_client=alpaca_broker_client
    )

@pytest.fixture(scope="session")
def model_portfolio_repository() -> UserAccountRepository:

    app_deps.get_model_portfolio_dynamodb_client.cache_clear()
    user_account_dynamodb_client = app_deps.get_user_account_dynamodb_client()

    return app_deps.get_user_account_repository(
        user_account_dynamodb_client=user_account_dynamodb_client
    )

@pytest.fixture(scope="session")
def model_portfolio_update_lock_repository() -> ModelPortfolioUpdateLockRepository:

    app_deps.get_model_portfolio_update_lock_dynamodb_client.cache_clear()
    model_portfolio_update_lock_dynamodb_client = app_deps.get_model_portfolio_update_lock_dynamodb_client()

    return app_deps.get_model_portfolio_update_lock_repository(
        model_portfolio_update_lock_dynamodb_client=model_portfolio_update_lock_dynamodb_client
    )

@pytest.fixture(scope="session")
def portfolio_allocation_repository() -> PortfolioAllocationRepository:
    app_deps.get_portfolio_allocation_dynamodb_client.cache_clear()
    portfolio_allocation_dynamodb_client = app_deps.get_portfolio_allocation_dynamodb_client()
    app_deps.get_alpaca_broker_client.cache_clear()
    alpaca_broker_client = app_deps.get_alpaca_broker_client()
    return app_deps.get_portfolio_allocation_repository(
        portfolio_allocation_dynamodb_client=portfolio_allocation_dynamodb_client,
        alpaca_broker_client=alpaca_broker_client
    )

@pytest.fixture(scope="session")
def order_repository() -> OrderRepository:
    app_deps.get_order_dynamodb_client.cache_clear()
    order_dynamodb_client = app_deps.get_order_dynamodb_client()
    app_deps.get_alpaca_broker_client.cache_clear()
    alpaca_broker_client = app_deps.get_alpaca_broker_client()
    return app_deps.get_order_repository(
        order_dynamodb_client=order_dynamodb_client,
        alpaca_broker_client=alpaca_broker_client
    )

@pytest.fixture(scope="session")
def user_trade_lock_repository() -> UserTradeLockRepository:
    app_deps.get_user_trade_lock_dynamodb_client.cache_clear()
    user_trade_lock_dynamodb_client = app_deps.get_user_trade_lock_dynamodb_client()
    return app_deps.get_user_trade_lock_repository(
        user_trade_lock_dynamodb_client=user_trade_lock_dynamodb_client
    )

@pytest.fixture(scope="session")
def user_account_repository() -> UserAccountRepository:
    app_deps.get_user_account_dynamodb_client.cache_clear()
    user_account_dynamodb_client = app_deps.get_user_account_dynamodb_client()
    return app_deps.get_user_account_repository(
        user_account_dynamodb_client=user_account_dynamodb_client
    )


##################################################
#################### SERVICES ####################
##################################################
    
@pytest.fixture(scope="session")
def trade_execution_service() -> TradeExecutionService:

    # Manually resolve all dependencies for TradeExecutionService
    app_deps.get_model_portfolio_dynamodb_client.cache_clear()
    model_portfolio_dynamodb_client = app_deps.get_model_portfolio_dynamodb_client()
    app_deps.get_alpaca_broker_client.cache_clear()
    alpaca_broker_client = app_deps.get_alpaca_broker_client()
    app_deps.get_portfolio_allocation_dynamodb_client.cache_clear()
    portfolio_allocation_dynamodb_client = app_deps.get_portfolio_allocation_dynamodb_client()
    app_deps.get_order_dynamodb_client.cache_clear()
    order_dynamodb_client = app_deps.get_order_dynamodb_client()
    app_deps.get_model_portfolio_follower_dynamodb_client.cache_clear()
    model_portfolio_follower_dynamodb_client = app_deps.get_model_portfolio_follower_dynamodb_client()
    app_deps.get_user_trade_lock_dynamodb_client.cache_clear()
    user_trade_lock_dynamodb_client = app_deps.get_user_trade_lock_dynamodb_client()

    model_portfolio_update_lock_repository = app_deps.get_model_portfolio_update_lock_repository(
        model_portfolio_update_lock_dynamodb_client=app_deps.get_model_portfolio_update_lock_dynamodb_client()
    )
    model_portfolio_repository = app_deps.get_model_portfolio_repository(
        dynamodb=model_portfolio_dynamodb_client,
        alpaca_broker_client=alpaca_broker_client,
        model_portfolio_update_lock_repository=model_portfolio_update_lock_repository
    )
    portfolio_allocation_repository = app_deps.get_portfolio_allocation_repository(
        portfolio_allocation_dynamodb_client=portfolio_allocation_dynamodb_client,
        alpaca_broker_client=alpaca_broker_client
    )
    order_repository = app_deps.get_order_repository(
        order_dynamodb_client=order_dynamodb_client,
        alpaca_broker_client=alpaca_broker_client
    )
    model_portfolio_follower_repository = app_deps.get_model_portfolio_follower_repository(
        model_protfolio_follower_dynamodb_client=model_portfolio_follower_dynamodb_client,
        alpaca_broker_client=alpaca_broker_client
    )
    user_trade_lock_repository = app_deps.get_user_trade_lock_repository(
        user_trade_lock_dynamodb_client=user_trade_lock_dynamodb_client
    )

    return app_deps.get_trade_execution_service(
        model_portfolio_repository=model_portfolio_repository,
        alpaca_broker_client=alpaca_broker_client,
        portfolio_allocation_repository=portfolio_allocation_repository,
        order_repository=order_repository,
        model_portfolio_follower_repository=model_portfolio_follower_repository,
        user_trade_lock_repository=user_trade_lock_repository,
    )
    

@pytest.fixture(scope="session")
def account_lifecycle_service(
) -> AccountLifecycleService:
    app_deps.get_cognito_client.cache_clear()
    app_deps.get_alpaca_broker_client.cache_clear()
    app_deps.get_user_account_dynamodb_client.cache_clear()
    user_account_dynamodb_client = app_deps.get_user_account_dynamodb_client()

    cognito_client = app_deps.get_cognito_client()
    alpaca_broker_client = app_deps.get_alpaca_broker_client()
    user_account_repository = app_deps.get_user_account_repository(user_account_dynamodb_client=user_account_dynamodb_client)

    return app_deps.get_account_lifecycle_service(
        alpaca_broker_client=alpaca_broker_client,
        cognito_client=cognito_client,
        user_account_repository=user_account_repository,
    )



