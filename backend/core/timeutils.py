# backend/core/timeutils.py

from __future__ import annotations

from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo


# def get_tz(tz_name: str) -> ZoneInfo:
#     """
#     Return a ZoneInfo timezone object for a given IANA timezone name.
#     Example: "America/New_York"
#     """
#     return ZoneInfo(tz_name)


# def parse_iso_datetime(value: str) -> datetime:
#     """
#     Parse an ISO-8601 datetime string into a timezone-aware datetime.

#     Supports both:
#       - "...Z" (Zulu/UTC)
#       - "...+00:00" offset format

#     If the parsed datetime is naive, assume UTC.
#     """
#     s = value.strip()

#     # Handle trailing Z
#     if s.endswith("Z"):
#         s = s[:-1] + "+00:00"

#     dt = datetime.fromisoformat(s)

#     if dt.tzinfo is None:
#         dt = dt.replace(tzinfo=timezone.utc)

#     return dt


# def iso_utc_to_local_date(iso_str: str, tz_name: str) -> date:
#     """
#     Take an ISO timestamp string stored in Dynamo (usually UTC)
#     and return the corresponding calendar date in the requested timezone.
#     """
#     dt_utc = parse_iso_datetime(iso_str)
#     tz = get_tz(tz_name)
#     return dt_utc.astimezone(tz).date()


def to_utc_from_iso(s: str) -> datetime:
    """
    Parse an ISO string and normalize to UTC-aware datetime.
    
    Handles 'Z' suffix, converts to UTC timezone, and validates input.
    This is specifically designed for parsing timestamps from DynamoDB.
    
    Args:
        s: ISO-8601 formatted datetime string
        
    Returns:
        UTC-aware datetime object
        
    Raises:
        ValueError: If input is not a string or cannot be parsed
    """
    if not isinstance(s, str):
        raise ValueError("Timestamp must be ISO string")
    iso = s.replace("Z", "+00:00")  # make 'Z' compatible with fromisoformat
    dt = datetime.fromisoformat(iso)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# def today_local(tz_name: str) -> date:
#     """
#     Return today's date in the given timezone (not UTC).
#     """
#     tz = get_tz(tz_name)
#     return datetime.now(tz).date()
