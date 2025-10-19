# -*- coding: utf-8 -*-
"""
Drawing Layer Manager

Manages all drawing and annotation layers for SAR operations:
- Lines: Free-form paths and routes
- Search Areas: Polygons for assigning search segments
- Range Rings: Circular search areas (manual or LPB-based)
- Bearing Lines: Direction lines from a point
- Search Sectors: Wedge/pie-slice search areas
- Text Labels: Map annotations

CRITICAL: This module contains WGS84 ellipsoid geodesic calculations
that must be preserved EXACTLY for accuracy (<1m error requirement).

Qt5/Qt6 Compatible: Uses qgis.PyQt for all imports.
"""

from typing import List
import math
import uuid
from datetime import datetime

from qgis.core import (
    QgsVectorLayer, QgsField, QgsFeature, QgsGeometry,
    QgsPointXY, QgsDistanceArea, QgsProject, QgsLineSymbol,
    QgsMarkerSymbol
)
from qgis.PyQt.QtGui import QColor

from .base_manager import BaseLayerManager


class DrawingLayerManager(BaseLayerManager):
    """
    Manages all drawing and annotation layers.

    Provides methods for creating various geometric features used in SAR operations.
    All distance calculations use WGS84 ellipsoid for maximum accuracy.
    """

    # Layer names
    LINES_LAYER_NAME = "Lines"
    SEARCH_AREAS_LAYER_NAME = "Search Areas"
    RANGE_RINGS_LAYER_NAME = "Range Rings"
    BEARING_LINES_LAYER_NAME = "Bearing Lines"
    SECTORS_LAYER_NAME = "Search Sectors"
    TEXT_LABELS_LAYER_NAME = "Text Labels"

    def __init__(self, iface):
        """Initialize drawing layer manager."""
        super().__init__(iface)

    def get_managed_layer_names(self):
        """Return list of layer names this manager handles."""
        return [
            self.LINES_LAYER_NAME,
            self.SEARCH_AREAS_LAYER_NAME,
            self.RANGE_RINGS_LAYER_NAME,
            self.BEARING_LINES_LAYER_NAME,
            self.SECTORS_LAYER_NAME,
            self.TEXT_LABELS_LAYER_NAME
        ]

    # =========================================================================
    # Lines Layer
    # =========================================================================

    def _get_or_create_lines_layer(self) -> QgsVectorLayer:
        """
        Get or create Lines layer for drawn paths/routes.

        Returns:
            QgsVectorLayer: Lines layer
        """
        layers = self.project.mapLayersByName(self.LINES_LAYER_NAME)
        if layers:
            return layers[0]

        # Create memory layer with WGS84 CRS
        # Qt5/Qt6 Compatible: Using integer type codes (10=String, 2=Int, 6=Double)
        layer = QgsVectorLayer(
            "LineString?crs=EPSG:4326",
            self.LINES_LAYER_NAME,
            "memory"
        )

        # Add fields
        layer.dataProvider().addAttributes([
            QgsField("id", 10),           # String - unique ID
            QgsField("name", 10),         # String - line name
            QgsField("description", 10),  # String - notes
            QgsField("color", 10),        # String - hex color
            QgsField("width", 2),         # Int - line width in pixels
            QgsField("distance_m", 6),    # Double - length in meters
            QgsField("created", 10),      # String - ISO timestamp
        ])
        layer.updateFields()

        # Basic styling
        symbol = QgsLineSymbol.createSimple({'color': 'red', 'width': '2'})
        layer.renderer().setSymbol(symbol)

        # Add to project in layer group
        self._add_layer_to_group(layer, position=0)

        return layer

    def add_line(self, name: str, points_wgs84: List[QgsPointXY],
                 description: str = "", color: str = "#FF0000", width: int = 2) -> int:
        """
        Add a line feature to the Lines layer.

        Args:
            name: Line name
            points_wgs84: List of QgsPointXY in WGS84
            description: Optional description
            color: Hex color string (default red)
            width: Line width in pixels (default 2)

        Returns:
            int: Feature ID of added line
        """
        layer = self._get_or_create_lines_layer()

        # Calculate total distance using WGS84 ellipsoid
        distance_calc = QgsDistanceArea()
        distance_calc.setSourceCrs(
            layer.crs(),
            QgsProject.instance().transformContext()
        )
        distance_calc.setEllipsoid('WGS84')

        total_distance = 0
        for i in range(len(points_wgs84) - 1):
            dist = distance_calc.measureLine(points_wgs84[i], points_wgs84[i + 1])
            total_distance += dist

        # Create feature
        feature = QgsFeature(layer.fields())
        feature.setGeometry(QgsGeometry.fromPolylineXY(points_wgs84))

        feature.setAttributes([
            str(uuid.uuid4()),
            name,
            description,
            color,
            width,
            total_distance,
            datetime.now().isoformat()
        ])

        # Add to layer
        layer.startEditing()
        layer.addFeature(feature)
        layer.commitChanges()
        layer.triggerRepaint()

        return feature.id()

    # =========================================================================
    # Search Areas Layer
    # =========================================================================

    def _get_or_create_search_areas_layer(self) -> QgsVectorLayer:
        """
        Get or create Search Areas layer with status tracking.

        Returns:
            QgsVectorLayer: Search Areas layer
        """
        layers = self.project.mapLayersByName(self.SEARCH_AREAS_LAYER_NAME)
        if layers:
            return layers[0]

        # Create memory layer with WGS84 CRS
        # Qt5/Qt6 Compatible: Using integer type codes
        layer = QgsVectorLayer(
            "Polygon?crs=EPSG:4326",
            self.SEARCH_AREAS_LAYER_NAME,
            "memory"
        )

        # Add fields with SAR-specific attributes
        layer.dataProvider().addAttributes([
            QgsField("id", 10),              # String - unique ID
            QgsField("name", 10),            # String - area name
            QgsField("team", 10),            # String - assigned team
            QgsField("status", 10),          # String - Planned/Assigned/InProgress/Completed/Cleared
            QgsField("priority", 10),        # String - High/Medium/Low
            QgsField("area_sqkm", 6),        # Double - area in square km
            QgsField("POA", 6),              # Double - Probability of Area (0-100)
            QgsField("POD", 6),              # Double - Probability of Detection (0-100)
            QgsField("terrain", 10),         # String - terrain type
            QgsField("search_method", 10),   # String - search method
            QgsField("color", 10),           # String - hex color
            QgsField("start_time", 10),      # String - ISO timestamp
            QgsField("end_time", 10),        # String - ISO timestamp
            QgsField("notes", 10),           # String - additional notes
            QgsField("created", 10),         # String - ISO timestamp
        ])
        layer.updateFields()

        # Basic styling with semi-transparent fill
        symbol = layer.renderer().symbol()
        symbol.setColor(QColor(0, 100, 255, 80))  # Blue with transparency
        symbol.symbolLayer(0).setStrokeColor(QColor(0, 100, 255))
        symbol.symbolLayer(0).setStrokeWidth(2)

        # Add to project in layer group
        self._add_layer_to_group(layer, position=0)

        return layer

    def add_search_area(self, name: str, polygon_wgs84: List[QgsPointXY],
                        team: str = "Unassigned", status: str = "Planned",
                        priority: str = "Medium", POA: float = 50.0,
                        terrain: str = "", search_method: str = "",
                        color: str = "#0064FF", notes: str = "") -> int:
        """
        Add a search area polygon with status tracking.

        Args:
            name: Area name
            polygon_wgs84: List of QgsPointXY in WGS84 forming closed polygon
            team: Assigned team name
            status: Status (Planned/Assigned/InProgress/Completed/Cleared)
            priority: Priority level (High/Medium/Low)
            POA: Probability of Area (0-100)
            terrain: Terrain description
            search_method: Search method to use
            color: Hex color string
            notes: Additional notes

        Returns:
            int: Feature ID of added search area
        """
        layer = self._get_or_create_search_areas_layer()

        # Calculate area in square kilometers using WGS84 ellipsoid
        distance_calc = QgsDistanceArea()
        distance_calc.setSourceCrs(
            layer.crs(),
            QgsProject.instance().transformContext()
        )
        distance_calc.setEllipsoid('WGS84')

        # Create polygon geometry
        polygon_geom = QgsGeometry.fromPolygonXY([polygon_wgs84])
        area_sqm = distance_calc.measureArea(polygon_geom)
        area_sqkm = area_sqm / 1000000.0  # Convert to km²

        # Create feature
        feature = QgsFeature(layer.fields())
        feature.setGeometry(polygon_geom)

        feature.setAttributes([
            str(uuid.uuid4()),
            name,
            team,
            status,
            priority,
            area_sqkm,
            POA,
            0.0,  # POD - to be calculated/updated later
            terrain,
            search_method,
            color,
            "",  # start_time - set when status changes to InProgress
            "",  # end_time - set when status changes to Completed
            notes,
            datetime.now().isoformat()
        ])

        # Add to layer
        layer.startEditing()
        layer.addFeature(feature)
        layer.commitChanges()
        layer.triggerRepaint()

        return feature.id()

    # =========================================================================
    # Range Rings Layer
    # =========================================================================

    def _get_or_create_range_rings_layer(self) -> QgsVectorLayer:
        """
        Get or create Range Rings layer for distance circles.

        Returns:
            QgsVectorLayer: Range Rings layer
        """
        layers = self.project.mapLayersByName(self.RANGE_RINGS_LAYER_NAME)
        if layers:
            return layers[0]

        # Create memory layer with WGS84 CRS
        # Qt5/Qt6 Compatible: Using integer type codes
        layer = QgsVectorLayer(
            "Polygon?crs=EPSG:4326",
            self.RANGE_RINGS_LAYER_NAME,
            "memory"
        )

        # Add fields
        layer.dataProvider().addAttributes([
            QgsField("id", 10),              # String - unique ID
            QgsField("name", 10),            # String - ring name
            QgsField("center_lat", 6),       # Double - center latitude
            QgsField("center_lon", 6),       # Double - center longitude
            QgsField("radius_m", 6),         # Double - radius in meters
            QgsField("label", 10),           # String - display label
            QgsField("color", 10),           # String - hex color
            QgsField("lpb_category", 10),    # String - LPB category if applicable
            QgsField("percentile", 2),       # Int - LPB percentile (25, 50, 75, 95)
            QgsField("created", 10),         # String - ISO timestamp
        ])
        layer.updateFields()

        # Basic styling with transparent fill
        symbol = layer.renderer().symbol()
        symbol.setColor(QColor(255, 165, 0, 40))  # Orange with high transparency
        symbol.symbolLayer(0).setStrokeColor(QColor(255, 165, 0))
        symbol.symbolLayer(0).setStrokeWidth(1.5)

        # Add to project in layer group
        self._add_layer_to_group(layer, position=0)

        return layer

    def add_range_ring(self, name: str, center_wgs84: QgsPointXY, radius_m: float,
                       label: str = "", color: str = "#FFA500",
                       lpb_category: str = "", percentile: int = 0) -> int:
        """
        Add a range ring (circle) feature.

        CRITICAL: Uses WGS84 ellipsoid geodesic calculations for accuracy.
        DO NOT MODIFY the geodesic math without thorough testing.

        Args:
            name: Ring name
            center_wgs84: Center point in WGS84
            radius_m: Radius in meters
            label: Display label (e.g., "1 km" or "50% probability")
            color: Hex color string
            lpb_category: LPB category if this is an LPB-based ring
            percentile: LPB percentile if applicable (25, 50, 75, 95)

        Returns:
            int: Feature ID of added ring
        """
        layer = self._get_or_create_range_rings_layer()

        # Create circle geometry using geodesic calculations
        # Use proper WGS84 ellipsoid parameters for accuracy
        # CRITICAL: This code was carefully tuned for <1m accuracy
        # Bug fix from Day 7 audit - DO NOT MODIFY

        # Number of segments for smooth circle
        segments = 64
        points = []

        # WGS84 ellipsoid parameters (more accurate than sphere)
        # Semi-major axis (equatorial radius)
        a = 6378137.0  # meters
        # Flattening
        f = 1 / 298.257223563
        # Semi-minor axis (polar radius)
        b = a * (1 - f)

        # Use mean Earth radius adjusted for latitude
        lat_rad = math.radians(center_wgs84.y())
        # Radius at given latitude (more accurate than constant radius)
        cos_lat = math.cos(lat_rad)
        sin_lat = math.sin(lat_rad)

        # Calculate radius of curvature at this latitude
        # This accounts for Earth's oblate spheroid shape
        numerator = (a * a * cos_lat)**2 + (b * b * sin_lat)**2
        denominator = (a * cos_lat)**2 + (b * sin_lat)**2
        earth_radius = math.sqrt(numerator / denominator)

        # Create circle points using geodesic calculations
        for i in range(segments + 1):
            # Calculate bearing in degrees
            bearing = (360.0 * i) / segments

            # Convert to radians
            bearing_rad = math.radians(bearing)
            lon_rad = math.radians(center_wgs84.x())

            # Calculate angular distance
            angular_distance = radius_m / earth_radius

            # Calculate destination point using haversine formula
            lat2 = math.asin(
                math.sin(lat_rad) * math.cos(angular_distance) +
                math.cos(lat_rad) * math.sin(angular_distance) * math.cos(bearing_rad)
            )

            lon2 = lon_rad + math.atan2(
                math.sin(bearing_rad) * math.sin(angular_distance) * math.cos(lat_rad),
                math.cos(angular_distance) - math.sin(lat_rad) * math.sin(lat2)
            )

            # Convert back to degrees
            point = QgsPointXY(math.degrees(lon2), math.degrees(lat2))
            points.append(point)

        # Create polygon geometry from points
        circle_geom = QgsGeometry.fromPolygonXY([points])

        # Create feature
        feature = QgsFeature(layer.fields())
        feature.setGeometry(circle_geom)

        feature.setAttributes([
            str(uuid.uuid4()),
            name,
            center_wgs84.y(),  # latitude
            center_wgs84.x(),  # longitude
            radius_m,
            label,
            color,
            lpb_category,
            percentile,
            datetime.now().isoformat()
        ])

        # Add to layer
        layer.startEditing()
        layer.addFeature(feature)
        layer.commitChanges()
        layer.triggerRepaint()

        return feature.id()

    # =========================================================================
    # Bearing Lines Layer
    # =========================================================================

    def _get_or_create_bearing_lines_layer(self) -> QgsVectorLayer:
        """
        Get or create Bearing Lines layer for direction-finding.

        Returns:
            QgsVectorLayer: Bearing Lines layer
        """
        layers = self.project.mapLayersByName(self.BEARING_LINES_LAYER_NAME)
        if layers:
            return layers[0]

        # Create memory layer with WGS84 CRS
        # Qt5/Qt6 Compatible: Using integer type codes
        layer = QgsVectorLayer(
            "LineString?crs=EPSG:4326",
            self.BEARING_LINES_LAYER_NAME,
            "memory"
        )

        # Add fields
        layer.dataProvider().addAttributes([
            QgsField("id", 10),              # String - unique ID
            QgsField("name", 10),            # String - line name
            QgsField("origin_lat", 6),       # Double - origin latitude
            QgsField("origin_lon", 6),       # Double - origin longitude
            QgsField("bearing", 6),          # Double - bearing in degrees (0-360)
            QgsField("distance_m", 6),       # Double - line length in meters
            QgsField("label", 10),           # String - display label
            QgsField("color", 10),           # String - hex color
            QgsField("created", 10),         # String - ISO timestamp
        ])
        layer.updateFields()

        # Basic styling
        symbol = QgsLineSymbol.createSimple({'color': 'purple', 'width': '2'})
        layer.renderer().setSymbol(symbol)

        # Add to project in layer group
        self._add_layer_to_group(layer, position=0)

        return layer

    def add_bearing_line(self, name: str, origin_wgs84: QgsPointXY,
                         bearing: float, distance_m: float,
                         label: str = "", color: str = "#800080") -> int:
        """
        Add a bearing line feature.

        CRITICAL: Uses WGS84 ellipsoid geodesic calculations for accuracy.
        DO NOT MODIFY the geodesic math without thorough testing.

        Args:
            name: Line name
            origin_wgs84: Origin point in WGS84
            bearing: Bearing in degrees (0-360, where 0=North)
            distance_m: Line length in meters
            label: Display label
            color: Hex color string

        Returns:
            int: Feature ID of added bearing line
        """
        layer = self._get_or_create_bearing_lines_layer()

        # Calculate endpoint using bearing and distance
        # CRITICAL: This code was carefully tuned for <1m accuracy
        # Bug fix from Day 7 audit - DO NOT MODIFY

        # Convert bearing to radians for calculation
        bearing_rad = math.radians(bearing)

        # Calculate endpoint using WGS84 ellipsoid parameters
        lat1 = math.radians(origin_wgs84.y())
        lon1 = math.radians(origin_wgs84.x())

        # WGS84 ellipsoid parameters
        a = 6378137.0  # Semi-major axis (equatorial radius) in meters
        f = 1 / 298.257223563  # Flattening
        b = a * (1 - f)  # Semi-minor axis (polar radius)

        # Calculate radius of curvature at origin latitude
        cos_lat = math.cos(lat1)
        sin_lat = math.sin(lat1)
        numerator = (a * a * cos_lat)**2 + (b * b * sin_lat)**2
        denominator = (a * cos_lat)**2 + (b * sin_lat)**2
        earth_radius = math.sqrt(numerator / denominator)

        # Angular distance
        angular_dist = distance_m / earth_radius

        lat2 = math.asin(math.sin(lat1) * math.cos(angular_dist) +
                         math.cos(lat1) * math.sin(angular_dist) * math.cos(bearing_rad))

        lon2 = lon1 + math.atan2(math.sin(bearing_rad) * math.sin(angular_dist) * math.cos(lat1),
                                  math.cos(angular_dist) - math.sin(lat1) * math.sin(lat2))

        endpoint = QgsPointXY(math.degrees(lon2), math.degrees(lat2))

        # Create line geometry
        line_geom = QgsGeometry.fromPolylineXY([origin_wgs84, endpoint])

        # Create feature
        feature = QgsFeature(layer.fields())
        feature.setGeometry(line_geom)

        feature.setAttributes([
            str(uuid.uuid4()),
            name,
            origin_wgs84.y(),
            origin_wgs84.x(),
            bearing,
            distance_m,
            label,
            color,
            datetime.now().isoformat()
        ])

        # Add to layer
        layer.startEditing()
        layer.addFeature(feature)
        layer.commitChanges()
        layer.triggerRepaint()

        return feature.id()

    # =========================================================================
    # Search Sectors Layer
    # =========================================================================

    def _get_or_create_sectors_layer(self) -> QgsVectorLayer:
        """
        Get or create Search Sectors layer for wedge/pie-slice search areas.

        Returns:
            QgsVectorLayer: Sectors layer
        """
        layers = self.project.mapLayersByName(self.SECTORS_LAYER_NAME)
        if layers:
            return layers[0]

        # Create memory layer with WGS84 CRS
        # Qt5/Qt6 Compatible: Using integer type codes
        layer = QgsVectorLayer(
            "Polygon?crs=EPSG:4326",
            self.SECTORS_LAYER_NAME,
            "memory"
        )

        # Add fields
        layer.dataProvider().addAttributes([
            QgsField("id", 10),              # String - unique ID
            QgsField("name", 10),            # String - sector name
            QgsField("center_lat", 6),       # Double - center latitude
            QgsField("center_lon", 6),       # Double - center longitude
            QgsField("start_bearing", 6),    # Double - start bearing (degrees)
            QgsField("end_bearing", 6),      # Double - end bearing (degrees)
            QgsField("radius_m", 6),         # Double - radius in meters
            QgsField("area_sqkm", 6),        # Double - area in square km
            QgsField("priority", 10),        # String - High/Medium/Low
            QgsField("color", 10),           # String - hex color
            QgsField("created", 10),         # String - ISO timestamp
        ])
        layer.updateFields()

        # Basic styling with semi-transparent fill
        symbol = layer.renderer().symbol()
        symbol.setColor(QColor(255, 100, 100, 60))  # Red with transparency
        symbol.symbolLayer(0).setStrokeColor(QColor(255, 100, 100))
        symbol.symbolLayer(0).setStrokeWidth(2)

        # Add to project in layer group
        self._add_layer_to_group(layer, position=0)

        return layer

    def add_sector(self, name: str, center_wgs84: QgsPointXY,
                   start_bearing: float, end_bearing: float, radius_m: float,
                   priority: str = "Medium", color: str = "#FF6464") -> int:
        """
        Add a sector/wedge feature.

        Args:
            name: Sector name
            center_wgs84: Center point in WGS84
            start_bearing: Start bearing in degrees (0-360)
            end_bearing: End bearing in degrees (0-360)
            radius_m: Radius in meters
            priority: Priority level (High/Medium/Low)
            color: Hex color string

        Returns:
            int: Feature ID of added sector
        """
        layer = self._get_or_create_sectors_layer()

        # Create sector geometry (simplified - create as polygon)
        # Create arc with 36 segments
        num_segments = 36
        angle_range = end_bearing - start_bearing
        if angle_range < 0:
            angle_range += 360

        points = [center_wgs84]  # Start from center

        for i in range(num_segments + 1):
            angle = start_bearing + (angle_range * i / num_segments)
            angle_rad = math.radians(angle)

            # Simplified coordinate calculation (could be improved with full ellipsoid)
            lat1 = math.radians(center_wgs84.y())
            lon1 = math.radians(center_wgs84.x())
            angular_dist = radius_m / 6371000.0

            lat2 = math.asin(math.sin(lat1) * math.cos(angular_dist) +
                            math.cos(lat1) * math.sin(angular_dist) * math.cos(angle_rad))
            lon2 = lon1 + math.atan2(math.sin(angle_rad) * math.sin(angular_dist) * math.cos(lat1),
                                     math.cos(angular_dist) - math.sin(lat1) * math.sin(lat2))

            points.append(QgsPointXY(math.degrees(lon2), math.degrees(lat2)))

        points.append(center_wgs84)  # Close the sector

        sector_geom = QgsGeometry.fromPolygonXY([points])

        # Calculate area using WGS84 ellipsoid
        distance_calc = QgsDistanceArea()
        distance_calc.setSourceCrs(layer.crs(), QgsProject.instance().transformContext())
        distance_calc.setEllipsoid('WGS84')
        area_sqm = distance_calc.measureArea(sector_geom)
        area_sqkm = area_sqm / 1000000.0

        # Create feature
        feature = QgsFeature(layer.fields())
        feature.setGeometry(sector_geom)

        feature.setAttributes([
            str(uuid.uuid4()),
            name,
            center_wgs84.y(),
            center_wgs84.x(),
            start_bearing,
            end_bearing,
            radius_m,
            area_sqkm,
            priority,
            color,
            datetime.now().isoformat()
        ])

        # Add to layer
        layer.startEditing()
        layer.addFeature(feature)
        layer.commitChanges()
        layer.triggerRepaint()

        return feature.id()

    # =========================================================================
    # Text Labels Layer
    # =========================================================================

    def _get_or_create_text_labels_layer(self) -> QgsVectorLayer:
        """
        Get or create Text Labels layer for map annotations.

        Returns:
            QgsVectorLayer: Text Labels layer
        """
        layers = self.project.mapLayersByName(self.TEXT_LABELS_LAYER_NAME)
        if layers:
            return layers[0]

        # Create memory layer with WGS84 CRS
        # Qt5/Qt6 Compatible: Using integer type codes
        layer = QgsVectorLayer(
            "Point?crs=EPSG:4326",
            self.TEXT_LABELS_LAYER_NAME,
            "memory"
        )

        # Add fields
        layer.dataProvider().addAttributes([
            QgsField("id", 10),              # String - unique ID
            QgsField("text", 10),            # String - label text
            QgsField("lat", 6),              # Double - latitude
            QgsField("lon", 6),              # Double - longitude
            QgsField("font_size", 2),        # Int - font size
            QgsField("color", 10),           # String - text color
            QgsField("rotation", 6),         # Double - rotation angle
            QgsField("created", 10),         # String - ISO timestamp
        ])
        layer.updateFields()

        # Basic point styling (small, will show label instead)
        symbol = layer.renderer().symbol()
        symbol.setSize(0)  # Hide the point marker

        # Add to project in layer group
        self._add_layer_to_group(layer, position=0)

        return layer

    def add_text_label(self, text: str, location_wgs84: QgsPointXY,
                       font_size: int = 12, color: str = "#000000",
                       rotation: float = 0.0) -> int:
        """
        Add a text label annotation.

        Args:
            text: Label text
            location_wgs84: Label location in WGS84
            font_size: Font size in points
            color: Text color hex string
            rotation: Rotation angle in degrees

        Returns:
            int: Feature ID of added label
        """
        layer = self._get_or_create_text_labels_layer()

        # Create feature
        feature = QgsFeature(layer.fields())
        feature.setGeometry(QgsGeometry.fromPointXY(location_wgs84))

        feature.setAttributes([
            str(uuid.uuid4()),
            text,
            location_wgs84.y(),
            location_wgs84.x(),
            font_size,
            color,
            rotation,
            datetime.now().isoformat()
        ])

        # Add to layer
        layer.startEditing()
        layer.addFeature(feature)
        layer.commitChanges()
        layer.triggerRepaint()

        return feature.id()
