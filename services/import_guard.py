# -*- coding: utf-8 -*-
"""
Import Guard Service

LIFE-SAFETY CRITICAL: This module centralizes import error tracking
and safe-mode support for the SAR Tracker plugin.

Phase 2 Refactor: Extracted from sartracker.py (lines 50-225, 1305-1374)

This module provides:
- Structured import error tracking with ImportErrorRecord and ImportReport
- Helper functions for tracking and classifying import errors
- Error formatting for UI display
- Error logging to temp files for diagnostics

Usage in sartracker.py:
    from .services.import_guard import (
        ImportReport, track_import_error, format_error_summary, write_error_log
    )

    # Create report at module level
    _import_report = ImportReport()

    # In each try/except import block:
    try:
        from .controllers.layers_controller import LayersController
    except Exception as e:
        LayersController = track_import_error(
            _import_report, 'controllers.layers_controller.LayersController', e
        )

    # In initGui():
    if not _import_report.ok:
        self._handle_import_failure(_import_report)
"""
from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional, TypeVar
from pathlib import Path
import traceback
import tempfile
import sys
from datetime import datetime


# ---------------------------------------------------------------------------
# Data Structures
# ---------------------------------------------------------------------------

@dataclass
class ImportErrorRecord:
    """
    Record of a single import failure.

    Attributes:
        module_name: Fully qualified module name that failed to import
        exception: The exception that was raised
        traceback_str: Full traceback string for diagnostics
        is_optional: True for optional imports that shouldn't trigger safe-mode
    """
    module_name: str
    exception: Exception
    traceback_str: str
    is_optional: bool = False


@dataclass
class ImportReport:
    """
    Result of import tracking.

    Attributes:
        ok: True if all critical (non-optional) imports succeeded
        errors: List of all import failures (critical and optional)
        warnings: Non-fatal warning messages (e.g., optional import failures)
    """
    ok: bool = True
    errors: List[ImportErrorRecord] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Module-level state (for diagnostics access)
# ---------------------------------------------------------------------------

_import_report: Optional[ImportReport] = None


def set_import_report(report: ImportReport) -> None:
    """
    Store the import report for later access by diagnostics.

    Args:
        report: The completed ImportReport from sartracker.py
    """
    global _import_report
    _import_report = report


def get_import_report() -> Optional[ImportReport]:
    """
    Get the cached import report.

    Returns:
        ImportReport if set_import_report() has been called, None otherwise.
    """
    return _import_report


# ---------------------------------------------------------------------------
# Import Error Tracking
# ---------------------------------------------------------------------------

T = TypeVar('T')


def track_import_error(
    report: ImportReport,
    module_path: str,
    exc: Exception,
    *,
    is_optional: bool = False,
    fallback_value: T = None,
) -> T:
    """
    Track an import error and return a fallback value.

    This function is designed to be used in except blocks of import statements.
    It records the error, updates the report, logs to console, and returns
    a fallback value that can be assigned to the failed import's name.

    Args:
        report: ImportReport to update with the error
        module_path: Full module path (e.g., 'controllers.layers_controller.LayersController')
        exc: The exception that was raised during import
        is_optional: If True, failure won't set report.ok = False
        fallback_value: Value to return (default: None)

    Returns:
        The fallback_value, suitable for assignment to the failed import name.

    Example:
        try:
            from .controllers.layers_controller import LayersController
        except Exception as e:
            LayersController = track_import_error(
                _import_report, 'controllers.layers_controller.LayersController', e
            )
    """
    tb = traceback.format_exc()
    record = ImportErrorRecord(
        module_name=module_path,
        exception=exc,
        traceback_str=tb,
        is_optional=is_optional,
    )
    report.errors.append(record)

    if is_optional:
        msg = f"Optional import {module_path} unavailable: {exc}"
        report.warnings.append(msg)
        print(f"[SARTRACKER] Warning: {msg}")
    else:
        report.ok = False
        print(f"[SARTRACKER] ERROR importing {module_path}: {exc}")

    return fallback_value


def track_optional_import_error(
    report: ImportReport,
    module_path: str,
    exc: Exception,
    fallback_value: T = None,
) -> T:
    """
    Track an optional import error (convenience wrapper).

    Same as track_import_error with is_optional=True.

    Args:
        report: ImportReport to update
        module_path: Module path that failed
        exc: The exception raised
        fallback_value: Value to return (default: None)

    Returns:
        The fallback_value.
    """
    return track_import_error(
        report, module_path, exc, is_optional=True, fallback_value=fallback_value
    )


# ---------------------------------------------------------------------------
# Error Formatting and Logging
# ---------------------------------------------------------------------------

def write_error_log(report: ImportReport) -> Optional[Path]:
    """
    Write import errors to a temporary log file.

    Creates a timestamped log file in the system temp directory containing
    full error details for user diagnostics and support requests.

    Args:
        report: ImportReport with errors to log

    Returns:
        Path to the log file, or None if writing failed or no errors.
    """
    if not report.errors:
        return None

    try:
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        log_path = Path(tempfile.gettempdir()) / f"sartracker_import_errors_{timestamp}.log"

        with open(log_path, 'w', encoding='utf-8') as f:
            f.write("SAR TRACKER IMPORT ERRORS\n")
            f.write("=" * 70 + "\n")
            f.write(f"Timestamp: {datetime.now().isoformat()}\n")
            f.write(f"Python: {sys.version}\n")
            f.write(f"Critical failures: {get_critical_error_count(report)}\n")
            f.write(f"Optional failures: {len([e for e in report.errors if e.is_optional])}\n")
            f.write("=" * 70 + "\n\n")

            for i, err in enumerate(report.errors, 1):
                status = "[OPTIONAL]" if err.is_optional else "[CRITICAL]"
                f.write(f"Error {i} {status}\n")
                f.write("-" * 50 + "\n")
                f.write(f"Module: {err.module_name}\n")
                f.write(f"Error: {type(err.exception).__name__}: {err.exception}\n")
                f.write(f"Traceback:\n{err.traceback_str}\n")
                f.write("\n")

        print(f"[SARTRACKER] Import errors written to: {log_path}")
        return log_path

    except Exception as exc:
        print(f"[SARTRACKER] Failed to write error log: {exc}")
        return None


def format_error_summary(
    report: ImportReport,
    log_path: Optional[Path] = None,
) -> str:
    """
    Format import errors for display in ImportFailureDialog.

    Produces a human-readable error summary with:
    - List of failed modules (critical first, then optional)
    - Suggested troubleshooting actions
    - Full traceback of first critical error
    - Path to log file (if available)

    Args:
        report: ImportReport with errors to format
        log_path: Optional path to error log file

    Returns:
        Formatted string suitable for display in a text widget.
    """
    lines = []
    lines.append("SAR Tracker failed to load due to the following import errors:\n")

    # List critical errors first
    critical_errors = [e for e in report.errors if not e.is_optional]
    optional_errors = [e for e in report.errors if e.is_optional]

    if critical_errors:
        lines.append("CRITICAL ERRORS (plugin cannot operate):\n")
        for err in critical_errors:
            lines.append(f"  X Module: {err.module_name}")
            lines.append(f"    Error: {type(err.exception).__name__}: {err.exception}\n")

    if optional_errors:
        lines.append("OPTIONAL FEATURES UNAVAILABLE:\n")
        for err in optional_errors:
            lines.append(f"  - Module: {err.module_name}")
            lines.append(f"    Error: {type(err.exception).__name__}: {err.exception}\n")

    lines.append("\n" + "=" * 70)
    lines.append("SUGGESTED ACTIONS:")
    lines.append("=" * 70 + "\n")
    lines.append("1. Verify all plugin files are present and not corrupted")
    lines.append("2. Run Diagnostics: Plugins > SAR Tracker > Diagnostics")
    lines.append("3. Run Smoke Test: Plugins > SAR Tracker > Run Smoke Test")
    lines.append("4. Try reinstalling the plugin")
    lines.append("5. Check QGIS Python console for additional details")
    lines.append("6. Ensure you have compatible QGIS version (3.28+)\n")

    if log_path:
        lines.append(f"Log file: {log_path}\n")

    if critical_errors:
        lines.append("=" * 70)
        lines.append("TECHNICAL DETAILS (first critical error):")
        lines.append("=" * 70 + "\n")
        # Defensive: handle None or empty traceback_str
        tb = critical_errors[0].traceback_str
        lines.append(tb if tb else "(no traceback available)")

    return "\n".join(lines)


def get_critical_error_count(report: ImportReport) -> int:
    """
    Get the count of critical (non-optional) import errors.

    Args:
        report: ImportReport to count errors from

    Returns:
        Number of critical import failures.
    """
    return len([e for e in report.errors if not e.is_optional])


def get_first_critical_error(report: ImportReport) -> Optional[ImportErrorRecord]:
    """
    Get the first critical import error for safe-mode reason.

    Args:
        report: ImportReport to search

    Returns:
        First critical ImportErrorRecord, or None if no critical errors.
    """
    for err in report.errors:
        if not err.is_optional:
            return err
    return None


def get_safe_mode_reason(report: ImportReport) -> str:
    """
    Get a human-readable reason for entering safe mode.

    Args:
        report: ImportReport with errors

    Returns:
        String describing the first critical error, or generic message.
    """
    first_err = get_first_critical_error(report)
    if first_err:
        return f"{first_err.module_name}: {first_err.exception}"
    return "Critical import failures detected"


# ---------------------------------------------------------------------------
# Legacy Compatibility (for transition period)
# ---------------------------------------------------------------------------

def convert_legacy_errors(
    errors: List[tuple],
) -> ImportReport:
    """
    Convert legacy error list format to ImportReport.

    This function helps migrate from the old format:
        [(module_name, exception, traceback_str), ...]

    To the new ImportReport structure.

    Args:
        errors: List of (module_name, exception, traceback_str) tuples

    Returns:
        ImportReport with the errors converted.
        ok=True if all errors are optional, ok=False if any critical error exists.
    """
    # BUG FIX: Initialize ok=True, let loop set False only for critical errors
    # Previously initialized as ok=len(errors)==0 which incorrectly set ok=False
    # for optional-only error lists.
    report = ImportReport(ok=True)

    for item in errors:
        # Defensive: validate tuple structure
        if not isinstance(item, (tuple, list)) or len(item) < 3:
            print(f"[SARTRACKER] Warning: Skipping malformed legacy error entry: {item!r}")
            continue
        module_name, exc, tb = item[0], item[1], item[2]
        # Detect optional imports by module name
        is_optional = 'traccar_http' in module_name
        report.errors.append(ImportErrorRecord(
            module_name=module_name,
            exception=exc,
            traceback_str=tb,
            is_optional=is_optional,
        ))
        if not is_optional:
            report.ok = False

    return report
