# -*- coding: utf-8 -*-
"""
Layers Controller (Orchestrator)

Main controller for SAR layer management.
Delegates to specialized managers for different layer types.

This is a thin orchestrator that provides a unified API while delegating
actual layer management to specialized manager classes:
- TrackingLayerManager: Current positions and breadcrumbs
- MarkerLayerManager: IPP/LKP, Clues, and Hazards
- DrawingLayerManager: Lines, areas, rings, sectors, labels

Qt5/Qt6 Compatible: Uses qgis.PyQt for all imports.
"""

from typing import List, Dict
from qgis.core import QgsProject, QgsPointXY

from .layer_managers.tracking_manager import TrackingLayerManager
from .layer_managers.marker_manager import MarkerLayerManager
from .layer_managers.drawing_manager import DrawingLayerManager


class LayersController:
    """
    Main controller for SAR layer management.

    Provides unified interface for all layer operations while delegating
    to specialized managers for actual implementation.

    Architecture:
    - TrackingLayerManager: Live device tracking (positions, breadcrumbs)
    - MarkerLayerManager: Static markers (IPP/LKP, clues, hazards)
    - DrawingLayerManager: Geometric features (lines, areas, rings, etc.)
    """

    # Layer group name (shared across all managers)
    LAYER_GROUP_NAME = "SAR Tracking"

    def __init__(self, iface):
        """
        Initialize layers controller.

        Args:
            iface: QGIS interface object
        """
        self.iface = iface
        self.project = QgsProject.instance()

        # Initialize specialized managers
        self.tracking = TrackingLayerManager(iface)
        self.markers = MarkerLayerManager(iface)
        self.drawings = DrawingLayerManager(iface)

    # =========================================================================
    # Tracking Methods (delegate to tracking manager)
    # =========================================================================

    def update_current_positions(self, positions: List[Dict]):
        """
        Update current positions layer.

        Args:
            positions: List of position dicts from tracking provider
        """
        return self.tracking.update_current_positions(positions)

    def update_breadcrumbs(self, positions: List[Dict], time_gap_minutes: int = 5):
        """
        Update breadcrumb trails layer.

        Args:
            positions: List of position dicts from tracking provider
            time_gap_minutes: Minutes gap to break trail into segments (default: 5)
        """
        return self.tracking.update_breadcrumbs(positions, time_gap_minutes)

    # =========================================================================
    # Marker Methods (delegate to marker manager)
    # =========================================================================

    def add_ipp_lkp(self, name: str, lat: float, lon: float,
                    subject_category: str = "", description: str = "",
                    irish_grid_e: float = None, irish_grid_n: float = None) -> str:
        """
        Add an IPP/LKP (Initial Planning Point / Last Known Position) marker.

        Args:
            name: Marker name/identifier
            lat: Latitude (WGS84 decimal degrees)
            lon: Longitude (WGS84 decimal degrees)
            subject_category: Subject type (e.g., "Child (1-3 years)", "Hiker", "Elderly")
            description: Additional notes
            irish_grid_e: Irish Grid (ITM) Easting (optional)
            irish_grid_n: Irish Grid (ITM) Northing (optional)

        Returns:
            str: UUID of added marker
        """
        return self.markers.add_ipp_lkp(
            name, lat, lon, subject_category, description,
            irish_grid_e, irish_grid_n
        )

    def add_clue(self, name: str, lat: float, lon: float,
                 clue_type: str = "", confidence: str = "Possible",
                 description: str = "",
                 irish_grid_e: float = None, irish_grid_n: float = None) -> str:
        """
        Add a clue marker (evidence found during search).

        Args:
            name: Clue name/identifier
            lat: Latitude (WGS84 decimal degrees)
            lon: Longitude (WGS84 decimal degrees)
            clue_type: Type (Footprint, Clothing, Equipment, Witness Sighting, etc.)
            confidence: Confidence level (Confirmed, Probable, Possible)
            description: Additional notes
            irish_grid_e: Irish Grid (ITM) Easting (optional)
            irish_grid_n: Irish Grid (ITM) Northing (optional)

        Returns:
            str: UUID of added clue
        """
        return self.markers.add_clue(
            name, lat, lon, clue_type, confidence, description,
            irish_grid_e, irish_grid_n
        )

    def add_hazard(self, name: str, lat: float, lon: float,
                   hazard_type: str = "", severity: str = "Medium",
                   description: str = "",
                   irish_grid_e: float = None, irish_grid_n: float = None) -> str:
        """
        Add a hazard marker (safety warning).

        Args:
            name: Hazard name/identifier
            lat: Latitude (WGS84 decimal degrees)
            lon: Longitude (WGS84 decimal degrees)
            hazard_type: Type (Cliff/Drop-off, Water Hazard, Bog, etc.)
            severity: Severity level (Critical, High, Medium, Low)
            description: Additional notes
            irish_grid_e: Irish Grid (ITM) Easting (optional)
            irish_grid_n: Irish Grid (ITM) Northing (optional)

        Returns:
            str: UUID of added hazard
        """
        return self.markers.add_hazard(
            name, lat, lon, hazard_type, severity, description,
            irish_grid_e, irish_grid_n
        )

    # =========================================================================
    # Drawing Methods (delegate to drawing manager)
    # =========================================================================

    def add_line(self, name: str, points_wgs84: List[QgsPointXY],
                 description: str = "", color: str = "#FF0000", width: int = 2) -> int:
        """
        Add a line feature.

        Args:
            name: Line name
            points_wgs84: List of QgsPointXY in WGS84
            description: Optional description
            color: Hex color string (default red)
            width: Line width in pixels (default 2)

        Returns:
            int: Feature ID of added line
        """
        return self.drawings.add_line(name, points_wgs84, description, color, width)

    def add_search_area(self, name: str, polygon_wgs84: List[QgsPointXY],
                        team: str = "Unassigned", status: str = "Planned",
                        priority: str = "Medium", POA: float = 50.0,
                        terrain: str = "", search_method: str = "",
                        color: str = "#0064FF", notes: str = "") -> int:
        """
        Add a search area polygon.

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
        return self.drawings.add_search_area(
            name, polygon_wgs84, team, status, priority, POA,
            terrain, search_method, color, notes
        )

    def add_range_ring(self, name: str, center_wgs84: QgsPointXY, radius_m: float,
                       label: str = "", color: str = "#FFA500",
                       lpb_category: str = "", percentile: int = 0) -> int:
        """
        Add a range ring (circle).

        Uses WGS84 ellipsoid geodesic calculations for accuracy (<1m error).

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
        return self.drawings.add_range_ring(
            name, center_wgs84, radius_m, label, color,
            lpb_category, percentile
        )

    def add_bearing_line(self, name: str, origin_wgs84: QgsPointXY,
                         bearing: float, distance_m: float,
                         label: str = "", color: str = "#800080") -> int:
        """
        Add a bearing line.

        Uses WGS84 ellipsoid geodesic calculations for accuracy (<1m error).

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
        return self.drawings.add_bearing_line(
            name, origin_wgs84, bearing, distance_m, label, color
        )

    def add_sector(self, name: str, center_wgs84: QgsPointXY,
                   start_bearing: float, end_bearing: float, radius_m: float,
                   priority: str = "Medium", color: str = "#FF6464") -> int:
        """
        Add a search sector (wedge/pie-slice).

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
        return self.drawings.add_sector(
            name, center_wgs84, start_bearing, end_bearing, radius_m,
            priority, color
        )

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
        return self.drawings.add_text_label(
            text, location_wgs84, font_size, color, rotation
        )

    # =========================================================================
    # Common Methods
    # =========================================================================

    def get_or_create_layer_group(self):
        """
        Get or create SAR Tracking layer group.

        Returns:
            QgsLayerTreeGroup: The SAR Tracking group
        """
        # Delegate to tracking manager (any manager can handle this)
        return self.tracking.get_or_create_layer_group()

    def clear_layers(self):
        """
        Remove all SAR tracking layers.

        Clears the entire SAR Tracking group and all device colors.
        """
        group = self.project.layerTreeRoot().findGroup(self.LAYER_GROUP_NAME)
        if group:
            self.project.layerTreeRoot().removeChildNode(group)

        # Clear cached device colors from all managers
        self.tracking.device_colors.clear()
        self.markers.device_colors.clear()
        self.drawings.device_colors.clear()
