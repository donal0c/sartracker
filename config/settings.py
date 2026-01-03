"""
SAR Tracker Configuration

Centralized configuration for tunable settings.
This file addresses SAR-kz7 for settings that should be easily adjustable
without digging through the codebase.

Note: This file is for operational parameters only.
- User preferences belong in QSettings
- Credentials belong in secure_store
"""

# =============================================================================
# DEVICE TRACKING SETTINGS (FR-6: Active Device Filtering)
# =============================================================================

# Threshold in seconds for considering an "unknown" status device as "stale"
# Devices with status="unknown" and last_update older than this are hidden
# from the SAR Panel device list. Online devices are always shown.
# Default: 3600 seconds (1 hour) - agreed with Kerry Mountain Rescue team
ACTIVE_DEVICE_STALE_THRESHOLD_SECONDS = 3600


# =============================================================================
# FUTURE SETTINGS (placeholders for SAR-kz7 expansion)
# =============================================================================

# Traccar polling interval (seconds)
# TRACCAR_POLLING_INTERVAL_SECONDS = 30

# Cache expiration time (seconds)
# CACHE_EXPIRATION_SECONDS = 300
