# -*- coding: utf-8 -*-
"""
SAR Tracker Smoke Test

Automated environment validation to ensure Qt5/Qt6 compatibility
and QGIS API compatibility.
"""

import json
import os
import sys
import tempfile
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

    # Test 7: BaseDialog Rendering (Phase 3/6)
    results["tests"]["basedialog_rendering"] = _test_basedialog_rendering()

    # Test 8: run() Method Guard (Issue #3)
    results["tests"]["run_method_guard"] = _test_run_method_guard()

    # Overall result
    all_passed = all(result == "PASS" or result.startswith("SKIP") for result in results["tests"].values())
    results["overall"] = "PASS" if all_passed else "FAIL"

    # Save results to file (capture path for display)
    output_path = _save_results(results)

    # Show result in message bar (with file path if saved)
    _display_results(iface, results, output_path)

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
    """Test qt_compat module imports including Phase 2 additions."""
    try:
        from ..utils.qt_compat import (
            # Original constants
            CrossCursor, LeftButton, Key_Escape,
            dialog_exec, push_message, DialogAccepted,
            # Phase 2 additions - TextInteractionFlags
            TextSelectableByMouse, TextSelectableByKeyboard,
            NoTextInteraction, LinksAccessibleByMouse,
            # Phase 2 additions - WindowFlags
            WindowStaysOnTopHint, WindowModal, ApplicationModal,
            # Phase 2 additions - Arrow Keys
            Key_Left, Key_Right, Key_Up, Key_Down
        )

        # Verify original constants
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

        # Verify Phase 2 TextInteractionFlags
        if TextSelectableByMouse is None:
            return "FAIL: TextSelectableByMouse is None"
        if TextSelectableByKeyboard is None:
            return "FAIL: TextSelectableByKeyboard is None"
        if NoTextInteraction is None:
            return "FAIL: NoTextInteraction is None"
        if LinksAccessibleByMouse is None:
            return "FAIL: LinksAccessibleByMouse is None"

        # Verify Phase 2 WindowFlags
        if WindowStaysOnTopHint is None:
            return "FAIL: WindowStaysOnTopHint is None"
        if WindowModal is None:
            return "FAIL: WindowModal is None"
        if ApplicationModal is None:
            return "FAIL: ApplicationModal is None"

        # Verify Phase 2 Arrow Keys
        if Key_Left is None:
            return "FAIL: Key_Left is None"
        if Key_Right is None:
            return "FAIL: Key_Right is None"
        if Key_Up is None:
            return "FAIL: Key_Up is None"
        if Key_Down is None:
            return "FAIL: Key_Down is None"

        return "PASS"
    except Exception as e:
        return f"FAIL: {e}"


def _test_basedialog_rendering():
    """Test BaseDialog (SafeQDialog) instantiates and has proper rendering workarounds."""
    try:
        from ..utils.dialog_utils import BaseDialog, SafeQDialog
        from qgis.PyQt.QtWidgets import QVBoxLayout, QLabel, QDialog
        from ..utils.qt_compat import QT_VERSION

        # Verify BaseDialog is alias of SafeQDialog
        if BaseDialog is not SafeQDialog:
            return "FAIL: BaseDialog is not alias of SafeQDialog"

        # Create test dialog
        dialog = BaseDialog()
        dialog.setWindowTitle("Smoke Test Dialog")

        # Add simple layout to test rendering workarounds
        layout = QVBoxLayout()
        label = QLabel("Test label")
        layout.addWidget(label)
        dialog.setLayout(layout)

        # Verify dialog has workaround methods
        if not hasattr(dialog, '_apply_rendering_workarounds'):
            return "FAIL: BaseDialog missing _apply_rendering_workarounds method"

        # Verify dialog is QDialog subclass
        if not isinstance(dialog, QDialog):
            return "FAIL: BaseDialog is not QDialog subclass"

        # CRITICAL TEST: Verify exec/exec_ methods don't cause AttributeError
        # This tests Issue #1 fix

        # Test that the correct method exists on parent QDialog
        base_dialog = QDialog()
        if QT_VERSION == 6:
            if not hasattr(base_dialog, 'exec'):
                return "FAIL: Qt6 QDialog missing exec() method"
            if hasattr(base_dialog, 'exec_'):
                return "FAIL: Qt6 QDialog should not have exec_() method"
        else:  # Qt5
            if not hasattr(base_dialog, 'exec_'):
                return "FAIL: Qt5 QDialog missing exec_() method"
            if not hasattr(base_dialog, 'exec'):
                return "FAIL: Qt5 QDialog missing exec() method"

        # Test that our BaseDialog has both methods regardless of Qt version
        if not hasattr(dialog, 'exec'):
            return "FAIL: BaseDialog missing exec() method"
        if not hasattr(dialog, 'exec_'):
            return "FAIL: BaseDialog missing exec_() method"

        # Test that methods are callable (don't actually execute, that would block)
        if not callable(dialog.exec):
            return "FAIL: BaseDialog.exec() is not callable"
        if not callable(dialog.exec_):
            return "FAIL: BaseDialog.exec_() is not callable"

        # Verify the methods would call the correct parent method by checking
        # that they don't raise AttributeError when accessing super() methods
        # We can't actually call them without blocking, but we can verify the
        # parent has the methods that would be called
        try:
            # Simulate what happens inside exec_() and exec()
            from ..utils.qt_compat import QT_VERSION as qt_ver
            parent_class = super(BaseDialog, dialog)
            if qt_ver == 6:
                # Our code should call super().exec() on Qt6
                if not hasattr(parent_class, 'exec'):
                    return "FAIL: Qt6 parent class missing exec() for super() call"
            else:
                # Our code should call super().exec_() on Qt5
                if not hasattr(parent_class, 'exec_'):
                    return "FAIL: Qt5 parent class missing exec_() for super() call"
        except Exception as e:
            return f"FAIL: Error verifying super() method access: {e}"

        # Clean up
        dialog.deleteLater()
        base_dialog.deleteLater()

        return "PASS"
    except AttributeError as e:
        # This is the specific error we're trying to prevent with Issue #1 fix
        return f"FAIL: AttributeError indicates Qt6 compatibility issue: {e}"
    except Exception as e:
        return f"FAIL: {e}"


def _test_run_method_guard():
    """
    Test that run() method guards against None panel (Issue #3).

    Simulates scenario where imports failed but action callback fires.
    Verifies defensive guard prevents AttributeError crash.
    """
    try:
        from qgis.utils import plugins

        if 'sartracker' not in plugins:
            return "SKIP: Plugin not loaded"

        plugin = plugins['sartracker']

        # Save original panel reference
        original_panel = plugin.sar_panel

        try:
            # Simulate import failure scenario (panel is None)
            plugin.sar_panel = None

            # Attempt to call run() - should not crash
            try:
                plugin.run()
                # If we get here, guard worked (no AttributeError)
                result = "PASS"
            except AttributeError as e:
                # This indicates Issue #3 is not fixed!
                result = f"FAIL: run() crashed with AttributeError: {e}"

        finally:
            # Restore original panel reference
            plugin.sar_panel = original_panel

        return result

    except Exception as e:
        return f"FAIL: Test setup error: {e}"


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
    """
    Save test results to JSON file.

    Attempts to save to QGIS profile directory first (persistent storage),
    falls back to system temp directory if that fails. Uses timestamp in
    filename to prevent overwrites and maintain diagnostic history.

    Args:
        results: Test results dictionary

    Returns:
        str: Path to saved file, or None if save failed

    Qt5/Qt6 Compatible: Uses cross-platform tempfile.gettempdir()
    """
    try:
        # Determine output directory (hybrid approach)
        try:
            # Try QGIS profile directory first (persistent storage)
            from qgis.core import QgsApplication
            base_dir = QgsApplication.qgisSettingsDirPath()
            results_dir = os.path.join(base_dir, 'sartracker', 'diagnostics')
            os.makedirs(results_dir, exist_ok=True)
        except Exception:
            # Fall back to system temp directory (cross-platform)
            results_dir = tempfile.gettempdir()

        # Create unique filename with timestamp to prevent overwrites
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"sartracker_smoketest_{timestamp}.json"
        output_path = os.path.join(results_dir, filename)

        # Write results
        with open(output_path, 'w') as f:
            json.dump(results, f, indent=2)

        print(f"Smoke test results saved to: {output_path}")
        return output_path

    except Exception as e:
        print(f"Could not save smoke test results: {e}")
        return None


def _display_results(iface, results, output_path=None):
    """
    Display test results in message bar.

    Args:
        iface: QGIS interface instance
        results: Test results dictionary
        output_path: Path to saved results file (optional)

    Qt5/Qt6 Compatible: Uses utils.notify helpers
    """
    from ..utils.notify import success, error, warning

    overall = results["overall"]
    test_count = len(results["tests"])
    passed_count = sum(1 for result in results["tests"].values() if result == "PASS")

    if overall == "PASS":
        message = f"All {test_count} tests passed! Plugin is compatible with this environment."
        if output_path:
            message += f"\nResults saved to:\n{output_path}"
        success(
            iface.messageBar(),
            "Smoke Test",
            message,
            duration=5
        )
    else:
        failed_tests = [name for name, result in results["tests"].items() if result != "PASS"]
        message = f"{passed_count}/{test_count} tests passed. Failed: {', '.join(failed_tests)}"
        if output_path:
            message += f"\nResults saved to:\n{output_path}"
        error(
            iface.messageBar(),
            "Smoke Test",
            message,
            duration=8
        )
