"""Enable the trade worker only during the 2026 U.S. core trading session."""

from __future__ import annotations

import os
from datetime import date, datetime, time, timedelta
from functools import lru_cache
from time import sleep
from typing import Any, Dict
from zoneinfo import ZoneInfo

import boto3


EASTERN = ZoneInfo("America/New_York")
MARKET_OPEN = time(9, 30)
REGULAR_CLOSE = time(16, 0)

MARKET_HOLIDAYS_2026 = {
    date(2026, 1, 1),
    date(2026, 1, 19),
    date(2026, 2, 16),
    date(2026, 4, 3),
    date(2026, 5, 25),
    date(2026, 6, 19),
    date(2026, 7, 3),
    date(2026, 9, 7),
    date(2026, 11, 26),
    date(2026, 12, 25),
}

EARLY_CLOSES_2026 = {
    date(2026, 11, 27): time(13, 0),
    date(2026, 12, 24): time(13, 0),
}

@lru_cache
def _lambda_client() -> Any:
    """Return the cached AWS Lambda control-plane client."""
    return boto3.client("lambda")


def _session_for_day(current_date: date) -> tuple[time, time] | None:
    """Return the core session bounds, or None when the market is closed."""
    if current_date.year != 2026:
        return None
    if current_date.weekday() >= 5 or current_date in MARKET_HOLIDAYS_2026:
        return None
    return MARKET_OPEN, EARLY_CLOSES_2026.get(current_date, REGULAR_CLOSE)


def _event_source_mapping() -> Dict[str, Any]:
    """Return the sole SQS mapping for the trade worker."""
    mappings = _lambda_client().list_event_source_mappings(
        FunctionName=os.environ["TRADE_EXECUTION_FUNCTION_NAME"],
        EventSourceArn=os.environ["TRADE_EXECUTION_QUEUE_ARN"],
    )["EventSourceMappings"]
    if len(mappings) != 1:
        raise RuntimeError(
            f"Expected one trade event-source mapping, found {len(mappings)}."
        )
    return mappings[0]


def _set_mapping_enabled(enabled: bool) -> bool:
    """Set the mapping state when it differs from the desired state."""
    mapping = _event_source_mapping()
    state = mapping["State"]
    if state in {"Creating", "Enabling", "Disabling", "Updating"}:
        return False
    if (state == "Enabled") == enabled:
        return False
    _lambda_client().update_event_source_mapping(
        UUID=mapping["UUID"],
        Enabled=enabled,
    )
    return True


def _warm_worker() -> None:
    """Initialize one worker execution environment before the open."""
    response = _lambda_client().invoke(
        FunctionName=os.environ["TRADE_EXECUTION_FUNCTION_NAME"],
        InvocationType="RequestResponse",
        Payload=b'{"action":"warmup"}',
    )
    if response.get("FunctionError"):
        raise RuntimeError("Trade execution worker warm-up failed.")


def _wait_until_thirty_seconds_before_close(
    now: datetime,
    close_time: time,
) -> None:
    """Wait until thirty seconds before today's scheduled market close."""
    disable_at = datetime.combine(
        now.date(),
        close_time,
        tzinfo=EASTERN,
    ) - timedelta(seconds=30)
    delay_seconds = (disable_at - now).total_seconds()
    if delay_seconds > 0:
        sleep(delay_seconds)


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Handle prepare, open, early-close, close, and deployment sync events."""
    action = event.get("action")
    now = datetime.now(EASTERN)
    session = _session_for_day(now.date())

    if action == "prepare":
        _set_mapping_enabled(False)
        if session is not None:
            _warm_worker()
        return {
            "trading_day": session is not None,
            "close": session[1].isoformat() if session else None,
        }

    if action == "open":
        changed = _set_mapping_enabled(session is not None)
        return {"enabled": session is not None, "changed": changed}

    if action == "early_close":
        should_close = session is not None and session[1] == time(13, 0)
        if should_close:
            _wait_until_thirty_seconds_before_close(now, session[1])
        changed = _set_mapping_enabled(False) if should_close else False
        return {"closed": should_close, "changed": changed}

    if action == "close":
        if session is not None and session[1] == REGULAR_CLOSE:
            _wait_until_thirty_seconds_before_close(now, session[1])
        return {"closed": True, "changed": _set_mapping_enabled(False)}

    if action == "sync":
        should_enable = (
            session is not None and session[0] <= now.time() < session[1]
        )
        return {
            "enabled": should_enable,
            "changed": _set_mapping_enabled(should_enable),
        }

    raise ValueError(f"Unsupported market-hours action '{action}'.")
