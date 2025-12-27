# -*- coding: utf-8 -*-
"""
Import Failure Dialog

Phase 3 Refactor: Extracted from sartracker.py (lines 293-338)

Dialog to display import failure details when plugin fails to load.
Shows detailed error information in a scrollable text area to help
users diagnose and report plugin initialization problems.

Qt5/Qt6 Compatible: Uses BaseDialog for rendering workarounds.
"""
from qgis.PyQt.QtWidgets import QVBoxLayout, QPushButton, QTextEdit
from qgis.PyQt.QtGui import QFont

from ..utils.dialog_utils import BaseDialog


class ImportFailureDialog(BaseDialog):
    """
    Dialog to display import failure details when plugin fails to load.

    Shows detailed error information in a scrollable text area to help
    users diagnose and report plugin initialization problems.

    Qt5/Qt6 Compatible: Uses BaseDialog for rendering workarounds.
    """

    def __init__(self, error_summary, parent=None):
        """
        Initialize import failure dialog.

        Args:
            error_summary: Formatted string containing error details
            parent: Parent widget (should be iface.mainWindow())
        """
        super().__init__(parent)
        self.error_summary = error_summary
        self.setWindowTitle("SAR Tracker - Import Failure")
        self.setMinimumSize(700, 500)

        self._setup_ui()

    def _setup_ui(self):
        """Build the dialog UI."""
        layout = QVBoxLayout()

        # Scrollable text area for error details
        text_edit = QTextEdit()
        text_edit.setReadOnly(True)
        text_edit.setPlainText(self.error_summary)
        text_edit.setFont(QFont("Courier New", 9))
        layout.addWidget(text_edit)

        # Close button
        close_button = QPushButton("Close")
        close_button.clicked.connect(self.accept)
        layout.addWidget(close_button)

        # Apply layout (triggers BaseDialog workarounds)
        self.setLayout(layout)
