from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from decimal import Decimal
import json
from pathlib import Path
from typing import Any

import pytest
from dotenv import load_dotenv


repo_root = Path(__file__).resolve().parents[2]
backend_dir = Path(__file__).resolve().parents[1]
for import_path in (str(backend_dir), str(repo_root)):
    if import_path not in sys.path:
        sys.path.insert(0, import_path)

load_dotenv(repo_root / ".env")

from core.config import get_settings
from core.deps import get_boto3_session


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
    parser.addoption(
        "--skip_resource_leak_report",
        action="store_true",
        default=False,
        help="Skip tests_v2 DynamoDB/Cognito before-after leak reporting.",
    )


def _json_safe(value: Any) -> Any:
    if isinstance(value, Decimal):
        if value % 1 == 0:
            return int(value)
        return float(value)
    if isinstance(value, dict):
        return {str(key): _json_safe(nested_value) for key, nested_value in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, set):
        return sorted(_json_safe(item) for item in value)
    return value


def _stable_json(value: Any) -> str:
    return json.dumps(_json_safe(value), sort_keys=True, default=str)


def _dynamodb_table_names() -> list[str]:
    settings = get_settings()
    return list(
        dict.fromkeys(
            [
                settings.allocation_dynamodb,
                settings.baskt_account_dynamodb,
                settings.model_portfolios_dynamodb,
                settings.model_portfolio_access_dynamodb,
                settings.model_portfolio_follower_dynamodb,
                settings.model_portfolio_update_lock_dynamodb,
                settings.order_dynamodb,
                settings.user_trade_lock_dynamodb,
            ]
        )
    )


def _scan_table_items(table: Any) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    scan_kwargs: dict[str, Any] = {}
    while True:
        response = table.scan(**scan_kwargs)
        items.extend(response.get("Items", []))
        last_evaluated_key = response.get("LastEvaluatedKey")
        if not last_evaluated_key:
            return items
        scan_kwargs["ExclusiveStartKey"] = last_evaluated_key


def _table_primary_key(item: dict[str, Any], key_names: list[str]) -> dict[str, Any]:
    return {key_name: item.get(key_name) for key_name in key_names}


def _snapshot_dynamodb_records() -> dict[str, dict[str, dict[str, Any]]]:
    session = get_boto3_session()
    settings = get_settings()
    dynamodb = session.resource("dynamodb", region_name=settings.aws_region)
    snapshot: dict[str, dict[str, dict[str, Any]]] = {}
    for table_name in _dynamodb_table_names():
        table = dynamodb.Table(table_name)
        key_names = [key["AttributeName"] for key in table.key_schema]
        table_snapshot: dict[str, dict[str, Any]] = {}
        for item in _scan_table_items(table):
            primary_key = _table_primary_key(item=item, key_names=key_names)
            table_snapshot[_stable_json(primary_key)] = item
        snapshot[table_name] = table_snapshot
    return snapshot


def _format_cognito_user(user: dict[str, Any]) -> dict[str, Any]:
    attributes = {
        attribute.get("Name"): attribute.get("Value")
        for attribute in user.get("Attributes", [])
    }
    return {
        "username": user.get("Username"),
        "email": attributes.get("email"),
        "alpaca_account_id": attributes.get("custom:alpaca_acct_id"),
        "status": user.get("UserStatus"),
        "enabled": user.get("Enabled"),
        "created_at": user.get("UserCreateDate"),
        "updated_at": user.get("UserLastModifiedDate"),
    }


def _snapshot_cognito_users() -> dict[str, dict[str, Any]]:
    settings = get_settings()
    if not settings.cognito_user_pool_id:
        return {}
    session = get_boto3_session()
    client = session.client("cognito-idp", region_name=settings.cognito_region)
    paginator = client.get_paginator("list_users")
    users: dict[str, dict[str, Any]] = {}
    for page in paginator.paginate(UserPoolId=settings.cognito_user_pool_id):
        for user in page.get("Users", []):
            username = str(user.get("Username"))
            users[username] = _format_cognito_user(user)
    return users


def _snapshot_test_resources() -> dict[str, Any]:
    return {
        "dynamodb": _snapshot_dynamodb_records(),
        "cognito": _snapshot_cognito_users(),
    }


def _new_dynamodb_records(
    before: dict[str, dict[str, dict[str, Any]]],
    after: dict[str, dict[str, dict[str, Any]]],
) -> dict[str, list[dict[str, Any]]]:
    leaked_records: dict[str, list[dict[str, Any]]] = {}
    for table_name, after_items in after.items():
        before_keys = set(before.get(table_name, {}))
        new_keys = sorted(set(after_items) - before_keys)
        if new_keys:
            leaked_records[table_name] = [after_items[key] for key in new_keys]
    return leaked_records


def _new_cognito_users(
    before: dict[str, dict[str, Any]],
    after: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    before_usernames = set(before)
    return [after[username] for username in sorted(set(after) - before_usernames)]


def _print_resource_leak_report(
    *,
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
    before_error: Exception | None,
    after_error: Exception | None,
) -> None:
    print("\n================ tests_v2 resource cleanup report ================")
    print(f"Environment: {get_settings().env}")
    if before_error is not None:
        print(f"Could not capture pre-test resource snapshot: {before_error}")
    if after_error is not None:
        print(f"Could not capture post-test resource snapshot: {after_error}")
    if before is None or after is None:
        print("Resource cleanup comparison skipped because a snapshot failed.")
        print("==================================================================\n")
        return

    leaked_records = _new_dynamodb_records(
        before=before["dynamodb"],
        after=after["dynamodb"],
    )
    leaked_users = _new_cognito_users(
        before=before["cognito"],
        after=after["cognito"],
    )

    if not leaked_records and not leaked_users:
        print("No new DynamoDB records or Cognito users remain after this run.")
        print("==================================================================\n")
        return

    if leaked_records:
        print("New DynamoDB records still present after this run:")
        for table_name, records in leaked_records.items():
            print(f"- {table_name}: {len(records)} new record(s)")
            for record in records:
                print(_stable_json(record))
    else:
        print("No new DynamoDB records remain after this run.")

    if leaked_users:
        print("New Cognito users still present after this run:")
        for user in leaked_users:
            print(_stable_json(user))
    else:
        print("No new Cognito users remain after this run.")
    print("==================================================================\n")


def pytest_sessionstart(session):
    if session.config.getoption("--skip_resource_leak_report"):
        session.config._tests_v2_resource_snapshot_before = None
        session.config._tests_v2_resource_snapshot_before_error = None
        return

    try:
        session.config._tests_v2_resource_snapshot_before = _snapshot_test_resources()
        session.config._tests_v2_resource_snapshot_before_error = None
    except Exception as error:
        session.config._tests_v2_resource_snapshot_before = None
        session.config._tests_v2_resource_snapshot_before_error = error


def pytest_sessionfinish(session, exitstatus):
    if session.config.getoption("--skip_resource_leak_report"):
        return

    before = getattr(session.config, "_tests_v2_resource_snapshot_before", None)
    before_error = getattr(
        session.config,
        "_tests_v2_resource_snapshot_before_error",
        None,
    )
    try:
        after = _snapshot_test_resources()
        after_error = None
    except Exception as error:
        after = None
        after_error = error

    _print_resource_leak_report(
        before=before,
        after=after,
        before_error=before_error,
        after_error=after_error,
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
