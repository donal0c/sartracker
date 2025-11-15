# -*- coding: utf-8 -*-
"""
Time parsing and manipulation utilities for SAR Tracker.

Provides ISO8601 parsing, formatting, and time window operations for
provider data handling. All functions follow mandatory validation patterns
defined in AI_CODE_REFERENCE.md.

Qt5/Qt6 Compatible: Pure Python implementation with no Qt dependencies.
Thread-safe: All functions are stateless and safe for concurrent use.

Classification: CRITICAL - LIFE SAFETY SYSTEM
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Tuple, Optional

logger = logging.getLogger(__name__)


def parse_iso(ts: str) -> datetime:
    """
    Parse ISO8601 timestamp string to timezone-aware datetime in UTC.

    Accepts multiple ISO8601 formats:
    - 2025-11-15T14:30:00Z
    - 2025-11-15T14:30:00+00:00
    - 2025-11-15T14:30:00-05:00
    - 2025-11-15T14:30:00.123456Z

    Input Validation (AI_CODE_REFERENCE.md):
    - Validates input is non-empty string
    - Validates timestamp format is ISO8601 compliant
    - Ensures result is timezone-aware (UTC)

    Args:
        ts: ISO8601 timestamp string

    Returns:
        Timezone-aware datetime object in UTC

    Raises:
        ValueError: If timestamp string is invalid or cannot be parsed

    Examples:
        >>> dt = parse_iso("2025-11-15T14:30:00Z")
        >>> dt.tzinfo
        datetime.timezone.utc

        >>> dt = parse_iso("2025-11-15T14:30:00+01:00")
        >>> dt.tzinfo
        datetime.timezone.utc
    """
    # Validate input (MANDATORY - AI_CODE_REFERENCE.md)
    if not ts or not isinstance(ts, str) or not ts.strip():
        raise ValueError("Timestamp string cannot be empty")

    ts = ts.strip()

    try:
        # Try parsing with datetime.fromisoformat (Python 3.7+)
        # This handles most ISO8601 formats including timezones

        # Special case: Replace 'Z' with '+00:00' for fromisoformat compatibility
        if ts.endswith('Z'):
            ts_normalized = ts[:-1] + '+00:00'
        else:
            ts_normalized = ts

        dt = datetime.fromisoformat(ts_normalized)

        # Ensure timezone-aware (convert to UTC if needed)
        if dt.tzinfo is None:
            logger.warning(f"Timestamp missing timezone, assuming UTC: {ts}")
            dt = dt.replace(tzinfo=timezone.utc)
        elif dt.tzinfo != timezone.utc:
            # Convert to UTC
            dt = dt.astimezone(timezone.utc)

        logger.debug(f"Parsed timestamp: {ts} -> {dt}")
        return dt

    except ValueError as e:
        raise ValueError(f"Invalid ISO8601 timestamp: {ts}. Error: {str(e)}")


def format_iso(dt: datetime) -> str:
    """
    Format datetime to ISO8601 string in UTC with 'Z' suffix.

    Output format: YYYY-MM-DDTHH:MM:SSZ (always UTC)

    Input Validation (AI_CODE_REFERENCE.md):
    - Validates input is datetime instance
    - Ensures datetime is timezone-aware
    - Converts to UTC before formatting

    Args:
        dt: Datetime object (timezone-aware recommended)

    Returns:
        ISO8601 formatted string in UTC with 'Z' suffix

    Raises:
        ValueError: If dt is not a datetime instance

    Examples:
        >>> from datetime import datetime, timezone
        >>> dt = datetime(2025, 11, 15, 14, 30, 0, tzinfo=timezone.utc)
        >>> format_iso(dt)
        '2025-11-15T14:30:00Z'
    """
    # Validate input (MANDATORY - AI_CODE_REFERENCE.md)
    if not isinstance(dt, datetime):
        raise ValueError(f"Input must be datetime instance, got {type(dt).__name__}")

    # Ensure timezone-aware
    if dt.tzinfo is None:
        logger.warning("Datetime missing timezone, assuming UTC")
        dt = dt.replace(tzinfo=timezone.utc)
    elif dt.tzinfo != timezone.utc:
        # Convert to UTC
        dt = dt.astimezone(timezone.utc)

    # Format as ISO8601 with Z suffix (remove microseconds for cleaner output)
    formatted = dt.replace(microsecond=0).strftime('%Y-%m-%dT%H:%M:%SZ')

    logger.debug(f"Formatted datetime: {dt} -> {formatted}")
    return formatted


def window(hours: int, reference_time: Optional[datetime] = None) -> Tuple[str, str]:
    """
    Generate time window (from, to) as ISO8601 strings relative to reference time.

    Returns a tuple of (from_iso, to_iso) representing a time window from
    (reference_time - hours) to reference_time, both in UTC.

    Input Validation (AI_CODE_REFERENCE.md):
    - Validates hours is positive integer
    - Validates reference_time is datetime if provided

    Args:
        hours: Number of hours to look back from reference time
        reference_time: Reference datetime (default: current time in UTC)

    Returns:
        Tuple of (from_iso, to_iso) as ISO8601 strings in UTC

    Raises:
        ValueError: If hours is not positive integer

    Examples:
        >>> from_iso, to_iso = window(hours=2)
        >>> # Returns time window from 2 hours ago to now
    """
    # Validate input (MANDATORY - AI_CODE_REFERENCE.md)
    if not isinstance(hours, int) or hours <= 0:
        raise ValueError(f"hours must be positive integer, got {hours}")

    # Use provided reference time or current time in UTC
    if reference_time is None:
        to_dt = datetime.now(timezone.utc)
    else:
        if not isinstance(reference_time, datetime):
            raise ValueError(f"reference_time must be datetime, got {type(reference_time).__name__}")

        # Ensure timezone-aware
        if reference_time.tzinfo is None:
            to_dt = reference_time.replace(tzinfo=timezone.utc)
        else:
            to_dt = reference_time.astimezone(timezone.utc)

    # Calculate from time
    from_dt = to_dt - timedelta(hours=hours)

    # Format both as ISO8601
    from_iso = format_iso(from_dt)
    to_iso = format_iso(to_dt)

    logger.debug(f"Time window: {hours}h -> ({from_iso}, {to_iso})")
    return (from_iso, to_iso)


def is_gap(prev_ts: str, curr_ts: str, gap_minutes: int) -> bool:
    """
    Check if there is a time gap between two timestamps.

    A gap is detected when the difference between curr_ts and prev_ts
    exceeds gap_minutes.

    Input Validation (AI_CODE_REFERENCE.md):
    - Validates both timestamps are valid ISO8601 strings
    - Validates gap_minutes is positive integer
    - Ensures timestamps are in chronological order

    Args:
        prev_ts: Previous timestamp (ISO8601 string)
        curr_ts: Current timestamp (ISO8601 string)
        gap_minutes: Gap threshold in minutes

    Returns:
        True if gap exceeds threshold, False otherwise

    Raises:
        ValueError: If timestamps invalid or gap_minutes not positive

    Examples:
        >>> is_gap("2025-11-15T14:00:00Z", "2025-11-15T14:05:00Z", gap_minutes=10)
        False

        >>> is_gap("2025-11-15T14:00:00Z", "2025-11-15T14:15:00Z", gap_minutes=10)
        True
    """
    # Validate input (MANDATORY - AI_CODE_REFERENCE.md)
    if not isinstance(gap_minutes, int) or gap_minutes <= 0:
        raise ValueError(f"gap_minutes must be positive integer, got {gap_minutes}")

    # Parse both timestamps (will raise ValueError if invalid)
    prev_dt = parse_iso(prev_ts)
    curr_dt = parse_iso(curr_ts)

    # Ensure chronological order
    if curr_dt < prev_dt:
        logger.warning(f"Timestamps not in chronological order: {prev_ts} > {curr_ts}")
        # Swap for comparison
        prev_dt, curr_dt = curr_dt, prev_dt

    # Calculate time difference
    time_diff = curr_dt - prev_dt
    diff_minutes = time_diff.total_seconds() / 60

    is_gap_detected = diff_minutes > gap_minutes

    logger.debug(
        f"Gap check: {prev_ts} -> {curr_ts} "
        f"(diff={diff_minutes:.1f}min, threshold={gap_minutes}min) "
        f"-> {'GAP' if is_gap_detected else 'OK'}"
    )

    return is_gap_detected


def clamp_to_interval(ts: str, start: str, end: str) -> str:
    """
    Clamp timestamp to interval [start, end].

    If ts is before start, returns start.
    If ts is after end, returns end.
    Otherwise, returns ts unchanged.

    Input Validation (AI_CODE_REFERENCE.md):
    - Validates all timestamps are valid ISO8601 strings
    - Ensures start <= end

    Args:
        ts: Timestamp to clamp (ISO8601 string)
        start: Interval start (ISO8601 string)
        end: Interval end (ISO8601 string)

    Returns:
        Clamped timestamp as ISO8601 string

    Raises:
        ValueError: If timestamps invalid or start > end

    Examples:
        >>> clamp_to_interval(
        ...     "2025-11-15T12:00:00Z",
        ...     "2025-11-15T14:00:00Z",
        ...     "2025-11-15T16:00:00Z"
        ... )
        '2025-11-15T14:00:00Z'  # Clamped to start

        >>> clamp_to_interval(
        ...     "2025-11-15T15:00:00Z",
        ...     "2025-11-15T14:00:00Z",
        ...     "2025-11-15T16:00:00Z"
        ... )
        '2025-11-15T15:00:00Z'  # Within interval, unchanged
    """
    # Parse all timestamps (will raise ValueError if invalid)
    ts_dt = parse_iso(ts)
    start_dt = parse_iso(start)
    end_dt = parse_iso(end)

    # Validate interval (MANDATORY - AI_CODE_REFERENCE.md)
    if start_dt > end_dt:
        raise ValueError(f"Invalid interval: start ({start}) is after end ({end})")

    # Clamp to interval
    if ts_dt < start_dt:
        clamped_dt = start_dt
        logger.debug(f"Clamped {ts} to interval start {start}")
    elif ts_dt > end_dt:
        clamped_dt = end_dt
        logger.debug(f"Clamped {ts} to interval end {end}")
    else:
        clamped_dt = ts_dt
        logger.debug(f"Timestamp {ts} within interval, unchanged")

    return format_iso(clamped_dt)


def seconds_between(ts1: str, ts2: str) -> float:
    """
    Calculate absolute time difference in seconds between two timestamps.

    Useful for timeout calculations and performance measurements.

    Input Validation (AI_CODE_REFERENCE.md):
    - Validates both timestamps are valid ISO8601 strings

    Args:
        ts1: First timestamp (ISO8601 string)
        ts2: Second timestamp (ISO8601 string)

    Returns:
        Absolute time difference in seconds (always positive)

    Raises:
        ValueError: If timestamps invalid

    Examples:
        >>> seconds_between("2025-11-15T14:00:00Z", "2025-11-15T14:05:30Z")
        330.0
    """
    # Parse timestamps (will raise ValueError if invalid)
    dt1 = parse_iso(ts1)
    dt2 = parse_iso(ts2)

    # Calculate absolute difference
    diff = abs((dt2 - dt1).total_seconds())

    logger.debug(f"Time difference: {ts1} <-> {ts2} = {diff}s")
    return diff


def is_recent(ts: str, max_age_minutes: int, reference_time: Optional[datetime] = None) -> bool:
    """
    Check if timestamp is recent (within max_age_minutes of reference time).

    Useful for validating data freshness in life-safety contexts.

    Input Validation (AI_CODE_REFERENCE.md):
    - Validates timestamp is valid ISO8601 string
    - Validates max_age_minutes is positive integer

    Args:
        ts: Timestamp to check (ISO8601 string)
        max_age_minutes: Maximum age in minutes
        reference_time: Reference datetime (default: current time in UTC)

    Returns:
        True if timestamp is within max_age_minutes of reference_time

    Raises:
        ValueError: If timestamp invalid or max_age_minutes not positive

    Examples:
        >>> # Check if timestamp is within last 15 minutes
        >>> is_recent("2025-11-15T14:58:00Z", max_age_minutes=15)
        True  # If current time is ~15:00:00Z
    """
    # Validate input (MANDATORY - AI_CODE_REFERENCE.md)
    if not isinstance(max_age_minutes, int) or max_age_minutes <= 0:
        raise ValueError(f"max_age_minutes must be positive integer, got {max_age_minutes}")

    # Parse timestamp
    ts_dt = parse_iso(ts)

    # Get reference time
    if reference_time is None:
        ref_dt = datetime.now(timezone.utc)
    else:
        if not isinstance(reference_time, datetime):
            raise ValueError(f"reference_time must be datetime, got {type(reference_time).__name__}")

        if reference_time.tzinfo is None:
            ref_dt = reference_time.replace(tzinfo=timezone.utc)
        else:
            ref_dt = reference_time.astimezone(timezone.utc)

    # Calculate age
    age = ref_dt - ts_dt
    age_minutes = age.total_seconds() / 60

    is_recent_flag = 0 <= age_minutes <= max_age_minutes

    logger.debug(
        f"Recency check: {ts} age={age_minutes:.1f}min "
        f"(max={max_age_minutes}min) -> {'RECENT' if is_recent_flag else 'STALE'}"
    )

    return is_recent_flag
