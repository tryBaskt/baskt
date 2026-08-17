from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


repo_root = Path(__file__).resolve().parents[2]
load_dotenv(repo_root / ".env")


@dataclass(frozen=True)
class TestUserIds:
    cognito_user_id: str
    alpaca_account_id: str


def _test_env_prefix() -> str:
    return os.getenv("ENV", "dev").strip().upper()


def _required_env_value(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is required for tests")
    return value


def get_test_user_ids(number: int) -> TestUserIds:
    env_prefix = _test_env_prefix()
    return TestUserIds(
        cognito_user_id=_required_env_value(
            f"{env_prefix}_TEST_USER_{number}_COGNITO_USER_ID"
        ),
        alpaca_account_id=_required_env_value(
            f"{env_prefix}_TEST_USER_{number}_ALPACA_ACCOUNT_ID"
        ),
    )


def pytest_addoption(parser):
    parser.addoption(
        "--mock_alpaca",
        action="store_true",
        default=False,
        help="Use in-memory mock Alpaca/SQS clients where tests support them.",
    )
