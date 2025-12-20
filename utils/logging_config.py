# -*- coding: utf-8 -*-
"""
QGIS-integrated logging configuration for SAR Tracker.

Routes Python logging to QgsMessageLog for unified troubleshooting in
QGIS Log Messages panel. Provides debug verbosity controls via settings
and environment variables.

Qt5/Qt6 Compatible: Uses qgis.PyQt imports.

Usage:
    from utils.logging_config import configure_logging, get_logger

    # At plugin init:
    configure_logging()

    # In modules:
    logger = get_logger(__name__)
    logger.info("Operation started")
    logger.debug("Detailed trace info")  # Only shown if debug enabled
"""

import logging
import os
from typing import Optional

# Category name shown in QGIS Log Messages panel
QGIS_LOG_CATEGORY = "SAR Tracker"

# Environment variable to enable debug logging (set to "1" or "true")
DEBUG_ENV_VAR = "SARTRACKER_DEBUG"


class QgsMessageLogHandler(logging.Handler):
    """
    Python logging handler that routes log records to QgsMessageLog.

    This allows all Python logger output to appear in the QGIS Log Messages
    panel under a consistent category, making troubleshooting easier.

    Level mapping:
        DEBUG    -> Qgis.Info (only if debug enabled)
        INFO     -> Qgis.Info
        WARNING  -> Qgis.Warning
        ERROR    -> Qgis.Critical
        CRITICAL -> Qgis.Critical
    """

    def __init__(self, category: str = QGIS_LOG_CATEGORY):
        """
        Initialize handler with QGIS log category.

        Args:
            category: Category name shown in QGIS Log Messages panel
        """
        super().__init__()
        self.category = category
        self._qgis_available = False
        self._QgsMessageLog = None
        self._Qgis = None
        self._try_import_qgis()

    def _try_import_qgis(self):
        """Attempt to import QGIS classes (may fail in standalone tests)."""
        try:
            from qgis.core import QgsMessageLog, Qgis
            self._QgsMessageLog = QgsMessageLog
            self._Qgis = Qgis
            self._qgis_available = True
        except ImportError:
            self._qgis_available = False

    def emit(self, record: logging.LogRecord):
        """
        Emit a log record to QgsMessageLog.

        Args:
            record: Python logging LogRecord
        """
        if not self._qgis_available:
            return

        try:
            msg = self.format(record)

            # Map Python log levels to QGIS message levels
            if record.levelno >= logging.ERROR:
                level = self._Qgis.Critical
            elif record.levelno >= logging.WARNING:
                level = self._Qgis.Warning
            else:
                level = self._Qgis.Info

            self._QgsMessageLog.logMessage(msg, self.category, level)
        except Exception:
            # Never let logging errors crash the plugin
            pass


def _is_debug_enabled() -> bool:
    """
    Check if debug logging is enabled via settings or environment.

    Returns:
        True if debug logging should be enabled
    """
    # Check environment variable first (takes precedence)
    env_val = os.environ.get(DEBUG_ENV_VAR, "").lower()
    if env_val in ("1", "true", "yes", "on"):
        return True

    # Check QSettings
    try:
        from ..config.keys import SETTINGS_KEYS, ConfigStore
        return ConfigStore.get(
            SETTINGS_KEYS.DEBUG_LOGGING_ENABLED,
            SETTINGS_KEYS.DEBUG_LOGGING_ENABLED_DEFAULT,
            bool
        )
    except Exception:
        return False


def configure_logging(force_debug: Optional[bool] = None) -> logging.Logger:
    """
    Configure Python logging to route to QGIS Log Messages panel.

    Sets up the root 'sartracker' logger with a QgsMessageLog handler.
    Should be called once during plugin initialization.

    Args:
        force_debug: Override debug setting (None = use settings/env)

    Returns:
        The configured root logger for SAR Tracker
    """
    # Determine log level
    if force_debug is not None:
        debug_enabled = force_debug
    else:
        debug_enabled = _is_debug_enabled()

    level = logging.DEBUG if debug_enabled else logging.INFO

    # Get or create root logger for plugin
    root_logger = logging.getLogger("sartracker")
    root_logger.setLevel(level)

    # Remove existing handlers to avoid duplicates on reload
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    # Create QGIS handler
    qgis_handler = QgsMessageLogHandler(QGIS_LOG_CATEGORY)
    qgis_handler.setLevel(level)

    # Format: module_name - message
    # Keep it concise since QGIS Log panel has limited width
    formatter = logging.Formatter("%(name)s - %(message)s")
    qgis_handler.setFormatter(formatter)

    root_logger.addHandler(qgis_handler)

    # Don't propagate to root logger (avoid double logging)
    root_logger.propagate = False

    return root_logger


def get_logger(name: str) -> logging.Logger:
    """
    Get a logger for a specific module.

    This is the recommended way to get loggers in SAR Tracker modules.
    All loggers will be children of the 'sartracker' root logger.

    Args:
        name: Module name (typically __name__)

    Returns:
        Logger instance

    Example:
        logger = get_logger(__name__)
        logger.info("Operation complete")
    """
    # Convert module names to be children of sartracker logger
    # e.g., "controllers.mission_controller" -> "sartracker.controllers.mission_controller"
    if name.startswith("sartracker."):
        logger_name = name
    elif name == "__main__":
        logger_name = "sartracker"
    else:
        # Strip leading module path components if they match plugin structure
        parts = name.split(".")
        # Remove common prefixes that might appear
        if parts[0] in ("controllers", "providers", "utils", "ui", "maptools", "layers", "config"):
            logger_name = f"sartracker.{name}"
        else:
            logger_name = f"sartracker.{name}"

    return logging.getLogger(logger_name)


def set_debug_enabled(enabled: bool):
    """
    Set debug logging enabled in settings and reconfigure logging.

    Args:
        enabled: True to enable debug logging
    """
    try:
        from ..config.keys import SETTINGS_KEYS, ConfigStore
        ConfigStore.set(SETTINGS_KEYS.DEBUG_LOGGING_ENABLED, enabled)
    except Exception:
        pass

    # Reconfigure logging with new setting
    configure_logging(force_debug=enabled)


__all__ = [
    'QGIS_LOG_CATEGORY',
    'DEBUG_ENV_VAR',
    'QgsMessageLogHandler',
    'configure_logging',
    'get_logger',
    'set_debug_enabled',
]
