# backend/core/timeutils.py

# Python imports
from __future__ import annotations
from datetime import datetime, timezone

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