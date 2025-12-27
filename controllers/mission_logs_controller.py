# -*- coding: utf-8 -*-
"""
Mission Logs Controller for SAR Tracker.

Manages the Mission Logs window lifecycle, signal wiring, and all handlers
for layer/marker operations initiated from the Mission Logs UI.

Phase 4 - Mission Logs Extraction:
Consolidates all _on_mission_logs_* handlers from sartracker.py into a
single controller with proper dependency injection.

Qt5/Qt6 Compatible: Uses qgis.PyQt and qt_compat for all Qt imports.
"""

import os.path
import traceback
from pathlib import Path
from typing import Optional, Callable, TYPE_CHECKING

from qgis.PyQt.QtCore import QObject, QUrl
from qgis.PyQt.QtGui import QDesktopServices
from qgis.PyQt.QtWidgets import QMessageBox

from qgis.core import (
    QgsPointXY,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsProject,
)

from ..utils.qt_compat import MessageBoxYes, MessageBoxNo
from ..utils.notify import warning, error

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
    from ..ui.mission_logs_window import MissionLogsWindow


class MissionLogsController(QObject):
    """
    Controller for Mission Logs window operations.

    Responsibilities:
    - Create and manage Mission Logs window lifecycle
    - Wire window signals to handlers
    - Handle all layer/marker operations from window
    - Clean up on unload

    Dependencies are injected via __init__ or setters to avoid
    accessing plugin globals directly.
    """

    def __init__(
        self,
        iface: "QgisInterface",
        layers_controller: Optional["LayersController"] = None,
        marker_controller: Optional["MarkerController"] = None,
        layer_manager: Optional["LayerManager"] = None,
        get_mission_paths: Optional[Callable] = None,
        get_mission_start_iso: Optional[Callable] = None,
        get_audit_user_name: Optional[Callable] = None,
        is_unloading: Optional[Callable[[], bool]] = None,
        parent: Optional[QObject] = None
    ):
        """
        Initialize mission logs controller.

        Args:
            iface: QGIS interface
            layers_controller: LayersController for layer operations
            marker_controller: MarkerController for marker edit/delete
            layer_manager: LayerManager for mission data
            get_mission_paths: Callback to get current MissionPaths
            get_mission_start_iso: Callback to get mission start ISO timestamp
            get_audit_user_name: Callback to get audit user name
            is_unloading: Callback to check if plugin is unloading
            parent: Optional QObject parent
        """
        super().__init__(parent)

        self.iface = iface
        self.layers_controller = layers_controller
        self.marker_controller = marker_controller
        self.layer_manager = layer_manager
        self._get_mission_paths = get_mission_paths
        self._get_mission_start_iso = get_mission_start_iso
        self._get_audit_user_name = get_audit_user_name or (lambda: "Unknown")
        self._is_unloading_cb = is_unloading or (lambda: False)

        # Window instance (created on demand)
        self._window: Optional["MissionLogsWindow"] = None

        # Safe-mode callback (set by sartracker)
        self._safe_mode_block: Optional[Callable[[str], bool]] = None

        # Shutdown flag
        self._is_shutting_down = False

    # ------------------------------------------------------------------
    # Dependency Setters (for late binding)
    # ------------------------------------------------------------------

    def set_layers_controller(self, controller: "LayersController"):
        """Set layers controller (for late binding)."""
        self.layers_controller = controller

    def set_marker_controller(self, controller: "MarkerController"):
        """Set marker controller (for late binding)."""
        self.marker_controller = controller

    def set_safe_mode_block(self, callback: Callable[[str], bool]):
        """Set safe-mode block callback."""
        self._safe_mode_block = callback

    # ------------------------------------------------------------------
    # Window Lifecycle
    # ------------------------------------------------------------------

    def show_window(self):
        """Show the Mission Logs window (non-modal)."""
        if self._safe_mode_block and self._safe_mode_block("Mission Logs"):
            return

        try:
            from ..ui.mission_logs_window import MissionLogsWindow

            # Reuse existing window if visible
            if self._window:
                try:
                    # CRITICAL: Check if Qt object still exists before accessing
                    if sip_isdeleted(self._window):
                        self._window = None
                    elif self._window.isVisible():
                        self._window.raise_()
                        self._window.activateWindow()
                        return
                except RuntimeError:
                    self._window = None

            # Create new window
            self._window = MissionLogsWindow(self.iface.mainWindow())

            # Configure catalog service
            if self.layers_controller and hasattr(self.layers_controller, "catalog") and self.layers_controller.catalog:
                self._window.set_catalog_service(self.layers_controller.catalog)

            # Configure marker fetcher
            if self.layers_controller and hasattr(self.layers_controller, "list_markers"):
                self._window.set_marker_fetcher(self.layers_controller.list_markers)

            # Configure mission info fetcher
            self._window.set_mission_info_fetcher(self.get_mission_info)

            # Wire signals
            self._connect_window_signals()

            # Show non-modal
            self._window.show()

        except Exception as e:
            error(
                self.iface.messageBar(),
                "SAR Tracker",
                f"Failed to open Mission Logs: {e}",
                duration=5
            )
            print(f"[MissionLogsController] ERROR opening Mission Logs: {e}")
            traceback.print_exc()

    def _connect_window_signals(self):
        """Connect window signals to handlers."""
        if not self._window:
            return

        # Marker signals
        self._window.zoom_requested.connect(self._on_zoom)
        self._window.edit_marker_requested.connect(self._on_edit_marker)
        self._window.delete_marker_requested.connect(self._on_delete_marker)
        self._window.open_attachment_requested.connect(self._on_open_attachment)

        # Layer console signals
        self._window.feature_zoom_requested.connect(self._on_feature_zoom)
        self._window.feature_delete_requested.connect(self._on_feature_delete)
        self._window.feature_rename_requested.connect(self._on_feature_rename)
        self._window.bulk_delete_requested.connect(self._on_bulk_delete)
        self._window.visibility_toggled.connect(self._on_visibility_toggled)
        self._window.layer_alias_change_requested.connect(self._on_alias_change)
        self._window.layer_favorite_toggled.connect(self._on_favorite_toggled)
        self._window.move_to_section_requested.connect(self._on_move_to_section)
        self._window.reorder_requested.connect(self._on_reorder)
        self._window.layer_console_refresh_requested.connect(self._on_refresh)
        self._window.closed.connect(self._on_closed)

    def _disconnect_window_signals(self):
        """
        Disconnect window signals from handlers.

        CRITICAL: Must be called before window is destroyed to prevent
        callbacks into deleted Qt objects.
        """
        if not self._window:
            return
        try:
            if sip_isdeleted(self._window):
                return
            # Disconnect all signals - use try/except for each in case already disconnected
            for signal, handler in [
                (self._window.zoom_requested, self._on_zoom),
                (self._window.edit_marker_requested, self._on_edit_marker),
                (self._window.delete_marker_requested, self._on_delete_marker),
                (self._window.open_attachment_requested, self._on_open_attachment),
                (self._window.feature_zoom_requested, self._on_feature_zoom),
                (self._window.feature_delete_requested, self._on_feature_delete),
                (self._window.feature_rename_requested, self._on_feature_rename),
                (self._window.bulk_delete_requested, self._on_bulk_delete),
                (self._window.visibility_toggled, self._on_visibility_toggled),
                (self._window.layer_alias_change_requested, self._on_alias_change),
                (self._window.layer_favorite_toggled, self._on_favorite_toggled),
                (self._window.move_to_section_requested, self._on_move_to_section),
                (self._window.reorder_requested, self._on_reorder),
                (self._window.layer_console_refresh_requested, self._on_refresh),
                (self._window.closed, self._on_closed),
            ]:
                try:
                    signal.disconnect(handler)
                except (TypeError, RuntimeError):
                    pass  # Already disconnected or object deleted
        except (RuntimeError, AttributeError):
            pass  # Window already deleted

    def refresh_window(self):
        """Refresh the Mission Logs window if open."""
        if self._is_unloading_cb() or self._is_shutting_down:
            return

        if self._window:
            try:
                if sip_isdeleted(self._window):
                    self._window = None
                    return
                self._window.refresh()
            except RuntimeError:
                self._window = None
            except Exception as exc:
                print(f"[MissionLogsController] Warning: Failed to refresh window: {exc}")

    def close_window(self):
        """Close the window if open."""
        if self._window:
            try:
                if not sip_isdeleted(self._window):
                    self._window.close()
            except Exception:
                pass
            self._window = None

    # ------------------------------------------------------------------
    # Mission Info Provider
    # ------------------------------------------------------------------

    def get_mission_info(self) -> dict:
        """Get mission information for the Mission Logs window."""
        info = {
            "name": None,
            "status": "inactive",
            "start_time": None,
            "end_time": None,
            "coordinators": "",
            "primary_store": None,
            "backup_store": None,
            "layer_count": 0,
            "feature_count": 0,
            "marker_count": 0,
            "tracking_devices": 0,
            "breadcrumb_count": 0,
            "data_incomplete": False,
        }

        try:
            # Mission name and paths
            if self._get_mission_paths:
                paths = self._get_mission_paths()
                if paths:
                    info["name"] = getattr(paths, 'name', None) or getattr(paths, 'mission_name', None)
                    info["status"] = "active"
                    info["primary_store"] = str(paths.gpkg_path) if paths.gpkg_path else None
                    backup_dir = getattr(paths, 'backup_dir', None) or getattr(paths, 'backup_directory', None)
                    info["backup_store"] = str(backup_dir) if backup_dir else None

            # Coordinators
            if self.layer_manager:
                coords = self.layer_manager.get_mission_coordinators()
                if coords:
                    info["coordinators"] = coords

            # Start time
            if self._get_mission_start_iso:
                start_iso = self._get_mission_start_iso()
                if start_iso:
                    info["start_time"] = start_iso

            # Layer/feature counts
            if self.layers_controller:
                try:
                    if hasattr(self.layers_controller, "get_layer_count"):
                        info["layer_count"] = self.layers_controller.get_layer_count()
                    if hasattr(self.layers_controller, "get_feature_count"):
                        info["feature_count"] = self.layers_controller.get_feature_count()
                except Exception as exc:
                    print(f"[MissionLogsController] Warning: Failed to get layer/feature counts: {exc}")
                    info["data_incomplete"] = True

            # Marker count
            if self.layers_controller and hasattr(self.layers_controller, "list_markers"):
                try:
                    markers = self.layers_controller.list_markers()
                    info["marker_count"] = len(markers) if markers else 0
                except Exception as exc:
                    print(f"[MissionLogsController] Warning: Failed to get marker count: {exc}")
                    info["data_incomplete"] = True

            # Tracking stats
            if self.layer_manager:
                try:
                    if hasattr(self.layer_manager, "get_device_count"):
                        info["tracking_devices"] = self.layer_manager.get_device_count()
                    if hasattr(self.layer_manager, "get_breadcrumb_count"):
                        info["breadcrumb_count"] = self.layer_manager.get_breadcrumb_count()
                except Exception as exc:
                    print(f"[MissionLogsController] Warning: Failed to get tracking stats: {exc}")
                    info["data_incomplete"] = True

        except Exception as exc:
            print(f"[MissionLogsController] Warning: Error getting mission info: {exc}")
            info["data_incomplete"] = True

        return info

    # ------------------------------------------------------------------
    # Signal Handlers
    # ------------------------------------------------------------------

    def _on_feature_zoom(self, layer_id: str, feature_id):
        """Handle zoom to feature request."""
        if self._is_unloading_cb() or self._is_shutting_down:
            return
        if self.layers_controller:
            try:
                self.layers_controller.zoom_to_feature(layer_id, feature_id)
            except Exception as exc:
                print(f"[MissionLogsController] Warning: Failed to zoom to feature: {exc}")

    def _on_zoom(self, lat: float, lon: float):
        """Handle coordinate zoom request."""
        if self._is_unloading_cb() or self._is_shutting_down:
            return
        try:
            from ..utils.exceptions import validate_coordinate_pair, CoordinateError

            try:
                lat, lon = validate_coordinate_pair(lat, lon)
            except CoordinateError as exc:
                warning(
                    self.iface.messageBar(),
                    "SAR Tracker",
                    f"Invalid coordinates: {exc}",
                    duration=4
                )
                return

            # Convert from WGS84 to project CRS
            wgs84 = QgsCoordinateReferenceSystem("EPSG:4326")
            project_crs = QgsProject.instance().crs()
            transform = QgsCoordinateTransform(wgs84, project_crs, QgsProject.instance())

            point = transform.transform(QgsPointXY(lon, lat))

            # Zoom to point with buffer
            canvas = self.iface.mapCanvas()
            current_scale = canvas.scale()
            canvas.setCenter(point)
            canvas.zoomScale(min(current_scale, 5000))
            canvas.refresh()
        except Exception as exc:
            print(f"[MissionLogsController] Warning: Failed to zoom to coordinates: {exc}")

    def _on_edit_marker(self, marker_type: str, marker_id: str):
        """Handle edit marker request."""
        if self._is_unloading_cb() or self._is_shutting_down:
            return
        if self.marker_controller:
            try:
                self.marker_controller.handle_edit(marker_type, marker_id)
            except Exception as exc:
                print(f"[MissionLogsController] Warning: Failed to edit marker: {exc}")

    def _on_delete_marker(self, marker_type: str, marker_id: str):
        """Handle delete marker request."""
        if self._is_unloading_cb() or self._is_shutting_down:
            return
        if self.marker_controller:
            try:
                self.marker_controller.handle_delete(marker_type, marker_id)
            except Exception as exc:
                print(f"[MissionLogsController] Warning: Failed to delete marker: {exc}")

    def _on_open_attachment(self, path: str):
        """Handle open attachment request."""
        if self._is_unloading_cb() or self._is_shutting_down:
            return

        if not path:
            print("[MissionLogsController] Warning: Empty attachment path")
            return
        if not os.path.isfile(path):
            warning(
                self.iface.messageBar(),
                "SAR Tracker",
                f"Attachment not found: {path}",
                duration=4
            )
            return

        try:
            if not QDesktopServices.openUrl(QUrl.fromLocalFile(path)):
                raise RuntimeError("QDesktopServices.openUrl returned False")
        except Exception as exc:
            warning(self.iface.messageBar(), "SAR Tracker", f"Could not open attachment: {exc}", duration=5)
            print(f"[MissionLogsController] Warning: Failed to open attachment: {exc}")

    def _on_feature_delete(self, layer_id: str, feature_id):
        """Handle feature delete request."""
        if self._is_unloading_cb() or self._is_shutting_down:
            return
        if self.layers_controller:
            try:
                self.layers_controller.delete_feature(
                    layer_id,
                    feature_id,
                    updated_by=self._get_audit_user_name()
                )
                self.refresh_window()
            except Exception as exc:
                warning(self.iface.messageBar(), "SAR Tracker", f"Delete failed: {exc}", duration=4)
                print(f"[MissionLogsController] Warning: Failed to delete feature: {exc}")

    def _on_feature_rename(self, layer_id: str, feature_id, new_name: str):
        """Handle feature rename request."""
        if self._is_unloading_cb() or self._is_shutting_down:
            return
        if self.layers_controller:
            try:
                self.layers_controller.rename_feature(
                    layer_id,
                    feature_id,
                    new_name,
                    updated_by=self._get_audit_user_name()
                )
                self.refresh_window()
            except Exception as exc:
                warning(self.iface.messageBar(), "SAR Tracker", f"Rename failed: {exc}", duration=4)
                print(f"[MissionLogsController] Warning: Failed to rename feature: {exc}")

    def _on_bulk_delete(self, layer_id: str, feature_ids: list):
        """Handle bulk delete request."""
        if self._is_unloading_cb() or self._is_shutting_down:
            return
        if self.layers_controller:
            try:
                if not feature_ids:
                    return
                if len(feature_ids) > 10:
                    confirm = QMessageBox.question(
                        self.iface.mainWindow(),
                        "Bulk Delete",
                        f"Delete {len(feature_ids)} features?\nThis action cannot be undone.",
                        MessageBoxYes | MessageBoxNo,
                        MessageBoxNo
                    )
                    if confirm != MessageBoxYes:
                        return
                self.layers_controller.bulk_delete_features(
                    layer_id,
                    feature_ids,
                    confirmed=True,
                    updated_by=self._get_audit_user_name()
                )
                self.refresh_window()
            except Exception as exc:
                warning(self.iface.messageBar(), "SAR Tracker", f"Bulk delete failed: {exc}", duration=5)
                print(f"[MissionLogsController] Warning: Failed to bulk delete features: {exc}")

    def _on_visibility_toggled(self, layer_id: str, visible: bool):
        """Handle layer visibility toggle."""
        if self._is_unloading_cb() or self._is_shutting_down:
            return
        if self.layers_controller:
            try:
                self.layers_controller.set_layer_visibility(layer_id, visible)
            except Exception as exc:
                print(f"[MissionLogsController] Warning: Failed to toggle visibility: {exc}")

    def _on_alias_change(self, layer_id: str, new_alias: str):
        """Handle layer alias change."""
        if self._is_unloading_cb() or self._is_shutting_down:
            return
        if self.layers_controller and hasattr(self.layers_controller, "catalog") and self.layers_controller.catalog:
            try:
                alias_value = new_alias.strip() if new_alias else None
                self.layers_controller.catalog.set_layer_alias(layer_id, alias_value)
            except Exception as exc:
                print(f"[MissionLogsController] Warning: Failed to change alias: {exc}")

    def _on_favorite_toggled(self, layer_id: str, is_favorite: bool):
        """Handle layer favorite toggle."""
        if self._is_unloading_cb() or self._is_shutting_down:
            return
        if self.layers_controller and hasattr(self.layers_controller, "catalog") and self.layers_controller.catalog:
            try:
                self.layers_controller.catalog.set_layer_favorite(layer_id, is_favorite)
            except Exception as exc:
                print(f"[MissionLogsController] Warning: Failed to toggle favorite: {exc}")

    def _on_move_to_section(self, feature_id: int, section: str):
        """Handle move to section request."""
        if self._is_unloading_cb() or self._is_shutting_down:
            return
        if self.layers_controller:
            try:
                self.layers_controller.move_search_area_to_section(
                    feature_id=feature_id,
                    target_section=section
                )
                self.refresh_window()
            except Exception as exc:
                print(f"[MissionLogsController] Warning: Failed to move to section: {exc}")

    def _on_reorder(self, layer_id: str, feature_ids: list):
        """Handle feature reorder request."""
        if self._is_unloading_cb() or self._is_shutting_down:
            return
        if self.layers_controller:
            try:
                self.layers_controller.reorder_features(layer_id, feature_ids)
            except Exception as exc:
                print(f"[MissionLogsController] Warning: Failed to reorder features: {exc}")

    def _on_refresh(self):
        """Handle manual refresh request."""
        if self._is_unloading_cb() or self._is_shutting_down:
            return
        if self.layers_controller and hasattr(self.layers_controller, "catalog") and self.layers_controller.catalog:
            try:
                self.layers_controller.catalog.rescan_layers()
            except Exception as exc:
                print(f"[MissionLogsController] Warning: Catalog rescan failed: {exc}")
        self.refresh_window()

    def _on_closed(self):
        """Handle window closed signal."""
        # CRITICAL: Disconnect signals before clearing reference
        self._disconnect_window_signals()
        self._window = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def cleanup(self):
        """Clean up controller resources."""
        self._is_shutting_down = True
        self.close_window()

    @property
    def window(self) -> Optional["MissionLogsWindow"]:
        """Get current window instance (may be None)."""
        return self._window

    def status_snapshot(self) -> dict:
        """Return current status for diagnostics."""
        return {
            "window_open": self._window is not None,
            "is_shutting_down": self._is_shutting_down,
        }
