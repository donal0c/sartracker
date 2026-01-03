# -*- coding: utf-8 -*-
"""
Device Filtering Utilities (FR-6: Active Device Filtering)

Pure Python business logic for filtering devices to show only active ones.
SAR-5c6: Filter SAR Panel devices_list to show only active devices.

This module has no Qt/QGIS dependencies for easy testing.
"""

from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional

# Default threshold from config - import lazily to avoid circular imports
DEFAULT_THRESHOLD_SECONDS = 3600  # 1 hour


def should_show_device(device: Dict, threshold_seconds: int = DEFAULT_THRESHOLD_SECONDS) -> bool:
    """
    Determine if a device should be shown in the SAR Panel device list.

    Filtering rules (from SAR-qvn):
    - 'online' devices: Always show
    - 'offline' devices: Never show
    - 'unknown' devices: Show if last_update is within threshold

    Args:
        device: Device dict with 'status' and 'last_update' keys
        threshold_seconds: Max age in seconds for unknown devices (default: 1 hour)

    Returns:
        True if device should be shown, False otherwise
    """
    status = device.get('status', 'unknown')

    # Online = always show
    if status == 'online':
        return True

    # Offline = never show
    if status == 'offline':
        return False

    # Unknown status - check last_update age
    last_update = device.get('last_update')
    if not last_update:
        # No last_update - fail safe, hide device
        return False

    # Parse the timestamp and check age
    try:
        if isinstance(last_update, str):
            # Handle ISO8601 format
            ts = last_update.replace('Z', '+00:00')
            update_time = datetime.fromisoformat(ts)
        elif isinstance(last_update, datetime):
            update_time = last_update
        else:
            return False

        # Ensure timezone awareness
        if update_time.tzinfo is None:
            update_time = update_time.replace(tzinfo=timezone.utc)

        now = datetime.now(timezone.utc)
        age_seconds = (now - update_time).total_seconds()

        # Show if within threshold (inclusive)
        return age_seconds <= threshold_seconds
    except (ValueError, TypeError):
        # Parse error - fail safe, hide device
        return False


def get_device_indicator(device: Dict) -> str:
    """
    Get the status indicator emoji for a device.

    Args:
        device: Device dict with 'status' key

    Returns:
        Indicator emoji: green (online), yellow (unknown/stale), red (offline)
    """
    status = device.get('status', 'unknown')

    if status == 'online':
        return '\U0001F7E2'  # Green circle
    elif status == 'offline':
        return '\U0001F534'  # Red circle
    else:
        # Unknown/stale - use yellow instead of white (FR-6 spec)
        return '\U0001F7E1'  # Yellow circle


def filter_devices(
    devices: Optional[List[Dict]],
    threshold_seconds: int = DEFAULT_THRESHOLD_SECONDS
) -> List[Dict]:
    """
    Filter device list to show only active devices.

    FR-6 (SAR-5c6) CORRECTED SPEC:
    - Layer Console (left panel): Shows only ACTIVE device tracking layers
    - SAR Panel devices_list (right panel): Shows ALL devices (no filtering)

    This function provides the filtering logic used by provider_controller
    to determine which device positions should be sent to the layer manager.

    Args:
        devices: List of device dicts from provider
        threshold_seconds: Max age in seconds for unknown devices

    Returns:
        Filtered list of devices to display
    """
    if not devices:
        return []

    return [d for d in devices if should_show_device(d, threshold_seconds)]
