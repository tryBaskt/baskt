# backend/core/config.py

from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


_REPO_ROOT_DOTENV = Path(__file__).resolve().parents[2] / ".env"


def _settings_env_file() -> str | None:
    runtime_env = os.getenv("ENV", "").strip().lower()
    if runtime_env and runtime_env != "dev":
        return None
    return str(_REPO_ROOT_DOTENV)


class Settings(BaseSettings):
    # .env is a local-dev convenience. Deployed envs should set ENV and all
    # environment-specific values through the runtime environment.
    model_config = SettingsConfigDict(
        env_file=_settings_env_file(),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        protected_namespaces=("settings_",),
    )

    # ---------- App ----------
    app_name: str = "portfolio-backend"
    env: str = Field(default="dev", alias="ENV", description="dev|test|stage|prod")
    alpaca_env: Optional[str] = Field(default=None, alias="ALPACA_ENV")

    # Read as a string to avoid JSON parsing edge-cases for list fields in env vars.
    # Accepts:
    #   "*"                           (allow all)
    #   "http://a.com,http://b.com"   (comma-separated)
    #   '["http://a.com","http://b.com"]' (JSON string)
    cors_origins: str = Field(default="*", alias="CORS_ORIGINS")
    timezone: str = "America/New_York"
    cloudwatch_logs_enabled: bool = Field(default=False, alias="CLOUDWATCH_LOGS_ENABLED")
    cloudwatch_log_stream_name: Optional[str] = Field(default=None, alias="CLOUDWATCH_LOG_STREAM_NAME")

    # ---------- AWS ----------
    aws_region: str = Field(default="us-east-1", alias="AWS_DEFAULT_REGION")
    # Table name suffixes - will be prefixed with environment automatically
    # e.g., if env=dev and suffix=model-portfolios -> dev-model-portfolios
    model_portfolios_dynamodb_suffix: str = Field(
        default="-model-portfolio-dynamodb",
        alias="MODEL_PORTFOLIO_DYNAMODB"
    )
    allocation_dynamodb_suffix: str = Field(
        default="-allocation-dynamodb",
        alias="ALLOCATION_DYNAMODB"
    )
    order_dynamodb_suffix: str = Field(
        default="-order-dynamodb",
        alias="ORDER_DYNAMODB"
    )
    model_portfolio_follower_dynamodb_suffix: str = Field(
        default="-model-portfolio-follower-dynamodb",
        alias="MODEL_PORTFOLIO_FOLLOWER_DYNAMODB"
    )
    model_portfolio_access_dynamodb_suffix: str = Field(
        default="-model-portfolio-access-dynamodb",
        alias="MODEL_PORTFOLIO_ACCESS_DYNAMODB",
    )
    user_trade_lock_dynamodb_suffix: str = Field(
        default="-user-trade-lock-dynamodb",
        alias="USER_TRADE_LOCK_DYNAMODB"
    )
    model_portfolio_update_lock_suffix: str = Field(
        default="-model-portfolio-update-lock-dynamodb",
        alias="MODEL_PORTFOLIO_UPDATE_LOCK_DYNAMODB"
    )
    baskt_account_dynamodb_suffix: str = Field(
        default="-baskt-account-dynamodb",
        alias="BASKT_ACCOUNT_DYNAMODB",
    )
    opensearch_domain_suffix: str = Field(
        default="-model-portfolio-search",
        alias="OPENSEARCH_DOMAIN_SUFFIX",
    )
    model_portfolio_search_index_suffix: str = Field(
        default="-model-portfolios",
        alias="MODEL_PORTFOLIO_SEARCH_INDEX_SUFFIX",
    )
    baskt_account_search_index_suffix: str = Field(
        default="-baskt-accounts",
        alias="BASKT_ACCOUNT_SEARCH_INDEX_SUFFIX",
    )
    trade_execution_queue_suffix: str = Field(
        default="-trade-execution-queue",
        alias="TRADE_EXECUTION_QUEUE_SUFFIX",
    )
    dev_trade_execution_queue_url: Optional[str] = Field(default=None, alias="DEV_TRADE_EXECUTION_QUEUE_URL")
    test_trade_execution_queue_url: Optional[str] = Field(default=None, alias="TEST_TRADE_EXECUTION_QUEUE_URL")
    stage_trade_execution_queue_url: Optional[str] = Field(default=None, alias="STAGE_TRADE_EXECUTION_QUEUE_URL")
    prod_trade_execution_queue_url: Optional[str] = Field(default=None, alias="PROD_TRADE_EXECUTION_QUEUE_URL")

    # Explicit credentials are optional. GitHub Actions OIDC credentials include
    # AWS_SESSION_TOKEN, so keep it with the access key and secret when present.
    aws_access_key_id: Optional[str] = Field(default=None, alias="AWS_ACCESS_KEY_ID")
    aws_secret_access_key: Optional[str] = Field(default=None, alias="AWS_SECRET_ACCESS_KEY")
    aws_session_token: Optional[str] = Field(default=None, alias="AWS_SESSION_TOKEN")

    # ---------- Cognito ----------
    dev_cognito_region: Optional[str] = Field(default=None, alias="DEV_COGNITO_REGION")
    dev_cognito_user_pool_id: Optional[str] = Field(default=None, alias="DEV_COGNITO_USER_POOL_ID")
    dev_cognito_app_client_id: Optional[str] = Field(default=None, alias="DEV_COGNITO_APP_CLIENT_ID")
    test_cognito_region: Optional[str] = Field(default=None, alias="TEST_COGNITO_REGION")
    test_cognito_user_pool_id: Optional[str] = Field(default=None, alias="TEST_COGNITO_USER_POOL_ID")
    test_cognito_app_client_id: Optional[str] = Field(default=None, alias="TEST_COGNITO_APP_CLIENT_ID")
    stage_cognito_region: Optional[str] = Field(default=None, alias="STAGE_COGNITO_REGION")
    stage_cognito_user_pool_id: Optional[str] = Field(default=None, alias="STAGE_COGNITO_USER_POOL_ID")
    stage_cognito_app_client_id: Optional[str] = Field(default=None, alias="STAGE_COGNITO_APP_CLIENT_ID")
    prod_cognito_region: Optional[str] = Field(default=None, alias="PROD_COGNITO_REGION")
    prod_cognito_user_pool_id: Optional[str] = Field(default=None, alias="PROD_COGNITO_USER_POOL_ID")
    prod_cognito_app_client_id: Optional[str] = Field(default=None, alias="PROD_COGNITO_APP_CLIENT_ID")

    # ----------- Alpaca Broker -------------
    sandbox_alpaca_broker_api_key: Optional[str] = Field(default=None, alias="SANDBOX_ALPACA_BROKER_API_KEY")
    sandbox_alpaca_broker_api_secret: Optional[str] = Field(default=None, alias="SANDBOX_ALPACA_BROKER_API_SECRET")
    live_alpaca_broker_api_key: Optional[str] = Field(default=None, alias="LIVE_ALPACA_BROKER_API_KEY")
    live_alpaca_broker_api_secret: Optional[str] = Field(default=None, alias="LIVE_ALPACA_BROKER_API_SECRET")

    # ---------- Validators / derived values ----------
    @field_validator("env", mode="before")
    @classmethod
    def _validate_env(cls, v: Any) -> str:
        env = str(v or "dev").strip().lower()
        if env not in {"dev", "test", "stage", "prod"}:
            raise ValueError("ENV must be one of: dev, test, stage, prod")
        return env

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _coerce_cors_origins(cls, v: Any) -> str:
        """
        Make cors_origins ALWAYS a string.

        Handles cases where pydantic-settings already decoded a JSON list into a Python list,
        e.g. env var CORS_ORIGINS='["*"]' may become ['*'].
        """
        if v is None:
            return "*"
        if isinstance(v, list):
            return ",".join(str(x) for x in v)
        return str(v)

    @field_validator("alpaca_env", mode="before")
    @classmethod
    def _validate_alpaca_env(cls, v: Any) -> Optional[str]:
        if v is None or str(v).strip() == "":
            return None
        alpaca_env = str(v).strip().lower()
        if alpaca_env not in {"sandbox", "live"}:
            raise ValueError("ALPACA_ENV must be either 'sandbox' or 'live'")
        return alpaca_env

    @model_validator(mode="after")
    def _default_alpaca_env(self) -> "Settings":
        if self.alpaca_env is None:
            self.alpaca_env = "live" if self.env in {"stage", "prod"} else "sandbox"
        return self

    @property
    def cors_origins_list(self) -> list[str]:
        """
        Always returns a list[str] suitable for FastAPI CORSMiddleware.allow_origins.
        """
        s = (self.cors_origins or "*").strip()

        if s == "" or s == "*":
            return ["*"]

        # If someone sets JSON string directly: '["a","b"]'
        if s.startswith("["):
            try:
                arr = json.loads(s)
                if isinstance(arr, list):
                    vals = [str(x).strip() for x in arr if str(x).strip()]
                    return vals or ["*"]
            except Exception:
                pass

        # Comma-separated list
        return [x.strip() for x in s.split(",") if x.strip()]

    @property
    def model_portfolios_dynamodb(self) -> str:
        """Full table name with environment prefix: {env}{suffix}"""
        return f"{self.env}{self.model_portfolios_dynamodb_suffix}"

    @property
    def allocation_dynamodb(self) -> str:
        """Full table name with environment prefix: {env}{suffix}"""
        return f"{self.env}{self.allocation_dynamodb_suffix}"

    @property
    def order_dynamodb(self) -> str:
        """Full table name with environment prefix: {env}{suffix}"""
        return f"{self.env}{self.order_dynamodb_suffix}"
    
    @property
    def model_portfolio_follower_dynamodb(self) -> str:
        """Full table name with environment prefix: {env}{suffix}"""
        return f"{self.env}{self.model_portfolio_follower_dynamodb_suffix}"

    @property
    def model_portfolio_access_dynamodb(self) -> str:
        """Full table name with environment prefix: {env}{suffix}"""
        return f"{self.env}{self.model_portfolio_access_dynamodb_suffix}"
    
    @property
    def user_trade_lock_dynamodb(self) -> str:
        """Full table name with environment prefix:: {env}{suffix}"""
        return f"{self.env}{self.user_trade_lock_dynamodb_suffix}"
    
    @property
    def model_portfolio_update_lock_dynamodb(self) -> str:
        """Full table name with environment prefix: {env}{suffix}"""
        return f"{self.env}{self.model_portfolio_update_lock_suffix}"

    @property
    def baskt_account_dynamodb(self) -> str:
        """Full Baskt account table name with environment prefix."""
        return f"{self.env}{self.baskt_account_dynamodb_suffix}"

    @property
    def opensearch_domain_name(self) -> str:
        """Return the environment-specific OpenSearch domain name."""
        return f"{self.env}{self.opensearch_domain_suffix}"

    @property
    def model_portfolio_search_index(self) -> str:
        """Return the environment-specific Baskt search index name."""
        return f"{self.env}{self.model_portfolio_search_index_suffix}"

    @property
    def baskt_account_search_index(self) -> str:
        """Return the environment-specific Baskt account search index name."""
        return f"{self.env}{self.baskt_account_search_index_suffix}"

    @property
    def trade_execution_queue_name(self) -> str:
        """Return the environment-specific trade execution queue name."""
        return f"{self.env}{self.trade_execution_queue_suffix}"

    @property
    def trade_execution_queue_url(self) -> Optional[str]:
        """Return the configured trade execution queue URL for the current environment."""
        queue_url = getattr(self, f"{self.env}_trade_execution_queue_url", None)
        return queue_url or None

    @property
    def backend_application_log_group_name(self) -> str:
        """Return the CloudWatch Logs group for backend application logs."""
        return f"/baskt/{self.env}/backend/application"

    @property
    def backend_audit_log_group_name(self) -> str:
        """Return the CloudWatch Logs group for backend audit logs."""
        return f"/baskt/{self.env}/backend/audit"

    @property
    def alpaca_api_key(self) -> str:
        """
        Returns the Alpaca API key for the current environment.
        Looks up the key for the current environment (e.g., DEV_ALPACA_API_KEY when env=dev).
        """
        env_specific_key = getattr(self, f"{self.env.lower()}_alpaca_api_key", None)
        if env_specific_key:
            return env_specific_key
        raise ValueError(
            f"Alpaca API key not configured for environment '{self.env}'. "
            f"Set {self.env.upper()}_ALPACA_API_KEY in your .env file"
        )

    @property
    def alpaca_api_secret(self) -> str:
        """
        Returns the Alpaca API secret for the current environment.
        Looks up the secret for the current environment (e.g., DEV_ALPACA_API_SECRET when env=dev).
        """
        env_specific_secret = getattr(self, f"{self.env.lower()}_alpaca_api_secret", None)
        if env_specific_secret:
            return env_specific_secret
        raise ValueError(
            f"Alpaca API secret not configured for environment '{self.env}'. "
            f"Set {self.env.upper()}_ALPACA_API_SECRET in your .env file"
        )
    
    @property
    def alpaca_broker_api_key(self) -> str:
        """
        Returns the Alpaca Broker API key for ALPACA_ENV.

        Looks up SANDBOX_ALPACA_BROKER_API_KEY when alpaca_env=sandbox and
        LIVE_ALPACA_BROKER_API_KEY when alpaca_env=live.
        """
        env_specific_key = getattr(self, f"{self.alpaca_env.lower()}_alpaca_broker_api_key", None)
        if env_specific_key:
            return env_specific_key
        raise ValueError(
            f"Alpaca Broker API key not configured for ALPACA_ENV='{self.alpaca_env}'. "
            f"Set {self.alpaca_env.upper()}_ALPACA_BROKER_API_KEY in your .env file"
        )

    @property
    def alpaca_broker_api_secret(self) -> str:
        """
        Returns the Alpaca Broker API secret for ALPACA_ENV.

        Looks up SANDBOX_ALPACA_BROKER_API_SECRET when alpaca_env=sandbox and
        LIVE_ALPACA_BROKER_API_SECRET when alpaca_env=live.
        """
        env_specific_secret = getattr(self, f"{self.alpaca_env.lower()}_alpaca_broker_api_secret", None)
        if env_specific_secret:
            return env_specific_secret
        raise ValueError(
            f"Alpaca Broker API secret not configured for ALPACA_ENV='{self.alpaca_env}'. "
            f"Set {self.alpaca_env.upper()}_ALPACA_BROKER_API_SECRET in your .env file"
        )
    
    @property
    def cognito_region(self) -> str:
        """
        Returns the cognito region for current environment
        """
        env_specific_cognito_region = getattr(self, f"{self.env.lower()}_cognito_region", None)
        if env_specific_cognito_region:
            return env_specific_cognito_region
        raise ValueError(
            f"Cognito not configured for environment '{self.env}'. "
            f"Set {self.env.upper()}_COGNITO_REGION in your .env file"
        )
    
    @property
    def cognito_user_pool_id(self) -> str:
        """
        Returns the cogito user pool id for current environment
        """
        env_specific_cognito_user_pool_id = getattr(self, f"{self.env.lower()}_cognito_user_pool_id", None)
        if env_specific_cognito_user_pool_id:
            return env_specific_cognito_user_pool_id 
        raise ValueError(
            f"Cognito user pool id not configured for environment '{self.env}'. "
            f"Set {self.env.upper()}_COGNITO_USER_POOL_ID in your .env file"
        )
    
    @property
    def cognito_app_client_id(self) -> str:
        """
        Returns the cognito app client id for current environment
        """
        env_specific_cognito_app_client_id = getattr(self, f"{self.env.lower()}_cognito_app_client_id", None)
        if env_specific_cognito_app_client_id:
            return env_specific_cognito_app_client_id 
        raise ValueError(
            f"Cognito app client id not configured for environment '{self.env}'. "
            f"Set {self.env.upper()}_COGNITO_APP_CLIENT_ID in your .env file"
        )
    

    @property
    def cognito_jwks_url(self) -> str:
        return (
            f"https://cognito-idp.{self.cognito_region}.amazonaws.com/"
            f"{self.cognito_user_pool_id}/.well-known/jwks.json"
        )

    @property
    def cognito_issuer(self) -> str:
        return f"https://cognito-idp.{self.cognito_region}.amazonaws.com/{self.cognito_user_pool_id}"

@lru_cache
def get_settings() -> Settings:
    """
    Cached settings object so imports don't repeatedly parse env vars.
    """
    return Settings()
