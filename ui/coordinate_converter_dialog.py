# -*- coding: utf-8 -*-
"""
Coordinate Converter Dialog

Convert between Irish Grid (ITM) and WGS84 coordinates.
"""

import logging
import math

from qgis.PyQt.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QFormLayout,
    QPushButton, QLineEdit, QLabel, QGroupBox, QRadioButton,
    QButtonGroup, QApplication, QComboBox
)
from qgis.PyQt.QtCore import pyqtSignal

from ..utils.dialog_utils import BaseDialog
from ..utils.coordinates import (
    build_tm65_crs,
    format_irish_grid_reference,
    format_wgs84_degrees,
    parse_irish_grid_reference,
)
from ..config.keys import ConfigStore, SETTINGS_KEYS
from qgis.core import (
    QgsCoordinateReferenceSystem, QgsCoordinateTransform,
    QgsProject, QgsPointXY, QgsRectangle, QgsCsException
)

logger = logging.getLogger(__name__)


class CoordinateConverterDialog(BaseDialog):
    """
    Dialog for converting coordinates between Irish Grid (ITM) and WGS84.
    """

    go_to_location = pyqtSignal(float, float)  # lat, lon

    def __init__(self, parent=None):
        super().__init__(parent)

        # Coordinate systems
        self.wgs84 = QgsCoordinateReferenceSystem("EPSG:4326")
        # Use EPSG:2157 (Irish Transverse Mercator / ITM) - the modern Irish Grid
        # Note: EPSG:29903 is the older TM65 Irish Grid which has 1-3m accuracy issues
        self.itm = QgsCoordinateReferenceSystem("EPSG:2157")
        self.tm65 = build_tm65_crs()

        # BUG-057 fix: Track timers to prevent crashes on early dialog close
        self.copy_timer = None
        self.goto_timer = None
        self.coordinate_display_mode = ConfigStore.get_coordinate_display_mode()

        self._setup_ui()

    def _setup_ui(self):
        """Build the dialog UI."""
        self.setWindowTitle("Coordinate Converter")
        self.setMinimumWidth(500)

        layout = QVBoxLayout()

        # Workflow Display Mode
        mode_group = QGroupBox("Workflow Mode")
        mode_layout = QFormLayout()
        self.display_mode_combo = QComboBox()
        self.display_mode_combo.addItem(
            "Lat/Lon first",
            SETTINGS_KEYS.COORDINATE_DISPLAY_MODE_LATLON_FIRST
        )
        self.display_mode_combo.addItem(
            "TM65 grid first",
            SETTINGS_KEYS.COORDINATE_DISPLAY_MODE_TM65_FIRST
        )
        mode_index = self.display_mode_combo.findData(self.coordinate_display_mode)
        if mode_index >= 0:
            self.display_mode_combo.setCurrentIndex(mode_index)
        self.display_mode_combo.currentIndexChanged.connect(self._on_display_mode_changed)
        mode_layout.addRow("Coordinate display:", self.display_mode_combo)
        mode_group.setLayout(mode_layout)
        layout.addWidget(mode_group)

        # Input Type Selection
        type_group = QGroupBox("Convert From")
        type_layout = QHBoxLayout()

        self.type_button_group = QButtonGroup()

        self.wgs84_radio = QRadioButton("WGS84 (Lat/Lon)")
        self.wgs84_radio.setChecked(True)
        self.wgs84_radio.toggled.connect(self._on_input_type_changed)
        self.type_button_group.addButton(self.wgs84_radio)
        type_layout.addWidget(self.wgs84_radio)

        self.irish_grid_radio = QRadioButton("Irish Grid (ITM)")
        self.irish_grid_radio.toggled.connect(self._on_input_type_changed)
        self.type_button_group.addButton(self.irish_grid_radio)
        type_layout.addWidget(self.irish_grid_radio)

        self.tm65_grid_radio = QRadioButton("Irish Grid Reference (TM65)")
        self.tm65_grid_radio.toggled.connect(self._on_input_type_changed)
        self.type_button_group.addButton(self.tm65_grid_radio)
        type_layout.addWidget(self.tm65_grid_radio)

        type_group.setLayout(type_layout)
        layout.addWidget(type_group)

        # Input Section
        input_group = QGroupBox("Input Coordinates")
        input_layout = QFormLayout()

        # WGS84 Inputs
        self.lat_input = QLineEdit()
        self.lat_input.setPlaceholderText("e.g. 52.274681")
        self.lat_label = QLabel("Latitude:")
        input_layout.addRow(self.lat_label, self.lat_input)

        self.lon_input = QLineEdit()
        self.lon_input.setPlaceholderText("e.g. -9.530912")
        self.lon_label = QLabel("Longitude:")
        input_layout.addRow(self.lon_label, self.lon_input)

        # Irish Grid Inputs
        self.easting_input = QLineEdit()
        self.easting_input.setPlaceholderText("e.g. 95553")
        self.easting_label = QLabel("Easting (E):")
        input_layout.addRow(self.easting_label, self.easting_input)

        self.northing_input = QLineEdit()
        self.northing_input.setPlaceholderText("e.g. 114716")
        self.northing_label = QLabel("Northing (N):")
        input_layout.addRow(self.northing_label, self.northing_input)

        # TM65 Grid Reference Input
        self.tm65_grid_input = QLineEdit()
        self.tm65_grid_input.setPlaceholderText("e.g. Q 99840 04018")
        self.tm65_grid_label = QLabel("Grid Reference:")
        input_layout.addRow(self.tm65_grid_label, self.tm65_grid_input)

        input_group.setLayout(input_layout)
        layout.addWidget(input_group)

        # Convert Button
        convert_btn_layout = QHBoxLayout()
        convert_btn_layout.addStretch()
        self.convert_button = QPushButton("Convert")
        self.convert_button.setDefault(True)
        self.convert_button.clicked.connect(self._on_convert)
        convert_btn_layout.addWidget(self.convert_button)
        convert_btn_layout.addStretch()
        layout.addLayout(convert_btn_layout)

        # Results Section
        results_group = QGroupBox("Converted Coordinates")
        results_layout = QVBoxLayout()

        self.result_label = QLabel("Results will appear here after conversion")
        self.result_label.setWordWrap(True)
        self.result_label.setStyleSheet("QLabel { padding: 10px; background-color: #f9f9f9; color: #333333; }")
        results_layout.addWidget(self.result_label)

        # Action buttons
        action_layout = QHBoxLayout()

        self.copy_button = QPushButton("Copy to Clipboard")
        self.copy_button.clicked.connect(self._on_copy)
        self.copy_button.setEnabled(False)
        action_layout.addWidget(self.copy_button)

        self.goto_button = QPushButton("Go to Location on Map")
        self.goto_button.clicked.connect(self._on_goto)
        self.goto_button.setEnabled(False)
        action_layout.addWidget(self.goto_button)

        results_layout.addLayout(action_layout)
        results_group.setLayout(results_layout)
        layout.addWidget(results_group)

        # Close button
        close_layout = QHBoxLayout()
        close_layout.addStretch()
        close_button = QPushButton("Close")
        close_button.clicked.connect(self.close)
        close_layout.addWidget(close_button)
        layout.addLayout(close_layout)

        self.setLayout(layout)

        if self._is_tm65_first_mode() and self.tm65 and self.tm65.isValid():
            self.tm65_grid_radio.setChecked(True)
        else:
            self.wgs84_radio.setChecked(True)

        # Initial state
        self._on_input_type_changed()

        # Store last conversion results
        self.last_lat = None
        self.last_lon = None
        self.last_result_text = None

    def _on_input_type_changed(self):
        """Handle input type radio button change."""
        is_wgs84 = self.wgs84_radio.isChecked()
        is_tm65_grid = self.tm65_grid_radio.isChecked()

        # Show/hide appropriate input fields
        self.lat_label.setVisible(is_wgs84)
        self.lat_input.setVisible(is_wgs84)
        self.lon_label.setVisible(is_wgs84)
        self.lon_input.setVisible(is_wgs84)

        self.easting_label.setVisible(not is_wgs84 and not is_tm65_grid)
        self.easting_input.setVisible(not is_wgs84 and not is_tm65_grid)
        self.northing_label.setVisible(not is_wgs84 and not is_tm65_grid)
        self.northing_input.setVisible(not is_wgs84 and not is_tm65_grid)

        self.tm65_grid_label.setVisible(is_tm65_grid)
        self.tm65_grid_input.setVisible(is_tm65_grid)

    def _on_display_mode_changed(self, _index: int):
        """Persist workflow display mode preference."""
        mode = self.display_mode_combo.currentData()
        ConfigStore.set_coordinate_display_mode(mode)
        self.coordinate_display_mode = ConfigStore.get_coordinate_display_mode()

    def _is_tm65_first_mode(self) -> bool:
        return (
            self.coordinate_display_mode ==
            SETTINGS_KEYS.COORDINATE_DISPLAY_MODE_TM65_FIRST
        )

    def _format_result_text(self, lat: float, lon: float, itm_easting: float, itm_northing: float,
                            tm65_ref: str = None, source_label: str = "WGS84") -> str:
        """Build formatted result text honoring display mode preference."""
        wgs84_text = format_wgs84_degrees(lat, lon, precision=6)
        lat_text, lon_text = wgs84_text.split(", ")
        itm_e = f"{round(itm_easting):,}"
        itm_n = f"{round(itm_northing):,}"

        tm65_block = ""
        if tm65_ref:
            tm65_block = (
                f"<b>Irish Grid (TM65) Reference:</b><br>"
                f"{tm65_ref}<br><br>"
            )

        wgs84_block = (
            f"<b>WGS84:</b><br>"
            f"Latitude: {lat_text}<br>"
            f"Longitude: {lon_text}<br><br>"
        )
        itm_block = (
            f"<b>Irish Grid (ITM):</b><br>"
            f"Easting: {itm_e}<br>"
            f"Northing: {itm_n}"
        )
        source_block = f"<b>Source:</b> {source_label}<br><br>"

        if self._is_tm65_first_mode():
            return source_block + tm65_block + wgs84_block + itm_block

        result = source_block + wgs84_block + itm_block
        if tm65_ref:
            result += (
                f"<br><br><b>Irish Grid (TM65) Reference:</b><br>"
                f"{tm65_ref}"
            )
        return result

    def _on_convert(self):
        """Handle convert button click."""
        try:
            if self.wgs84_radio.isChecked():
                # Convert WGS84 -> Irish Grid
                lat = float(self.lat_input.text().strip())
                lon = float(self.lon_input.text().strip())

                # Validate ranges
                if not (-90 <= lat <= 90):
                    self.result_label.setText("❌ Error: Latitude must be between -90 and 90")
                    return
                if not (-180 <= lon <= 180):
                    self.result_label.setText("❌ Error: Longitude must be between -180 and 180")
                    return

                # Transform
                transform = QgsCoordinateTransform(
                    self.wgs84,
                    self.itm,
                    QgsProject.instance()
                )
                point = QgsPointXY(lon, lat)
                itm_point = transform.transform(point)

                # BUG-056 FIX: Validate transform result is not NaN/Inf
                if math.isnan(itm_point.x()) or math.isnan(itm_point.y()):
                    logger.error("BUG-056: Transform produced NaN result for lat=%s, lon=%s", lat, lon)
                    self.result_label.setText(
                        "❌ Error: Transformation produced invalid coordinates.\n"
                        "The input coordinates may be outside the supported region."
                    )
                    return
                if math.isinf(itm_point.x()) or math.isinf(itm_point.y()):
                    logger.error("BUG-056: Transform produced Inf result for lat=%s, lon=%s", lat, lon)
                    self.result_label.setText(
                        "❌ Error: Transformation produced infinite coordinates.\n"
                        "Please check your input values."
                    )
                    return

                tm65_ref = None
                if self.tm65 and self.tm65.isValid():
                    try:
                        transform_tm65 = QgsCoordinateTransform(
                            self.wgs84,
                            self.tm65,
                            QgsProject.instance()
                        )
                        tm65_point = transform_tm65.transform(point)
                        tm65_ref = format_irish_grid_reference(tm65_point.x(), tm65_point.y())
                    except Exception:
                        tm65_ref = None

                # Store results
                self.last_lat = lat
                self.last_lon = lon

                result_text = self._format_result_text(
                    lat,
                    lon,
                    itm_point.x(),
                    itm_point.y(),
                    tm65_ref=tm65_ref,
                    source_label="WGS84 (Lat/Lon)"
                )

            elif self.irish_grid_radio.isChecked():
                # Convert Irish Grid -> WGS84
                easting = float(self.easting_input.text().strip().replace(',', ''))
                northing = float(self.northing_input.text().strip().replace(',', ''))

                # BUG-069 FIX: Use consistent Irish Grid (ITM) validation ranges
                # matching marker_manager.py for consistency across the codebase.
                # Full ITM grid range: E 0-1,000,000, N 0-1,500,000
                # Typical Ireland range: E ~400,000-800,000, N ~500,000-1,000,000
                if not (0 <= easting <= 1000000):
                    self.result_label.setText(
                        "❌ Error: Easting must be between 0 and 1,000,000 for Irish Grid (ITM)\n"
                        "(Typical Ireland range: 400,000-800,000)"
                    )
                    return
                if not (0 <= northing <= 1500000):
                    self.result_label.setText(
                        "❌ Error: Northing must be between 0 and 1,500,000 for Irish Grid (ITM)\n"
                        "(Typical Ireland range: 500,000-1,000,000)"
                    )
                    return

                # Transform
                transform = QgsCoordinateTransform(
                    self.itm,
                    self.wgs84,
                    QgsProject.instance()
                )
                point = QgsPointXY(easting, northing)
                wgs84_point = transform.transform(point)

                # BUG-056 FIX: Validate transform result is not NaN/Inf
                if math.isnan(wgs84_point.x()) or math.isnan(wgs84_point.y()):
                    logger.error("BUG-056: Transform produced NaN result for E=%s, N=%s", easting, northing)
                    self.result_label.setText(
                        "❌ Error: Transformation produced invalid coordinates.\n"
                        "The Irish Grid coordinates may be outside the valid region."
                    )
                    return
                if math.isinf(wgs84_point.x()) or math.isinf(wgs84_point.y()):
                    logger.error("BUG-056: Transform produced Inf result for E=%s, N=%s", easting, northing)
                    self.result_label.setText(
                        "❌ Error: Transformation produced infinite coordinates.\n"
                        "Please check your input values."
                    )
                    return

                tm65_ref = None
                if self.tm65 and self.tm65.isValid():
                    try:
                        transform_tm65 = QgsCoordinateTransform(
                            self.itm,
                            self.tm65,
                            QgsProject.instance()
                        )
                        tm65_point = transform_tm65.transform(point)
                        tm65_ref = format_irish_grid_reference(tm65_point.x(), tm65_point.y())
                    except Exception:
                        tm65_ref = None

                # Store results
                self.last_lat = wgs84_point.y()
                self.last_lon = wgs84_point.x()

                result_text = self._format_result_text(
                    wgs84_point.y(),
                    wgs84_point.x(),
                    easting,
                    northing,
                    tm65_ref=tm65_ref,
                    source_label="Irish Grid (ITM)"
                )

            else:
                # Convert Irish Grid Reference (TM65) -> WGS84 and ITM
                if not self.tm65 or not self.tm65.isValid():
                    self.result_label.setText(
                        "❌ Error: TM65 coordinate system is unavailable in this QGIS build."
                    )
                    return

                tm65_ref_input = self.tm65_grid_input.text().strip()
                tm65_easting, tm65_northing = parse_irish_grid_reference(tm65_ref_input)
                tm65_point = QgsPointXY(tm65_easting, tm65_northing)

                transform_to_wgs84 = QgsCoordinateTransform(
                    self.tm65,
                    self.wgs84,
                    QgsProject.instance()
                )
                wgs84_point = transform_to_wgs84.transform(tm65_point)

                transform_to_itm = QgsCoordinateTransform(
                    self.tm65,
                    self.itm,
                    QgsProject.instance()
                )
                itm_point = transform_to_itm.transform(tm65_point)

                if (math.isnan(wgs84_point.x()) or math.isnan(wgs84_point.y()) or
                        math.isinf(wgs84_point.x()) or math.isinf(wgs84_point.y()) or
                        math.isnan(itm_point.x()) or math.isnan(itm_point.y()) or
                        math.isinf(itm_point.x()) or math.isinf(itm_point.y())):
                    self.result_label.setText(
                        "❌ Error: Transformation produced invalid coordinates."
                    )
                    return

                self.last_lat = wgs84_point.y()
                self.last_lon = wgs84_point.x()
                tm65_ref = format_irish_grid_reference(tm65_easting, tm65_northing)
                result_text = self._format_result_text(
                    wgs84_point.y(),
                    wgs84_point.x(),
                    itm_point.x(),
                    itm_point.y(),
                    tm65_ref=tm65_ref,
                    source_label="Irish Grid Reference (TM65)"
                )

            self.last_result_text = result_text
            self.result_label.setText(result_text)

            # Enable action buttons
            self.copy_button.setEnabled(True)
            self.goto_button.setEnabled(True)

        except ValueError as e:
            # BUG-056 FIX: Specific error for input format issues
            logger.warning("BUG-056: Coordinate input format error: %s", e)
            self.result_label.setText(
                "❌ Error: Invalid number format. Please enter valid numeric coordinates.\n"
                "Example: Latitude 53.34, Longitude -6.26"
            )
        except QgsCsException as e:
            # BUG-056 FIX: Specific error for CRS/transformation issues
            logger.error("BUG-056: Coordinate transformation CRS error: %s", e)
            self.result_label.setText(
                "❌ Error: Coordinate system transformation failed.\n"
                "The coordinate reference systems may be incompatible or invalid."
            )
        except RuntimeError as e:
            # BUG-056 FIX: Specific error for QGIS runtime transform errors
            logger.error("BUG-056: Coordinate transformation runtime error: %s", e)
            self.result_label.setText(
                f"❌ Error: Transformation calculation failed.\n"
                f"Details: {str(e)}"
            )
        except Exception as e:
            # BUG-056 FIX: Log unexpected errors for diagnostics
            logger.exception("BUG-056: Unexpected coordinate conversion error: %s", e)
            self.result_label.setText(f"❌ Error: An unexpected error occurred: {str(e)}")

    def _on_copy(self):
        """Copy results to clipboard."""
        if self.last_result_text:
            # Create plain text version for clipboard
            clipboard_text = self.last_result_text.replace('<b>', '').replace('</b>', '').replace('<br>', '\n')
            QApplication.clipboard().setText(clipboard_text)

            # Briefly show feedback
            original_text = self.copy_button.text()
            self.copy_button.setText("✓ Copied!")
            self.copy_button.setEnabled(False)

            # Reset after 1 second
            # BUG-057 fix: Store timer reference for cleanup
            from qgis.PyQt.QtCore import QTimer
            self.copy_timer = QTimer(self)
            self.copy_timer.setSingleShot(True)
            self.copy_timer.timeout.connect(lambda: self._reset_copy_button(original_text))
            self.copy_timer.start(1000)

    def _reset_copy_button(self, original_text):
        """Reset copy button after brief delay."""
        self.copy_button.setText(original_text)
        self.copy_button.setEnabled(True)

    def _on_goto(self):
        """Emit signal to go to location on map."""
        if self.last_lat is not None and self.last_lon is not None:
            self.go_to_location.emit(self.last_lat, self.last_lon)

            # Brief feedback
            original_text = self.goto_button.text()
            self.goto_button.setText("✓ Map Updated!")
            self.goto_button.setEnabled(False)

            # BUG-057 fix: Store timer reference for cleanup
            from qgis.PyQt.QtCore import QTimer
            self.goto_timer = QTimer(self)
            self.goto_timer.setSingleShot(True)
            self.goto_timer.timeout.connect(lambda: self._reset_goto_button(original_text))
            self.goto_timer.start(1000)

    def _reset_goto_button(self, original_text):
        """Reset goto button after brief delay."""
        self.goto_button.setText(original_text)
        self.goto_button.setEnabled(True)

    def closeEvent(self, event):
        """Handle dialog close - cancel any pending timers."""
        # BUG-057 fix: Stop timers to prevent callbacks on deleted dialog
        if hasattr(self, 'copy_timer') and self.copy_timer:
            self.copy_timer.stop()
            self.copy_timer = None
        if hasattr(self, 'goto_timer') and self.goto_timer:
            self.goto_timer.stop()
            self.goto_timer = None
        super().closeEvent(event)
