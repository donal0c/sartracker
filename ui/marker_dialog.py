# -*- coding: utf-8 -*-
"""
Marker Dialog

Dialog for adding/editing SAR markers: IPP/LKP, Clues, and Hazards.
"""

from qgis.PyQt.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QFormLayout,
    QPushButton, QLineEdit, QTextEdit, QComboBox,
    QLabel, QGroupBox, QRadioButton, QButtonGroup, QFileDialog
)
from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsProject,
    QgsPointXY,
)

from ..utils.dialog_utils import BaseDialog
from ..utils.coordinates import (
    build_tm65_crs,
    format_irish_grid_reference,
    format_wgs84_degrees,
)


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

    def __init__(self, lat, lon, easting, northing, parent=None, existing_data=None):
        """
        Initialize marker dialog.

        BUG-079 FIX: Added coordinate validation to prevent NaN/Infinity values
        from reaching the UI. Invalid coordinates could result in markers being
        placed at incorrect locations during SAR operations.

        Args:
            lat: Latitude in WGS84 decimal degrees
            lon: Longitude in WGS84 decimal degrees
            easting: Irish Grid (ITM) easting (can be None)
            northing: Irish Grid (ITM) northing (can be None)
            parent: Parent widget
            existing_data: Existing marker data for edit mode

        Raises:
            ValueError: If lat/lon are NaN, Infinity, or out of range
        """
        import math

        # BUG-079 FIX: Validate coordinates before storing
        # LIFE-SAFETY CRITICAL: Invalid coordinates could misdirect rescue teams
        if lat is None or lon is None:
            raise ValueError("Coordinates cannot be None")

        if math.isnan(lat) or math.isinf(lat):
            raise ValueError(f"Invalid latitude: {lat} (NaN/Infinity not allowed)")
        if math.isnan(lon) or math.isinf(lon):
            raise ValueError(f"Invalid longitude: {lon} (NaN/Infinity not allowed)")

        if not (-90 <= lat <= 90):
            raise ValueError(f"Latitude {lat} out of valid range [-90, 90]")
        if not (-180 <= lon <= 180):
            raise ValueError(f"Longitude {lon} out of valid range [-180, 180]")

        # Validate Irish Grid coordinates if provided (optional fields)
        if easting is not None:
            if math.isnan(easting) or math.isinf(easting):
                raise ValueError(f"Invalid easting: {easting} (NaN/Infinity not allowed)")
            if not (0 <= easting <= 1000000):
                raise ValueError(f"Easting {easting} out of valid Irish Grid range [0, 1000000]")

        if northing is not None:
            if math.isnan(northing) or math.isinf(northing):
                raise ValueError(f"Invalid northing: {northing} (NaN/Infinity not allowed)")
            if not (0 <= northing <= 1500000):
                raise ValueError(f"Northing {northing} out of valid Irish Grid range [0, 1500000]")

        super().__init__(parent)

        self.lat = lat
        self.lon = lon
        self.easting = easting
        self.northing = northing

        self.existing_data = existing_data or {}
        self.edit_mode = bool(self.existing_data)
        self.marker_id = self.existing_data.get('id')
        self.marker_type = self.existing_data.get('type', "ipp_lkp")  # or "clue" or "hazard" or "casualty"
        self.itm = QgsCoordinateReferenceSystem("EPSG:2157")
        self.tm65 = build_tm65_crs()

        self._setup_ui()
        
    def _setup_ui(self):
        """Build the dialog UI."""
        self.setWindowTitle("Update Marker" if self.edit_mode else "Add Marker")
        self.setMinimumWidth(500)
        
        layout = QVBoxLayout()
        
        # Marker Type Selection
        type_group = QGroupBox("Marker Type")
        type_layout = QHBoxLayout()

        self.type_button_group = QButtonGroup()

        self.ipp_lkp_radio = QRadioButton("IPP/LKP")
        self.ipp_lkp_radio.setChecked(self.marker_type == "ipp_lkp")
        self.ipp_lkp_radio.setToolTip(
            "Initial Planning Point / Last Known Position\n"
            "The starting point for search planning, typically where the\n"
            "subject was last reliably seen or located."
        )
        self.ipp_lkp_radio.toggled.connect(self._on_type_changed)
        self.type_button_group.addButton(self.ipp_lkp_radio)
        type_layout.addWidget(self.ipp_lkp_radio)

        self.clue_radio = QRadioButton("Clue")
        self.clue_radio.setChecked(self.marker_type == "clue")
        self.clue_radio.setToolTip(
            "Evidence or clues found during search:\n"
            "Footprints, clothing, equipment, witness sightings, etc."
        )
        self.clue_radio.toggled.connect(self._on_type_changed)
        self.type_button_group.addButton(self.clue_radio)
        type_layout.addWidget(self.clue_radio)

        self.hazard_radio = QRadioButton("Hazard")
        self.hazard_radio.setChecked(self.marker_type == "hazard")
        self.hazard_radio.setToolTip(
            "Safety hazard marking:\n"
            "Cliffs, water hazards, bogs, dense vegetation, etc."
        )
        self.hazard_radio.toggled.connect(self._on_type_changed)
        self.type_button_group.addButton(self.hazard_radio)
        type_layout.addWidget(self.hazard_radio)

        self.casualty_radio = QRadioButton("Casualty")
        self.casualty_radio.setChecked(self.marker_type == "casualty")
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
        wgs84_label = QLabel(f"<b>{format_wgs84_degrees(self.lat, self.lon, precision=6)}</b>")
        coords_layout.addRow("WGS84:", wgs84_label)
        
        # Irish Grid (ITM) - BUG-083 FIX: Handle None values gracefully
        # Easting/northing can be None when coordinates are outside Ireland
        # or when Irish Grid data is not available
        if self.easting is not None and self.northing is not None:
            itm_label = QLabel(f"<b>E: {self.easting:,.0f}  N: {self.northing:,.0f}</b>")
        else:
            itm_label = QLabel("<i>Not available</i>")
        coords_layout.addRow("Irish Grid (ITM):", itm_label)

        tm65_ref = self._build_tm65_reference()
        if tm65_ref:
            self.tm65_label = QLabel(f"<b>{tm65_ref}</b>")
        else:
            self.tm65_label = QLabel("<i>Not available</i>")
        coords_layout.addRow("Irish Grid (TM65):", self.tm65_label)
        
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

        # Hazard Severity (only for Hazard)
        self.severity_combo = QComboBox()
        self.severity_combo.addItems([
            "Critical",
            "High",
            "Medium",
            "Low"
        ])
        default_severity_index = self.severity_combo.findText("Medium")
        if default_severity_index != -1:
            self.severity_combo.setCurrentIndex(default_severity_index)
        self.severity_label = QLabel("Severity:")
        details_layout.addRow(self.severity_label, self.severity_combo)

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

        # Found By (for Clue and Casualty)
        self.found_by_input = QLineEdit()
        self.found_by_input.setPlaceholderText("Team member or device ID...")
        self.found_by_label = QLabel("Found By:")
        details_layout.addRow(self.found_by_label, self.found_by_input)

        # Description/Notes
        self.description_input = QTextEdit()
        self.description_input.setPlaceholderText("Enter additional notes...")
        self.description_input.setMaximumHeight(100)
        details_layout.addRow("Notes:", self.description_input)

        # Updated By / Operator
        self.updated_by_input = QLineEdit()
        self.updated_by_input.setPlaceholderText("Operator / updated by")
        details_layout.addRow("Updated By:", self.updated_by_input)

        # Coordinator IDs
        self.coordinator_input = QLineEdit()
        self.coordinator_input.setPlaceholderText("Coordinator IDs (comma-separated)")
        details_layout.addRow("Coordinator IDs:", self.coordinator_input)

        # Attachment path (optional)
        attachment_layout = QHBoxLayout()
        self.attachment_input = QLineEdit()
        self.attachment_input.setPlaceholderText("Attachment path or URL...")
        attachment_layout.addWidget(self.attachment_input)
        self.attachment_button = QPushButton("Browse…")
        self.attachment_button.clicked.connect(self._on_browse_attachment)
        attachment_layout.addWidget(self.attachment_button)
        details_layout.addRow("Attachment:", attachment_layout)
        
        details_group.setLayout(details_layout)
        layout.addWidget(details_group)
        
        # Buttons
        buttons_layout = QHBoxLayout()
        
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.reject)
        buttons_layout.addWidget(self.cancel_button)
        
        buttons_layout.addStretch()
        
        self.save_button = QPushButton("Update Marker" if self.edit_mode else "Add Marker")
        self.save_button.setDefault(True)
        self.save_button.clicked.connect(self._on_save)
        buttons_layout.addWidget(self.save_button)
        
        layout.addLayout(buttons_layout)
        
        self.setLayout(layout)
        
        # Initial state
        self._on_type_changed()
        if self.edit_mode:
            self._load_existing_data()
        
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
        self.severity_label.setVisible(is_hazard)
        self.severity_combo.setVisible(is_hazard)

        # Casualty fields
        self.condition_label.setVisible(is_casualty)
        self.condition_combo.setVisible(is_casualty)
        self.treatment_label.setVisible(is_casualty)
        self.treatment_input.setVisible(is_casualty)
        self.evacuation_priority_label.setVisible(is_casualty)
        self.evacuation_priority_combo.setVisible(is_casualty)
        self.found_by_label.setVisible(is_clue or is_casualty)
        self.found_by_input.setVisible(is_clue or is_casualty)
        
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
            data['found_by'] = self.found_by_input.text().strip()
        elif self.marker_type == 'hazard':
            data['hazard_type'] = self.hazard_type_combo.currentText()
            data['severity'] = self.severity_combo.currentText()
        elif self.marker_type == 'casualty':
            data['condition'] = self.condition_combo.currentText()
            data['treatment'] = self.treatment_input.text().strip()
            data['evacuation_priority'] = self.evacuation_priority_combo.currentText()
            data['found_by'] = self.found_by_input.text().strip()

        data['updated_by'] = self.updated_by_input.text().strip()
        data['coordinator_ids'] = self.coordinator_input.text().strip()
        data['attachment_path'] = self.attachment_input.text().strip()

        if self.edit_mode and self.marker_id:
            data['id'] = self.marker_id

        return data

    # ------------------------------------------------------------------
    # Attachment helpers / edit mode
    # ------------------------------------------------------------------

    def _on_browse_attachment(self):
        """Open file picker for attachment path."""
        file_path, _ = QFileDialog.getOpenFileName(self, "Select Attachment", "", "All Files (*)")
        if file_path:
            self.attachment_input.setText(file_path)

    def _load_existing_data(self):
        """Populate form with existing marker details."""
        data = self.existing_data
        self.name_input.setText(data.get('name', ''))
        self.description_input.setPlainText(data.get('description', ''))
        self.updated_by_input.setText(data.get('updated_by', ''))
        self.coordinator_input.setText(data.get('coordinator_ids', ''))
        self.attachment_input.setText(data.get('attachment_path', ''))

        # Type-specific fields
        if self.marker_type == 'ipp_lkp':
            subject = data.get('subject_category')
            if subject:
                index = self.subject_category_combo.findText(subject)
                if index != -1:
                    self.subject_category_combo.setCurrentIndex(index)
        elif self.marker_type == 'clue':
            clue_type = data.get('clue_type')
            confidence = data.get('confidence')
            found_by = data.get('found_by')
            if clue_type:
                idx = self.clue_type_combo.findText(clue_type)
                if idx != -1:
                    self.clue_type_combo.setCurrentIndex(idx)
            if confidence:
                idx = self.confidence_combo.findText(confidence)
                if idx != -1:
                    self.confidence_combo.setCurrentIndex(idx)
            if found_by:
                self.found_by_input.setText(found_by)
        elif self.marker_type == 'hazard':
            hazard_type = data.get('hazard_type')
            severity = data.get('severity')
            if hazard_type:
                idx = self.hazard_type_combo.findText(hazard_type)
                if idx != -1:
                    self.hazard_type_combo.setCurrentIndex(idx)
            if severity:
                idx = self.severity_combo.findText(severity)
                if idx != -1:
                    self.severity_combo.setCurrentIndex(idx)
        elif self.marker_type == 'casualty':
            condition = data.get('condition')
            evacuation = data.get('evacuation_priority')
            found_by = data.get('found_by')
            treatment = data.get('treatment')
            if condition:
                idx = self.condition_combo.findText(condition)
                if idx != -1:
                    self.condition_combo.setCurrentIndex(idx)
            if evacuation:
                idx = self.evacuation_priority_combo.findText(evacuation)
                if idx != -1:
                    self.evacuation_priority_combo.setCurrentIndex(idx)
            if treatment:
                self.treatment_input.setText(treatment)
            if found_by:
                self.found_by_input.setText(found_by)

    def _build_tm65_reference(self):
        """Return read-only TM65 grid reference for the current ITM coordinates."""
        if self.easting is None or self.northing is None or not self.tm65 or not self.tm65.isValid():
            return None

        try:
            transform = QgsCoordinateTransform(self.itm, self.tm65, QgsProject.instance())
            tm65_point = transform.transform(QgsPointXY(self.easting, self.northing))
            return format_irish_grid_reference(tm65_point.x(), tm65_point.y())
        except Exception:
            return None
