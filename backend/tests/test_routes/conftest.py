from __future__ import annotations

import sys
import os
from dataclasses import dataclass
from pathlib import Path

import pytest
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.testclient import TestClient

backend_dir = Path(__file__).resolve().parents[2]
repo_root = Path(__file__).resolve().parents[3]
for import_path in (str(backend_dir), str(repo_root)):
    if import_path not in sys.path:
        sys.path.insert(0, import_path)

load_dotenv(repo_root / ".env")

from core.authentication import (
    get_current_user,
)


@dataclass(frozen=True)
class RouteTestUserIds:
    cognito_user_id: str
    alpaca_account_id: str


def _test_env_prefix() -> str:
    return os.getenv("ENV", "dev").strip().upper()


def _required_env_value(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is required for route tests")
    return value


def _test_user_ids(number: int) -> RouteTestUserIds:
    env_prefix = _test_env_prefix()
    return RouteTestUserIds(
        cognito_user_id=_required_env_value(
            f"{env_prefix}_TEST_USER_{number}_COGNITO_USER_ID"
        ),
        alpaca_account_id=_required_env_value(
            f"{env_prefix}_TEST_USER_{number}_ALPACA_ACCOUNT_ID"
        ),
    )


OWNER_TEST_USER = _test_user_ids(2)
OTHER_TEST_USER = _test_user_ids(1)
OWNER_USER_ID = OWNER_TEST_USER.cognito_user_id
OTHER_USER_ID = OTHER_TEST_USER.cognito_user_id
OWNER_ALPACA_ACCOUNT_ID = OWNER_TEST_USER.alpaca_account_id
OTHER_ALPACA_ACCOUNT_ID = OTHER_TEST_USER.alpaca_account_id


@pytest.fixture
def app_factory():
    def build_app(
        *routers,
        cognito_user_id: str = OTHER_USER_ID,
        alpaca_account_id: str = OTHER_ALPACA_ACCOUNT_ID,
    ):
        app = FastAPI()
        for router in routers:
            app.include_router(router)
        app.dependency_overrides[get_current_user] = lambda: {
            "sub": cognito_user_id,
            "custom:alpaca_acct_id": alpaca_account_id,
        }
        return app

    return build_app


@pytest.fixture
def client_for_app():
    def build_client(app: FastAPI) -> TestClient:
        return TestClient(app)

    return build_client
