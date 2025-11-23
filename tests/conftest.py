# -*- coding: utf-8 -*-
"""
Test bootstrap to avoid importing full QGIS plugin while enabling package-relative imports.
"""
import os
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Ensure repo root and vendored site-packages are importable
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
vendor_path = ROOT / "vendor" / "site-packages"
if vendor_path.exists() and str(vendor_path) not in sys.path:
    sys.path.insert(0, str(vendor_path))

# Stub lightweight sartracker package to satisfy relative imports without running QGIS entrypoint
if "sartracker" not in sys.modules:
    pkg = types.ModuleType("sartracker")
    pkg.__path__ = [str(ROOT)]
    sys.modules["sartracker"] = pkg
