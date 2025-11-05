# -*- coding: utf-8 -*-
"""
SAR Tracker Smoke Test

Automated environment validation to ensure Qt5/Qt6 compatibility
and QGIS API compatibility.
"""

import json
import os
import sys
from datetime import datetime


def run_smoke_test(iface):
    """
    Run comprehensive smoke test suite.

    Args:
        iface: QGIS interface instance

    Returns:
        dict: Test results
    """
    results = {
        "timestamp": datetime.now().isoformat(),
        "plugin_version": _get_plugin_version(),
        "tests": {}
    }

    # Import capabilities for version info
    try:
        from ..utils import capabilities
        results["qgis_version"] = capabilities.QGIS_VERSION_STR
        results["qt_version"] = capabilities.QT_VERSION_STR
        results["python_version"] = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    except Exception as e:
        results["qgis_version"] = "Unknown"
        results["qt_version"] = "Unknown"
        results["python_version"] = "Unknown"
        results["tests"]["capabilities_import"] = f"FAIL: {e}"

    # Test 1: Qt Imports
    results["tests"]["qt_imports"] = _test_qt_imports()

    # Test 2: QgsField Creation
    results["tests"]["qgsfield_creation"] = _test_qgsfield_creation()

    # Test 3: Dialog Execution
    results["tests"]["dialog_execution"] = _test_dialog_execution()

    # Test 4: Message Bar
    results["tests"]["message_bar"] = _test_message_bar(iface)

    # Test 5: Geometry Creation
    results["tests"]["geometry_creation"] = _test_geometry_creation()

    # Test 6: qt_compat Imports
    results["tests"]["qt_compat_imports"] = _test_qt_compat_imports()

    # Overall result
    all_passed = all(result == "PASS" for result in results["tests"].values())
    results["overall"] = "PASS" if all_passed else "FAIL"

    # Save results to file
    _save_results(results)

    # Show result in message bar
    _display_results(iface, results)

    return results


def _test_qt_imports():
    """Test Qt imports from qgis.PyQt."""
    try:
        from qgis.PyQt.QtCore import Qt
        from qgis.PyQt.QtWidgets import QDialog
        return "PASS"
    except Exception as e:
        return f"FAIL: {e}"


def _test_qgsfield_creation():
    """Test QgsField creation with QVariant pattern."""
    try:
        from qgis.core import QgsVectorLayer, QgsField
        from qgis.PyQt.QtCore import QVariant

        layer = QgsVectorLayer("Point?crs=epsg:4326", "test", "memory")
        if not layer.isValid():
            return "FAIL: Could not create memory layer"

        # Test field creation with QVariant types
        fields = [
            QgsField("name", QVariant.String),
            QgsField("value", QVariant.Double),
            QgsField("count", QVariant.Int),
        ]

        success = layer.dataProvider().addAttributes(fields)
        layer.updateFields()

        if not success:
            return "FAIL: Could not add attributes"

        # Verify fields were added
        if layer.fields().count() != 3:
            return f"FAIL: Expected 3 fields, got {layer.fields().count()}"

        return "PASS"
    except Exception as e:
        return f"FAIL: {e}"


def _test_dialog_execution():
    """Test dialog execution compatibility."""
    try:
        from qgis.PyQt.QtWidgets import QDialog
        from ..utils.qt_compat import dialog_exec, DialogAccepted

        # Create test dialog (don't show it, just verify the function exists)
        dialog = QDialog()

        # Verify dialog_exec is callable
        if not callable(dialog_exec):
            return "FAIL: dialog_exec is not callable"

        # Verify dialog has correct exec method
        from ..utils import capabilities
        if capabilities.HAS_QT6:
            if not hasattr(dialog, 'exec'):
                return "FAIL: Qt6 dialog missing exec() method"
        else:
            if not hasattr(dialog, 'exec_'):
                return "FAIL: Qt5 dialog missing exec_() method"

        return "PASS"
    except Exception as e:
        return f"FAIL: {e}"


def _test_message_bar(iface):
    """Test message bar notification."""
    try:
        from ..utils.notify import info

        # Test that info function works (display for 1 second)
        info(iface.messageBar(), "Smoke Test", "Testing message bar", duration=1)

        return "PASS"
    except Exception as e:
        return f"FAIL: {e}"


def _test_geometry_creation():
    """Test geometry creation."""
    try:
        from qgis.core import QgsGeometry, QgsPointXY

        # Create point geometry
        point = QgsGeometry.fromPointXY(QgsPointXY(-10.0, 52.0))
        if point.isNull():
            return "FAIL: Point geometry is null"

        # Create line geometry
        line = QgsGeometry.fromPolylineXY([
            QgsPointXY(0, 0),
            QgsPointXY(1, 1)
        ])
        if line.isNull():
            return "FAIL: Line geometry is null"

        # Create polygon geometry
        polygon = QgsGeometry.fromPolygonXY([[
            QgsPointXY(0, 0),
            QgsPointXY(1, 0),
            QgsPointXY(1, 1),
            QgsPointXY(0, 1),
            QgsPointXY(0, 0)
        ]])
        if polygon.isNull():
            return "FAIL: Polygon geometry is null"

        return "PASS"
    except Exception as e:
        return f"FAIL: {e}"


def _test_qt_compat_imports():
    """Test qt_compat module imports."""
    try:
        from ..utils.qt_compat import (
            CrossCursor, LeftButton, Key_Escape,
            dialog_exec, push_message, DialogAccepted
        )

        # Verify they're not None
        if CrossCursor is None:
            return "FAIL: CrossCursor is None"
        if LeftButton is None:
            return "FAIL: LeftButton is None"
        if Key_Escape is None:
            return "FAIL: Key_Escape is None"
        if dialog_exec is None:
            return "FAIL: dialog_exec is None"
        if push_message is None:
            return "FAIL: push_message is None"

        return "PASS"
    except Exception as e:
        return f"FAIL: {e}"


def _get_plugin_version():
    """Get plugin version from metadata.txt."""
    try:
        # Get path to metadata.txt (two levels up from this file)
        plugin_dir = os.path.dirname(os.path.dirname(__file__))
        metadata_path = os.path.join(plugin_dir, 'metadata.txt')

        if os.path.exists(metadata_path):
            with open(metadata_path, 'r') as f:
                for line in f:
                    if line.startswith('version='):
                        return line.split('=')[1].strip()
    except:
        pass

    return "Unknown"


def _save_results(results):
    """Save test results to JSON file."""
    try:
        output_path = "/tmp/sartracker_smoketest.json"
        with open(output_path, 'w') as f:
            json.dump(results, f, indent=2)
        print(f"Smoke test results saved to: {output_path}")
    except Exception as e:
        print(f"Could not save smoke test results: {e}")


def _display_results(iface, results):
    """Display test results in message bar."""
    from ..utils.notify import success, error

    overall = results["overall"]
    test_count = len(results["tests"])
    passed_count = sum(1 for result in results["tests"].values() if result == "PASS")

    if overall == "PASS":
        success(
            iface.messageBar(),
            "Smoke Test",
            f"All {test_count} tests passed! Plugin is compatible with this environment.",
            duration=5
        )
    else:
        failed_tests = [name for name, result in results["tests"].items() if result != "PASS"]
        error(
            iface.messageBar(),
            "Smoke Test",
            f"{passed_count}/{test_count} tests passed. Failed: {', '.join(failed_tests)}",
            duration=8
        )
