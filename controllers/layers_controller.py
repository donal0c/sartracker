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

from typing import List, Dict, Optional, Any
from qgis.core import QgsProject, QgsPointXY, QgsLayerTreeGroup

from .layer_managers.tracking_manager import TrackingLayerManager
from .layer_managers.marker_manager import MarkerLayerManager
from .layer_managers.drawing_manager import DrawingLayerManager
from .layer_catalog import LayerCatalogService
from ..layers.helicopter_manager import HelicopterLayerManager
from ..layers import LayerManager as SchemaLayerManager, GroupNames, LayerIds
from ..utils.exceptions import LayerTransactionError


class LayersController:
    """
    Main controller for SAR layer management.

    Provides unified interface for all layer operations while delegating
    to specialized managers for actual implementation.

    Architecture:
    - TrackingLayerManager: Live device tracking (positions, breadcrumbs)
    - MarkerLayerManager: Static markers (IPP/LKP, clues, hazards)
    - DrawingLayerManager: Geometric features (lines, areas, rings, etc.)

    Design Note - Return Value Consistency:
    - Marker methods return str (UUID): Markers are persistent and need stable
      identifiers that survive QGIS restarts and project reloads.
    - Drawing methods return int (feature ID): Drawings are session-specific
      and feature IDs are sufficient for in-session operations.
    - Tracking methods return None: Position updates are bulk operations
      that don't need individual feature tracking.
    This intentional inconsistency reflects different use cases and persistence requirements.

    Design Note - Parameter Validation:
    - This orchestrator is a thin delegation layer that doesn't perform parameter validation.
    - All validation is done in the specialized managers (TrackingLayerManager,
      MarkerLayerManager, DrawingLayerManager).
    - This avoids redundant validation overhead and keeps the orchestrator simple.
    - Exceptions from managers propagate up with full context.
    """

    # Layer group name (shared across all managers)
    LAYER_GROUP_NAME = GroupNames.ROOT
    MARKER_TYPE_TO_LAYER_ID = {
        "ipp_lkp": LayerIds.MARKERS_IPP_LKP,
        "clue": LayerIds.MARKERS_CLUES,
        "hazard": LayerIds.MARKERS_HAZARDS,
        "casualty": LayerIds.MARKERS_CASUALTIES
    }

    def __init__(self, iface, layer_manager: Optional[SchemaLayerManager] = None, task_manager=None):
        """
        Initialize layers controller.

        Args:
            iface: QGIS interface object

        Raises:
            RuntimeError: If manager initialization fails
        """
        self.iface = iface
        self.project = QgsProject.instance()

        if not self.project:
            raise RuntimeError("QgsProject instance not available - cannot initialize LayersController")

        # Shared device color registry for consistency across all layers
        # Same device ID will always get same color in all layers
        self._shared_device_colors = {}

        # Shared LayerManager (GeoPackage-aware)
        self.layer_manager = layer_manager or SchemaLayerManager(iface)
        self.task_manager = task_manager

        # Initialize specialized managers with shared color registry
        # Managers must be initialized in this order (no dependencies between them currently)
        try:
            self.tracking = TrackingLayerManager(
                iface,
                self._shared_device_colors,
                self.layer_manager,
                task_manager=task_manager
            )
        except Exception as e:
            raise RuntimeError(f"Failed to initialize TrackingLayerManager: {e}")

        try:
            self.markers = MarkerLayerManager(iface, self._shared_device_colors, self.layer_manager)
        except Exception as e:
            raise RuntimeError(f"Failed to initialize MarkerLayerManager: {e}")

        try:
            self.drawings = DrawingLayerManager(iface, self._shared_device_colors, self.layer_manager)
        except Exception as e:
            raise RuntimeError(f"Failed to initialize DrawingLayerManager: {e}")

        try:
            self.helicopters = HelicopterLayerManager(iface)
        except Exception as e:
            raise RuntimeError(f"Failed to initialize HelicopterLayerManager: {e}")

        # Initialize catalog service (Phase 1 - CalTopo Console)
        # NON-FATAL: Catalog is optional, core SAR functionality works without it
        try:
            self.catalog = LayerCatalogService(iface, self.layer_manager)
            print("[LayersController] Catalog service initialized successfully")
        except Exception as e:
            self.catalog = None
            print(f"[LayersController] WARNING: Failed to initialize catalog service: {e}")
            print("[LayersController] Plugin will continue without catalog (core functionality unaffected)")
            import traceback
            traceback.print_exc()

    def _assert_not_read_only(self, operation: str):
        """Raise if mission is finalized/read-only."""
        if self.layer_manager and self.layer_manager.is_read_only():
            raise LayerTransactionError("mission data", operation, details="Mission is finalized (read-only)")

    # =========================================================================
    # Tracking Methods (delegate to tracking manager)
    # =========================================================================

    def update_current_positions(self, positions: List[Dict]):
        """
        Update current positions layer.

        Args:
            positions: List of position dicts from tracking provider

        Raises:
            ValueError: If position data is invalid (from manager)
            RuntimeError: If layer operations fail (from manager)
        """
        self._assert_not_read_only("update current positions")
        return self.tracking.update_current_positions(positions)

    def update_breadcrumbs(
        self,
        positions: List[Dict],
        time_gap_minutes: int = 5,
        processed_segments: Optional[Dict[str, Any]] = None
    ):
        """
        Update breadcrumb trails layer.

        Args:
            positions: List of position dicts from tracking provider
            time_gap_minutes: Minutes gap to break trail into segments (default: 5)
            processed_segments: Optional provider-supplied segment payload

        Raises:
            ValueError: If position data is invalid (from manager)
            RuntimeError: If layer operations fail (from manager)
        """
        self._assert_not_read_only("update breadcrumbs")
        return self.tracking.update_breadcrumbs(
            positions,
            time_gap_minutes,
            processed_segments=processed_segments
        )

    # =========================================================================
    # Catalog Methods
    # =========================================================================

    def rescan_catalog(self):
        """Force catalog to rescan all layers (HIGH-5)."""
        if self.catalog:
            self.catalog.rescan_layers()

    def _refresh_catalog_for_layer(self, layer_id: str):
        """Helper to refresh catalog feature count (HIGH-6)."""
        if self.catalog:
            try:
                self.catalog.refresh_layer(layer_id, full=False)
            except Exception as e:
                print(f"[LayersController] Warning: Catalog refresh failed for {layer_id}: {e}")

    # =========================================================================
    # Marker Methods (delegate to marker manager)
    # =========================================================================

    def add_ipp_lkp(self, name: str, lat: float, lon: float,
                    subject_category: str = "", description: str = "",
                    irish_grid_e: float = None, irish_grid_n: float = None,
                    coordinator_ids: Optional[str] = None,
                    updated_by: Optional[str] = None,
                    attachment_path: Optional[str] = None) -> str:
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
            coordinator_ids: CSV of coordinators responsible for this marker
            updated_by: Identifier for the user entering the marker
            attachment_path: Optional attachment stored for the marker

        Returns:
            str: UUID of added marker
        """
        self._assert_not_read_only("add marker")
        marker_id = self.markers.add_ipp_lkp(
            name, lat, lon, subject_category, description,
            irish_grid_e, irish_grid_n,
            coordinator_ids=coordinator_ids,
            updated_by=updated_by,
            attachment_path=attachment_path
        )
        self._refresh_catalog_for_layer(LayerIds.MARKERS_IPP_LKP)
        return marker_id

    def add_clue(self, name: str, lat: float, lon: float,
                 clue_type: str = "", confidence: str = "Possible",
                 description: str = "",
                 irish_grid_e: float = None, irish_grid_n: float = None,
                 coordinator_ids: Optional[str] = None,
                 updated_by: Optional[str] = None,
                 attachment_path: Optional[str] = None) -> str:
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
            coordinator_ids: CSV of coordinators responsible for this clue
            updated_by: Identifier for the user entering the clue
            attachment_path: Optional attachment stored with the clue

        Returns:
            str: UUID of added clue
        """
        self._assert_not_read_only("add marker")
        clue_id = self.markers.add_clue(
            name, lat, lon, clue_type, confidence, description,
            irish_grid_e, irish_grid_n,
            coordinator_ids=coordinator_ids,
            updated_by=updated_by,
            attachment_path=attachment_path
        )
        self._refresh_catalog_for_layer(LayerIds.MARKERS_CLUES)
        return clue_id

    def add_hazard(self, name: str, lat: float, lon: float,
                   hazard_type: str = "", severity: str = "Medium",
                   description: str = "",
                   irish_grid_e: float = None, irish_grid_n: float = None,
                   coordinator_ids: Optional[str] = None,
                   updated_by: Optional[str] = None,
                   attachment_path: Optional[str] = None) -> str:
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
            coordinator_ids: CSV of coordinators responsible for the hazard
            updated_by: Identifier for the user entering the hazard
            attachment_path: Optional attachment stored with the hazard

        Returns:
            str: UUID of added hazard
        """
        self._assert_not_read_only("add marker")
        hazard_id = self.markers.add_hazard(
            name, lat, lon, hazard_type, severity, description,
            irish_grid_e, irish_grid_n,
            coordinator_ids=coordinator_ids,
            updated_by=updated_by,
            attachment_path=attachment_path
        )
        self._refresh_catalog_for_layer(LayerIds.MARKERS_HAZARDS)
        return hazard_id

    def add_casualty(self, name: str, lat: float, lon: float,
                     condition: str = "", treatment: str = "",
                     evacuation_priority: str = "",
                     description: str = "", found_by: str = "",
                     irish_grid_e: float = None, irish_grid_n: float = None,
                     coordinator_ids: Optional[str] = None,
                     updated_by: Optional[str] = None,
                     attachment_path: Optional[str] = None) -> str:
        """
        Add a casualty marker (found injured or deceased person).

        CRITICAL: This is distinct from clues (evidence). Casualties trigger
        medical response, evacuation, and legal documentation requirements.

        Args:
            name: Person identifier/name
            lat: Latitude (WGS84 decimal degrees)
            lon: Longitude (WGS84 decimal degrees)
            condition: Condition (Injured, Deceased, Unresponsive, etc.)
            treatment: First aid administered
            evacuation_priority: Priority (Immediate, Urgent, Delayed, None Required)
            description: Additional notes
            found_by: Team member or device ID who found the casualty
            irish_grid_e: Irish Grid (ITM) Easting (optional)
            irish_grid_n: Irish Grid (ITM) Northing (optional)
            coordinator_ids: CSV of coordinators responsible for the casualty record
            updated_by: Identifier for the user entering the casualty
            attachment_path: Optional attachment stored with the casualty

        Returns:
            str: UUID of added casualty
        """
        self._assert_not_read_only("add marker")
        casualty_id = self.markers.add_casualty(
            name, lat, lon, condition, treatment, evacuation_priority,
            description, found_by, irish_grid_e, irish_grid_n,
            coordinator_ids=coordinator_ids,
            updated_by=updated_by,
            attachment_path=attachment_path
        )
        self._refresh_catalog_for_layer(LayerIds.MARKERS_CASUALTIES)
        return casualty_id

    def list_markers(self) -> List[Dict[str, Any]]:
        """
        Return flattened list of all markers for UI consumption.

        Returns:
            List of dicts with marker metadata
        """
        return self.markers.list_markers()

    def get_marker_feature(self, marker_type: str, marker_id: str):
        """
        Fetch a marker feature by type/id.

        Args:
            marker_type: 'ipp_lkp', 'clue', 'hazard', or 'casualty'
            marker_id: UUID string stored in 'id' attribute
        """
        return self.markers.get_marker_feature(marker_type, marker_id)

    def update_marker(self, marker_type: str, marker_id: str, updates: Dict[str, Any], updated_by: Optional[str] = None) -> bool:
        """
        Update a marker feature in-place.

        Args:
            marker_type: Marker category
            marker_id: UUID string
            updates: Attribute payload keyed by field name
            updated_by: Optional operator name for audit trail
        """
        self._assert_not_read_only("update marker")
        updated = self.markers.update_marker(marker_type, marker_id, updates, updated_by=updated_by)
        layer_id = self.MARKER_TYPE_TO_LAYER_ID.get(marker_type)
        if updated and layer_id:
            self._refresh_catalog_for_layer(layer_id)
        return updated

    def delete_marker(self, marker_type: str, marker_id: str) -> bool:
        """
        Delete a marker by UUID.

        Args:
            marker_type: Marker category
            marker_id: UUID string
        """
        self._assert_not_read_only("delete marker")
        deleted = self.markers.delete_marker(marker_type, marker_id)
        layer_id = self.MARKER_TYPE_TO_LAYER_ID.get(marker_type)
        if deleted and layer_id:
            self._refresh_catalog_for_layer(layer_id)
        return deleted

    # =========================================================================
    # Drawing Methods (delegate to drawing manager)
    # =========================================================================

    def add_line(self, name: str, points_wgs84: List[QgsPointXY],
                 description: str = "", color: str = "#FF0000", width: int = 2,
                 temporary_measure: bool = False) -> int:
        """
        Add a line feature.

        Args:
            name: Line name
            points_wgs84: List of QgsPointXY in WGS84
            description: Optional description
            color: Hex color string (default red)
            width: Line width in pixels (default 2)

        Args:
            temporary_measure: Flag measurement overlays for cleanup

        Returns:
            int: Feature ID of added line
        """
        self._assert_not_read_only("add drawing")
        line_id = self.drawings.add_line(
            name,
            points_wgs84,
            description,
            color,
            width,
            temporary_measure=temporary_measure
        )
        self._refresh_catalog_for_layer(LayerIds.LINES)
        return line_id

    def add_measurement_overlay(self, name: str, points_wgs84: List[QgsPointXY],
                                description: str, color: str = "#FFD447",
                                width: int = 3) -> int:
        """
        Add a temporary measurement overlay to the Lines layer.

        Args:
            name: Overlay label
            points_wgs84: List of points describing the measurement line
            description: Detail text (distance/bearing)
            color: Hex color for the overlay
            width: Overlay width in pixels

        Returns:
            int: Feature ID
        """
        self._assert_not_read_only("add measurement")
        overlay_id = self.drawings.add_measurement_overlay(
            name=name,
            points_wgs84=points_wgs84,
            description=description,
            color=color,
            width=width
        )
        self._refresh_catalog_for_layer(LayerIds.LINES)
        return overlay_id

    def clear_measurement_overlays(self) -> int:
        """
        Remove all measurement overlays from the Lines layer.

        Returns:
            int: Number of overlays deleted
        """
        self._assert_not_read_only("clear measurement overlays")
        removed = self.drawings.clear_measurement_overlays()
        if removed:
            self._refresh_catalog_for_layer(LayerIds.LINES)
        return removed

    def count_measurement_overlays(self) -> int:
        """Return number of active measurement overlays."""
        return self.drawings.count_measurement_overlays()

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
        self._assert_not_read_only("add search area")
        area_id = self.drawings.add_search_area(
            name, polygon_wgs84, team, status, priority, POA,
            terrain, search_method, color, notes
        )
        self._refresh_catalog_for_layer(LayerIds.SEARCH_AREAS)
        return area_id

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
        self._assert_not_read_only("add range ring")
        ring_id = self.drawings.add_range_ring(
            name, center_wgs84, radius_m, label, color,
            lpb_category, percentile
        )
        self._refresh_catalog_for_layer(LayerIds.RANGE_RINGS)
        return ring_id

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
        self._assert_not_read_only("add bearing line")
        bearing_id = self.drawings.add_bearing_line(
            name, origin_wgs84, bearing, distance_m, label, color
        )
        self._refresh_catalog_for_layer(LayerIds.BEARING_LINES)
        return bearing_id

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
        self._assert_not_read_only("add sector")
        sector_id = self.drawings.add_sector(
            name, center_wgs84, start_bearing, end_bearing, radius_m,
            priority, color
        )
        self._refresh_catalog_for_layer(LayerIds.SEARCH_SECTORS)
        return sector_id

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
        self._assert_not_read_only("add text label")
        label_id = self.drawings.add_text_label(
            text, location_wgs84, font_size, color, rotation
        )
        self._refresh_catalog_for_layer(LayerIds.TEXT_LABELS)
        return label_id

    # =========================================================================
    # Common Methods
    # =========================================================================

    def get_or_create_layer_group(self) -> QgsLayerTreeGroup:
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

        Clears the entire SAR Tracking group and all device colors atomically.
        """
        self._assert_not_read_only("clear layers")
        group = self.project.layerTreeRoot().findGroup(self.LAYER_GROUP_NAME)
        if group:
            self.project.layerTreeRoot().removeChildNode(group)

        # Clear shared device colors atomically
        self._shared_device_colors.clear()

        # Reset manager state (e.g., first_load flag in tracking manager)
        self.tracking.reset_state()
        self.markers.reset_state()
        self.drawings.reset_state()

    # =========================================================================
    # Phase 2 - Bulk Operations (CalTopo Console Support)
    # =========================================================================

    def bulk_delete_features(
        self,
        layer_id: str,
        feature_ids: List[int],
        confirmed: bool = False,
        updated_by: Optional[str] = None
    ) -> int:
        """
        Delete multiple features from a layer.

        LIFE-SAFETY CRITICAL: Requires explicit confirmation for large deletions.

        Args:
            layer_id: Layer identifier (from LayerIds)
            feature_ids: List of feature IDs to delete
            confirmed: Must be True if count > 10 (safety check)
            updated_by: Coordinator name for audit trail

        Returns:
            Number of features deleted

        Raises:
            ValueError: If not confirmed for large deletion
            LayerTransactionError: If deletion fails
        """
        from ..utils.exceptions import LayerTransactionError
        self._assert_not_read_only("bulk delete")

        # Validate
        if not feature_ids:
            return 0

        if len(feature_ids) > 10 and not confirmed:
            raise ValueError(
                f"Bulk delete of {len(feature_ids)} features requires explicit confirmation"
            )

        # Get appropriate manager based on layer_id
        # Search areas, range rings, bearing lines, text labels
        if layer_id in [LayerIds.SEARCH_AREAS, LayerIds.RANGE_RINGS,
                        LayerIds.BEARING_LINES, LayerIds.TEXT_LABELS,
                        LayerIds.LINES, LayerIds.SEARCH_SECTORS]:
            # Use DrawingLayerManager bulk delete methods
            if layer_id == LayerIds.SEARCH_AREAS:
                deleted = self.drawings.delete_search_areas(feature_ids, updated_by)
            elif layer_id == LayerIds.RANGE_RINGS:
                deleted = self.drawings.delete_range_rings(feature_ids, updated_by)
            elif layer_id == LayerIds.BEARING_LINES:
                deleted = self.drawings.delete_bearing_lines(feature_ids, updated_by)
            elif layer_id == LayerIds.TEXT_LABELS:
                deleted = self.drawings.delete_text_labels(feature_ids, updated_by)
            elif layer_id == LayerIds.LINES:
                deleted = self.drawings.delete_lines(feature_ids, updated_by)
            elif layer_id == LayerIds.SEARCH_SECTORS:
                deleted = self.drawings.delete_sectors(feature_ids, updated_by)
            else:
                raise ValueError(f"Unsupported layer_id: {layer_id}")

            # Refresh catalog
            self._refresh_catalog_for_layer(layer_id)
            return deleted

        # Prevent misuse on marker/tracking layers (must go through their managers)
        marker_layers = {
            LayerIds.MARKERS_IPP_LKP,
            LayerIds.MARKERS_CLUES,
            LayerIds.MARKERS_HAZARDS,
            LayerIds.MARKERS_CASUALTIES
        }
        tracking_layers = {LayerIds.CURRENT_ACTIVE, LayerIds.BREADCRUMBS}
        if layer_id in marker_layers or layer_id in tracking_layers:
            raise ValueError(f"Bulk delete for {layer_id} must use the dedicated manager API")

        # For other layers, fall back to direct layer manipulation
        layer = self.layer_manager.get_layer(layer_id)
        if not layer or not layer.isValid():
            raise RuntimeError(f"Layer {layer_id} not available")

        if not layer.startEditing():
            raise LayerTransactionError(
                layer_name=layer.name(),
                operation="start editing",
                details="Bulk delete operation"
            )

        deleted = 0
        try:
            for feature_id in feature_ids:
                if layer.deleteFeature(feature_id):
                    deleted += 1

            if not layer.commitChanges():
                errors = layer.commitErrors()
                raise RuntimeError(f"Commit failed: {', '.join(errors)}")

            print(f"[LayersController] Bulk deleted {deleted}/{len(feature_ids)} features from {layer_id}")

        except Exception as e:
            if layer.isEditable():
                layer.rollBack()
            raise LayerTransactionError(
                layer_name=layer.name(),
                operation="bulk delete features",
                details=str(e)
            ) from e
        finally:
            # CRITICAL: Ensure layer NEVER left in edit mode (even if exception during rollback)
            if layer and layer.isValid() and layer.isEditable():
                try:
                    layer.rollBack()
                except RuntimeError:
                    pass  # Layer already rolled back or deleted

            # Move catalog refresh outside transaction scope to ensure it happens
            # even if there are issues during commit
            try:
                self._refresh_catalog_for_layer(layer_id)
            except Exception as refresh_error:
                # Log but don't fail the operation if catalog refresh fails
                print(f"[LayersController] Warning: Catalog refresh failed for {layer_id}: {refresh_error}")

        return deleted

    # =========================================================================
    # Phase 2 - Move/Reorder Operations (CalTopo Console Support)
    # =========================================================================

    def move_search_area_to_section(
        self,
        feature_id: int,
        target_section: str,
        updated_by: Optional[str] = None
    ) -> bool:
        """
        Move search area between sections by updating status field.

        Args:
            feature_id: Search area feature ID
            target_section: Target section ('planning', 'active', 'reserve', 'completed')
            updated_by: Coordinator name for audit trail

        Returns:
            True on success

        Raises:
            ValueError: If target_section invalid
            LayerTransactionError: If update fails
        """
        # Map section names to status values
        section_to_status = {
            'planning': 'Planned',
            'active': 'InProgress',
            'active_teams': 'InProgress',
            'reserves': 'Planned',
            'reserve': 'Planned',
            'completed': 'Completed'
        }

        # Validate target_section
        if target_section not in section_to_status:
            raise ValueError(
                f"Invalid target_section: {target_section}. "
                f"Must be one of: {list(section_to_status.keys())}"
            )

        new_status = section_to_status[target_section]

        # Update status field using DrawingLayerManager
        success = self.drawings.update_search_area(
            feature_id=feature_id,
            updates={'status': new_status},
            updated_by=updated_by
        )

        if success:
            self._refresh_catalog_for_layer(LayerIds.SEARCH_AREAS)

        return success

    def reorder_features(
        self,
        layer_id: str,
        feature_ids_in_order: List[int],
        updated_by: Optional[str] = None
    ) -> bool:
        """
        Set display_order for features based on list order.

        Args:
            layer_id: Layer identifier (from LayerIds)
            feature_ids_in_order: Feature IDs in desired display order (top to bottom)
            updated_by: Coordinator name for audit trail

        Returns:
            True on success

        Raises:
            ValueError: If layer_id invalid or feature_ids empty
            LayerTransactionError: If update fails
        """
        self._assert_not_read_only("reorder features")
        from ..utils.exceptions import LayerTransactionError, LayerLockError

        # Validate
        if not feature_ids_in_order:
            raise ValueError("feature_ids_in_order cannot be empty")

        layer = self.layer_manager.get_layer(layer_id)
        if not layer or not layer.isValid():
            raise RuntimeError(f"Layer {layer_id} not available")

        # Check display_order field exists
        if layer.fields().indexFromName('display_order') == -1:
            raise ValueError(f"Layer {layer_id} does not have display_order field")

        if layer.isEditable():
            raise LayerLockError(layer.name())

        # Start transaction
        if not layer.startEditing():
            raise LayerTransactionError(
                layer_name=layer.name(),
                operation="start editing",
                details="Reorder features"
            )

        try:
            # Set display_order = index for each feature
            field_index = layer.fields().indexFromName('display_order')
            updated_count = 0

            for order, feature_id in enumerate(feature_ids_in_order):
                # Verify feature exists
                feature = layer.getFeature(feature_id)
                if not feature.isValid():
                    print(f"[LayersController] Warning: Feature {feature_id} not found, skipping")
                    continue

                # Update display_order
                success = layer.changeAttributeValue(feature_id, field_index, order)
                if success:
                    updated_count += 1
                else:
                    print(f"[LayersController] Warning: Failed to update display_order for {feature_id}")

            # Commit changes
            if not layer.commitChanges():
                errors = layer.commitErrors()
                raise RuntimeError(f"Commit failed: {', '.join(errors)}")

            # Refresh catalog
            self._refresh_catalog_for_layer(layer_id)

            print(f"[LayersController] Reordered {updated_count} features in {layer_id}")
            return True

        except Exception as e:
            layer.rollBack()
            raise LayerTransactionError(
                layer_name=layer.name(),
                operation="reorder features",
                details=str(e)
            ) from e
        finally:
            if layer and layer.isValid() and layer.isEditable():
                try:
                    layer.rollBack()
                except RuntimeError:
                    pass

    # =========================================================================
    # Phase 2 - Visibility and Layer Management Helpers
    # =========================================================================

    def set_layer_visibility(
        self,
        layer_id: str,
        is_visible: bool
    ) -> bool:
        """
        Toggle layer visibility in QGIS layer tree.

        Updates both QGIS state and catalog cache.

        Args:
            layer_id: Layer identifier (from LayerIds)
            is_visible: True to show, False to hide

        Returns:
            True on success
        """
        layer = self.layer_manager.get_layer(layer_id)
        if not layer or not layer.isValid():
            return False

        # Get layer tree node
        root = self.project.layerTreeRoot()
        node = root.findLayer(layer.id())

        if node:
            node.setItemVisibilityChecked(is_visible)
            # Refresh catalog
            self._refresh_catalog_for_layer(layer_id)
            return True

        return False

    def get_all_diagnostics(self) -> Dict[str, Any]:
        """
        Aggregate diagnostics from all managers and catalog.

        Returns:
            Dict with diagnostic information from all components
        """
        diagnostics = {}

        # Catalog diagnostics
        if self.catalog:
            try:
                snapshot = self.catalog.get_catalog_snapshot()
                diagnostics['catalog'] = {
                    'status': 'operational',
                    'layer_count': snapshot.get('layer_count', 0),
                    'warnings': snapshot.get('warnings', [])
                }
            except Exception as e:
                diagnostics['catalog'] = {'status': 'error', 'error': str(e)}
        else:
            diagnostics['catalog'] = {'status': 'not_available'}

        # Manager diagnostics
        # Note: Managers would need get_diagnostics() methods for full implementation
        diagnostics['tracking'] = {'status': 'operational'}
        diagnostics['markers'] = {'status': 'operational'}
        diagnostics['drawings'] = {'status': 'operational'}

        return diagnostics

    def cleanup(self):
        """
        Clean up resources on plugin unload.

        CRITICAL: This is called from sartracker.py unload().
        Must clean up catalog first (it depends on other managers).
        """
        print("[LayersController] Starting cleanup...")

        # Clean up catalog FIRST (it depends on other managers)
        if hasattr(self, 'catalog') and self.catalog:
            try:
                self.catalog.cleanup()
            except Exception as e:
                print(f"[LayersController] Catalog cleanup error: {e}")
            self.catalog = None

        # MEMORY LEAK FIX: Clear shared device color cache (unbounded growth issue)
        # This dict accumulates entries for every device ever seen, but never removes them
        # Over 8-hour operations, this can grow to hundreds of orphaned entries
        if hasattr(self, '_shared_device_colors') and self._shared_device_colors:
            print(f"[LayersController] Clearing device color cache ({len(self._shared_device_colors)} entries)")
            self._shared_device_colors.clear()

        # LIFECYCLE FIX: Explicitly clear manager references for clean garbage collection
        # While Python GC should handle this, explicit cleanup is safer for life-safety systems
        try:
            if hasattr(self, 'tracking') and self.tracking:
                self.tracking = None
            if hasattr(self, 'markers') and self.markers:
                self.markers = None
            if hasattr(self, 'drawings') and self.drawings:
                self.drawings = None
            if hasattr(self, 'helicopters') and self.helicopters:
                self.helicopters = None
        except Exception as e:
            print(f"[LayersController] Manager cleanup error: {e}")

        print("[LayersController] Cleanup complete")
