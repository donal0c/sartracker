# -*- coding: utf-8 -*-
"""
Base Drawing Tool

Abstract base class for all SAR drawing tools.
Provides common functionality for coordinate transformation,
preview management, and tool lifecycle.

Qt5/Qt6 Compatible: Uses qgis.PyQt and qt_compat for all Qt imports.
"""

from qgis.core import (
    QgsPointXY, QgsCoordinateReferenceSystem, QgsCoordinateTransform,
    QgsProject, QgsDistanceArea
)
from qgis.gui import QgsMapTool, QgsRubberBand
from qgis.PyQt.QtCore import pyqtSignal
from qgis.PyQt.QtGui import QCursor

# Import Qt5/Qt6 compatible constants
from ..utils.qt_compat import CrossCursor, Key_Escape


class BaseDrawingTool(QgsMapTool):
    """
    Base class for SAR drawing tools.

    Provides:
    - Coordinate system handling (WGS84 ↔ Irish Grid ↔ Canvas CRS)
    - Distance/bearing calculations
    - Rubber band preview management
    - Common signal patterns
    - ESC key cancellation

    Subclasses must implement:
    - canvasPressEvent() - Handle mouse clicks
    - canvasMoveEvent() - Handle mouse movement (optional)
    - _create_feature() - Create the actual feature (optional)

    Signals:
        drawing_complete: Emitted when drawing is finished (feature_data: dict)
        drawing_cancelled: Emitted when drawing is cancelled
    """

    # Signals
    drawing_complete = pyqtSignal(object)  # Emits feature data dict
    drawing_cancelled = pyqtSignal()

    def __init__(self, canvas):
        """
        Initialize base drawing tool.

        Args:
            canvas: QGIS map canvas
        """
        super().__init__(canvas)
        self.canvas = canvas
        self.setCursor(QCursor(CrossCursor))

        # Coordinate systems
        self.wgs84 = QgsCoordinateReferenceSystem("EPSG:4326")
        self.itm = QgsCoordinateReferenceSystem("EPSG:29903")  # Irish Grid

        # Distance calculator (geodesic)
        self.distance_calc = QgsDistanceArea()
        self.distance_calc.setSourceCrs(
            self.wgs84,
            QgsProject.instance().transformContext()
        )
        self.distance_calc.setEllipsoid('WGS84')

        # Rubber bands for preview (subclasses can add more)
        self.rubber_bands = []

        # State
        self.is_active = False

    def transform_to_wgs84(self, point):
        """
        Transform point from canvas CRS to WGS84.

        Args:
            point: QgsPointXY in canvas CRS

        Returns:
            QgsPointXY in WGS84, or original point if transformation fails
        """
        try:
            canvas_crs = self.canvas.mapSettings().destinationCrs()
            if canvas_crs.authid() == "EPSG:4326":
                return point

            transform = QgsCoordinateTransform(
                canvas_crs,
                self.wgs84,
                QgsProject.instance()
            )
            return transform.transform(point)
        except Exception as e:
            print(f"Error transforming to WGS84: {e}")
            return point  # Return original point as fallback

    def transform_to_itm(self, point):
        """
        Transform point from canvas CRS to Irish Grid (ITM).

        Args:
            point: QgsPointXY in canvas CRS

        Returns:
            QgsPointXY in ITM, or original point if transformation fails
        """
        try:
            canvas_crs = self.canvas.mapSettings().destinationCrs()
            if canvas_crs.authid() == "EPSG:29903":
                return point

            transform = QgsCoordinateTransform(
                canvas_crs,
                self.itm,
                QgsProject.instance()
            )
            return transform.transform(point)
        except Exception as e:
            print(f"Error transforming to ITM: {e}")
            return point  # Return original point as fallback

    def transform_from_wgs84(self, point):
        """
        Transform point from WGS84 to canvas CRS.

        Args:
            point: QgsPointXY in WGS84

        Returns:
            QgsPointXY in canvas CRS, or original point if transformation fails
        """
        try:
            canvas_crs = self.canvas.mapSettings().destinationCrs()
            if canvas_crs.authid() == "EPSG:4326":
                return point

            transform = QgsCoordinateTransform(
                self.wgs84,
                canvas_crs,
                QgsProject.instance()
            )
            return transform.transform(point)
        except Exception as e:
            print(f"Error transforming from WGS84: {e}")
            return point  # Return original point as fallback

    def calculate_distance(self, point1_wgs84, point2_wgs84):
        """
        Calculate geodesic distance between two points.

        Args:
            point1_wgs84: First point in WGS84
            point2_wgs84: Second point in WGS84

        Returns:
            Distance in meters
        """
        return self.distance_calc.measureLine(point1_wgs84, point2_wgs84)

    def calculate_bearing(self, point1_wgs84, point2_wgs84):
        """
        Calculate bearing from point1 to point2.

        Args:
            point1_wgs84: Start point in WGS84
            point2_wgs84: End point in WGS84

        Returns:
            Bearing in degrees (0-360, where 0 = North), or 0.0 if points are identical
        """
        import math

        # Handle identical points
        if (abs(point1_wgs84.x() - point2_wgs84.x()) < 1e-9 and
            abs(point1_wgs84.y() - point2_wgs84.y()) < 1e-9):
            return 0.0

        lat1 = math.radians(point1_wgs84.y())
        lat2 = math.radians(point2_wgs84.y())
        lon1 = math.radians(point1_wgs84.x())
        lon2 = math.radians(point2_wgs84.x())

        dlon = lon2 - lon1

        x = math.sin(dlon) * math.cos(lat2)
        y = (math.cos(lat1) * math.sin(lat2) -
             math.sin(lat1) * math.cos(lat2) * math.cos(dlon))

        bearing = math.atan2(x, y)
        bearing = math.degrees(bearing)

        # Normalize to 0-360
        return (bearing + 360) % 360

    def clear_rubber_bands(self):
        """Clear all rubber band previews."""
        if not self.canvas or not self.canvas.scene():
            # Canvas not available, just clear the list
            self.rubber_bands = []
            return

        for band in self.rubber_bands:
            try:
                if self.canvas.scene():
                    self.canvas.scene().removeItem(band)
                # Explicitly delete the rubber band to avoid memory leak
                band.reset()
            except:
                pass  # Band may already be deleted

        self.rubber_bands = []

    def activate(self):
        """Called when tool is activated."""
        super().activate()
        self.is_active = True
        self.canvas.setCursor(QCursor(CrossCursor))
        self.clear_rubber_bands()

    def deactivate(self):
        """Called when tool is deactivated."""
        super().deactivate()
        self.is_active = False
        self.clear_rubber_bands()

    def keyPressEvent(self, event):
        """
        Handle keyboard input.

        ESC key cancels drawing.
        """
        if event.key() == Key_Escape:
            self.cancel()
            event.ignore()

    def cancel(self):
        """Cancel current drawing operation."""
        self.clear_rubber_bands()
        self.drawing_cancelled.emit()

    def isZoomTool(self):
        """Return False - drawing tools are not zoom tools."""
        return False

    def isEditTool(self):
        """Return True - drawing tools are editing tools."""
        return True

    def canvasPressEvent(self, event):
        """
        Handle mouse click - must be implemented by subclass.

        Args:
            event: QgsMapMouseEvent
        """
        raise NotImplementedError("Subclasses must implement canvasPressEvent()")

    def canvasMoveEvent(self, event):
        """
        Handle mouse move - can be implemented by subclass for preview.

        Args:
            event: QgsMapMouseEvent
        """
        pass  # Optional for subclasses
