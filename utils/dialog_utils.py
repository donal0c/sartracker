# -*- coding: utf-8 -*-
"""
Dialog utilities for Qt 5.15.x rendering workarounds and Qt5/Qt6 compatibility.

This module provides utilities and base classes to work around known
Qt 5.15.x dialog rendering issues where dialogs appear blank or grey,
especially on Windows 10/11.

The module is fully compatible with both Qt5 and Qt6, automatically
detecting the Qt version and using the appropriate dialog execution method.

Classes:
    SafeQDialog - Base dialog class with automatic rendering workarounds
    BaseDialog - Alias for SafeQDialog (preferred for new code)
    DelayedShowDialog - Alternative dialog using delayed showing approach

Functions:
    safe_show_dialog(dialog) - Show any dialog with rendering workarounds
    create_test_dialog() - Create a test dialog for smoke testing

Qt5/Qt6 Compatibility:
    Both SafeQDialog and BaseDialog automatically handle the exec() vs exec_()
    difference between Qt5 and Qt6. No changes needed in subclasses.

Usage:
    # Recommended approach:
    from utils.dialog_utils import BaseDialog
    from utils.qt_compat import dialog_exec, DialogAccepted

    class MyDialog(BaseDialog):
        def __init__(self, parent=None):
            super().__init__(parent)
            # Your dialog code here

    # Execute the dialog (Qt5/Qt6 compatible):
    result = dialog_exec(dialog)
    if result == DialogAccepted:
        # Process dialog results
        pass
"""

from qgis.PyQt.QtCore import QTimer, QCoreApplication
from qgis.PyQt.QtWidgets import QDialog, QApplication


def safe_show_dialog(dialog, modal=True, force_update=True):
    """
    Safely show a dialog with Qt 5.15.x rendering workarounds.

    This function applies multiple workarounds for the known Qt 5.15.x issue
    where dialogs appear blank or grey, particularly on Windows.

    Args:
        dialog: QDialog instance to show
        modal: If True, use exec_() for modal display, otherwise show()
        force_update: If True, apply aggressive update workarounds

    Returns:
        Dialog result code if modal, None otherwise
    """
    # Workaround 1: Force layout calculation
    if dialog.layout():
        dialog.layout().activate()

    # Workaround 2: Adjust size to force geometry calculation
    dialog.adjustSize()

    # Workaround 3: Process pending events before showing
    QApplication.processEvents()

    # Workaround 4: Force update if requested
    if force_update:
        dialog.update()

    # Show dialog
    if modal:
        # For modal dialogs, use exec_() (Qt5) or exec() (Qt6)
        from .qt_compat import dialog_exec
        result = dialog_exec(dialog)

        # Extra safety: process events after close
        QApplication.processEvents()

        return result
    else:
        # For non-modal, just show
        dialog.show()

        # Workaround 5: Force repaint after show for non-modal
        if force_update:
            QTimer.singleShot(0, dialog.repaint)

        return None


class SafeQDialog(QDialog):
    """
    Base dialog class with built-in Qt 5.15.x rendering workarounds.

    This class automatically applies workarounds for the blank dialog
    rendering issue when used as a base class for custom dialogs.

    Example:
        class MyDialog(SafeQDialog):
            def __init__(self, parent=None):
                super().__init__(parent)
                self.setupUi()
    """

    def __init__(self, parent=None):
        """Initialize with rendering workarounds."""
        super().__init__(parent)
        self._first_show = True
        self._layout_set = False

    def setLayout(self, layout):
        """
        Override setLayout to activate layout immediately.

        This ensures layout calculation happens before the dialog is shown,
        preventing blank rendering.
        """
        super().setLayout(layout)

        if layout and not self._layout_set:
            self._layout_set = True

            # Force immediate layout calculation
            layout.activate()

            # Calculate proper size
            self.adjustSize()

            # Process any pending events
            QApplication.processEvents()

    def showEvent(self, event):
        """
        Override showEvent to force proper rendering on first show.

        This handles cases where the dialog still appears blank despite
        other workarounds.
        """
        super().showEvent(event)

        if self._first_show:
            self._first_show = False

            # Force layout recalculation
            if self.layout():
                self.layout().activate()

            # Process events to ensure painting
            QApplication.processEvents()

            # Force immediate repaint
            self.update()

            # Schedule another update just in case
            QTimer.singleShot(0, self._delayed_update)

    def _delayed_update(self):
        """Delayed update to ensure rendering."""
        self.repaint()

    def _apply_rendering_workarounds(self):
        """
        Apply rendering workarounds before showing dialog.

        Internal method to avoid code duplication between exec() and exec_().
        This method applies the necessary workarounds for Qt 5.15.x blank dialog
        rendering issues.
        """
        if self.layout():
            self.layout().activate()
        self.adjustSize()
        QApplication.processEvents()

    def exec_(self):
        """
        Override exec_ to apply workarounds before modal execution.

        Qt5 compatibility: This method exists for Qt5 where dialog.exec_() is standard.
        On Qt6, this method is deprecated but we keep it for backwards compatibility
        in case any code directly calls dialog.exec_().
        """
        self._apply_rendering_workarounds()

        # Call parent exec_ (Qt5) or exec (Qt6)
        from .qt_compat import QT_VERSION
        if QT_VERSION == 6:
            return super().exec()
        else:  # Qt5
            return super().exec_()

    def exec(self):
        """
        Qt5/Qt6 compatible exec method.

        This is the recommended method for Qt6. On Qt5, we delegate to exec_()
        to maintain compatibility. This method applies all rendering workarounds
        before executing the dialog.
        """
        self._apply_rendering_workarounds()

        # Call parent exec (Qt6) or exec_ (Qt5)
        from .qt_compat import QT_VERSION
        if QT_VERSION == 6:
            return super().exec()
        else:  # Qt5
            return super().exec_()


class DelayedShowDialog(QDialog):
    """
    Dialog that uses delayed showing to work around rendering issues.

    This approach gives Qt's event loop time to properly initialize
    the dialog before showing it.
    """

    def __init__(self, parent=None, delay_ms=0):
        """
        Initialize with optional show delay.

        Args:
            parent: Parent widget
            delay_ms: Delay in milliseconds before showing (0 = next event loop)
        """
        super().__init__(parent)
        self._delay_ms = delay_ms
        self._pending_show = False

    def show(self):
        """Override show to use delayed showing."""
        if not self._pending_show:
            self._pending_show = True
            QTimer.singleShot(self._delay_ms, self._do_show)

    def _do_show(self):
        """Actually show the dialog after delay."""
        self._pending_show = False

        # Apply workarounds
        if self.layout():
            self.layout().activate()
        self.adjustSize()
        QApplication.processEvents()

        # Now show
        super().show()

        # Force repaint
        self.repaint()


def ensure_dialog_visible(dialog):
    """
    Ensure a dialog is properly visible and rendered.

    This function can be called after showing a dialog to ensure
    it's properly rendered if it appears blank.

    Args:
        dialog: QDialog instance to ensure visible
    """
    # Force geometry recalculation
    dialog.adjustSize()

    # Activate layout if present
    if dialog.layout():
        dialog.layout().activate()

    # Process all pending events
    QApplication.processEvents()

    # Force updates
    dialog.update()
    dialog.repaint()

    # Raise and activate
    dialog.raise_()
    dialog.activateWindow()


def create_test_dialog(parent=None):
    """
    Create a test dialog to verify rendering workarounds.

    Returns:
        SafeQDialog instance with test content
    """
    from qgis.PyQt.QtWidgets import QVBoxLayout, QLabel, QPushButton

    dialog = SafeQDialog(parent)
    dialog.setWindowTitle("Qt 5.15.x Rendering Test")
    dialog.setModal(True)

    layout = QVBoxLayout()

    # Add test content
    layout.addWidget(QLabel("If you can read this, the workaround is working!"))
    layout.addWidget(QLabel("Qt 5.15.x blank dialog issue has been mitigated."))

    button = QPushButton("Close")
    button.clicked.connect(dialog.accept)
    layout.addWidget(button)

    # This will trigger our workarounds
    dialog.setLayout(layout)

    return dialog


# =============================================================================
# Aliases for clearer naming
# =============================================================================

# BaseDialog is a more intuitive name than SafeQDialog for general use
# Both names are exported for backward compatibility
BaseDialog = SafeQDialog


# =============================================================================
# Export all public symbols
# =============================================================================
__all__ = [
    'SafeQDialog',
    'BaseDialog',
    'DelayedShowDialog',
    'safe_show_dialog',
    'create_test_dialog',
]