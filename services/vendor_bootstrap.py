# -*- coding: utf-8 -*-
"""
Vendor Bootstrap Service

LIFE-SAFETY CRITICAL: This module MUST be imported and executed BEFORE any
provider imports that depend on the requests package.

Phase 1 Refactor: Extracted from sartracker.py (lines 36-236)

This module ensures bundled dependencies (requests, urllib3, certifi, etc.)
are loaded from the vendor directory rather than system packages, providing:
- Consistent SSL/TLS behavior across QGIS installations
- Known-good certificate bundle
- Isolation from conflicting system packages

Usage:
    from .services.vendor_bootstrap import bootstrap_vendor, get_vendor_info

    # Call at module level, BEFORE provider imports
    bootstrap_vendor(Path(__file__).parent)

    # Later, for diagnostics
    vendor_info = get_vendor_info()
"""
from typing import Dict, List, Any, Optional
from pathlib import Path
import sys
import os


# ---------------------------------------------------------------------------
# Vendor diagnostics state (module-level singleton)
# ---------------------------------------------------------------------------
_vendor_info: Dict[str, Any] = {
    "using_vendor": False,
    "requests_path": None,
    "certifi_path": None,
    "missing": [],
    "error": None,
    "bootstrap_complete": False,
}


def get_vendor_info() -> Dict[str, Any]:
    """
    Get vendor bootstrap diagnostics info.

    Returns:
        Dict containing:
            - using_vendor: bool - True if vendor bundle is active
            - requests_path: str or None - Path to requests package
            - certifi_path: str or None - Path to CA certificate bundle
            - missing: List[str] - List of missing vendor assets
            - error: str or None - Error message if bootstrap failed
            - bootstrap_complete: bool - True if bootstrap has run
    """
    return dict(_vendor_info)


def _verify_vendor_bundle(vendor_dir: Path) -> List[str]:
    """
    Verify critical vendor assets exist before imports.

    Args:
        vendor_dir: Path to vendor/site-packages directory

    Returns:
        List of missing file paths (empty if all present).
    """
    required = [
        vendor_dir / "requests" / "__init__.py",
        vendor_dir / "urllib3" / "__init__.py",
        vendor_dir / "charset_normalizer" / "__init__.py",
        vendor_dir / "idna" / "__init__.py",
        vendor_dir / "certifi" / "cacert.pem",
    ]
    missing = [str(path) for path in required if not path.exists()]
    return missing


def _force_vendor_requests(vendor_dir: Path) -> bool:
    """
    Force requests stack to load from vendor_dir even if system requests was imported.

    Non-fatal:
        If the vendor stack cannot be loaded reliably, fall back to the system
        requests stack and record details in _vendor_info for diagnostics.

    Args:
        vendor_dir: Path to vendor/site-packages directory

    Returns:
        True if vendor bundle is now active, False if using system fallback.
    """
    global _vendor_info

    try:
        vendor_dir = vendor_dir.resolve()
    except Exception:
        vendor_dir = Path(str(vendor_dir))

    if not vendor_dir.exists():
        _vendor_info.update(
            {
                "using_vendor": False,
                "requests_path": None,
                "certifi_path": None,
                "missing": _verify_vendor_bundle(vendor_dir),
                "error": f"Vendor directory not found: {vendor_dir}",
            }
        )
        return False

    def _norm_path(path: Path) -> str:
        try:
            return os.path.normcase(os.path.normpath(str(path)))
        except Exception:
            return str(path).lower()

    vendor_norm = _norm_path(vendor_dir)
    vendor_marker = os.path.normcase(
        os.path.normpath(os.path.join("sartracker", "vendor", "site-packages"))
    )

    def _is_vendor_path(path: Path) -> bool:
        """Best-effort check for a path living under sartracker/vendor/site-packages."""
        try:
            path_norm = _norm_path(path)
        except Exception:
            return False
        if path_norm == vendor_norm or path_norm.startswith(vendor_norm + os.sep):
            return True
        # Fallback for cases like Windows 8.3 paths or differing drive casing.
        return vendor_marker in path_norm

    # If requests is already imported from system, clear it and its dependencies
    def _is_from_vendor(mod_name: str) -> bool:
        mod = sys.modules.get(mod_name)
        try:
            return _is_vendor_path(Path(mod.__file__).resolve())  # type: ignore[arg-type]
        except Exception:
            return False

    if "requests" in sys.modules and not _is_from_vendor("requests"):
        for name in list(sys.modules.keys()):
            if name == "requests" or name.startswith(
                ("requests.", "urllib3", "charset_normalizer", "idna", "certifi")
            ):
                sys.modules.pop(name, None)

    # Ensure vendor path is first for import resolution
    vendor_str = str(vendor_dir)
    new_sys_path: List[str] = [vendor_str]
    for entry in list(sys.path):
        try:
            if _norm_path(Path(entry)) == vendor_norm:
                continue
        except Exception:
            pass
        if entry != vendor_str:
            new_sys_path.append(entry)
    sys.path = new_sys_path

    try:
        # Import and validate paths
        import requests  # noqa: E401
        import certifi  # noqa: E401

        requests_path = Path(requests.__file__).resolve()
        cert_path = Path(certifi.where()).resolve()

        if _is_vendor_path(requests_path) and _is_vendor_path(cert_path):
            _vendor_info.update(
                {
                    "using_vendor": True,
                    "requests_path": str(requests_path),
                    "certifi_path": str(cert_path),
                    "missing": [],
                    "error": None,
                }
            )
            return True
        raise RuntimeError(
            f"Requests stack not using vendor bundle. requests: {requests_path}, certifi: {cert_path}"
        )
    except Exception as exc:
        # Fall back to system requests stack (non-fatal) to keep plugin usable.
        _vendor_info.update(
            {
                "using_vendor": False,
                "requests_path": None,
                "certifi_path": None,
                "missing": [],
                "error": str(exc),
            }
        )

        # Remove vendor path from sys.path to avoid mixing vendored/system deps.
        filtered_sys_path: List[str] = []
        for entry in list(sys.path):
            try:
                if _norm_path(Path(entry)) == vendor_norm:
                    continue
            except Exception:
                pass
            filtered_sys_path.append(entry)
        sys.path = filtered_sys_path

        # Clear any partially imported vendor stack
        for name in list(sys.modules.keys()):
            if name == "requests" or name.startswith(
                ("requests.", "urllib3", "charset_normalizer", "idna", "certifi")
            ):
                sys.modules.pop(name, None)

        # Ensure charset helpers exist for minimal requests import compatibility
        # NOTE: This import is deferred to avoid circular imports during bootstrap
        try:
            from ..utils.dependency_guard import ensure_requests_charset_modules

            ensure_requests_charset_modules()
        except Exception as guard_exc:
            print(f"[SAR Tracker] Warning: Could not ensure charset helpers: {guard_exc}")

        try:
            import requests  # noqa: E401
            import certifi  # noqa: E401

            _vendor_info.update(
                {
                    "using_vendor": False,
                    "requests_path": str(Path(requests.__file__).resolve()),
                    "certifi_path": str(Path(certifi.where()).resolve()),
                }
            )
        except Exception as sys_exc:
            _vendor_info.update(
                {"error": f"{_vendor_info.get('error')}; system import failed: {sys_exc}"}
            )
        return False


def bootstrap_vendor(plugin_root: Path) -> Dict[str, Any]:
    """
    Bootstrap vendored dependencies for the SAR Tracker plugin.

    MUST be called at module-level in sartracker.py BEFORE any provider imports.

    This function:
    1. Verifies the vendor bundle exists
    2. Forces the requests stack to load from the vendor directory
    3. Falls back to system packages if vendor bundle is unavailable

    Args:
        plugin_root: Path to the sartracker plugin directory (contains vendor/)

    Returns:
        Dict containing vendor diagnostics info (same as get_vendor_info())

    Example:
        # At top of sartracker.py, before provider imports:
        from .services.vendor_bootstrap import bootstrap_vendor
        _vendor_info = bootstrap_vendor(Path(__file__).parent)
    """
    global _vendor_info

    # Prevent double-bootstrap
    if _vendor_info.get("bootstrap_complete"):
        return get_vendor_info()

    vendor_path = plugin_root / "vendor" / "site-packages"

    # Check vendor directory exists
    if not vendor_path.exists():
        print(f"[SAR Tracker] Warning: Vendor path not found: {vendor_path}")
        _vendor_info.update(
            {
                "error": f"Vendor path not found: {vendor_path}",
                "bootstrap_complete": True,
            }
        )
        return get_vendor_info()

    # Ensure plugin parent is available for package imports (defensive)
    plugin_parent = plugin_root.parent
    if plugin_parent and str(plugin_parent) not in sys.path:
        sys.path.insert(0, str(plugin_parent))
        print(f"[SAR Tracker] Added plugin parent to sys.path: {plugin_parent}")

    # Perform vendor verification and force the vendored requests stack
    try:
        vendor_missing: List[str] = _verify_vendor_bundle(vendor_path)
        if vendor_missing:
            raise RuntimeError(f"Missing vendor assets: {', '.join(vendor_missing)}")
        _force_vendor_requests(vendor_path)
    except Exception as e:
        _vendor_info.update(
            {
                "missing": list(locals().get("vendor_missing", [])),
                "error": str(e),
            }
        )
        print(f"[SAR Tracker] Warning: Vendor bundle unavailable, using system dependencies: {e}")

    _vendor_info["bootstrap_complete"] = True
    return get_vendor_info()
