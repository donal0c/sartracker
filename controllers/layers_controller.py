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

from typing import List, Dict, Optional, Any, Callable
import logging
from qgis.core import QgsProject, QgsPointXY, QgsLayerTreeGroup

from .layer_managers.tracking_manager import TrackingLayerManager
from .layer_managers.marker_manager import MarkerLayerManager
from .layer_managers.drawing_manager import DrawingLayerManager
from .layer_catalog import LayerCatalogService
from ..layers.helicopter_manager import HelicopterLayerManager
from ..layers import LayerManager as SchemaLayerManager, GroupNames, LayerIds
from ..utils.exceptions import LayerTransactionError, LayerLockError
from ..utils.notify import error as notify_error, warning as notify_warning


logger = logging.getLogger(__name__)


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
    CATALOG_RETRY_LIMIT = 2
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
            logger.info("Layer catalog service initialized successfully")
        except Exception as e:
            self.catalog = None
            logger.warning("Failed to initialize catalog service: %s", e)
            logger.warning("Plugin will continue without catalog (core functionality unaffected)")
            logger.exception("Layer catalog initialization error")

    def _assert_not_read_only(self, operation: str):
        """Raise if mission is finalized/read-only."""
        if self.layer_manager and self.layer_manager.is_read_only():
            raise LayerTransactionError("mission data", operation, details="Mission is finalized (read-only)")

    def _execute_manager_call(self, operation: str, func: Callable, *args, **kwargs):
        """
        Execute a manager call with consistent exception logging.

        Args:
            operation: Human-friendly operation description
            func: Callable to execute
        """
        try:
            return func(*args, **kwargs)
        except Exception as exc:
            logger.exception("LayersController %s failed: %s", operation, exc)
            self._notify_error("Layer Operation Failed", f"{operation} failed: {exc}")
            raise

    def _apply_layer_edit(self, layer, operation: str, edit_fn: Callable):
        """
        Apply edits to a QGIS layer within a safe transaction.

        Args:
            layer: Target QgsVectorLayer
            operation: Human-friendly description for error context
            edit_fn: Callable that performs edits when passed the layer
        """
        if not layer.startEditing():
            raise LayerTransactionError(
                layer_name=layer.name(),
                operation="start editing",
                details=operation
            )

        try:
            result = edit_fn(layer)

            if not layer.commitChanges():
                errors = layer.commitErrors()
                raise RuntimeError(
                    f"Commit failed: {', '.join(errors) if errors else 'Unknown error'}"
                )

            return result

        except Exception as exc:
            raise LayerTransactionError(
                layer_name=layer.name(),
                operation=operation,
                details=str(exc)
            ) from exc

        finally:
            if layer and layer.isValid() and layer.isEditable():
                try:
                    layer.rollBack()
                except RuntimeError:
                    pass

    def _run_task_or_sync(self, description: str, func: Callable[[], Any], task_id: Optional[str] = None):
        """
        Run a callable via TaskManager if available, otherwise synchronously.

        Args:
            description: Human-readable task description
            func: Callable to execute
            task_id: Optional task identifier for TaskManager tracking
        """
        task_manager = getattr(self, "task_manager", None)

        if not task_manager:
            return func()

        try:
            from qgis.core import QgsTask
        except Exception as exc:
            logger.warning("QgsTask unavailable for %s; running synchronously: %s", description, exc)
            return func()

        create_task = getattr(QgsTask, "fromFunction", None)
        if not create_task:
            logger.warning("QgsTask.fromFunction unavailable for %s; running synchronously", description)
            return func()

        def _runner(task):
            try:
                func()
                return True
            except Exception as exc:
                try:
                    task.setProperty("sartracker:error", str(exc))
                except Exception:
                    pass
                raise

        def _on_complete(task):
            logger.info("%s completed", description)

        def _on_error(task):
            error_details = None
            try:
                error_details = task.property("sartracker:error")
            except Exception:
                error_details = None
            message = error_details or "Unknown error"
            logger.error("%s failed: %s", description, message)
            self._notify_error("Background Task Failed", f"{description} failed: {message}")

        try:
            task = create_task(description, _runner)
        except Exception as exc:
            logger.warning("Failed to create task '%s': %s. Running synchronously.", description, exc)
            return func()

        assigned_id = task_id or f"layers_controller::{description.replace(' ', '_').lower()}"
        task_manager.start_task(task, on_complete=_on_complete, on_error=_on_error, task_id=assigned_id)
        return assigned_id

    def _notify(self, notify_func: Callable, title: str, message: str, duration: int = 6):
        """Send a message-bar notification via utils.notify helpers."""
        if not self.iface:
            logger.warning("Notification dropped (iface unavailable): %s - %s", title, message)
            return

        bar_getter = getattr(self.iface, "messageBar", None)
        bar = bar_getter() if callable(bar_getter) else None
        if not bar:
            logger.warning("Notification dropped (message bar unavailable): %s - %s", title, message)
            return

        try:
            notify_func(bar, title, message, duration=duration)
        except Exception as exc:
            logger.warning("Failed to deliver notification '%s': %s", title, exc)

    def _notify_error(self, title: str, message: str, duration: int = 6):
        """Convenience wrapper for error notifications."""
        self._notify(notify_error, title, message, duration=duration)

    def _notify_warning(self, title: str, message: str, duration: int = 6):
        """Convenience wrapper for warning notifications."""
        self._notify(notify_warning, title, message, duration=duration)

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
        return self._execute_manager_call(
            "update current positions",
            self.tracking.update_current_positions,
            positions
        )

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
        return self._execute_manager_call(
            "update breadcrumbs",
            self.tracking.update_breadcrumbs,
            positions,
            time_gap_minutes,
            processed_segments=processed_segments
        )

    # =========================================================================
    # Catalog Methods
    # =========================================================================

    def rescan_catalog(self, use_background: bool = True):
        """Force catalog to rescan all layers (HIGH-5)."""
        if not self.catalog:
            return

        if use_background:
            self._run_task_or_sync(
                "Layer Catalog Rescan",
                lambda: self._call_catalog_operation("rescan layers", self.catalog.rescan_layers),
                task_id="layers_controller::catalog_rescan"
            )
        else:
            self._call_catalog_operation("rescan layers", self.catalog.rescan_layers)

    def _refresh_catalog_for_layer(self, layer_id: str):
        """Helper to refresh catalog feature count (HIGH-6)."""
        if self.catalog:
            self._call_catalog_operation(
                f"refresh layer {layer_id}",
                self.catalog.refresh_layer,
                layer_id,
                full=False
            )

    def _call_catalog_operation(self, operation: str, func: Callable, *args, **kwargs) -> bool:
        """Execute catalog operations with retries."""
        attempts = self.CATALOG_RETRY_LIMIT
        if attempts < 1:
            attempts = 1

        last_exc = None
        for attempt in range(1, attempts + 1):
            try:
                func(*args, **kwargs)
                if attempt > 1:
                    logger.info(
                        "Catalog operation %s succeeded on attempt %s/%s",
                        operation,
                        attempt,
                        attempts
                    )
                return True
            except Exception as exc:
                last_exc = exc
                if attempt < attempts:
                    logger.warning(
                        "Catalog operation %s failed (attempt %s/%s): %s",
                        operation,
                        attempt,
                        attempts,
                        exc
                    )
                else:
                    logger.exception(
                        "Catalog operation %s failed after %s attempts: %s",
                        operation,
                        attempts,
                        exc
                    )
                    self._notify_warning(
                        "Catalog Update",
                        f"{operation} failed after {attempts} attempts: {exc}"
                    )
        return False

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
        marker_id = self._execute_manager_call(
            "add IPP/LKP marker",
            self.markers.add_ipp_lkp,
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
        clue_id = self._execute_manager_call(
            "add clue marker",
            self.markers.add_clue,
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
        hazard_id = self._execute_manager_call(
            "add hazard marker",
            self.markers.add_hazard,
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
        casualty_id = self._execute_manager_call(
            "add casualty marker",
            self.markers.add_casualty,
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
        return self._execute_manager_call("list markers", self.markers.list_markers)

    def get_marker_feature(self, marker_type: str, marker_id: str):
        """
        Fetch a marker feature by type/id.

        Args:
            marker_type: 'ipp_lkp', 'clue', 'hazard', or 'casualty'
            marker_id: UUID string stored in 'id' attribute
        """
        return self._execute_manager_call(
            "get marker feature",
            self.markers.get_marker_feature,
            marker_type,
            marker_id
        )

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
        updated = self._execute_manager_call(
            "update marker",
            self.markers.update_marker,
            marker_type,
            marker_id,
            updates,
            updated_by=updated_by
        )
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
        deleted = self._execute_manager_call(
            "delete marker",
            self.markers.delete_marker,
            marker_type,
            marker_id
        )
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
        line_id = self._execute_manager_call(
            "add line",
            self.drawings.add_line,
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
        overlay_id = self._execute_manager_call(
            "add measurement overlay",
            self.drawings.add_measurement_overlay,
            name,
            points_wgs84,
            description,
            color,
            width
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
        removed = self._execute_manager_call(
            "clear measurement overlays",
            self.drawings.clear_measurement_overlays
        )
        if removed:
            self._refresh_catalog_for_layer(LayerIds.LINES)
        return removed

    def count_measurement_overlays(self) -> int:
        """Return number of active measurement overlays."""
        return self._execute_manager_call(
            "count measurement overlays",
            self.drawings.count_measurement_overlays
        )

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
        area_id = self._execute_manager_call(
            "add search area",
            self.drawings.add_search_area,
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
        ring_id = self._execute_manager_call(
            "add range ring",
            self.drawings.add_range_ring,
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
        bearing_id = self._execute_manager_call(
            "add bearing line",
            self.drawings.add_bearing_line,
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
        sector_id = self._execute_manager_call(
            "add sector",
            self.drawings.add_sector,
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
        label_id = self._execute_manager_call(
            "add text label",
            self.drawings.add_text_label,
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
        return self._execute_manager_call(
            "get or create layer group",
            self.tracking.get_or_create_layer_group
        )

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

        def _delete_features_transaction(target_layer):
            deleted_count = 0
            for feature_id in feature_ids:
                if target_layer.deleteFeature(feature_id):
                    deleted_count += 1
            return deleted_count

        deleted = self._apply_layer_edit(
            layer,
            "bulk delete features",
            _delete_features_transaction
        )

        logger.info("Bulk deleted %s/%s features from %s", deleted, len(feature_ids), layer_id)
        self._refresh_catalog_for_layer(layer_id)
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
        success = self._execute_manager_call(
            "update search area status",
            self.drawings.update_search_area,
            feature_id,
            {'status': new_status},
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
        # Validate
        if not feature_ids_in_order:
            raise ValueError("feature_ids_in_order cannot be empty")

        layer = self.layer_manager.get_layer(layer_id)
        if not layer or not layer.isValid():
            raise RuntimeError(f"Layer {layer_id} not available")

        # Check display_order field exists
        field_index = layer.fields().indexFromName('display_order')
        if field_index == -1:
            raise ValueError(f"Layer {layer_id} does not have display_order field")

        if layer.isEditable():
            raise LayerLockError(layer.name())

        def _reorder_transaction(target_layer):
            updated_count = 0
            for order, feature_id in enumerate(feature_ids_in_order):
                feature = target_layer.getFeature(feature_id)
                if not feature.isValid():
                    logger.warning(
                        "Feature %s not found while reordering layer %s; skipping",
                        feature_id,
                        layer_id
                    )
                    continue

                success = target_layer.changeAttributeValue(feature_id, field_index, order)
                if success:
                    updated_count += 1
                else:
                    logger.warning(
                        "Failed to update display_order for feature %s in layer %s",
                        feature_id,
                        layer_id
                    )
            return updated_count

        updated_count = self._apply_layer_edit(
            layer,
            "reorder features",
            _reorder_transaction
        )

        self._refresh_catalog_for_layer(layer_id)
        logger.info("Reordered %s features in %s", updated_count, layer_id)
        return True

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
        logger.info("LayersController cleanup started")

        # Clean up catalog FIRST (it depends on other managers)
        if hasattr(self, 'catalog') and self.catalog:
            try:
                self.catalog.cleanup()
            except Exception as e:
                logger.exception("Catalog cleanup error: %s", e)
            self.catalog = None

        # MEMORY LEAK FIX: Clear shared device color cache (unbounded growth issue)
        # This dict accumulates entries for every device ever seen, but never removes them
        # Over 8-hour operations, this can grow to hundreds of orphaned entries
        if hasattr(self, '_shared_device_colors') and self._shared_device_colors:
            logger.info("Clearing device color cache (%s entries)", len(self._shared_device_colors))
            self._shared_device_colors.clear()

        # LIFECYCLE FIX: Call cleanup() on managers before nullifying references
        # This ensures background tasks are cancelled, signals disconnected, etc.
        # Critical: tracking manager has background tasks that must be cancelled
        try:
            if hasattr(self, 'tracking') and self.tracking:
                try:
                    self.tracking.cleanup()
                except Exception as e:
                    logger.warning("Tracking manager cleanup error: %s", e)
                self.tracking = None
            if hasattr(self, 'markers') and self.markers:
                try:
                    self.markers.cleanup()
                except Exception as e:
                    logger.warning("Markers manager cleanup error: %s", e)
                self.markers = None
            if hasattr(self, 'drawings') and self.drawings:
                try:
                    self.drawings.cleanup()
                except Exception as e:
                    logger.warning("Drawings manager cleanup error: %s", e)
                self.drawings = None
            if hasattr(self, 'helicopters') and self.helicopters:
                # helicopters is a module-level manager, check for cleanup method
                if hasattr(self.helicopters, 'cleanup'):
                    try:
                        self.helicopters.cleanup()
                    except Exception as e:
                        logger.warning("Helicopters manager cleanup error: %s", e)
                self.helicopters = None
        except Exception as e:
            logger.exception("Manager cleanup error: %s", e)

        logger.info("LayersController cleanup complete")
