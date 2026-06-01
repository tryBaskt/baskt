# backend/core/config.py

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Prefer a deterministic env file location (repo root/.env) if present.
    # Falls back to ".env" in the current working directory.
    _repo_root_env = Path(__file__).resolve().parents[2] / ".env"
    _default_env = Path(".env")

    model_config = SettingsConfigDict(
        env_file=str(_repo_root_env if _repo_root_env.exists() else _default_env),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        protected_namespaces=("settings_",),
    )

    # ---------- App ----------
    app_name: str = "portfolio-backend"
    env: str = Field(default="dev", description="dev|test|stage|prod")
    alpaca_env: str = Field(default="sandbox", description="sandbox|live")

    # Read as a string to avoid JSON parsing edge-cases for list fields in env vars.
    # Accepts:
    #   "*"                           (allow all)
    #   "http://a.com,http://b.com"   (comma-separated)
    #   '["http://a.com","http://b.com"]' (JSON string)
    cors_origins: str = Field(default="*", alias="CORS_ORIGINS")
    timezone: str = "America/New_York"

    # ---------- AWS ----------
    aws_region: str = Field(default="us-east-1", alias="AWS_DEFAULT_REGION")
    # Table name suffixes - will be prefixed with environment automatically
    # e.g., if env=dev and suffix=model-portfolios -> dev-model-portfolios
    model_portfolios_dynamodb_suffix: str = Field(
        default="_model_portfolio_dynamodb",
        alias="MODEL_PORTFOLIO_DYNAMODB"
    )
    portfolio_allocation_dynamodb_suffix: str = Field(
        default="_portfolio_allocation_dynamodb",
        alias="PORTFOLIO_ALLOCATION_DYNAMODB"
    )
    order_dynamodb_suffix: str = Field(
        default="_order_dynamodb",
        alias="ORDER_DYNAMODB"
    )
    model_portfolio_follower_dynamodb_suffix: str = Field(
        default="_model_portfolio_follower_dynamodb",
        alias="MODEL_PORTFOLIO_FOLLOWER_DYNAMODB"
    )
    user_trade_lock_dynamodb_suffix: str = Field(
        default="_user_trade_lock_dynamodb",
        alias="USER_TRADE_LOCK_DYNAMODB"
    )
    user_account_dynamodb_suffix: str = Field(
        default="_user_account_dynamodb",
        alias="USER_ACCOUNT_DYNAMODB"
    )
    model_portfolio_update_lock_suffix: str = Field(
        default="_model_portfolio_update_lock_dynamodb",
        alias="MODEL_PORTFOLIO_UPDATE_LOCK_DYNAMODB"
    )
    # Local-only credentials (on AWS, rely on IAM roles; these can be unset)
    aws_access_key_id: Optional[str] = Field(alias="AWS_ACCESS_KEY_ID")
    aws_secret_access_key: Optional[str] = Field(alias="AWS_SECRET_ACCESS_KEY")

    # ---------- Cognito ----------
    dev_cognito_region: str = Field(alias="DEV_COGNITO_REGION")
    dev_cognito_user_pool_id: str = Field(alias="DEV_COGNITO_USER_POOL_ID")
    dev_cognito_app_client_id: str = Field(alias="DEV_COGNITO_APP_CLIENT_ID")

    # ---------- Alpaca -----------
    # Environment-specific Alpaca credentials (e.g., DEV_ALPACA_API_KEY for dev environment)
    dev_alpaca_api_key: Optional[str] = Field(default=None, alias="DEV_ALPACA_API_KEY")
    dev_alpaca_api_secret: Optional[str] = Field(default=None, alias="DEV_ALPACA_API_SECRET")
    test_alpaca_api_key: Optional[str] = Field(default=None, alias="TEST_ALPACA_API_KEY")
    test_alpaca_api_secret: Optional[str] = Field(default=None, alias="TEST_ALPACA_API_SECRET")
    stage_alpaca_api_key: Optional[str] = Field(default=None, alias="STAGE_ALPACA_API_KEY")
    stage_alpaca_api_secret: Optional[str] = Field(default=None, alias="STAGE_ALPACA_API_SECRET")
    prod_alpaca_api_key: Optional[str] = Field(default=None, alias="PROD_ALPACA_API_KEY")
    prod_alpaca_api_secret: Optional[str] = Field(default=None, alias="PROD_ALPACA_API_SECRET")

    # ----------- Alpaca Broker -------------
    sandbox_alpaca_broker_api_key: Optional[str] = Field(default=None, alias="SANDBOX_ALPACA_BROKER_API_KEY")
    sandbox_alpaca_broker_api_secret: Optional[str] = Field(default=None, alias="SANDBOX_ALPACA_BROKER_API_SECRET")
    live_alpaca_broker_api_key: Optional[str] = Field(default=None, alias="LIVE_ALPACA_BROKER_API_KEY")
    live_alpaca_broker_api_secret: Optional[str] = Field(default=None, alias="LIVE_ALPACA_BROKER_API_SECRET")

    # # ---------- Orders-DB RDS -----------
    # orders_db_write_host: str = Field(alias="ORDERS_DB_WRITE_HOST")
    # orders_db_write_port: str = Field(alias="ORDERS_DB_WRITE_PORT")
    # orders_db_write_database: str = Field(alias="ORDERS_DB_WRITE_DATABASE")
    # orders_db_write_user: str = Field(alias="ORDERS_DB_WRITE_USER")
    # orders_db_write_password: str = Field(alias="ORDERS_DB_WRITE_PASSWORD")

    # ---------- Validators / derived values ----------
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
    def _validate_alpaca_env(cls, v: Any) -> str:
        alpaca_env = str(v or "sandbox").strip().lower()
        if alpaca_env not in {"sandbox", "live"}:
            raise ValueError("ALPACA_ENV must be either 'sandbox' or 'live'")
        return alpaca_env

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
    def portfolio_allocation_dynamodb(self) -> str:
        """Full table name with environment prefix: {env}{suffix}"""
        return f"{self.env}{self.portfolio_allocation_dynamodb_suffix}"
    
    @property
    def order_dynamodb(self) -> str:
        """Full table name with environment prefix: {env}{suffix}"""
        return f"{self.env}{self.order_dynamodb_suffix}"
    
    @property
    def model_portfolio_follower_dynamodb(self) -> str:
        """Full table name with environment prefix: {env}{suffix}"""
        return f"{self.env}{self.model_portfolio_follower_dynamodb_suffix}"
    
    @property
    def user_trade_lock_dynamodb(self) -> str:
        """Full table name with environment prefix:: {env}{suffix}"""
        return f"{self.env}{self.user_trade_lock_dynamodb_suffix}"

    @property
    def user_account_dynamodb(self) -> str:
        """Full table name with environment prefix: {env}{suffix}"""
        return f"{self.env}{self.user_account_dynamodb_suffix}"
    
    @property
    def model_portfolio_update_lock_dynamodb(self) -> str:
        """Full table name with environment prefix: {env}{suffix}"""
        return f"{self.env}{self.model_portfolio_update_lock_suffix}"

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
            f"Set {self.env.upper()}_COGNTIO_REGION in your .env file"
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
