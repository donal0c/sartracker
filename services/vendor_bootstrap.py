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
from typing import Dict, List, Any, Optional, Tuple
from pathlib import Path
import sys
import os


# ---------------------------------------------------------------------------
# Vendor diagnostics state (module-level singleton)
# ---------------------------------------------------------------------------
_vendor_info: Dict[str, Any] = {
    "using_vendor": False,
    "requests_path": None,
    "urllib3_path": None,
    "idna_path": None,
    "charset_path": None,
    "charset_module": None,
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
            - urllib3_path: str or None - Path to urllib3 package
            - idna_path: str or None - Path to idna package
            - charset_path: str or None - Path to charset module (charset_normalizer/chardet)
            - charset_module: str or None - Name of charset module in use
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

    stack_modules = (
        "requests",
        "urllib3",
        "charset_normalizer",
        "chardet",
        "idna",
        "certifi",
    )

    def _module_path(mod: object) -> Optional[Path]:
        mod_file = getattr(mod, "__file__", None)
        if not mod_file:
            return None
        try:
            return Path(mod_file).resolve()
        except Exception:
            return Path(str(mod_file))

    def _is_vendor_module(mod: object) -> bool:
        mod_path = _module_path(mod)
        return bool(mod_path and _is_vendor_path(mod_path))

    def _is_stack_module(name: str) -> bool:
        return any(
            name == base or name.startswith(base + ".") for base in stack_modules
        )

    # Purge non-vendored stack modules to avoid mixing system and vendor deps.
    for name, mod in list(sys.modules.items()):
        if _is_stack_module(name) and not _is_vendor_module(mod):
            sys.modules.pop(name, None)

    def _load_charset_module() -> Tuple[Optional[str], Optional[Path]]:
        try:
            import charset_normalizer as _charset_mod  # noqa: E401
            return "charset_normalizer", _module_path(_charset_mod)
        except Exception:
            try:
                import chardet as _charset_mod  # noqa: E401
                return "chardet", _module_path(_charset_mod)
            except Exception:
                return None, None

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
        import urllib3  # noqa: E401
        import idna  # noqa: E401
        import certifi  # noqa: E401

        requests_path = _module_path(requests)
        urllib3_path = _module_path(urllib3)
        idna_path = _module_path(idna)
        charset_module, charset_path = _load_charset_module()
        cert_path = Path(certifi.where()).resolve()

        stack_mismatch: List[str] = []

        def _check_vendor_path(label: str, path: Optional[Path]) -> None:
            if not path or not _is_vendor_path(path):
                stack_mismatch.append(f"{label}: {path}")

        _check_vendor_path("requests", requests_path)
        _check_vendor_path("urllib3", urllib3_path)
        _check_vendor_path("idna", idna_path)
        _check_vendor_path("certifi", cert_path)

        if charset_module:
            _check_vendor_path(charset_module, charset_path)
        else:
            stack_mismatch.append("charset helper missing")

        if stack_mismatch:
            raise RuntimeError(
                "Requests stack not using vendor bundle: " + "; ".join(stack_mismatch)
            )

        _vendor_info.update(
            {
                "using_vendor": True,
                "requests_path": str(requests_path) if requests_path else None,
                "urllib3_path": str(urllib3_path) if urllib3_path else None,
                "idna_path": str(idna_path) if idna_path else None,
                "charset_path": str(charset_path) if charset_path else None,
                "charset_module": charset_module,
                "certifi_path": str(cert_path),
                "missing": [],
                "error": None,
            }
        )
        return True
    except Exception as exc:
        # Fall back to system requests stack (non-fatal) to keep plugin usable.
        _vendor_info.update(
            {
                "using_vendor": False,
                "requests_path": None,
                "urllib3_path": None,
                "idna_path": None,
                "charset_path": None,
                "charset_module": None,
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
            import urllib3  # noqa: E401
            import idna  # noqa: E401
            import certifi  # noqa: E401

            requests_path = _module_path(requests)
            urllib3_path = _module_path(urllib3)
            idna_path = _module_path(idna)
            charset_module, charset_path = _load_charset_module()
            cert_path = Path(certifi.where()).resolve()

            _vendor_info.update(
                {
                    "using_vendor": False,
                    "requests_path": str(requests_path) if requests_path else None,
                    "urllib3_path": str(urllib3_path) if urllib3_path else None,
                    "idna_path": str(idna_path) if idna_path else None,
                    "charset_path": str(charset_path) if charset_path else None,
                    "charset_module": charset_module,
                    "certifi_path": str(cert_path),
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
