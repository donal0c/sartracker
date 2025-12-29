# -*- coding: utf-8 -*-
"""
Map Tools Controller for SAR Tracker.

Manages all map tools: marker placement, drawing tools, measurement, and GPX import.
Consolidates tool initialization, signal wiring, and event handlers that were
previously scattered across sartracker.py.

Phase 7 - Map Tools Controller Extraction:
- Marker tool setup and click handlers
- Drawing tools (line, polygon, bearing, range rings) setup and completion handlers
- Measurement tool and overlay persistence
- GPX import and folder watch functionality
- Tool registry lifecycle management

Qt5/Qt6 Compatible: Uses qgis.PyQt and qt_compat for all Qt imports.

LIFE-SAFETY CRITICAL: Map tools are used during active rescue operations.
All defensive patterns from the original implementation are preserved.
Coordinate validation is mandatory for all marker operations.
"""

import math
import traceback
from datetime import datetime
from importlib import import_module
from pathlib import Path
from typing import Optional, Callable, Dict, Any, TYPE_CHECKING

from qgis.PyQt.QtCore import QObject, pyqtSignal
from qgis.PyQt.QtWidgets import QMessageBox

from qgis.core import (
    QgsPointXY,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsProject,
    QgsRectangle,
)

from ..utils.qt_compat import (
    dialog_exec, DialogAccepted,
    MessageBoxYes, MessageBoxNo,
)
from ..utils.notify import info, warning, error, success

# sip.isdeleted import pattern (Qt5/Qt6 compatible)
try:
    from qgis.PyQt.sip import isdeleted as sip_isdeleted
except ImportError:
    try:
        import sip
        sip_isdeleted = sip.isdeleted
    except Exception:
        def sip_isdeleted(_obj):
            return False

if TYPE_CHECKING:
    from qgis.gui import QgisInterface
    from ..controllers.layers_controller import LayersController
    from ..controllers.marker_controller import MarkerController
    from ..layers import LayerManager
    from ..ui.sar_panel import SARPanel
    from ..utils.error_handler import ErrorHandler
    from ..maptools.tool_registry import ToolRegistry


class MapToolsController(QObject):
    """
    Controller for all map tools: markers, drawing, measurement, and GPX.

    Responsibilities:
    - Initialize and manage all map tool instances
    - Handle tool activation/deactivation via ToolRegistry
    - Process marker placement clicks and CRUD operations
    - Handle drawing tool completion callbacks
    - Manage measurement overlays
    - Handle GPX import and folder watching
    - Clean up all tools on unload

    Dependencies are injected via __init__ or setters to avoid plugin globals.

    LIFE-SAFETY CRITICAL: Coordinate validation is mandatory for all marker
    operations. Invalid coordinates must be rejected with clear user feedback.
    """

    # Signals for UI updates
    tool_activated = pyqtSignal(str)  # tool_name
    tool_deactivated = pyqtSignal(str)  # tool_name
    marker_placed = pyqtSignal()  # After successful marker placement
    measurement_complete = pyqtSignal(float, float, str)  # distance_m, bearing, cardinal (str)

    def __init__(
        self,
        iface: "QgisInterface",
        layers_controller: Optional["LayersController"] = None,
        marker_controller: Optional["MarkerController"] = None,
        layer_manager: Optional["LayerManager"] = None,
        sar_panel: Optional["SARPanel"] = None,
        error_handler: Optional["ErrorHandler"] = None,
        ingest_attachment: Optional[Callable[[Optional[str]], Optional[str]]] = None,
        get_mission_directory: Optional[Callable[[], Optional[str]]] = None,
        refresh_mission_logs_window: Optional[Callable[[], None]] = None,
        show_diagnostics: Optional[Callable[[], None]] = None,
        is_unloading: Optional[Callable[[], bool]] = None,
        is_app_quitting: Optional[Callable[[], bool]] = None,
        log_exception: Optional[Callable[[str, Exception], None]] = None,
        parent: Optional[QObject] = None
    ):
        """
        Initialize map tools controller.

        Args:
            iface: QGIS interface
            layers_controller: LayersController for layer operations
            marker_controller: MarkerController for marker CRUD (optional)
            layer_manager: LayerManager for SAR project state
            sar_panel: SARPanel for UI updates
            error_handler: ErrorHandler for error reporting
            ingest_attachment: Callback to process attachment file paths
            get_mission_directory: Callback to get mission directory path
            refresh_mission_logs_window: Callback to refresh Mission Logs window
            show_diagnostics: Callback to show diagnostics dialog
            is_unloading: Callback to check if plugin is unloading
            is_app_quitting: Callback to check if app is quitting
            log_exception: Callback to log exceptions
            parent: Optional QObject parent
        """
        super().__init__(parent)

        self.iface = iface
        self.layers_controller = layers_controller
        self.marker_controller = marker_controller
        self.layer_manager = layer_manager
        self.sar_panel = sar_panel
        self.error_handler = error_handler
        self._ingest_attachment = ingest_attachment or (lambda x: x)
        self._get_mission_directory = get_mission_directory or (lambda: None)
        self._refresh_mission_logs_window = refresh_mission_logs_window or (lambda: None)
        self._show_diagnostics = show_diagnostics or (lambda: None)
        self._is_unloading_cb = is_unloading or (lambda: False)
        self._is_app_quitting_cb = is_app_quitting or (lambda: False)
        self._log_exception = log_exception

        # Shutdown flag for async callbacks
        self._is_shutting_down = False

        # Tool instances - initialized by init()
        self.marker_tool = None
        self.measure_tool = None
        self.line_tool = None
        self.range_ring_tool = None
        self.bearing_tool = None
        self.polygon_tool = None
        self.tool_registry: Optional["ToolRegistry"] = None

        # Marker state
        self.current_marker_type: Optional[str] = None

        # Coordinate systems
        self.wgs84 = QgsCoordinateReferenceSystem("EPSG:4326")
        # EPSG:2157 (Irish Transverse Mercator / ITM) - modern Irish Grid
        self.itm = QgsCoordinateReferenceSystem("EPSG:2157")

        # Logger reference (set during init if available)
        self._logger = None

    # ------------------------------------------------------------------
    # Dependency Setters (for late binding)
    # ------------------------------------------------------------------

    def set_layers_controller(self, controller: "LayersController"):
        """Set layers controller (for late binding after initialization)."""
        self.layers_controller = controller

    def set_marker_controller(self, controller: "MarkerController"):
        """Set marker controller (for late binding after initialization)."""
        self.marker_controller = controller

    def set_sar_panel(self, panel: "SARPanel"):
        """Set SAR panel (for late binding after initialization)."""
        self.sar_panel = panel

    def set_error_handler(self, handler: "ErrorHandler"):
        """Set error handler (for late binding after initialization)."""
        self.error_handler = handler

    # ------------------------------------------------------------------
    # Initialization
    # ------------------------------------------------------------------

    def init(self) -> bool:
        """
        Initialize all map tools.

        Returns:
            True if initialization succeeded (at least basic tools loaded),
            False if critical failure.

        SAFETY: Tool initialization failures are non-fatal for the plugin.
        If a tool fails to load, the corresponding button will be disabled.
        """
        try:
            # Initialize marker map tool
            try:
                from ..maptools.marker_tool import MarkerMapTool
                self.marker_tool = MarkerMapTool(self.iface.mapCanvas(), self.iface)
                self.marker_tool.marker_clicked.connect(self._on_marker_clicked)
                print("[MapToolsController] MarkerMapTool initialized")
            except Exception as e:
                self.marker_tool = None
                print(f"[MapToolsController] ERROR initializing MarkerMapTool: {e}")
                warning(
                    self.iface.messageBar(),
                    "SAR Tracker",
                    f"Marker tool failed to load: {e}",
                    duration=5
                )

            # Initialize measure tool
            try:
                from ..maptools.measure_tool import MeasureTool
                # BUG-FIX: Pass iface for notification support
                self.measure_tool = MeasureTool(self.iface.mapCanvas(), self.iface)
                self.measure_tool.measurement_complete.connect(self._on_measurement_complete)
                print("[MapToolsController] MeasureTool initialized")
            except Exception as e:
                self.measure_tool = None
                print(f"[MapToolsController] ERROR initializing MeasureTool: {e}")
                warning(
                    self.iface.messageBar(),
                    "SAR Tracker",
                    f"Measure tool failed to load: {e}",
                    duration=5
                )

            # Initialize drawing tools using helper
            self._init_drawing_tool(
                tool_attr="line_tool",
                import_path="..maptools",
                class_name="LineTool",
                ctor=lambda cls: cls(self.iface.mapCanvas(), self.layers_controller),
                hooks=lambda tool: (
                    tool.drawing_complete.connect(self._on_line_complete),
                    tool.drawing_cancelled.connect(self._on_drawing_cancelled),
                    tool.drawing_error.connect(
                        lambda e: self._handle_drawing_error(e, "Line drawing")
                    )
                )
            )

            self._init_drawing_tool(
                tool_attr="range_ring_tool",
                import_path="..maptools",
                class_name="RangeRingTool",
                ctor=lambda cls: cls(self.iface.mapCanvas(), self.layers_controller, self.iface),
                hooks=lambda tool: (
                    tool.drawing_complete.connect(self._on_range_rings_complete),
                    tool.drawing_cancelled.connect(self._on_drawing_cancelled),
                    tool.drawing_error.connect(
                        lambda e: self._handle_drawing_error(e, "Range ring")
                    )
                )
            )

            self._init_drawing_tool(
                tool_attr="bearing_tool",
                import_path="..maptools",
                class_name="BearingTool",
                ctor=lambda cls: cls(self.iface.mapCanvas(), self.layers_controller, self.iface),
                hooks=lambda tool: (
                    tool.drawing_complete.connect(self._on_bearing_complete),
                    tool.drawing_cancelled.connect(self._on_drawing_cancelled),
                    tool.drawing_error.connect(
                        lambda e: self._handle_drawing_error(e, "Bearing line")
                    )
                )
            )

            self._init_drawing_tool(
                tool_attr="polygon_tool",
                import_path="..maptools",
                class_name="PolygonTool",
                ctor=lambda cls: cls(self.iface.mapCanvas(), self.layers_controller, self.iface),
                hooks=lambda tool: (
                    tool.drawing_complete.connect(self._on_polygon_complete),
                    tool.drawing_cancelled.connect(self._on_drawing_cancelled),
                    tool.drawing_error.connect(
                        lambda e: self._handle_drawing_error(e, "Polygon drawing")
                    )
                )
            )

            # Initialize Tool Registry
            self._init_tool_registry()

            print("[MapToolsController] Initialization complete")
            return True

        except Exception as exc:
            if self._log_exception:
                self._log_exception("MapToolsController.init", exc)
            print(f"[MapToolsController] CRITICAL ERROR during init: {exc}")
            traceback.print_exc()
            return False

    def _init_drawing_tool(self, tool_attr: str, import_path: str, class_name: str, ctor, hooks):
        """
        Initialize a drawing tool with error handling.

        Args:
            tool_attr: Attribute name to store tool instance
            import_path: Module import path
            class_name: Class name to import
            ctor: Constructor lambda taking class
            hooks: Lambda to connect signals after construction
        """
        resolved_name = None
        try:
            package_name = __package__ or (__name__.rpartition('.')[0] or __name__)
            if not package_name or package_name == "__main__":
                package_name = Path(__file__).resolve().parent.parent.name

            # First attempt: relative import using package context (preferred)
            try:
                module = import_module(import_path, package=package_name)
                resolved_name = f"{package_name}{import_path}"
            except ModuleNotFoundError:
                # Fallback: build absolute module path manually
                if import_path.startswith('.'):
                    resolved_name = f"{package_name}{import_path}"
                else:
                    resolved_name = import_path
                module = import_module(resolved_name)

            cls = getattr(module, class_name)
            tool = ctor(cls)
            hooks(tool)
            setattr(self, tool_attr, tool)
            print(f"[MapToolsController] {class_name} initialized")

        except Exception as e:
            setattr(self, tool_attr, None)
            warning(
                self.iface.messageBar(),
                "SAR Tracker",
                f"{class_name} failed to load: {e}",
                duration=5
            )
            print(f"[MapToolsController] ERROR initializing {class_name} from {resolved_name or import_path}: {e}")
            traceback.print_exc()

    def _init_tool_registry(self):
        """Initialize the tool registry and register all available tools."""
        try:
            from ..maptools import ToolRegistry
            self.tool_registry = ToolRegistry(self.iface.mapCanvas(), self.iface)

            # Only register tools that successfully loaded
            if self.line_tool:
                self.tool_registry.register_tool('line', self.line_tool)
            if self.range_ring_tool:
                self.tool_registry.register_tool('range_rings', self.range_ring_tool)
            if self.bearing_tool:
                self.tool_registry.register_tool('bearing', self.bearing_tool)
            if self.polygon_tool:
                self.tool_registry.register_tool('polygon', self.polygon_tool)

            # Connect registry signals
            self.tool_registry.tool_activated.connect(self._on_tool_activated)
            self.tool_registry.tool_deactivated.connect(self._on_tool_deactivated)

            print("[MapToolsController] ToolRegistry initialized with tools: " +
                  str(self.tool_registry.get_registered_tools()))

        except Exception as e:
            self.tool_registry = None
            error(
                self.iface.messageBar(),
                "SAR Tracker - Drawing Tools Unavailable",
                f"Drawing tools failed to initialize: {e}. Other features remain available.",
                duration=0  # Persistent
            )
            print(f"[MapToolsController] ERROR initializing ToolRegistry: {e}")
            traceback.print_exc()

    # ------------------------------------------------------------------
    # Validation Helpers
    # ------------------------------------------------------------------

    def _is_number(self, value) -> bool:
        """Return True if value can be interpreted as a finite float (excludes bool)."""
        if value is None or isinstance(value, bool):
            return False
        try:
            return math.isfinite(float(value))
        except Exception:
            return False

    def _valid_latlon(self, lat, lon) -> bool:
        """
        Validate latitude/longitude coordinates.

        LIFE-SAFETY CRITICAL: Invalid coordinates must be rejected.
        """
        if not self._is_number(lat) or not self._is_number(lon):
            return False
        lat_f = float(lat)
        lon_f = float(lon)
        return -90.0 <= lat_f <= 90.0 and -180.0 <= lon_f <= 180.0

    def _should_skip_callback(self) -> bool:
        """Check if callbacks should be skipped (unloading or quitting)."""
        return self._is_shutting_down or self._is_unloading_cb() or self._is_app_quitting_cb()

    # ------------------------------------------------------------------
    # Marker Tool Methods
    # ------------------------------------------------------------------

    def on_add_poi_requested(self):
        """Handle Add IPP/LKP button click from SAR Panel."""
        # Deactivate any drawing tools first
        if self.tool_registry:
            self.tool_registry.deactivate_current()

        self.current_marker_type = 'ipp_lkp'
        if self.marker_tool:
            self.iface.mapCanvas().setMapTool(self.marker_tool)
            info(
                self.iface.messageBar(),
                "SAR Tracker",
                "Click on map to add IPP/LKP location",
                duration=3
            )
        else:
            warning(
                self.iface.messageBar(),
                "SAR Tracker",
                "Marker tool not available",
                duration=4
            )

    def on_add_clue_requested(self):
        """Handle Add Clue button click from SAR Panel."""
        if self.tool_registry:
            self.tool_registry.deactivate_current()

        self.current_marker_type = 'clue'
        if self.marker_tool:
            self.iface.mapCanvas().setMapTool(self.marker_tool)
            info(
                self.iface.messageBar(),
                "SAR Tracker",
                "Click on map to add Clue location",
                duration=3
            )
        else:
            warning(
                self.iface.messageBar(),
                "SAR Tracker",
                "Marker tool not available",
                duration=4
            )

    def on_add_casualty_requested(self):
        """Handle Add Casualty button click from SAR Panel."""
        if self.tool_registry:
            self.tool_registry.deactivate_current()

        self.current_marker_type = 'casualty'
        if self.marker_tool:
            self.iface.mapCanvas().setMapTool(self.marker_tool)
            info(
                self.iface.messageBar(),
                "SAR Tracker - CRITICAL",
                "Click on map to add Casualty location (found injured/deceased person)",
                duration=5
            )
        else:
            warning(
                self.iface.messageBar(),
                "SAR Tracker",
                "Marker tool not available",
                duration=4
            )

    def on_add_hazard_requested(self):
        """Handle Add Hazard button click from SAR Panel."""
        if self.tool_registry:
            self.tool_registry.deactivate_current()

        self.current_marker_type = 'hazard'
        if self.marker_tool:
            self.iface.mapCanvas().setMapTool(self.marker_tool)
            info(
                self.iface.messageBar(),
                "SAR Tracker",
                "Click on map to add Hazard location",
                duration=3
            )
        else:
            warning(
                self.iface.messageBar(),
                "SAR Tracker",
                "Marker tool not available",
                duration=4
            )

    def _on_marker_clicked(self, lat, lon, easting, northing):
        """
        Handle map click from MarkerMapTool.

        Args:
            lat: Latitude (WGS84)
            lon: Longitude (WGS84)
            easting: Irish Grid Easting (ITM)
            northing: Irish Grid Northing (ITM)

        LIFE-SAFETY CRITICAL: Validates coordinates before creating marker.
        """
        # HIGH FIX: Guard against callbacks during shutdown
        if self._should_skip_callback():
            return

        if not self._valid_latlon(lat, lon):
            warning(
                self.iface.messageBar(),
                "Markers",
                "Invalid coordinates from map click; marker not added.",
                duration=4
            )
            return

        if self.marker_controller:
            self.marker_controller.handle_new_marker(
                self.current_marker_type or "ipp_lkp",
                lat,
                lon,
                easting,
                northing
            )
        else:
            warning(
                self.iface.messageBar(),
                "Markers",
                "Marker controller unavailable.",
                duration=4
            )

        # Deactivate marker tool (return to pan/zoom)
        if self.marker_tool:
            try:
                self.iface.mapCanvas().unsetMapTool(self.marker_tool)
            except Exception:
                pass  # Canvas may be unavailable during shutdown
        self.current_marker_type = None

        # HIGH FIX: Guard these operations against shutdown
        if not self._should_skip_callback():
            self._refresh_mission_logs_window()
            self.marker_placed.emit()

    def on_marker_edit_requested(self, marker_type: str, marker_id: str):
        """Handle marker edit requests originating from the Marker Log."""
        # Import here to avoid circular imports
        try:
            from ..ui.marker_dialog import MarkerDialog
        except ImportError:
            MarkerDialog = None

        if not self.layers_controller or MarkerDialog is None:
            warning(
                self.iface.messageBar(),
                "Markers",
                "Marker editing is unavailable.",
                duration=4
            )
            return

        try:
            feature = self.layers_controller.get_marker_feature(marker_type, marker_id)
            if not feature:
                warning(
                    self.iface.messageBar(),
                    "Markers",
                    "Selected marker no longer exists.",
                    duration=4
                )
                return

            lat, lon, easting, northing = self._extract_marker_coordinates(feature)
            existing_data = self._build_marker_dialog_payload(feature, marker_type)
            dialog = MarkerDialog(
                lat, lon, easting, northing,
                self.iface.mainWindow(),
                existing_data=existing_data
            )

            if dialog_exec(dialog) == DialogAccepted:
                marker_data = dialog.get_marker_data()
                marker_data['attachment_path'] = self._ingest_attachment(
                    marker_data.get('attachment_path')
                )
                updates = self._build_marker_update_payload(marker_type, marker_data)
                self.layers_controller.update_marker(
                    marker_type,
                    marker_id,
                    updates,
                    updated_by=marker_data.get('updated_by')
                )
                success(
                    self.iface.messageBar(),
                    "Markers",
                    f"{marker_data['name']} updated successfully",
                    duration=3
                )
                self._refresh_mission_logs_window()

        except Exception as exc:
            error(
                self.iface.messageBar(),
                "Markers",
                f"Failed to update marker: {exc}",
                duration=5
            )
            if self._log_exception:
                self._log_exception("on_marker_edit_requested", exc)

    def on_marker_delete_requested(self, marker_type: str, marker_id: str):
        """Handle marker deletion requests from Marker Log."""
        if not self.layers_controller:
            return

        confirm = QMessageBox.question(
            self.iface.mainWindow(),
            "Delete Marker",
            "Are you sure you want to delete this marker?\nThis action cannot be undone.",
            MessageBoxYes | MessageBoxNo,
            MessageBoxNo
        )
        if confirm != MessageBoxYes:
            return

        try:
            self.layers_controller.delete_marker(marker_type, marker_id)
            success(
                self.iface.messageBar(),
                "Markers",
                "Marker deleted.",
                duration=2
            )
            self._refresh_mission_logs_window()
        except Exception as exc:
            error(
                self.iface.messageBar(),
                "Markers",
                f"Failed to delete marker: {exc}",
                duration=5
            )
            if self._log_exception:
                self._log_exception("on_marker_delete_requested", exc)

    def on_marker_zoom_requested(self, lat: float, lon: float):
        """Zoom map canvas to marker coordinates."""
        if not self._valid_latlon(lat, lon):
            warning(
                self.iface.messageBar(),
                "Markers",
                "Marker coordinates are invalid; cannot zoom.",
                duration=4
            )
            return

        try:
            dest_crs = self.iface.mapCanvas().mapSettings().destinationCrs()
            source_crs = QgsCoordinateReferenceSystem(4326)
            transform = QgsCoordinateTransform(source_crs, dest_crs, QgsProject.instance())
            point = transform.transform(QgsPointXY(lon, lat))
            canvas = self.iface.mapCanvas()
            canvas.setCenter(point)
            canvas.zoomScale(2500)
            canvas.refresh()
        except Exception as exc:
            warning(
                self.iface.messageBar(),
                "Markers",
                f"Could not zoom to marker: {exc}",
                duration=4
            )
            if self._log_exception:
                self._log_exception("on_marker_zoom_requested", exc)

    def _extract_marker_coordinates(self, feature) -> tuple:
        """
        Return (lat, lon, easting, northing) with validation.

        BUG-078 FIX: Changed from returning Null Island (0,0) fallback to raising
        ValueError. Silent fallback to (0,0) is LIFE-SAFETY CRITICAL as it could
        direct rescue teams to the wrong continent.

        Args:
            feature: QgsFeature to extract coordinates from

        Returns:
            tuple: (lat, lon, easting, northing)

        Raises:
            ValueError: If feature is None, invalid, or has missing/invalid coordinates
        """
        import logging
        logger = logging.getLogger(__name__)

        # BUG-078 FIX: Raise instead of returning Null Island coordinates
        if feature is None:
            logger.error("BUG-078: _extract_marker_coordinates called with None feature")
            raise ValueError("Cannot extract coordinates: feature is None")

        try:
            if not feature.isValid():
                logger.error("BUG-078: _extract_marker_coordinates called with invalid feature")
                raise ValueError("Cannot extract coordinates: feature is invalid")
        except AttributeError:
            # isValid() might not exist on some feature types - continue with extraction
            pass

        # Safely extract field values
        lat = None
        lon = None
        easting = None
        northing = None

        try:
            lat = feature["lat"]
            lon = feature["lon"]
            easting = feature["irish_grid_e"]
            northing = feature["irish_grid_n"]
        except (KeyError, TypeError) as field_err:
            logger.warning("BUG-078: Could not extract marker fields: %s", field_err)

        # Fallback to geometry if coordinate fields are missing
        if (lat is None or lon is None) and feature.geometry() and not feature.geometry().isEmpty():
            try:
                point = feature.geometry().asPoint()
                if point:
                    extracted_lat = point.y()
                    extracted_lon = point.x()
                    # Validate extracted coordinates are in reasonable range
                    if -90 <= extracted_lat <= 90 and -180 <= extracted_lon <= 180:
                        lat = lat if lat is not None else extracted_lat
                        lon = lon if lon is not None else extracted_lon
                        logger.info(
                            "BUG-078: Extracted coordinates from geometry: lat=%.6f, lon=%.6f",
                            lat, lon
                        )
                    else:
                        logger.warning(
                            "BUG-078: Geometry coordinates out of range: lat=%.6f, lon=%.6f",
                            extracted_lat, extracted_lon
                        )
            except Exception as geom_err:
                logger.warning("BUG-078: Failed to extract from geometry: %s", geom_err)

        # BUG-078 FIX: NEVER return Null Island (0,0) silently
        # This is LIFE-SAFETY CRITICAL - could send rescuers to wrong location
        if lat is None or lon is None:
            raise ValueError(
                "Cannot extract coordinates: lat/lon fields are missing and "
                "geometry extraction failed"
            )

        # Validate coordinate ranges
        if not (-90 <= lat <= 90):
            raise ValueError(f"Latitude {lat} out of valid range [-90, 90]")
        if not (-180 <= lon <= 180):
            raise ValueError(f"Longitude {lon} out of valid range [-180, 180]")

        # Check for explicit (0,0) which is valid only if explicitly set
        if lat == 0.0 and lon == 0.0:
            # Only allow if these were explicitly stored values (not None fallbacks)
            if feature["lat"] is None or feature["lon"] is None:
                raise ValueError(
                    "Invalid coordinates: (0, 0) detected but fields were not "
                    "explicitly set. This may indicate data corruption."
                )
            logger.warning(
                "BUG-078: Marker has explicit (0,0) coordinates - verify this is intentional"
            )

        # Irish Grid can be None (optional), return as-is
        return lat, lon, easting, northing

    def _build_marker_dialog_payload(self, feature, marker_type: str) -> Dict[str, Any]:
        """Build payload passed to MarkerDialog for edit mode."""
        payload: Dict[str, Any] = {}
        for field in feature.fields():
            payload[field.name()] = feature[field.name()]
        payload["type"] = marker_type
        return payload

    def _build_marker_update_payload(self, marker_type: str, marker_data: Dict[str, Any]) -> Dict[str, Any]:
        """Prepare attribute updates per marker type."""
        updates: Dict[str, Any] = {
            "name": marker_data.get("name", ""),
            "description": marker_data.get("description", ""),
            "updated_by": marker_data.get("updated_by", ""),
            "coordinator_ids": marker_data.get("coordinator_ids", ""),
            "attachment_path": marker_data.get("attachment_path", "")
        }

        if marker_type == "ipp_lkp":
            updates["subject_category"] = marker_data.get("subject_category", "")
        elif marker_type == "clue":
            updates["clue_type"] = marker_data.get("clue_type", "")
            updates["confidence"] = marker_data.get("confidence", "")
        elif marker_type == "hazard":
            updates["hazard_type"] = marker_data.get("hazard_type", "")
            updates["severity"] = marker_data.get("severity", "")
        elif marker_type == "casualty":
            updates["condition"] = marker_data.get("condition", "")
            updates["treatment"] = marker_data.get("treatment", "")
            updates["evacuation_priority"] = marker_data.get("evacuation_priority", "")
            updates["found_by"] = marker_data.get("found_by", "")

        return updates

    # ------------------------------------------------------------------
    # Coordinate Converter
    # ------------------------------------------------------------------

    def on_coordinate_converter_requested(self):
        """Handle Coordinate Converter button click."""
        try:
            from ..ui.coordinate_converter_dialog import CoordinateConverterDialog
        except ImportError:
            warning(
                self.iface.messageBar(),
                "SAR Tracker",
                "Coordinate converter not available.",
                duration=4
            )
            return

        dialog = CoordinateConverterDialog(self.iface.mainWindow())
        dialog.go_to_location.connect(self._zoom_to_location)
        dialog_exec(dialog)

    def _zoom_to_location(self, lat, lon):
        """
        Zoom map to specified location.

        Args:
            lat: Latitude (WGS84)
            lon: Longitude (WGS84)

        LIFE-SAFETY CRITICAL: Validates coordinates before panning to prevent
        zooming to invalid locations during active rescue operations.
        """
        # CRITICAL FIX: Validate coordinates before zoom
        if not self._valid_latlon(lat, lon):
            warning(
                self.iface.messageBar(),
                "Navigation",
                "Invalid coordinates; cannot zoom to location.",
                duration=4
            )
            return

        point = QgsPointXY(lon, lat)
        canvas_crs = self.iface.mapCanvas().mapSettings().destinationCrs()

        # BUG-082 FIX: Transform point to canvas CRS with proper exception handling
        # CRS transforms can fail for invalid CRS combinations or edge coordinates
        if canvas_crs.authid() != "EPSG:4326":
            try:
                transform = QgsCoordinateTransform(
                    self.wgs84,
                    canvas_crs,
                    QgsProject.instance()
                )

                # Validate transform is usable
                if not transform.isValid():
                    warning(
                        self.iface.messageBar(),
                        "Navigation",
                        f"Cannot transform to project CRS ({canvas_crs.authid()}). "
                        "Check project coordinate system settings.",
                        duration=5
                    )
                    return

                point = transform.transform(point)

                # BUG-082: Verify transformed point is valid (not NaN/Inf)
                import math
                if math.isnan(point.x()) or math.isnan(point.y()):
                    warning(
                        self.iface.messageBar(),
                        "Navigation",
                        "Coordinate transform produced invalid result (NaN). "
                        "Coordinates may be outside valid projection bounds.",
                        duration=5
                    )
                    return
                if math.isinf(point.x()) or math.isinf(point.y()):
                    warning(
                        self.iface.messageBar(),
                        "Navigation",
                        "Coordinate transform produced invalid result (Infinity). "
                        "Coordinates may be outside valid projection bounds.",
                        duration=5
                    )
                    return

            except Exception as transform_err:
                warning(
                    self.iface.messageBar(),
                    "Navigation",
                    f"CRS transform failed: {transform_err}",
                    duration=5
                )
                return

        # Create extent (about 500m radius in map units)
        extent_size = 500  # meters
        if canvas_crs.isGeographic():
            extent_size = 0.005  # about 500m at typical latitudes

        extent = QgsRectangle(
            point.x() - extent_size,
            point.y() - extent_size,
            point.x() + extent_size,
            point.y() + extent_size
        )

        self.iface.mapCanvas().setExtent(extent)
        self.iface.mapCanvas().refresh()

    # ------------------------------------------------------------------
    # Drawing Tool Request Handlers
    # ------------------------------------------------------------------

    def on_measure_distance_requested(self):
        """Handle Measure Distance & Bearing button click."""
        if self.measure_tool:
            self.iface.mapCanvas().setMapTool(self.measure_tool)
            info(
                self.iface.messageBar(),
                "SAR Tracker",
                "Click two points on the map to measure distance and bearing",
                duration=5
            )
        else:
            warning(
                self.iface.messageBar(),
                "SAR Tracker",
                "Measure tool not available",
                duration=4
            )

    def on_line_tool_requested(self):
        """
        Handle Line Tool button click.

        SAFETY: Guards against tool_registry being None if initialization failed.
        """
        if not self.tool_registry:
            error(
                self.iface.messageBar(),
                "Drawing Tool Unavailable",
                "Line Tool failed to load during initialization. Run Diagnostics for details.",
                duration=0
            )
            self._show_diagnostics()
            return

        print(f"[MapToolsController] _on_line_tool_requested() called")
        self.tool_registry.activate_tool('line')
        info(
            self.iface.messageBar(),
            "SAR Tracker",
            "Click to add points. Right-click or ESC to finish line.",
            duration=5
        )

    def on_polygon_tool_requested(self):
        """
        Handle Polygon Tool (Search Area) button click.

        SAFETY: Guards against tool_registry being None if initialization failed.
        """
        if not self.tool_registry:
            error(
                self.iface.messageBar(),
                "Drawing Tool Unavailable",
                "Polygon Tool (Search Area) failed to load during initialization. Run Diagnostics for details.",
                duration=0
            )
            self._show_diagnostics()
            return

        print(f"[MapToolsController] _on_polygon_tool_requested() called")
        self.tool_registry.activate_tool('polygon')
        info(
            self.iface.messageBar(),
            "SAR Tracker",
            "Search Area Tool: Click to add vertices (min 3). Right-click to finish and configure area.",
            duration=5
        )

    def on_range_rings_tool_requested(self):
        """
        Handle Range Rings Tool button click.

        SAFETY: Guards against tool_registry being None if initialization failed.
        """
        if not self.tool_registry:
            error(
                self.iface.messageBar(),
                "Drawing Tool Unavailable",
                "Range Rings Tool failed to load during initialization. Run Diagnostics for details.",
                duration=0
            )
            self._show_diagnostics()
            return

        self.tool_registry.activate_tool('range_rings')
        info(
            self.iface.messageBar(),
            "SAR Tracker",
            "Range Rings Tool: Click center point to configure rings",
            duration=5
        )

    def on_bearing_tool_requested(self):
        """
        Handle Bearing Tool button click.

        SAFETY: Guards against tool_registry being None if initialization failed.
        """
        if not self.tool_registry:
            error(
                self.iface.messageBar(),
                "Drawing Tool Unavailable",
                "Bearing Tool failed to load during initialization. Run Diagnostics for details.",
                duration=0
            )
            self._show_diagnostics()
            return

        self.tool_registry.activate_tool('bearing')
        info(
            self.iface.messageBar(),
            "SAR Tracker",
            "Bearing Line Tool: Click origin point to configure bearing and distance",
            duration=5
        )

    # ------------------------------------------------------------------
    # Drawing Tool Completion Handlers
    # ------------------------------------------------------------------

    def _on_line_complete(self, feature_data):
        """Handle line drawing completion."""
        if self._should_skip_callback():
            return

        # HIGH FIX: Use .get() for safer dictionary access
        name = feature_data.get('name', 'Line')
        points = feature_data.get('points', 0)
        distance_m = feature_data.get('distance_m', 0)
        success(
            self.iface.messageBar(),
            "SAR Tracker",
            f"Line '{name}' added ({points} points, {distance_m:.0f}m)",
            duration=3
        )
        if self.tool_registry:
            self.tool_registry.deactivate_current()

    def _on_range_rings_complete(self, feature_data):
        """Handle range rings drawing completion."""
        if self._should_skip_callback():
            return

        # HIGH FIX: Use .get() for safer dictionary access
        mode = feature_data.get('mode', '')
        mode_str = "LPB-based" if mode == 'lpb' else "Manual"
        count = feature_data.get('count', 0)
        success(
            self.iface.messageBar(),
            "SAR Tracker",
            f"{mode_str} range rings created ({count} rings)",
            duration=3
        )
        if self.tool_registry:
            self.tool_registry.deactivate_current()

    def _on_bearing_complete(self, feature_data):
        """Handle bearing line drawing completion."""
        if self._should_skip_callback():
            return

        # HIGH FIX: Use .get() for safer dictionary access
        name = feature_data.get('name', 'Bearing')
        bearing = feature_data.get('bearing', 0)
        magnetic_bearing = feature_data.get('magnetic_bearing', 0)
        distance_m = feature_data.get('distance_m', 0)
        success(
            self.iface.messageBar(),
            "SAR Tracker",
            f"Bearing Line '{name}' created ({bearing:.1f}deg True, {magnetic_bearing:.1f}deg Magnetic, {distance_m:.0f}m)",
            duration=3
        )
        if self.tool_registry:
            self.tool_registry.deactivate_current()

    def _on_polygon_complete(self, feature_data):
        """Handle polygon (search area) drawing completion."""
        if self._should_skip_callback():
            return

        # HIGH FIX: Use .get() for safer dictionary access
        name = feature_data.get('name', 'Search Area')
        vertices = feature_data.get('vertices', 0)
        priority = feature_data.get('priority', 'Unknown')
        status = feature_data.get('status', 'Unknown')
        success(
            self.iface.messageBar(),
            "SAR Tracker",
            f"Search Area '{name}' created ({vertices} vertices, {priority} priority, {status})",
            duration=3
        )
        if self.tool_registry:
            self.tool_registry.deactivate_current()

    def _on_drawing_cancelled(self):
        """Handle drawing cancellation (ESC pressed or dialog cancelled)."""
        if self._should_skip_callback():
            return

        if self.tool_registry:
            self.tool_registry.deactivate_current()
        # Silent cancellation - no message needed

    def _handle_drawing_error(self, exc: Exception, context: str):
        """
        Handle drawing tool errors with proper shutdown guards.

        CRITICAL FIX: This method replaces inline lambdas to prevent
        errors during shutdown when error_handler may be None or deleted.

        Args:
            exc: The exception that occurred
            context: Description of where the error occurred (e.g., "Line drawing")
        """
        # Guard against callbacks during shutdown
        if self._should_skip_callback():
            return

        if self.error_handler:
            try:
                self.error_handler.handle_exception(exc, context)
            except Exception as handler_error:
                # Fallback if error handler itself fails
                print(f"[MapToolsController] {context} error: {exc}")
                print(f"[MapToolsController] Error handler failed: {handler_error}")
        else:
            print(f"[MapToolsController] {context} error: {exc}")

    def _on_tool_activated(self, tool_name):
        """Update UI when drawing tool activated."""
        if self.sar_panel:
            try:
                if not sip_isdeleted(self.sar_panel):
                    self.sar_panel.set_active_tool(tool_name.title())
            except Exception:
                pass
        self.tool_activated.emit(tool_name)

    def _on_tool_deactivated(self, tool_name):
        """Update UI when drawing tool deactivated."""
        if self.sar_panel:
            try:
                if not sip_isdeleted(self.sar_panel):
                    self.sar_panel.set_active_tool("None")
            except Exception:
                pass
        self.tool_deactivated.emit(tool_name)

    # ------------------------------------------------------------------
    # Measurement Methods
    # ------------------------------------------------------------------

    def _on_measurement_complete(self, distance_m, distance_km, bearing, point1, point2):
        """
        Handle measurement completion.

        Args:
            distance_m: Distance in meters
            distance_km: Distance in kilometers
            bearing: Bearing in degrees (0-360, where 0 = North)
            point1: First point
            point2: Second point
        """
        if self._should_skip_callback():
            return

        # Format distance nicely
        if distance_m < 1000:
            distance_str = f"{distance_m:.1f} meters"
        else:
            distance_str = f"{distance_km:.2f} km"

        # Format bearing with cardinal direction
        cardinal = self._bearing_to_cardinal(bearing)

        # Show results on single line for better visibility
        message = f"<b>Distance:</b> {distance_str}  |  <b>Bearing:</b> {bearing:.1f}deg ({cardinal})"

        success(
            self.iface.messageBar(),
            "Measurement Result",
            message,
            duration=10
        )

        try:
            self._persist_measurement_overlay(distance_m, bearing, point1, point2)
            self._update_measurement_overlay_indicator()
        except Exception as overlay_error:
            print(f"[MapToolsController] Warning: Failed to persist measurement overlay: {overlay_error}")

        # Deactivate tool (return to pan/zoom)
        if self.measure_tool:
            self.iface.mapCanvas().unsetMapTool(self.measure_tool)

        self.measurement_complete.emit(distance_m, bearing, cardinal)

    def _bearing_to_cardinal(self, bearing) -> str:
        """
        Convert bearing to cardinal direction.

        Args:
            bearing: Bearing in degrees (0-360)

        Returns:
            str: Cardinal direction (N, NE, E, SE, S, SW, W, NW)
        """
        # HIGH FIX: Validate bearing to prevent calculation errors
        if not self._is_number(bearing):
            return "Unknown"
        try:
            bearing_f = float(bearing)
            if not math.isfinite(bearing_f):
                return "Unknown"
        except (ValueError, TypeError):
            return "Unknown"

        directions = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
        index = int((bearing_f + 22.5) / 45) % 8
        return directions[index]

    def _persist_measurement_overlay(self, distance_m, bearing, point1, point2):
        """
        Save measurement as temporary overlay in Lines layer.

        Args:
            distance_m: Distance in meters
            bearing: Bearing in degrees
            point1: Start point in canvas CRS
            point2: End point in canvas CRS
        """
        if not self.layers_controller:
            return

        # Basic validation
        if not self._is_number(distance_m) or not self._is_number(bearing):
            warning(
                self.iface.messageBar(),
                "Measurement Overlays",
                "Invalid measurement values; overlay not saved.",
                duration=4
            )
            return

        try:
            canvas = self.iface.mapCanvas()
            canvas_crs = canvas.mapSettings().destinationCrs()
            transform = QgsCoordinateTransform(canvas_crs, self.wgs84, QgsProject.instance())

            points_wgs84 = [
                transform.transform(point1),
                transform.transform(point2)
            ]

            if distance_m < 1000:
                distance_str = f"{distance_m:.1f} m"
            else:
                distance_str = f"{distance_m / 1000.0:.2f} km"

            name = f"Measurement {datetime.now().strftime('%H:%M:%S')}"
            description = f"{distance_str} | {bearing:.1f}deg"

            self.layers_controller.add_measurement_overlay(
                name=name,
                points_wgs84=points_wgs84,
                description=description
            )
        except Exception as exc:
            if self._log_exception:
                self._log_exception("_persist_measurement_overlay", exc)
            warning(
                self.iface.messageBar(),
                "Measurement Overlays",
                "Could not save measurement overlay.",
                duration=4
            )

    def _update_measurement_overlay_indicator(self):
        """Update SARPanel measurement badge with current overlay count."""
        if not self.layers_controller or not self.sar_panel:
            return

        try:
            # IMPORTANT: Avoid mutating the startup "Untitled Project".
            # Counting overlays can create the Lines layer if missing, which
            # dirties the project and can trigger QGIS' save prompt on startup.
            project = QgsProject.instance()
            project_filename = ""
            try:
                project_filename = project.fileName() or ""
            except Exception:
                project_filename = ""

            mission_store = ""
            try:
                if self.layer_manager:
                    mission_store = str(self.layer_manager.get_mission_store() or "")
            except Exception:
                mission_store = ""

            is_sar = False
            try:
                if self.layer_manager:
                    is_sar = bool(self.layer_manager.is_sar_project())
            except Exception:
                is_sar = False

            if not ((project_filename or mission_store) and is_sar):
                count = 0
            else:
                count = self.layers_controller.count_measurement_overlays()
        except Exception as e:
            print(f"[MapToolsController] Warning: Could not count measurement overlays: {e}")
            count = 0

        try:
            if not sip_isdeleted(self.sar_panel):
                self.sar_panel.update_measurements_indicator(count)
        except Exception as panel_err:
            print(f"[MapToolsController] Warning: Could not update measurement indicator: {panel_err}")

    def on_clear_measurements_requested(self):
        """Handle Clear Measurements request from panel."""
        if not self.layers_controller:
            return

        try:
            removed = self.layers_controller.clear_measurement_overlays()
            self._update_measurement_overlay_indicator()
            info(
                self.iface.messageBar(),
                "Measurement Overlays",
                f"Cleared {removed} measurement overlay(s)." if removed else "No measurement overlays to clear.",
                duration=3
            )
        except Exception as exc:
            error(
                self.iface.messageBar(),
                "Measurement Overlays",
                f"Failed to clear measurement overlays: {exc}",
                duration=5
            )
            if self._log_exception:
                self._log_exception("on_clear_measurements_requested", exc)

    def update_measurement_indicator(self):
        """Public method to trigger measurement indicator update."""
        self._update_measurement_overlay_indicator()

    # ------------------------------------------------------------------
    # GPX Import/Watch Methods
    # ------------------------------------------------------------------

    def on_gpx_import_file(self, file_path: str):
        """
        Handle GPX file import request.

        LIFE-SAFETY CRITICAL: Validates file and provides clear error messages.

        Args:
            file_path: Absolute path to GPX file
        """
        if self._should_skip_callback():
            return

        if not self.layers_controller or not self.layers_controller.drawings:
            error(
                self.iface.messageBar(),
                "GPX Import Failed",
                "Drawing manager not initialized",
                duration=0
            )
            return

        try:
            layer, error_msg = self.layers_controller.drawings.import_gpx_file(file_path)

            if layer:
                success(
                    self.iface.messageBar(),
                    "GPX Imported",
                    f"Imported: {layer.name()} ({layer.featureCount()} features)",
                    duration=5
                )
            else:
                error(
                    self.iface.messageBar(),
                    "GPX Import Failed",
                    error_msg,
                    duration=0
                )

        except Exception as e:
            print(f"[MapToolsController] GPX import error: {e}")
            traceback.print_exc()
            error(
                self.iface.messageBar(),
                "GPX Import Error",
                f"Unexpected error: {e}",
                duration=0
            )

    def on_gpx_import_folder(self, folder_path: str):
        """
        Handle GPX folder import request.

        LIFE-SAFETY CRITICAL: Validates folder and provides summary of results.

        Args:
            folder_path: Absolute path to folder containing GPX files
        """
        if self._should_skip_callback():
            return

        if not self.layers_controller or not self.layers_controller.drawings:
            error(
                self.iface.messageBar(),
                "GPX Import Failed",
                "Drawing manager not initialized",
                duration=0
            )
            return

        try:
            layers, errors = self.layers_controller.drawings.import_gpx_folder(folder_path)

            if layers:
                success(
                    self.iface.messageBar(),
                    "GPX Folder Imported",
                    f"Imported {len(layers)} GPX files",
                    duration=5
                )

                # Show errors if any
                if errors:
                    warning(
                        self.iface.messageBar(),
                        "Some GPX Files Failed",
                        f"{len(errors)} files could not be imported. Check QGIS Log Messages for details.",
                        duration=10
                    )
                    for err_msg in errors:
                        print(f"[MapToolsController] GPX import failed: {err_msg}")

            else:
                error(
                    self.iface.messageBar(),
                    "GPX Folder Import Failed",
                    errors[0] if errors else "No GPX files found in folder",
                    duration=0
                )

        except Exception as e:
            print(f"[MapToolsController] GPX folder import error: {e}")
            traceback.print_exc()
            error(
                self.iface.messageBar(),
                "GPX Import Error",
                f"Unexpected error: {e}",
                duration=0
            )

    def on_gpx_watch_folder(self, folder_path: str):
        """
        Handle GPX folder watch request.

        LIFE-SAFETY CRITICAL: Starts folder watching for auto-import.

        Args:
            folder_path: Absolute path to folder to watch
        """
        if self._should_skip_callback():
            return

        if not self.layers_controller or not self.layers_controller.drawings:
            error(
                self.iface.messageBar(),
                "GPX Watch Failed",
                "Drawing manager not initialized",
                duration=0
            )
            return

        try:
            success_flag, error_msg = self.layers_controller.drawings.start_gpx_folder_watch(folder_path)

            if success_flag:
                success(
                    self.iface.messageBar(),
                    "Watching GPX Folder",
                    f"Existing and new GPX files in {folder_path} will be imported",
                    duration=10
                )
            else:
                error(
                    self.iface.messageBar(),
                    "GPX Watch Failed",
                    error_msg,
                    duration=0
                )

        except Exception as e:
            print(f"[MapToolsController] GPX watch error: {e}")
            traceback.print_exc()
            error(
                self.iface.messageBar(),
                "GPX Watch Error",
                f"Unexpected error: {e}",
                duration=0
            )

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def cleanup(self, reason: Optional[str] = None):
        """
        Clean up all map tools and registry.

        This method should be called during plugin unload.
        Idempotent: Safe to call multiple times.

        Args:
            reason: Optional reason string for logging
        """
        # Guard against double cleanup
        if self._is_shutting_down:
            return
        self._is_shutting_down = True

        cleanup_reason = reason or "controller cleanup"
        print(f"[MapToolsController] cleanup started: {cleanup_reason}")

        # Deactivate current tool in registry
        if self.tool_registry:
            try:
                self.tool_registry.deactivate_current()
            except Exception as e:
                print(f"[MapToolsController] Warning: Error deactivating current tool: {e}")

        # Clean up individual tools
        tool_attrs = ['marker_tool', 'measure_tool', 'line_tool', 'range_ring_tool', 'bearing_tool', 'polygon_tool']
        for tool_attr in tool_attrs:
            tool = getattr(self, tool_attr, None)
            if tool:
                try:
                    # Check if it's the current canvas tool
                    try:
                        if self.iface and self.iface.mapCanvas().mapTool() == tool:
                            self.iface.mapCanvas().unsetMapTool(tool)
                    except Exception:
                        pass

                    # Call deactivate if available
                    if hasattr(tool, 'deactivate'):
                        try:
                            tool.deactivate()
                        except Exception:
                            pass

                    # Delete the tool
                    try:
                        if not sip_isdeleted(tool):
                            tool.deleteLater()
                    except Exception:
                        pass
                except Exception as e:
                    print(f"[MapToolsController] Warning: Error cleaning up {tool_attr}: {e}")
                finally:
                    setattr(self, tool_attr, None)

        # Clean up tool registry
        if self.tool_registry:
            try:
                if not sip_isdeleted(self.tool_registry):
                    self.tool_registry.deleteLater()
            except Exception as e:
                print(f"[MapToolsController] Warning: Error cleaning up tool_registry: {e}")
            finally:
                self.tool_registry = None

        # Clear references
        self.current_marker_type = None
        self.layers_controller = None
        self.marker_controller = None
        self.layer_manager = None
        self.sar_panel = None
        self.error_handler = None

        print(f"[MapToolsController] cleanup complete")

    def status_snapshot(self) -> dict:
        """
        Return current status for diagnostics.

        Returns:
            dict with current state information
        """
        # Safely check tool registry state
        registry_ok = False
        registered_tools = []
        active_tool = None

        if self.tool_registry:
            try:
                if not sip_isdeleted(self.tool_registry):
                    registry_ok = True
                    registered_tools = self.tool_registry.get_registered_tools()
                    active_tool = self.tool_registry.get_active_tool_name()
            except Exception:
                pass

        # Check individual tools
        def tool_status(tool):
            if tool is None:
                return "not_loaded"
            try:
                if sip_isdeleted(tool):
                    return "deleted"
                return "loaded"
            except Exception:
                return "unknown"

        return {
            "tool_registry_loaded": registry_ok,
            "registered_tools": registered_tools,
            "active_tool": active_tool,
            "marker_tool": tool_status(self.marker_tool),
            "measure_tool": tool_status(self.measure_tool),
            "line_tool": tool_status(self.line_tool),
            "range_ring_tool": tool_status(self.range_ring_tool),
            "bearing_tool": tool_status(self.bearing_tool),
            "polygon_tool": tool_status(self.polygon_tool),
            "current_marker_type": self.current_marker_type,
            "is_shutting_down": self._is_shutting_down,
        }
