# -*- coding: utf-8 -*-
"""
SAR Tracker Layer Manager

Provides idempotent creation and retrieval of layer groups and layers according
to the canonical schema. Manages layer cache, project signals, and ensures
persistent layer structure across plugin sessions.

Qt5/Qt6 Compatible: Uses qgis.PyQt and qt_compat for all Qt imports.
"""

import json
import logging
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, List, Optional, Callable, Any
from threading import RLock

logger = logging.getLogger(__name__)
from qgis.PyQt.QtCore import QVariant, QObject, pyqtSignal, QCoreApplication, QEvent, QTimer
from qgis.core import (
    QgsProject,
    QgsVectorLayer,
    QgsField,
    QgsLayerTreeGroup,
    QgsLayerTreeLayer,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransformContext,
    QgsMarkerSymbol,
    QgsLineSymbol,
    QgsFillSymbol,
    QgsWkbTypes,
    QgsMapLayerStyle,
    QgsVectorLayerExporter,
    QgsVectorFileWriter,
    QgsDataSourceUri
)

from .schema import (
    SAR_LAYER_SCHEMA_VERSION,
    GroupNames,
    LayerIds,
    LayerDefinition,
    GroupDefinition,
    get_expected_structure,
    get_group_path,
    get_layer_by_id,
    LAYER_GROUP_PATHS,
    LAYER_NAME_TO_ID,
    LAYER_FIELD_CHECKS,
    migration_tracker
)
from ..utils.notify import info, warning, error


# Qt type mapping for field creation
# Use QVariant constants directly for Qt5/Qt6 compatibility
QT_TYPE_MAP = {
    "String": QVariant.String,
    "Int": QVariant.Int,
    "Double": QVariant.Double,
    "DateTime": QVariant.DateTime,
    "Bool": QVariant.Bool
}

GEOMETRY_WKB_MAP = {
    "Point": QgsWkbTypes.Point,
    "LineString": QgsWkbTypes.LineString,
    "Polygon": QgsWkbTypes.Polygon
}

_HAS_EXPORTER_SAVE_OPTIONS = hasattr(QgsVectorLayerExporter, "SaveVectorOptions")


def _create_save_vector_options():
    """Return a SaveVectorOptions instance compatible with the running QGIS version."""
    if _HAS_EXPORTER_SAVE_OPTIONS:
        return QgsVectorLayerExporter.SaveVectorOptions()
    return QgsVectorFileWriter.SaveVectorOptions()


def _export_layer(layer, path, options, transform_context):
    """Export a layer using the best available writer API."""
    if _HAS_EXPORTER_SAVE_OPTIONS:
        return QgsVectorLayerExporter.exportLayer(layer, path, options, transform_context)
    return QgsVectorFileWriter.writeAsVectorFormatV3(layer, path, transform_context, options)


_EXPORT_CREATE_OR_OVERWRITE_LAYER = (
    QgsVectorLayerExporter.CreateOrOverwriteLayer
    if _HAS_EXPORTER_SAVE_OPTIONS
    else QgsVectorFileWriter.CreateOrOverwriteLayer
)

_EXPORT_CREATE_OR_OVERWRITE_FILE = (
    getattr(QgsVectorLayerExporter, "CreateOrOverwriteFile", _EXPORT_CREATE_OR_OVERWRITE_LAYER)
    if _HAS_EXPORTER_SAVE_OPTIONS
    else getattr(QgsVectorFileWriter, "CreateOrOverwriteFile", _EXPORT_CREATE_OR_OVERWRITE_LAYER)
)

_EXPORT_NO_ERROR = (
    QgsVectorLayerExporter.NoError
    if _HAS_EXPORTER_SAVE_OPTIONS
    else QgsVectorFileWriter.NoError
)


def _set_option_if_available(options, attr_name, value):
    """Safely set advanced exporter options that may not exist on older QGIS releases."""
    if hasattr(options, attr_name):
        setattr(options, attr_name, value)


# Build valid layer IDs set from schema (for HIGH-2 validation)
VALID_LAYER_IDS = {
    getattr(LayerIds, attr)
    for attr in dir(LayerIds)
    if not attr.startswith('_') and isinstance(getattr(LayerIds, attr), str)
}


class LayerManager(QObject):
    """
    Manages the SAR Tracker layer hierarchy with idempotent operations.

    This class ensures that all mission artifacts are stored in a predictable,
    persistent layer structure. It provides methods to create groups and layers
    according to the canonical schema, with automatic migration and repair.

    Attributes:
        project: The current QGIS project
        iface: QGIS interface
        _layer_cache: Cache of layer IDs to layer objects
        _group_cache: Cache of group paths to group objects
        _signals_connected: Whether project signals are connected
    """

    # Qt SIGNALS (HIGH-7)
    mission_store_changed = pyqtSignal(str)  # Emits new path (empty string if cleared)

    MISSION_STORE_VAR = "sartracker:mission_store_path"
    MISSION_STORE_DRIVER = "GPKG"
    MISSION_STORE_PROVIDER = "ogr"
    MISSION_FINALIZED_VAR = "sartracker:mission_finalized"
    MISSION_FINALIZED_BY_VAR = "sartracker:finalized_by"
    MISSION_FINALIZED_AT_VAR = "sartracker:finalized_at"
    MISSION_COORDINATORS_VAR = "sartracker:mission_coordinators"
    MISSION_RESUME_TIME_VAR = "sartracker:mission_resume_time"
    _metadata_migration_in_progress = False

    def __init__(self, iface):
        """
        Initialize the LayerManager.

        Args:
            iface: QGIS interface instance
        """
        # CRITICAL: Initialize QObject parent FIRST (HIGH-7)
        super().__init__()

        self.iface = iface
        self.project = QgsProject.instance()
        self._layer_cache: Dict[str, QgsVectorLayer] = {}
        self._group_cache: Dict[str, QgsLayerTreeGroup] = {}
        # BUG-044 FIX: Thread-safe lock for concurrent cache access
        self._cache_lock = RLock()
        self._signals_connected = False
        self._project_cleared_connected = False
        self._application_closing = False
        self._about_to_quit_connected = False
        self._event_filter_installed = False
        self._main_window = iface.mainWindow() if iface else None
        self._mission_store_path: Optional[str] = self._load_mission_store_path()
        # SAR-604i: Temporary mission store for replay mode (takes priority)
        self._temp_mission_store_path: Optional[str] = None
        self._layer_provider_uris: Dict[str, str] = {}
        self._metadata_lock = RLock()  # Thread-safety for metadata operations
        self._metadata_migration_in_progress = False
        self._load_migration_state()

        # Track QGIS shutdown so we can skip rebuilds during app exit
        app = QCoreApplication.instance()
        if app:
            try:
                app.aboutToQuit.connect(self._handle_app_about_to_quit)
                self._about_to_quit_connected = True
            except Exception as exc:
                self._log("WARN", f"Could not track application shutdown: {exc}")

        if self._main_window:
            try:
                self._main_window.installEventFilter(self)
                self._event_filter_installed = True
            except Exception as exc:
                self._log("WARN", f"Could not install main window event filter: {exc}")

        # Connect to project signals for cache management
        self._connect_signals()

    def _read_mission_store_path_from_project(self) -> Optional[str]:
        """Best-effort read of mission store path from project custom variables."""
        try:
            value = self.project.customVariables().get(self.MISSION_STORE_VAR)
            if value:
                return str(Path(str(value)).expanduser())
        except Exception as exc:
            print(f"[LayerManager] Warning: Could not read mission store path: {exc}")
        return None

    def _refresh_mission_store_path(self, *, emit_signal: bool = True) -> Optional[str]:
        """
        Refresh cached mission store path from the current project.

        Keeps LayerManager state correct when users open/close projects during a
        single QGIS session.
        """
        new_path = self._read_mission_store_path_from_project()
        if new_path == "":
            new_path = None
        if new_path != self._mission_store_path:
            old = self._mission_store_path
            self._mission_store_path = new_path
            if emit_signal:
                try:
                    self.mission_store_changed.emit(new_path or "")
                except Exception:
                    pass
            self._log("INFO", f"Mission store updated: {old} → {new_path}")
        return self._mission_store_path

    def on_project_read(self):
        """
        Notify LayerManager that the active project has changed or finished loading.

        Clears caches and refreshes project-backed state (mission store path).
        """
        with self._cache_lock:
            self._layer_cache.clear()
            self._group_cache.clear()
        self._layer_provider_uris.clear()
        self._refresh_mission_store_path(emit_signal=True)
        self._load_migration_state()

    def is_sar_project(self) -> bool:
        """
        Return True if the current project appears to be a SAR Tracker project.

        Used to avoid mutating unrelated user projects during startup.
        """
        try:
            custom_vars = self.project.customVariables()
        except Exception:
            custom_vars = {}

        try:
            if custom_vars.get(self.MISSION_STORE_VAR):
                return True
        except Exception:
            pass

        try:
            if custom_vars.get("sar_layer_schema"):
                return True
        except Exception:
            pass

        try:
            root = self.project.layerTreeRoot()
            sar_group = root.findGroup(GroupNames.ROOT) if root else None
            if sar_group:
                return True
        except Exception:
            pass

        return False

    def _load_migration_state(self):
        """Load persisted migration state for the current project."""
        try:
            migration_tracker.load_from_project(self.project)
        except Exception as exc:
            self._log("WARN", f"Failed to load migration state: {exc}")

    def _log(self, level: str, message: str):
        """Consistent logging helper for LayerManager."""
        try:
            print(f"[LayerManager][{level}] {message}")
        except Exception:
            # Avoid raising if stdout unavailable
            pass

    def _connect_signals(self):
        """Connect to project signals to manage cache lifecycle."""
        if not self._signals_connected:
            try:
                self.project.layersWillBeRemoved.connect(self._on_layers_removed)
                self._signals_connected = True
            except Exception as e:
                msg = f"Could not connect project signals: {e}"
                self._log("WARN", msg)
                try:
                    warning(self.iface.messageBar(), "Layer Manager", msg)
                except Exception:
                    pass

            # Detect full project clears (e.g., user discards project)
            try:
                self.project.cleared.connect(self._on_project_cleared)
                self._project_cleared_connected = True
            except Exception:
                # cleared not available in some QGIS versions
                self._project_cleared_connected = False

    def _load_mission_store_path(self) -> Optional[str]:
        """Read mission store path from project custom variables."""
        try:
            return self._read_mission_store_path_from_project()
        except Exception as exc:
            print(f"[LayerManager] Warning: Could not load mission store path: {exc}")
        return None

    def set_mission_store(self, path: str):
        """
        Configure the mission store GeoPackage path.

        Args:
            path: Absolute path to the mission GeoPackage file.
        """
        if not path or not isinstance(path, str):
            raise ValueError("Mission store path must be a non-empty string")

        normalized = str(Path(path).expanduser())
        target_dir = Path(normalized).parent
        try:
            target_dir.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            msg = f"Failed to prepare mission store directory '{target_dir}': {exc}"
            self._log("WARN", msg)
            try:
                error(self.iface.messageBar(), "Mission Store", msg)
            except Exception:
                # Best-effort notify; avoid raising further
                pass
            return

        try:
            self._set_project_variable(self.MISSION_STORE_VAR, normalized)
        except RuntimeError as exc:
            msg = f"{exc}"
            self._log("WARN", msg)
            try:
                error(self.iface.messageBar(), "Mission Store", msg)
            except Exception:
                pass
            return

        old_path = self._mission_store_path
        self._mission_store_path = normalized
        self._layer_provider_uris.clear()
        self._layer_cache.clear()

        # HIGH-7: Emit signal if path changed
        if old_path != normalized:
            print(f"[LayerManager] Mission store changed: {old_path} → {normalized}")
            self.mission_store_changed.emit(normalized)

    def get_mission_store(self) -> Optional[str]:
        """Return the configured mission store path, if any (refreshing from project)."""
        return self._refresh_mission_store_path(emit_signal=False)

    def clear_mission_store(self):
        """Remove the mission store association from the project."""
        try:
            self._set_project_variable(self.MISSION_STORE_VAR, "")
        except RuntimeError as exc:
            print(f"[LayerManager] Warning: {exc}")

        self._mission_store_path = None
        self._layer_provider_uris.clear()
        self._layer_cache.clear()

    # ------------------------------------------------------------------ #
    # Temporary Mission Store for Replay (Phase 3: SAR-604i)
    # ------------------------------------------------------------------ #

    def set_temp_mission_store(self, path: str) -> None:
        """
        Set a temporary mission store path for replay mode.

        The temp store takes priority over the regular mission store.
        This ensures replay data is isolated from live mission data.

        Args:
            path: Absolute path to the temporary GeoPackage file.
        """
        if not path:
            return

        normalized = str(Path(path).expanduser())
        target_dir = Path(normalized).parent

        try:
            target_dir.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            self._log("WARN", f"Failed to create temp store directory: {exc}")
            return

        old_path = self._temp_mission_store_path
        self._temp_mission_store_path = normalized

        # Clear caches when store changes (layers need to be recreated)
        if old_path != normalized:
            self._layer_provider_uris.clear()
            self._layer_cache.clear()
            self._log("INFO", f"Temp mission store set: {normalized}")

    def clear_temp_mission_store(self) -> None:
        """
        Clear the temporary mission store.

        After clearing, layers will route to the regular mission store
        (if configured) or memory.
        """
        if self._temp_mission_store_path:
            self._log("INFO", f"Clearing temp mission store: {self._temp_mission_store_path}")

        self._temp_mission_store_path = None
        self._layer_provider_uris.clear()
        self._layer_cache.clear()

    def get_temp_mission_store(self) -> Optional[str]:
        """Return the current temp mission store path, if any."""
        return self._temp_mission_store_path

    def _get_effective_store_path(self) -> Optional[str]:
        """
        Get the effective store path, considering temp store priority.

        Priority order:
        1. Temp mission store (for replay)
        2. Regular mission store (cached value)
        3. None (memory layers)

        Returns:
            The path to use for layer storage, or None for memory layers.
        """
        if self._temp_mission_store_path:
            return self._temp_mission_store_path
        # Use cached value for efficiency; project sync happens via refresh calls
        return self._mission_store_path

    def set_mission_finalized(self, finalized: bool, finalized_by: str = "", finalized_at: Optional[str] = None):
        """
        Persist mission finalized flag and metadata.

        Args:
            finalized: True to mark finalized, False to clear.
            finalized_by: Operator/admin name.
            finalized_at: ISO timestamp (optional, defaults to now when setting).
        """
        try:
            self._persist_finalized_state(finalized, finalized_by, finalized_at)
        except Exception as exc:
            print(f"[LayerManager] Warning: Failed to persist finalized flag: {exc}")

    def _persist_finalized_state(self, finalized: bool, finalized_by: str, finalized_at: Optional[str]):
        """Internal helper to persist finalized/read-only state safely."""
        project = QgsProject.instance()
        if finalized:
            timestamp = finalized_at or datetime.now(timezone.utc).isoformat()
            self._set_project_variable(self.MISSION_FINALIZED_VAR, "true")
            self._set_project_variable(self.MISSION_FINALIZED_BY_VAR, finalized_by or "")
            self._set_project_variable(self.MISSION_FINALIZED_AT_VAR, timestamp)
            self._set_layers_read_only(True)
        else:
            self._set_project_variable(self.MISSION_FINALIZED_VAR, "")
            self._set_project_variable(self.MISSION_FINALIZED_BY_VAR, "")
            self._set_project_variable(self.MISSION_FINALIZED_AT_VAR, "")
            self._set_layers_read_only(False)
        project.write()

    def is_mission_finalized(self) -> bool:
        """Return True if project is marked finalized."""
        project = QgsProject.instance()
        try:
            value = project.customVariables().get(self.MISSION_FINALIZED_VAR)
            return str(value).lower() == "true"
        except Exception:
            return False

    def is_read_only(self) -> bool:
        """Alias for finalized state to simplify controllers."""
        return self.is_mission_finalized()

    def _set_layers_read_only(self, read_only: bool):
        """
        Apply read-only state to all managed layers for extra defense in depth.
        Controllers also guard mutations, but layer flags prevent UI edits.
        """
        try:
            for layer in self.project.mapLayers().values():
                if isinstance(layer, QgsVectorLayer):
                    layer.setReadOnly(read_only)
        except Exception as exc:
            self._log("WARN", f"Failed to set layer read-only={read_only}: {exc}")

    def set_mission_coordinators(self, coordinators: str):
        """Persist coordinator roster for the current mission (comma-delimited)."""
        try:
            self._set_project_variable(self.MISSION_COORDINATORS_VAR, coordinators or "")
            QgsProject.instance().write()
        except Exception as exc:
            print(f"[LayerManager] Warning: Failed to persist mission coordinators: {exc}")

    def get_mission_coordinators(self) -> str:
        try:
            return QgsProject.instance().customVariables().get(self.MISSION_COORDINATORS_VAR, "") or ""
        except Exception:
            return ""

    def set_resume_timestamp(self, resume_iso: Optional[str]):
        """Persist custom resume timestamp (ISO format) if provided."""
        try:
            self._set_project_variable(self.MISSION_RESUME_TIME_VAR, resume_iso or "")
            QgsProject.instance().write()
        except Exception as exc:
            print(f"[LayerManager] Warning: Failed to persist resume timestamp: {exc}")

    def get_resume_timestamp(self) -> str:
        try:
            return QgsProject.instance().customVariables().get(self.MISSION_RESUME_TIME_VAR, "") or ""
        except Exception:
            return ""

    def _mission_store_enabled(self) -> bool:
        """Check if a mission store (temp or regular) is available."""
        # SAR-604i: Check temp store first (replay mode priority)
        if self._temp_mission_store_path:
            return True
        return bool(self._refresh_mission_store_path(emit_signal=False))

    def _notify_metadata_warning(self, message: str):
        """Best-effort helper to warn users about metadata issues."""
        try:
            warning(self.iface.messageBar(), "Catalog Metadata", message)
        except Exception:
            # Avoid raising if iface/messageBar is unavailable (e.g., tests)
            pass

    def _set_project_variable(self, key: str, value: Optional[str]):
        """
        Backwards-compatible helper to set/clear project custom variables.
        """
        try:
            setter = getattr(self.project, "setCustomVariable", None)
            if setter:
                setter(key, value or "")
                return

            variables = dict(self.project.customVariables() or {})
            if value:
                variables[key] = value
            else:
                variables.pop(key, None)
            self.project.setCustomVariables(variables)
        except Exception as exc:
            raise RuntimeError(f"Failed to persist project variable '{key}': {exc}")

    def _get_layer_tree_node(self, layer_id: str) -> Optional[QgsLayerTreeLayer]:
        """Return the layer tree node for a managed layer, if available."""
        layer = self.get_layer(layer_id)
        if not layer:
            return None

        root = self.project.layerTreeRoot()
        if not root:
            return None

        return root.findLayer(layer.id())

    def disconnect_signals(self):
        """Disconnect from project signals on cleanup.

        BUG-079 FIX: Added sip_isdeleted checks to prevent crashes when
        Qt objects have been deleted during QGIS shutdown.
        """
        # Import sip_isdeleted for safe C++ object access
        try:
            from ..utils.qt_compat import sip_isdeleted
        except ImportError:
            sip_isdeleted = lambda x: False  # Fallback - assume valid

        # BUG-079: Set application_closing flag FIRST to prevent callbacks
        self._application_closing = True

        if self._signals_connected:
            try:
                # BUG-079: Check project is valid before disconnecting
                if self.project and not sip_isdeleted(self.project):
                    self.project.layersWillBeRemoved.disconnect(self._on_layers_removed)
                self._signals_connected = False
            except (TypeError, RuntimeError):
                # Signal already disconnected or object deleted
                self._signals_connected = False
            except Exception as e:
                print(f"[LayerManager] Warning: Could not disconnect signals: {e}")
                self._signals_connected = False

        if self._project_cleared_connected:
            try:
                # BUG-079: Check project is valid before disconnecting
                if self.project and not sip_isdeleted(self.project):
                    self.project.cleared.disconnect(self._on_project_cleared)
            except (TypeError, RuntimeError):
                pass  # Signal already disconnected or object deleted
            except Exception as exc:
                self._log("WARN", f"Could not disconnect project cleared signal: {exc}")
            finally:
                self._project_cleared_connected = False

        if self._about_to_quit_connected:
            app = QCoreApplication.instance()
            if app and not sip_isdeleted(app):
                try:
                    app.aboutToQuit.disconnect(self._handle_app_about_to_quit)
                except (TypeError, RuntimeError):
                    pass  # Signal already disconnected or object deleted
                except Exception as exc:
                    self._log("WARN", f"Could not disconnect shutdown handler: {exc}")
            self._about_to_quit_connected = False

        if self._event_filter_installed and self._main_window:
            try:
                # BUG-079: Check main window is valid before removing filter
                if not sip_isdeleted(self._main_window):
                    self._main_window.removeEventFilter(self)
            except (TypeError, RuntimeError):
                pass  # Object already deleted
            except Exception as exc:
                self._log("WARN", f"Could not remove event filter: {exc}")
            finally:
                self._event_filter_installed = False
                self._main_window = None  # Clear reference

    def set_application_closing(self, closing: bool = True):
        """Allow external callers to mark that QGIS shutdown has started."""
        self._application_closing = closing

    def _handle_app_about_to_quit(self):
        """Qt aboutToQuit handler to prevent late-stage rebuilds."""
        self._application_closing = True

    def _on_layers_removed(self, layer_ids: List[str]):
        """
        Handle layer removal by clearing cache entries.

        Args:
            layer_ids: List of layer IDs being removed

        BUG-079 FIX: Added sip_isdeleted checks to prevent SIGSEGV when accessing
        layer objects whose C++ counterparts have been deleted during QGIS shutdown.
        """
        # CRITICAL: Skip during QGIS shutdown to prevent access violation crashes
        # During app exit, cached layer objects may have deleted C++ objects
        if self._application_closing:
            return

        # Import sip_isdeleted for safe C++ object access
        try:
            from ..utils.qt_compat import sip_isdeleted
        except ImportError:
            # Fallback if import fails - clear entire cache to be safe
            self._layer_cache.clear()
            return

        # BUG-079 FIX: Use list() to avoid dict modification during iteration
        # and check sip_isdeleted before accessing layer.id()
        # BUG-FIX: Use _cache_lock for thread safety (consistent with get_layer)
        with self._cache_lock:
            for layer_id in layer_ids:
                cache_keys_to_remove = []
                for k, v in list(self._layer_cache.items()):
                    try:
                        # BUG-079: Check if C++ object is still valid before accessing
                        if v is None or sip_isdeleted(v):
                            cache_keys_to_remove.append(k)
                            continue
                        if v.id() == layer_id:
                            cache_keys_to_remove.append(k)
                    except (RuntimeError, AttributeError, TypeError):
                        # BUG-079: Layer C++ object already deleted - mark for removal
                        cache_keys_to_remove.append(k)

                for key in cache_keys_to_remove:
                    try:
                        del self._layer_cache[key]
                        print(f"[LayerManager] Removed {key} from cache")
                    except KeyError:
                        pass  # Already removed

    def _on_project_cleared(self):
        """
        Handle QGIS project clear events.

        QGIS clears projects during startup and when opening different projects.
        The plugin must not rebuild/create SAR layers here, because doing so can
        mark a transient project dirty and trigger QGIS' "Do you want to save
        the current project?" prompt unexpectedly.

        BUG-079 FIX: Added additional safety checks during shutdown.
        """
        if self._application_closing:
            self._log("INFO", "Project cleared during application shutdown; skipping state refresh")
            # BUG-079: Clear caches immediately during shutdown to prevent stale references
            with self._cache_lock:
                self._layer_cache.clear()
                self._group_cache.clear()
            return

        try:
            print("[LayerManager] Project cleared detected; refreshing LayerManager state")
            self.on_project_read()
        except RuntimeError as exc:
            # BUG-079: C++ object deleted - this is expected during shutdown
            self._log("INFO", f"Project cleared during C++ teardown: {exc}")
        except Exception as exc:
            self._log("WARN", f"Failed to refresh state after project clear: {exc}")

    def eventFilter(self, obj, event):
        """Watch the QGIS main window for close events to detect shutdown earlier.

        BUG-079 FIX: Added safety checks to prevent crashes during Qt teardown.
        """
        # BUG-079: Skip if we're already closing to avoid unnecessary processing
        if self._application_closing:
            try:
                return super().eventFilter(obj, event)
            except (RuntimeError, TypeError):
                return False  # Object deleted

        if obj == self._main_window and event is not None:
            try:
                if event.type() == QEvent.Close:
                    self._application_closing = True
                    # BUG-079: Clear caches immediately on close to prevent stale access
                    with self._cache_lock:
                        self._layer_cache.clear()
                        self._group_cache.clear()
            except (RuntimeError, TypeError):
                # BUG-079: Qt object deleted - mark as closing
                self._application_closing = True
            except Exception:
                pass

        try:
            return super().eventFilter(obj, event)
        except (RuntimeError, TypeError):
            # BUG-079: Parent object deleted
            return False

    def ensure_structure(self, auto_migrate: bool = True) -> bool:
        """
        Ensure the complete SAR Tracker layer structure exists.

        Creates the root group and all nested groups/layers according to the
        schema. If the structure already exists, verifies and updates as needed.
        Handles migration from older schema versions.

        Args:
            auto_migrate: If True, automatically migrate older projects

        Returns:
            True if structure created/verified successfully, False otherwise
        """
        try:
            self._rename_legacy_root_group()

            # Check current schema version
            current_version = self._get_schema_version()

            if current_version is None:
                # New project or pre-schema project
                info(self.iface.messageBar(),
                     "Layer Setup",
                     "Creating SAR Tracker layer structure...")
                created = self._create_structure()
                if created:
                    self._set_schema_version(SAR_LAYER_SCHEMA_VERSION)
                self._organize_existing_layers()
                return created

            elif current_version != SAR_LAYER_SCHEMA_VERSION:
                # Schema version mismatch
                if auto_migrate:
                    warning(self.iface.messageBar(),
                           "Layer Migration",
                           f"Migrating layer structure from v{current_version} to v{SAR_LAYER_SCHEMA_VERSION}")
                    migrated = self._migrate_structure(current_version)
                    if migrated:
                        self._set_schema_version(SAR_LAYER_SCHEMA_VERSION)
                    self._organize_existing_layers()
                    return migrated
                else:
                    warning(self.iface.messageBar(),
                           "Schema Version",
                           f"Layer schema version mismatch (project: v{current_version}, plugin: v{SAR_LAYER_SCHEMA_VERSION})")
                    return False

            else:
                # Schema version matches - verify structure
                valid = self._verify_structure()
                self._organize_existing_layers()
                # Run migrations even when schema version matches to pick up
                # additive fields such as display_order.
                self._run_migrations()
                return valid

        except Exception as e:
            error(self.iface.messageBar(),
                  "Layer Setup Error",
                  f"Failed to ensure layer structure: {str(e)}")
            print(f"[LayerManager] Error in ensure_structure: {e}")
            import traceback
            traceback.print_exc()
            return False

    def _get_schema_version(self) -> Optional[int]:
        """
        Get the current schema version from project variables.

        Returns:
            Schema version number, or None if not set
        """
        try:
            custom_vars = self.project.customVariables()
            if 'sar_layer_schema' in custom_vars:
                return int(custom_vars['sar_layer_schema'])
            return None
        except (ValueError, KeyError):
            return None

    def _set_schema_version(self, version: int):
        """
        Set the schema version in project variables.

        Args:
            version: Schema version number to set
        """
        try:
            self._set_project_variable('sar_layer_schema', str(version))
            print(f"[LayerManager] Set schema version to {version}")
        except RuntimeError as e:
            print(f"[LayerManager] Warning: {e}")

    def _create_structure(self) -> bool:
        """
        Create the complete layer structure from scratch.

        Returns:
            True if successful, False otherwise
        """
        try:
            structure = get_expected_structure()
            self._create_group_recursive(structure)
            print("[LayerManager] Created complete layer structure")
            return True
        except Exception as e:
            print(f"[LayerManager] Error creating structure: {e}")
            import traceback
            traceback.print_exc()
            return False

    def _create_group_recursive(self, group_def: GroupDefinition, parent: Optional[QgsLayerTreeGroup] = None):
        """
        Recursively create groups and layers from a group definition.

        Args:
            group_def: Group definition to create
            parent: Parent group (None = root)
        """
        # Phase 4: Skip groups with auto_create=False (legacy groups)
        # These groups are kept in schema for backward compatibility but should
        # not be created for new missions. They will only exist if migrated data
        # is present.
        if not getattr(group_def, 'auto_create', True):
            return

        # Create the group using explicit parent path (supports nested groups)
        if group_def.parent_path:
            group_path = list(group_def.parent_path) + [group_def.name]
        else:
            group_path = [group_def.name]
        group = self.ensure_group(group_path, position=group_def.position)

        # Set group metadata
        if group_def.metadata:
            for key, value in group_def.metadata.items():
                group.setCustomProperty(key, value)

        # Create layers in this group
        if group_def.layers:
            for layer_def in group_def.layers:
                if layer_def.auto_create:
                    self.ensure_vector_layer(
                        layer_def=layer_def,
                        group_path=group_path
                    )

        # Create subgroups recursively
        if group_def.subgroups:
            for subgroup_def in group_def.subgroups:
                self._create_group_recursive(subgroup_def, group)

    def _verify_structure(self) -> bool:
        """
        Verify that the layer structure matches the schema.

        If the root group exists but individual layers are missing,
        this method will recreate them (idempotent operation).

        Returns:
            True if structure is valid, False otherwise
        """
        try:
            # Check root group exists
            root = self.project.layerTreeRoot()
            sar_group = root.findGroup(GroupNames.ROOT)
            if not sar_group:
                warning(self.iface.messageBar(),
                       "Layer Verification",
                       "Root group missing - use 'Repair Layers' in Settings")
                return False

            # CRITICAL FIX: Ensure all layers exist even when schema version matches
            # _create_group_recursive is idempotent - it only creates missing layers
            structure = get_expected_structure()
            self._create_group_recursive(structure)
            print("[LayerManager] Verified and ensured layer structure is complete")

            return True

        except Exception as e:
            print(f"[LayerManager] Error verifying structure: {e}")
            return False

    def _migrate_structure(self, from_version: int) -> bool:
        """
        Migrate layer structure from an older version.

        Args:
            from_version: Source schema version

        Returns:
            True if migration successful, False otherwise
        """
        try:
            print(f"[LayerManager] Migrating from schema version {from_version}")

            # Create any missing groups/layers
            structure = get_expected_structure()
            self._create_group_recursive(structure)

            # Run any additive migrations (e.g., new fields)
            self._run_migrations()

            return True

        except Exception as e:
            print(f"[LayerManager] Error during migration: {e}")
            import traceback
            traceback.print_exc()
            return False

    def ensure_group(self, path: List[str], position: int = 0) -> QgsLayerTreeGroup:
        """
        Ensure a group exists in the layer tree, creating it if necessary.

        This method is idempotent - safe to call multiple times.

        Args:
            path: List of group names from root to target (e.g., ['SAR Tracker', 'Helicopters'])
            position: Position within parent group (0 = top)

        Returns:
            QgsLayerTreeGroup object

        Raises:
            RuntimeError: If group creation fails
        """
        # Check cache first
        cache_key = "/".join(path)
        if cache_key in self._group_cache:
            cached_group = self._group_cache[cache_key]
            # Verify cached group still exists
            if self._group_exists(cached_group):
                return cached_group
            else:
                del self._group_cache[cache_key]

        # Navigate/create group hierarchy
        root = self.project.layerTreeRoot()
        current_parent = root
        current_path = []

        for group_name in path:
            current_path.append(group_name)
            path_key = "/".join(current_path)

            # Check if group exists
            group = current_parent.findGroup(group_name)
            if group and not self._group_exists(group):
                group = None

            if not group:
                # Create group
                group = current_parent.insertGroup(position, group_name)
                if not group:
                    raise RuntimeError(f"Failed to create group: {group_name}")
                print(f"[LayerManager] Created group: {path_key}")

            # Cache the group
            self._group_cache[path_key] = group
            current_parent = group

        return current_parent

    def _group_exists(self, group: QgsLayerTreeGroup) -> bool:
        """
        Check if a group still exists in the layer tree.

        Args:
            group: Group to check

        Returns:
            True if group exists, False otherwise
        """
        try:
            from ..utils.qt_compat import sip_isdeleted
        except Exception:
            sip_isdeleted = lambda _obj: False

        if group is None:
            return False

        try:
            if sip_isdeleted(group):
                return False
        except Exception:
            return False

        try:
            # Try to access a property - will fail if group deleted
            _ = group.name()
            return True
        except (RuntimeError, AttributeError, TypeError):
            return False

    def _run_migrations(self):
        """
        Run pending migrations on existing layers.

        Additive migrations are safe to re-run; each migration should be
        idempotent and skip if already applied.
        """
        try:
            from .migrations.add_display_order import run_migration
        except Exception as exc:  # ImportError or runtime issues
            print(f"[LayerManager] Warning: Could not import migrations: {exc}")
            return

        try:
            results = run_migration(self)
            if results.get('migrated'):
                self._log("INFO", f"Ran migrations on: {results['migrated']}")
            if results.get('failed'):
                self._log("WARN", f"Migrations failed for: {results['failed']}")
        except Exception as exc:
            self._log("WARN", f"Migration run failed: {exc}")

    def ensure_vector_layer(
        self,
        layer_def: LayerDefinition,
        group_path: List[str],
        style_factory: Optional[Callable[[QgsVectorLayer], None]] = None
    ) -> QgsVectorLayer:
        """
        Ensure a vector layer exists, creating it if necessary.

        This method is idempotent - safe to call multiple times.

        Args:
            layer_def: Layer definition from schema
            group_path: Path to parent group
            style_factory: Optional function to apply custom styling

        Returns:
            QgsVectorLayer object

        Raises:
            RuntimeError: If layer creation fails
        """
        # Check cache first
        if layer_def.layer_id in self._layer_cache:
            cached_layer = self._layer_cache[layer_def.layer_id]
            # Verify cached layer still exists
            if self._layer_exists(cached_layer):
                migrated_layer = self._migrate_existing_layer_if_needed(cached_layer, layer_def, group_path)
                self._layer_cache[layer_def.layer_id] = migrated_layer
                return migrated_layer
            else:
                del self._layer_cache[layer_def.layer_id]

        # Check if layer already exists in project
        existing_layer = self._find_layer_by_id(layer_def.layer_id)
        if existing_layer:
            migrated_layer = self._migrate_existing_layer_if_needed(existing_layer, layer_def, group_path)
            self._layer_cache[layer_def.layer_id] = migrated_layer
            return migrated_layer

        # Create new layer
        layer = self._create_vector_layer(layer_def)

        # Apply custom styling if provided
        if style_factory:
            try:
                style_factory(layer)
            except Exception as e:
                print(f"[LayerManager] Warning: Style factory failed: {e}")

        # Add layer to project and group
        group = self.ensure_group(group_path)
        self.project.addMapLayer(layer, False)  # Don't add to root
        group.insertLayer(layer_def.position, layer)

        # Set layer metadata
        if layer_def.metadata:
            for key, value in layer_def.metadata.items():
                layer.setCustomProperty(key, value)

        # Store layer ID for retrieval
        layer.setCustomProperty('sartracker:layer_id', layer_def.layer_id)

        # Cache the layer
        self._layer_cache[layer_def.layer_id] = layer

        print(f"[LayerManager] Created layer: {layer_def.name} ({layer_def.layer_id})")

        return layer

    def _migrate_existing_layer_if_needed(
        self,
        layer: QgsVectorLayer,
        layer_def: LayerDefinition,
        group_path: List[str]
    ) -> QgsVectorLayer:
        """
        Migrate an existing memory layer to mission store when persistence is enabled.

        Keeps legacy in-project memory layers from staying transient after mission
        storage becomes available.
        """
        if not layer:
            return layer

        try:
            provider = (layer.providerType() or "").lower()
        except Exception:
            provider = ""

        if provider != "memory" or not self._mission_store_enabled():
            return layer

        try:
            persistent_layer = self.migrate_memory_layer_to_store(layer, layer_def)
            self._replace_layer_in_project_tree(layer, persistent_layer, group_path, layer_def.position)
            return persistent_layer
        except Exception as exc:
            self._log("WARN", f"Failed to migrate existing memory layer '{layer_def.layer_id}': {exc}")
            try:
                warning(
                    self.iface.messageBar(),
                    "Mission Store",
                    f"Could not migrate '{layer_def.layer_id}' to mission store; continuing with memory layer.",
                    duration=5
                )
            except Exception:
                pass
            return layer

    def _replace_layer_in_project_tree(
        self,
        old_layer: QgsVectorLayer,
        new_layer: QgsVectorLayer,
        group_path: List[str],
        fallback_position: int
    ) -> None:
        """Replace old layer with new layer in the same tree location (best effort)."""
        if not old_layer or not new_layer:
            return

        root = self.project.layerTreeRoot()
        old_node = root.findLayer(old_layer.id()) if root else None
        parent_group = old_node.parent() if old_node and old_node.parent() else self.ensure_group(group_path)
        target_index = fallback_position
        if old_node and parent_group:
            try:
                target_index = parent_group.children().index(old_node)
            except Exception:
                target_index = fallback_position

        self.project.addMapLayer(new_layer, False)
        if parent_group:
            parent_group.insertLayer(target_index, new_layer)

        try:
            self.project.removeMapLayer(old_layer.id())
        except Exception:
            pass

    def _create_vector_layer(self, layer_def: LayerDefinition) -> QgsVectorLayer:
        """Create a layer backed by memory or the mission store."""
        if self._mission_store_enabled():
            try:
                return self._ensure_persistent_layer(layer_def)
            except Exception as exc:
                msg = f"Persistent layer failed for {layer_def.layer_id}: {exc}"
                self._log("WARN", msg)
                try:
                    warning(self.iface.messageBar(), "Mission Store", f"{msg}; using memory instead.")
                except Exception:
                    pass
        return self._create_memory_layer(layer_def)

    def _create_memory_layer(self, layer_def: LayerDefinition) -> QgsVectorLayer:
        """
        Create a QgsVectorLayer from a layer definition.

        Args:
            layer_def: Layer definition

        Returns:
            QgsVectorLayer object

        Raises:
            RuntimeError: If layer creation fails
        """
        # Create CRS
        crs = QgsCoordinateReferenceSystem(f"EPSG:{layer_def.crs_epsg}")
        if not crs.isValid():
            raise RuntimeError(f"Invalid CRS: EPSG:{layer_def.crs_epsg}")

        # Create layer URI
        uri = f"{layer_def.geometry_type}?crs=EPSG:{layer_def.crs_epsg}"

        # Create layer
        layer = QgsVectorLayer(uri, layer_def.name, "memory")
        if not layer.isValid():
            raise RuntimeError(f"Failed to create layer: {layer_def.name}")

        # Add fields
        if layer_def.fields:
            # BUG FIX: DATA-PERSIST-2 - Check startEditing() return value
            if not layer.startEditing():
                raise RuntimeError(f"Failed to start editing {layer_def.name} - layer may be locked or read-only")

            # BUG-041 FIX: Track edit state explicitly for robust error recovery
            edit_started = True
            commit_succeeded = False

            try:
                for field_def in layer_def.fields:
                    field = self._create_field(field_def)
                    if not layer.addAttribute(field):
                        raise RuntimeError(f"Failed to add field: {field_def['name']}")

                if not layer.commitChanges():
                    errors = layer.commitErrors()
                    raise RuntimeError(f"Failed to commit field changes: {errors}")

                commit_succeeded = True
                edit_started = False  # Edit session ended with commit

            except Exception as e:
                # BUG-041 FIX: Explicit rollback with error handling
                if edit_started:
                    try:
                        layer.rollBack()
                        edit_started = False
                    except Exception as rollback_error:
                        # Log rollback failure - layer may be in inconsistent state
                        print(f"BUG-041 WARNING: Rollback failed for {layer_def.name}: {rollback_error}")
                raise RuntimeError(f"Error adding fields: {e}")

            finally:
                # BUG-041 FIX: Safety net with explicit state check and logging
                # Ensure layer is NEVER left in edit mode (Issue #3 critical fix)
                if layer.isEditable():
                    print(f"BUG-041 WARNING: Layer {layer_def.name} still editable in finally - forcing rollback")
                    try:
                        layer.rollBack()
                    except Exception as final_rollback_error:
                        print(f"BUG-041 ERROR: Final rollback failed for {layer_def.name}: {final_rollback_error}")

        return layer

    def _ensure_mission_store_directory(self):
        """Ensure the directory containing the effective mission store exists."""
        # SAR-604i: Use effective path (temp store takes priority)
        effective_path = self._get_effective_store_path()
        if not effective_path:
            raise RuntimeError("Mission store path is not configured")
        Path(effective_path).parent.mkdir(parents=True, exist_ok=True)

    def _build_mission_store_uri(self, layer_def: LayerDefinition) -> str:
        """Construct and cache the provider URI for a mission-store layer."""
        if layer_def.layer_id in self._layer_provider_uris:
            return self._layer_provider_uris[layer_def.layer_id]

        # SAR-604i: Use effective path (temp store takes priority)
        effective_path = self._get_effective_store_path()
        if not effective_path:
            raise RuntimeError("Mission store path is not configured")

        # OGR provider expects the canonical "<path>|layername=<table>" syntax for GeoPackage layers.
        # Using QgsDataSourceUri yields a PostGIS-style connection string that the ogr provider
        # does not understand, which in turn produces invalid layers and forces a fallback to memory.
        path = Path(effective_path).as_posix()
        uri = f"{path}|layername={layer_def.layer_id}"

        self._layer_provider_uris[layer_def.layer_id] = uri
        return uri

    def _load_persistent_layer(self, layer_def: LayerDefinition) -> Optional[QgsVectorLayer]:
        """Try to load an existing GeoPackage layer."""
        # SAR-604i: Use effective path (temp store takes priority)
        if not self._get_effective_store_path():
            return None

        uri = self._build_mission_store_uri(layer_def)
        layer = QgsVectorLayer(uri, layer_def.name, self.MISSION_STORE_PROVIDER)
        if layer.isValid():
            layer.setCustomProperty('sartracker:layer_id', layer_def.layer_id)
            return layer

        return None

    def _create_persistent_table(self, layer_def: LayerDefinition):
        """Create an empty GeoPackage table for the layer definition."""
        self._ensure_mission_store_directory()
        template_layer = self._create_memory_layer(layer_def)

        options = _create_save_vector_options()
        options.driverName = self.MISSION_STORE_DRIVER
        options.layerName = layer_def.layer_id
        options.fileEncoding = "UTF-8"
        options.onlySelectedFeatures = False
        _set_option_if_available(options, "includeMetadata", True)
        _set_option_if_available(options, "overwriteWithEmptyLayer", True)

        # SAR-604i: Use effective path (temp store takes priority)
        effective_path = self._get_effective_store_path()
        mission_store_exists = Path(effective_path).exists()
        if hasattr(options, "actionOnExistingFile"):
            if mission_store_exists:
                options.actionOnExistingFile = _EXPORT_CREATE_OR_OVERWRITE_LAYER
            else:
                options.actionOnExistingFile = _EXPORT_CREATE_OR_OVERWRITE_FILE

        export_result = _export_layer(
            template_layer,
            effective_path,
            options,
            QgsCoordinateTransformContext()
        )

        if isinstance(export_result, tuple):
            if len(export_result) == 3:
                result, error_message, _ = export_result
            elif len(export_result) == 2:
                result, error_message = export_result
            else:
                # Unexpected signature; best effort
                result = export_result[0]
                error_message = export_result[1] if len(export_result) > 1 else ""
        else:
            result = export_result
            error_message = ""

        if result != _EXPORT_NO_ERROR:
            raise RuntimeError(
                f"Failed to create persistent layer '{layer_def.layer_id}': {error_message}"
            )

    def _ensure_persistent_layer(self, layer_def: LayerDefinition) -> QgsVectorLayer:
        """Ensure a GeoPackage-backed layer exists and return it."""
        layer = self._load_persistent_layer(layer_def)
        if layer:
            return layer

        self._create_persistent_table(layer_def)
        layer = self._load_persistent_layer(layer_def)
        if not layer or not layer.isValid():
            raise RuntimeError(f"Persistent layer '{layer_def.layer_id}' could not be loaded")
        return layer

    def _create_field(self, field_def: Dict) -> QgsField:
        """
        Create a QgsField from a field definition.

        Args:
            field_def: Field definition dictionary

        Returns:
            QgsField object
        """
        field_name = field_def["name"]
        field_type_str = field_def["type"]
        field_length = field_def.get("length", 0)

        # Map type string to QVariant type code
        qt_type = QT_TYPE_MAP.get(field_type_str, 10)  # Default to String

        return QgsField(field_name, qt_type, field_type_str, field_length)

    def _find_layer_by_id(self, layer_id: str) -> Optional[QgsVectorLayer]:
        """
        Find a layer in the project by its SAR Tracker layer ID.

        Args:
            layer_id: SAR Tracker layer ID

        Returns:
            QgsVectorLayer if found, None otherwise
        """
        for layer in self.project.mapLayers().values():
            if isinstance(layer, QgsVectorLayer):
                stored_id = layer.customProperty('sartracker:layer_id')
                if stored_id == layer_id:
                    return layer
        return None

    def _layer_exists(self, layer: QgsVectorLayer) -> bool:
        """
        Check if a layer still exists in the project.

        Args:
            layer: Layer to check

        Returns:
            True if layer exists, False otherwise
        """
        try:
            return layer.id() in self.project.mapLayers()
        except:
            return False

    def get_layer(self, layer_id: str) -> Optional[QgsVectorLayer]:
        """
        Get a layer by its SAR Tracker layer ID.

        BUG-044 FIX: Uses _cache_lock for thread-safe cache access.

        Args:
            layer_id: SAR Tracker layer ID from LayerIds

        Returns:
            QgsVectorLayer if found, None otherwise
        """
        # BUG-044 FIX: Thread-safe cache access
        with self._cache_lock:
            # Check cache first
            if layer_id in self._layer_cache:
                cached_layer = self._layer_cache[layer_id]
                if self._layer_exists(cached_layer):
                    return cached_layer
                else:
                    del self._layer_cache[layer_id]

            # Search project
            layer = self._find_layer_by_id(layer_id)
            if layer:
                self._layer_cache[layer_id] = layer

            return layer

    def ensure_persistent_layer(self, layer_id: str) -> QgsVectorLayer:
        """
        Ensure a mission-store backed layer exists and return it.

        Args:
            layer_id: SAR Tracker layer ID

        Returns:
            QgsVectorLayer backed by the mission store
        """
        layer_def = get_layer_by_id(layer_id)
        if not layer_def:
            raise ValueError(f"Unknown layer id: {layer_id}")
        if not self._mission_store_enabled():
            raise RuntimeError("Mission store is not configured")
        return self._ensure_persistent_layer(layer_def)

    def get_helicopter_layer(self, slot: int) -> Optional[QgsVectorLayer]:
        """
        Get a helicopter layer by slot number (1-4).

        Args:
            slot: Helicopter slot number (1-4)

        Returns:
            QgsVectorLayer if found, None otherwise

        Raises:
            ValueError: If slot number invalid
        """
        if not 1 <= slot <= 4:
            raise ValueError(f"Invalid helicopter slot: {slot}. Must be 1-4.")

        layer_id = getattr(LayerIds, f"HELICOPTER_{slot}")
        return self.get_layer(layer_id)

    def repair_structure(self) -> bool:
        """
        Repair the layer structure by recreating missing groups/layers.

        Returns:
            True if repair successful, False otherwise
        """
        try:
            info(self.iface.messageBar(),
                 "Layer Repair",
                 "Repairing SAR Tracker layer structure...")

            # Clear caches
            self._layer_cache.clear()
            self._group_cache.clear()

            # Recreate structure (rebuild groups + auto-created layers)
            success = self._create_structure()

            if success:
                self._set_schema_version(SAR_LAYER_SCHEMA_VERSION)
                self._organize_existing_layers()
                info(self.iface.messageBar(),
                     "Layer Repair",
                     "Layer structure repaired successfully")
            else:
                error(self.iface.messageBar(),
                      "Layer Repair",
                      "Failed to repair layer structure")

            return success

        except Exception as e:
            error(self.iface.messageBar(),
                  "Layer Repair Error",
                  f"Error repairing structure: {str(e)}")
            print(f"[LayerManager] Error in repair_structure: {e}")
            import traceback
            traceback.print_exc()
            return False

    def ensure_structure_async(
        self,
        task_manager,
        auto_migrate: bool = True,
        on_complete: Optional[Callable[[bool], None]] = None,
        on_error: Optional[Callable[[Exception], None]] = None
    ):
        """
        Run ensure_structure with optional TaskManager to avoid blocking the UI.

        Falls back to synchronous execution if tasks are unavailable.
        """
        return self._run_on_ui_thread(
            description="Ensure SAR Tracker layer structure",
            func=lambda: self.ensure_structure(auto_migrate=auto_migrate),
            on_complete=on_complete,
            on_error=on_error
        )

    def repair_structure_async(
        self,
        task_manager,
        on_complete: Optional[Callable[[bool], None]] = None,
        on_error: Optional[Callable[[Exception], None]] = None
    ):
        """
        Run repair_structure with optional TaskManager to avoid blocking the UI.

        Falls back to synchronous execution if tasks are unavailable.
        """
        return self._run_on_ui_thread(
            description="Repair SAR Tracker layer structure",
            func=self.repair_structure,
            on_complete=on_complete,
            on_error=on_error
        )

    def _run_on_ui_thread(
        self,
        description: str,
        func: Callable[[], bool],
        on_complete: Optional[Callable[[bool], None]],
        on_error: Optional[Callable[[Exception], None]]
    ):
        """
        Schedule a layer operation on the UI thread (QGIS layer API requirement).
        """
        def _runner():
            if getattr(self, "_application_closing", False):
                return False
            try:
                result = func()
                if on_complete:
                    on_complete(result)
                return result
            except Exception as exc:
                if on_error:
                    on_error(exc)
                else:
                    self._log("WARN", f"{description} failed: {exc}")
                return False

        try:
            QTimer.singleShot(0, _runner)
            return True
        except Exception as exc:
            self._log("WARN", f"Failed to schedule '{description}' on UI thread: {exc}")
            return _runner()

    def _run_task_or_sync(
        self,
        description: str,
        func: Callable[[], bool],
        task_manager,
        on_complete: Optional[Callable[[bool], None]],
        on_error: Optional[Callable[[Exception], None]]
    ):
        """
        Helper to run a function via TaskManager if available, otherwise sync.
        """
        if task_manager is None:
            try:
                result = func()
                if on_complete:
                    on_complete(result)
                return result
            except Exception as exc:
                if on_error:
                    on_error(exc)
                    return False
                raise

        try:
            from qgis.core import QgsTask
        except Exception:
            print("[LayerManager] Warning: QgsTask not available; running synchronously")
            return self._run_task_or_sync(description, func, None, on_complete, on_error)

        create_task = getattr(QgsTask, "fromFunction", None)
        if not create_task:
            print("[LayerManager] Warning: QgsTask.fromFunction missing; running synchronously")
            return self._run_task_or_sync(description, func, None, on_complete, on_error)

        def _runner(_task):
            try:
                return func()
            except Exception as exc:
                _task.setProperty("sartracker:error", exc)
                return False

        def _finished(_task, result):
            if getattr(self, "_application_closing", False):
                return
            if result:
                if on_complete:
                    on_complete(result)
            else:
                exc = getattr(_task, "property", lambda _k: None)("sartracker:error") if hasattr(_task, "property") else None
                if on_error:
                    on_error(exc or RuntimeError(f"{description} failed"))
                else:
                    self._log("WARN", f"{description} failed: {exc}")

        try:
            task = create_task(description, _runner, on_finished=_finished)
            task_manager.start_task(task)
            return True
        except Exception as exc:
            self._log("WARN", f"Failed to start task '{description}': {exc}")
            return self._run_task_or_sync(description, func, None, on_complete, on_error)

    def migrate_memory_layer_to_store(self, layer: QgsVectorLayer, layer_def: LayerDefinition) -> QgsVectorLayer:
        """
        Export an existing memory layer into the mission store.

        BUG-062 FIX: Enhanced validation and error handling for safer migration.

        Args:
            layer: Source memory-backed layer
            layer_def: Target schema definition

        Returns:
            The newly created persistent layer

        Raises:
            RuntimeError: If migration fails
            ValueError: If layer is invalid for migration
        """
        if not self._mission_store_enabled():
            raise RuntimeError("Mission store is not configured")

        if not layer or layer.providerType() != "memory":
            raise ValueError("Only memory layers can be migrated")

        # BUG-062 FIX: Pre-migration validation
        if not layer.isValid():
            logger.error("BUG-062: Cannot migrate invalid layer '%s'", layer_def.layer_id)
            raise ValueError(f"Layer '{layer_def.layer_id}' is not valid")

        source_feature_count = layer.featureCount()
        logger.info(
            "BUG-062: Starting migration of layer '%s' with %d features",
            layer_def.layer_id, source_feature_count
        )

        options = _create_save_vector_options()
        options.driverName = self.MISSION_STORE_DRIVER
        options.layerName = layer_def.layer_id
        if hasattr(options, "actionOnExistingFile"):
            options.actionOnExistingFile = _EXPORT_CREATE_OR_OVERWRITE_LAYER
        options.fileEncoding = "UTF-8"
        _set_option_if_available(options, "includeMetadata", True)

        # SAR-604i: Use effective path (temp store takes priority)
        effective_path = self._get_effective_store_path()
        if not effective_path:
            raise RuntimeError("Mission store path is not configured")

        export_result = _export_layer(
            layer,
            effective_path,
            options,
            self.project.transformContext()
        )

        if isinstance(export_result, tuple):
            if len(export_result) == 3:
                result, error_message, _ = export_result
            elif len(export_result) == 2:
                result, error_message = export_result
            else:
                result = export_result[0]
                error_message = export_result[1] if len(export_result) > 1 else ""
        else:
            result = export_result
            error_message = ""

        if result != _EXPORT_NO_ERROR:
            # BUG-062 FIX: Enhanced error logging
            logger.error(
                "BUG-062: Layer migration failed for '%s': %s (error code: %s)",
                layer_def.layer_id, error_message, result
            )
            raise RuntimeError(
                f"Failed to migrate layer '{layer_def.layer_id}' to mission store: {error_message}"
            )

        persistent_layer = self._load_persistent_layer(layer_def)
        if not persistent_layer:
            logger.error("BUG-062: Failed to load persistent layer '%s' after migration", layer_def.layer_id)
            raise RuntimeError(f"Persistent layer '{layer_def.layer_id}' could not be loaded after migration")

        # BUG-062 FIX: Post-migration validation - verify feature count
        target_feature_count = persistent_layer.featureCount()
        if target_feature_count != source_feature_count:
            logger.warning(
                "BUG-062: Feature count mismatch after migration of '%s': "
                "source=%d, target=%d - possible data loss",
                layer_def.layer_id, source_feature_count, target_feature_count
            )

        style = QgsMapLayerStyle()
        if style.readFromLayer(layer):
            style.writeToLayer(persistent_layer)

        persistent_layer.setCustomProperty('sartracker:layer_id', layer_def.layer_id)
        persistent_layer.triggerRepaint()

        logger.info(
            "BUG-062: Successfully migrated layer '%s' with %d features",
            layer_def.layer_id, target_feature_count
        )
        return persistent_layer

    def route_feature(self, category: str, feature):
        """
        Route a feature to the appropriate layer based on category.

        Args:
            category: Artifact category (e.g., 'clue', 'marker_ipp_lkp')
            feature: QgsFeature to add

        Raises:
            ValueError: If category is invalid
            RuntimeError: If feature addition fails
        """
        from .schema import ARTIFACT_LAYER_MAP

        if category not in ARTIFACT_LAYER_MAP:
            raise ValueError(f"Unknown artifact category: {category}")

        layer_id = ARTIFACT_LAYER_MAP[category]
        layer = self.get_layer(layer_id)

        if not layer:
            raise RuntimeError(f"Layer not found for category: {category}")

        try:
            # Add feature to layer (BUG FIX: DATA-PERSIST-2)
            if not layer.startEditing():
                raise RuntimeError(f"Failed to start editing {layer.name()} - layer may be locked or read-only")

            if not layer.addFeature(feature):
                raise RuntimeError(f"Failed to add feature to layer: {layer.name()}")

            if not layer.commitChanges():
                errors = layer.commitErrors()
                raise RuntimeError(f"Failed to commit changes: {errors}")

        except Exception as e:
            try:
                error(self.iface.messageBar(), "Add Feature Failed", str(e))
            except Exception:
                pass
            try:
                layer.rollBack()
            except Exception:
                pass
            raise

        finally:
            # Safety net: Ensure layer is NEVER left in edit mode (Issue #3 critical fix)
            if layer.isEditable():
                layer.rollBack()

    def validate_persistence(self, quiet: bool = False) -> Dict[str, str]:
        """
        Validate that managed layers are backed by non-memory providers.

        Returns:
            Dict mapping layer_ids to issue description (empty if healthy)
        """
        issues: Dict[str, str] = {}
        if not self._mission_store_enabled():
            if not quiet:
                warning(self.iface.messageBar(),
                        "Mission Store",
                        "Mission store is not configured; layers remain in memory.")
            issues["mission_store"] = "not_configured"
            return issues

        missing_layers: List[str] = []
        memory_layers: List[str] = []

        for layer_def in self._collect_layer_definitions():
            layer = self.get_layer(layer_def.layer_id)
            if not layer:
                issues[layer_def.layer_id] = "missing"
                missing_layers.append(layer_def.layer_id)
                continue

            provider = (layer.providerType() or "").lower()
            if provider == "memory":
                issues[layer_def.layer_id] = "memory"
                memory_layers.append(layer_def.layer_id)

        if issues:
            if not quiet:
                details = []
                if missing_layers:
                    details.append(f"missing: {', '.join(missing_layers)}")
                if memory_layers:
                    details.append(f"in memory: {', '.join(memory_layers)}")
                warning(self.iface.messageBar(),
                        "Persistence Diagnostics",
                        f"{len(issues)} layer(s) need attention ({'; '.join(details)})")
        else:
            if not quiet:
                info(self.iface.messageBar(),
                     "Persistence Diagnostics",
                     "All managed layers use persistent providers.")

        return issues

    def clear_cache(self):
        """
        Clear all cached layer and group references.

        BUG-044 FIX: Uses _cache_lock for thread-safe cache clearing.
        """
        with self._cache_lock:
            self._layer_cache.clear()
            self._group_cache.clear()
        self._log("INFO", "Cleared layer cache")

    # ------------------------------------------------------------------
    # Catalog Metadata Management (Phase 1 - CalTopo Console)
    # ------------------------------------------------------------------

    def get_layer_metadata(self, layer_id: str) -> Optional[Dict[str, Any]]:
        """
        Retrieve catalog metadata for a layer (thread-safe, with sync verification).

        Checks both storage locations and repairs sync drift if detected.
        Layer properties are the source of truth.

        Args:
            layer_id: Layer identifier (from LayerIds)

        Returns:
            Dictionary with metadata or None if not found

        Example return value:
            {
                "alias": "Initial Info",
                "display_order": 10,
                "favorite": True,
                "last_user": "Coordinator Smith",
                "updated_at": "2025-02-10T21:03:54Z"
            }
        """
        with self._metadata_lock:
            layer_metadata = None
            project_metadata = None
            parse_warning_emitted = False

            # Read from layer tree node custom property (new source of truth)
            node = self._get_layer_tree_node(layer_id)
            if node:
                metadata_json = node.customProperty('sartracker:catalog_meta')
                if metadata_json:
                    try:
                        layer_metadata = json.loads(metadata_json)
                        layer_metadata = self._migrate_datetime_timezone(layer_metadata, layer_id)
                    except (json.JSONDecodeError, TypeError) as e:
                        print(f"[LayerManager] Failed to parse layer tree metadata for {layer_id}: {e}")
                        if not parse_warning_emitted:
                            self._notify_metadata_warning(f"Layer metadata for {layer_id} is corrupt; using project fallback.")
                            parse_warning_emitted = True

            # Read from layer custom property (legacy storage for backward compatibility)
            layer = self.get_layer(layer_id)
            if layer:
                metadata_json = layer.customProperty('sartracker:catalog_meta')
                if metadata_json and not layer_metadata:
                    try:
                        layer_metadata = json.loads(metadata_json)
                        # CRITICAL FIX: Migrate naive datetimes to timezone-aware
                        layer_metadata = self._migrate_datetime_timezone(layer_metadata, layer_id)
                        # Migrate legacy location into layer tree node for persistence
                        if node and layer_metadata:
                            try:
                                node.setCustomProperty('sartracker:catalog_meta', json.dumps(layer_metadata))
                            except Exception as migrate_exc:
                                print(f"[LayerManager] Warning: Could not migrate metadata to layer tree: {migrate_exc}")
                    except (json.JSONDecodeError, TypeError) as e:
                        print(f"[LayerManager] Failed to parse layer metadata for {layer_id}: {e}")
                        if not parse_warning_emitted:
                            self._notify_metadata_warning(f"Layer metadata for {layer_id} is corrupt; using project fallback.")
                            parse_warning_emitted = True

            # Read from project variable (fallback storage)
            project = QgsProject.instance()
            if project:
                var_name = f"sartracker:layer_meta:{layer_id}"
                metadata_json = project.readEntry("SARTracker", var_name)[0]
                if metadata_json:
                    try:
                        project_metadata = json.loads(metadata_json)
                        # CRITICAL FIX: Migrate naive datetimes to timezone-aware
                        project_metadata = self._migrate_datetime_timezone(project_metadata, layer_id)
                    except (json.JSONDecodeError, TypeError) as e:
                        print(f"[LayerManager] Failed to parse project metadata for {layer_id}: {e}")
                        if not parse_warning_emitted:
                            self._notify_metadata_warning(f"Project metadata for {layer_id} is corrupt.")
                            parse_warning_emitted = True

            # Repair missing layer/node metadata from project fallback when possible
            if project_metadata and not layer_metadata:
                metadata_json = json.dumps(project_metadata)
                if node:
                    try:
                        node.setCustomProperty('sartracker:catalog_meta', metadata_json)
                    except Exception as migrate_exc:
                        print(f"[LayerManager] Warning: Could not write metadata to layer tree: {migrate_exc}")
                if layer:
                    try:
                        layer.setCustomProperty('sartracker:catalog_meta', metadata_json)
                    except Exception as migrate_exc:
                        print(f"[LayerManager] Warning: Could not write metadata to layer: {migrate_exc}")
                layer_metadata = project_metadata

            # CRITICAL FIX: Check for sync drift and repair
            if layer_metadata and project_metadata:
                if layer_metadata != project_metadata:
                    print(f"[LayerManager] WARNING: Metadata out of sync for {layer_id}")
                    print(f"  Layer property: {layer_metadata}")
                    print(f"  Project variable: {project_metadata}")

                    # Layer property is source of truth - repair project variable
                    try:
                        self._repair_project_metadata(layer_id, layer_metadata)
                    except Exception as e:
                        print(f"[LayerManager] Warning: Could not repair sync: {e}")

            # Return layer metadata (source of truth) or fall back to project
            return layer_metadata or project_metadata

    def set_layer_metadata(self, layer_id: str, metadata: Dict[str, Any]) -> None:
        """
        Store catalog metadata for a layer (thread-safe).

        Writes to BOTH layer custom properties and project variables
        for redundancy.

        Args:
            layer_id: Layer identifier (from LayerIds)
            metadata: Dictionary with metadata to store

        Raises:
            ValueError: If layer_id is invalid or metadata is malformed
            RuntimeError: If write fails
        """
        with self._metadata_lock:
            # Validate inputs
            if not layer_id or not isinstance(layer_id, str):
                raise ValueError("layer_id must be a non-empty string")

            # HIGH-2: Validate layer_id against schema
            if layer_id not in VALID_LAYER_IDS:
                raise ValueError(
                    f"Unknown layer_id: '{layer_id}'. "
                    f"Must be one of: {', '.join(sorted(VALID_LAYER_IDS)[:5])}... "
                    f"(see layers.schema.LayerIds)"
                )

            if not isinstance(metadata, dict):
                raise ValueError("metadata must be a dictionary")

            # CRITICAL-8: Sanitize metadata for JSON serialization
            metadata_to_save = self._sanitize_metadata(metadata.copy())

            # Add timestamp if not present (using timezone-aware datetime)
            if 'updated_at' not in metadata_to_save:
                metadata_to_save['updated_at'] = datetime.now(timezone.utc).isoformat()

            # Serialize to JSON (should never fail after sanitization)
            try:
                metadata_json = json.dumps(metadata_to_save)
            except (TypeError, ValueError) as e:
                # This should rarely happen after sanitization
                # Try to identify problematic field
                problem_fields = []
                for key, value in metadata_to_save.items():
                    try:
                        json.dumps({key: value})
                    except (TypeError, ValueError):
                        problem_fields.append(f"{key} ({type(value).__name__})")

                error_msg = f"Failed to serialize metadata: {e}"
                if problem_fields:
                    error_msg += f"\nProblematic fields: {', '.join(problem_fields)}"
                error_msg += "\nEnsure all values are JSON-serializable (str, int, float, bool, list, dict, None)"
                raise ValueError(error_msg)

            # BEST-EFFORT WRITE: Track success for all storage locations
            layer_tree_write_success = False
            layer_write_success = False
            project_write_success = False

            # Write to layer tree node custom property (primary storage)
            node = self._get_layer_tree_node(layer_id)
            if node:
                try:
                    node.setCustomProperty('sartracker:catalog_meta', metadata_json)
                    layer_tree_write_success = True
                    print(f"[LayerManager] Wrote catalog metadata to layer tree node {layer_id}")
                except Exception as e:
                    print(f"[LayerManager] ERROR: Failed to write layer tree custom property: {e}")
            else:
                print(f"[LayerManager] Warning: Layer tree node not found for {layer_id}")

            # Write to layer custom property (legacy compatibility)
            layer = self.get_layer(layer_id)
            if layer:
                try:
                    layer.setCustomProperty('sartracker:catalog_meta', metadata_json)
                    layer_write_success = True
                    print(f"[LayerManager] Wrote catalog metadata to layer {layer_id}")
                except Exception as e:
                    print(f"[LayerManager] ERROR: Failed to write layer custom property: {e}")
            else:
                print(f"[LayerManager] Warning: Layer {layer_id} not found, only writing to project variables")

            # Write to project variable (fallback storage)
            project = QgsProject.instance()
            if project:
                try:
                    var_name = f"sartracker:layer_meta:{layer_id}"
                    project.writeEntry("SARTracker", var_name, metadata_json)
                    project_write_success = True
                    print(f"[LayerManager] Wrote catalog metadata to project variable {var_name}")
                except Exception as e:
                    print(f"[LayerManager] ERROR: Failed to write project variable: {e}")

            # Check results - fail only if ALL writes failed
            if not layer_tree_write_success and not layer_write_success and not project_write_success:
                raise RuntimeError(f"Failed to write metadata to ANY storage location for {layer_id}")

            # Warn if storage is out of sync
            if (layer_tree_write_success != layer_write_success) or (layer_tree_write_success != project_write_success):
                print(f"[LayerManager] WARNING: Metadata storage out of sync for {layer_id}")
                print(f"  Layer tree: {'written' if layer_tree_write_success else 'FAILED'}")
                print(f"  Layer property: {'written' if layer_write_success else 'FAILED'}")
                print(f"  Project variable: {'written' if project_write_success else 'FAILED'}")
                print(f"  CRITICAL-7 sync repair will fix this on next read")
                # Don't raise - allow partial success (life-safety: better than complete failure)

    def clear_layer_metadata(self, layer_id: str) -> None:
        """
        Clear catalog metadata for a layer (thread-safe).

        Removes from both layer properties and project variables.

        Args:
            layer_id: Layer identifier (from LayerIds)
        """
        with self._metadata_lock:
            # Clear layer tree property
            node = self._get_layer_tree_node(layer_id)
            if node:
                try:
                    node.removeCustomProperty('sartracker:catalog_meta')
                    print(f"[LayerManager] Cleared catalog metadata from layer tree node {layer_id}")
                except Exception as e:
                    print(f"[LayerManager] Warning: Failed to clear layer tree property: {e}")

            # Clear layer custom property (legacy)
            layer = self.get_layer(layer_id)
            if layer:
                try:
                    layer.removeCustomProperty('sartracker:catalog_meta')
                    print(f"[LayerManager] Cleared catalog metadata from layer {layer_id}")
                except Exception as e:
                    print(f"[LayerManager] Warning: Failed to clear layer property: {e}")

            # Clear project variable
            project = QgsProject.instance()
            if project:
                try:
                    var_name = f"sartracker:layer_meta:{layer_id}"
                    project.removeEntry("SARTracker", var_name)
                    print(f"[LayerManager] Cleared catalog metadata from project variable {var_name}")
                except Exception as e:
                    print(f"[LayerManager] Warning: Failed to clear project variable: {e}")

    def _repair_project_metadata(self, layer_id: str, correct_metadata: Dict[str, Any]) -> None:
        """
        Repair out-of-sync project variable metadata.

        When layer property and project variable are out of sync, this method
        repairs the project variable to match the layer property (source of truth).

        Args:
            layer_id: Layer identifier
            correct_metadata: Correct metadata from layer property (source of truth)
        """
        project = QgsProject.instance()
        if not project:
            return

        try:
            var_name = f"sartracker:layer_meta:{layer_id}"
            metadata_json = json.dumps(correct_metadata)
            project.writeEntry("SARTracker", var_name, metadata_json)
            print(f"[LayerManager] Repaired project variable for {layer_id}")
        except Exception as e:
            print(f"[LayerManager] Failed to repair project metadata: {e}")

    # BUG-043 FIX: Maximum metadata size to prevent memory exhaustion
    MAX_METADATA_SIZE = 100000  # 100KB max serialized size
    MAX_METADATA_KEYS = 100     # Maximum number of keys in metadata dict
    MAX_STRING_LENGTH = 10000   # Maximum string value length

    def _sanitize_metadata(self, metadata: Dict[str, Any]) -> Dict[str, Any]:
        """
        Sanitize metadata for JSON serialization.

        Converts non-serializable types to serializable equivalents.
        Skips fields that cannot be converted.

        BUG-043 FIX: Added size limits and validation to prevent memory
        exhaustion and potential injection attacks.

        Args:
            metadata: Metadata dictionary (may contain non-serializable types)

        Returns:
            Sanitized metadata dictionary (all values JSON-serializable)
        """
        # BUG-043 FIX: Validate input type
        if not isinstance(metadata, dict):
            print(f"[LayerManager] BUG-043: Invalid metadata type: {type(metadata).__name__}")
            return {}

        # BUG-043 FIX: Limit number of keys to prevent DoS
        if len(metadata) > self.MAX_METADATA_KEYS:
            print(f"[LayerManager] BUG-043: Truncating metadata from {len(metadata)} to {self.MAX_METADATA_KEYS} keys")
            metadata = dict(list(metadata.items())[:self.MAX_METADATA_KEYS])

        sanitized = {}

        for key, value in metadata.items():
            # BUG-043 FIX: Validate key is a string
            if not isinstance(key, str):
                print(f"[LayerManager] BUG-043: Skipping non-string key: {type(key).__name__}")
                continue

            # Handle datetime objects
            if isinstance(value, datetime):
                sanitized[key] = value.isoformat()

            # Handle basic JSON-serializable types
            elif isinstance(value, (str, int, float, bool, type(None))):
                # BUG-043 FIX: Truncate oversized strings
                if isinstance(value, str) and len(value) > self.MAX_STRING_LENGTH:
                    print(f"[LayerManager] BUG-043: Truncating string field '{key}' from {len(value)} to {self.MAX_STRING_LENGTH} chars")
                    value = value[:self.MAX_STRING_LENGTH]
                sanitized[key] = value

            # Handle lists (recursive sanitization)
            elif isinstance(value, list):
                try:
                    sanitized[key] = [self._sanitize_value(item) for item in value]
                except ValueError:
                    print(f"[LayerManager] Warning: Skipping non-serializable list field '{key}'")

            # Handle dicts (recursive sanitization)
            elif isinstance(value, dict):
                try:
                    sanitized[key] = self._sanitize_metadata(value)
                except ValueError:
                    print(f"[LayerManager] Warning: Skipping non-serializable dict field '{key}'")

            # Handle other types - try to serialize, skip if fails
            else:
                try:
                    json.dumps(value)
                    sanitized[key] = value
                except (TypeError, ValueError):
                    print(f"[LayerManager] Warning: Skipping non-serializable field '{key}' of type {type(value).__name__}")

        return sanitized

    def _sanitize_value(self, value: Any) -> Any:
        """
        Sanitize a single value for JSON serialization.

        Args:
            value: Value to sanitize

        Returns:
            Sanitized value

        Raises:
            ValueError: If value is not serializable
        """
        if isinstance(value, datetime):
            return value.isoformat()
        elif isinstance(value, (str, int, float, bool, type(None))):
            return value
        elif isinstance(value, (list, dict)):
            # Test if serializable
            json.dumps(value)
            return value
        else:
            raise ValueError(f"Non-serializable type: {type(value).__name__}")

    def _migrate_datetime_timezone(self, metadata: Dict[str, Any], layer_id: str) -> Dict[str, Any]:
        """
        Migrate naive datetimes to timezone-aware UTC (CRITICAL FIX).

        In multi-timezone SAR operations, naive datetimes are ambiguous and dangerous.
        This migrates old metadata with naive timestamps to UTC timezone-aware format.

        Args:
            metadata: Metadata dictionary (may contain naive datetimes)
            layer_id: Layer ID (for logging)

        Returns:
            Metadata with timezone-aware datetimes
        """
        # BUG-020 FIX: Use thread-safe lock for atomic flag checking
        with self._metadata_lock:
            if self._metadata_migration_in_progress:
                return metadata

        if 'updated_at' in metadata:
            try:
                # Parse existing datetime
                dt_str = metadata['updated_at']
                if isinstance(dt_str, str):
                    dt = datetime.fromisoformat(dt_str)

                    # Check if naive (no timezone info)
                    if dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None:
                        print(f"[LayerManager] Migrating naive datetime for {layer_id}: {dt_str}")
                        # Assume UTC for existing naive timestamps
                        dt_aware = dt.replace(tzinfo=timezone.utc)
                        metadata['updated_at'] = dt_aware.isoformat()

                        # Write back to storage to persist migration
                        # BUG-020 FIX: Use lock for atomic flag setting
                        try:
                            with self._metadata_lock:
                                self._metadata_migration_in_progress = True
                            self.set_layer_metadata(layer_id, metadata)
                            print(f"[LayerManager] Migrated timestamp persisted for {layer_id}")
                        except Exception as e:
                            print(f"[LayerManager] Warning: Could not persist migrated timestamp: {e}")
                            self._notify_metadata_warning(f"Could not persist migrated timestamp for {layer_id}: {e}")
                        finally:
                            # BUG-020 FIX: Ensure flag is always cleared under lock
                            with self._metadata_lock:
                                self._metadata_migration_in_progress = False
            except (ValueError, TypeError, AttributeError) as e:
                print(f"[LayerManager] Warning: Could not migrate datetime for {layer_id}: {e}")

        return metadata

    # ------------------------------------------------------------------
    # Legacy structure helpers
    # ------------------------------------------------------------------

    def _rename_legacy_root_group(self):
        """Rename or merge the legacy SAR Tracking root group."""
        root = self.project.layerTreeRoot()
        if not root:
            return

        legacy_group = root.findGroup("SAR Tracking")
        modern_group = root.findGroup(GroupNames.ROOT)

        if legacy_group and legacy_group == modern_group:
            # Already renamed
            legacy_group.setName(GroupNames.ROOT)
            return

        if legacy_group and not modern_group:
            legacy_group.setName(GroupNames.ROOT)
            return

        if legacy_group and modern_group and legacy_group != modern_group:
            # Move children then remove legacy group
            children = list(legacy_group.children())
            for child in children:
                legacy_group.removeChildNode(child)
                modern_group.insertChildNode(0, child)
            parent = legacy_group.parent()
            if parent:
                parent.removeChildNode(legacy_group)

    def _organize_existing_layers(self):
        """Move existing layers into the canonical SAR Tracker groups."""
        root = self.project.layerTreeRoot()
        if not root:
            return

        for layer_name, group_path in LAYER_GROUP_PATHS.items():
            layers = self.project.mapLayersByName(layer_name)
            if not layers:
                continue

            for layer in layers:
                if not self._layer_matches_fields(layer, layer_name):
                    continue

                self._move_layer_to_group(layer, group_path)

                layer_id = LAYER_NAME_TO_ID.get(layer_name)
                if layer_id:
                    layer.setCustomProperty('sartracker:layer_id', layer_id)

    def _move_layer_to_group(self, layer: QgsVectorLayer, group_path: List[str], position: int = 0):
        """Move an existing layer into the specified group path."""
        try:
            target_group = self.ensure_group(group_path, position=position)
        except Exception as e:
            print(f"[LayerManager] Warning: Failed to ensure group for path {group_path}: {e}")
            return

        root = self.project.layerTreeRoot()
        if not root:
            return

        layer_node = root.findLayer(layer.id())
        if layer_node:
            current_parent = layer_node.parent()
            if current_parent == target_group:
                return
            if current_parent:
                # Clone the node before removing - removeChildNode deletes the C++ object
                cloned_node = layer_node.clone()
                current_parent.removeChildNode(layer_node)
                target_group.insertChildNode(position, cloned_node)
            else:
                # No parent, just insert
                target_group.insertChildNode(position, layer_node)
        else:
            # Layer not in tree yet
            self.project.addMapLayer(layer, False)
            target_group.insertLayer(position, layer)

    def _layer_matches_fields(self, layer: QgsVectorLayer, layer_name: str) -> bool:
        """Check whether a layer matches expected field structure."""
        required_fields = LAYER_FIELD_CHECKS.get(layer_name)
        if not required_fields:
            return True

        existing = {field.name() for field in layer.fields()}
        return all(field in existing for field in required_fields)

    def _collect_layer_definitions(self) -> List[LayerDefinition]:
        """Return a flat list of all layer definitions in the schema."""
        structure = get_expected_structure()
        collected: List[LayerDefinition] = []

        def _walk(group: GroupDefinition):
            if group.layers:
                collected.extend(group.layers)
            if group.subgroups:
                for subgroup in group.subgroups:
                    _walk(subgroup)

        _walk(structure)
        return collected
