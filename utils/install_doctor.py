# -*- coding: utf-8 -*-
"""
Install Doctor - Diagnose common installation problems.

This module detects common installation issues that cause the plugin to fail
silently or display "Not Initialized" errors. It provides actionable messages
to help users fix problems.

Qt5/Qt6 Compatible: Uses only stdlib and path checks.
"""

import os
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class InstallIssue:
    """A single installation issue with severity and remediation."""
    severity: str  # "error", "warning", "info"
    title: str
    message: str
    remediation: str


@dataclass
class InstallDoctorReport:
    """Complete installation health report."""
    issues: List[InstallIssue] = field(default_factory=list)
    plugin_dir: str = ""
    folder_name: str = ""

    @property
    def has_errors(self) -> bool:
        return any(i.severity == "error" for i in self.issues)

    @property
    def has_warnings(self) -> bool:
        return any(i.severity == "warning" for i in self.issues)

    @property
    def is_healthy(self) -> bool:
        return not self.has_errors and not self.has_warnings


# Expected vendor assets that must be present for offline/bundled operation
CRITICAL_VENDOR_ASSETS = [
    "vendor/site-packages/requests/__init__.py",
    "vendor/site-packages/urllib3/__init__.py",
    "vendor/site-packages/certifi/__init__.py",
    "vendor/site-packages/certifi/cacert.pem",
    "vendor/site-packages/charset_normalizer/__init__.py",
]

# Files that indicate a proper release vs GitHub source ZIP
RELEASE_MARKERS = [
    "VERSION.txt",  # Created by make_release.py
]


def get_plugin_dir() -> Path:
    """Get the plugin directory path from this file's location."""
    return Path(__file__).parent.parent


def check_folder_name(plugin_dir: Path) -> Optional[InstallIssue]:
    """
    Check that plugin folder is named exactly 'sartracker'.

    GitHub source ZIPs extract to 'sartracker-main' or 'sartracker-master'
    which breaks Python imports and QGIS plugin loading.
    """
    folder_name = plugin_dir.name

    if folder_name == "sartracker":
        return None

    return InstallIssue(
        severity="error",
        title="Wrong Plugin Folder Name",
        message=f"Plugin folder is '{folder_name}' but must be 'sartracker'.",
        remediation=(
            f"Rename the folder from '{folder_name}' to 'sartracker', or "
            "install from an official SAR Tracker release ZIP instead of "
            "downloading the GitHub source code directly."
        )
    )


def check_nested_install(plugin_dir: Path) -> Optional[InstallIssue]:
    """
    Check for nested installation (sartracker-main/sartracker/...).

    This happens when users extract GitHub ZIPs without flattening,
    resulting in double-nested folders.
    """
    # Check if there's a sartracker subfolder inside the plugin dir
    nested_path = plugin_dir / "sartracker"
    if nested_path.is_dir() and (nested_path / "__init__.py").exists():
        return InstallIssue(
            severity="error",
            title="Nested Installation Detected",
            message=(
                f"Found nested 'sartracker' folder inside '{plugin_dir.name}'. "
                "This creates import errors."
            ),
            remediation=(
                "Move the contents of the inner 'sartracker' folder up one level, "
                "or reinstall from an official release ZIP."
            )
        )

    # Also check parent - if we're inside sartracker-main/sartracker/
    parent_name = plugin_dir.parent.name
    if parent_name.startswith("sartracker-") or parent_name.startswith("sartracker_"):
        # We might be the inner folder of a nested install
        # Check if parent looks like a plugin dir too
        parent_init = plugin_dir.parent / "__init__.py"
        if not parent_init.exists():
            return InstallIssue(
                severity="warning",
                title="Possible Nested Installation",
                message=(
                    f"Plugin appears to be inside '{parent_name}' which looks like "
                    "an extracted GitHub ZIP folder."
                ),
                remediation=(
                    "Ensure the plugin folder structure is correct. The 'sartracker' "
                    "folder should be directly inside QGIS plugins directory."
                )
            )

    return None


def check_vendor_assets(plugin_dir: Path) -> List[InstallIssue]:
    """
    Check that critical vendor assets are present.

    Missing vendor assets cause SSL/TLS failures and import errors
    when system Python doesn't have required packages.
    """
    issues = []
    missing = []

    for asset_path in CRITICAL_VENDOR_ASSETS:
        full_path = plugin_dir / asset_path
        if not full_path.exists():
            missing.append(asset_path)

    if missing:
        # Determine severity based on what's missing
        if any("cacert.pem" in m for m in missing):
            severity = "error"
            title = "Missing SSL Certificates"
        elif any("requests" in m for m in missing):
            severity = "warning"
            title = "Missing Vendor Dependencies"
        else:
            severity = "warning"
            title = "Incomplete Vendor Bundle"

        issues.append(InstallIssue(
            severity=severity,
            title=title,
            message=f"Missing {len(missing)} vendor asset(s): {', '.join(missing[:3])}{'...' if len(missing) > 3 else ''}",
            remediation=(
                "Reinstall from an official SAR Tracker release ZIP, or run "
                "'python tools/vendor_deps.py --refresh' from the plugin directory."
            )
        ))

    return issues


def check_mission_store_writable(plugin_dir: Path) -> Optional[InstallIssue]:
    """
    Check that the default mission store path is writable.

    If the user can't write to ~/SAR Tracker Missions, mission
    creation will fail silently or with confusing errors.
    """
    # Import here to avoid circular imports
    try:
        from ..config.keys import SETTINGS_KEYS
        default_path = Path(SETTINGS_KEYS.MISSION_PRIMARY_ROOT_DEFAULT).expanduser()
    except Exception:
        # Fallback if config import fails
        default_path = Path.home() / "SAR Tracker Missions"

    # If path exists, check if writable
    if default_path.exists():
        if not os.access(default_path, os.W_OK):
            return InstallIssue(
                severity="error",
                title="Mission Store Not Writable",
                message=f"Cannot write to mission store: {default_path}",
                remediation=(
                    "Check folder permissions, or change the mission storage location "
                    "in SAR Tracker Settings."
                )
            )
    else:
        # Path doesn't exist - check if parent is writable
        parent = default_path.parent
        if parent.exists() and not os.access(parent, os.W_OK):
            return InstallIssue(
                severity="warning",
                title="Cannot Create Mission Store",
                message=f"Cannot create mission store folder: {default_path}",
                remediation=(
                    "Check permissions on your home folder, or change the mission "
                    "storage location in SAR Tracker Settings before starting a mission."
                )
            )

    return None


def check_release_install(plugin_dir: Path) -> Optional[InstallIssue]:
    """
    Check if this appears to be a release install vs raw GitHub source.

    This is informational - not an error, but helps explain potential issues.
    """
    has_version_txt = (plugin_dir / "VERSION.txt").exists()
    has_git_dir = (plugin_dir / ".git").exists()

    if has_git_dir and not has_version_txt:
        return InstallIssue(
            severity="info",
            title="Development Installation",
            message="This appears to be a development/git installation.",
            remediation=(
                "For production use, install from an official release ZIP "
                "created with 'python tools/make_release.py'."
            )
        )

    if not has_version_txt and not has_git_dir:
        # Likely a GitHub source ZIP download
        return InstallIssue(
            severity="info",
            title="Source Installation",
            message="This appears to be installed from GitHub source ZIP.",
            remediation=(
                "For best results, install from an official release ZIP "
                "from the GitHub Releases page."
            )
        )

    return None


def run_diagnostics(plugin_dir: Optional[Path] = None) -> InstallDoctorReport:
    """
    Run all installation diagnostics and return a report.

    Args:
        plugin_dir: Optional plugin directory path. If None, auto-detected.

    Returns:
        InstallDoctorReport with all detected issues.
    """
    if plugin_dir is None:
        plugin_dir = get_plugin_dir()

    report = InstallDoctorReport(
        plugin_dir=str(plugin_dir),
        folder_name=plugin_dir.name
    )

    # Run all checks
    checks = [
        check_folder_name(plugin_dir),
        check_nested_install(plugin_dir),
        check_mission_store_writable(plugin_dir),
        check_release_install(plugin_dir),
    ]

    # Add single-issue checks
    for issue in checks:
        if issue is not None:
            report.issues.append(issue)

    # Add multi-issue checks
    report.issues.extend(check_vendor_assets(plugin_dir))

    return report


def format_report_text(report: InstallDoctorReport) -> str:
    """
    Format report as human-readable text for display.

    Args:
        report: InstallDoctorReport to format

    Returns:
        Formatted text string
    """
    if report.is_healthy:
        return "All checks passed - installation looks good."

    lines = []

    # Group by severity
    errors = [i for i in report.issues if i.severity == "error"]
    warnings = [i for i in report.issues if i.severity == "warning"]
    infos = [i for i in report.issues if i.severity == "info"]

    if errors:
        for issue in errors:
            lines.append(f"ERROR: {issue.title}")
            lines.append(f"  {issue.message}")
            lines.append(f"  Fix: {issue.remediation}")

    if warnings:
        for issue in warnings:
            lines.append(f"WARNING: {issue.title}")
            lines.append(f"  {issue.message}")
            lines.append(f"  Fix: {issue.remediation}")

    if infos:
        for issue in infos:
            lines.append(f"INFO: {issue.title}")
            lines.append(f"  {issue.message}")

    return "\n".join(lines)


def format_report_html(report: InstallDoctorReport) -> str:
    """
    Format report as HTML for Qt labels.

    Args:
        report: InstallDoctorReport to format

    Returns:
        HTML formatted string
    """
    if report.is_healthy:
        return '<span style="color: green;">All checks passed</span>'

    parts = []

    # Group by severity
    errors = [i for i in report.issues if i.severity == "error"]
    warnings = [i for i in report.issues if i.severity == "warning"]

    if errors:
        parts.append(f'<span style="color: red;">Found {len(errors)} error(s)</span>')

    if warnings:
        parts.append(f'<span style="color: orange;">Found {len(warnings)} warning(s)</span>')

    return " | ".join(parts) if parts else "Unknown status"
