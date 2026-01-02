# -*- coding: utf-8 -*-
"""
Pure-Python helpers for tracking layer data processing.

These functions are intentionally free of QGIS dependencies so they can be
unit-tested without a running QGIS environment.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class SanitizationResult:
    """Simple container summarizing sanitization outcomes."""

    valid: List[Dict[str, Any]]
    invalid_count: int = 0
    last_error: Optional[str] = None


def sanitize_breadcrumb_positions(positions: Optional[List[Dict]]) -> SanitizationResult:
    """
    Validate and normalize raw breadcrumb payloads.

    Returns:
        SanitizationResult with valid points plus summary of skipped records.
    """
    if positions is None:
        return SanitizationResult(valid=[])

    if not isinstance(positions, list):
        raise ValueError("positions must be a list")

    sanitized: List[Dict[str, Any]] = []
    invalid_count = 0
    last_error: Optional[str] = None

    for i, pos in enumerate(positions):
        try:
            sanitized.append(_sanitize_breadcrumb_point(pos, i))
        except ValueError as exc:
            invalid_count += 1
            last_error = str(exc)

    return SanitizationResult(valid=sanitized, invalid_count=invalid_count, last_error=last_error)


def sanitize_current_positions(positions: List[Dict]) -> SanitizationResult:
    """
    Validate and normalize current-position payloads.

    Raises:
        ValueError: if positions is not a list (programming error).
    """
    if not isinstance(positions, list):
        raise ValueError("positions must be a list")

    sanitized: List[Dict[str, Any]] = []
    invalid_count = 0
    last_error: Optional[str] = None

    for i, pos in enumerate(positions):
        try:
            sanitized.append(_sanitize_current_position(pos, i))
        except ValueError as exc:
            invalid_count += 1
            last_error = str(exc)

    return SanitizationResult(valid=sanitized, invalid_count=invalid_count, last_error=last_error)


def _sanitize_breadcrumb_point(pos: Dict[str, Any], index: int) -> Dict[str, Any]:
    if not isinstance(pos, dict):
        raise ValueError(f"Position {index} must be a dictionary")

    required_fields = ["device_id", "name", "ts", "lat", "lon"]
    missing_fields = [field for field in required_fields if field not in pos]
    if missing_fields:
        raise ValueError(f"Position {index} missing required fields: {missing_fields}")

    lat, lon = _coerce_coordinates(pos.get("lat"), pos.get("lon"), index)

    device_id = pos["device_id"]
    name = pos["name"]
    if not device_id or not isinstance(device_id, str):
        raise ValueError(f"Position {index} has invalid device_id (must be non-empty string)")
    if not name or not isinstance(name, str):
        raise ValueError(f"Position {index} has invalid name (must be non-empty string)")

    ts = pos["ts"]
    if not isinstance(ts, str):
        raise ValueError(f"Position {index} has invalid timestamp (must be string)")

    return {
        "device_id": device_id,
        "name": name,
        "ts": ts,
        "lat": lat,
        "lon": lon,
    }


def _sanitize_current_position(pos: Dict[str, Any], index: int) -> Dict[str, Any]:
    if not isinstance(pos, dict):
        raise ValueError(f"Position {index} must be a dictionary")

    required_fields = ["device_id", "name", "ts", "lat", "lon"]
    missing_fields = [field for field in required_fields if field not in pos]
    if missing_fields:
        raise ValueError(f"Position {index} missing required fields: {missing_fields}")

    lat, lon = _coerce_coordinates(pos.get("lat"), pos.get("lon"), index)

    device_id = pos["device_id"]
    name = pos["name"]
    if not device_id or not isinstance(device_id, str):
        raise ValueError(f"Position {index} has invalid device_id (must be non-empty string)")
    if not name or not isinstance(name, str):
        raise ValueError(f"Position {index} has invalid name (must be non-empty string)")

    ts = pos["ts"]
    if not isinstance(ts, str):
        raise ValueError(f"Position {index} has invalid timestamp (must be string)")

    return {
        "device_id": device_id,
        "name": name,
        "ts": ts,
        "lat": lat,
        "lon": lon,
        "altitude": pos.get("altitude"),
        "speed": pos.get("speed"),
        "battery": pos.get("battery"),
    }


def _coerce_coordinates(lat_value: Any, lon_value: Any, index: int) -> (float, float):
    try:
        lat = float(lat_value)
        lon = float(lon_value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Position {index} has invalid lat/lon: {exc}") from exc

    if not (-90 <= lat <= 90):
        raise ValueError(f"Position {index} has invalid latitude: {lat} (must be -90 to 90)")

    if not (-180 <= lon <= 180):
        raise ValueError(f"Position {index} has invalid longitude: {lon} (must be -180 to 180)")

    # SAR-1lt FIX: Reject Null Island (0,0) - common GPS failure indicator
    if abs(lat) < 0.0001 and abs(lon) < 0.0001:
        raise ValueError(f"Position {index} rejected: (0,0) is likely GPS failure, not valid position")

    return lat, lon


# BUG-038 FIX: Maximum positions to process in memory
# Beyond this limit, positions are truncated to prevent memory exhaustion.
# 100,000 positions at ~200 bytes each ≈ 20MB memory usage
MAX_POSITIONS_IN_MEMORY = 100000


def build_segments_from_positions(
    positions: List[Dict[str, Any]],
    time_gap_minutes: float,
) -> List[Dict[str, Any]]:
    """
    Reproduce legacy segmentation logic for fallback scenarios.

    BUG-038 FIX: Enforces MAX_POSITIONS_IN_MEMORY limit to prevent
    memory exhaustion with large datasets. Keeps most recent positions.
    """
    # BUG-038 FIX: Memory guard - truncate if over limit
    if len(positions) > MAX_POSITIONS_IN_MEMORY:
        logger.warning(
            "BUG-038 memory guard - truncating %d positions to %d (keeping most recent)",
            len(positions), MAX_POSITIONS_IN_MEMORY
        )
        # Keep the most recent positions (assumes list is somewhat chronological)
        positions = positions[-MAX_POSITIONS_IN_MEMORY:]

    device_positions: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for pos in positions:
        device_positions[pos["device_id"]].append(pos)

    segments: List[Dict[str, Any]] = []

    for device_id, device_pts in device_positions.items():
        device_pts.sort(key=lambda p: p["ts"])
        if not device_pts:
            continue

        current_segment = [device_pts[0]]
        drawable_segments: List[List[Dict[str, Any]]] = []

        for idx in range(1, len(device_pts)):
            pos = device_pts[idx]
            prev_pos = device_pts[idx - 1]

            try:
                prev_time = parse_iso_timestamp(prev_pos["ts"])
                curr_time = parse_iso_timestamp(pos["ts"])
                gap_minutes = (curr_time - prev_time).total_seconds() / 60.0

                # BUG-067 FIX: Handle out-of-order timestamps (negative gap)
                if gap_minutes < 0:
                    logger.warning(
                        "BUG-067: Out-of-order timestamps for device %s: "
                        "prev=%s, curr=%s (gap=%.1f min). Forcing segment break.",
                        device_id, prev_pos.get("ts"), pos.get("ts"), gap_minutes
                    )
                    gap_minutes = float('inf')  # Force segment break for safety

            except Exception as exc:  # pragma: no cover - defensive logging upstream
                # SAFETY: Cannot determine time gap with invalid timestamps.
                # Force a segment break rather than guessing - prevents incorrect
                # joining of positions that may be hours/days apart.
                # BUG-067 FIX: Use proper logging instead of print
                logger.error(
                    "BUG-067: Could not parse timestamp for device %s: %s "
                    "(prev_ts=%s, curr_ts=%s). Forcing segment break for safety.",
                    device_id, exc, prev_pos.get("ts"), pos.get("ts")
                )
                gap_minutes = float('inf')  # Force segment break

            if gap_minutes > time_gap_minutes:
                if len(current_segment) >= 2:
                    drawable_segments.append(list(current_segment))
                current_segment = [pos]
            else:
                current_segment.append(pos)

        if len(current_segment) >= 2:
            drawable_segments.append(list(current_segment))

        # If we have >=2 points total but produced no drawable segments (e.g., every gap exceeds the
        # threshold), fall back to adjacent pairs so operators see *some* movement history instead
        # of an empty map.
        if not drawable_segments and len(device_pts) >= 2:
            for idx in range(1, len(device_pts)):
                drawable_segments.append([device_pts[idx - 1], device_pts[idx]])

        for seg_points in drawable_segments:
            segments.append(_segment_from_points(device_id, seg_points[0]["name"], seg_points))

    return segments


def _segment_from_points(device_id: str, device_name: str, points: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Convert a list of sanitized points into a standardized segment payload."""
    return {
        "device_id": device_id,
        "name": device_name,
        "points": [
            {
                "lon": point["lon"],
                "lat": point["lat"],
                "ts": point.get("ts"),
            }
            for point in points
        ],
    }


def validate_processed_segments(
    processed_payload: Optional[Dict[str, Any]],
    requested_gap_minutes: float,
) -> Optional[List[Dict[str, Any]]]:
    """
    Validate provider-supplied pre-processed segments.

    Returns:
        List of safe segment payloads, an empty list (meaning no features),
        or None if payload is unusable and we must fallback to raw data.
    """
    if not processed_payload:
        return None

    if isinstance(processed_payload, dict):
        segments = processed_payload.get("segments")
        payload_gap = processed_payload.get("time_gap_minutes", requested_gap_minutes)
    else:
        segments = processed_payload
        payload_gap = requested_gap_minutes

    try:
        gap_value = float(payload_gap)
    except (TypeError, ValueError):
        gap_value = requested_gap_minutes

    if gap_value <= 0 or abs(gap_value - requested_gap_minutes) > 0.001:
        return None

    if segments is None or not isinstance(segments, list):
        return None

    validated: List[Dict[str, Any]] = []
    for segment in segments:
        if not isinstance(segment, dict):
            continue

        device_id = segment.get("device_id")
        name = segment.get("name") or device_id
        points = segment.get("points")

        if not device_id or not isinstance(device_id, str):
            continue
        if not name or not isinstance(name, str):
            name = device_id
        # Allow single-point segments (isolated position reports are valid)
        if not isinstance(points, list) or len(points) < 1:
            continue

        processed_points = []
        valid_segment = True
        for point in points:
            if not isinstance(point, dict):
                valid_segment = False
                break
            try:
                lat = float(point.get("lat"))
                lon = float(point.get("lon"))
            except (TypeError, ValueError):
                valid_segment = False
                break

            if not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
                valid_segment = False
                break
            if abs(lat) < 0.0001 and abs(lon) < 0.0001:
                valid_segment = False
                break

            processed_points.append({"lat": lat, "lon": lon, "ts": point.get("ts")})

        # Include single-point segments (valid for isolated position reports)
        if valid_segment and len(processed_points) >= 1:
            validated.append({"device_id": device_id, "name": name, "points": processed_points})

    return validated if validated else []


def parse_iso_timestamp(timestamp: str) -> datetime:
    """Parse ISO timestamp handling 'Z' suffix."""
    if not isinstance(timestamp, str):
        raise ValueError("Timestamp must be a string")

    ts = timestamp.strip()
    if ts.endswith("Z"):
        ts = ts[:-1] + "+00:00"

    return datetime.fromisoformat(ts)
