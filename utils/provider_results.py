# -*- coding: utf-8 -*-
"""
Provider result validation and sanitization helpers.

Keeps validation out of QGIS-bound code paths so it can be unit tested headlessly.
"""
from typing import Any, Dict, List, Tuple


def _coerce_float(value: Any) -> float:
    """Try to coerce to float; raises ValueError on failure."""
    if value is None:
        raise ValueError("value is None")
    return float(value)


def filter_positions(positions: Any) -> Tuple[List[Dict[str, Any]], int]:
    """
    Validate and filter provider position records.

    Expected keys: device_id, name, ts, lat, lon. Invalid entries are dropped.
    Returns cleaned list and count of dropped records.
    """
    cleaned: List[Dict[str, Any]] = []
    dropped = 0

    if not positions:
        return cleaned, dropped

    if not isinstance(positions, list):
        return cleaned, 1

    for pos in positions:
        try:
            if not isinstance(pos, dict):
                raise ValueError("not a dict")

            device_id = pos.get("device_id")
            name = pos.get("name")
            ts = pos.get("ts")
            lat = _coerce_float(pos.get("lat"))
            lon = _coerce_float(pos.get("lon"))

            if not device_id or not isinstance(device_id, str):
                raise ValueError("invalid device_id")
            if not name or not isinstance(name, str):
                raise ValueError("invalid name")
            if not ts:
                raise ValueError("missing ts")
            if not (-90 <= lat <= 90):
                raise ValueError("lat out of range")
            if not (-180 <= lon <= 180):
                raise ValueError("lon out of range")

            # Preserve original dict but ensure lat/lon are floats
            cleaned.append({**pos, "lat": lat, "lon": lon})
        except Exception:
            dropped += 1
            continue

    return cleaned, dropped


def filter_devices(devices: Any) -> Tuple[List[Dict[str, Any]], int]:
    """
    Validate and filter device summary records.

    Requires device_id at minimum; keeps other keys as-is. Invalid entries are dropped.
    """
    cleaned: List[Dict[str, Any]] = []
    dropped = 0

    if not devices:
        return cleaned, dropped

    if not isinstance(devices, list):
        return cleaned, 1

    for dev in devices:
        try:
            if not isinstance(dev, dict):
                raise ValueError("not a dict")
            device_id = dev.get("device_id") or dev.get("id")
            if not device_id or not isinstance(device_id, str):
                raise ValueError("invalid device_id")
            cleaned.append({**dev, "device_id": device_id})
        except Exception:
            dropped += 1
            continue

    return cleaned, dropped


def sanitize_provider_results(results: Any) -> Tuple[Dict[str, Any], Dict[str, int]]:
    """
    Sanitize provider task results for safe layer updates.

    Returns (sanitized_results, drop_counts) where drop_counts includes counts for
    current, breadcrumbs, and devices.
    """
    payload = results or {}

    current, dropped_current = filter_positions(payload.get("current", []))
    breadcrumbs, dropped_breadcrumbs = filter_positions(payload.get("breadcrumbs", []))
    devices, dropped_devices = filter_devices(payload.get("devices", []))

    sanitized = {
        "current": current,
        "breadcrumbs": breadcrumbs,
        "devices": devices,
        "breadcrumb_processing": payload.get("breadcrumb_processing"),
    }
    dropped = {
        "current": dropped_current,
        "breadcrumbs": dropped_breadcrumbs,
        "devices": dropped_devices,
    }
    return sanitized, dropped
