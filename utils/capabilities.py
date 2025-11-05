# -*- coding: utf-8 -*-
"""
Runtime capability detection for Qt5/Qt6 and QGIS version differences.

Detects environment once at startup and exposes as module-level constants.
Used by compat layer and diagnostic tools.
"""

from qgis.core import Qgis
from qgis.PyQt.QtWidgets import QDialog

# Qt version detection - test for Qt6 by checking if exec_() exists
# In Qt6, exec_() was removed in favor of exec()
HAS_QT6 = not hasattr(QDialog, 'exec_')

# Dialog execution method name
DIALOG_EXEC_NAME = "exec" if HAS_QT6 else "exec_"

# Qt version as integer and string
QT_VERSION = 6 if HAS_QT6 else 5
QT_VERSION_STR = f"Qt{QT_VERSION}"

# QGIS API detection - MessageLevel enum added in QGIS 3.16
HAS_MESSAGE_ENUM = hasattr(Qgis, 'MessageLevel')

# QGIS version info
QGIS_VERSION_INT = Qgis.QGIS_VERSION_INT
QGIS_VERSION_STR = Qgis.QGIS_VERSION

# All exports
__all__ = [
    'HAS_QT6',
    'QT_VERSION',
    'QT_VERSION_STR',
    'DIALOG_EXEC_NAME',
    'HAS_MESSAGE_ENUM',
    'QGIS_VERSION_INT',
    'QGIS_VERSION_STR',
]
