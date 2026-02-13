# -*- coding: utf-8 -*-
"""
Centralized QSettings Key Definitions

This module provides a single source of truth for all QSettings keys used
throughout the SAR Tracker plugin. Centralizing keys here prevents typos,
makes refactoring easier, and provides clear documentation of all persisted
settings.

Qt5/Qt6 Compatible: Pure Python constants, no Qt dependencies.

Usage:
    from config.keys import SETTINGS_KEYS
    settings = QSettings()
    settings.setValue(SETTINGS_KEYS.AUTO_REFRESH_ENABLED, True)
"""


import os


class SETTINGS_KEYS:
    """
    Centralized QSettings key definitions.

    All keys use the "SARTracker/" prefix for namespace isolation.
    Keys are organized by functional area for maintainability.
    """

    # ========================================================================
    # AUTO-REFRESH CONFIGURATION
    # ========================================================================
    AUTO_REFRESH_ENABLED = "SARTracker/AutoRefresh/enabled"
    AUTO_REFRESH_INTERVAL = "SARTracker/AutoRefresh/interval_seconds"

    # Defaults
    AUTO_REFRESH_ENABLED_DEFAULT = False
    AUTO_REFRESH_INTERVAL_DEFAULT = 30  # seconds
    AUTO_REFRESH_INTERVAL_MIN = 5
    AUTO_REFRESH_INTERVAL_MAX = 300

    # ========================================================================
    # AUTO-SAVE CONFIGURATION
    # ========================================================================
    AUTO_SAVE_ENABLED = "SARTracker/AutoSave/enabled"
    AUTO_SAVE_INTERVAL = "SARTracker/AutoSave/interval_minutes"

    # Defaults
    AUTO_SAVE_ENABLED_DEFAULT = False
    AUTO_SAVE_INTERVAL_DEFAULT = 5  # minutes
    AUTO_SAVE_INTERVAL_MIN = 1
    AUTO_SAVE_INTERVAL_MAX = 60

    # ========================================================================
    # PROVIDER CONFIGURATION
    # ========================================================================
    PROVIDER_LAST = "SARTracker/Providers/last_provider"
    PROVIDER_AUTO_CONNECT = "SARTracker/Providers/auto_connect_on_startup"

    # Provider-specific config (use format: f"SARTracker/Providers/{provider_name}/{key}")
    # HTTP Traccar Provider (legacy)
    PROVIDER_HTTP_SERVER_URL = "SARTracker/Providers/http_traccar/server_url"
    PROVIDER_HTTP_USERNAME = "SARTracker/Providers/http_traccar/username"
    PROVIDER_HTTP_PASSWORD = "SARTracker/Providers/http_traccar/password"
    PROVIDER_HTTP_TIMEOUT = "SARTracker/Providers/http_traccar/timeout"

    # Traccar HTTP Provider (Phase 4)
    PROVIDER_TRACCAR_BASE_URL = "SARTracker/Providers/traccar_http/base_url"
    PROVIDER_TRACCAR_AUTH_TYPE = "SARTracker/Providers/traccar_http/auth_type"
    PROVIDER_TRACCAR_USERNAME = "SARTracker/Providers/traccar_http/username"
    PROVIDER_TRACCAR_PASSWORD = "SARTracker/Providers/traccar_http/password"
    PROVIDER_TRACCAR_TOKEN = "SARTracker/Providers/traccar_http/token"
    PROVIDER_TRACCAR_TIMEOUT = "SARTracker/Providers/traccar_http/timeout_s"
    PROVIDER_TRACCAR_CACHE_TTL = "SARTracker/Providers/traccar_http/cache_ttl"
    PROVIDER_TRACCAR_CACHE_ENABLED = "SARTracker/Providers/traccar_http/enable_last_good_cache"
    PROVIDER_TRACCAR_TEST_WINDOW_ENABLED = "SARTracker/Providers/traccar_http/test_window_enabled"
    PROVIDER_TRACCAR_TEST_WINDOW_START = "SARTracker/Providers/traccar_http/test_window_start"
    PROVIDER_TRACCAR_TEST_WINDOW_HOURS = "SARTracker/Providers/traccar_http/test_window_hours"

    # Defaults
    PROVIDER_AUTO_CONNECT_DEFAULT = False
    PROVIDER_HTTP_TIMEOUT_DEFAULT = 10  # seconds
    PROVIDER_TRACCAR_TIMEOUT_DEFAULT = 10  # seconds
    PROVIDER_TRACCAR_CACHE_TTL_DEFAULT = 300  # seconds
    PROVIDER_TRACCAR_CACHE_ENABLED_DEFAULT = True
    PROVIDER_TRACCAR_TEST_WINDOW_ENABLED_DEFAULT = False
    PROVIDER_TRACCAR_TEST_WINDOW_START_DEFAULT = ""
    PROVIDER_TRACCAR_TEST_WINDOW_HOURS_DEFAULT = 3

    # ========================================================================
    # MISSION STATE (transient - not configuration)
    # These keys store active mission state for auto-resume functionality.
    # They are NOT part of settings configuration and should NOT be exposed
    # in the Settings panel.
    # ========================================================================
    MISSION_PAUSED = "SAR_Tracker/mission_paused"  # Legacy key format
    MISSION_NAME = "SAR_Tracker/mission_name"      # Legacy key format
    MISSION_START_TIME = "SAR_Tracker/mission_start_time"  # Legacy key format

    # ========================================================================
    # MISSION STORAGE CONFIGURATION
    # ========================================================================
    MISSION_PRIMARY_ROOT = "SARTracker/Missions/primary_root"
    MISSION_BACKUP_ROOT = "SARTracker/Missions/backup_root"
    MISSION_COORDINATOR_ROSTER = "SARTracker/Missions/coordinators"
    MISSION_ADMIN_ROSTER = "SARTracker/Missions/admins"

    MISSION_PRIMARY_ROOT_DEFAULT = os.path.join(os.path.expanduser("~"), "SAR Tracker Missions")
    MISSION_BACKUP_ROOT_DEFAULT = ""
    MISSION_COORDINATOR_ROSTER_DEFAULT = ""
    MISSION_ADMIN_ROSTER_DEFAULT = ""

    # ========================================================================
    # UI STATE (Phase N1)
    # ========================================================================
    SETTINGS_MIGRATION_NOTICE_SHOWN = "SARTracker/UI/settings_migration_notice_shown"
    COORDINATE_DISPLAY_MODE = "SARTracker/Coordinates/display_mode"
    COORDINATE_DISPLAY_MODE_LATLON_FIRST = "latlon_first"
    COORDINATE_DISPLAY_MODE_TM65_FIRST = "tm65_first"
    COORDINATE_DISPLAY_MODE_DEFAULT = COORDINATE_DISPLAY_MODE_LATLON_FIRST
    # Layer Console (Phase 4 canonical keys)
    LAYER_CONSOLE_EXPANDED_GROUPS = "sartracker/layer_console/expanded_groups"
    LAYER_CONSOLE_COLUMN_WIDTHS = "sartracker/layer_console/column_widths"
    LAYER_CONSOLE_FILTER_STATE = "sartracker/layer_console/filter_state"  # index-based for current UI
    LAYER_CONSOLE_FILTER_TYPE = "sartracker/layer_console/filter_type"
    LAYER_CONSOLE_SEARCH_TEXT = "sartracker/layer_console/search_text"
    LAYER_CONSOLE_SHOW_HIDDEN = "sartracker/layer_console/show_hidden"
    LAYER_CONSOLE_SELECTED_LAYER = "sartracker/layer_console/selected_layer"
    LAYER_CONSOLE_SELECTED_FEATURE = "sartracker/layer_console/selected_feature"
    LAYER_CONSOLE_LAST_SELECTION = "sartracker/layer_console/last_selection"

    # Defaults (Issue #4.6)
    LAYER_CONSOLE_SHOW_HIDDEN_DEFAULT = False

    # Legacy Phase 3 keys retained for compatibility
    LAYER_CONSOLE_EXPANDED_GROUPS_LEGACY = "SARTracker/LayerConsole/expanded_groups"
    LAYER_CONSOLE_COLUMN_WIDTHS_LEGACY = "SARTracker/LayerConsole/column_widths"
    LAYER_CONSOLE_FILTER_STATE_LEGACY = "SARTracker/LayerConsole/filter_state"
    LAYER_CONSOLE_SELECTED_LAYER_LEGACY = "SARTracker/LayerConsole/selected_layer"
    LAYER_CONSOLE_SELECTED_FEATURE_LEGACY = "SARTracker/LayerConsole/selected_feature"

    # ========================================================================
    # FEATURE FLAGS
    # ========================================================================
    # Note: Feature flags can also be enabled via environment variables
    # (e.g., SARTRACKER_ENABLE_TRACCAR_HTTP=1)

    # ========================================================================
    # DEBUG / LOGGING CONFIGURATION
    # ========================================================================
    DEBUG_LOGGING_ENABLED = "SARTracker/Debug/logging_enabled"

    # Defaults
    DEBUG_LOGGING_ENABLED_DEFAULT = False

    # Note: Debug logging can also be enabled via environment variable:
    # SARTRACKER_DEBUG=1

    # ========================================================================
    # VALIDATION RULES
    # ========================================================================

    @staticmethod
    def validate_interval(value: int, min_val: int, max_val: int) -> bool:
        """
        Validate interval setting.

        Args:
            value: Value to validate
            min_val: Minimum allowed value
            max_val: Maximum allowed value

        Returns:
            True if valid, False otherwise
        """
        if not isinstance(value, int):
            return False
        return min_val <= value <= max_val

    @staticmethod
    def validate_url(url: str) -> bool:
        """
        Validate URL format.

        Args:
            url: URL string to validate

        Returns:
            True if valid, False otherwise
        """
        if not url or not isinstance(url, str):
            return False
        url = url.strip()
        if not url:
            return False
        # Basic URL validation (http or https)
        return url.startswith('http://') or url.startswith('https://')

    @staticmethod
    def validate_file_path(path: str) -> bool:
        """
        Validate file path (not empty, basic format check).

        Args:
            path: File path to validate

        Returns:
            True if valid format, False otherwise

        Note: Does NOT check if file exists - that's a runtime check.
        """
        if not path or not isinstance(path, str):
            return False
        return bool(path.strip())


class ConfigStore:
    """
    Helper class for reading/writing QSettings with defaults and validation.

    Provides a consistent interface for accessing settings throughout the plugin,
    reducing boilerplate and preventing typos.

    Qt5/Qt6 Compatible: Uses QSettings which is identical in both versions.
    """

    @staticmethod
    def get(key: str, default=None, value_type=None):
        """
        Get setting value with default.

        Args:
            key: QSettings key
            default: Default value if key doesn't exist
            value_type: Type to cast value to (e.g., bool, int, str)

        Returns:
            Setting value or default
        """
        from qgis.PyQt.QtCore import QSettings
        settings = QSettings()

        if value_type is not None:
            return settings.value(key, default, type=value_type)
        else:
            return settings.value(key, default)

    @staticmethod
    def set(key: str, value):
        """
        Set setting value.

        Args:
            key: QSettings key
            value: Value to store
        """
        from qgis.PyQt.QtCore import QSettings
        settings = QSettings()
        settings.setValue(key, value)

    @staticmethod
    def get_mission_primary_root() -> str:
        """Return configured mission primary root or default."""
        path = ConfigStore.get(SETTINGS_KEYS.MISSION_PRIMARY_ROOT, SETTINGS_KEYS.MISSION_PRIMARY_ROOT_DEFAULT)
        if not isinstance(path, str):
            return SETTINGS_KEYS.MISSION_PRIMARY_ROOT_DEFAULT
        path = path.strip()
        return path or SETTINGS_KEYS.MISSION_PRIMARY_ROOT_DEFAULT

    @staticmethod
    def set_mission_primary_root(path: str):
        ConfigStore.set(SETTINGS_KEYS.MISSION_PRIMARY_ROOT, path or "")

    @staticmethod
    def get_mission_backup_root() -> str:
        """Return configured mission backup root (empty if not set)."""
        path = ConfigStore.get(SETTINGS_KEYS.MISSION_BACKUP_ROOT, SETTINGS_KEYS.MISSION_BACKUP_ROOT_DEFAULT)
        if not isinstance(path, str):
            return ""
        return path.strip()

    @staticmethod
    def set_mission_backup_root(path: str):
        ConfigStore.set(SETTINGS_KEYS.MISSION_BACKUP_ROOT, path or "")

    @staticmethod
    def get_coordinator_roster() -> str:
        """Return configured coordinator roster as raw string (newline/comma-delimited)."""
        roster = ConfigStore.get(
            SETTINGS_KEYS.MISSION_COORDINATOR_ROSTER,
            SETTINGS_KEYS.MISSION_COORDINATOR_ROSTER_DEFAULT
        )
        if not isinstance(roster, str):
            return ""
        return roster

    @staticmethod
    def set_coordinator_roster(roster: str):
        ConfigStore.set(SETTINGS_KEYS.MISSION_COORDINATOR_ROSTER, roster or "")

    @staticmethod
    def get_admin_roster() -> str:
        """Return configured admin roster as raw string (newline/comma-delimited)."""
        roster = ConfigStore.get(
            SETTINGS_KEYS.MISSION_ADMIN_ROSTER,
            SETTINGS_KEYS.MISSION_ADMIN_ROSTER_DEFAULT
        )
        if not isinstance(roster, str):
            return ""
        return roster

    @staticmethod
    def set_admin_roster(roster: str):
        ConfigStore.set(SETTINGS_KEYS.MISSION_ADMIN_ROSTER, roster or "")

    # ------------------------------------------------------------------
    # Roster helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _parse_roster(raw: str) -> list:
        """Split roster string on newlines/commas and return trimmed unique entries."""
        if not raw:
            return []
        tokens = []
        for line in raw.splitlines():
            for part in line.split(","):
                name = part.strip()
                if name:
                    tokens.append(name)
        # Preserve order while removing duplicates
        seen = set()
        unique = []
        for name in tokens:
            if name not in seen:
                unique.append(name)
                seen.add(name)
        return unique

    @staticmethod
    def get_coordinator_list() -> list:
        return ConfigStore._parse_roster(ConfigStore.get_coordinator_roster())

    @staticmethod
    def get_admin_list() -> list:
        return ConfigStore._parse_roster(ConfigStore.get_admin_roster())

    @staticmethod
    def remove(key: str):
        """
        Remove setting.

        Args:
            key: QSettings key to remove
        """
        from qgis.PyQt.QtCore import QSettings
        settings = QSettings()
        settings.remove(key)

    @staticmethod
    def get_auto_refresh_enabled() -> bool:
        """Get auto-refresh enabled setting."""
        return ConfigStore.get(
            SETTINGS_KEYS.AUTO_REFRESH_ENABLED,
            SETTINGS_KEYS.AUTO_REFRESH_ENABLED_DEFAULT,
            bool
        )

    @staticmethod
    def get_auto_refresh_interval() -> int:
        """Get auto-refresh interval setting (seconds)."""
        return ConfigStore.get(
            SETTINGS_KEYS.AUTO_REFRESH_INTERVAL,
            SETTINGS_KEYS.AUTO_REFRESH_INTERVAL_DEFAULT,
            int
        )

    @staticmethod
    def get_auto_save_enabled() -> bool:
        """Get auto-save enabled setting."""
        return ConfigStore.get(
            SETTINGS_KEYS.AUTO_SAVE_ENABLED,
            SETTINGS_KEYS.AUTO_SAVE_ENABLED_DEFAULT,
            bool
        )

    @staticmethod
    def get_auto_save_interval() -> int:
        """Get auto-save interval setting (minutes)."""
        return ConfigStore.get(
            SETTINGS_KEYS.AUTO_SAVE_INTERVAL,
            SETTINGS_KEYS.AUTO_SAVE_INTERVAL_DEFAULT,
            int
        )

    @staticmethod
    def get_provider_auto_connect() -> bool:
        """Get provider auto-connect setting."""
        return ConfigStore.get(
            SETTINGS_KEYS.PROVIDER_AUTO_CONNECT,
            SETTINGS_KEYS.PROVIDER_AUTO_CONNECT_DEFAULT,
            bool
        )

    @staticmethod
    def get_traccar_test_window_enabled() -> bool:
        """Get replay/test window enabled setting."""
        return ConfigStore.get(
            SETTINGS_KEYS.PROVIDER_TRACCAR_TEST_WINDOW_ENABLED,
            SETTINGS_KEYS.PROVIDER_TRACCAR_TEST_WINDOW_ENABLED_DEFAULT,
            bool
        )

    @staticmethod
    def set_traccar_test_window_enabled(enabled: bool):
        """Set replay/test window enabled setting."""
        ConfigStore.set(SETTINGS_KEYS.PROVIDER_TRACCAR_TEST_WINDOW_ENABLED, bool(enabled))

    @staticmethod
    def get_traccar_test_window_start() -> str:
        """Get replay/test window start timestamp (ISO8601 string)."""
        value = ConfigStore.get(
            SETTINGS_KEYS.PROVIDER_TRACCAR_TEST_WINDOW_START,
            SETTINGS_KEYS.PROVIDER_TRACCAR_TEST_WINDOW_START_DEFAULT,
            str
        )
        return value or ""

    @staticmethod
    def set_traccar_test_window_start(start_iso: str):
        """Set replay/test window start timestamp (ISO8601 string)."""
        ConfigStore.set(SETTINGS_KEYS.PROVIDER_TRACCAR_TEST_WINDOW_START, start_iso or "")

    @staticmethod
    def get_traccar_test_window_hours() -> int:
        """Get replay/test window duration (hours)."""
        return ConfigStore.get(
            SETTINGS_KEYS.PROVIDER_TRACCAR_TEST_WINDOW_HOURS,
            SETTINGS_KEYS.PROVIDER_TRACCAR_TEST_WINDOW_HOURS_DEFAULT,
            int
        )

    @staticmethod
    def set_traccar_test_window_hours(hours: int):
        """Set replay/test window duration (hours)."""
        ConfigStore.set(SETTINGS_KEYS.PROVIDER_TRACCAR_TEST_WINDOW_HOURS, int(hours))

    @staticmethod
    def get_debug_logging_enabled() -> bool:
        """Get debug logging enabled setting."""
        return ConfigStore.get(
            SETTINGS_KEYS.DEBUG_LOGGING_ENABLED,
            SETTINGS_KEYS.DEBUG_LOGGING_ENABLED_DEFAULT,
            bool
        )

    @staticmethod
    def set_debug_logging_enabled(enabled: bool):
        """Set debug logging enabled setting."""
        ConfigStore.set(SETTINGS_KEYS.DEBUG_LOGGING_ENABLED, enabled)

    @staticmethod
    def get_coordinate_display_mode() -> str:
        """Get coordinate display mode with safe fallback."""
        mode = ConfigStore.get(
            SETTINGS_KEYS.COORDINATE_DISPLAY_MODE,
            SETTINGS_KEYS.COORDINATE_DISPLAY_MODE_DEFAULT,
            str
        )
        valid_modes = {
            SETTINGS_KEYS.COORDINATE_DISPLAY_MODE_LATLON_FIRST,
            SETTINGS_KEYS.COORDINATE_DISPLAY_MODE_TM65_FIRST,
        }
        if mode not in valid_modes:
            return SETTINGS_KEYS.COORDINATE_DISPLAY_MODE_DEFAULT
        return mode

    @staticmethod
    def set_coordinate_display_mode(mode: str):
        """Persist coordinate display mode."""
        valid_modes = {
            SETTINGS_KEYS.COORDINATE_DISPLAY_MODE_LATLON_FIRST,
            SETTINGS_KEYS.COORDINATE_DISPLAY_MODE_TM65_FIRST,
        }
        value = mode if mode in valid_modes else SETTINGS_KEYS.COORDINATE_DISPLAY_MODE_DEFAULT
        ConfigStore.set(SETTINGS_KEYS.COORDINATE_DISPLAY_MODE, value)
