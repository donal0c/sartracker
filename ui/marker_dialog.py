# -*- coding: utf-8 -*-
"""
Marker Dialog

Dialog for adding/editing SAR markers: IPP/LKP, Clues, and Hazards.
"""

from qgis.PyQt.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QFormLayout,
    QPushButton, QLineEdit, QTextEdit, QComboBox,
    QLabel, QGroupBox, QRadioButton, QButtonGroup
)

from ..utils.dialog_utils import BaseDialog


class MarkerDialog(BaseDialog):
    """
    Dialog for adding/editing SAR markers.

    Supports four marker types:
    - IPP/LKP (Initial Planning Point / Last Known Position)
    - Clue (Evidence, sightings, footprints, etc.)
    - Hazard (Safety-critical warnings)
    - Casualty (Found injured or deceased persons)

    Shows coordinates in both WGS84 and Irish Grid (ITM).
    """

    def __init__(self, lat, lon, easting, northing, parent=None):
        super().__init__(parent)

        self.lat = lat
        self.lon = lon
        self.easting = easting
        self.northing = northing

        self.marker_type = "ipp_lkp"  # or "clue" or "hazard" or "casualty"

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

        self.ipp_lkp_radio = QRadioButton("IPP/LKP")
        self.ipp_lkp_radio.setChecked(True)
        self.ipp_lkp_radio.setToolTip(
            "Initial Planning Point / Last Known Position\n"
            "The starting point for search planning, typically where the\n"
            "subject was last reliably seen or located."
        )
        self.ipp_lkp_radio.toggled.connect(self._on_type_changed)
        self.type_button_group.addButton(self.ipp_lkp_radio)
        type_layout.addWidget(self.ipp_lkp_radio)

        self.clue_radio = QRadioButton("Clue")
        self.clue_radio.setToolTip(
            "Evidence or clues found during search:\n"
            "Footprints, clothing, equipment, witness sightings, etc."
        )
        self.clue_radio.toggled.connect(self._on_type_changed)
        self.type_button_group.addButton(self.clue_radio)
        type_layout.addWidget(self.clue_radio)

        self.hazard_radio = QRadioButton("Hazard")
        self.hazard_radio.setToolTip(
            "Safety hazard marking:\n"
            "Cliffs, water hazards, bogs, dense vegetation, etc."
        )
        self.hazard_radio.toggled.connect(self._on_type_changed)
        self.type_button_group.addButton(self.hazard_radio)
        type_layout.addWidget(self.hazard_radio)

        self.casualty_radio = QRadioButton("Casualty")
        self.casualty_radio.setToolTip(
            "Found injured or deceased person:\n"
            "CRITICAL: Use for actual casualties requiring medical response,\n"
            "evacuation, and legal documentation. NOT for evidence/clues."
        )
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
        itm_label = QLabel(f"<b>E: {self.easting:,.0f}  N: {self.northing:,.0f}</b>")
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

        # Subject Category (only for IPP/LKP)
        self.subject_category_combo = QComboBox()
        self.subject_category_combo.addItems([
            "Child (1-3 years)",
            "Child (4-6 years)",
            "Child (7-12 years)",
            "Hiker",
            "Hunter",
            "Elderly",
            "Dementia Patient",
            "Despondent",
            "Autistic",
            "Other"
        ])
        self.subject_category_label = QLabel("Subject Category:")
        details_layout.addRow(self.subject_category_label, self.subject_category_combo)

        # Clue Type (only for Clue)
        self.clue_type_combo = QComboBox()
        self.clue_type_combo.addItems([
            "Footprint",
            "Clothing",
            "Equipment",
            "Witness Sighting",
            "Physical Evidence",
            "Other"
        ])
        self.clue_type_label = QLabel("Clue Type:")
        details_layout.addRow(self.clue_type_label, self.clue_type_combo)

        # Confidence Level (only for Clue)
        self.confidence_combo = QComboBox()
        self.confidence_combo.addItems([
            "Confirmed",
            "Probable",
            "Possible"
        ])
        self.confidence_label = QLabel("Confidence:")
        details_layout.addRow(self.confidence_label, self.confidence_combo)

        # Hazard Type (only for Hazard)
        self.hazard_type_combo = QComboBox()
        self.hazard_type_combo.addItems([
            "Cliff/Drop-off",
            "Water Hazard",
            "Bog/Peatland",
            "Dense Vegetation",
            "Wildlife Danger",
            "Weather Exposure",
            "Other"
        ])
        self.hazard_type_label = QLabel("Hazard Type:")
        details_layout.addRow(self.hazard_type_label, self.hazard_type_combo)

        # Casualty Condition (only for Casualty)
        self.condition_combo = QComboBox()
        self.condition_combo.addItems([
            "Injured - Conscious",
            "Injured - Unconscious",
            "Deceased",
            "Unresponsive",
            "Medical Emergency",
            "Unknown"
        ])
        self.condition_label = QLabel("Condition:*")
        details_layout.addRow(self.condition_label, self.condition_combo)

        # Treatment (only for Casualty)
        self.treatment_input = QLineEdit()
        self.treatment_input.setPlaceholderText("First aid administered...")
        self.treatment_label = QLabel("Treatment:")
        details_layout.addRow(self.treatment_label, self.treatment_input)

        # Evacuation Priority (only for Casualty)
        self.evacuation_priority_combo = QComboBox()
        self.evacuation_priority_combo.addItems([
            "Immediate",
            "Urgent",
            "Delayed",
            "None Required"
        ])
        self.evacuation_priority_label = QLabel("Evacuation Priority:")
        details_layout.addRow(self.evacuation_priority_label, self.evacuation_priority_combo)

        # Found By (only for Casualty)
        self.found_by_input = QLineEdit()
        self.found_by_input.setPlaceholderText("Team member or device ID...")
        self.found_by_label = QLabel("Found By:")
        details_layout.addRow(self.found_by_label, self.found_by_input)

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
        """Handle marker type change - show/hide relevant fields."""
        is_ipp_lkp = self.ipp_lkp_radio.isChecked()
        is_clue = self.clue_radio.isChecked()
        is_hazard = self.hazard_radio.isChecked()
        is_casualty = self.casualty_radio.isChecked()

        # Update marker type
        if is_ipp_lkp:
            self.marker_type = "ipp_lkp"
        elif is_clue:
            self.marker_type = "clue"
        elif is_hazard:
            self.marker_type = "hazard"
        else:
            self.marker_type = "casualty"

        # Show/hide type-specific fields
        # IPP/LKP fields
        self.subject_category_label.setVisible(is_ipp_lkp)
        self.subject_category_combo.setVisible(is_ipp_lkp)

        # Clue fields
        self.clue_type_label.setVisible(is_clue)
        self.clue_type_combo.setVisible(is_clue)
        self.confidence_label.setVisible(is_clue)
        self.confidence_combo.setVisible(is_clue)

        # Hazard fields
        self.hazard_type_label.setVisible(is_hazard)
        self.hazard_type_combo.setVisible(is_hazard)

        # Casualty fields
        self.condition_label.setVisible(is_casualty)
        self.condition_combo.setVisible(is_casualty)
        self.treatment_label.setVisible(is_casualty)
        self.treatment_input.setVisible(is_casualty)
        self.evacuation_priority_label.setVisible(is_casualty)
        self.evacuation_priority_combo.setVisible(is_casualty)
        self.found_by_label.setVisible(is_casualty)
        self.found_by_input.setVisible(is_casualty)
        
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
            Dict with marker details including type-specific fields
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

        # Add type-specific fields
        if self.marker_type == 'ipp_lkp':
            data['subject_category'] = self.subject_category_combo.currentText()
        elif self.marker_type == 'clue':
            data['clue_type'] = self.clue_type_combo.currentText()
            data['confidence'] = self.confidence_combo.currentText()
        elif self.marker_type == 'hazard':
            data['hazard_type'] = self.hazard_type_combo.currentText()
        elif self.marker_type == 'casualty':
            data['condition'] = self.condition_combo.currentText()
            data['treatment'] = self.treatment_input.text().strip()
            data['evacuation_priority'] = self.evacuation_priority_combo.currentText()
            data['found_by'] = self.found_by_input.text().strip()

        return data
