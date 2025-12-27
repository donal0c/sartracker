# -*- coding: utf-8 -*-
"""
Mission Resume Dialog

Phase 3 Refactor: Extracted from sartracker.py (lines 227-291)

Dialog to prompt user to resume a paused mission. Shows mission details
and offers options to resume or start fresh.

Qt5/Qt6 Compatible: Uses BaseDialog for rendering workarounds.
"""
from qgis.PyQt.QtWidgets import QVBoxLayout, QHBoxLayout, QLabel, QPushButton

from ..utils.dialog_utils import BaseDialog


class MissionResumeDialog(BaseDialog):
    """
    Dialog to prompt user to resume a paused mission.

    Shows mission details and offers two options:
    - Resume Mission: Restore saved mission state
    - Start Fresh: Clear saved state and begin new mission

    Qt5/Qt6 Compatible: Uses BaseDialog for rendering workarounds.
    """

    def __init__(self, saved_state, parent=None):
        """
        Initialize mission resume dialog.

        Args:
            saved_state: Dictionary containing mission state data
                Required keys: 'name', 'start_time'
            parent: Parent widget (should be iface.mainWindow())
        """
        super().__init__(parent)
        self.saved_state = saved_state
        self.setWindowTitle("Resume Mission?")
        self.setModal(True)
        self.setMinimumWidth(400)

        self._setup_ui()

    def _setup_ui(self):
        """Build the dialog UI."""
        layout = QVBoxLayout()

        # Format start time for display
        # Handle various edge cases: missing key, None value, non-string types
        try:
            start_time_raw = self.saved_state.get('start_time')
            if isinstance(start_time_raw, str) and len(start_time_raw) >= 19:
                start_time_display = start_time_raw[:19].replace('T', ' ')
            elif start_time_raw is not None:
                start_time_display = str(start_time_raw)
            else:
                start_time_display = 'Unknown'
        except Exception:
            start_time_display = 'Unknown'

        # Message label
        message = QLabel(
            f"<b>Found paused mission:</b><br><br>"
            f"Mission: {self.saved_state.get('name', 'Unknown')}<br>"
            f"Started: {start_time_display}<br><br>"
            f"Do you want to resume this mission?"
        )
        message.setWordWrap(True)
        layout.addWidget(message)

        # Buttons
        button_layout = QHBoxLayout()

        resume_button = QPushButton("Resume Mission")
        resume_button.setDefault(True)
        resume_button.clicked.connect(self.accept)
        button_layout.addWidget(resume_button)

        cancel_button = QPushButton("Start Fresh")
        cancel_button.clicked.connect(self.reject)
        button_layout.addWidget(cancel_button)

        layout.addLayout(button_layout)

        # Apply layout (triggers BaseDialog workarounds)
        self.setLayout(layout)
