# -*- coding: utf-8 -*-
"""
Base Drawing Tool

Abstract base class for all SAR drawing tools.
Provides common functionality for coordinate transformation,
preview management, and tool lifecycle.

Qt5/Qt6 Compatible: Uses qgis.PyQt and qt_compat for all Qt imports.
"""

import logging
import math

from qgis.core import (
    QgsPointXY, QgsCoordinateReferenceSystem, QgsCoordinateTransform,
    QgsProject, QgsDistanceArea
)
from qgis.gui import QgsMapTool, QgsRubberBand
from qgis.PyQt.QtCore import pyqtSignal
from qgis.PyQt.QtGui import QCursor

# Import Qt5/Qt6 compatible constants
from ..utils.qt_compat import CrossCursor, Key_Escape

logger = logging.getLogger(__name__)


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
        drawing_error: Emitted when drawing operation fails (exception: Exception)
    """

    # Signals
    drawing_complete = pyqtSignal(object)  # Emits feature data dict
    drawing_cancelled = pyqtSignal()
    drawing_error = pyqtSignal(Exception)  # Emits exception for error handler (Issue #3)

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
        # Use EPSG:2157 (Irish Transverse Mercator / ITM) - the modern Irish Grid
        # Note: EPSG:29903 is the older TM65 Irish Grid which has 1-3m accuracy issues
        self.itm = QgsCoordinateReferenceSystem("EPSG:2157")

        # BUG-016 FIX: Validate CRS at initialization
        if not self.wgs84.isValid():
            logger.error("WGS84 CRS (EPSG:4326) failed to initialize - coordinate transforms will fail")
        if not self.itm.isValid():
            logger.error("ITM CRS (EPSG:2157) failed to initialize - Irish Grid transforms will fail")

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

    def _validate_coordinate(self, x: float, y: float, context: str) -> None:
        """
        BUG-031 FIX: Validate coordinate values for NaN, Infinity, and valid ranges.

        Args:
            x: X coordinate (longitude for WGS84, easting for projected CRS)
            y: Y coordinate (latitude for WGS84, northing for projected CRS)
            context: Description of operation for error messages

        Raises:
            RuntimeError: If coordinates are invalid (NaN, Infinity, or out of range)

        LIFE-SAFETY CRITICAL: Invalid coordinates could lead rescue teams to wrong locations.
        """
        # Check for NaN
        if math.isnan(x) or math.isnan(y):
            error_msg = f"Invalid coordinate during {context}: NaN value detected (x={x}, y={y})"
            logger.error(error_msg)
            raise RuntimeError(error_msg)

        # Check for Infinity
        if math.isinf(x) or math.isinf(y):
            error_msg = f"Invalid coordinate during {context}: Infinite value detected (x={x}, y={y})"
            logger.error(error_msg)
            raise RuntimeError(error_msg)

    def _validate_wgs84_range(self, lon: float, lat: float, context: str) -> None:
        """
        BUG-031 FIX: Validate WGS84 coordinates are within valid ranges.

        Args:
            lon: Longitude (-180 to 180)
            lat: Latitude (-90 to 90)
            context: Description of operation for error messages

        Raises:
            RuntimeError: If coordinates are out of valid WGS84 range
        """
        if not (-180.0 <= lon <= 180.0):
            error_msg = f"Invalid longitude during {context}: {lon} is outside valid range [-180, 180]"
            logger.error(error_msg)
            raise RuntimeError(error_msg)

        if not (-90.0 <= lat <= 90.0):
            error_msg = f"Invalid latitude during {context}: {lat} is outside valid range [-90, 90]"
            logger.error(error_msg)
            raise RuntimeError(error_msg)

    def transform_to_wgs84(self, point):
        """
        Transform point from canvas CRS to WGS84.

        BUG-016 FIX: Added explicit CRS validity checks before transformation.
        BUG-031 FIX: Added NaN/Infinity checks before and after transformation.

        Args:
            point: QgsPointXY in canvas CRS

        Returns:
            QgsPointXY in WGS84

        Raises:
            RuntimeError: If coordinate transformation fails or CRS is invalid
        """
        try:
            # BUG-031 FIX: Validate input coordinates before transformation
            self._validate_coordinate(point.x(), point.y(), "transform_to_wgs84 input")

            canvas_crs = self.canvas.mapSettings().destinationCrs()

            # BUG-016 FIX: Validate canvas CRS
            if not canvas_crs or not canvas_crs.isValid():
                error_msg = "Canvas CRS is not available or invalid. Check project CRS settings."
                logger.error(error_msg)
                error = RuntimeError(error_msg)
                self.drawing_error.emit(error)
                raise error

            # BUG-016 FIX: Validate target CRS
            if not self.wgs84.isValid():
                error_msg = "WGS84 CRS (EPSG:4326) is not available. QGIS installation may be corrupted."
                logger.error(error_msg)
                error = RuntimeError(error_msg)
                self.drawing_error.emit(error)
                raise error

            if canvas_crs.authid() == "EPSG:4326":
                # BUG-031 FIX: Still validate WGS84 range even when no transform needed
                self._validate_wgs84_range(point.x(), point.y(), "transform_to_wgs84 passthrough")
                return point

            transform = QgsCoordinateTransform(
                canvas_crs,
                self.wgs84,
                QgsProject.instance()
            )

            # BUG-016 FIX: Validate transform is valid
            if not transform.isValid():
                error_msg = f"Coordinate transform from {canvas_crs.authid()} to WGS84 is not valid."
                logger.error(error_msg)
                error = RuntimeError(error_msg)
                self.drawing_error.emit(error)
                raise error

            result = transform.transform(point)

            # BUG-031 FIX: Validate output coordinates after transformation
            self._validate_coordinate(result.x(), result.y(), "transform_to_wgs84 output")
            self._validate_wgs84_range(result.x(), result.y(), "transform_to_wgs84 output")

            return result
        except RuntimeError:
            # Re-raise our own RuntimeErrors (from validation checks above)
            raise
        except Exception as e:
            # TRANSFORM-SILENT fix: Raise error instead of silently returning wrong coordinates
            error_msg = f"Failed to transform coordinates from {canvas_crs.authid() if canvas_crs else 'Unknown'} to WGS84: {e}"
            logger.error(error_msg)
            error = RuntimeError(error_msg)
            self.drawing_error.emit(error)
            raise error

    def transform_to_itm(self, point):
        """
        Transform point from canvas CRS to Irish Grid (ITM).

        BUG-016 FIX: Added explicit CRS validity checks before transformation.
        BUG-031 FIX: Added NaN/Infinity checks before and after transformation.

        Args:
            point: QgsPointXY in canvas CRS

        Returns:
            QgsPointXY in ITM

        Raises:
            RuntimeError: If coordinate transformation fails or CRS is invalid
        """
        try:
            # BUG-031 FIX: Validate input coordinates before transformation
            self._validate_coordinate(point.x(), point.y(), "transform_to_itm input")

            canvas_crs = self.canvas.mapSettings().destinationCrs()

            # BUG-016 FIX: Validate canvas CRS
            if not canvas_crs or not canvas_crs.isValid():
                error_msg = "Canvas CRS is not available or invalid. Check project CRS settings."
                logger.error(error_msg)
                error = RuntimeError(error_msg)
                self.drawing_error.emit(error)
                raise error

            # BUG-016 FIX: Validate target CRS
            if not self.itm.isValid():
                error_msg = "ITM CRS (EPSG:2157) is not available. QGIS installation may be corrupted."
                logger.error(error_msg)
                error = RuntimeError(error_msg)
                self.drawing_error.emit(error)
                raise error

            if canvas_crs.authid() == "EPSG:2157":
                # BUG-031 FIX: Still validate output even when no transform needed
                self._validate_coordinate(point.x(), point.y(), "transform_to_itm passthrough")
                return point

            transform = QgsCoordinateTransform(
                canvas_crs,
                self.itm,
                QgsProject.instance()
            )

            # BUG-016 FIX: Validate transform is valid
            if not transform.isValid():
                error_msg = f"Coordinate transform from {canvas_crs.authid()} to ITM is not valid."
                logger.error(error_msg)
                error = RuntimeError(error_msg)
                self.drawing_error.emit(error)
                raise error

            result = transform.transform(point)

            # BUG-031 FIX: Validate output coordinates after transformation
            self._validate_coordinate(result.x(), result.y(), "transform_to_itm output")

            return result
        except RuntimeError:
            # Re-raise our own RuntimeErrors (from validation checks above)
            raise
        except Exception as e:
            # TRANSFORM-SILENT fix: Raise error instead of silently returning wrong coordinates
            error_msg = f"Failed to transform coordinates from {canvas_crs.authid() if canvas_crs else 'Unknown'} to ITM: {e}"
            logger.error(error_msg)
            error = RuntimeError(error_msg)
            self.drawing_error.emit(error)
            raise error

    def transform_from_wgs84(self, point):
        """
        Transform point from WGS84 to canvas CRS.

        BUG-016 FIX: Added explicit CRS validity checks before transformation.
        BUG-031 FIX: Added NaN/Infinity checks before and after transformation.

        Args:
            point: QgsPointXY in WGS84

        Returns:
            QgsPointXY in canvas CRS

        Raises:
            RuntimeError: If coordinate transformation fails or CRS is invalid
        """
        try:
            # BUG-031 FIX: Validate input coordinates before transformation
            self._validate_coordinate(point.x(), point.y(), "transform_from_wgs84 input")
            self._validate_wgs84_range(point.x(), point.y(), "transform_from_wgs84 input")

            canvas_crs = self.canvas.mapSettings().destinationCrs()

            # BUG-016 FIX: Validate canvas CRS
            if not canvas_crs or not canvas_crs.isValid():
                error_msg = "Canvas CRS is not available or invalid. Check project CRS settings."
                logger.error(error_msg)
                error = RuntimeError(error_msg)
                self.drawing_error.emit(error)
                raise error

            # BUG-016 FIX: Validate source CRS
            if not self.wgs84.isValid():
                error_msg = "WGS84 CRS (EPSG:4326) is not available. QGIS installation may be corrupted."
                logger.error(error_msg)
                error = RuntimeError(error_msg)
                self.drawing_error.emit(error)
                raise error

            if canvas_crs.authid() == "EPSG:4326":
                return point

            transform = QgsCoordinateTransform(
                self.wgs84,
                canvas_crs,
                QgsProject.instance()
            )

            # BUG-016 FIX: Validate transform is valid
            if not transform.isValid():
                error_msg = f"Coordinate transform from WGS84 to {canvas_crs.authid()} is not valid."
                logger.error(error_msg)
                error = RuntimeError(error_msg)
                self.drawing_error.emit(error)
                raise error

            result = transform.transform(point)

            # BUG-031 FIX: Validate output coordinates after transformation
            self._validate_coordinate(result.x(), result.y(), "transform_from_wgs84 output")

            return result
        except RuntimeError:
            # Re-raise our own RuntimeErrors (from validation checks above)
            raise
        except Exception as e:
            # TRANSFORM-SILENT fix: Raise error instead of silently returning wrong coordinates
            error_msg = f"Failed to transform coordinates from WGS84 to {canvas_crs.authid() if canvas_crs else 'Unknown'}: {e}"
            logger.error(error_msg)
            error = RuntimeError(error_msg)
            self.drawing_error.emit(error)
            raise error

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
