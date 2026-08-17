from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest
from dotenv import load_dotenv


repo_root = Path(__file__).resolve().parents[2]
backend_dir = Path(__file__).resolve().parents[1]
for import_path in (str(backend_dir), str(repo_root)):
    if import_path not in sys.path:
        sys.path.insert(0, import_path)

load_dotenv(repo_root / ".env")

from core.config import get_settings


get_settings.cache_clear()


@dataclass(frozen=True)
class RepositoryTestUser:
    cognito_user_id: str
    alpaca_account_id: str
    email_address: str


def pytest_addoption(parser):
    parser.addoption(
        "--mock_alpaca",
        action="store_true",
        default=False,
        help="Use in-memory mock Alpaca/SQS clients where tests support them.",
    )


def _required_env_value(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is required for tests_v2 integration tests")
    return value


def _test_user(number: int) -> RepositoryTestUser:
    env_prefix = get_settings().env.upper()
    return RepositoryTestUser(
        cognito_user_id=_required_env_value(
            f"{env_prefix}_TEST_USER_{number}_COGNITO_USER_ID"
        ),
        alpaca_account_id=_required_env_value(
            f"{env_prefix}_TEST_USER_{number}_ALPACA_ACCOUNT_ID"
        ),
        email_address=_required_env_value(
            f"{env_prefix}_TEST_USER_{number}_EMAIL_ADDRESS"
        ),
    )


@pytest.fixture(scope="session")
def test_user_1() -> RepositoryTestUser:
    return _test_user(1)


@pytest.fixture(scope="session")
def test_user_2() -> RepositoryTestUser:
    return _test_user(2)
