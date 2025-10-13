# -*- coding: utf-8 -*-
"""
Marker Dialog

Dialog for adding/editing POI and Casualty markers.
"""

from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QPushButton, QLineEdit, QTextEdit, QComboBox,
    QLabel, QGroupBox, QRadioButton, QButtonGroup
)
from qgis.PyQt.QtCore import Qt


class MarkerDialog(QDialog):
    """
    Dialog for adding/editing markers (POI or Casualty).
    
    Shows coordinates in both WGS84 and Irish Grid (ITM).
    """
    
    def __init__(self, lat, lon, easting, northing, parent=None):
        super().__init__(parent)
        
        self.lat = lat
        self.lon = lon
        self.easting = easting
        self.northing = northing
        
        self.marker_type = "poi"  # or "casualty"
        
        self._setup_ui()
        
    def _setup_ui(self):
        """Build the dialog UI."""
        self.setWindowTitle("Add Marker")
        self.setMinimumWidth(500)
        
        layout = QVBoxLayout()
        
        # Marker Type Selection
        type_group = QGroupBox("Marker Type")
        type_layout = QHBoxLayout()
        
        self.type_button_group = QButtonGroup()
        
        self.poi_radio = QRadioButton("Point of Interest (POI)")
        self.poi_radio.setChecked(True)
        self.poi_radio.toggled.connect(self._on_type_changed)
        self.type_button_group.addButton(self.poi_radio)
        type_layout.addWidget(self.poi_radio)
        
        self.casualty_radio = QRadioButton("Casualty")
        self.casualty_radio.toggled.connect(self._on_type_changed)
        self.type_button_group.addButton(self.casualty_radio)
        type_layout.addWidget(self.casualty_radio)
        
        type_group.setLayout(type_layout)
        layout.addWidget(type_group)
        
        # Coordinates Display
        coords_group = QGroupBox("Coordinates")
        coords_layout = QFormLayout()
        
        # WGS84
        wgs84_label = QLabel(f"<b>{self.lat:.6f}°N, {self.lon:.6f}°E</b>")
        coords_layout.addRow("WGS84:", wgs84_label)
        
        # Irish Grid (ITM)
        itm_label = QLabel(f"<b>E: {int(self.easting):,}  N: {int(self.northing):,}</b>")
        coords_layout.addRow("Irish Grid (ITM):", itm_label)
        
        coords_group.setLayout(coords_layout)
        layout.addWidget(coords_group)
        
        # Marker Details
        details_group = QGroupBox("Details")
        details_layout = QFormLayout()
        
        # Name
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("Enter name...")
        details_layout.addRow("Name:*", self.name_input)
        
        # POI Type (only for POI)
        self.poi_type_combo = QComboBox()
        self.poi_type_combo.addItems([
            "Base/Command Post",
            "Vehicle",
            "Landmark",
            "Hazard",
            "Water Source",
            "Shelter",
            "Other"
        ])
        self.poi_type_row_label = QLabel("Type:")
        details_layout.addRow(self.poi_type_row_label, self.poi_type_combo)
        
        # Casualty Condition (only for Casualty)
        self.condition_combo = QComboBox()
        self.condition_combo.addItems([
            "Uninjured",
            "Minor Injury",
            "Serious Injury",
            "Critical",
            "Deceased",
            "Unknown"
        ])
        self.condition_row_label = QLabel("Condition:")
        details_layout.addRow(self.condition_row_label, self.condition_combo)
        
        # Description/Notes
        self.description_input = QTextEdit()
        self.description_input.setPlaceholderText("Enter additional notes...")
        self.description_input.setMaximumHeight(100)
        details_layout.addRow("Notes:", self.description_input)
        
        details_group.setLayout(details_layout)
        layout.addWidget(details_group)
        
        # Buttons
        buttons_layout = QHBoxLayout()
        
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.reject)
        buttons_layout.addWidget(self.cancel_button)
        
        buttons_layout.addStretch()
        
        self.save_button = QPushButton("Add Marker")
        self.save_button.setDefault(True)
        self.save_button.clicked.connect(self._on_save)
        buttons_layout.addWidget(self.save_button)
        
        layout.addLayout(buttons_layout)
        
        self.setLayout(layout)
        
        # Initial state
        self._on_type_changed()
        
    def _on_type_changed(self):
        """Handle marker type change."""
        is_poi = self.poi_radio.isChecked()
        self.marker_type = "poi" if is_poi else "casualty"
        
        # Show/hide type-specific fields
        self.poi_type_row_label.setVisible(is_poi)
        self.poi_type_combo.setVisible(is_poi)
        
        self.condition_row_label.setVisible(not is_poi)
        self.condition_combo.setVisible(not is_poi)
        
    def _on_save(self):
        """Validate and save."""
        if not self.name_input.text().strip():
            self.name_input.setFocus()
            self.name_input.setStyleSheet("border: 1px solid red;")
            return
        
        self.accept()
    
    def get_marker_data(self):
        """
        Get marker data from dialog.
        
        Returns:
            Dict with marker details
        """
        data = {
            'type': self.marker_type,
            'name': self.name_input.text().strip(),
            'description': self.description_input.toPlainText().strip(),
            'lat': self.lat,
            'lon': self.lon,
            'easting': self.easting,
            'northing': self.northing
        }
        
        if self.marker_type == 'poi':
            data['poi_type'] = self.poi_type_combo.currentText()
        else:
            data['condition'] = self.condition_combo.currentText()
        
        return data
