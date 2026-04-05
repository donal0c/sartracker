# -*- coding: utf-8 -*-
"""
Runtime capability detection for Qt5/Qt6 and QGIS version differences.

Detects environment once at startup and exposes as module-level constants.
Used by compat layer and diagnostic tools.
"""

from qgis.core import Qgis
from qgis.PyQt import QtCore
from qgis.PyQt.QtWidgets import QDialog

def detect_qt_major_version(qtcore_module, qdialog_class):
    """
    Detect the active Qt major version.

    Prefer the runtime's reported Qt version and fall back to dialog API shape
    for older or mocked environments that do not expose QT_VERSION_STR.
    """
    version_str = getattr(qtcore_module, "QT_VERSION_STR", "")
    if isinstance(version_str, str):
        try:
            return int(version_str.split(".", 1)[0])
        except (TypeError, ValueError):
            pass

    # In Qt6, exec_() was removed in favor of exec().
    return 6 if not hasattr(qdialog_class, "exec_") else 5


QT_VERSION = detect_qt_major_version(QtCore, QDialog)
HAS_QT6 = QT_VERSION >= 6

# Dialog execution method name
DIALOG_EXEC_NAME = "exec" if HAS_QT6 else "exec_"

# Qt version as integer and string
QT_VERSION_STR = f"Qt{QT_VERSION}"

# QGIS API detection - MessageLevel enum added in QGIS 3.16
HAS_MESSAGE_ENUM = hasattr(Qgis, 'MessageLevel')

# QGIS version info
QGIS_VERSION_INT = Qgis.QGIS_VERSION_INT
QGIS_VERSION_STR = Qgis.QGIS_VERSION

# All exports
__all__ = [
    'HAS_QT6',
    'detect_qt_major_version',
    'QT_VERSION',
    'QT_VERSION_STR',
    'DIALOG_EXEC_NAME',
    'HAS_MESSAGE_ENUM',
    'QGIS_VERSION_INT',
    'QGIS_VERSION_STR',
]
