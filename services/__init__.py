# -*- coding: utf-8 -*-
"""
SAR Tracker Services Package.

Contains service modules that encapsulate business logic for testability.
"""
from .lifecycle_manager import PluginLifecycleManager, ComponentRegistry

# Note: import_guard and vendor_bootstrap are NOT auto-imported here
# because they have module-level side effects (sys.path modification, imports).
# Import them explicitly where needed:
#   from .services.import_guard import run_imports, get_import_report
#   from .services.vendor_bootstrap import bootstrap_vendor, get_vendor_info

__all__ = ['PluginLifecycleManager', 'ComponentRegistry']
