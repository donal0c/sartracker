# -*- coding: utf-8 -*-
"""
Measure Tool

Custom QGIS map tool for measuring distance and bearing between two points.
"""

import logging

from qgis.core import (
    QgsPointXY, QgsCoordinateReferenceSystem, QgsCoordinateTransform,
    QgsProject, QgsGeometry, QgsDistanceArea, QgsUnitTypes, QgsWkbTypes
)
from qgis.gui import QgsMapTool, QgsRubberBand
from qgis.PyQt.QtCore import pyqtSignal
from qgis.PyQt.QtGui import QCursor, QColor
import math

# Import Qt5/Qt6 compatible constants
from ..utils.qt_compat import CrossCursor
# Import shared geodesic utilities
from ..utils.drawing_math import geodesic_bearing
# Import notification utilities
from ..utils.notify import warning as notify_warning

logger = logging.getLogger(__name__)


class MeasureTool(QgsMapTool):
    """
    Map tool for measuring distance and bearing between two points.

    Signals:
        measurement_complete: Emitted when measurement is done
                              (distance_m, distance_km, bearing_degrees, point1, point2)
    """

    measurement_complete = pyqtSignal(float, float, float, QgsPointXY, QgsPointXY)

    def __init__(self, canvas):
        """
        Initialize measure tool.

        Args:
            canvas: QGIS map canvas
        """
        super().__init__(canvas)
        self.canvas = canvas
        self.setCursor(QCursor(CrossCursor))

        # Measurement state
        self.first_point = None
        self.second_point = None

        # Rubber band for visual feedback
        self.rubber_band = QgsRubberBand(self.canvas, QgsWkbTypes.LineGeometry)
        self.rubber_band.setColor(QColor(255, 0, 0, 180))  # Red, semi-transparent
        self.rubber_band.setWidth(2)

        # Distance calculator
        self.distance_calc = QgsDistanceArea()
        self.distance_calc.setSourceCrs(
            QgsCoordinateReferenceSystem("EPSG:4326"),
            QgsProject.instance().transformContext()
        )
        self.distance_calc.setEllipsoid('WGS84')

    def canvasPressEvent(self, event):
        """Handle mouse click on canvas."""
        # Get click position in map coordinates
        point = self.toMapCoordinates(event.pos())

        if self.first_point is None:
            # First click - store starting point
            self.first_point = point
            self.rubber_band.reset(QgsWkbTypes.LineGeometry)
            self.rubber_band.addPoint(point)
        else:
            # Second click - calculate and emit results
            self.second_point = point
            self.rubber_band.addPoint(point)

            # Calculate distance and bearing
            distance_m, distance_km, bearing = self._calculate_measurement()

            # Emit signal
            self.measurement_complete.emit(
                distance_m,
                distance_km,
                bearing,
                self.first_point,
                self.second_point
            )

            # Reset for next measurement
            self.first_point = None
            self.second_point = None
            self.rubber_band.reset(QgsWkbTypes.LineGeometry)

    def canvasMoveEvent(self, event):
        """Handle mouse move - show preview line."""
        if self.first_point is not None:
            # Show preview line from first point to cursor
            point = self.toMapCoordinates(event.pos())
            self.rubber_band.reset(QgsWkbTypes.LineGeometry)
            self.rubber_band.addPoint(self.first_point)
            self.rubber_band.addPoint(point)

    def canvasReleaseEvent(self, event):
        """Handle mouse release (not used)."""
        pass

    def _calculate_measurement(self):
        """
        Calculate distance and bearing between two points.

        Returns:
            tuple: (distance_meters, distance_km, bearing_degrees)
        """
        # Get canvas CRS
        canvas_crs = self.canvas.mapSettings().destinationCrs()

        # Transform points to WGS84 for accurate distance calculation
        # MEASURE-TRANSFORM fix: Add error handling for coordinate transforms
        try:
            wgs84 = QgsCoordinateReferenceSystem("EPSG:4326")
            transform = QgsCoordinateTransform(
                canvas_crs,
                wgs84,
                QgsProject.instance()
            )

            point1_wgs84 = transform.transform(self.first_point)
            point2_wgs84 = transform.transform(self.second_point)
        except Exception as e:
            error_msg = f"Failed to transform coordinates for measurement: {e}"
            logger.error(error_msg)
            notify_warning("Coordinate transform failed", error_msg)
            raise RuntimeError(error_msg)

        # Calculate distance using ellipsoidal calculation
        distance_m = self.distance_calc.measureLine(point1_wgs84, point2_wgs84)
        distance_km = distance_m / 1000.0

        # Calculate bearing using geodesic formula (BUG-035 fix)
        # Uses shared utility function to ensure consistency across codebase
        # Provides <0.1° accuracy for SAR operational distances
        bearing = geodesic_bearing(
            point1_wgs84.x(), point1_wgs84.y(),
            point2_wgs84.x(), point2_wgs84.y()
        )

        return distance_m, distance_km, bearing

    def activate(self):
        """Called when tool is activated."""
        super().activate()
        self.canvas.setCursor(QCursor(CrossCursor))
        self.first_point = None
        self.second_point = None
        self.rubber_band.reset(QgsWkbTypes.LineGeometry)

    def deactivate(self):
        """Called when tool is deactivated."""
        super().deactivate()
        self.rubber_band.reset(QgsWkbTypes.LineGeometry)
        self.first_point = None
        self.second_point = None

    def isZoomTool(self):
        """Return False - this is not a zoom tool."""
        return False

    def isTransient(self):
        """Return False - tool stays active until manually deactivated."""
        return False

    def isEditTool(self):
        """Return False - this is a measurement tool."""
        return False
