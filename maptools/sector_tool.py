# -*- coding: utf-8 -*-
"""
Search Sector Tool

Custom QGIS map tool for creating search sectors (pie slice/wedge shapes).
Useful for SAR operations to define directional search areas.

BUG-054 Fix: Now inherits from BaseDrawingTool for consistency with other drawing tools.
"""

from qgis.core import (
    QgsPointXY, QgsCoordinateReferenceSystem, QgsCoordinateTransform,
    QgsProject, QgsGeometry, QgsFeature, QgsVectorLayer, QgsField,
    QgsWkbTypes
)
from qgis.gui import QgsRubberBand, QgsVertexMarker
from qgis.PyQt.QtCore import pyqtSignal
from qgis.PyQt.QtGui import QCursor, QColor
import math

# Import base class and utilities
from .base_drawing_tool import BaseDrawingTool
# Import Qt5/Qt6 compatible constants
from ..utils.qt_compat import CrossCursor, LeftButton, Key_Escape
# Import shared geometry utilities
from ..utils.drawing_math import calculate_sector_arc_length


class SearchSectorTool(BaseDrawingTool):
    """
    Map tool for creating search sectors (wedge/pie slice shapes).

    Three-click operation:
    1. First click: Set center point
    2. Second click: Set radius and start angle
    3. Third click: Set end angle and create sector

    Signals:
        sector_created: Emitted when sector is created (center, radius, start_angle, end_angle, layer)
    """

    sector_created = pyqtSignal(QgsPointXY, float, float, float, QgsVectorLayer)

    # Tool states
    STATE_START = 0
    STATE_RADIUS = 1
    STATE_ANGLE = 2

    def __init__(self, canvas):
        """
        Initialize search sector tool.

        Args:
            canvas: QGIS map canvas
        """
        # BUG-054 fix: Call BaseDrawingTool initialization
        # This sets up wgs84, itm, distance_calc, rubber_bands, and cursor
        super().__init__(canvas)

        # Sector-specific state
        self.state = self.STATE_START
        self.center = None
        self.radius = None
        self.start_angle = None
        self.end_angle = None

        # Sector-specific visual feedback elements
        self.center_marker = None
        self.radius_band = None
        self.sector_band = None

    def canvasPressEvent(self, event):
        """Handle mouse click - multi-step sector creation."""
        # BUG-052 fix: Only respond to left mouse button
        # Right-click should not advance state, allows for context menu/cancel
        if event.button() != LeftButton:
            return

        point = self.toMapCoordinates(event.pos())

        # Transform to WGS84 for consistent calculations
        # CRITICAL FIX (BUG-026): Add exception handling for coordinate transforms
        try:
            canvas_crs = self.canvas.mapSettings().destinationCrs()
            transform = QgsCoordinateTransform(
                canvas_crs,
                self.wgs84,
                QgsProject.instance()
            )
            point_wgs84 = transform.transform(point)
        except Exception as exc:
            from qgis.utils import iface
            from ..utils.notify import warning
            warning(
                iface.messageBar(),
                "Sector Tool",
                f"Coordinate transform failed: {exc}. Please check the map CRS.",
                duration=5
            )
            return

        if self.state == self.STATE_START:
            # First click: Set center
            self.center = point_wgs84
            self.show_center_marker(point)
            self.state = self.STATE_RADIUS

        elif self.state == self.STATE_RADIUS:
            # Second click: Set radius and start angle
            self.radius = self.calculate_distance(self.center, point_wgs84)
            self.start_angle = self.calculate_bearing(self.center, point_wgs84)
            self.show_radius_line(self.center, point_wgs84)
            self.state = self.STATE_ANGLE

        elif self.state == self.STATE_ANGLE:
            # Third click: Set end angle and create sector
            self.end_angle = self.calculate_bearing(self.center, point_wgs84)

            # Create the sector
            layer = self.create_sector_layer()

            # Emit signal
            self.sector_created.emit(
                self.center,
                self.radius,
                self.start_angle,
                self.end_angle,
                layer
            )

            # Reset tool
            self.reset()

    def canvasMoveEvent(self, event):
        """Handle mouse move - show preview based on current state."""
        if self.state == self.STATE_START:
            return  # No preview in initial state

        point = self.toMapCoordinates(event.pos())

        # Transform to WGS84
        canvas_crs = self.canvas.mapSettings().destinationCrs()
        transform = QgsCoordinateTransform(
            canvas_crs,
            self.wgs84,
            QgsProject.instance()
        )
        point_wgs84 = transform.transform(point)

        if self.state == self.STATE_RADIUS:
            # Show radius preview
            self.show_radius_preview(self.center, point_wgs84)

        elif self.state == self.STATE_ANGLE:
            # Show sector preview
            current_angle = self.calculate_bearing(self.center, point_wgs84)
            self.show_sector_preview(self.center, self.radius, self.start_angle, current_angle)

    def canvasReleaseEvent(self, event):
        """Handle mouse release (not used)."""
        pass

    def calculate_distance(self, point1, point2):
        """
        Calculate distance between two points in meters.

        Args:
            point1: First point (QgsPointXY) in WGS84
            point2: Second point (QgsPointXY) in WGS84

        Returns:
            Distance in meters
        """
        return self.distance_calc.measureLine(point1, point2)

    def calculate_bearing(self, point1, point2):
        """
        Calculate bearing from point1 to point2.

        Args:
            point1: Start point (QgsPointXY) in WGS84
            point2: End point (QgsPointXY) in WGS84

        Returns:
            Bearing in degrees (0-360, where 0 = North)
        """
        # Calculate bearing using simple spherical approximation
        lat1 = math.radians(point1.y())
        lat2 = math.radians(point2.y())
        lon1 = math.radians(point1.x())
        lon2 = math.radians(point2.x())

        dlon = lon2 - lon1

        x = math.sin(dlon) * math.cos(lat2)
        y = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlon)

        bearing = math.atan2(x, y)
        bearing = math.degrees(bearing)

        # Normalize to 0-360
        return (bearing + 360) % 360

    def _calculate_arc_length(self, start_angle, end_angle):
        """
        Calculate the clockwise arc length between two bearings.

        Delegates to the shared utility function in utils.drawing_math to ensure
        consistency across all sector calculations in the codebase.

        Args:
            start_angle: Start bearing in degrees (0 = North, can be any value)
            end_angle: End bearing in degrees (can be any value)

        Returns:
            float: Arc length in degrees (0 to 360)
        """
        return calculate_sector_arc_length(start_angle, end_angle)

    def create_sector_geometry(self, center, radius, start_angle, end_angle):
        """
        Create a sector (wedge) geometry.

        Args:
            center: Center point (QgsPointXY) in WGS84
            radius: Radius in meters
            start_angle: Start angle in degrees (0 = North)
            end_angle: End angle in degrees

        Returns:
            QgsGeometry polygon representing the sector
        """
        points = [center]  # Start at center

        # Calculate arc length using shared, validated logic
        arc_length = self._calculate_arc_length(start_angle, end_angle)

        # Normalize angles for geometry generation
        start = start_angle % 360
        end = end_angle % 360
        if end < start:
            end += 360
        elif start == end:
            # Full circle case
            end = start + 360

        # Number of segments for the arc
        segments = max(10, int(arc_length / 5))  # One point every 5 degrees

        # Create arc points
        # Apply latitude correction for longitude distortion
        # At higher latitudes, longitude degrees are "narrower" than latitude degrees
        center_lat_rad = math.radians(center.y())
        cos_lat = math.cos(center_lat_rad)

        for i in range(segments + 1):
            angle = start + (arc_length * i / segments)
            angle_rad = math.radians(angle)

            # Approximate distance in degrees
            # 111000m = 1 degree latitude (constant)
            # Longitude degree varies by latitude: 111000m * cos(lat)
            dist_deg_lat = radius / 111000.0
            dist_deg_lon = radius / (111000.0 * cos_lat) if cos_lat > 0.01 else dist_deg_lat

            # Calculate point position with latitude correction
            dx = dist_deg_lon * math.sin(angle_rad)  # Longitude offset (corrected)
            dy = dist_deg_lat * math.cos(angle_rad)  # Latitude offset (no correction needed)

            point = QgsPointXY(
                center.x() + dx,
                center.y() + dy
            )
            points.append(point)

        # Close back to center
        points.append(center)

        return QgsGeometry.fromPolygonXY([points])

    def create_sector_layer(self):
        """
        Create a vector layer containing the search sector.

        Returns:
            QgsVectorLayer containing the sector
        """
        # Create memory layer
        layer = QgsVectorLayer(
            "Polygon?crs=EPSG:4326&"
            "field=radius_m:double&"
            "field=start_angle:double&"
            "field=end_angle:double&"
            "field=arc_length:double&"
            "field=area_sqkm:double",
            "Search Sector",
            "memory"
        )

        provider = layer.dataProvider()

        # Create sector geometry
        geometry = self.create_sector_geometry(
            self.center,
            self.radius,
            self.start_angle,
            self.end_angle
        )

        # Calculate arc length using shared, validated logic
        # CRITICAL: This MUST match the geometry calculation to ensure
        # area metadata accurately reflects the drawn sector
        arc_length = self._calculate_arc_length(self.start_angle, self.end_angle)

        # Calculate area (approximate) - use actual arc length
        area_sqm = (math.pi * self.radius * self.radius) * (arc_length / 360)
        area_sqkm = area_sqm / 1000000

        # Create feature
        feature = QgsFeature(layer.fields())
        feature.setGeometry(geometry)

        # IMPORTANT: Set attributes by field name (not positional list).
        # Persistent (GeoPackage/OGR) layers may include provider-managed fields
        # (e.g. fid) that vary by QGIS version/platform, and positional
        # setAttributes() will fail with "wrong field count".
        attr_map = {
            "radius_m": self.radius,
            "start_angle": self.start_angle,
            "end_angle": self.end_angle,
            "arc_length": arc_length,
            "area_sqkm": area_sqkm,
        }
        fields = layer.fields()
        for field_name, value in attr_map.items():
            idx = fields.indexFromName(field_name)
            if idx != -1:
                feature.setAttribute(idx, value)

        # Add feature
        provider.addFeatures([feature])

        # Apply styling
        self.style_sector(layer)

        # Add to project
        QgsProject.instance().addMapLayer(layer)

        return layer

    def style_sector(self, layer):
        """
        Apply styling to sector layer.

        Args:
            layer: QgsVectorLayer to style
        """
        renderer = layer.renderer()
        if renderer:
            symbol = renderer.symbol()
            if symbol:
                # Semi-transparent blue fill
                symbol.setColor(QColor(0, 100, 255, 50))
                # Blue outline
                symbol.symbolLayer(0).setStrokeColor(QColor(0, 100, 255, 200))
                symbol.symbolLayer(0).setStrokeWidth(2.0)

    def show_center_marker(self, point):
        """Show marker at center point."""
        if self.center_marker:
            self.canvas.scene().removeItem(self.center_marker)

        self.center_marker = QgsVertexMarker(self.canvas)
        self.center_marker.setCenter(point)
        self.center_marker.setColor(QColor(255, 0, 0))
        self.center_marker.setIconSize(10)
        self.center_marker.setIconType(QgsVertexMarker.ICON_CROSS)
        self.center_marker.setPenWidth(2)

    def show_radius_line(self, start, end):
        """Show line indicating radius."""
        # BUG-053 fix: Properly clean up old rubber band before creating new one
        if self.radius_band:
            self.canvas.scene().removeItem(self.radius_band)
            self.radius_band = None

        # Create line geometry
        line = QgsGeometry.fromPolylineXY([start, end])

        # Transform to canvas CRS
        canvas_crs = self.canvas.mapSettings().destinationCrs()
        if canvas_crs.authid() != "EPSG:4326":
            transform = QgsCoordinateTransform(
                self.wgs84,
                canvas_crs,
                QgsProject.instance()
            )
            line.transform(transform)

        self.radius_band = QgsRubberBand(self.canvas, QgsWkbTypes.LineGeometry)
        self.radius_band.setColor(QColor(255, 0, 0, 200))
        self.radius_band.setWidth(2)
        self.radius_band.setToGeometry(line, None)
        # BUG-053/054 fix: Track rubber band for proper cleanup via base class
        if self.radius_band not in self.rubber_bands:
            self.rubber_bands.append(self.radius_band)

    def show_radius_preview(self, center, current):
        """Show preview of radius."""
        self.show_radius_line(center, current)

    def show_sector_preview(self, center, radius, start_angle, current_angle):
        """Show preview of sector."""
        # BUG-053 fix: Properly clean up old rubber band before creating new one
        if self.sector_band:
            self.canvas.scene().removeItem(self.sector_band)
            self.sector_band = None

        # Create sector geometry
        geometry = self.create_sector_geometry(center, radius, start_angle, current_angle)

        # Transform to canvas CRS
        canvas_crs = self.canvas.mapSettings().destinationCrs()
        if canvas_crs.authid() != "EPSG:4326":
            transform = QgsCoordinateTransform(
                self.wgs84,
                canvas_crs,
                QgsProject.instance()
            )
            geometry.transform(transform)

        self.sector_band = QgsRubberBand(self.canvas, QgsWkbTypes.PolygonGeometry)
        self.sector_band.setColor(QColor(0, 100, 255, 50))
        self.sector_band.setStrokeColor(QColor(0, 100, 255, 200))
        self.sector_band.setWidth(2)
        self.sector_band.setToGeometry(geometry, None)
        # BUG-053/054 fix: Track rubber band for proper cleanup via base class
        if self.sector_band not in self.rubber_bands:
            self.rubber_bands.append(self.sector_band)

    def reset(self):
        """Reset tool to initial state."""
        self.state = self.STATE_START
        self.center = None
        self.radius = None
        self.start_angle = None
        self.end_angle = None

        # Clear visual elements
        if self.center_marker:
            self.canvas.scene().removeItem(self.center_marker)
            self.center_marker = None

        # BUG-053/054 fix: Use base class clear_rubber_bands() for consistent cleanup
        # This properly cleans up all tracked rubber bands
        self.clear_rubber_bands()
        self.radius_band = None
        self.sector_band = None

    def activate(self):
        """Called when tool is activated."""
        # BUG-054 fix: Base class handles cursor and rubber band cleanup
        super().activate()
        # Reset sector-specific state
        self.reset()

    def deactivate(self):
        """Called when tool is deactivated."""
        # BUG-054 fix: Base class handles rubber band cleanup
        super().deactivate()
        # Reset sector-specific state
        self.reset()

    # BUG-054 fix: Removed isZoomTool(), isEditTool(), isTransient()
    # These are inherited from BaseDrawingTool with correct defaults

    def isTransient(self):
        """Return False - tool stays active for multiple clicks."""
        return False

    def isEditTool(self):
        """Return True - this is an editing tool."""
        return True

    def keyPressEvent(self, event):
        """Handle keyboard input."""
        # ESC key cancels current operation
        if event.key() == Key_Escape:
            self.reset()
            event.ignore()  # Let QGIS also handle it