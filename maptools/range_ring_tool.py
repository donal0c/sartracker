# -*- coding: utf-8 -*-
"""
Range Ring Drawing Tool

Interactive tool for creating circular range rings around a point.
Supports manual radius entry or LPB (Lost Person Behavior) statistics.

Qt5/Qt6 Compatible: Uses qgis.PyQt and qt_compat for all Qt imports.
"""

from qgis.core import QgsPointXY, QgsGeometry, QgsWkbTypes
from qgis.gui import QgsRubberBand
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QColor
from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QRadioButton, QComboBox,
    QCheckBox, QGroupBox, QButtonGroup, QSpinBox
)

# Import Qt5/Qt6 compatible constants and functions
from ..utils.qt_compat import LeftButton, RightButton, Key_Escape, dialog_exec, push_message, DialogAccepted
from ..utils.lpb_statistics import LPBStatistics

from .base_drawing_tool import BaseDrawingTool


class RangeRingDialog(QDialog):
    """
    Dialog for configuring range rings.

    User can choose:
    - Manual: Custom radius and optional multiple rings
    - LPB: Subject category with percentile-based rings
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Create Range Rings")
        self.setModal(True)
        self.setMinimumWidth(400)

        # Result data
        self.ring_data = None

        self._setup_ui()

    def _setup_ui(self):
        """Create dialog UI."""
        layout = QVBoxLayout()

        # Mode selection
        mode_group = QGroupBox("Ring Type")
        mode_layout = QVBoxLayout()

        self.mode_group = QButtonGroup()
        self.manual_radio = QRadioButton("Manual Radius")
        self.lpb_radio = QRadioButton("LPB Statistics (Lost Person Behavior)")

        self.mode_group.addButton(self.manual_radio, 0)
        self.mode_group.addButton(self.lpb_radio, 1)
        self.manual_radio.setChecked(True)

        mode_layout.addWidget(self.manual_radio)
        mode_layout.addWidget(self.lpb_radio)
        mode_group.setLayout(mode_layout)
        layout.addWidget(mode_group)

        # Manual mode controls
        self.manual_group = QGroupBox("Manual Configuration")
        manual_layout = QVBoxLayout()

        radius_layout = QHBoxLayout()
        radius_layout.addWidget(QLabel("Radius (meters):"))
        self.radius_input = QLineEdit()
        self.radius_input.setText("1000")
        self.radius_input.setPlaceholderText("e.g., 1000")
        radius_layout.addWidget(self.radius_input)
        manual_layout.addLayout(radius_layout)

        # Multiple rings option
        self.multiple_check = QCheckBox("Create multiple concentric rings")
        manual_layout.addWidget(self.multiple_check)

        rings_layout = QHBoxLayout()
        rings_layout.addWidget(QLabel("Number of rings:"))
        self.num_rings_spin = QSpinBox()
        self.num_rings_spin.setMinimum(1)
        self.num_rings_spin.setMaximum(10)
        self.num_rings_spin.setValue(3)
        self.num_rings_spin.setEnabled(False)
        rings_layout.addWidget(self.num_rings_spin)
        rings_layout.addStretch()
        manual_layout.addLayout(rings_layout)

        self.manual_group.setLayout(manual_layout)
        layout.addWidget(self.manual_group)

        # LPB mode controls
        self.lpb_group = QGroupBox("LPB Configuration")
        lpb_layout = QVBoxLayout()

        category_layout = QHBoxLayout()
        category_layout.addWidget(QLabel("Subject Category:"))
        self.category_combo = QComboBox()
        self.category_combo.addItems(LPBStatistics.get_all_categories())
        category_layout.addWidget(self.category_combo)
        lpb_layout.addLayout(category_layout)

        lpb_layout.addWidget(QLabel("Will create rings at 25%, 50%, 75%, 95% probability"))

        self.lpb_group.setLayout(lpb_layout)
        self.lpb_group.setEnabled(False)
        layout.addWidget(self.lpb_group)

        # Buttons
        button_layout = QHBoxLayout()
        button_layout.addStretch()

        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(cancel_btn)

        create_btn = QPushButton("Create Rings")
        create_btn.clicked.connect(self._create_rings)
        create_btn.setDefault(True)
        button_layout.addWidget(create_btn)

        layout.addLayout(button_layout)

        self.setLayout(layout)

        # Connect signals
        self.manual_radio.toggled.connect(self._on_mode_changed)
        self.lpb_radio.toggled.connect(self._on_mode_changed)
        self.multiple_check.toggled.connect(self.num_rings_spin.setEnabled)

    def _on_mode_changed(self):
        """Handle mode radio button changes."""
        is_manual = self.manual_radio.isChecked()
        self.manual_group.setEnabled(is_manual)
        self.lpb_group.setEnabled(not is_manual)

    def _create_rings(self):
        """Validate input and prepare ring data."""
        if self.manual_radio.isChecked():
            # Manual mode
            try:
                radius = float(self.radius_input.text())
                if radius <= 0:
                    raise ValueError("Radius must be positive")
                if radius > 100000:  # 100km maximum for SAR operations
                    raise ValueError("Radius too large (maximum 100,000m = 100km)")
                if not (0 < radius < float('inf')):
                    raise ValueError("Invalid radius value")
            except ValueError as e:
                from qgis.PyQt.QtWidgets import QMessageBox
                QMessageBox.warning(self, "Invalid Input",
                                  f"Please enter a valid positive number for radius (max 100km).\n{e}")
                return

            if self.multiple_check.isChecked():
                num_rings = self.num_rings_spin.value()
                # Create evenly spaced rings
                self.ring_data = {
                    'mode': 'manual',
                    'rings': [
                        {
                            'radius_m': radius * (i + 1) / num_rings,
                            'label': f"{radius * (i + 1) / num_rings:.0f}m"
                        }
                        for i in range(num_rings)
                    ]
                }
            else:
                self.ring_data = {
                    'mode': 'manual',
                    'rings': [
                        {
                            'radius_m': radius,
                            'label': f"{radius:.0f}m"
                        }
                    ]
                }
        else:
            # LPB mode
            category_name = self.category_combo.currentText()
            category_key = LPBStatistics.get_category_from_display_name(category_name)

            if not category_key:
                from qgis.PyQt.QtWidgets import QMessageBox
                QMessageBox.warning(self, "Error", "Invalid category selected")
                return

            distances = LPBStatistics.get_distances(category_key, [25, 50, 75, 95])

            if not distances or len(distances) == 0:
                from qgis.PyQt.QtWidgets import QMessageBox
                QMessageBox.warning(self, "Error", "Failed to load LPB statistics for this category")
                return

            self.ring_data = {
                'mode': 'lpb',
                'category': category_key,
                'category_name': category_name,
                'rings': [
                    {
                        'radius_m': dist,
                        'percentile': perc,
                        'label': f"{perc}% ({dist}m)"
                    }
                    for perc, dist in sorted(distances.items())
                ]
            }

        self.accept()


class RangeRingTool(BaseDrawingTool):
    """
    Tool for creating range rings around a clicked point.

    Click to select center point, then configure rings in dialog.
    Supports both manual radii and LPB statistics.
    """

    def __init__(self, canvas, layers_controller):
        """
        Initialize range ring tool.

        Args:
            canvas: QGIS map canvas
            layers_controller: LayersController instance for saving rings
        """
        super().__init__(canvas)
        self.layers_controller = layers_controller

        # State
        self.center_point = None  # Canvas CRS
        self.preview_rubber_band = None

    def activate(self):
        """Called when tool is activated."""
        super().activate()
        self.center_point = None

    def deactivate(self):
        """Called when tool is deactivated."""
        super().deactivate()
        self.center_point = None

    def canvasPressEvent(self, event):
        """
        Handle mouse click to set center point.

        Args:
            event: QgsMapMouseEvent
        """
        if event.button() == LeftButton:
            # Get click position
            self.center_point = self.toMapCoordinates(event.pos())

            # Show configuration dialog
            self._show_dialog()

    def canvasMoveEvent(self, event):
        """
        Show preview circle while moving mouse.

        Args:
            event: QgsMapMouseEvent
        """
        if self.center_point:
            # Could show preview of a default radius ring
            pass

    def _show_dialog(self):
        """Show range ring configuration dialog."""
        # Use None as parent since canvas is not a QWidget
        dialog = RangeRingDialog(None)

        if dialog_exec(dialog) == DialogAccepted and dialog.ring_data:
            self._create_rings(dialog.ring_data)
        else:
            # User cancelled
            self.center_point = None
            self.drawing_cancelled.emit()

    def _create_rings(self, ring_data):
        """
        Create range rings based on configuration.

        Args:
            ring_data: Dict with mode and rings configuration
        """
        try:
            center_wgs84 = self.transform_to_wgs84(self.center_point)

            is_lpb = ring_data['mode'] == 'lpb'
            feature_ids = []

            # Create each ring
            for i, ring in enumerate(ring_data['rings']):
                radius_m = ring['radius_m']
                label = ring['label']

                # Generate name
                if is_lpb:
                    name = f"{ring_data['category_name']} - {ring['percentile']}%"
                    color = self._get_lpb_color(ring['percentile'])
                    lpb_category = ring_data['category']
                    percentile = ring['percentile']
                else:
                    name = f"Range Ring {label}"
                    color = self._get_ring_color(i, len(ring_data['rings']))
                    lpb_category = ""
                    percentile = 0

                # Add to layer
                feature_id = self.layers_controller.add_range_ring(
                    name=name,
                    center_wgs84=center_wgs84,
                    radius_m=radius_m,
                    label=label,
                    color=color,
                    lpb_category=lpb_category,
                    percentile=percentile
                )

                feature_ids.append(feature_id)

            # Emit completion signal
            self.drawing_complete.emit({
                'type': 'range_rings',
                'feature_ids': feature_ids,
                'count': len(ring_data['rings']),
                'mode': ring_data['mode'],
                'center_lat': center_wgs84.y(),
                'center_lon': center_wgs84.x()
            })

        except Exception as e:
            print(f"Error creating range rings: {e}")
            import traceback
            traceback.print_exc()
            # Show error to user
            try:
                from qgis.utils import iface
                if iface:
                    push_message(
                        iface.messageBar(),
                        "Error",
                        f"Failed to create range rings: {str(e)}",
                        level=2,  # Warning
                        duration=5
                    )
            except:
                pass  # iface not available

        finally:
            # Reset for next ring set
            self.center_point = None
            self.clear_rubber_bands()

    def _get_lpb_color(self, percentile):
        """
        Get color for LPB ring based on percentile.

        Args:
            percentile: Percentile value (25, 50, 75, 95)

        Returns:
            Hex color string
        """
        colors = {
            25: "#00FF00",  # Green - highest probability
            50: "#FFFF00",  # Yellow
            75: "#FFA500",  # Orange
            95: "#FF0000",  # Red - lowest probability
        }
        return colors.get(percentile, "#FFA500")

    def _get_ring_color(self, index, total):
        """
        Get color for manual ring based on index.

        Args:
            index: Ring index (0-based)
            total: Total number of rings

        Returns:
            Hex color string
        """
        # Gradient from light to dark orange
        if total == 1:
            return "#FFA500"

        # Calculate brightness (255 = lightest, 100 = darkest)
        brightness = 255 - int((index / (total - 1)) * 155)
        return f"#{brightness:02x}a500"

    def cancel(self):
        """Cancel current operation."""
        self.center_point = None
        self.clear_rubber_bands()
        self.drawing_cancelled.emit()
