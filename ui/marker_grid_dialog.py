# -*- coding: utf-8 -*-
"""
Marker Grid Reference Dialog

Collects a marker type and TM65 Irish Grid reference before routing
into the normal marker dialog workflow.
"""

from qgis.PyQt.QtWidgets import (
    QVBoxLayout,
    QHBoxLayout,
    QFormLayout,
    QLabel,
    QPushButton,
    QComboBox,
    QLineEdit,
)

from ..utils.dialog_utils import BaseDialog


class MarkerGridDialog(BaseDialog):
    """Prompt for marker type and TM65 Irish Grid reference."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Marker at Grid Reference")
        self.setModal(True)
        self.setMinimumWidth(420)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout()

        message = QLabel(
            "Enter a TM65 Irish Grid reference, then continue into the normal "
            "marker form with coordinates pre-filled."
        )
        message.setWordWrap(True)
        layout.addWidget(message)

        form = QFormLayout()

        self.marker_type_combo = QComboBox()
        self.marker_type_combo.addItem("IPP/LKP", "ipp_lkp")
        self.marker_type_combo.addItem("Clue", "clue")
        self.marker_type_combo.addItem("Hazard", "hazard")
        self.marker_type_combo.addItem("Casualty", "casualty")
        form.addRow("Marker type:", self.marker_type_combo)

        self.grid_ref_input = QLineEdit()
        self.grid_ref_input.setPlaceholderText("e.g. Q 99840 04018")
        form.addRow("TM65 grid ref:", self.grid_ref_input)

        layout.addLayout(form)

        buttons = QHBoxLayout()
        buttons.addStretch()

        cancel_button = QPushButton("Cancel")
        cancel_button.clicked.connect(self.reject)
        buttons.addWidget(cancel_button)

        continue_button = QPushButton("Continue")
        continue_button.setDefault(True)
        continue_button.clicked.connect(self.accept)
        buttons.addWidget(continue_button)

        layout.addLayout(buttons)
        self.setLayout(layout)

    def get_marker_request(self):
        """Return selected marker type and trimmed grid reference text."""
        return self.marker_type_combo.currentData(), self.grid_ref_input.text().strip()
