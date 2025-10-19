# -*- coding: utf-8 -*-
"""
Bearing Line Drawing Tool

Interactive tool for creating direction-finding lines based on bearing and distance.
Used for witness sightings, radio direction finding, and line-of-sight analysis.

Qt5/Qt6 Compatible: Uses qgis.PyQt and qt_compat for all Qt imports.
"""

from qgis.core import QgsPointXY, QgsGeometry, QgsWkbTypes
from qgis.gui import QgsRubberBand
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QColor
from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QDoubleSpinBox, QComboBox,
    QGroupBox, QFormLayout, QRadioButton, QButtonGroup
)

# Import Qt5/Qt6 compatible constants and functions
from ..utils.qt_compat import LeftButton, RightButton, Key_Escape, dialog_exec, push_message, DialogAccepted

from .base_drawing_tool import BaseDrawingTool


class BearingLineDialog(QDialog):
    """
    Dialog for configuring bearing line parameters.

    User can specify:
    - Line name
    - Bearing (0-360°) with true/magnetic option
    - Distance in meters or kilometers
    - Color
    """

    # Magnetic declination for Ireland (approximate)
    # Negative = West declination
    MAGNETIC_DECLINATION_IRELAND = -4.5

    def __init__(self, origin_lat, origin_lon, parent=None):
        """
        Initialize bearing line dialog.

        Args:
            origin_lat: Origin point latitude (WGS84)
            origin_lon: Origin point longitude (WGS84)
            parent: Parent widget (optional)
        """
        super().__init__(parent)
        self.setWindowTitle("Create Bearing Line")
        self.setModal(True)
        self.setMinimumWidth(450)

        # Store origin coordinates
        self.origin_lat = origin_lat
        self.origin_lon = origin_lon

        # Result data
        self.bearing_data = None

        self._setup_ui()

    def _setup_ui(self):
        """Create dialog UI."""
        layout = QVBoxLayout()

        # Origin information group
        origin_group = QGroupBox("Origin Point")
        origin_layout = QFormLayout()

        origin_text = f"{self.origin_lat:.6f}°, {self.origin_lon:.6f}°"
        origin_label = QLabel(origin_text)
        origin_layout.addRow("Coordinates:", origin_label)

        origin_group.setLayout(origin_layout)
        layout.addWidget(origin_group)

        # Line name
        name_group = QGroupBox("Line Information")
        name_layout = QFormLayout()

        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("e.g., Witness Sighting, DF Line 1")
        name_layout.addRow("Line Name:", self.name_input)

        name_group.setLayout(name_layout)
        layout.addWidget(name_group)

        # Bearing configuration group
        bearing_group = QGroupBox("Bearing Configuration")
        bearing_layout = QVBoxLayout()

        # Bearing type selection
        type_layout = QHBoxLayout()
        self.bearing_type_group = QButtonGroup()
        self.true_bearing_radio = QRadioButton("True Bearing (Geographic North)")
        self.magnetic_bearing_radio = QRadioButton("Magnetic Bearing (Compass)")

        self.bearing_type_group.addButton(self.true_bearing_radio, 0)
        self.bearing_type_group.addButton(self.magnetic_bearing_radio, 1)
        self.true_bearing_radio.setChecked(True)

        type_layout.addWidget(self.true_bearing_radio)
        type_layout.addWidget(self.magnetic_bearing_radio)
        bearing_layout.addLayout(type_layout)

        # Bearing value
        bearing_value_layout = QFormLayout()
        self.bearing_spin = QDoubleSpinBox()
        self.bearing_spin.setRange(0.0, 360.0)
        self.bearing_spin.setValue(0.0)
        self.bearing_spin.setSuffix("°")
        self.bearing_spin.setDecimals(1)
        self.bearing_spin.setWrapping(True)  # Wrap around from 360 to 0
        bearing_value_layout.addRow("Bearing:", self.bearing_spin)
        bearing_layout.addLayout(bearing_value_layout)

        # Magnetic declination info
        declination_text = f"(Magnetic declination for Ireland: {self.MAGNETIC_DECLINATION_IRELAND:+.1f}°)"
        self.declination_label = QLabel(declination_text)
        self.declination_label.setStyleSheet("QLabel { color: #666; font-size: 10pt; }")
        self.declination_label.setVisible(False)
        bearing_layout.addWidget(self.declination_label)

        # Converted bearing display
        self.converted_bearing_label = QLabel("")
        self.converted_bearing_label.setStyleSheet("QLabel { color: #0066cc; font-weight: bold; }")
        self.converted_bearing_label.setVisible(False)
        bearing_layout.addWidget(self.converted_bearing_label)

        bearing_group.setLayout(bearing_layout)
        layout.addWidget(bearing_group)

        # Distance configuration group
        distance_group = QGroupBox("Distance Configuration")
        distance_layout = QFormLayout()

        # Distance input
        distance_input_layout = QHBoxLayout()
        self.distance_spin = QDoubleSpinBox()
        self.distance_spin.setRange(1.0, 100000.0)  # 1m to 100km
        self.distance_spin.setValue(1000.0)
        self.distance_spin.setDecimals(1)
        distance_input_layout.addWidget(self.distance_spin)

        self.distance_unit_combo = QComboBox()
        self.distance_unit_combo.addItems(["meters", "kilometers"])
        self.distance_unit_combo.currentTextChanged.connect(self._on_distance_unit_changed)
        distance_input_layout.addWidget(self.distance_unit_combo)

        distance_layout.addRow("Distance:", distance_input_layout)

        distance_group.setLayout(distance_layout)
        layout.addWidget(distance_group)

        # Color selection
        color_group = QGroupBox("Display")
        color_layout = QFormLayout()

        self.color_combo = QComboBox()
        self.color_combo.addItem("Purple", "#800080")
        self.color_combo.addItem("Red", "#FF0000")
        self.color_combo.addItem("Blue", "#0000FF")
        self.color_combo.addItem("Green", "#00AA00")
        self.color_combo.addItem("Orange", "#FFA500")
        self.color_combo.addItem("Yellow", "#FFD700")
        color_layout.addRow("Color:", self.color_combo)

        color_group.setLayout(color_layout)
        layout.addWidget(color_group)

        # Buttons
        button_layout = QHBoxLayout()
        button_layout.addStretch()

        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(cancel_btn)

        create_btn = QPushButton("Create Bearing Line")
        create_btn.clicked.connect(self._create_bearing_line)
        create_btn.setDefault(True)
        button_layout.addWidget(create_btn)

        layout.addLayout(button_layout)

        self.setLayout(layout)

        # Connect signals
        self.true_bearing_radio.toggled.connect(self._on_bearing_type_changed)
        self.magnetic_bearing_radio.toggled.connect(self._on_bearing_type_changed)
        self.bearing_spin.valueChanged.connect(self._update_converted_bearing)

        # Focus on name input
        self.name_input.setFocus()

    def _on_bearing_type_changed(self):
        """Handle bearing type radio button changes."""
        is_magnetic = self.magnetic_bearing_radio.isChecked()
        self.declination_label.setVisible(is_magnetic)
        self._update_converted_bearing()

    def _update_converted_bearing(self):
        """Update the converted bearing display."""
        if self.magnetic_bearing_radio.isChecked():
            # User entered magnetic, show true bearing
            magnetic_bearing = self.bearing_spin.value()
            true_bearing = magnetic_bearing - self.MAGNETIC_DECLINATION_IRELAND
            # Normalize to 0-360
            if true_bearing < 0:
                true_bearing += 360
            elif true_bearing >= 360:
                true_bearing -= 360

            self.converted_bearing_label.setText(f"→ True Bearing: {true_bearing:.1f}°")
            self.converted_bearing_label.setVisible(True)
        elif self.true_bearing_radio.isChecked():
            # User entered true, optionally show magnetic
            true_bearing = self.bearing_spin.value()
            magnetic_bearing = true_bearing + self.MAGNETIC_DECLINATION_IRELAND
            # Normalize to 0-360
            if magnetic_bearing < 0:
                magnetic_bearing += 360
            elif magnetic_bearing >= 360:
                magnetic_bearing -= 360

            self.converted_bearing_label.setText(f"→ Magnetic Bearing: {magnetic_bearing:.1f}°")
            self.converted_bearing_label.setVisible(True)
        else:
            self.converted_bearing_label.setVisible(False)

    def _on_distance_unit_changed(self, unit):
        """Handle distance unit changes."""
        if unit == "kilometers":
            # Convert range to km
            self.distance_spin.setRange(0.001, 100.0)
            if self.distance_spin.value() > 100.0:
                self.distance_spin.setValue(1.0)
        else:  # meters
            self.distance_spin.setRange(1.0, 100000.0)
            if self.distance_spin.value() < 1.0:
                self.distance_spin.setValue(1000.0)

    def _create_bearing_line(self):
        """Validate input and prepare bearing line data."""
        name = self.name_input.text().strip()
        if not name:
            name = "Bearing Line"

        # Get bearing value
        bearing_input = self.bearing_spin.value()

        # Convert to true bearing if magnetic was entered
        if self.magnetic_bearing_radio.isChecked():
            true_bearing = bearing_input - self.MAGNETIC_DECLINATION_IRELAND
            # Normalize to 0-360
            if true_bearing < 0:
                true_bearing += 360
            elif true_bearing >= 360:
                true_bearing -= 360
            bearing_type = "Magnetic"
            magnetic_bearing = bearing_input
        else:
            true_bearing = bearing_input
            bearing_type = "True"
            magnetic_bearing = bearing_input + self.MAGNETIC_DECLINATION_IRELAND
            if magnetic_bearing < 0:
                magnetic_bearing += 360
            elif magnetic_bearing >= 360:
                magnetic_bearing -= 360

        # Get distance in meters
        distance_value = self.distance_spin.value()
        distance_unit = self.distance_unit_combo.currentText()

        if distance_unit == "kilometers":
            distance_m = distance_value * 1000.0
        else:
            distance_m = distance_value

        # Validate distance
        if distance_m <= 0 or distance_m > 100000:
            from qgis.PyQt.QtWidgets import QMessageBox
            QMessageBox.warning(self, "Invalid Distance",
                              "Distance must be between 1m and 100km (100,000m).")
            return

        # Get color
        color = self.color_combo.currentData()

        # Create label
        label = f"{bearing_input:.1f}° ({bearing_type}), {distance_m:.0f}m"

        # Prepare result data
        self.bearing_data = {
            'name': name,
            'bearing': true_bearing,  # Always store true bearing
            'bearing_input': bearing_input,  # What user entered
            'bearing_type': bearing_type,
            'magnetic_bearing': magnetic_bearing,
            'distance_m': distance_m,
            'label': label,
            'color': color
        }

        self.accept()


class BearingTool(BaseDrawingTool):
    """
    Tool for creating bearing lines.

    Click to set origin point, then configure bearing and distance in dialog.
    """

    def __init__(self, canvas, layers_controller):
        """
        Initialize bearing line tool.

        Args:
            canvas: QGIS map canvas
            layers_controller: LayersController instance for saving bearing lines
        """
        super().__init__(canvas)
        self.layers_controller = layers_controller

        # State
        self.origin_point = None  # Canvas CRS

    def activate(self):
        """Called when tool is activated."""
        super().activate()
        self.origin_point = None

    def deactivate(self):
        """Called when tool is deactivated."""
        super().deactivate()
        self.origin_point = None

    def canvasPressEvent(self, event):
        """
        Handle mouse click to set origin point.

        Args:
            event: QgsMapMouseEvent
        """
        if event.button() == LeftButton:
            # Get click position
            self.origin_point = self.toMapCoordinates(event.pos())

            # Show configuration dialog
            self._show_dialog()

    def _show_dialog(self):
        """Show bearing line configuration dialog."""
        try:
            # Transform origin to WGS84 for display
            origin_wgs84 = self.transform_to_wgs84(self.origin_point)

            # Use None as parent since canvas is not a QWidget
            dialog = BearingLineDialog(origin_wgs84.y(), origin_wgs84.x(), None)

            if dialog_exec(dialog) == DialogAccepted and dialog.bearing_data:
                self._create_bearing_line(origin_wgs84, dialog.bearing_data)
            else:
                # User cancelled
                self.origin_point = None
                if self.canvas:
                    self.canvas.unsetMapTool(self)
                self.drawing_cancelled.emit()

        except Exception as e:
            print(f"Error showing bearing dialog: {e}")
            import traceback
            traceback.print_exc()
            self.origin_point = None
            if self.canvas:
                self.canvas.unsetMapTool(self)
            self.drawing_cancelled.emit()

    def _create_bearing_line(self, origin_wgs84, bearing_data):
        """
        Create bearing line based on configuration.

        Args:
            origin_wgs84: Origin point in WGS84
            bearing_data: Dict with bearing line configuration
        """
        success = False
        try:
            # Add to layer using DrawingManager
            feature_id = self.layers_controller.add_bearing_line(
                name=bearing_data['name'],
                origin_wgs84=origin_wgs84,
                bearing=bearing_data['bearing'],  # True bearing
                distance_m=bearing_data['distance_m'],
                label=bearing_data['label'],
                color=bearing_data['color']
            )

            success = True

            # Emit completion signal
            self.drawing_complete.emit({
                'type': 'bearing_line',
                'feature_id': feature_id,
                'name': bearing_data['name'],
                'bearing': bearing_data['bearing'],
                'bearing_type': bearing_data['bearing_type'],
                'magnetic_bearing': bearing_data['magnetic_bearing'],
                'distance_m': bearing_data['distance_m'],
                'origin_lat': origin_wgs84.y(),
                'origin_lon': origin_wgs84.x()
            })

        except Exception as e:
            print(f"Error creating bearing line: {e}")
            import traceback
            traceback.print_exc()
            # Show error to user
            try:
                from qgis.utils import iface
                if iface:
                    push_message(
                        iface.messageBar(),
                        "Error",
                        f"Failed to create bearing line: {str(e)}",
                        level=2,  # Warning
                        duration=5
                    )
            except:
                pass  # iface not available

        finally:
            # ALWAYS reset, whether success or failure
            self.origin_point = None
            self.clear_rubber_bands()

            # Immediately unset this tool from the canvas to prevent further clicks
            # This is critical - without this, the tool keeps intercepting mouse events
            if self.canvas:
                self.canvas.unsetMapTool(self)

            # If failed, emit cancelled signal so tool deactivates
            if not success:
                self.drawing_cancelled.emit()

    def cancel(self):
        """Cancel current operation."""
        self.origin_point = None
        self.clear_rubber_bands()
        # Immediately unset this tool from the canvas
        if self.canvas:
            self.canvas.unsetMapTool(self)
        self.drawing_cancelled.emit()
