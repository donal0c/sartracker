# -*- coding: utf-8 -*-
"""
Layer Catalog Service

Provides centralized catalog of all SAR layers/features with metadata and signals.
Serves as the read-optimized data source for future UI components (Phase 3).

Qt5/Qt6 Compatible: Uses qgis.PyQt for all imports.

Phase 1 Deliverable - Part of CalTopo Console Foundation
"""

import logging
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Any, Set, Callable, Tuple

from qgis.PyQt.QtCore import QObject, pyqtSignal, QTimer
from qgis.core import (
    QgsProject, QgsVectorLayer, QgsLayerTreeGroup, QgsLayerTreeNode,
    QgsFeatureRequest, QgsWkbTypes, QgsTask
)

from ..layers import LayerManager, LayerIds, GroupNames, get_layer_by_id
from ..layers.schema import get_expected_structure, LAYER_NAME_TO_ID
from ..utils.notify import info as notify_info, warning as notify_warning, error as notify_error
from ..utils.task_manager import TaskManager


logger = logging.getLogger(__name__)


# ============================================================================
# DATA MODELS
# ============================================================================

@dataclass
class LayerGroupInfo:
    """Metadata for a layer group in the catalog."""
    id: str                                    # Group identifier (path-based)
    name: str                                  # Canonical group name
    alias: Optional[str] = None                # User-assigned alias
    order: int = 0                             # Display order
    parent_id: Optional[str] = None            # Parent group ID (None = root)
    children: List[str] = field(default_factory=list)  # Child layer_ids
    subgroups: List[str] = field(default_factory=list) # Child group IDs
    visible: bool = True                       # Group visibility
    expanded: bool = True                      # Group expanded in tree

    def __post_init__(self):
        """Validate fields after initialization."""
        # Validate required string fields
        if not self.id or not isinstance(self.id, str):
            raise ValueError(f"Invalid group id: {self.id}")
        if not self.name or not isinstance(self.name, str):
            raise ValueError(f"Invalid group name: {self.name}")

        # Validate order is non-negative
        if not isinstance(self.order, int) or self.order < 0:
            raise ValueError(f"Group order must be non-negative integer, got {self.order}")

        # Validate parent_id if set
        if self.parent_id is not None and not isinstance(self.parent_id, str):
            raise ValueError(f"Invalid parent_id: {self.parent_id}")

        # Validate children/subgroups list
        if not isinstance(self.children, list):
            raise ValueError(f"Children must be a list, got {type(self.children).__name__}")
        if not isinstance(self.subgroups, list):
            raise ValueError(f"subgroups must be a list, got {type(self.subgroups).__name__}")

        # Validate boolean fields
        if not isinstance(self.visible, bool):
            raise ValueError(f"visible must be boolean, got {type(self.visible).__name__}")
        if not isinstance(self.expanded, bool):
            raise ValueError(f"expanded must be boolean, got {type(self.expanded).__name__}")


@dataclass
class LayerInfo:
    """Metadata for a single layer in the catalog."""
    # Required fields (no defaults) must come first
    id: str                                    # LayerIds value
    canonical_name: str                        # Schema-defined name
    group_id: str                              # Parent group identifier
    qgis_layer_id: str                         # Internal QGIS layer ID

    # Optional fields (with defaults) come after
    alias: Optional[str] = None                # User-assigned alias
    order: int = 0                             # Display order within group
    visible: bool = True                       # Layer visibility
    provider: str = "memory"                   # 'memory' or 'ogr' (GeoPackage)
    feature_count: int = 0                     # Cached feature count
    last_updated: Optional[datetime] = None    # Last modification time
    favorite: bool = False                     # User favorite flag
    schema_fields: List[str] = field(default_factory=list)  # Field names
    layer_type: str = ""                       # Type tag (from LayerIds)
    geometry_type: str = ""                    # 'Point', 'LineString', 'Polygon'
    editable: bool = True                      # Can user edit this layer?
    data_source_uri: str = ""                  # Data provider source URI snapshot

    def __post_init__(self):
        """Validate fields after initialization."""
        # Validate required string fields
        if not self.id or not isinstance(self.id, str):
            raise ValueError(f"Invalid layer id: {self.id}")
        if not self.canonical_name or not isinstance(self.canonical_name, str):
            raise ValueError(f"Invalid canonical_name: {self.canonical_name}")
        if not self.group_id or not isinstance(self.group_id, str):
            raise ValueError(f"Invalid group_id: {self.group_id}")
        if not self.qgis_layer_id or not isinstance(self.qgis_layer_id, str):
            raise ValueError(f"Invalid qgis_layer_id: {self.qgis_layer_id}")

        # Validate order is non-negative
        if not isinstance(self.order, int) or self.order < 0:
            raise ValueError(f"order must be non-negative integer, got {self.order}")

        # Validate feature_count is non-negative
        if not isinstance(self.feature_count, int) or self.feature_count < 0:
            raise ValueError(f"feature_count must be non-negative, got {self.feature_count}")

        # Validate provider is known value
        if self.provider not in ["memory", "ogr", "unknown"]:
            raise ValueError(f"Invalid provider: {self.provider}. Must be 'memory', 'ogr', or 'unknown'")

        # Validate boolean fields
        if not isinstance(self.visible, bool):
            raise ValueError(f"visible must be boolean, got {type(self.visible).__name__}")
        if not isinstance(self.favorite, bool):
            raise ValueError(f"favorite must be boolean, got {type(self.favorite).__name__}")
        if not isinstance(self.editable, bool):
            raise ValueError(f"editable must be boolean, got {type(self.editable).__name__}")

        # Validate schema_fields is a list
        if not isinstance(self.schema_fields, list):
            raise ValueError(f"schema_fields must be a list, got {type(self.schema_fields).__name__}")

    @property
    def display_name(self) -> str:
        """Return display name (alias if set, else canonical name)."""
        return self.alias if self.alias else self.canonical_name

    @property
    def is_persistent(self) -> bool:
        """Return True if layer is backed by GeoPackage."""
        return self.provider == "ogr"


@dataclass
class FeatureSummary:
    """Minimal feature payload for UI display (lightweight)."""
    id: str                                    # Feature ID or UUID
    name: str                                  # Display name
    type: str                                  # Feature type (marker_type, line_type, etc.)
    geometry_wkt: str                          # Geometry as WKT (lightweight)
    created_at: Optional[datetime] = None      # Creation timestamp
    updated_at: Optional[datetime] = None      # Modification timestamp
    display_order: int = 0                     # User-defined order
    attributes: Dict[str, Any] = field(default_factory=dict)  # Key attributes only

    def __post_init__(self):
        """Validate fields after initialization."""
        # Validate required string fields
        if not self.id or not isinstance(self.id, str):
            raise ValueError(f"Invalid feature id: {self.id}")
        if not self.name or not isinstance(self.name, str):
            raise ValueError(f"Invalid feature name: {self.name}")
        if not self.type or not isinstance(self.type, str):
            raise ValueError(f"Invalid feature type: {self.type}")
        if not isinstance(self.geometry_wkt, str):
            raise ValueError(f"geometry_wkt must be string, got {type(self.geometry_wkt).__name__}")

        # Validate display_order is non-negative
        if not isinstance(self.display_order, int) or self.display_order < 0:
            raise ValueError(f"display_order must be non-negative integer, got {self.display_order}")

        # Validate attributes is a dict
        if not isinstance(self.attributes, dict):
            raise ValueError(f"attributes must be a dict, got {type(self.attributes).__name__}")


class _ConsoleModelTask(QgsTask):
    """Background task for fetching console model safely."""

    def __init__(
        self,
        catalog: "LayerCatalogService",
        include_features: bool,
        feature_limit: int,
        show_hidden: bool,
        filter_favorites_only: bool
    ):
        super().__init__("Fetch Layer Catalog Model", QgsTask.CanCancel)
        self._catalog = catalog
        self.include_features = include_features
        self.feature_limit = feature_limit
        self.show_hidden = show_hidden
        self.filter_favorites_only = filter_favorites_only
        self.result: Optional[Dict[str, Any]] = None
        self.error: Optional[Exception] = None

    def run(self) -> bool:
        try:
            if getattr(self._catalog, "_cleanup_in_progress", False):
                self.result = {"groups": []}
                return True

            self.result = self._catalog.get_console_model(
                include_features=self.include_features,
                feature_limit=self.feature_limit,
                show_hidden=self.show_hidden,
                filter_favorites_only=self.filter_favorites_only
            )
            return True
        except Exception as exc:
            self.error = exc
            logger.exception("Console model task failed")
            return False


@dataclass
class CatalogBuildResult:
    """Container for cache build outputs."""
    groups: Dict[str, LayerGroupInfo]
    layers: Dict[str, LayerInfo]
    layer_refs: Dict[str, QgsVectorLayer]


class _CatalogCacheBuilder:
    """Pure helper that constructs layer/group metadata."""

    def __init__(
        self,
        layer_manager: LayerManager,
        project: QgsProject,
        logger_instance: logging.Logger = None,
    ) -> None:
        self.layer_manager = layer_manager
        self.project = project
        self.logger = logger_instance or logger
        self._groups: Dict[str, LayerGroupInfo] = {}
        self._layers: Dict[str, LayerInfo] = {}
        self._layer_refs: Dict[str, QgsVectorLayer] = {}

    def build(self) -> CatalogBuildResult:
        """Run a full catalog build and return the cache dictionaries."""
        self._groups = {
            GroupNames.ROOT: LayerGroupInfo(
                id=GroupNames.ROOT,
                name=GroupNames.ROOT,
                order=0,
                visible=True,
                expanded=True
            )
        }
        self._layers = {}
        self._layer_refs = {}

        root_group = get_expected_structure()
        self._process_group_definition(root_group, parent_id=None)

        return CatalogBuildResult(
            groups=self._groups,
            layers=self._layers,
            layer_refs=self._layer_refs
        )

    # ------------------------------------------------------------------
    # Internal helpers (mirrors previous LayerCatalogService methods)
    # ------------------------------------------------------------------

    def _process_group_definition(self, group_def, parent_id: Optional[str]) -> None:
        group_id = self._ensure_group_entry(group_def, parent_id)

        if group_def.layers:
            for layer_def in sorted(group_def.layers, key=lambda ld: ld.position):
                self._add_layer_from_definition(layer_def, group_id)

        if group_def.subgroups:
            for subgroup in sorted(group_def.subgroups, key=lambda gd: gd.position):
                self._process_group_definition(subgroup, group_id)

    def _ensure_group_entry(self, group_def, parent_id: Optional[str]) -> str:
        if parent_id is None and group_def.name == GroupNames.ROOT:
            return GroupNames.ROOT

        group_id = self._generate_group_id(group_def, parent_id)

        if group_id not in self._groups:
            self._groups[group_id] = LayerGroupInfo(
                id=group_id,
                name=group_def.name,
                order=group_def.position,
                parent_id=parent_id,
                alias=None,
                visible=True,
                expanded=True
            )

        if parent_id and parent_id in self._groups:
            parent_info = self._groups[parent_id]
            if group_id not in parent_info.subgroups:
                parent_info.subgroups.append(group_id)

        return group_id

    def _generate_group_id(self, group_def, parent_id: Optional[str]) -> str:
        if not parent_id:
            return group_def.name
        return f"{parent_id}/{group_def.name}"

    def _add_layer_from_definition(self, layer_def, group_id: str) -> None:
        layer_id = layer_def.layer_id
        layer = self.layer_manager.get_layer(layer_id)

        if not layer or not layer.isValid():
            self.logger.warning("Layer %s not found or invalid in group %s; skipping", layer_id, group_id)
            return

        try:
            layer_info = self._extract_layer_info(layer_id, layer, layer_def, group_id)
        except RuntimeError:
            return

        self._layers[layer_id] = layer_info
        self._layer_refs[layer_id] = layer

        group_info = self._groups.get(group_id)
        if group_info and layer_id not in group_info.children:
            group_info.children.append(layer_id)

    def _extract_layer_info(self, layer_id: str, layer: QgsVectorLayer, layer_def, group_id: str) -> LayerInfo:
        return build_layer_info(
            layer_manager=self.layer_manager,
            project=self.project,
            layer_id=layer_id,
            layer=layer,
            layer_def=layer_def,
            group_id=group_id,
            logger_instance=self.logger
        )


def build_layer_info(
    layer_manager: LayerManager,
    project: QgsProject,
    layer_id: str,
    layer: QgsVectorLayer,
    layer_def,
    group_id: str,
    logger_instance: logging.Logger,
) -> LayerInfo:
    """Shared helper to build LayerInfo objects from a live layer."""
    logger_ref = logger_instance or logger

    try:
        metadata = layer_manager.get_layer_metadata(layer_id) or {}
    except Exception as e:
        logger_ref.warning("Failed to get metadata for %s: %s", layer_id, e, exc_info=True)
        metadata = {}

    try:
        provider = layer.dataProvider().name() if layer.dataProvider() else "memory"
    except Exception as e:
        logger_ref.warning("Failed to get provider for %s: %s", layer_id, e, exc_info=True)
        provider = "unknown"

    try:
        feature_count = layer.featureCount()
    except Exception as e:
        logger_ref.warning("Failed to get feature count for %s: %s", layer_id, e, exc_info=True)
        feature_count = 0

    try:
        field_names = [field.name() for field in layer.fields()]
    except Exception as e:
        logger_ref.warning("Failed to get fields for %s: %s", layer_id, e, exc_info=True)
        field_names = []

    geom_type = ""
    try:
        geom_value = layer.geometryType()
        point_geom = getattr(QgsWkbTypes, "PointGeometry", getattr(QgsWkbTypes, "Point", None))
        line_geom = getattr(QgsWkbTypes, "LineGeometry", getattr(QgsWkbTypes, "Line", None))
        poly_geom = getattr(QgsWkbTypes, "PolygonGeometry", getattr(QgsWkbTypes, "Polygon", None))
        if point_geom is not None and geom_value == point_geom:
            geom_type = "Point"
        elif line_geom is not None and geom_value == line_geom:
            geom_type = "LineString"
        elif poly_geom is not None and geom_value == poly_geom:
            geom_type = "Polygon"
    except Exception as e:
        logger_ref.warning("Failed to get geometry type for %s: %s", layer_id, e, exc_info=True)

    visible = True
    try:
        layer_tree_root = project.layerTreeRoot()
        if layer_tree_root:
            layer_node = layer_tree_root.findLayer(layer.id())
            if layer_node:
                visible = layer_node.isVisible()
    except Exception as e:
        logger_ref.warning("Could not determine visibility for %s: %s", layer_id, e, exc_info=True)

    last_updated = None
    timestamp = metadata.get('updated_at')
    if timestamp:
        try:
            last_updated = datetime.fromisoformat(timestamp)
        except Exception:
            pass

    try:
        data_source_uri = layer.source()
    except Exception:
        data_source_uri = ""

    try:
        return LayerInfo(
            id=layer_id,
            canonical_name=layer_def.name,
            group_id=group_id,
            qgis_layer_id=layer.id(),
            alias=metadata.get('alias'),
            order=metadata.get('display_order', layer_def.position),
            visible=visible,
            provider=provider,
            feature_count=feature_count,
            last_updated=last_updated,
            favorite=metadata.get('favorite', False),
            schema_fields=field_names,
            layer_type=layer_id.split('_')[0] if '_' in layer_id else '',
            geometry_type=geom_type,
            editable=True,
            data_source_uri=data_source_uri
        )
    except Exception as e:
        logger_ref.exception("Failed to create LayerInfo for %s", layer_id)
        raise RuntimeError(f"Failed to extract layer info for {layer_id}: {e}")

# ============================================================================
# CATALOG SERVICE
# ============================================================================

class LayerCatalogService(QObject):
    """
    Centralized catalog of SAR layers with metadata and signals.

    Provides:
    - Read-optimized cache of layer/feature metadata
    - Alias/ordering/favorite persistence via LayerManager
    - Qt signals for UI synchronization
    - Efficient incremental refresh on layer changes

    Design Pattern:
    - Follows BaseLayerManager diagnostic patterns
    - Uses TaskManager-style signal lifecycle management
    - Implements defensive guards (Issue #4, Issue #6)

    Qt5/Qt6 Compatible: All Qt imports via qgis.PyQt
    """

    # ========================================================================
    # Qt SIGNALS (Class-level declaration)
    # ========================================================================

    model_changed = pyqtSignal()                     # Full catalog rebuilt
    layer_updated = pyqtSignal(str)                  # layer_id metadata changed
    alias_changed = pyqtSignal(str)                  # layer_id alias set/cleared
    group_updated = pyqtSignal(str)                  # group_id changed
    feature_count_changed = pyqtSignal(str, int)     # layer_id, new_count

    def __init__(
        self,
        iface,
        layer_manager: LayerManager,
        task_manager: Optional[TaskManager] = None,
        project: Optional[QgsProject] = None
    ):
        """
        Initialize catalog service.

        Args:
            iface: QGIS interface object
            layer_manager: Shared LayerManager instance (source of truth)

        Raises:
            RuntimeError: If initialization fails
        """
        # CRITICAL: Initialize QObject parent class FIRST
        super().__init__()

        self.iface = iface
        self.layer_manager = layer_manager
        self.project = project or QgsProject.instance()
        self._task_manager = task_manager or TaskManager()
        self._owned_task_manager = task_manager is None
        self._message_bar = self._resolve_message_bar()

        if not self.project:
            raise RuntimeError("QgsProject instance not available")

        # Cache dictionaries (keyed by ID)
        self._groups: Dict[str, LayerGroupInfo] = {}
        self._layers: Dict[str, LayerInfo] = {}

        # Refresh management
        self._refresh_pending = False
        self._refresh_timer: Optional[QTimer] = None
        self._pending_refresh_layers: Set[str] = set()

        # Signal tracking for cleanup
        self._signal_connections = []
        self._layer_signal_connections: Dict[str, List[tuple]] = {}

        # Cleanup flag (CRITICAL FIX: Prevents handlers from firing during cleanup)
        self._cleanup_in_progress = False
        self._layer_lock_alerts: Dict[str, datetime] = {}

        # Build initial cache
        try:
            self._build_cache()
        except Exception as e:
            raise RuntimeError(f"Failed to build initial cache: {e}")

        # Wire QGIS signals
        self._wire_signals()

        # HIGH-7: Connect to mission store changes
        if hasattr(layer_manager, 'mission_store_changed'):
            layer_manager.mission_store_changed.connect(self._on_mission_store_changed)
            self._signal_connections.append((
                layer_manager.mission_store_changed,
                'mission_store_changed',
                self._on_mission_store_changed
            ))
            logger.debug("LayerCatalogService connected to mission store change signal")

        logger.info("LayerCatalogService initialized successfully")

    # ========================================================================
    # Logging / Notification Utilities
    # ========================================================================

    def _resolve_message_bar(self):
        """Return QGIS message bar if iface provides one."""
        iface = getattr(self, 'iface', None)
        if not iface or not hasattr(iface, 'messageBar'):
            return None
        try:
            return iface.messageBar()
        except Exception:
            logger.debug("LayerCatalogService could not resolve message bar", exc_info=True)
            return None

    def _message_bar_safe(self):
        """Lazy-fetch message bar, caching first successful lookup."""
        if self._message_bar:
            return self._message_bar
        self._message_bar = self._resolve_message_bar()
        return self._message_bar

    def _notify_info(self, title: str, message: str) -> None:
        """Show informational notification (BUG-059 fix: user feedback for cache rebuild)."""
        bar = self._message_bar_safe()
        if not bar:
            return
        try:
            notify_info(bar, title, message, duration=3)
        except Exception:
            logger.debug("LayerCatalogService info notification suppressed", exc_info=True)

    def _notify_warning(self, title: str, message: str) -> None:
        bar = self._message_bar_safe()
        if not bar:
            return
        try:
            notify_warning(bar, title, message, duration=7)
        except Exception:
            logger.debug("LayerCatalogService warning notification suppressed", exc_info=True)

    def _notify_error(self, title: str, message: str) -> None:
        bar = self._message_bar_safe()
        if not bar:
            return
        try:
            notify_error(bar, title, message, duration=10)
        except Exception:
            logger.debug("LayerCatalogService error notification suppressed", exc_info=True)

    # ========================================================================
    # Background Task Helpers
    # ========================================================================

    def start_console_model_task(
        self,
        include_features: bool = True,
        feature_limit: int = 500,
        show_hidden: bool = True,
        filter_favorites_only: bool = False,
        on_complete: Optional[Callable[[Dict[str, Any]], None]] = None,
        on_error: Optional[Callable[[Exception], None]] = None,
        task_id: Optional[str] = None
    ) -> str:
        """Run get_console_model() in background via TaskManager."""
        task_manager = getattr(self, "_task_manager", None)
        if not task_manager:
            raise RuntimeError("Task manager not available")

        task = _ConsoleModelTask(
            catalog=self,
            include_features=include_features,
            feature_limit=feature_limit,
            show_hidden=show_hidden,
            filter_favorites_only=filter_favorites_only
        )

        def _handle_complete(qgs_task: _ConsoleModelTask):
            payload = qgs_task.result or {"groups": []}
            if on_complete:
                on_complete(payload)

        def _handle_error(qgs_task: _ConsoleModelTask):
            err = qgs_task.error or RuntimeError("Catalog fetch failed")
            if on_error:
                on_error(err)
            else:
                self._notify_error("Layer Catalog", str(err))

        return task_manager.start_task(
            task=task,
            on_complete=_handle_complete,
            on_error=_handle_error,
            task_id=task_id or "catalog_fetch"
        )

    def cancel_task(self, task_id: str) -> bool:
        """Cancel a background catalog task."""
        task_manager = getattr(self, "_task_manager", None)
        if not task_manager:
            return False
        return task_manager.cancel_task(task_id)

    def _load_layer_metadata(self, layer_id: str) -> Dict[str, Any]:
        if not self.layer_manager:
            raise RuntimeError("Layer manager not available")
        try:
            return self.layer_manager.get_layer_metadata(layer_id) or {}
        except Exception as exc:
            logger.exception("Failed to load metadata for %s", layer_id)
            self._notify_error("Layer Metadata", f"Could not read metadata for {layer_id}: {exc}")
            raise

    def _persist_layer_metadata(self, layer_id: str, metadata: Dict[str, Any], action: str) -> None:
        if not self.layer_manager:
            raise RuntimeError("Layer manager not available")
        try:
            self.layer_manager.set_layer_metadata(layer_id, metadata)
        except Exception as exc:
            logger.exception("Failed to %s for %s", action, layer_id)
            self._notify_error("Layer Metadata", f"Could not {action} for {layer_id}: {exc}")
            raise RuntimeError(f"Failed to {action} for {layer_id}: {exc}")

    # ========================================================================
    # PUBLIC API - Read Operations
    # ========================================================================

    def list_groups(self) -> List[LayerGroupInfo]:
        """
        Return all layer groups.

        Returns:
            List of LayerGroupInfo objects (defensive copy)
        """
        return list(self._groups.values())

    def get_group(self, group_id: str) -> Optional[LayerGroupInfo]:
        """
        Get group metadata by ID.

        Args:
            group_id: Group identifier

        Returns:
            LayerGroupInfo or None if not found
        """
        return self._groups.get(group_id)

    def list_layers(self, group_id: Optional[str] = None) -> List[LayerInfo]:
        """
        Return layers, optionally filtered by group.

        Args:
            group_id: Optional group identifier to filter by

        Returns:
            List of LayerInfo objects (defensive copy)
        """
        if group_id is None:
            return list(self._layers.values())

        return [info for info in self._layers.values() if info.group_id == group_id]

    def get_layer(self, layer_id: str) -> Optional[LayerInfo]:
        """
        Get layer metadata by ID.

        Args:
            layer_id: Layer identifier (from LayerIds)

        Returns:
            LayerInfo or None if not found
        """
        return self._layers.get(layer_id)

    def list_features(
        self,
        layer_id: str,
        filters: Optional[Dict] = None,
        limit: Optional[int] = 1000
    ) -> List[FeatureSummary]:
        """
        Return feature summaries for a layer.

        PERFORMANCE NOTE: This queries the actual layer, not cache.
        Use sparingly. For feature counts, use LayerInfo.feature_count.

        Args:
            layer_id: Layer identifier
            filters: Optional filters (e.g., {'name': 'Test'}) (not yet implemented)
            limit: Optional limit on results (default: 1000, max: 500 for life-safety)

        Returns:
            List of FeatureSummary objects (empty list on error)

        Raises:
            ValueError: If parameters are invalid
        """
        # Validate layer_id
        if not layer_id or not isinstance(layer_id, str):
            raise ValueError("layer_id must be a non-empty string")

        # CRITICAL FIX: Issue #1.14 - Validate limit bounds (life-safety: prevent UI freeze)
        if limit is not None:
            if not isinstance(limit, int):
                raise ValueError(f"limit must be an integer, got {type(limit).__name__}")
            if limit <= 0:
                raise ValueError(f"limit must be positive, got {limit}")
            if limit > 500:
                raise ValueError(f"limit too large ({limit}), maximum is 500 for life-safety systems")

        # Validate filters
        if filters is not None:
            if not isinstance(filters, dict):
                raise ValueError(f"filters must be a dict, got {type(filters).__name__}")

        layer_info = self.get_layer(layer_id)
        if not layer_info:
            logger.warning("Layer %s not in catalog during list_features", layer_id)
            return []

        layer = self.layer_manager.get_layer(layer_id)
        if not layer or not layer.isValid():
            logger.warning("Layer %s not available or invalid during list_features", layer_id)
            return []

        # Build feature request
        request = QgsFeatureRequest()
        if limit:
            request.setLimit(limit)

        # TODO: Apply filters if provided (not yet implemented)

        summaries = []
        try:
            for feature in layer.getFeatures(request):
                # Extract key attributes safely
                name = ''
                name_idx = feature.fieldNameIndex('name')
                if name_idx >= 0:
                    name_val = feature.attribute('name')
                    if name_val is not None:
                        name = str(name_val)

                type_field = ''
                type_idx = feature.fieldNameIndex('type')
                if type_idx >= 0:
                    type_val = feature.attribute('type')
                    if type_val is not None:
                        type_field = str(type_val)

                # Business identifier (if present)
                business_id = None
                business_idx = feature.fieldNameIndex('id')
                if business_idx >= 0:
                    business_val = feature.attribute('id')
                    if business_val is not None and str(business_val) != '':
                        business_id = str(business_val)

                # Created / updated timestamps (lightweight string capture)
                created_at_val = None
                created_idx = feature.fieldNameIndex('created_at')
                if created_idx >= 0:
                    created_raw = feature.attribute('created_at')
                    if created_raw not in (None, ''):
                        created_at_val = str(created_raw)

                updated_at_val = None
                updated_idx = feature.fieldNameIndex('updated_at')
                if updated_idx >= 0:
                    updated_raw = feature.attribute('updated_at')
                    if updated_raw not in (None, ''):
                        updated_at_val = str(updated_raw)

                # Display order (optional)
                display_order_val = 0
                order_idx = feature.fieldNameIndex('display_order')
                if order_idx >= 0:
                    order_raw = feature.attribute('display_order')
                    try:
                        display_order_val = max(0, int(order_raw))
                    except (TypeError, ValueError):
                        display_order_val = 0

                # Extract geometry safely
                geometry_wkt = ''
                if feature.hasGeometry():
                    try:
                        geom = feature.geometry()
                        if geom and not geom.isNull():
                            geometry_wkt = geom.asWkt()
                    except Exception as e:
                        logger.warning(
                            "Could not extract geometry for feature %s in layer %s: %s",
                            feature.id(),
                            layer_id,
                            e,
                            exc_info=True
                        )

                # Build attributes payload for UI consumers
                attributes: Dict[str, Any] = {
                    'feature_id': feature.id()
                }
                if business_id is not None:
                    attributes['business_id'] = business_id
                if type_field:
                    attributes['type'] = type_field
                attributes['display_order'] = display_order_val
                if created_at_val:
                    attributes['created_at'] = created_at_val
                if updated_at_val:
                    attributes['updated_at'] = updated_at_val

                summary_id = business_id if business_id is not None else str(feature.id())

                summary = FeatureSummary(
                    id=str(summary_id),
                    name=name or str(summary_id),
                    type=type_field or layer_id,
                    geometry_wkt=geometry_wkt,
                    created_at=created_at_val,
                    updated_at=updated_at_val,
                    display_order=display_order_val,
                    attributes=attributes
                )
                summaries.append(summary)
        except Exception as e:
            logger.exception("Error enumerating features for layer %s", layer_id)
            self._notify_warning("Layer Data Unavailable", f"Could not list features for {layer_info.display_name}: {e}")

        try:
            summaries.sort(key=lambda s: (s.display_order if s.display_order is not None else 0, str(s.id)))
        except Exception:
            pass

        return summaries

    def get_console_model(
        self,
        include_features: bool = True,
        feature_limit: int = 500,
        show_hidden: bool = True,
        filter_favorites_only: bool = False
    ) -> Dict[str, Any]:
        """
        Build hierarchical payload for LayerConsoleWidget.

        CRITICAL FIX: Issue #2.5 - feature_limit is now GLOBAL budget across all layers.
        Previously: 300 limit per layer × 20 layers = 6000 features (16× too many).
        Now: 300 limit total across all layers.

        PERFORMANCE FIX: Issue #3.4 - Push filters to catalog to avoid fetching unused data.

        Args:
            include_features: Include feature summaries for each layer
            feature_limit: GLOBAL maximum features to return across ALL layers (None = no limit)
            show_hidden: Include hidden (non-visible) layers (default: True)
            filter_favorites_only: Only include favorite layers (default: False)

        Returns:
            Dictionary with group/layer/feature structure
        """
        if feature_limit is not None:
            if not isinstance(feature_limit, int) or feature_limit <= 0:
                raise ValueError("feature_limit must be a positive integer or None")

        if self._cleanup_in_progress:
            return {"groups": []}

        # CRITICAL FIX: Issue #2.5 - Track remaining budget globally
        remaining_budget = feature_limit if feature_limit else float('inf')

        # Sort groups by defined order, skip root container
        try:
            groups_sorted = sorted(self._groups.values(), key=lambda g: g.order)
        except Exception:
            groups_sorted = list(self._groups.values())

        groups_payload: List[Dict[str, Any]] = []

        for group_info in groups_sorted:
            if group_info.id == GroupNames.ROOT:
                continue  # Skip root container

            # Only include top-level groups for now (Phase 3 scope)
            if group_info.parent_id not in (None, GroupNames.ROOT):
                continue

            # Collect layer payloads
            layers_payload: List[Dict[str, Any]] = []
            child_layers = [
                self._layers[layer_id]
                for layer_id in group_info.children
                if layer_id in self._layers
            ]
            try:
                child_layers.sort(key=lambda li: li.order)
            except Exception:
                pass

            for layer_info in child_layers:
                # PERFORMANCE FIX: Issue #3.4 - Skip layers early based on filters
                if not show_hidden and not layer_info.visible:
                    continue  # Skip hidden layers if filter active
                if filter_favorites_only and not layer_info.favorite:
                    continue  # Skip non-favorites if filter active

                layer_entry: Dict[str, Any] = {
                    "layer_id": layer_info.id,
                    "name": layer_info.canonical_name,
                    "display_name": layer_info.display_name,
                    "feature_count": layer_info.feature_count,
                    "geometry_type": layer_info.geometry_type,
                    "is_visible": layer_info.visible,
                    "is_favorite": layer_info.favorite,
                    "provider": layer_info.provider,
                    "last_updated": layer_info.last_updated.isoformat() if layer_info.last_updated else None
                }

                # Feature summaries (optional for performance)
                features_payload: List[Dict[str, Any]] = []
                if include_features and remaining_budget > 0:
                    try:
                        # CRITICAL FIX: Issue #2.5 - Use remaining budget for this layer
                        # Allocate min of (remaining budget, reasonable per-layer max)
                        layer_limit = min(int(remaining_budget), feature_limit) if feature_limit else None
                        summaries = self.list_features(layer_info.id, limit=layer_limit)

                        # Deduct what we actually got from budget
                        remaining_budget -= len(summaries)
                        for summary in summaries:
                            created_val = summary.created_at
                            if isinstance(created_val, datetime):
                                created_val = created_val.isoformat()

                            updated_val = summary.updated_at
                            if isinstance(updated_val, datetime):
                                updated_val = updated_val.isoformat()

                            features_payload.append({
                                "id": summary.id,
                                "name": summary.name,
                                "feature_id": summary.attributes.get("feature_id", summary.id),
                                "business_id": summary.attributes.get("business_id"),
                                "created_at": created_val,
                                "updated_at": updated_val,
                                "display_order": summary.display_order,
                                "type": summary.type,
                                "attributes": summary.attributes
                            })
                        try:
                            features_payload.sort(
                                key=lambda f: (
                                    f.get("display_order", 0),
                                    str(f.get("business_id") or f.get("feature_id") or f.get("id"))
                                )
                            )
                        except Exception:
                            pass
                    except Exception as exc:
                        logger.exception("Failed to build feature list for %s", layer_info.id)
                        self._notify_warning(
                            "Feature List Failed",
                            f"Could not load features for {layer_info.display_name}: {exc}"
                        )

                layer_entry["features"] = features_payload
                layers_payload.append(layer_entry)

            if not layers_payload:
                continue

            groups_payload.append({
                "id": group_info.id,
                "name": group_info.alias or group_info.name,
                "expanded": group_info.expanded,
                "visible": group_info.visible,
                "layers": layers_payload
            })

        return {"groups": groups_payload}

    # ========================================================================
    # PUBLIC API - Write Operations (Metadata Only)
    # ========================================================================

    def set_layer_alias(self, layer_id: str, alias: Optional[str]) -> None:
        """
        Set or clear layer alias.

        Args:
            layer_id: Layer identifier (from LayerIds)
            alias: New alias (None or empty string to clear)

        Raises:
            ValueError: If layer_id is invalid or alias is malformed
            RuntimeError: If metadata write fails
        """
        # Validate layer exists
        if layer_id not in self._layers:
            raise ValueError(f"Unknown layer_id: {layer_id}")

        # Validate alias (if provided)
        if alias is not None:
            alias = alias.strip()
            if not alias:
                alias = None  # Empty string = clear alias
            elif len(alias) > 128:
                raise ValueError("Alias must be ≤ 128 characters")
            else:
                # ISSUE #4.4: Check for duplicate aliases
                for lid, layer_info in self._layers.items():
                    if lid != layer_id and layer_info.alias == alias:
                        logger.warning("Alias '%s' already used by layer '%s'", alias, lid)
                        # Don't raise error, just warn - allow duplicates but notify user

        # Get current metadata
        try:
            metadata = self._load_layer_metadata(layer_id)
        except Exception:
            return

        # Update alias
        if alias is None:
            metadata.pop('alias', None)
        else:
            metadata['alias'] = alias

        # Write to storage
        self._persist_layer_metadata(layer_id, metadata, "set alias")

        # Update cache
        if layer_id in self._layers:
            self._layers[layer_id].alias = alias

        # Emit signals
        self.alias_changed.emit(layer_id)
        self.layer_updated.emit(layer_id)

        logger.info("Set alias for %s -> %s", layer_id, alias)

    def set_layer_order(self, layer_id: str, order: int) -> None:
        """
        Set layer display order.

        Args:
            layer_id: Layer identifier
            order: Display order (0 = top, higher = lower)

        Raises:
            ValueError: If layer_id invalid or order < 0
            RuntimeError: If metadata write fails
        """
        # Validate
        if layer_id not in self._layers:
            raise ValueError(f"Unknown layer_id: {layer_id}")

        if not isinstance(order, int) or order < 0:
            raise ValueError("Order must be non-negative integer")

        # Get current metadata
        try:
            metadata = self._load_layer_metadata(layer_id)
        except Exception:
            return
        metadata['display_order'] = order

        # Write to storage
        self._persist_layer_metadata(layer_id, metadata, "set order")

        # Update cache
        if layer_id in self._layers:
            self._layers[layer_id].order = order

        # Emit signal
        self.layer_updated.emit(layer_id)

        logger.info("Set order for %s -> %s", layer_id, order)

    def set_layer_favorite(self, layer_id: str, is_favorite: bool) -> None:
        """
        Mark layer as favorite.

        Args:
            layer_id: Layer identifier
            is_favorite: True to mark as favorite, False to unmark

        Raises:
            ValueError: If layer_id invalid
            RuntimeError: If metadata write fails
        """
        # Validate
        if layer_id not in self._layers:
            raise ValueError(f"Unknown layer_id: {layer_id}")

        # Get current metadata
        try:
            metadata = self._load_layer_metadata(layer_id)
        except Exception:
            return
        metadata['favorite'] = bool(is_favorite)

        # Write to storage
        self._persist_layer_metadata(layer_id, metadata, "set favorite")

        # Update cache
        if layer_id in self._layers:
            self._layers[layer_id].favorite = is_favorite

        # Emit signal
        self.layer_updated.emit(layer_id)

        logger.info("Set favorite for %s -> %s", layer_id, is_favorite)

    # ========================================================================
    # CACHE MANAGEMENT
    # ========================================================================

    def _build_cache(self) -> None:
        """
        Build full catalog cache from LayerManager.

        This is called on init and on major structural changes.
        Queries LayerManager for all layers and populates cache.
        """
        logger.info("Building layer catalog cache")

        # Ensure LayerManager structure exists
        try:
            self.layer_manager.ensure_structure()
        except Exception as e:
            logger.exception("LayerManager.ensure_structure failed")
            self._notify_error("Layer Catalog", f"Layer structure incomplete: {e}")

        # Disconnect existing per-layer signal hooks before rebuilding cache
        self._disconnect_all_layer_signals()

        builder = _CatalogCacheBuilder(
            layer_manager=self.layer_manager,
            project=self.project,
            logger_instance=logger
        )

        result = builder.build()

        # Replace cache contents in-place so external references stay valid
        self._groups.clear()
        self._groups.update(result.groups)

        self._layers.clear()
        self._layers.update(result.layers)

        # Rewire per-layer signals now that cache is rebuilt
        for layer_id, layer in result.layer_refs.items():
            self._wire_layer_signals(layer_id, layer)

        logger.info(
            "Layer catalog cache built (%s groups, %s layers)",
            len(self._groups),
            len(self._layers)
        )

        # Emit full refresh signal
        self.model_changed.emit()

    def rescan_layers(self):
        """
        Force full cache rebuild.

        Use after structural changes (layer deletions, schema repairs).
        This is a public method that can be called by LayersController or other components.
        """
        logger.info("Rescanning all layers for catalog rebuild")
        # BUG-059 fix: Defer cache rebuild to improve UI responsiveness
        self._notify_info("Layer Catalog", "Rebuilding layer cache...")
        QTimer.singleShot(10, self._build_cache_with_notification)

    def _build_cache_with_notification(self):
        """
        Build cache and show completion notification.

        BUG-059 fix: Wrapper around _build_cache() that provides user feedback.
        Called via QTimer.singleShot to improve perceived UI responsiveness.
        """
        try:
            self._build_cache()
            logger.info("Layer catalog cache rebuild complete")
        except Exception as e:
            logger.exception("Cache rebuild failed")
            self._notify_error("Layer Catalog", f"Cache rebuild failed: {e}")

    def refresh_layer(self, layer_id: str, full: bool = False) -> None:
        """
        Refresh single layer metadata.

        Args:
            layer_id: Layer identifier
            full: If True, rebuild from scratch. If False, update counts only.

        Raises:
            ValueError: If layer_id is invalid
        """
        # Input validation
        if not layer_id or not isinstance(layer_id, str):
            raise ValueError("layer_id must be a non-empty string")

        # DEFENSIVE GUARD - Check cleanup flag first
        if self._cleanup_in_progress:
            logger.debug("refresh_layer called during cleanup; ignoring request")
            return

        if not self.layer_manager or not self._layers:
            logger.debug("refresh_layer called after cleanup; ignoring request")
            return

        if layer_id not in self._layers:
            logger.warning("Attempted refresh of unknown layer %s", layer_id)
            return

        try:
            # Get layer from manager
            layer = self.layer_manager.get_layer(layer_id)
            if not layer or not layer.isValid():
                logger.warning("Layer %s not valid during refresh", layer_id)
                return

            # Get layer definition from schema
            layer_def = get_layer_by_id(layer_id)
            if not layer_def:
                logger.warning("No schema definition for %s", layer_id)
                return

            if full:
                # Full rebuild - extract all layer info
                try:
                    group_id = self._layers[layer_id].group_id if layer_id in self._layers else GroupNames.ROOT
                    layer_info = build_layer_info(
                        layer_manager=self.layer_manager,
                        project=self.project,
                        layer_id=layer_id,
                        layer=layer,
                        layer_def=layer_def,
                        group_id=group_id,
                        logger_instance=logger
                    )
                    self._layers[layer_id] = layer_info
                    self._wire_layer_signals(layer_id, layer)
                    logger.info("Full refresh completed for %s", layer_id)
                except Exception as e:
                    logger.exception("Error extracting layer info for %s", layer_id)
                    return
            else:
                # Quick update (feature count only)
                try:
                    old_count = self._layers[layer_id].feature_count
                    new_count = layer.featureCount()

                    if old_count != new_count:
                        self._layers[layer_id].feature_count = new_count
                        if hasattr(self, 'feature_count_changed'):
                            self.feature_count_changed.emit(layer_id, new_count)
                        logger.debug(
                            "Feature count updated for %s: %s -> %s",
                            layer_id,
                            old_count,
                            new_count
                        )
                except Exception as e:
                    logger.warning("Error updating feature count for %s: %s", layer_id, e, exc_info=True)
                    return

            # Emit signal (defensive - check attribute exists)
            if hasattr(self, 'layer_updated'):
                self.layer_updated.emit(layer_id)

        except Exception as e:
            logger.exception("Unexpected error in refresh_layer for %s", layer_id)

    # ========================================================================
    # SIGNAL HANDLERS (Defensive)
    # ========================================================================

    def _wire_signals(self) -> None:
        """Connect to QGIS project signals."""
        project = QgsProject.instance()

        if not project:
            logger.warning("No QgsProject instance available; skipping signal wiring")
            return

        # Wire signals with exception handling
        # CRITICAL FIX: Store (signal_object, signal_name, handler) tuples for reliable disconnection
        try:
            project.layersAdded.connect(self._on_layers_added)
            self._signal_connections.append((project.layersAdded, 'layersAdded', self._on_layers_added))
        except Exception as e:
            logger.warning("Failed to connect layersAdded: %s", e, exc_info=True)

        try:
            project.layersWillBeRemoved.connect(self._on_layers_removed)
            self._signal_connections.append((project.layersWillBeRemoved, 'layersWillBeRemoved', self._on_layers_removed))
        except Exception as e:
            logger.warning("Failed to connect layersWillBeRemoved: %s", e, exc_info=True)

        try:
            layer_tree_root = project.layerTreeRoot()
            if layer_tree_root:
                layer_tree_root.visibilityChanged.connect(self._on_visibility_changed)
                self._signal_connections.append((layer_tree_root.visibilityChanged, 'visibilityChanged', self._on_visibility_changed))
        except Exception as e:
            logger.warning("Failed to connect visibilityChanged: %s", e, exc_info=True)

        try:
            project.projectSaved.connect(self._on_project_saved)
            self._signal_connections.append((project.projectSaved, 'projectSaved', self._on_project_saved))
        except Exception as e:
            logger.warning("Failed to connect projectSaved: %s", e, exc_info=True)

        logger.debug("Wired %s signals", len(self._signal_connections))

    def _on_layers_added(self, layers: List[QgsVectorLayer]):
        """Handle layersAdded signal."""
        # CRITICAL FIX: Check cleanup flag FIRST
        if self._cleanup_in_progress:
            return

        # DEFENSIVE GUARD
        if not self.layer_manager or not self._layers or not self.project:
            logger.debug("layersAdded handler fired after cleanup; ignoring")
            return

        if not hasattr(self, '_signal_connections'):
            return

        try:
            # Filter to SAR Tracker managed layers
            managed_layers = []
            for layer in layers:
                if not isinstance(layer, QgsVectorLayer):
                    continue

                layer_id = layer.customProperty('sartracker:layer_id')
                if layer_id:
                    managed_layers.append((layer_id, layer))

            if not managed_layers:
                return

            # Schedule debounced refresh
            self._schedule_refresh(managed_layers)

        except Exception as e:
            logger.exception("layersAdded handler failed")

    def _on_layers_removed(self, layer_ids: List[str]):
        """Handle layersWillBeRemoved signal."""
        # CRITICAL FIX: Check cleanup flag FIRST
        if self._cleanup_in_progress:
            return

        # DEFENSIVE GUARD
        if not self.layer_manager or not self._layers:
            return

        try:
            removed_count = 0
            # Remove from cache
            for qgis_layer_id in layer_ids:
                # Find catalog layer_id by qgis_layer_id
                for catalog_id, info in list(self._layers.items()):
                    if info.qgis_layer_id == qgis_layer_id:
                        del self._layers[catalog_id]
                        self._disconnect_layer_signals(catalog_id)
                        removed_count += 1
                        logger.info("Removed %s from catalog cache", catalog_id)
                        self.layer_updated.emit(catalog_id)

            if removed_count > 0:
                logger.info("Removed %s managed layer(s) from catalog", removed_count)
                logger.debug("If layers are recreated, call rescan_layers() to refresh cache")

        except Exception as e:
            logger.exception("layersWillBeRemoved handler failed")

    def _on_visibility_changed(self, node: QgsLayerTreeNode):
        """Handle visibilityChanged signal."""
        # CRITICAL FIX: Check cleanup flag FIRST
        if self._cleanup_in_progress:
            return

        # DEFENSIVE GUARD
        if not self.layer_manager or not self._layers:
            return

        try:
            # TODO: Update visibility in cache
            # For now, just emit model_changed
            self.model_changed.emit()
        except Exception as e:
            logger.warning("visibilityChanged handler failed: %s", e, exc_info=True)

    def _on_project_saved(self):
        """Handle projectSaved signal."""
        # No-op for now - metadata already saved via layer properties
        pass

    def _schedule_refresh(self, layers: List[tuple]):
        """Schedule a debounced refresh for the given layers."""
        # Add to pending set
        for layer_id, _ in layers:
            self._pending_refresh_layers.add(layer_id)

        # Stop existing timer
        if self._refresh_timer and self._refresh_timer.isActive():
            self._refresh_timer.stop()

        # Create or reuse timer
        if not self._refresh_timer:
            self._refresh_timer = QTimer(self)
            self._refresh_timer.setSingleShot(True)
            self._refresh_timer.timeout.connect(self._execute_refresh)

        # Start timer (100ms debounce)
        self._refresh_timer.start(100)

    def _execute_refresh(self):
        """Execute the debounced refresh."""
        # CRITICAL FIX: Check cleanup flag FIRST
        if self._cleanup_in_progress:
            return

        # CRITICAL FIX: Check if timer still exists (guard against race condition)
        if not hasattr(self, '_refresh_timer') or self._refresh_timer is None:
            return

        # DEFENSIVE GUARD - Check all required components exist
        if not self.layer_manager or not self._layers:
            return

        if not hasattr(self, '_pending_refresh_layers'):
            return

        layer_ids = list(self._pending_refresh_layers)
        self._pending_refresh_layers.clear()

        if not layer_ids:
            return

        logger.debug("Refreshing %s layer(s) after debounce", len(layer_ids))

        for layer_id in layer_ids:
            try:
                self.refresh_layer(layer_id, full=False)
            except Exception as e:
                logger.warning("Error refreshing %s during debounced update: %s", layer_id, e, exc_info=True)

    # --------------------------------------------------------------------
    # Layer-level signal wiring (keeps catalog in sync with edits)
    # --------------------------------------------------------------------

    def _make_layer_refresh_handler(self, layer_id: str) -> Callable:
        """Return a handler that schedules a refresh for the given layer."""

        def _handler(*args, **kwargs):
            if self._cleanup_in_progress:
                return
            self._schedule_layer_refresh_by_id(layer_id)

        return _handler

    def _schedule_layer_refresh_by_id(self, layer_id: str) -> None:
        """
        Schedule refresh for a single layer id by looking up the QgsVectorLayer.

        BUG-034 FIX: Enhanced layer validity checking with comprehensive logging
        and project registration verification.
        """
        if not self.layer_manager:
            logger.debug("Layer refresh skipped - no layer_manager available")
            return

        layer = self.layer_manager.get_layer(layer_id)

        # BUG-034 FIX: Enhanced layer validity checking with detailed logging
        if not layer:
            logger.warning(
                "BUG-034: Layer %s not found in layer_manager - may have been deleted",
                layer_id
            )
            return

        if not layer.isValid():
            logger.warning(
                "BUG-034: Layer %s exists but is invalid (corrupted or source unavailable)",
                layer_id
            )
            return

        # BUG-034 FIX: Additional check - verify layer still registered with project
        project = QgsProject.instance()
        if project and not project.mapLayer(layer.id()):
            logger.warning(
                "BUG-034: Layer %s exists and is valid but not registered with current project",
                layer_id
            )
            return

        lock_info = self._detect_geopackage_lock(layer_id, layer)
        if lock_info:
            self._handle_locked_layer(layer_id, layer, lock_info)
            return

        self._schedule_refresh([(layer_id, layer)])

    def _extract_geopackage_path(self, layer: QgsVectorLayer) -> Optional[Path]:
        """Extract GeoPackage path from a QgsVectorLayer source string."""
        try:
            provider_name = ""
            data_provider = layer.dataProvider() if hasattr(layer, "dataProvider") else None
            if data_provider:
                provider_name = (data_provider.name() or "").lower()
            elif hasattr(layer, "providerType"):
                provider_name = (layer.providerType() or "").lower()
        except Exception:
            provider_name = ""

        if provider_name not in ("ogr",):
            return None

        try:
            source = layer.source()
        except Exception:
            return None

        if not source:
            return None

        base = source.split("|", 1)[0].strip()
        if base.startswith("file://"):
            base = base[7:]

        if not base.lower().endswith(".gpkg"):
            return None

        return Path(base)

    def _detect_geopackage_lock(
        self,
        layer_id: str,
        layer: QgsVectorLayer
    ) -> Optional[Tuple[Path, str]]:
        """Return lock details if the GeoPackage is currently locked."""
        gpkg_path = self._extract_geopackage_path(layer)
        if not gpkg_path or not gpkg_path.exists():
            return None

        conn = None
        try:
            conn = sqlite3.connect(str(gpkg_path), timeout=0.05)
            conn.execute("PRAGMA schema_version;")
        except sqlite3.OperationalError as exc:
            message = str(exc) or "database is locked"
            lowered = message.lower()
            if "locked" in lowered or "busy" in lowered:
                logger.warning(
                    "GeoPackage lock detected for %s (%s): %s",
                    layer_id,
                    gpkg_path,
                    message
                )
                return gpkg_path, message
        except Exception as exc:
            logger.debug(
                "GeoPackage lock probe failed for %s (%s): %s",
                layer_id,
                gpkg_path,
                exc,
                exc_info=True
            )
        finally:
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass
        return None

    def _handle_locked_layer(
        self,
        layer_id: str,
        layer: QgsVectorLayer,
        lock_info: Tuple[Path, str]
    ) -> None:
        """Notify user and retry refresh when GeoPackage is locked."""
        gpkg_path, reason = lock_info
        now = datetime.now(timezone.utc)
        last_alert = self._layer_lock_alerts.get(layer_id)
        should_notify = not last_alert or (now - last_alert).total_seconds() >= 15

        if should_notify:
            layer_name = ""
            try:
                layer_name = layer.name()
            except Exception:
                layer_name = layer_id
            friendly_name = layer_name or layer_id

            message = (
                f"{friendly_name} is locked by another application "
                f"(GeoPackage: {gpkg_path.name}). Retrying shortly."
            )
            if reason:
                message = f"{message} Details: {reason}"

            self._notify_warning("Mission Store Locked", message)
            self._layer_lock_alerts[layer_id] = now

        self._schedule_lock_retry(layer_id)

    def _schedule_lock_retry(self, layer_id: str, delay_ms: int = 1000) -> None:
        """Retry scheduling a layer refresh after a short delay."""
        if self._cleanup_in_progress:
            return

        def _retry():
            if self._cleanup_in_progress:
                return
            self._schedule_layer_refresh_by_id(layer_id)

        QTimer.singleShot(delay_ms, _retry)

    def _wire_layer_signals(self, layer_id: str, layer: QgsVectorLayer) -> None:
        """Connect per-layer signals so catalog stays in sync with edits."""
        if not layer:
            return

        self._disconnect_layer_signals(layer_id)

        handler = self._make_layer_refresh_handler(layer_id)
        signal_names = [
            "featureAdded",
            "featureDeleted",
            "geometryChanged",
            "attributeValueChanged",
            "dataChanged",
            "editingStopped",
            "afterCommitChanges",
            "committedFeaturesAdded",
            "committedFeaturesRemoved",
            "committedFeaturesDeleted",
            "committedAttributeValuesChanges",
            "committedGeometriesChanges"
        ]

        connections: List[tuple] = []

        for signal_name in signal_names:
            signal = getattr(layer, signal_name, None)
            if not signal:
                continue
            try:
                signal.connect(handler)
                connections.append((signal, handler))
            except Exception as exc:
                logger.warning(
                    "Could not connect %s for %s: %s",
                    signal_name,
                    layer_id,
                    exc,
                    exc_info=True
                )

        if connections:
            self._layer_signal_connections[layer_id] = connections

    def _safe_disconnect(self, signal_obj, handler=None, label: str = "") -> None:
        """
        Safely disconnect a Qt signal, skipping if the parent QObject is gone.

        Prevents the PyQt crash seen when calling disconnect() on a bound signal
        whose C++ parent has already been destroyed (common during QGIS shutdown).
        """
        if not signal_obj:
            return

        parent = getattr(signal_obj, "__self__", None)
        if parent is None:
            return

        if isinstance(parent, QObject):
            try:
                # Accessing objectName triggers RuntimeError if QObject is deleted
                _ = parent.objectName()
            except (RuntimeError, AttributeError):
                return

        try:
            if handler:
                signal_obj.disconnect(handler)
            else:
                signal_obj.disconnect()
        except (TypeError, RuntimeError, AttributeError) as exc:
            if label:
                logger.debug("Could not disconnect %s: %s", label, exc)

    def _disconnect_layer_signals(self, layer_id: str) -> None:
        """Disconnect per-layer signal handlers for a specific layer."""
        connections = self._layer_signal_connections.pop(layer_id, [])
        for signal, handler in connections:
            self._safe_disconnect(signal, handler, label=f"layer {layer_id}")

    def _disconnect_all_layer_signals(self) -> None:
        """Disconnect all layer-level signals (called on cache rebuild/cleanup)."""
        for layer_id in list(self._layer_signal_connections.keys()):
            self._disconnect_layer_signals(layer_id)

    def _on_mission_store_changed(self, new_path: str):
        """Handle mission store path change (HIGH-7)."""
        # DEFENSIVE GUARD
        if self._cleanup_in_progress:
            return

        if not self.layer_manager or not self._layers:
            return

        try:
            logger.info("Mission store changed to %s", new_path)
            # BUG-059 fix: Defer cache rebuild to next event loop iteration
            # This allows UI to update before the blocking operation, improving perceived responsiveness
            # Note: Layer operations MUST run on UI thread (Qt requirement), so we cannot use QgsTask
            self._notify_info("Layer Catalog", "Rebuilding layer cache...")
            QTimer.singleShot(10, self._build_cache_with_notification)
        except Exception as e:
            logger.exception("Error handling mission store change")
            self._notify_error("Mission Store", f"Could not reload mission data: {e}")

    # ========================================================================
    # DIAGNOSTICS (Phase 5 Prep)
    # ========================================================================

    def get_catalog_snapshot(self) -> Dict[str, Any]:
        """
        Return diagnostic snapshot for diagnostics panel.

        Returns:
            Dictionary with catalog statistics and warnings
        """
        # Count layers by provider
        memory_count = sum(1 for info in self._layers.values() if info.provider == 'memory')
        persistent_count = sum(1 for info in self._layers.values() if info.provider == 'ogr')

        # Build warnings
        warnings = []
        if memory_count > 0:
            warnings.append(f"{memory_count} layer(s) still using memory provider")

        mission_store_path = ""
        if self.layer_manager:
            try:
                mission_store_path = self.layer_manager.get_mission_store() or ""
            except Exception as exc:
                warnings.append(f"Mission store lookup failed: {exc}")

        return {
            "layer_count": len(self._layers),
            "group_count": len(self._groups),
            "memory_layers": memory_count,
            "persistent_layers": persistent_count,
            "total_features": sum(info.feature_count for info in self._layers.values()),
            "warnings": warnings,
            "mission_store_path": mission_store_path,
            "last_refresh": datetime.now(timezone.utc).isoformat()
        }

    def dump_catalog(self, path: str) -> None:
        """
        Write catalog JSON to file for debugging.

        Args:
            path: Output file path
        """
        import json
        from dataclasses import asdict

        data = {
            "groups": [asdict(g) for g in self._groups.values()],
            "layers": [asdict(l) for l in self._layers.values()],
            "snapshot": self.get_catalog_snapshot()
        }

        try:
            with open(path, 'w') as f:
                json.dump(data, f, indent=2, default=str)
            logger.info("Dumped catalog snapshot to %s", path)
        except OSError as exc:
            logger.exception("Failed to dump catalog to %s", path)
            self._notify_warning("Catalog Dump Failed", f"Could not write catalog file: {exc}")

    # ========================================================================
    # LIFECYCLE
    # ========================================================================

    def cleanup(self):
        """
        Clean up resources on plugin unload.

        CRITICAL: Called from LayersController.cleanup().
        Must disconnect ALL signals to prevent post-unload crashes.
        """
        # CRITICAL FIX: Set cleanup flag FIRST (before any other operations)
        self._cleanup_in_progress = True
        logger.info("LayerCatalogService cleanup started")

        # CRITICAL FIX: Stop timer IMMEDIATELY after setting cleanup flag
        # This prevents race condition where timer fires between flag set and signal disconnect
        if self._refresh_timer:
            try:
                if self._refresh_timer.isActive():
                    self._refresh_timer.stop()  # Stop BEFORE disconnect
                logger.debug("Stopped refresh timer")
            except (RuntimeError, TypeError):
                pass

        # CRITICAL FIX: Disconnect signals SECOND (after timer stopped)
        if hasattr(self, '_signal_connections'):
            for signal_obj, signal_name, handler in self._signal_connections:
                self._safe_disconnect(signal_obj, handler, label=signal_name)

        # Clear tracking
        self._signal_connections = []
        self._disconnect_all_layer_signals()

        # Disconnect timer signal (if connected)
        if self._refresh_timer:
            self._safe_disconnect(self._refresh_timer.timeout, self._execute_refresh, label="refresh_timer.timeout")

        # THEN delete timer (safe - stopped and disconnected)
        if self._refresh_timer:
            try:
                self._refresh_timer.deleteLater()
            except (RuntimeError, TypeError):
                pass
            finally:
                self._refresh_timer = None

        # Clear cache (in-place to break external references)
        self._groups.clear()
        self._layers.clear()
        self._pending_refresh_layers.clear()

        task_manager = getattr(self, "_task_manager", None)
        if task_manager:
            try:
                task_manager.cancel_all()
            except Exception:
                pass
            if getattr(self, "_owned_task_manager", False):
                self._task_manager = None

        # Null out references
        self.layer_manager = None
        self.iface = None
        self.project = None

        self._message_bar = None
        logger.info("LayerCatalogService cleanup complete")
