# -*- coding: utf-8 -*-
"""
Search Area (Polygon) Drawing Tool

Interactive tool for drawing polygon search areas on the map.
Supports multi-click drawing with detailed area configuration dialog.

Qt5/Qt6 Compatible: Uses qgis.PyQt and qt_compat for all Qt imports.
"""

from qgis.core import QgsPointXY, QgsGeometry, QgsWkbTypes
from qgis.gui import QgsRubberBand
from qgis.PyQt.QtCore import Qt, QTimer
from qgis.PyQt.QtGui import QColor
from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QComboBox, QTextEdit,
    QGroupBox, QFormLayout, QDoubleSpinBox, QMessageBox
)

# Import Qt5/Qt6 compatible constants
from ..utils.qt_compat import LeftButton, RightButton, Key_Escape

from .base_drawing_tool import BaseDrawingTool


class SearchAreaDialog(QDialog):
    """
    Dialog for configuring search area properties.

    Collects all metadata needed for a search area:
    - Name (required)
    - Team assignment
    - Status (Planned/Active/Complete/Suspended)
    - Priority (High/Medium/Low)
    - POA (Probability of Area) percentage
    - Terrain type
    - Search method
    - Color
    - Notes
    """

    def __init__(self, area_sqkm, parent=None):
        """
        Initialize search area dialog.

        Args:
            area_sqkm: Calculated area in square kilometers (for display)
            parent: Parent widget (typically None for modal dialogs)
        """
        super().__init__(parent)
        self.setWindowTitle("Create Search Area")
        self.setModal(True)
        self.setMinimumWidth(450)

        # Store calculated area
        self.area_sqkm = area_sqkm

        # Result data (None until user accepts)
        self.area_data = None

        self._setup_ui()

    def _setup_ui(self):
        """Create dialog UI."""
        layout = QVBoxLayout()

        # Area info display
        info_group = QGroupBox("Area Information")
        info_layout = QVBoxLayout()

        area_label = QLabel(f"<b>Calculated Area:</b> {self.area_sqkm:.3f} km² ({self.area_sqkm * 1000000:.0f} m²)")
        info_layout.addWidget(area_label)

        info_group.setLayout(info_layout)
        layout.addWidget(info_group)

        # Main properties group
        props_group = QGroupBox("Search Area Properties")
        props_layout = QFormLayout()

        # Name (required)
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("e.g., Zone Alpha, Grid 12A")
        props_layout.addRow("Name*:", self.name_input)

        # Team
        self.team_input = QLineEdit()
        self.team_input.setPlaceholderText("e.g., Team 1, K9 Unit")
        self.team_input.setText("Unassigned")
        props_layout.addRow("Team:", self.team_input)

        # Status
        self.status_combo = QComboBox()
        self.status_combo.addItems(["Planned", "Active", "Complete", "Suspended"])
        props_layout.addRow("Status:", self.status_combo)

        # Priority
        self.priority_combo = QComboBox()
        self.priority_combo.addItems(["High", "Medium", "Low"])
        self.priority_combo.setCurrentText("Medium")
        props_layout.addRow("Priority:", self.priority_combo)

        # POA (Probability of Area)
        self.poa_spin = QDoubleSpinBox()
        self.poa_spin.setMinimum(0.0)
        self.poa_spin.setMaximum(100.0)
        self.poa_spin.setValue(50.0)
        self.poa_spin.setSuffix(" %")
        self.poa_spin.setDecimals(1)
        props_layout.addRow("POA:", self.poa_spin)

        # Terrain
        self.terrain_combo = QComboBox()
        self.terrain_combo.setEditable(True)
        self.terrain_combo.addItems([
            "",
            "Urban",
            "Suburban",
            "Rural",
            "Forest - Dense",
            "Forest - Light",
            "Mountain",
            "Coastal",
            "Water",
            "Agricultural",
            "Scrubland",
            "Mixed"
        ])
        props_layout.addRow("Terrain:", self.terrain_combo)

        # Search Method
        self.method_combo = QComboBox()
        self.method_combo.setEditable(True)
        self.method_combo.addItems([
            "",
            "Ground - Hasty",
            "Ground - Grid",
            "Ground - Line",
            "K9",
            "Aerial - Helicopter",
            "Aerial - Drone",
            "Water - Shore",
            "Water - Boat",
            "Mixed Methods"
        ])
        props_layout.addRow("Search Method:", self.method_combo)

        # Color picker (using combo with predefined colors)
        self.color_combo = QComboBox()
        self.colors = {
            "Blue": "#0064FF",
            "Red": "#FF0000",
            "Green": "#00FF00",
            "Yellow": "#FFFF00",
            "Orange": "#FFA500",
            "Purple": "#800080",
            "Pink": "#FF69B4",
            "Cyan": "#00FFFF"
        }
        for color_name in self.colors.keys():
            self.color_combo.addItem(color_name)
        props_layout.addRow("Color:", self.color_combo)

        props_group.setLayout(props_layout)
        layout.addWidget(props_group)

        # Notes group
        notes_group = QGroupBox("Notes")
        notes_layout = QVBoxLayout()

        self.notes_text = QTextEdit()
        self.notes_text.setPlaceholderText("Additional notes, observations, or instructions...")
        self.notes_text.setMaximumHeight(80)
        notes_layout.addWidget(self.notes_text)

        notes_group.setLayout(notes_layout)
        layout.addWidget(notes_group)

        # Required field note
        req_label = QLabel("<i>* Required fields</i>")
        layout.addWidget(req_label)

        # Buttons
        button_layout = QHBoxLayout()
        button_layout.addStretch()

        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(cancel_btn)

        create_btn = QPushButton("Create Search Area")
        create_btn.clicked.connect(self._create_area)
        create_btn.setDefault(True)
        button_layout.addWidget(create_btn)

        layout.addLayout(button_layout)

        self.setLayout(layout)

    def _create_area(self):
        """Validate input and prepare area data."""
        # Validate required fields
        name = self.name_input.text().strip()
        if not name:
            QMessageBox.warning(
                self,
                "Validation Error",
                "Name is required. Please provide a name for the search area."
            )
            self.name_input.setFocus()
            return

        # Get color hex value
        color_name = self.color_combo.currentText()
        color = self.colors.get(color_name, "#0064FF")

        # Prepare data dictionary
        self.area_data = {
            'name': name,
            'team': self.team_input.text().strip(),
            'status': self.status_combo.currentText(),
            'priority': self.priority_combo.currentText(),
            'POA': self.poa_spin.value(),
            'terrain': self.terrain_combo.currentText(),
            'search_method': self.method_combo.currentText(),
            'color': color,
            'notes': self.notes_text.toPlainText().strip()
        }

        # Accept dialog
        self.accept()


class PolygonTool(BaseDrawingTool):
    """
    Tool for drawing polygon search areas on the map.

    Click to add vertices, right-click to finish (minimum 3 vertices).
    ESC key cancels drawing.
    Shows live preview with rubber band.
    """

    def __init__(self, canvas, layers_controller):
        """
        Initialize polygon drawing tool.

        Args:
            canvas: QGIS map canvas
            layers_controller: LayersController instance for saving polygons
        """
        super().__init__(canvas)
        self.layers_controller = layers_controller

        # Polygon drawing state
        self.points = []  # Points in canvas CRS
        self.is_drawing = False

        # Rubber band for preview
        self.polygon_rubber_band = None

    def activate(self):
        """Called by QGIS when tool is activated."""
        super().activate()
        self.reset()

    def deactivate(self):
        """Called by QGIS when tool is deactivated."""
        super().deactivate()
        self.reset()

    def reset(self):
        """Reset ALL state to initial conditions."""
        self.points = []
        self.is_drawing = False
        self.clear_rubber_bands()
        self.polygon_rubber_band = None

    def canvasPressEvent(self, event):
        """
        Handle mouse clicks.

        Left-click: Add vertex
        Right-click: Finish polygon (if 3+ vertices)

        Args:
            event: QgsMapMouseEvent
        """
        print(f"[POLYGON] canvasPressEvent() called!")
        print(f"[POLYGON] Tool is_active: {self.is_active}")
        print(f"[POLYGON] Canvas current tool: {self.canvas.mapTool()}")

        if event.button() == LeftButton:
            # Add vertex
            point = self.toMapCoordinates(event.pos())
            self.points.append(point)
            self.is_drawing = True

            # Update preview
            self._update_rubber_band()

        elif event.button() == RightButton:
            # Finish polygon - defer dialog to avoid nested event loop
            # Validate minimum vertices first
            if len(self.points) < 3:
                print(f"[POLYGON] Not enough points, cancelling")
                self.cancel()
                return

            # Defer dialog display to next event loop iteration
            QTimer.singleShot(0, self._finish_polygon_deferred)

    def canvasMoveEvent(self, event):
        """
        Handle mouse movement - update preview.

        Args:
            event: QgsMapMouseEvent
        """
        if self.is_drawing and len(self.points) > 0:
            # Show preview polygon from vertices to cursor
            current_pos = self.toMapCoordinates(event.pos())
            self._update_rubber_band(preview_point=current_pos)

    def keyPressEvent(self, event):
        """
        Handle keyboard input.

        ESC cancels drawing.

        Args:
            event: QKeyEvent
        """
        if event.key() == Key_Escape:
            self.cancel()

    def _update_rubber_band(self, preview_point=None):
        """
        Update rubber band preview.

        Args:
            preview_point: Optional preview point (cursor position)
        """
        # Check canvas is valid
        if not self.canvas or not self.canvas.scene():
            return

        # Create rubber band if needed
        if not self.polygon_rubber_band:
            self.polygon_rubber_band = QgsRubberBand(
                self.canvas,
                QgsWkbTypes.PolygonGeometry  # POLYGON, not LINE!
            )
            self.polygon_rubber_band.setColor(QColor(0, 100, 255, 100))  # Semi-transparent blue
            self.polygon_rubber_band.setFillColor(QColor(0, 100, 255, 40))  # Light fill
            self.polygon_rubber_band.setWidth(2)
            self.rubber_bands.append(self.polygon_rubber_band)

        # Build preview points list
        preview_points = list(self.points)
        if preview_point:
            preview_points.append(preview_point)

        # Reset and rebuild rubber band
        self.polygon_rubber_band.reset(QgsWkbTypes.PolygonGeometry)
        for point in preview_points:
            self.polygon_rubber_band.addPoint(point)

        # Close polygon visually if 3+ points
        if len(preview_points) >= 3:
            self.polygon_rubber_band.addPoint(preview_points[0])  # Close the ring

        # Force update
        self.polygon_rubber_band.show()

    def _calculate_area(self, points_wgs84):
        """
        Calculate area of polygon in square kilometers.

        Args:
            points_wgs84: List of QgsPointXY in WGS84

        Returns:
            float: Area in square kilometers
        """
        if len(points_wgs84) < 3:
            return 0.0

        try:
            # Create polygon geometry
            polygon = QgsGeometry.fromPolygonXY([points_wgs84])

            # Calculate area using distance calculator (geodesic)
            area_sqm = self.distance_calc.measureArea(polygon)

            # Convert to km²
            return area_sqm / 1_000_000

        except Exception as e:
            print(f"Error calculating area: {e}")
            return 0.0

    def _finish_polygon_deferred(self):
        """
        Show dialog after event processing completes.

        This is called via QTimer.singleShot(0, ...) to defer dialog display
        until after the current event (right-click) has finished processing.
        This prevents nested event loop issues.
        """
        print(f"[POLYGON] _finish_polygon_deferred() called, points: {len(self.points)}")
        print(f"[POLYGON] Tool is_active: {self.is_active}")
        print(f"[POLYGON] Canvas current tool: {self.canvas.mapTool()}")

        # CRITICAL: Unset tool BEFORE showing modal dialog
        # This prevents Qt event system corruption
        print(f"[POLYGON] Unsetting tool before dialog...")
        if self.canvas:
            self.canvas.unsetMapTool(self)
        print(f"[POLYGON] Canvas tool after unset: {self.canvas.mapTool()}")

        try:
            # Transform to WGS84
            points_wgs84 = [self.transform_to_wgs84(p) for p in self.points]

            # Calculate area for dialog
            area_sqkm = self._calculate_area(points_wgs84)

            print(f"[POLYGON] Opening dialog...")
            # Now safe to show modal dialog - tool is no longer active
            dialog = SearchAreaDialog(area_sqkm, None)

            dialog_result = dialog.exec_()
            print(f"[POLYGON] Dialog closed, result: {dialog_result}")

            if dialog_result == QDialog.Accepted and dialog.area_data:
                # User accepted - create the feature
                print(f"[POLYGON] User accepted, creating search area...")
                self._create_search_area(points_wgs84, dialog.area_data)
                print(f"[POLYGON] Search area created, signal emitted")
            else:
                # User cancelled - emit cancelled signal
                print(f"[POLYGON] User cancelled, emitting cancelled signal")
                self._cleanup_and_cancel()

        except Exception as e:
            print(f"[POLYGON] ERROR in _finish_polygon_deferred: {e}")
            import traceback
            traceback.print_exc()
            self._cleanup_and_cancel()

    def _cleanup_and_cancel(self):
        """Clean up and emit cancellation."""
        self.points = []
        self.is_drawing = False
        self.clear_rubber_bands()
        self.polygon_rubber_band = None
        self.drawing_cancelled.emit()

    def _create_search_area(self, points_wgs84, area_data):
        """
        Save the search area to the layer.

        Args:
            points_wgs84: List of QgsPointXY in WGS84
            area_data: Dict with area properties from dialog
        """
        try:
            # Save to layer via controller
            feature_id = self.layers_controller.add_search_area(
                name=area_data['name'],
                polygon_wgs84=points_wgs84,
                team=area_data['team'],
                status=area_data['status'],
                priority=area_data['priority'],
                POA=area_data['POA'],
                terrain=area_data['terrain'],
                search_method=area_data['search_method'],
                color=area_data['color'],
                notes=area_data['notes']
            )

            # Emit success signal
            self.drawing_complete.emit({
                'type': 'search_area',
                'feature_id': feature_id,
                'name': area_data['name'],
                'team': area_data['team'],
                'status': area_data['status'],
                'priority': area_data['priority'],
                'vertices': len(points_wgs84)
            })

        except Exception as e:
            print(f"Error saving search area: {e}")
            import traceback
            traceback.print_exc()
            # Show error to user
            try:
                from qgis.utils import iface
                if iface:
                    iface.messageBar().pushMessage(
                        "Error",
                        f"Failed to create search area: {str(e)}",
                        level=2,  # Warning
                        duration=5
                    )
            except:
                pass  # iface not available

    def cancel(self):
        """Cancel the current drawing operation."""
        self.reset()
        self.drawing_cancelled.emit()
