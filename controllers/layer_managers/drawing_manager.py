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

from typing import List, Optional, Dict, Any, Set, Union, Tuple
from collections import OrderedDict
from pathlib import Path
import uuid
import logging
import math
from datetime import datetime, timezone

# Set up logger for this module
logger = logging.getLogger(__name__)


class BoundedSet:
    """
    A bounded set that evicts oldest entries when max_size is exceeded.

    Uses an OrderedDict internally for efficient LRU-style eviction.
    Thread-safety: NOT thread-safe. Use in main thread only.

    Args:
        max_size: Maximum number of entries (default: 100)
    """

    def __init__(self, max_size: int = 100):
        self._max_size = max(1, max_size)
        self._data: OrderedDict = OrderedDict()

    def add(self, item) -> None:
        """Add item, evicting oldest if at capacity."""
        if item in self._data:
            # Move to end (most recently used)
            self._data.move_to_end(item)
            return

        # Evict oldest entries if at capacity
        while len(self._data) >= self._max_size:
            oldest = next(iter(self._data))
            del self._data[oldest]
            logger.debug("BoundedSet: Evicted oldest entry: %s", oldest)

        self._data[item] = True

    def __contains__(self, item) -> bool:
        return item in self._data

    def __len__(self) -> int:
        return len(self._data)

    def clear(self) -> None:
        """Remove all entries."""
        self._data.clear()

    def __iter__(self):
        return iter(self._data.keys())

from qgis.core import (
    QgsVectorLayer, QgsField, QgsFeature, QgsGeometry,
    QgsPointXY, QgsDistanceArea, QgsProject, QgsLineSymbol,
    QgsMarkerSymbol, QgsFeatureRequest, QgsWkbTypes,
    QgsFillSymbol, QgsPointPatternFillSymbolLayer,
    QgsSimpleMarkerSymbolLayer, QgsSimpleLineSymbolLayer,
    QgsSimpleFillSymbolLayer, QgsUnitTypes
)
from qgis.PyQt.QtCore import QVariant
from qgis.core import NULL
from qgis.PyQt.QtGui import QColor

from .base_manager import BaseLayerManager
from ...layers import LayerIds
from ..per_item_layer_factory import ItemType, PerItemLayerFactory, SAR_ITEM_TYPE
from ...utils.drawing_math import (
    geodesic_bearing_endpoint,
    geodesic_circle_points,
    geodesic_sector_points,
    calculate_sector_arc_length
)
from ...utils.drawing_validation import (
    validate_point,
    validate_point_sequence,
    validate_positive_number,
    validate_bearing,
    validate_color_hex,
    validate_font_size,
    validate_width
)
from ...utils.exceptions import LayerTransactionError, LayerLockError, GeometryError
from ...utils.notify import error as notify_error, safe_error


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
    MAX_SYNC_FEATURES = 500  # Hint threshold for bulk operations

    # Maximum number of GPX file paths to track (prevents unbounded memory growth)
    MAX_GPX_IMPORT_HISTORY = 100

    # Maximum text label length (GeoPackage/SQLite VARCHAR limit)
    MAX_TEXT_LABEL_LENGTH = 255

    # Phase 4: Enable per-item layers for specific drawing types
    # When True, new drawings of these types create individual layers
    # When False, use legacy shared layers (backward compatibility)
    USE_PER_ITEM_LAYERS = {
        "search_area": True,    # Phase 4 Step 3: Search Areas use per-item layers
        "range_ring": True,     # Phase 4 Step 3: Range Rings use per-item layers
        "bearing_line": True,   # Phase 4 Step 3: Bearing Lines use per-item layers
        "line": True,           # Phase 4 Step 3: Lines use per-item layers
        "sector": True,         # Search sectors use per-item layers
        "text_label": True,     # Text labels use per-item layers
    }

    def __init__(self, iface, shared_device_colors=None, layer_manager=None):
        """Initialize drawing layer manager with GPX support."""
        super().__init__(iface, shared_device_colors, layer_manager)

        # Initialize GPX import support
        # Uses BoundedSet to prevent unbounded memory growth from long-running sessions
        self._gpx_watcher = None
        self._watched_gpx_folder = None
        self._imported_gpx_files = BoundedSet(max_size=self.MAX_GPX_IMPORT_HISTORY)

        # Phase 4: Per-item layer factory (lazy initialized)
        self._per_item_factory: Optional[PerItemLayerFactory] = None

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
    # Phase 4: Per-Item Layer Helpers
    # =========================================================================

    def _uses_per_item_layers(self, drawing_type: str) -> bool:
        """
        Check if the given drawing type should use per-item layers.

        Args:
            drawing_type: One of "search_area", "range_ring", "bearing_line", "line",
                         "sector", "text_label"

        Returns:
            True if per-item layers should be used, False for legacy shared layers
        """
        return self.USE_PER_ITEM_LAYERS.get(drawing_type, False)

    def _is_uuid(self, value: object) -> bool:
        """Return True if value looks like a UUID string."""
        if not isinstance(value, str):
            return False
        try:
            uuid.UUID(value)
            return True
        except (ValueError, AttributeError, TypeError):
            return False

    def _get_per_item_layer(self, item_type: str, item_id: str) -> Optional[QgsVectorLayer]:
        """
        Return per-item layer for item_id if it matches the expected type.
        """
        if not item_id or not isinstance(item_id, str):
            return None

        factory = self._get_per_item_factory()
        if not factory:
            return None

        layer = factory.get_layer_by_item_id(item_id)
        if not layer or not layer.isValid():
            return None

        layer_item_type = layer.customProperty(SAR_ITEM_TYPE)
        if layer_item_type and layer_item_type != item_type:
            logger.warning(
                "Phase 4: Per-item layer type mismatch for %s: expected %s, got %s",
                item_id, item_type, layer_item_type
            )
            return None

        return layer

    def _get_single_feature(self, layer: QgsVectorLayer) -> Optional[QgsFeature]:
        """Return the first feature in a layer (per-item layers store one feature)."""
        for feature in layer.getFeatures():
            return feature
        return None

    def _list_per_item_records(self, item_type: str) -> List[Dict[str, Any]]:
        """Return records for all loaded per-item layers of the given type."""
        records: List[Dict[str, Any]] = []
        factory = self._get_per_item_factory()
        if not factory:
            return records

        try:
            items = factory.get_all_item_layers(item_type=item_type)
        except Exception as exc:
            logger.warning("Phase 4: Failed to enumerate per-item layers for %s: %s", item_type, exc)
            return records

        for item_info in items:
            layer = item_info.layer
            if not layer or not layer.isValid():
                continue
            for feature in layer.getFeatures():
                try:
                    record = self._feature_to_record(feature, layer)
                    if record:
                        records.append(record)
                except Exception as exc:
                    logger.warning(
                        "Phase 4: Failed to serialize per-item %s %s: %s",
                        item_type, item_info.item_id, exc
                    )
        return records

    def get_per_item_feature_for_layer_id(
        self,
        layer_id: str,
        item_id: str
    ) -> Optional[Tuple[QgsVectorLayer, QgsFeature]]:
        """
        Return (layer, feature) for a per-item drawing layer.
        """
        layer_map = {
            LayerIds.LINES: ("line", ItemType.LINE),
            LayerIds.SEARCH_AREAS: ("search_area", ItemType.SEARCH_AREA),
            LayerIds.RANGE_RINGS: ("range_ring", ItemType.RANGE_RING),
            LayerIds.BEARING_LINES: ("bearing_line", ItemType.BEARING_LINE),
            LayerIds.SEARCH_SECTORS: ("sector", ItemType.SEARCH_SECTOR),
            LayerIds.TEXT_LABELS: ("text_label", ItemType.TEXT_LABEL),
        }
        mapping = layer_map.get(layer_id)
        if not mapping:
            return None

        drawing_type, item_type = mapping
        if not self._uses_per_item_layers(drawing_type):
            return None

        layer = self._get_per_item_layer(item_type, item_id)
        if not layer:
            return None

        feature = self._get_single_feature(layer)
        if not feature:
            return None

        return (layer, feature)

    def _cleanup_failed_per_item_layer(
        self,
        factory: PerItemLayerFactory,
        item_id: str,
        context: str
    ) -> None:
        """Remove per-item layer/table after a failed create."""
        try:
            factory.delete_item_layer(
                item_id=item_id,
                remove_table=True,
                hard_delete=True
            )
            logger.warning(
                "Phase 4: Cleaned up failed per-item %s layer %s",
                context,
                item_id
            )
        except Exception as exc:
            logger.warning(
                "Phase 4: Failed to clean up per-item %s layer %s: %s",
                context,
                item_id,
                exc
            )

    def _get_per_item_factory(self) -> PerItemLayerFactory:
        """
        Get or create the PerItemLayerFactory for per-item layers.

        Returns:
            PerItemLayerFactory
        """
        # Return cached factory if available
        if self._per_item_factory is not None:
            return self._per_item_factory

        # Mission store required for per-item layers
        gpkg_path = self._require_mission_store("Per-item drawing operations")

        # Create factory
        self._per_item_factory = PerItemLayerFactory(
            gpkg_path=Path(gpkg_path),
            auto_wal=True,
            auto_registry=True
        )
        logger.info("Phase 4: PerItemLayerFactory initialized with mission store: %s", gpkg_path)
        return self._per_item_factory

    def _ensure_per_item_group(self, item_type: str) -> Optional[Any]:
        """
        Ensure the target group exists for per-item layers.

        Args:
            item_type: ItemType string value (e.g., ItemType.SEARCH_AREA which is "search_area")
                       Note: ItemType is a class with string constants, NOT an enum.

        Returns:
            QgsLayerTreeGroup or None if not available
        """
        from ...layers import get_per_item_group_path

        # ItemType values are strings (e.g., ItemType.LINE = "line"), not enums
        # Do NOT call .value on them
        group_path = get_per_item_group_path(item_type)
        if not group_path:
            logger.warning("Phase 4: No group path defined for item type: %s", item_type)
            return None

        # Get or create the group
        root = QgsProject.instance().layerTreeRoot()
        return self._get_or_create_nested_group(root, group_path)

    def _get_or_create_nested_group(self, parent, path_parts: List[str]):
        """
        Get or create a nested group structure.

        Args:
            parent: Parent QgsLayerTreeGroup
            path_parts: List of group names to create/find

        Returns:
            The deepest group in the path
        """
        from qgis.core import QgsLayerTreeGroup

        current = parent
        for part in path_parts:
            found = None
            for child in current.children():
                if isinstance(child, QgsLayerTreeGroup) and child.name() == part:
                    found = child
                    break
            if found:
                current = found
            else:
                current = current.addGroup(part)
        return current

    def _current_timestamp(self) -> str:
        """Return ISO timestamp for audit fields (timezone-aware UTC)."""
        return datetime.now(timezone.utc).isoformat()

    def _style_lines_layer(self, layer: QgsVectorLayer):
        symbol = QgsLineSymbol.createSimple({'color': '#FF0000', 'width': '0.7'})
        layer.renderer().setSymbol(symbol)

    def _style_search_areas_layer(self, layer: QgsVectorLayer):
        symbol = layer.renderer().symbol()
        symbol.setColor(QColor(0, 100, 255, 80))
        symbol.symbolLayer(0).setStrokeColor(QColor(0, 100, 255))
        symbol.symbolLayer(0).setStrokeWidth(2)

    def _style_range_rings_layer(self, layer: QgsVectorLayer):
        """Style range rings with 'zelda' triangle pattern at 15% opacity.

        Pattern structure:
        - Simple Fill (transparent background)
        - Point Pattern Fill with triangle markers (4.8mm grid, 1.2mm displacement)
        - Simple Line (orange outline)

        Triangle markers: 4.6mm, orange fill and stroke
        Layer opacity: 15%
        """
        orange = QColor(255, 165, 0)

        # Create fresh fill symbol
        symbol = QgsFillSymbol()
        symbol.deleteSymbolLayer(0)  # Remove default

        # 1. Simple Fill - transparent background (no stroke)
        simple_fill = QgsSimpleFillSymbolLayer()
        simple_fill.setColor(QColor(0, 0, 0, 0))  # Transparent
        simple_fill.setStrokeWidth(0)  # No stroke
        symbol.appendSymbolLayer(simple_fill)

        # 2. Point Pattern Fill with triangle markers
        point_pattern = QgsPointPatternFillSymbolLayer()
        point_pattern.setDistanceX(4.8)
        point_pattern.setDistanceY(4.8)
        point_pattern.setDisplacementX(1.2)
        point_pattern.setDisplacementY(0.0)
        point_pattern.setDistanceXUnit(QgsUnitTypes.RenderMillimeters)
        point_pattern.setDistanceYUnit(QgsUnitTypes.RenderMillimeters)
        point_pattern.setDisplacementXUnit(QgsUnitTypes.RenderMillimeters)
        point_pattern.setDisplacementYUnit(QgsUnitTypes.RenderMillimeters)

        # Create triangle marker
        triangle_marker = QgsSimpleMarkerSymbolLayer()
        triangle_marker.setShape(QgsSimpleMarkerSymbolLayer.Triangle)
        triangle_marker.setSize(4.6)
        triangle_marker.setSizeUnit(QgsUnitTypes.RenderMillimeters)
        triangle_marker.setColor(orange)
        triangle_marker.setStrokeColor(orange)
        triangle_marker.setStrokeWidth(0.2)
        triangle_marker.setStrokeWidthUnit(QgsUnitTypes.RenderMillimeters)

        # Create marker symbol and set as sub-symbol
        marker_symbol = QgsMarkerSymbol()
        marker_symbol.deleteSymbolLayer(0)
        marker_symbol.appendSymbolLayer(triangle_marker)
        point_pattern.setSubSymbol(marker_symbol)

        symbol.appendSymbolLayer(point_pattern)

        # 3. Simple Line - orange outline
        simple_line = QgsSimpleLineSymbolLayer()
        simple_line.setColor(orange)
        simple_line.setWidth(1.5)
        simple_line.setWidthUnit(QgsUnitTypes.RenderMillimeters)
        symbol.appendSymbolLayer(simple_line)

        # Apply symbol to layer
        layer.renderer().setSymbol(symbol)

        # Set layer opacity to 15%
        layer.setOpacity(0.15)

    def _style_bearing_lines_layer(self, layer: QgsVectorLayer):
        symbol = QgsLineSymbol.createSimple({'color': 'purple', 'width': '2'})
        layer.renderer().setSymbol(symbol)

    def _style_sectors_layer(self, layer: QgsVectorLayer):
        symbol = layer.renderer().symbol()
        symbol.setColor(QColor(255, 100, 100, 60))
        symbol.symbolLayer(0).setStrokeColor(QColor(255, 100, 100))
        symbol.symbolLayer(0).setStrokeWidth(2)

    def _style_text_labels_layer(self, layer: QgsVectorLayer):
        layer.renderer().symbol().setSize(0)

    def _log_drawing_event(self, layer: QgsVectorLayer, layer_type: str, action: str, **extra):
        """Emit diagnostics for drawing layers when enabled."""
        payload = extra if extra else None
        self._log_layer_snapshot(layer, f"{layer_type}::{action}", payload)

    def _require_valid_layer(self, layer: QgsVectorLayer, layer_name: str) -> QgsVectorLayer:
        """Raise if layer is invalid to avoid operating on a bad reference."""
        if not layer or not layer.isValid():
            raise LayerTransactionError(
                layer_name=layer_name,
                operation="layer access",
                details="Layer not available or invalid"
            )
        return layer

    def _check_transaction_isolation(self, layer: QgsVectorLayer, operation: str) -> None:
        """
        Check if layer is available for a new transaction.

        BUG-060 FIX: Provides explicit transaction conflict detection with logging.
        This helps diagnose concurrent edit issues and potential race conditions.

        Args:
            layer: Layer to check
            operation: Description of the operation being attempted

        Raises:
            LayerLockError: If layer is already in edit mode (transaction conflict)
        """
        if layer.isEditable():
            # BUG-060 FIX: Log transaction conflict for diagnostics
            logger.warning(
                "BUG-060: Transaction conflict detected on layer '%s' during '%s' - "
                "layer is already in edit mode. This may indicate a race condition "
                "or unclosed transaction.",
                layer.name(),
                operation
            )
            raise LayerLockError(layer.name())

    # ------------------------------------------------------------------
    # BUG-017 FIX: Layer Recreation Logic
    # ------------------------------------------------------------------

    def _get_or_recreate_layer(
        self,
        layer_id: str,
        layer_name: str,
        style_factory,
        allow_recreate: bool = True
    ) -> QgsVectorLayer:
        """
        Get a valid layer or attempt to recreate it if invalid.

        BUG-017 FIX: Provides fallback layer recreation when a layer becomes
        invalid (e.g., due to GeoPackage lock, project changes, or corruption).

        Args:
            layer_id: The schema layer ID
            layer_name: Human-readable layer name for logging
            style_factory: Method to apply styling to the layer
            allow_recreate: If True, attempt to recreate invalid layers

        Returns:
            QgsVectorLayer: A valid layer

        Raises:
            LayerTransactionError: If layer cannot be obtained or recreated
        """
        # First attempt: get existing layer
        try:
            layer = self._ensure_schema_layer(
                layer_id,
                fallback_name=layer_name,
                style_factory=style_factory
            )

            if layer and layer.isValid():
                return layer

        except Exception as e:
            logger.warning(
                "Initial layer retrieval failed for '%s': %s",
                layer_name, e
            )

        if not allow_recreate:
            raise LayerTransactionError(
                layer_name=layer_name,
                operation="layer access",
                details="Layer is invalid and recreation not allowed"
            )

        # BUG-017 FIX: Attempt layer recreation
        logger.warning(
            "Layer '%s' is invalid, attempting recreation...",
            layer_name
        )

        try:
            # Clear any cached references
            if self.layer_manager:
                self.layer_manager.invalidate_cache(layer_id)

            # Re-ensure the layer (will create fresh if needed)
            layer = self._ensure_schema_layer(
                layer_id,
                fallback_name=layer_name,
                style_factory=style_factory
            )

            if layer and layer.isValid():
                logger.info(
                    "Successfully recreated layer '%s'",
                    layer_name
                )
                return layer

        except Exception as recreate_exc:
            logger.error(
                "Layer recreation failed for '%s': %s",
                layer_name,
                recreate_exc
            )

        # All attempts failed
        raise LayerTransactionError(
            layer_name=layer_name,
            operation="layer recreation",
            details=f"Could not obtain or recreate layer '{layer_name}'. "
                    "Check GeoPackage file locks and project settings."
        )

    def _get_shared_layer_if_exists(self, layer_id: str, layer_name: str) -> Optional[QgsVectorLayer]:
        """
        Return an existing shared layer without creating placeholders.

        Used for legacy layers when per-item mode is enabled.
        """
        if self.layer_manager:
            layer = self.layer_manager.get_layer(layer_id)
            if layer and layer.isValid():
                return layer

        layers = self.project.mapLayersByName(layer_name)
        if layers:
            layer = layers[0]
            if layer and layer.isValid():
                return layer

        return None

    def _notify_error(self, title: str, message: str):
        """Show a user-facing error if iface/messageBar is available.

        LIFECYCLE SAFETY: Uses safe_error to guard against deleted Qt objects.
        """
        # Use safe_error which handles None iface, deleted objects, and exceptions
        safe_error(getattr(self, "iface", None), title, message)

    def _safe_commit(self, layer: QgsVectorLayer, operation: str, layer_type: str, context: Dict[str, Any]) -> None:
        """
        Commit edits and raise typed error with user notification on failure.
        """
        if not layer.commitChanges():
            errors = layer.commitErrors()
            msg = f"Commit failed: {', '.join(errors)}"
            self._notify_error(f"{operation} Failed", msg)
            raise RuntimeError(msg)
        self._log_drawing_event(layer, layer_type, operation, **context)

    def _set_display_order(self, layer: QgsVectorLayer, feature_id: int):
        """
        Set display_order field to feature_id for deterministic ordering.

        Safe to call even if the field is missing.
        """
        field_idx = layer.fields().indexFromName("display_order")
        if field_idx == -1:
            return
        try:
            layer.changeAttributeValue(feature_id, field_idx, int(feature_id))
        except Exception as exc:
            logger.warning(
                "Failed to set display_order for %s feature %s: %s",
                layer.name(),
                feature_id,
                exc
            )

    def _sort_records_by_display_order(self, records: List[Dict]) -> List[Dict]:
        """Return records ordered by display_order if present."""
        return sorted(
            records,
            key=lambda rec: rec.get('display_order', rec.get('feature_id', 0))
        )

    def _build_filter_request(self, layer: QgsVectorLayer, filters: Optional[Dict]) -> QgsFeatureRequest:
        """Safely build a QgsFeatureRequest with simple equality filters."""
        request = QgsFeatureRequest()
        if not filters:
            return request

        expressions = []
        for field_name, value in filters.items():
            if layer.fields().indexFromName(field_name) == -1:
                logger.warning("Unknown filter field %s on layer %s", field_name, layer.name())
                continue
            if isinstance(value, str):
                expressions.append(f'"{field_name}" = \'{value}\'')
            elif isinstance(value, (int, float)):
                expressions.append(f'"{field_name}" = {value}')
            elif value is None:
                expressions.append(f'"{field_name}" IS NULL')

        if expressions:
            try:
                request.setFilterExpression(' AND '.join(expressions))
            except Exception as exc:
                logger.warning("Invalid filter expression on %s: %s", layer.name(), exc)
        return request

    # =========================================================================
    # Lines Layer
    # =========================================================================

    def _get_or_create_lines_layer(self) -> QgsVectorLayer:
        """
        Get or create Lines layer for drawn paths/routes.

        Returns:
            QgsVectorLayer: Lines layer
        """
        if self.layer_manager:
            layer = self._ensure_schema_layer(
                LayerIds.LINES,
                fallback_name=self.LINES_LAYER_NAME,
                style_factory=self._style_lines_layer
            )
            layer = self._require_valid_layer(layer, self.LINES_LAYER_NAME)
            self._ensure_lines_layer_schema(layer)
            self._log_drawing_event(layer, "LINES", "ensure")
            return layer

        layers = self.project.mapLayersByName(self.LINES_LAYER_NAME)
        if layers:
            layer = layers[0]
            layer = self._require_valid_layer(layer, self.LINES_LAYER_NAME)
            self._ensure_lines_layer_schema(layer)
            self._log_drawing_event(layer, "LINES", "reused")
            return layer

        # Create memory layer with WGS84 CRS
        # Qt5/Qt6 Compatible: Using integer type codes (10=String, 2=Int, 6=Double)
        layer = QgsVectorLayer(
            "LineString?crs=EPSG:4326",
            self.LINES_LAYER_NAME,
            "memory"
        )

        # Add fields
        layer.dataProvider().addAttributes([
            QgsField("id", QVariant.String),           # String - unique ID
            QgsField("name", QVariant.String),         # String - line name
            QgsField("description", QVariant.String),  # String - notes
            QgsField("color", QVariant.String),        # String - hex color
            QgsField("width", QVariant.Int),           # Int - line width in pixels
            QgsField("distance_m", QVariant.Double),   # Double - length in meters
            QgsField("created", QVariant.String),      # String - ISO timestamp
            QgsField("temporary_measure", QVariant.Bool),  # Bool - measurement overlay flag
            QgsField("display_order", QVariant.Int),   # Int - display order for UI (Phase 2)
        ])
        layer.updateFields()

        # Basic styling
        symbol = QgsLineSymbol.createSimple({'color': 'red', 'width': '2'})
        layer.renderer().setSymbol(symbol)

        # Add to project in layer group
        self._add_layer_to_group(layer, position=0)

        self._log_drawing_event(layer, "LINES", "created")
        return self._require_valid_layer(layer, self.LINES_LAYER_NAME)

    def add_line(self, name: str, points_wgs84: List[QgsPointXY],
                 description: str = "", color: str = "#FF0000", width: int = 2,
                 temporary_measure: bool = False) -> Union[int, str]:
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
        try:
            points_wgs84 = list(points_wgs84)
            validate_point_sequence(points_wgs84, min_points=2, name="points_wgs84")
            validate_color_hex(color, "color")
            validate_width(width, "width")
        except Exception as exc:
            self._notify_error("Add Line Failed", str(exc))
            raise

        # Phase 4: Check if we should use per-item layers
        if self._uses_per_item_layers("line"):
            return self._add_line_per_item(
                name=name, points_wgs84=points_wgs84, description=description,
                color=color, width=width, temporary_measure=temporary_measure
            )

        # Legacy path: shared layer
        return self._add_line_shared_layer(
            name=name, points_wgs84=points_wgs84, description=description,
            color=color, width=width, temporary_measure=temporary_measure
        )

    def _add_line_shared_layer(
        self, name: str, points_wgs84: List[QgsPointXY], description: str,
        color: str, width: int, temporary_measure: bool
    ) -> int:
        """Legacy implementation: Add line to shared layer."""
        layer = self._get_or_create_lines_layer()
        self._ensure_lines_layer_schema(layer)

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

        logger.debug(f"Line '{name}': {len(points_wgs84)} points, total distance={total_distance:.2f}m")

        # Create feature
        feature = QgsFeature(layer.fields())
        feature.setGeometry(QgsGeometry.fromPolylineXY(points_wgs84))

        # IMPORTANT: Set attributes by field name (not positional list).
        # Persistent (GeoPackage/OGR) layers may include provider-managed fields
        # (e.g. fid) that vary by QGIS version/platform, and positional
        # setAttributes() will fail with "wrong field count".
        attr_map = {
            "id": str(uuid.uuid4()),
            "name": name,
            "description": description,
            "color": color,
            "width": int(width),
            "distance_m": float(total_distance),
            "created": self._current_timestamp(),
            "temporary_measure": bool(temporary_measure),
            "display_order": None,  # set after addFeature
        }
        fields = layer.fields()
        for field_name, value in attr_map.items():
            idx = fields.indexFromName(field_name)
            if idx != -1:
                feature.setAttribute(idx, value)

        # Add to layer with proper resource cleanup
        # CRITICAL: Check for nested transactions
        if layer.isEditable():
            raise LayerLockError(layer.name())

        layer.startEditing()
        try:
            if not layer.addFeature(feature):
                layer.rollBack()
                raise RuntimeError(f"Failed to add feature to {self.LINES_LAYER_NAME} layer")
            self._set_display_order(layer, feature.id())
            self._safe_commit(layer, "add", "LINES", {})
        except Exception as e:
            layer.rollBack()
            # Raise typed exception for error handler (Issue #3)
            raise LayerTransactionError(
                self.LINES_LAYER_NAME,
                "add feature",
                details=str(e)
            ) from e
        finally:
            # Ensure layer is not left in edit mode
            if layer.isEditable():
                layer.rollBack()

        layer.triggerRepaint()
        self._log_drawing_event(
            layer,
            "LINES",
            "add",
            name=name,
            points=len(points_wgs84),
            distance_m=total_distance,
            temporary=temporary_measure
        )
        return feature.id()

    def _add_line_per_item(
        self, name: str, points_wgs84: List[QgsPointXY], description: str,
        color: str, width: int, temporary_measure: bool
    ) -> str:
        """
        Phase 4: Add line as a per-item layer.

        Creates an individual GeoPackage-backed layer for this line,
        placed under "SAR Tracker / Map Tools / Lines /".

        Returns:
            str: item_id (which serves as the feature identifier)
        """
        factory = self._get_per_item_factory()
        if not factory:
            # Fallback to shared layer if no mission store configured
            logger.warning("Phase 4: No factory available, falling back to shared layer for line")
            return self._add_line_shared_layer(
                name=name, points_wgs84=points_wgs84, description=description,
                color=color, width=width, temporary_measure=temporary_measure
            )

        # Ensure the target group exists
        target_group = self._ensure_per_item_group(ItemType.LINE)

        # Define fields for the line layer (matching schema)
        line_fields = [
            {"name": "id", "type": "String", "length": 50},
            {"name": "name", "type": "String", "length": 255},
            {"name": "description", "type": "String", "length": 1000},
            {"name": "color", "type": "String", "length": 20},
            {"name": "width", "type": "Int"},
            {"name": "distance_m", "type": "Double"},
            {"name": "created", "type": "String", "length": 50},
            {"name": "temporary_measure", "type": "Int"},  # Boolean stored as 0/1
            {"name": "display_order", "type": "Int"},
        ]

        # Create the per-item layer
        try:
            item_info = factory.create_item_layer(
                item_type=ItemType.LINE,
                display_name=name,
                fields=line_fields,
                add_to_project=True,
                target_group=target_group
            )
        except Exception as e:
            logger.error("Phase 4: Failed to create per-item layer for line '%s': %s", name, e)
            raise RuntimeError(f"Failed to create per-item line layer: {e}") from e

        layer = item_info.layer
        item_id = item_info.item_id

        if not layer or not layer.isValid():
            raise RuntimeError(f"Per-item layer created but invalid for line '{name}'")

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

        logger.debug(f"Line '{name}' (per-item): {len(points_wgs84)} points, total distance={total_distance:.2f}m")

        # Create and add the feature to the layer
        feature = QgsFeature(layer.fields())
        feature.setGeometry(QgsGeometry.fromPolylineXY(points_wgs84))

        created_ts = datetime.now(timezone.utc).isoformat()
        attr_map = {
            "id": item_id,  # Use item_id as the feature id
            "name": name,
            "description": description,
            "color": color,
            "width": int(width),
            "distance_m": float(total_distance),
            "created": created_ts,
            "temporary_measure": 1 if temporary_measure else 0,
        }

        fields = layer.fields()
        for field_name, value in attr_map.items():
            idx = fields.indexFromName(field_name)
            if idx != -1:
                feature.setAttribute(idx, value)

        # Add feature to layer
        if layer.isEditable():
            raise LayerLockError(layer.name())

        layer.startEditing()
        try:
            if not layer.addFeature(feature):
                layer.rollBack()
                raise RuntimeError(f"Failed to add feature to per-item line layer '{name}'")
            self._set_display_order(layer, feature.id())
            self._safe_commit(layer, "add", "LINES", {})
        except Exception as e:
            layer.rollBack()
            self._cleanup_failed_per_item_layer(factory, item_id, "line")
            raise LayerTransactionError(
                name,
                "add feature",
                details=str(e)
            ) from e
        finally:
            if layer.isEditable():
                layer.rollBack()

        # Apply styling
        self._style_lines_layer(layer)

        layer.triggerRepaint()
        logger.info(
            "Phase 4: Created per-item line layer '%s' (item_id=%s) under Map Tools/Lines",
            name, item_id
        )
        return item_id

    def add_measurement_overlay(self, name: str, points_wgs84: List[QgsPointXY],
                                description: str, color: str = "#FFD447",
                                width: int = 3) -> int:
        """
        Add a temporary measurement overlay feature to the Lines layer.

        Args:
            name: Overlay name
            points_wgs84: Line points in WGS84 CRS
            description: Detail text (distance/bearing)
            color: Line color
            width: Line width

        Returns:
            int: Feature ID
        """
        return self.add_line(
            name=name,
            points_wgs84=points_wgs84,
            description=description,
            color=color,
            width=width,
            temporary_measure=True
        )

    def clear_measurement_overlays(self) -> int:
        """
        Remove all temporary measurement overlays from the Lines layer.

        Returns:
            int: Number of deleted overlays
        """
        layer = self._get_or_create_lines_layer()
        field_idx = layer.fields().indexFromName("temporary_measure")
        if field_idx == -1:
            return 0

        ids_to_delete = [
            feature.id()
            for feature in layer.getFeatures(QgsFeatureRequest())
            if bool(feature.attribute(field_idx))
        ]

        if not ids_to_delete:
            return 0

        # CRITICAL: Check for nested transactions
        if layer.isEditable():
            raise LayerLockError(layer.name())

        # CRITICAL FIX (BUG-027): Check startEditing and deleteFeatures return values
        if not layer.startEditing():
            raise LayerTransactionError(
                self.LINES_LAYER_NAME,
                "start editing for delete",
                details="Layer may be locked or read-only"
            )
        try:
            if not layer.deleteFeatures(ids_to_delete):
                raise RuntimeError("deleteFeatures returned False - features may not have been deleted")
            self._safe_commit(layer, "clear_overlays", "LINES", {"deleted": len(ids_to_delete)})
        except Exception as exc:
            layer.rollBack()
            raise LayerTransactionError(
                self.LINES_LAYER_NAME,
                "delete measurement overlays",
                details=str(exc)
            ) from exc
        finally:
            if layer.isEditable():
                layer.rollBack()

        layer.triggerRepaint()
        return len(ids_to_delete)

    def count_measurement_overlays(self) -> int:
        """Return quantity of temporary measurement overlays."""
        layer = self._get_or_create_lines_layer()
        field_idx = layer.fields().indexFromName("temporary_measure")
        if field_idx == -1:
            return 0
        return sum(
            1
            for feature in layer.getFeatures(QgsFeatureRequest())
            if bool(feature.attribute(field_idx))
        )

    # -------------------------------------------------------------------------
    # Lines - Full CRUD (Phase 2)
    # -------------------------------------------------------------------------

    def list_lines(self, filters: Optional[Dict] = None) -> List[Dict]:
        """List all line features."""
        records: List[Dict[str, Any]] = []

        layer = self._get_or_create_lines_layer()
        if layer and layer.isValid():
            request = self._build_filter_request(layer, filters)
            try:
                for feature in layer.getFeatures(request):
                    rec = self._feature_to_record(feature, layer)
                    if rec:
                        records.append(rec)
            except Exception as exc:
                logger.error("Error listing lines: %s", exc, exc_info=True)

        if self._uses_per_item_layers("line"):
            records.extend(self._list_per_item_records(ItemType.LINE))

        return self._sort_records_by_display_order(records)

    def get_line(self, feature_id: Union[int, str]) -> Optional[Dict]:
        """Get a single line by feature id."""
        if isinstance(feature_id, str) and self._uses_per_item_layers("line") and self._is_uuid(feature_id):
            layer = self._get_per_item_layer(ItemType.LINE, feature_id)
            if not layer:
                return None
            feature = self._get_single_feature(layer)
            if not feature or not feature.isValid():
                return None
            return self._feature_to_record(feature, layer)

        if not isinstance(feature_id, int):
            try:
                feature_id = int(feature_id)
            except (TypeError, ValueError):
                return None

        layer = self._get_or_create_lines_layer()
        if not layer or not layer.isValid():
            return None
        feature = layer.getFeature(feature_id)
        if not feature.isValid():
            return None
        return self._feature_to_record(feature, layer)

    def update_line(self, feature_id: Union[int, str], updates: Dict[str, Any], updated_by: Optional[str] = None) -> bool:
        """Update attributes of a line feature."""
        if isinstance(feature_id, str) and self._uses_per_item_layers("line") and self._is_uuid(feature_id):
            return self._update_line_per_item(feature_id, updates, updated_by)

        if not isinstance(feature_id, int):
            try:
                feature_id = int(feature_id)
            except (TypeError, ValueError):
                raise ValueError(f"Invalid feature_id: {feature_id}")

        if feature_id <= 0:
            raise ValueError(f"Invalid feature_id: {feature_id}")
        if not isinstance(updates, dict) or not updates:
            raise ValueError("updates must be a non-empty dictionary")

        layer = self._get_or_create_lines_layer()
        if not layer or not layer.isValid():
            raise RuntimeError("Lines layer not available")

        if layer.isEditable():
            raise LayerLockError(layer.name())

        if not layer.startEditing():
            raise LayerTransactionError(layer_name=layer.name(), operation="start editing", details="startEditing() returned False")

        try:
            feature = layer.getFeature(feature_id)
            if not feature.isValid():
                raise ValueError(f"Feature {feature_id} not found")

            field_names = [field.name() for field in layer.fields()]
            for field_name in updates.keys():
                if field_name not in field_names:
                    raise ValueError(f"Invalid field: {field_name}. Valid fields: {field_names}")

            if 'color' in updates:
                validate_color_hex(updates['color'], "color")
            if 'width' in updates:
                validate_width(updates['width'], "width")

            # Apply updates
            for field_name, value in updates.items():
                field_index = layer.fields().indexFromName(field_name)
                if field_index == -1:
                    continue
                if not layer.changeAttributeValue(feature_id, field_index, value):
                    raise RuntimeError(f"Failed to update {field_name}")

            self._safe_commit(layer, "update", "LINES", {"feature_id": feature_id})

            layer.triggerRepaint()
            return True

        except Exception as exc:
            layer.rollBack()
            if isinstance(exc, LayerTransactionError):
                raise
            raise LayerTransactionError(
                layer_name=layer.name(),
                operation="update feature",
                details=str(exc)
            ) from exc
        finally:
            if layer.isEditable():
                try:
                    layer.rollBack()
                except RuntimeError:
                    pass

    def _update_line_per_item(
        self,
        item_id: str,
        updates: Dict[str, Any],
        updated_by: Optional[str] = None
    ) -> bool:
        """Update attributes of a per-item line."""
        if not isinstance(updates, dict) or not updates:
            raise ValueError("updates must be a non-empty dictionary")

        layer = self._get_per_item_layer(ItemType.LINE, item_id)
        if not layer or not layer.isValid():
            raise ValueError(f"Per-item line '{item_id}' not found")

        if layer.isEditable():
            raise LayerLockError(layer.name())

        if not layer.startEditing():
            raise LayerTransactionError(layer_name=layer.name(), operation="start editing", details="startEditing() returned False")

        try:
            feature = self._get_single_feature(layer)
            if not feature or not feature.isValid():
                raise ValueError(f"Per-item line '{item_id}' has no feature")

            field_names = [field.name() for field in layer.fields()]
            for field_name in updates.keys():
                if field_name not in field_names:
                    raise ValueError(f"Invalid field: {field_name}. Valid fields: {field_names}")

            if 'color' in updates:
                validate_color_hex(updates['color'], "color")
            if 'width' in updates:
                validate_width(updates['width'], "width")

            for field_name, value in updates.items():
                field_index = layer.fields().indexFromName(field_name)
                if field_index == -1:
                    continue
                if not layer.changeAttributeValue(feature.id(), field_index, value):
                    raise RuntimeError(f"Failed to update {field_name}")

            self._safe_commit(layer, "update", "LINES", {"item_id": item_id, "feature_id": feature.id()})

            if "name" in updates and updates["name"]:
                factory = self._get_per_item_factory()
                if factory:
                    factory.rename_item_layer(item_id, str(updates["name"]))

            layer.triggerRepaint()
            return True

        except Exception as exc:
            layer.rollBack()
            if isinstance(exc, LayerTransactionError):
                raise
            raise LayerTransactionError(
                layer_name=layer.name(),
                operation="update feature",
                details=str(exc)
            ) from exc
        finally:
            if layer.isEditable():
                try:
                    layer.rollBack()
                except RuntimeError:
                    pass

    def delete_line(self, feature_id: Union[int, str], updated_by: Optional[str] = None) -> bool:
        """Delete a single line feature."""
        if isinstance(feature_id, str) and self._uses_per_item_layers("line") and self._is_uuid(feature_id):
            return self._delete_line_per_item(feature_id, updated_by)

        if not isinstance(feature_id, int):
            try:
                feature_id = int(feature_id)
            except (TypeError, ValueError):
                raise ValueError(f"Invalid feature_id: {feature_id}")

        if feature_id <= 0:
            raise ValueError(f"Invalid feature_id: {feature_id}")

        layer = self._get_or_create_lines_layer()
        if not layer or not layer.isValid():
            raise RuntimeError("Lines layer not available")

        if layer.isEditable():
            raise LayerLockError(layer.name())

        if not layer.startEditing():
            raise LayerTransactionError(layer_name=layer.name(), operation="start editing", details="delete operation")

        try:
            if not layer.deleteFeature(feature_id):
                raise RuntimeError(f"Failed to delete feature {feature_id}")
            self._safe_commit(layer, "delete", "LINES", {"feature_id": feature_id})

            layer.triggerRepaint()
            return True
        except Exception as exc:
            layer.rollBack()
            raise LayerTransactionError(
                layer_name=layer.name(),
                operation="delete feature",
                details=str(exc)
            ) from exc
        finally:
            if layer.isEditable():
                try:
                    layer.rollBack()
                except RuntimeError:
                    pass

    def _delete_line_per_item(self, item_id: str, updated_by: Optional[str] = None) -> bool:
        """Delete a per-item line layer."""
        factory = self._get_per_item_factory()
        if not factory:
            raise RuntimeError("Per-item factory unavailable for line deletion")

        layer = self._get_per_item_layer(ItemType.LINE, item_id)
        if not layer or not layer.isValid():
            raise ValueError(f"Per-item line '{item_id}' not found")

        success = factory.delete_item_layer(
            item_id=item_id,
            remove_table=False,
            hard_delete=False
        )
        if not success:
            raise RuntimeError(f"Failed to delete per-item line '{item_id}'")

        return True

    def delete_lines(self, feature_ids: List[int], updated_by: Optional[str] = None) -> int:
        """Bulk delete lines."""
        if not feature_ids:
            return 0

        if len(feature_ids) > self.MAX_SYNC_FEATURES:
            logger.warning("Deleting %s line features synchronously; consider background task", len(feature_ids))

        layer = self._get_or_create_lines_layer()
        if not layer or not layer.isValid():
            raise RuntimeError("Lines layer not available")

        if layer.isEditable():
            raise LayerLockError(layer.name())

        if not layer.startEditing():
            raise LayerTransactionError(layer_name=layer.name(), operation="start editing", details="bulk delete operation")

        try:
            deleted = 0
            for fid in feature_ids:
                if layer.deleteFeature(fid):
                    deleted += 1

            self._safe_commit(layer, "bulk_delete", "LINES", {"deleted": deleted})

            layer.triggerRepaint()
            return deleted
        except Exception as exc:
            layer.rollBack()
            raise LayerTransactionError(
                layer_name=layer.name(),
                operation="bulk delete features",
                details=str(exc)
            ) from exc
        finally:
            if layer.isEditable():
                try:
                    layer.rollBack()
                except RuntimeError:
                    pass

    def _ensure_lines_layer_schema(self, layer: QgsVectorLayer):
        """Ensure legacy lines layers include measurement overlay field."""
        layer = self._require_valid_layer(layer, self.LINES_LAYER_NAME)
        if layer.fields().indexFromName("temporary_measure") != -1:
            return

        layer.startEditing()
        try:
            if not layer.addAttribute(QgsField("temporary_measure", QVariant.Bool)):
                raise RuntimeError("Failed to add temporary_measure field")
            self._safe_commit(layer, "schema_update", "LINES", {"field": "temporary_measure"})
        except Exception as exc:
            layer.rollBack()
            logger.warning(
                "Could not update Lines layer schema for measurement overlays: %s",
                exc
            )
        finally:
            if layer.isEditable():
                layer.rollBack()

    # =========================================================================
    # Search Areas Layer
    # =========================================================================

    def _get_or_create_search_areas_layer(self) -> QgsVectorLayer:
        """
        Get or create Search Areas layer with status tracking.

        Returns:
            QgsVectorLayer: Search Areas layer
        """
        if self.layer_manager:
            layer = self._ensure_schema_layer(
                LayerIds.SEARCH_AREAS,
                fallback_name=self.SEARCH_AREAS_LAYER_NAME,
                style_factory=self._style_search_areas_layer
            )
            layer = self._require_valid_layer(layer, self.SEARCH_AREAS_LAYER_NAME)
            self._log_drawing_event(layer, "SEARCH_AREAS", "ensure")
            return layer

        layers = self.project.mapLayersByName(self.SEARCH_AREAS_LAYER_NAME)
        if layers:
            layer = layers[0]
            layer = self._require_valid_layer(layer, self.SEARCH_AREAS_LAYER_NAME)
            self._log_drawing_event(layer, "SEARCH_AREAS", "reused")
            return layer

        # Create memory layer with WGS84 CRS
        # Qt5/Qt6 Compatible: Using integer type codes
        layer = QgsVectorLayer(
            "Polygon?crs=EPSG:4326",
            self.SEARCH_AREAS_LAYER_NAME,
            "memory"
        )

        # Add fields with SAR-specific attributes
        layer.dataProvider().addAttributes([
            QgsField("id", QVariant.String),              # String - unique ID
            QgsField("name", QVariant.String),            # String - area name
            QgsField("team", QVariant.String),            # String - assigned team
            QgsField("status", QVariant.String),          # String - Planned/Assigned/InProgress/Completed/Cleared
            QgsField("priority", QVariant.String),        # String - High/Medium/Low
            QgsField("area_sqkm", QVariant.Double),       # Double - area in square km
            QgsField("POA", QVariant.Double),             # Double - Probability of Area (0-100)
            QgsField("POD", QVariant.Double),             # Double - Probability of Detection (0-100)
            QgsField("terrain", QVariant.String),         # String - terrain type
            QgsField("search_method", QVariant.String),   # String - search method
            QgsField("color", QVariant.String),           # String - hex color
            QgsField("start_time", QVariant.String),      # String - ISO timestamp
            QgsField("end_time", QVariant.String),        # String - ISO timestamp
            QgsField("notes", QVariant.String),           # String - additional notes
            QgsField("created", QVariant.String),         # String - ISO timestamp
            QgsField("display_order", QVariant.Int),      # Int - display order for UI (Phase 2)
        ])
        layer.updateFields()

        # Basic styling with semi-transparent fill
        symbol = layer.renderer().symbol()
        symbol.setColor(QColor(0, 100, 255, 80))  # Blue with transparency
        symbol.symbolLayer(0).setStrokeColor(QColor(0, 100, 255))
        symbol.symbolLayer(0).setStrokeWidth(2)

        # Add to project in layer group
        self._add_layer_to_group(layer, position=0)

        self._log_drawing_event(layer, "SEARCH_AREAS", "created")
        return self._require_valid_layer(layer, self.SEARCH_AREAS_LAYER_NAME)

    def add_search_area(self, name: str, polygon_wgs84: List[QgsPointXY],
                        team: str = "Unassigned", status: str = "Planned",
                        priority: str = "Medium", POA: float = 50.0,
                        terrain: str = "", search_method: str = "",
                        color: str = "#0064FF", notes: str = "") -> Union[int, str]:
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
            int: Feature ID of added search area (or item_id as string for per-item layers)
        """
        try:
            polygon_wgs84 = list(polygon_wgs84)
            validate_point_sequence(polygon_wgs84, min_points=3, name="polygon_wgs84")
            validate_color_hex(color, "color")
        except Exception as exc:
            self._notify_error("Add Search Area Failed", str(exc))
            raise

        # Phase 4: Check if we should use per-item layers
        if self._uses_per_item_layers("search_area"):
            return self._add_search_area_per_item(
                name=name, polygon_wgs84=polygon_wgs84,
                team=team, status=status, priority=priority, POA=POA,
                terrain=terrain, search_method=search_method,
                color=color, notes=notes
            )

        # Legacy path: shared layer
        return self._add_search_area_shared_layer(
            name=name, polygon_wgs84=polygon_wgs84,
            team=team, status=status, priority=priority, POA=POA,
            terrain=terrain, search_method=search_method,
            color=color, notes=notes
        )

    def _add_search_area_shared_layer(
        self, name: str, polygon_wgs84: List[QgsPointXY],
        team: str, status: str, priority: str, POA: float,
        terrain: str, search_method: str, color: str, notes: str
    ) -> int:
        """Legacy implementation: Add search area to shared layer."""
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

        logger.debug(f"Search area '{name}': {len(polygon_wgs84)} points, area={area_sqkm:.4f}km²")

        # Create feature
        feature = QgsFeature(layer.fields())
        feature.setGeometry(polygon_geom)

        attr_map = {
            "id": str(uuid.uuid4()),
            "name": name,
            "team": team,
            "status": status,
            "priority": priority,
            "area_sqkm": float(area_sqkm),
            "POA": float(POA),
            "POD": 0.0,  # to be calculated/updated later
            "terrain": terrain,
            "search_method": search_method,
            "color": color,
            "start_time": "",  # set when status changes to InProgress
            "end_time": "",  # set when status changes to Completed
            "notes": notes,
            "created": self._current_timestamp(),
            "display_order": None,  # set after addFeature
        }
        fields = layer.fields()
        for field_name, value in attr_map.items():
            idx = fields.indexFromName(field_name)
            if idx != -1:
                feature.setAttribute(idx, value)

        # Add to layer with proper resource cleanup
        # CRITICAL: Check for nested transactions
        if layer.isEditable():
            raise LayerLockError(layer.name())

        layer.startEditing()
        try:
            if not layer.addFeature(feature):
                layer.rollBack()
                raise RuntimeError(f"Failed to add feature to {self.SEARCH_AREAS_LAYER_NAME} layer")
            self._set_display_order(layer, feature.id())
            self._safe_commit(layer, "add", "SEARCH_AREAS", {})
        except Exception as e:
            layer.rollBack()
            # Raise typed exception for error handler (Issue #3)
            raise LayerTransactionError(
                self.SEARCH_AREAS_LAYER_NAME,
                "add feature",
                details=str(e)
            ) from e
        finally:
            # Ensure layer is not left in edit mode
            if layer.isEditable():
                layer.rollBack()

        layer.triggerRepaint()
        self._log_drawing_event(
            layer,
            "SEARCH_AREAS",
            "add",
            name=name,
            area_sqkm=area_sqkm,
            team=team,
            status=status
        )
        return feature.id()

    def _add_search_area_per_item(
        self, name: str, polygon_wgs84: List[QgsPointXY],
        team: str, status: str, priority: str, POA: float,
        terrain: str, search_method: str, color: str, notes: str
    ) -> str:
        """
        Phase 4: Add search area as a per-item layer.

        Creates an individual GeoPackage-backed layer for this search area,
        placed under "SAR Tracker / Map Tools / Search Areas /".

        Returns:
            str: item_id (which serves as the feature identifier)
        """
        factory = self._get_per_item_factory()
        if not factory:
            # Fallback to shared layer if no mission store configured
            logger.warning("Phase 4: No factory available, falling back to shared layer for search area")
            return self._add_search_area_shared_layer(
                name=name, polygon_wgs84=polygon_wgs84,
                team=team, status=status, priority=priority, POA=POA,
                terrain=terrain, search_method=search_method,
                color=color, notes=notes
            )

        # Ensure the target group exists
        target_group = self._ensure_per_item_group(ItemType.SEARCH_AREA)

        # Define fields for the search area layer (matching schema)
        search_area_fields = [
            {"name": "id", "type": "String", "length": 50},
            {"name": "name", "type": "String", "length": 255},
            {"name": "team", "type": "String", "length": 255},
            {"name": "status", "type": "String", "length": 50},
            {"name": "priority", "type": "String", "length": 50},
            {"name": "area_sqkm", "type": "Double"},
            {"name": "POA", "type": "Double"},
            {"name": "POD", "type": "Double"},
            {"name": "terrain", "type": "String", "length": 255},
            {"name": "search_method", "type": "String", "length": 255},
            {"name": "color", "type": "String", "length": 20},
            {"name": "start_time", "type": "String", "length": 50},
            {"name": "end_time", "type": "String", "length": 50},
            {"name": "notes", "type": "String", "length": 1000},
            {"name": "created", "type": "String", "length": 50},
            {"name": "display_order", "type": "Int"},
        ]

        # Create the per-item layer
        try:
            item_info = factory.create_item_layer(
                item_type=ItemType.SEARCH_AREA,
                display_name=name,
                fields=search_area_fields,
                add_to_project=True,
                target_group=target_group
            )
        except Exception as e:
            logger.error("Phase 4: Failed to create per-item layer for search area '%s': %s", name, e)
            raise RuntimeError(f"Failed to create per-item search area layer: {e}") from e

        layer = item_info.layer
        item_id = item_info.item_id

        if not layer or not layer.isValid():
            raise RuntimeError(f"Per-item layer created but invalid for search area '{name}'")

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

        logger.debug(f"Search area '{name}' (per-item): {len(polygon_wgs84)} points, area={area_sqkm:.4f}km²")

        # Create and add the feature to the layer
        feature = QgsFeature(layer.fields())
        feature.setGeometry(polygon_geom)

        created_ts = datetime.now(timezone.utc).isoformat()
        attr_map = {
            "id": item_id,  # Use item_id as the marker id
            "name": name,
            "team": team,
            "status": status,
            "priority": priority,
            "area_sqkm": float(area_sqkm),
            "POA": float(POA),
            "POD": 0.0,
            "terrain": terrain,
            "search_method": search_method,
            "color": color,
            "start_time": "",
            "end_time": "",
            "notes": notes,
            "created": created_ts,
        }

        fields = layer.fields()
        for field_name, value in attr_map.items():
            idx = fields.indexFromName(field_name)
            if idx != -1:
                feature.setAttribute(idx, value)

        # Add feature to layer
        if layer.isEditable():
            raise LayerLockError(layer.name())

        layer.startEditing()
        try:
            if not layer.addFeature(feature):
                layer.rollBack()
                raise RuntimeError(f"Failed to add feature to per-item search area layer '{name}'")
            self._set_display_order(layer, feature.id())
            self._safe_commit(layer, "add", "SEARCH_AREAS", {})
        except Exception as e:
            layer.rollBack()
            self._cleanup_failed_per_item_layer(factory, item_id, "search area")
            raise LayerTransactionError(
                name,
                "add feature",
                details=str(e)
            ) from e
        finally:
            if layer.isEditable():
                layer.rollBack()

        # Apply styling
        self._style_search_areas_layer(layer)

        layer.triggerRepaint()
        logger.info(
            "Phase 4: Created per-item search area layer '%s' (item_id=%s) under Map Tools/Search Areas",
            name, item_id
        )
        return item_id

    # =========================================================================
    # Range Rings Layer
    # =========================================================================

    def _get_or_create_range_rings_layer(self) -> QgsVectorLayer:
        """
        Get or create Range Rings layer for distance circles.

        Returns:
            QgsVectorLayer: Range Rings layer
        """
        if self.layer_manager:
            layer = self._ensure_schema_layer(
                LayerIds.RANGE_RINGS,
                fallback_name=self.RANGE_RINGS_LAYER_NAME,
                style_factory=self._style_range_rings_layer
            )
            layer = self._require_valid_layer(layer, self.RANGE_RINGS_LAYER_NAME)
            self._log_drawing_event(layer, "RANGE_RINGS", "ensure")
            return layer

        layers = self.project.mapLayersByName(self.RANGE_RINGS_LAYER_NAME)
        if layers:
            layer = layers[0]
            layer = self._require_valid_layer(layer, self.RANGE_RINGS_LAYER_NAME)
            self._log_drawing_event(layer, "RANGE_RINGS", "reused")
            return layer

        # Create memory layer with WGS84 CRS
        # Qt5/Qt6 Compatible: Using integer type codes
        layer = QgsVectorLayer(
            "Polygon?crs=EPSG:4326",
            self.RANGE_RINGS_LAYER_NAME,
            "memory"
        )

        # Add fields
        layer.dataProvider().addAttributes([
            QgsField("id", QVariant.String),              # String - unique ID
            QgsField("name", QVariant.String),            # String - ring name
            QgsField("center_lat", QVariant.Double),      # Double - center latitude
            QgsField("center_lon", QVariant.Double),      # Double - center longitude
            QgsField("radius_m", QVariant.Double),        # Double - radius in meters
            QgsField("label", QVariant.String),           # String - display label
            QgsField("color", QVariant.String),           # String - hex color
            QgsField("lpb_category", QVariant.String),    # String - LPB category if applicable
            QgsField("percentile", QVariant.Int),         # Int - LPB percentile (25, 50, 75, 95)
            QgsField("created", QVariant.String),         # String - ISO timestamp
            QgsField("display_order", QVariant.Int),      # Int - display order for UI (Phase 2)
        ])
        layer.updateFields()

        # Basic styling with transparent fill
        symbol = layer.renderer().symbol()
        symbol.setColor(QColor(255, 165, 0, 40))  # Orange with high transparency
        symbol.symbolLayer(0).setStrokeColor(QColor(255, 165, 0))
        symbol.symbolLayer(0).setStrokeWidth(1.5)

        # Add to project in layer group
        self._add_layer_to_group(layer, position=0)

        self._log_drawing_event(layer, "RANGE_RINGS", "created")
        return self._require_valid_layer(layer, self.RANGE_RINGS_LAYER_NAME)

    def add_range_ring(self, name: str, center_wgs84: QgsPointXY, radius_m: float,
                       label: str = "", color: str = "#FFA500",
                       lpb_category: str = "", percentile: int = 0) -> Union[int, str]:
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
        try:
            validate_point(center_wgs84, "center_wgs84")
            validate_positive_number(radius_m, "radius_m")
            validate_color_hex(color, "color")
        except Exception as exc:
            self._notify_error("Add Range Ring Failed", str(exc))
            raise

        # Phase 4: Check if we should use per-item layers
        if self._uses_per_item_layers("range_ring"):
            return self._add_range_ring_per_item(
                name=name, center_wgs84=center_wgs84, radius_m=radius_m,
                label=label, color=color, lpb_category=lpb_category, percentile=percentile
            )

        # Legacy path: shared layer
        return self._add_range_ring_shared_layer(
            name=name, center_wgs84=center_wgs84, radius_m=radius_m,
            label=label, color=color, lpb_category=lpb_category, percentile=percentile
        )

    def _add_range_ring_shared_layer(
        self, name: str, center_wgs84: QgsPointXY, radius_m: float,
        label: str, color: str, lpb_category: str, percentile: int
    ) -> int:
        """Legacy implementation: Add range ring to shared layer."""
        layer = self._get_or_create_range_rings_layer()

        circle_points = geodesic_circle_points(center_wgs84.x(), center_wgs84.y(), radius_m, segments=64)
        points = [QgsPointXY(lon, lat) for lon, lat in circle_points]

        # Create polygon geometry from points
        circle_geom = QgsGeometry.fromPolygonXY([points])

        # Create feature
        feature = QgsFeature(layer.fields())
        feature.setGeometry(circle_geom)

        attr_map = {
            "id": str(uuid.uuid4()),
            "name": name,
            "center_lat": float(center_wgs84.y()),
            "center_lon": float(center_wgs84.x()),
            "radius_m": float(radius_m),
            "label": label,
            "color": color,
            "lpb_category": lpb_category,
            "percentile": int(percentile) if percentile is not None else None,
            "created": self._current_timestamp(),
            "display_order": None,  # set after addFeature
        }
        fields = layer.fields()
        for field_name, value in attr_map.items():
            idx = fields.indexFromName(field_name)
            if idx != -1:
                feature.setAttribute(idx, value)

        # Add to layer with proper resource cleanup
        # CRITICAL: Check for nested transactions
        if layer.isEditable():
            raise LayerLockError(layer.name())

        layer.startEditing()
        try:
            if not layer.addFeature(feature):
                layer.rollBack()
                raise RuntimeError(f"Failed to add feature to {self.RANGE_RINGS_LAYER_NAME} layer")
            self._set_display_order(layer, feature.id())
            self._safe_commit(layer, "add", "RANGE_RINGS", {})
        except Exception as e:
            layer.rollBack()
            # Raise typed exception for error handler (Issue #3)
            raise LayerTransactionError(
                self.RANGE_RINGS_LAYER_NAME,
                "add feature",
                details=str(e)
            ) from e
        finally:
            # Ensure layer is not left in edit mode
            if layer.isEditable():
                layer.rollBack()

        layer.triggerRepaint()
        self._log_drawing_event(
            layer,
            "RANGE_RINGS",
            "add",
            name=name,
            radius_m=radius_m,
            lpb_category=lpb_category,
            percentile=percentile
        )
        return feature.id()

    def _add_range_ring_per_item(
        self, name: str, center_wgs84: QgsPointXY, radius_m: float,
        label: str, color: str, lpb_category: str, percentile: int
    ) -> str:
        """
        Phase 4: Add range ring as a per-item layer.

        Creates an individual GeoPackage-backed layer for this range ring,
        placed under "SAR Tracker / Map Tools / Range Rings /".

        Returns:
            str: item_id (which serves as the feature identifier)
        """
        factory = self._get_per_item_factory()
        if not factory:
            # Fallback to shared layer if no mission store configured
            logger.warning("Phase 4: No factory available, falling back to shared layer for range ring")
            return self._add_range_ring_shared_layer(
                name=name, center_wgs84=center_wgs84, radius_m=radius_m,
                label=label, color=color, lpb_category=lpb_category, percentile=percentile
            )

        # Ensure the target group exists
        target_group = self._ensure_per_item_group(ItemType.RANGE_RING)

        # Define fields for the range ring layer (matching schema)
        range_ring_fields = [
            {"name": "id", "type": "String", "length": 50},
            {"name": "name", "type": "String", "length": 255},
            {"name": "center_lat", "type": "Double"},
            {"name": "center_lon", "type": "Double"},
            {"name": "radius_m", "type": "Double"},
            {"name": "label", "type": "String", "length": 100},
            {"name": "color", "type": "String", "length": 20},
            {"name": "lpb_category", "type": "String", "length": 100},
            {"name": "percentile", "type": "Int"},
            {"name": "created", "type": "String", "length": 50},
            {"name": "display_order", "type": "Int"},
        ]

        # Create the per-item layer
        try:
            item_info = factory.create_item_layer(
                item_type=ItemType.RANGE_RING,
                display_name=name,
                fields=range_ring_fields,
                add_to_project=True,
                target_group=target_group
            )
        except Exception as e:
            logger.error("Phase 4: Failed to create per-item layer for range ring '%s': %s", name, e)
            raise RuntimeError(f"Failed to create per-item range ring layer: {e}") from e

        layer = item_info.layer
        item_id = item_info.item_id

        if not layer or not layer.isValid():
            raise RuntimeError(f"Per-item layer created but invalid for range ring '{name}'")

        # Calculate geodesic circle points
        circle_points = geodesic_circle_points(center_wgs84.x(), center_wgs84.y(), radius_m, segments=64)
        points = [QgsPointXY(lon, lat) for lon, lat in circle_points]

        # Create polygon geometry from points
        circle_geom = QgsGeometry.fromPolygonXY([points])

        # Create and add the feature to the layer
        feature = QgsFeature(layer.fields())
        feature.setGeometry(circle_geom)

        created_ts = datetime.now(timezone.utc).isoformat()
        attr_map = {
            "id": item_id,  # Use item_id as the feature id
            "name": name,
            "center_lat": float(center_wgs84.y()),
            "center_lon": float(center_wgs84.x()),
            "radius_m": float(radius_m),
            "label": label,
            "color": color,
            "lpb_category": lpb_category,
            "percentile": int(percentile) if percentile is not None else None,
            "created": created_ts,
        }

        fields = layer.fields()
        for field_name, value in attr_map.items():
            idx = fields.indexFromName(field_name)
            if idx != -1:
                feature.setAttribute(idx, value)

        # Add feature to layer
        if layer.isEditable():
            raise LayerLockError(layer.name())

        layer.startEditing()
        try:
            if not layer.addFeature(feature):
                layer.rollBack()
                raise RuntimeError(f"Failed to add feature to per-item range ring layer '{name}'")
            self._set_display_order(layer, feature.id())
            self._safe_commit(layer, "add", "RANGE_RINGS", {})
        except Exception as e:
            layer.rollBack()
            self._cleanup_failed_per_item_layer(factory, item_id, "range ring")
            raise LayerTransactionError(
                name,
                "add feature",
                details=str(e)
            ) from e
        finally:
            if layer.isEditable():
                layer.rollBack()

        # Apply styling
        self._style_range_rings_layer(layer)

        layer.triggerRepaint()
        logger.info(
            "Phase 4: Created per-item range ring layer '%s' (item_id=%s) under Map Tools/Range Rings",
            name, item_id
        )
        return item_id

    # =========================================================================
    # Bearing Lines Layer
    # =========================================================================

    def _get_or_create_bearing_lines_layer(self) -> QgsVectorLayer:
        """
        Get or create Bearing Lines layer for direction-finding.

        Returns:
            QgsVectorLayer: Bearing Lines layer
        """
        if self.layer_manager:
            layer = self._ensure_schema_layer(
                LayerIds.BEARING_LINES,
                fallback_name=self.BEARING_LINES_LAYER_NAME,
                style_factory=self._style_bearing_lines_layer
            )
            layer = self._require_valid_layer(layer, self.BEARING_LINES_LAYER_NAME)
            self._log_drawing_event(layer, "BEARING_LINES", "ensure")
            return layer

        layers = self.project.mapLayersByName(self.BEARING_LINES_LAYER_NAME)
        if layers:
            layer = layers[0]
            layer = self._require_valid_layer(layer, self.BEARING_LINES_LAYER_NAME)
            self._log_drawing_event(layer, "BEARING_LINES", "reused")
            return layer

        # Create memory layer with WGS84 CRS
        # Qt5/Qt6 Compatible: Using integer type codes
        layer = QgsVectorLayer(
            "LineString?crs=EPSG:4326",
            self.BEARING_LINES_LAYER_NAME,
            "memory"
        )

        # Add fields
        layer.dataProvider().addAttributes([
            QgsField("id", QVariant.String),              # String - unique ID
            QgsField("name", QVariant.String),            # String - line name
            QgsField("origin_lat", QVariant.Double),      # Double - origin latitude
            QgsField("origin_lon", QVariant.Double),      # Double - origin longitude
            QgsField("bearing", QVariant.Double),         # Double - bearing in degrees (0-360)
            QgsField("distance_m", QVariant.Double),      # Double - line length in meters
            QgsField("label", QVariant.String),           # String - display label
            QgsField("color", QVariant.String),           # String - hex color
            QgsField("created", QVariant.String),         # String - ISO timestamp
            QgsField("display_order", QVariant.Int),      # Int - display order for UI (Phase 2)
        ])
        layer.updateFields()

        # Basic styling
        symbol = QgsLineSymbol.createSimple({'color': 'purple', 'width': '2'})
        layer.renderer().setSymbol(symbol)

        # Add to project in layer group
        self._add_layer_to_group(layer, position=0)

        self._log_drawing_event(layer, "BEARING_LINES", "created")
        return self._require_valid_layer(layer, self.BEARING_LINES_LAYER_NAME)

    def add_bearing_line(self, name: str, origin_wgs84: QgsPointXY,
                         bearing: float, distance_m: float,
                         label: str = "", color: str = "#800080") -> Union[int, str]:
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
        try:
            validate_point(origin_wgs84, "origin_wgs84")
            validate_bearing(bearing)
            validate_positive_number(distance_m, "distance_m")
            validate_color_hex(color, "color")
        except Exception as exc:
            self._notify_error("Add Bearing Line Failed", str(exc))
            raise

        # Phase 4: Check if we should use per-item layers
        if self._uses_per_item_layers("bearing_line"):
            return self._add_bearing_line_per_item(
                name=name, origin_wgs84=origin_wgs84, bearing=bearing,
                distance_m=distance_m, label=label, color=color
            )

        # Legacy path: shared layer
        return self._add_bearing_line_shared_layer(
            name=name, origin_wgs84=origin_wgs84, bearing=bearing,
            distance_m=distance_m, label=label, color=color
        )

    def _add_bearing_line_shared_layer(
        self, name: str, origin_wgs84: QgsPointXY, bearing: float,
        distance_m: float, label: str, color: str
    ) -> int:
        """Legacy implementation: Add bearing line to shared layer."""
        layer = self._get_or_create_bearing_lines_layer()

        # Calculate endpoint using bearing and distance
        # CRITICAL: This code was carefully tuned for <1m accuracy
        # Bug fix from Day 7 audit - DO NOT MODIFY

        endpoint_lon, endpoint_lat = geodesic_bearing_endpoint(
            origin_wgs84.x(),
            origin_wgs84.y(),
            bearing,
            distance_m
        )
        endpoint = QgsPointXY(endpoint_lon, endpoint_lat)

        # Create line geometry
        line_geom = QgsGeometry.fromPolylineXY([origin_wgs84, endpoint])

        # Create feature
        feature = QgsFeature(layer.fields())
        feature.setGeometry(line_geom)

        attr_map = {
            "id": str(uuid.uuid4()),
            "name": name,
            "origin_lat": float(origin_wgs84.y()),
            "origin_lon": float(origin_wgs84.x()),
            "bearing": float(bearing),
            "distance_m": float(distance_m),
            "label": label,
            "color": color,
            "created": self._current_timestamp(),
            "display_order": None,  # set after addFeature
        }
        fields = layer.fields()
        for field_name, value in attr_map.items():
            idx = fields.indexFromName(field_name)
            if idx != -1:
                feature.setAttribute(idx, value)

        # Add to layer with proper resource cleanup
        # CRITICAL: Check for nested transactions
        if layer.isEditable():
            raise LayerLockError(layer.name())

        layer.startEditing()
        try:
            if not layer.addFeature(feature):
                layer.rollBack()
                raise RuntimeError(f"Failed to add feature to {self.BEARING_LINES_LAYER_NAME} layer")
            self._set_display_order(layer, feature.id())
            self._safe_commit(layer, "add", "BEARING_LINES", {})
        except Exception as e:
            layer.rollBack()
            # Raise typed exception for error handler (Issue #3)
            raise LayerTransactionError(
                self.BEARING_LINES_LAYER_NAME,
                "add feature",
                details=str(e)
            ) from e
        finally:
            # Ensure layer is not left in edit mode
            if layer.isEditable():
                layer.rollBack()

        layer.triggerRepaint()
        self._log_drawing_event(
            layer,
            "BEARING_LINES",
            "add",
            name=name,
            bearing=bearing,
            distance_m=distance_m
        )
        return feature.id()

    def _add_bearing_line_per_item(
        self, name: str, origin_wgs84: QgsPointXY, bearing: float,
        distance_m: float, label: str, color: str
    ) -> str:
        """
        Phase 4: Add bearing line as a per-item layer.

        Creates an individual GeoPackage-backed layer for this bearing line,
        placed under "SAR Tracker / Map Tools / Bearing Lines /".

        CRITICAL: Uses WGS84 ellipsoid geodesic calculations for accuracy.
        DO NOT MODIFY the geodesic math without thorough testing.

        Returns:
            str: item_id (which serves as the feature identifier)
        """
        factory = self._get_per_item_factory()
        if not factory:
            # Fallback to shared layer if no mission store configured
            logger.warning("Phase 4: No factory available, falling back to shared layer for bearing line")
            return self._add_bearing_line_shared_layer(
                name=name, origin_wgs84=origin_wgs84, bearing=bearing,
                distance_m=distance_m, label=label, color=color
            )

        # Ensure the target group exists
        target_group = self._ensure_per_item_group(ItemType.BEARING_LINE)

        # Define fields for the bearing line layer (matching schema)
        bearing_line_fields = [
            {"name": "id", "type": "String", "length": 50},
            {"name": "name", "type": "String", "length": 255},
            {"name": "origin_lat", "type": "Double"},
            {"name": "origin_lon", "type": "Double"},
            {"name": "bearing", "type": "Double"},
            {"name": "distance_m", "type": "Double"},
            {"name": "label", "type": "String", "length": 100},
            {"name": "color", "type": "String", "length": 20},
            {"name": "created", "type": "String", "length": 50},
            {"name": "display_order", "type": "Int"},
        ]

        # Create the per-item layer
        try:
            item_info = factory.create_item_layer(
                item_type=ItemType.BEARING_LINE,
                display_name=name,
                fields=bearing_line_fields,
                add_to_project=True,
                target_group=target_group
            )
        except Exception as e:
            logger.error("Phase 4: Failed to create per-item layer for bearing line '%s': %s", name, e)
            raise RuntimeError(f"Failed to create per-item bearing line layer: {e}") from e

        layer = item_info.layer
        item_id = item_info.item_id

        if not layer or not layer.isValid():
            raise RuntimeError(f"Per-item layer created but invalid for bearing line '{name}'")

        # Calculate endpoint using bearing and distance
        # CRITICAL: This code was carefully tuned for <1m accuracy
        # Bug fix from Day 7 audit - DO NOT MODIFY

        endpoint_lon, endpoint_lat = geodesic_bearing_endpoint(
            origin_wgs84.x(),
            origin_wgs84.y(),
            bearing,
            distance_m
        )
        endpoint = QgsPointXY(endpoint_lon, endpoint_lat)

        # Create line geometry
        line_geom = QgsGeometry.fromPolylineXY([origin_wgs84, endpoint])

        # Create and add the feature to the layer
        feature = QgsFeature(layer.fields())
        feature.setGeometry(line_geom)

        created_ts = datetime.now(timezone.utc).isoformat()
        attr_map = {
            "id": item_id,  # Use item_id as the feature id
            "name": name,
            "origin_lat": float(origin_wgs84.y()),
            "origin_lon": float(origin_wgs84.x()),
            "bearing": float(bearing),
            "distance_m": float(distance_m),
            "label": label,
            "color": color,
            "created": created_ts,
        }

        fields = layer.fields()
        for field_name, value in attr_map.items():
            idx = fields.indexFromName(field_name)
            if idx != -1:
                feature.setAttribute(idx, value)

        # Add feature to layer
        if layer.isEditable():
            raise LayerLockError(layer.name())

        layer.startEditing()
        try:
            if not layer.addFeature(feature):
                layer.rollBack()
                raise RuntimeError(f"Failed to add feature to per-item bearing line layer '{name}'")
            self._set_display_order(layer, feature.id())
            self._safe_commit(layer, "add", "BEARING_LINES", {})
        except Exception as e:
            layer.rollBack()
            self._cleanup_failed_per_item_layer(factory, item_id, "bearing line")
            raise LayerTransactionError(
                name,
                "add feature",
                details=str(e)
            ) from e
        finally:
            if layer.isEditable():
                layer.rollBack()

        # Apply styling
        self._style_bearing_lines_layer(layer)

        layer.triggerRepaint()
        logger.info(
            "Phase 4: Created per-item bearing line layer '%s' (item_id=%s) under Map Tools/Bearing Lines",
            name, item_id
        )
        return item_id

    # =========================================================================
    # Search Sectors Layer
    # =========================================================================

    def _get_or_create_sectors_layer(self) -> QgsVectorLayer:
        """
        Get or create Search Sectors layer for wedge/pie-slice search areas.

        Returns:
            QgsVectorLayer: Sectors layer
        """
        if self.layer_manager:
            layer = self._ensure_schema_layer(
                LayerIds.SEARCH_SECTORS,
                fallback_name=self.SECTORS_LAYER_NAME,
                style_factory=self._style_sectors_layer
            )
            layer = self._require_valid_layer(layer, self.SECTORS_LAYER_NAME)
            self._log_drawing_event(layer, "SECTORS", "ensure")
            return layer

        layers = self.project.mapLayersByName(self.SECTORS_LAYER_NAME)
        if layers:
            layer = layers[0]
            layer = self._require_valid_layer(layer, self.SECTORS_LAYER_NAME)
            self._log_drawing_event(layer, "SECTORS", "reused")
            return layer

        # Create memory layer with WGS84 CRS
        # Qt5/Qt6 Compatible: Using integer type codes
        layer = QgsVectorLayer(
            "Polygon?crs=EPSG:4326",
            self.SECTORS_LAYER_NAME,
            "memory"
        )

        # Add fields
        layer.dataProvider().addAttributes([
            QgsField("id", QVariant.String),              # String - unique ID
            QgsField("name", QVariant.String),            # String - sector name
            QgsField("center_lat", QVariant.Double),      # Double - center latitude
            QgsField("center_lon", QVariant.Double),      # Double - center longitude
            QgsField("start_bearing", QVariant.Double),   # Double - start bearing (degrees)
            QgsField("end_bearing", QVariant.Double),     # Double - end bearing (degrees)
            QgsField("radius_m", QVariant.Double),        # Double - radius in meters
            QgsField("arc_length_deg", QVariant.Double),  # Double - arc length in degrees (BUG-034 fix)
            QgsField("area_sqkm", QVariant.Double),       # Double - area in square km
            QgsField("priority", QVariant.String),        # String - High/Medium/Low
            QgsField("color", QVariant.String),           # String - hex color
            QgsField("created", QVariant.String),         # String - ISO timestamp
            QgsField("display_order", QVariant.Int),      # Int - display order for UI (Phase 2)
        ])
        layer.updateFields()

        # Basic styling with semi-transparent fill
        symbol = layer.renderer().symbol()
        symbol.setColor(QColor(255, 100, 100, 60))  # Red with transparency
        symbol.symbolLayer(0).setStrokeColor(QColor(255, 100, 100))
        symbol.symbolLayer(0).setStrokeWidth(2)

        # Add to project in layer group
        self._add_layer_to_group(layer, position=0)

        self._log_drawing_event(layer, "SECTORS", "created")
        return self._require_valid_layer(layer, self.SECTORS_LAYER_NAME)

    def _assert_valid_sector_geometry(self, geometry: QgsGeometry, name: str):
        """Ensure generated sector polygon is valid before committing."""
        if not geometry or geometry.isEmpty():
            raise GeometryError(f"Sector '{name}' generated an empty geometry.", geometry_type="polygon")

        try:
            validation_results = geometry.validateGeometry() or []
        except Exception as exc:
            raise GeometryError(
                f"Sector '{name}' geometry validation failed: {exc}",
                geometry_type="polygon"
            ) from exc

        if validation_results:
            issues = []
            for result in validation_results:
                message = None
                if hasattr(result, "what") and callable(getattr(result, "what")):
                    try:
                        message = result.what()
                    except Exception:
                        message = None
                message = message or getattr(result, "description", None) or str(result)
                issues.append(message)
            raise GeometryError(
                f"Sector '{name}' geometry is invalid: {'; '.join(issues)}",
                geometry_type="polygon"
            )

    def add_sector(self, name: str, center_wgs84: QgsPointXY,
                   start_bearing: float, end_bearing: float, radius_m: float,
                   priority: str = "Medium", color: str = "#FF6464") -> Union[int, str]:
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
            int: Feature ID of added sector (shared layer)
            str: item_id for per-item layer
        """
        try:
            validate_point(center_wgs84, "center_wgs84")
            validate_bearing(start_bearing, "start_bearing")
            validate_bearing(end_bearing, "end_bearing")
            validate_positive_number(radius_m, "radius_m")
            validate_color_hex(color, "color")
        except Exception as exc:
            self._notify_error("Add Sector Failed", str(exc))
            raise

        # Phase 4: Check if we should use per-item layers
        if self._uses_per_item_layers("sector"):
            return self._add_sector_per_item(
                name=name,
                center_wgs84=center_wgs84,
                start_bearing=start_bearing,
                end_bearing=end_bearing,
                radius_m=radius_m,
                priority=priority,
                color=color
            )

        # Legacy path: shared layer
        return self._add_sector_shared_layer(
            name=name,
            center_wgs84=center_wgs84,
            start_bearing=start_bearing,
            end_bearing=end_bearing,
            radius_m=radius_m,
            priority=priority,
            color=color
        )

    def _add_sector_shared_layer(
        self,
        name: str,
        center_wgs84: QgsPointXY,
        start_bearing: float,
        end_bearing: float,
        radius_m: float,
        priority: str,
        color: str
    ) -> int:
        """Legacy implementation: Add search sector to shared layer."""
        if self._uses_per_item_layers("sector"):
            layer = self._get_shared_layer_if_exists(LayerIds.SEARCH_SECTORS, self.SECTORS_LAYER_NAME)
        else:
            layer = self._get_or_create_sectors_layer()
        if not layer or not layer.isValid():
            raise RuntimeError("Sectors layer not available")

        try:
            points_deg = geodesic_sector_points(
                center_wgs84.x(),
                center_wgs84.y(),
                start_bearing,
                end_bearing,
                radius_m,
                num_segments=36
            )
            points = [QgsPointXY(lon, lat) for lon, lat in points_deg]
            sector_geom = QgsGeometry.fromPolygonXY([points])
            self._assert_valid_sector_geometry(sector_geom, name)
        except GeometryError as exc:
            self._notify_error("Add Sector Failed", str(exc))
            raise

        # Calculate arc length (BUG-034 fix)
        # CRITICAL: This determines search area size for SAR operations
        arc_length_deg = calculate_sector_arc_length(start_bearing, end_bearing)

        # Calculate area using WGS84 ellipsoid
        distance_calc = QgsDistanceArea()
        distance_calc.setSourceCrs(layer.crs(), QgsProject.instance().transformContext())
        distance_calc.setEllipsoid('WGS84')
        area_sqm = distance_calc.measureArea(sector_geom)
        area_sqkm = area_sqm / 1000000.0

        logger.debug(f"Sector '{name}': bearings {start_bearing:.1f}°-{end_bearing:.1f}°, arc={arc_length_deg:.1f}°, radius={radius_m:.2f}m, area={area_sqkm:.4f}km²")

        # Create feature
        feature = QgsFeature(layer.fields())
        feature.setGeometry(sector_geom)

        attr_map = {
            "id": str(uuid.uuid4()),
            "name": name,
            "center_lat": float(center_wgs84.y()),
            "center_lon": float(center_wgs84.x()),
            "start_bearing": float(start_bearing),
            "end_bearing": float(end_bearing),
            "radius_m": float(radius_m),
            # BUG-034 fix: store calculated arc length when schema supports it.
            "arc_length_deg": float(arc_length_deg),
            "area_sqkm": float(area_sqkm),
            "priority": priority,
            "color": color,
            "created": self._current_timestamp(),
            "display_order": None,  # set after addFeature
        }
        fields = layer.fields()
        for field_name, value in attr_map.items():
            idx = fields.indexFromName(field_name)
            if idx != -1:
                feature.setAttribute(idx, value)

        # Add to layer with proper resource cleanup
        # CRITICAL: Check for nested transactions
        if layer.isEditable():
            raise LayerLockError(layer.name())

        layer.startEditing()
        try:
            if not layer.addFeature(feature):
                layer.rollBack()
                raise RuntimeError(f"Failed to add feature to {self.SECTORS_LAYER_NAME} layer")
            self._set_display_order(layer, feature.id())
            self._safe_commit(layer, "add", "SECTORS", {})
        except Exception as e:
            layer.rollBack()
            # Raise typed exception for error handler (Issue #3)
            raise LayerTransactionError(
                self.SECTORS_LAYER_NAME,
                "add feature",
                details=str(e)
            ) from e
        finally:
            # Ensure layer is not left in edit mode
            if layer.isEditable():
                layer.rollBack()

        layer.triggerRepaint()
        self._log_drawing_event(
            layer,
            "SECTORS",
            "add",
            name=name,
            start_bearing=start_bearing,
            end_bearing=end_bearing,
            radius_m=radius_m,
            area_sqkm=area_sqkm
        )
        return feature.id()

    def _add_sector_per_item(
        self,
        name: str,
        center_wgs84: QgsPointXY,
        start_bearing: float,
        end_bearing: float,
        radius_m: float,
        priority: str,
        color: str
    ) -> str:
        """
        Phase 4: Add search sector as a per-item layer.

        Creates an individual GeoPackage-backed layer for this sector,
        placed under "SAR Tracker / Map Tools / Search Sectors /".

        Returns:
            str: item_id (which serves as the feature identifier)
        """
        factory = self._get_per_item_factory()
        if not factory:
            logger.warning("Phase 4: No factory available, falling back to shared layer for sector")
            return self._add_sector_shared_layer(
                name=name,
                center_wgs84=center_wgs84,
                start_bearing=start_bearing,
                end_bearing=end_bearing,
                radius_m=radius_m,
                priority=priority,
                color=color
            )

        target_group = self._ensure_per_item_group(ItemType.SEARCH_SECTOR)

        sector_fields = [
            {"name": "id", "type": "String", "length": 50},
            {"name": "name", "type": "String", "length": 255},
            {"name": "center_lat", "type": "Double"},
            {"name": "center_lon", "type": "Double"},
            {"name": "start_bearing", "type": "Double"},
            {"name": "end_bearing", "type": "Double"},
            {"name": "radius_m", "type": "Double"},
            {"name": "arc_length_deg", "type": "Double"},
            {"name": "area_sqkm", "type": "Double"},
            {"name": "priority", "type": "String", "length": 50},
            {"name": "color", "type": "String", "length": 20},
            {"name": "created", "type": "String", "length": 50},
            {"name": "display_order", "type": "Int"},
        ]

        try:
            item_info = factory.create_item_layer(
                item_type=ItemType.SEARCH_SECTOR,
                display_name=name,
                fields=sector_fields,
                add_to_project=True,
                target_group=target_group
            )
        except Exception as e:
            logger.error("Phase 4: Failed to create per-item layer for sector '%s': %s", name, e)
            raise RuntimeError(f"Failed to create per-item sector layer: {e}") from e

        layer = item_info.layer
        item_id = item_info.item_id

        if not layer or not layer.isValid():
            raise RuntimeError(f"Per-item layer created but invalid for sector '{name}'")

        try:
            points_deg = geodesic_sector_points(
                center_wgs84.x(),
                center_wgs84.y(),
                start_bearing,
                end_bearing,
                radius_m,
                num_segments=36
            )
            points = [QgsPointXY(lon, lat) for lon, lat in points_deg]
            sector_geom = QgsGeometry.fromPolygonXY([points])
            self._assert_valid_sector_geometry(sector_geom, name)
        except GeometryError as exc:
            self._notify_error("Add Sector Failed", str(exc))
            raise

        arc_length_deg = calculate_sector_arc_length(start_bearing, end_bearing)

        distance_calc = QgsDistanceArea()
        distance_calc.setSourceCrs(layer.crs(), QgsProject.instance().transformContext())
        distance_calc.setEllipsoid('WGS84')
        area_sqm = distance_calc.measureArea(sector_geom)
        area_sqkm = area_sqm / 1000000.0

        feature = QgsFeature(layer.fields())
        feature.setGeometry(sector_geom)

        created_ts = datetime.now(timezone.utc).isoformat()
        attr_map = {
            "id": item_id,
            "name": name,
            "center_lat": float(center_wgs84.y()),
            "center_lon": float(center_wgs84.x()),
            "start_bearing": float(start_bearing),
            "end_bearing": float(end_bearing),
            "radius_m": float(radius_m),
            "arc_length_deg": float(arc_length_deg),
            "area_sqkm": float(area_sqkm),
            "priority": priority,
            "color": color,
            "created": created_ts,
        }
        fields = layer.fields()
        for field_name, value in attr_map.items():
            idx = fields.indexFromName(field_name)
            if idx != -1:
                feature.setAttribute(idx, value)

        if layer.isEditable():
            raise LayerLockError(layer.name())

        layer.startEditing()
        try:
            if not layer.addFeature(feature):
                layer.rollBack()
                raise RuntimeError(f"Failed to add feature to per-item sector layer '{name}'")
            self._set_display_order(layer, feature.id())
            self._safe_commit(layer, "add", "SECTORS", {})
        except Exception as e:
            layer.rollBack()
            self._cleanup_failed_per_item_layer(factory, item_id, "sector")
            raise LayerTransactionError(
                name,
                "add feature",
                details=str(e)
            ) from e
        finally:
            if layer.isEditable():
                layer.rollBack()

        self._style_sectors_layer(layer)

        layer.triggerRepaint()
        logger.info(
            "Phase 4: Created per-item sector layer '%s' (item_id=%s) under Map Tools/Search Sectors",
            name, item_id
        )
        return item_id

    # -------------------------------------------------------------------------
    # Sectors - Full CRUD (Phase 2)
    # -------------------------------------------------------------------------

    def list_sectors(self, filters: Optional[Dict] = None) -> List[Dict]:
        """List all search sector features."""
        records: List[Dict[str, Any]] = []

        if self._uses_per_item_layers("sector"):
            layer = self._get_shared_layer_if_exists(LayerIds.SEARCH_SECTORS, self.SECTORS_LAYER_NAME)
        else:
            layer = self._get_or_create_sectors_layer()

        if layer and layer.isValid():
            request = self._build_filter_request(layer, filters)

            try:
                for feature in layer.getFeatures(request):
                    rec = self._feature_to_record(feature, layer)
                    if rec:
                        records.append(rec)
            except Exception as exc:
                logger.error("Error listing sectors: %s", exc, exc_info=True)

        if self._uses_per_item_layers("sector"):
            records.extend(self._list_per_item_records(ItemType.SEARCH_SECTOR))

        return self._sort_records_by_display_order(records)

    def get_sector(self, feature_id: Union[int, str]) -> Optional[Dict]:
        """Get a single search sector by feature id."""
        if isinstance(feature_id, str) and self._uses_per_item_layers("sector") and self._is_uuid(feature_id):
            layer = self._get_per_item_layer(ItemType.SEARCH_SECTOR, feature_id)
            if not layer:
                return None
            feature = self._get_single_feature(layer)
            if not feature or not feature.isValid():
                return None
            return self._feature_to_record(feature, layer)

        if not isinstance(feature_id, int):
            try:
                feature_id = int(feature_id)
            except (TypeError, ValueError):
                return None

        # Use same pattern as list_sectors() to avoid creating shared layer in per-item mode
        if self._uses_per_item_layers("sector"):
            layer = self._get_shared_layer_if_exists(LayerIds.SEARCH_SECTORS, self.SECTORS_LAYER_NAME)
        else:
            layer = self._get_or_create_sectors_layer()
        if not layer or not layer.isValid():
            return None
        feature = layer.getFeature(feature_id)
        if not feature.isValid():
            return None
        return self._feature_to_record(feature, layer)

    def update_sector(self, feature_id: Union[int, str], updates: Dict[str, Any], updated_by: Optional[str] = None) -> bool:
        """Update a search sector feature."""
        if isinstance(feature_id, str) and self._uses_per_item_layers("sector") and self._is_uuid(feature_id):
            return self._update_sector_per_item(feature_id, updates, updated_by)

        if not isinstance(feature_id, int):
            try:
                feature_id = int(feature_id)
            except (TypeError, ValueError):
                raise ValueError(f"Invalid feature_id: {feature_id}")
        if feature_id <= 0:
            raise ValueError(f"Invalid feature_id: {feature_id}")
        if not isinstance(updates, dict) or not updates:
            raise ValueError("updates must be a non-empty dictionary")

        if self._uses_per_item_layers("sector"):
            layer = self._get_shared_layer_if_exists(LayerIds.SEARCH_SECTORS, self.SECTORS_LAYER_NAME)
        else:
            layer = self._get_or_create_sectors_layer()

        if not layer:
            raise RuntimeError("Sectors layer not available")
        return self._update_sector_feature(layer, feature_id, updates)

    def _update_sector_feature(
        self,
        layer: QgsVectorLayer,
        feature_id: int,
        updates: Dict[str, Any]
    ) -> bool:
        """Update a search sector feature in the provided layer."""
        if not layer or not layer.isValid():
            raise RuntimeError("Sectors layer not available")

        if layer.isEditable():
            raise LayerLockError(layer.name())

        if not layer.startEditing():
            raise LayerTransactionError(
                layer_name=layer.name(),
                operation="start editing",
                details="startEditing() returned False"
            )

        try:
            feature = layer.getFeature(feature_id)
            if not feature.isValid():
                raise ValueError(f"Feature {feature_id} not found")

            field_names = [field.name() for field in layer.fields()]
            for field_name in updates.keys():
                if field_name not in field_names:
                    raise ValueError(f"Invalid field: {field_name}. Valid fields: {field_names}")

            if 'start_bearing' in updates:
                validate_bearing(updates['start_bearing'], "start_bearing")
            if 'end_bearing' in updates:
                validate_bearing(updates['end_bearing'], "end_bearing")
            if 'radius_m' in updates:
                validate_positive_number(updates['radius_m'], "radius_m")
            if 'color' in updates:
                validate_color_hex(updates['color'], "color")
            if 'center_lat' in updates:
                lat = float(updates['center_lat'])
                if not (-90.0 <= lat <= 90.0):
                    raise ValueError("center_lat must be between -90 and 90")
            if 'center_lon' in updates:
                lon = float(updates['center_lon'])
                if not (-180.0 <= lon <= 180.0):
                    raise ValueError("center_lon must be between -180 and 180")

            # Check if geometric parameters changed - if so, regenerate geometry
            geometric_params = {'center_lat', 'center_lon', 'start_bearing', 'end_bearing', 'radius_m'}
            if geometric_params & updates.keys():
                # Get current values for any parameters not being updated
                current_center_lat = feature.attribute('center_lat')
                current_center_lon = feature.attribute('center_lon')
                current_start_bearing = feature.attribute('start_bearing')
                current_end_bearing = feature.attribute('end_bearing')
                current_radius_m = feature.attribute('radius_m')

                # Use updated values if provided, otherwise keep current
                new_center_lat = updates.get('center_lat', current_center_lat)
                new_center_lon = updates.get('center_lon', current_center_lon)
                new_start_bearing = updates.get('start_bearing', current_start_bearing)
                new_end_bearing = updates.get('end_bearing', current_end_bearing)
                new_radius_m = updates.get('radius_m', current_radius_m)

                # Regenerate sector geometry
                points_deg = geodesic_sector_points(
                    float(new_center_lon),
                    float(new_center_lat),
                    float(new_start_bearing),
                    float(new_end_bearing),
                    float(new_radius_m),
                    num_segments=36
                )
                points = [QgsPointXY(lon, lat) for lon, lat in points_deg]
                new_geometry = QgsGeometry.fromPolygonXY([points])

                # Recalculate arc length (BUG-034 fix)
                # CRITICAL: Arc length must be recalculated when bearings change
                new_arc_length_deg = calculate_sector_arc_length(
                    float(new_start_bearing),
                    float(new_end_bearing)
                )

                # Recalculate area
                distance_calc = QgsDistanceArea()
                distance_calc.setSourceCrs(layer.crs(), QgsProject.instance().transformContext())
                distance_calc.setEllipsoid('WGS84')
                area_sqm = distance_calc.measureArea(new_geometry)
                area_sqkm = area_sqm / 1000000.0

                # Update geometry
                if not layer.changeGeometry(feature_id, new_geometry):
                    raise RuntimeError("Failed to update sector geometry")

                # Update arc_length_deg attribute (BUG-034 fix)
                arc_length_field_index = layer.fields().indexFromName('arc_length_deg')
                if arc_length_field_index != -1:
                    if not layer.changeAttributeValue(feature_id, arc_length_field_index, new_arc_length_deg):
                        raise RuntimeError("Failed to update arc_length_deg")

                # Update area attribute
                area_field_index = layer.fields().indexFromName('area_sqkm')
                if area_field_index != -1:
                    if not layer.changeAttributeValue(feature_id, area_field_index, area_sqkm):
                        raise RuntimeError("Failed to update area_sqkm")

            # Update all requested attributes
            for field_name, value in updates.items():
                field_index = layer.fields().indexFromName(field_name)
                if field_index == -1:
                    continue
                if not layer.changeAttributeValue(feature_id, field_index, value):
                    raise RuntimeError(f"Failed to update {field_name}")

            self._safe_commit(layer, "update", "SECTORS", {"feature_id": feature_id})

            layer.triggerRepaint()
            return True

        except Exception as exc:
            layer.rollBack()
            if isinstance(exc, LayerTransactionError):
                raise
            raise LayerTransactionError(
                layer_name=layer.name(),
                operation="update feature",
                details=str(exc)
            ) from exc
        finally:
            if layer.isEditable():
                try:
                    layer.rollBack()
                except RuntimeError:
                    pass

    def _update_sector_per_item(
        self,
        item_id: str,
        updates: Dict[str, Any],
        updated_by: Optional[str] = None
    ) -> bool:
        """Update attributes of a per-item sector."""
        if not isinstance(updates, dict) or not updates:
            raise ValueError("updates must be a non-empty dictionary")

        layer = self._get_per_item_layer(ItemType.SEARCH_SECTOR, item_id)
        if not layer or not layer.isValid():
            raise ValueError(f"Per-item sector '{item_id}' not found")

        feature = self._get_single_feature(layer)
        if not feature or not feature.isValid():
            raise ValueError(f"Per-item sector '{item_id}' has no feature")

        result = self._update_sector_feature(layer, feature.id(), updates)
        if result and "name" in updates and updates["name"]:
            factory = self._get_per_item_factory()
            if factory:
                factory.rename_item_layer(item_id, str(updates["name"]))
        return result

    def delete_sector(self, feature_id: Union[int, str], updated_by: Optional[str] = None) -> bool:
        """Delete a single search sector."""
        if isinstance(feature_id, str) and self._uses_per_item_layers("sector") and self._is_uuid(feature_id):
            return self._delete_sector_per_item(feature_id, updated_by)

        if not isinstance(feature_id, int):
            try:
                feature_id = int(feature_id)
            except (TypeError, ValueError):
                raise ValueError(f"Invalid feature_id: {feature_id}")
        if feature_id <= 0:
            raise ValueError(f"Invalid feature_id: {feature_id}")

        if self._uses_per_item_layers("sector"):
            layer = self._get_shared_layer_if_exists(LayerIds.SEARCH_SECTORS, self.SECTORS_LAYER_NAME)
        else:
            layer = self._get_or_create_sectors_layer()
        if not layer or not layer.isValid():
            raise RuntimeError("Sectors layer not available")

        if layer.isEditable():
            raise LayerLockError(layer.name())

        if not layer.startEditing():
            raise LayerTransactionError(
                layer_name=layer.name(),
                operation="start editing",
                details="delete operation"
            )

        try:
            if not layer.deleteFeature(feature_id):
                raise RuntimeError(f"Failed to delete feature {feature_id}")

            self._safe_commit(layer, "delete", "SECTORS", {"feature_id": feature_id})

            layer.triggerRepaint()
            return True
        except Exception as exc:
            layer.rollBack()
            raise LayerTransactionError(
                layer_name=layer.name(),
                operation="delete feature",
                details=str(exc)
            ) from exc
        finally:
            if layer.isEditable():
                try:
                    layer.rollBack()
                except RuntimeError:
                    pass

    def _delete_sector_per_item(self, item_id: str, updated_by: Optional[str] = None) -> bool:
        """Delete a per-item sector layer."""
        factory = self._get_per_item_factory()
        if not factory:
            raise RuntimeError("Per-item factory unavailable for sector deletion")

        layer = self._get_per_item_layer(ItemType.SEARCH_SECTOR, item_id)
        if not layer or not layer.isValid():
            raise ValueError(f"Per-item sector '{item_id}' not found")

        success = factory.delete_item_layer(
            item_id=item_id,
            remove_table=False,
            hard_delete=False
        )
        if not success:
            raise RuntimeError(f"Failed to delete per-item sector '{item_id}'")

        return True

    def delete_sectors(self, feature_ids: List[Union[int, str]], updated_by: Optional[str] = None) -> int:
        """Bulk delete search sectors."""
        if not feature_ids:
            return 0

        deleted = 0
        per_item_ids = [
            fid for fid in feature_ids
            if isinstance(fid, str) and self._uses_per_item_layers("sector") and self._is_uuid(fid)
        ]
        if per_item_ids:
            for item_id in per_item_ids:
                try:
                    if self._delete_sector_per_item(item_id, updated_by):
                        deleted += 1
                except Exception as exc:
                    logger.error(
                        "Failed to delete per-item sector '%s': %s",
                        item_id, exc, exc_info=True
                    )
                    # Continue processing remaining items

        shared_ids: List[int] = []
        for fid in feature_ids:
            if isinstance(fid, str) and self._is_uuid(fid):
                continue
            try:
                shared_ids.append(int(fid))
            except (TypeError, ValueError):
                continue

        if not shared_ids:
            return deleted

        if len(shared_ids) > self.MAX_SYNC_FEATURES:
            logger.warning("Deleting %s sector features synchronously; consider background task", len(shared_ids))

        if self._uses_per_item_layers("sector"):
            layer = self._get_shared_layer_if_exists(LayerIds.SEARCH_SECTORS, self.SECTORS_LAYER_NAME)
        else:
            layer = self._get_or_create_sectors_layer()
        if not layer or not layer.isValid():
            raise RuntimeError("Sectors layer not available")

        if layer.isEditable():
            raise LayerLockError(layer.name())

        if not layer.startEditing():
            raise LayerTransactionError(
                layer_name=layer.name(),
                operation="start editing",
                details="bulk delete operation"
            )

        try:
            for fid in shared_ids:
                if layer.deleteFeature(fid):
                    deleted += 1

            self._safe_commit(layer, "bulk_delete", "SECTORS", {"deleted": deleted})

            layer.triggerRepaint()
            return deleted
        except Exception as exc:
            layer.rollBack()
            raise LayerTransactionError(
                layer_name=layer.name(),
                operation="bulk delete features",
                details=str(exc)
            ) from exc
        finally:
            if layer.isEditable():
                try:
                    layer.rollBack()
                except RuntimeError:
                    pass


    # =========================================================================
    # Text Labels Layer
    # =========================================================================

    def _get_or_create_text_labels_layer(self) -> QgsVectorLayer:
        """
        Get or create Text Labels layer for map annotations.

        Returns:
            QgsVectorLayer: Text Labels layer
        """
        if self.layer_manager:
            layer = self._ensure_schema_layer(
                LayerIds.TEXT_LABELS,
                fallback_name=self.TEXT_LABELS_LAYER_NAME,
                style_factory=self._style_text_labels_layer
            )
            layer = self._require_valid_layer(layer, self.TEXT_LABELS_LAYER_NAME)
            self._log_drawing_event(layer, "TEXT_LABELS", "ensure")
            return layer

        layers = self.project.mapLayersByName(self.TEXT_LABELS_LAYER_NAME)
        if layers:
            layer = layers[0]
            layer = self._require_valid_layer(layer, self.TEXT_LABELS_LAYER_NAME)
            self._log_drawing_event(layer, "TEXT_LABELS", "reused")
            return layer

        # Create memory layer with WGS84 CRS
        # Qt5/Qt6 Compatible: Using integer type codes
        layer = QgsVectorLayer(
            "Point?crs=EPSG:4326",
            self.TEXT_LABELS_LAYER_NAME,
            "memory"
        )

        # Add fields
        layer.dataProvider().addAttributes([
            QgsField("id", QVariant.String),              # String - unique ID
            QgsField("text", QVariant.String),            # String - label text
            QgsField("lat", QVariant.Double),             # Double - latitude
            QgsField("lon", QVariant.Double),             # Double - longitude
            QgsField("font_size", QVariant.Int),          # Int - font size
            QgsField("color", QVariant.String),           # String - text color
            QgsField("rotation", QVariant.Double),        # Double - rotation angle
            QgsField("created", QVariant.String),         # String - ISO timestamp
            QgsField("display_order", QVariant.Int),      # Int - display order for UI (Phase 2)
        ])
        layer.updateFields()

        # Basic point styling (small, will show label instead)
        symbol = layer.renderer().symbol()
        symbol.setSize(0)  # Hide the point marker

        # Add to project in layer group
        self._add_layer_to_group(layer, position=0)

        self._log_drawing_event(layer, "TEXT_LABELS", "created")
        return self._require_valid_layer(layer, self.TEXT_LABELS_LAYER_NAME)

    def add_text_label(self, text: str, location_wgs84: QgsPointXY,
                       font_size: int = 12, color: str = "#000000",
                       rotation: float = 0.0) -> Union[int, str]:
        """
        Add a text label annotation.

        Args:
            text: Label text
            location_wgs84: Label location in WGS84
            font_size: Font size in points
            color: Text color hex string
            rotation: Rotation angle in degrees

        Returns:
            int: Feature ID of added label (shared layer)
            str: item_id for per-item layer
        """
        # Validate text is not empty or whitespace-only
        if not text or not text.strip():
            raise ValueError("Text label cannot be empty or whitespace-only")

        # Use stripped text (remove leading/trailing whitespace)
        text = text.strip()

        # Validate text length (GeoPackage/SQLite VARCHAR limit)
        if len(text) > self.MAX_TEXT_LABEL_LENGTH:
            raise ValueError(
                f"Text label must be {self.MAX_TEXT_LABEL_LENGTH} characters or less "
                f"(got {len(text)})"
            )

        try:
            validate_point(location_wgs84, "location_wgs84")
            validate_font_size(font_size, "font_size")
            validate_color_hex(color, "color")
        except Exception as exc:
            self._notify_error("Add Text Label Failed", str(exc))
            raise

        # Validate rotation is a finite number and normalize to float
        try:
            rotation_val = float(rotation)
            if not math.isfinite(rotation_val):
                raise ValueError("rotation must be a finite number (not NaN or Inf)")
        except (TypeError, ValueError) as exc:
            self._notify_error("Add Text Label Failed", f"Invalid rotation: {exc}")
            raise ValueError(f"Invalid rotation: {exc}") from exc

        # Phase 4: Check if we should use per-item layers
        if self._uses_per_item_layers("text_label"):
            return self._add_text_label_per_item(
                text=text,
                location_wgs84=location_wgs84,
                font_size=font_size,
                color=color,
                rotation=rotation_val  # Use validated/normalized value
            )

        # Legacy path: shared layer
        return self._add_text_label_shared_layer(
            text=text,
            location_wgs84=location_wgs84,
            font_size=font_size,
            color=color,
            rotation=rotation_val  # Use validated/normalized value
        )

    def _add_text_label_shared_layer(
        self,
        text: str,
        location_wgs84: QgsPointXY,
        font_size: int,
        color: str,
        rotation: float
    ) -> int:
        """Legacy implementation: Add text label to shared layer."""
        if self._uses_per_item_layers("text_label"):
            layer = self._get_shared_layer_if_exists(LayerIds.TEXT_LABELS, self.TEXT_LABELS_LAYER_NAME)
        else:
            layer = self._get_or_create_text_labels_layer()
        if not layer or not layer.isValid():
            raise RuntimeError("Text labels layer not available")

        # Create feature
        feature = QgsFeature(layer.fields())
        feature.setGeometry(QgsGeometry.fromPointXY(location_wgs84))

        attr_map = {
            "id": str(uuid.uuid4()),
            "text": text,
            "lat": float(location_wgs84.y()),
            "lon": float(location_wgs84.x()),
            "font_size": int(font_size),
            "color": color,
            "rotation": float(rotation),
            "created": self._current_timestamp(),
            "display_order": None,  # set after addFeature
        }
        fields = layer.fields()
        for field_name, value in attr_map.items():
            idx = fields.indexFromName(field_name)
            if idx != -1:
                feature.setAttribute(idx, value)

        # Add to layer with proper resource cleanup
        # CRITICAL: Check for nested transactions
        if layer.isEditable():
            raise LayerLockError(layer.name())

        layer.startEditing()
        try:
            if not layer.addFeature(feature):
                layer.rollBack()
                raise RuntimeError(f"Failed to add feature to {self.TEXT_LABELS_LAYER_NAME} layer")
            self._set_display_order(layer, feature.id())
            self._safe_commit(layer, "add", "TEXT_LABELS", {})
        except Exception as e:
            layer.rollBack()
            # Raise typed exception for error handler (Issue #3)
            raise LayerTransactionError(
                self.TEXT_LABELS_LAYER_NAME,
                "add feature",
                details=str(e)
            ) from e
        finally:
            # Ensure layer is not left in edit mode
            if layer.isEditable():
                layer.rollBack()

        layer.triggerRepaint()
        self._log_drawing_event(
            layer,
            "TEXT_LABELS",
            "add",
            text=text,
            font_size=font_size,
            rotation=rotation
        )
        return feature.id()

    def _add_text_label_per_item(
        self,
        text: str,
        location_wgs84: QgsPointXY,
        font_size: int,
        color: str,
        rotation: float
    ) -> str:
        """
        Phase 4: Add text label as a per-item layer.

        Creates an individual GeoPackage-backed layer for this text label,
        placed under "SAR Tracker / Map Tools / Text Labels /".

        Returns:
            str: item_id (which serves as the feature identifier)
        """
        factory = self._get_per_item_factory()
        if not factory:
            logger.warning("Phase 4: No factory available, falling back to shared layer for text label")
            return self._add_text_label_shared_layer(
                text=text,
                location_wgs84=location_wgs84,
                font_size=font_size,
                color=color,
                rotation=rotation
            )

        target_group = self._ensure_per_item_group(ItemType.TEXT_LABEL)

        label_fields = [
            {"name": "id", "type": "String", "length": 50},
            {"name": "text", "type": "String", "length": 255},
            {"name": "lat", "type": "Double"},
            {"name": "lon", "type": "Double"},
            {"name": "font_size", "type": "Int"},
            {"name": "color", "type": "String", "length": 20},
            {"name": "rotation", "type": "Double"},
            {"name": "created", "type": "String", "length": 50},
            {"name": "display_order", "type": "Int"},
        ]

        try:
            item_info = factory.create_item_layer(
                item_type=ItemType.TEXT_LABEL,
                display_name=text,
                fields=label_fields,
                add_to_project=True,
                target_group=target_group
            )
        except Exception as e:
            logger.error("Phase 4: Failed to create per-item layer for text label '%s': %s", text, e)
            raise RuntimeError(f"Failed to create per-item text label layer: {e}") from e

        layer = item_info.layer
        item_id = item_info.item_id

        if not layer or not layer.isValid():
            raise RuntimeError("Per-item text label layer created but invalid")

        feature = QgsFeature(layer.fields())
        feature.setGeometry(QgsGeometry.fromPointXY(location_wgs84))

        created_ts = datetime.now(timezone.utc).isoformat()
        attr_map = {
            "id": item_id,
            "text": text,
            "lat": float(location_wgs84.y()),
            "lon": float(location_wgs84.x()),
            "font_size": int(font_size),
            "color": color,
            "rotation": float(rotation),
            "created": created_ts,
        }
        fields = layer.fields()
        for field_name, value in attr_map.items():
            idx = fields.indexFromName(field_name)
            if idx != -1:
                feature.setAttribute(idx, value)

        if layer.isEditable():
            raise LayerLockError(layer.name())

        layer.startEditing()
        try:
            if not layer.addFeature(feature):
                layer.rollBack()
                raise RuntimeError(f"Failed to add feature to per-item text label layer '{text}'")
            self._set_display_order(layer, feature.id())
            self._safe_commit(layer, "add", "TEXT_LABELS", {})
        except Exception as e:
            layer.rollBack()
            self._cleanup_failed_per_item_layer(factory, item_id, "text label")
            raise LayerTransactionError(
                text,
                "add feature",
                details=str(e)
            ) from e
        finally:
            if layer.isEditable():
                layer.rollBack()

        self._style_text_labels_layer(layer)

        layer.triggerRepaint()
        logger.info(
            "Phase 4: Created per-item text label layer '%s' (item_id=%s) under Map Tools/Text Labels",
            text, item_id
        )
        return item_id

    # =========================================================================
    # Phase 2: Full CRUD Operations for All Drawing Types
    # =========================================================================

    def _feature_to_record(self, feature: QgsFeature, layer: QgsVectorLayer) -> Dict[str, Any]:
        """
        Convert QgsFeature to dictionary record.

        Handles NULL values, date parsing, geometry serialization.
        CRITICAL: NULL value handling is essential for JSON serialization.

        Args:
            feature: QGIS feature to convert
            layer: Parent layer (for field metadata)

        Returns:
            Dictionary with feature attributes
        """
        if not feature.isValid():
            return {}

        record = {}

        # Extract all attributes
        for field in layer.fields():
            field_name = field.name()
            value = feature.attribute(field_name)

            # Handle NULL values (CRITICAL for JSON serialization)
            if value is None or value == NULL:
                record[field_name] = None
                continue

            # Handle numeric fields
            if field.type() in (QVariant.Int, QVariant.LongLong):
                record[field_name] = int(value) if value else 0
            elif field.type() == QVariant.Double:
                record[field_name] = float(value) if value else 0.0
            elif field.type() == QVariant.Bool:
                record[field_name] = bool(value) if value else False
            else:
                # String and other types
                record[field_name] = str(value) if value else ""

        # Add feature ID (not an attribute)
        record['feature_id'] = feature.id()

        # Add geometry summary (lightweight)
        if feature.hasGeometry():
            geom = feature.geometry()
            record['geometry_type'] = QgsWkbTypes.displayString(geom.wkbType())

            try:
                # Add computed geometry properties
                if geom.type() == QgsWkbTypes.PolygonGeometry:
                    # Area calculation using WGS84 ellipsoid
                    distance_calc = QgsDistanceArea()
                    distance_calc.setSourceCrs(layer.crs(), QgsProject.instance().transformContext())
                    distance_calc.setEllipsoid('WGS84')
                    area_m2 = distance_calc.measureArea(geom)
                    record['area_km2'] = area_m2 / 1_000_000
                elif geom.type() == QgsWkbTypes.LineGeometry:
                    # Length calculation using WGS84 ellipsoid
                    distance_calc = QgsDistanceArea()
                    distance_calc.setSourceCrs(layer.crs(), QgsProject.instance().transformContext())
                    distance_calc.setEllipsoid('WGS84')
                    length_m = distance_calc.measureLine(geom.asPolyline())
                    record['length_km'] = length_m / 1000
            except Exception as exc:
                logger.warning(
                    "Geometry summary failed for %s feature %s: %s",
                    layer.name(),
                    feature.id(),
                    exc
                )
        else:
            record['geometry_type'] = None

        return record

    # =========================================================================
    # SEARCH AREAS - Full CRUD Operations
    # =========================================================================

    def list_search_areas(self, filters: Optional[Dict] = None) -> List[Dict]:
        """
        List all search area features.

        Args:
            filters: Optional filters (e.g., {'status': 'Planned', 'team': 'Alpha'})

        Returns:
            List of feature dictionaries ordered by display_order (if field exists)
        """
        records: List[Dict[str, Any]] = []

        layer = self._get_or_create_search_areas_layer()
        if layer and layer.isValid():
            request = self._build_filter_request(layer, filters)

            # Fetch and serialize features
            try:
                for feature in layer.getFeatures(request):
                    record = self._feature_to_record(feature, layer)
                    if record:
                        records.append(record)
            except Exception as e:
                logger.error(f"Error listing search areas: {e}", exc_info=True)

        if self._uses_per_item_layers("search_area"):
            records.extend(self._list_per_item_records(ItemType.SEARCH_AREA))

        return self._sort_records_by_display_order(records)

    def get_search_area(self, feature_id: Union[int, str]) -> Optional[Dict]:
        """
        Get single search area by feature ID.

        Args:
            feature_id: Feature ID to retrieve

        Returns:
            Feature dictionary or None if not found
        """
        if isinstance(feature_id, str) and self._uses_per_item_layers("search_area") and self._is_uuid(feature_id):
            layer = self._get_per_item_layer(ItemType.SEARCH_AREA, feature_id)
            if not layer:
                return None
            feature = self._get_single_feature(layer)
            if not feature or not feature.isValid():
                return None
            return self._feature_to_record(feature, layer)

        if not isinstance(feature_id, int):
            try:
                feature_id = int(feature_id)
            except (TypeError, ValueError):
                return None

        layer = self._get_or_create_search_areas_layer()
        if not layer or not layer.isValid():
            return None

        feature = layer.getFeature(feature_id)
        if not feature.isValid():
            return None

        return self._feature_to_record(feature, layer)

    def update_search_area(
        self,
        feature_id: Union[int, str],
        updates: Dict[str, Any],
        updated_by: Optional[str] = None
    ) -> bool:
        """
        Update search area feature attributes.

        CRITICAL: Transaction-safe pattern for life-safety system.
        Follows mandatory pattern from phase2_supplement.md.

        Args:
            feature_id: Feature ID to update
            updates: Dict of field->value pairs to update
            updated_by: Coordinator name for audit trail

        Returns:
            True on success

        Raises:
            ValueError: If feature_id invalid or updates malformed
            LayerTransactionError: If commit fails
        """
        # ========================================================================
        # STEP 1: VALIDATE INPUT (BEFORE touching layer)
        # ========================================================================

        if isinstance(feature_id, str) and self._uses_per_item_layers("search_area") and self._is_uuid(feature_id):
            return self._update_search_area_per_item(feature_id, updates, updated_by)

        if not isinstance(feature_id, int):
            try:
                feature_id = int(feature_id)
            except (TypeError, ValueError):
                raise ValueError(
                    f"Invalid feature ID: {feature_id}. "
                    "Feature IDs must be positive integers. "
                    "Verify the ID was correctly retrieved from the search areas layer."
                )

        if feature_id <= 0:
            raise ValueError(
                f"Invalid feature ID: {feature_id}. "
                "Feature IDs must be positive integers. "
                "Verify the ID was correctly retrieved from the search areas layer."
            )

        if not isinstance(updates, dict) or not updates:
            raise ValueError("updates must be a non-empty dictionary")

        # Get layer
        layer = self._get_or_create_search_areas_layer()
        if not layer or not layer.isValid():
            raise RuntimeError("Search areas layer not available")

        # ========================================================================
        # STEP 2: START TRANSACTION (BEFORE validation to prevent TOCTOU)
        # ========================================================================
        # CRITICAL: Start editing BEFORE feature validation to prevent race condition
        # where feature could be deleted between validation and transaction start

        if layer.isEditable():
            raise LayerLockError(layer.name())

        if not layer.startEditing():
            raise LayerTransactionError(
                layer_name=layer.name(),
                operation="start editing",
                details="startEditing() returned False"
            )

        try:
            # ====================================================================
            # STEP 3: VALIDATE FEATURE EXISTS (inside transaction)
            # ====================================================================

            feature = layer.getFeature(feature_id)
            if not feature.isValid():
                raise ValueError(f"Feature {feature_id} not found in search areas layer")

            # ====================================================================
            # STEP 4: VALIDATE ALL UPDATE FIELDS
            # ====================================================================

            # Get layer field names
            field_names = [field.name() for field in layer.fields()]

            for field_name, value in updates.items():
                # Check field exists
                if field_name not in field_names:
                    raise ValueError(f"Invalid field: {field_name}. Valid fields: {field_names}")

                # Validate field-specific constraints
                if field_name == 'name':
                    if not isinstance(value, str) or not value.strip():
                        raise ValueError("name must be a non-empty string")
                    if len(value) > 128:
                        raise ValueError("name must be ≤ 128 characters")

                elif field_name == 'status':
                    valid_statuses = ['Planned', 'Assigned', 'InProgress', 'Completed', 'Cleared']
                    if value not in valid_statuses:
                        raise ValueError(f"status must be one of: {valid_statuses}")

                elif field_name == 'priority':
                    valid_priorities = ['High', 'Medium', 'Low']
                    if value not in valid_priorities:
                        raise ValueError(f"priority must be one of: {valid_priorities}")

                elif field_name == 'area_sqkm':
                    if not isinstance(value, (int, float)) or value <= 0:
                        raise ValueError("area_sqkm must be a positive number")

                elif field_name == 'POA':
                    if not isinstance(value, (int, float)) or not (0 <= value <= 100):
                        raise ValueError("POA must be between 0 and 100")
                elif field_name == 'color':
                    validate_color_hex(value, "color")
            # ====================================================================
            # STEP 5: APPLY UPDATES
            # ====================================================================

            # Add audit trail if updated_by provided
            if updated_by:
                updates['updated_by'] = updated_by
                updates['updated_at'] = self._current_timestamp()

            # Apply each update
            for field_name, value in updates.items():
                field_index = layer.fields().indexFromName(field_name)
                if field_index == -1:
                    # Field doesn't exist (might be audit field not in schema)
                    continue

                success = layer.changeAttributeValue(feature_id, field_index, value)
                if not success:
                    raise RuntimeError(f"Failed to update {field_name} on feature {feature_id}")

            # ====================================================================
            # STEP 6: COMMIT CHANGES
            # ====================================================================

            self._safe_commit(layer, "update", "SEARCH_AREAS", {"feature_id": feature_id})

            # ====================================================================
            # STEP 7: POST-COMMIT ACTIONS
            # ====================================================================

            layer.triggerRepaint()
            logger.debug(f"Updated search area {feature_id}: {updates}")

            return True

        except Exception as e:
            # ====================================================================
            # STEP 8: ROLLBACK ON ANY ERROR
            # ====================================================================

            if layer.isEditable():
                layer.rollBack()
                logger.debug(f"Rolled back transaction due to error: {e}")

            # Re-raise as LayerTransactionError with correct signature
            if isinstance(e, LayerTransactionError):
                raise
            else:
                raise LayerTransactionError(
                    layer_name=layer.name(),
                    operation="update feature",
                    details=str(e)
                ) from e
        finally:
            # ====================================================================
            # STEP 9: FINAL CLEANUP (CRITICAL for life-safety)
            # ====================================================================

            # Ensure layer NEVER left in edit mode (even if exception during rollback)
            if layer and layer.isValid() and layer.isEditable():
                try:
                    layer.rollBack()
                except RuntimeError:
                    pass  # Layer already rolled back or deleted

    def _update_search_area_per_item(
        self,
        item_id: str,
        updates: Dict[str, Any],
        updated_by: Optional[str] = None
    ) -> bool:
        """Update attributes of a per-item search area."""
        if not isinstance(updates, dict) or not updates:
            raise ValueError("updates must be a non-empty dictionary")

        layer = self._get_per_item_layer(ItemType.SEARCH_AREA, item_id)
        if not layer or not layer.isValid():
            raise ValueError(f"Per-item search area '{item_id}' not found")

        if layer.isEditable():
            raise LayerLockError(layer.name())

        if not layer.startEditing():
            raise LayerTransactionError(
                layer_name=layer.name(),
                operation="start editing",
                details="startEditing() returned False"
            )

        try:
            feature = self._get_single_feature(layer)
            if not feature or not feature.isValid():
                raise ValueError(f"Per-item search area '{item_id}' has no feature")

            field_names = [field.name() for field in layer.fields()]
            for field_name, value in updates.items():
                if field_name not in field_names:
                    raise ValueError(f"Invalid field: {field_name}. Valid fields: {field_names}")

                if field_name == 'name':
                    if not isinstance(value, str) or not value.strip():
                        raise ValueError("name must be a non-empty string")
                    if len(value) > 128:
                        raise ValueError("name must be ≤ 128 characters")
                elif field_name == 'status':
                    valid_statuses = ['Planned', 'Assigned', 'InProgress', 'Completed', 'Cleared']
                    if value not in valid_statuses:
                        raise ValueError(f"status must be one of: {valid_statuses}")
                elif field_name == 'priority':
                    valid_priorities = ['High', 'Medium', 'Low']
                    if value not in valid_priorities:
                        raise ValueError(f"priority must be one of: {valid_priorities}")
                elif field_name == 'area_sqkm':
                    if not isinstance(value, (int, float)) or value <= 0:
                        raise ValueError("area_sqkm must be a positive number")
                elif field_name == 'POA':
                    if not isinstance(value, (int, float)) or not (0 <= value <= 100):
                        raise ValueError("POA must be between 0 and 100")
                elif field_name == 'color':
                    validate_color_hex(value, "color")

            if updated_by:
                updates['updated_by'] = updated_by
                updates['updated_at'] = self._current_timestamp()

            for field_name, value in updates.items():
                field_index = layer.fields().indexFromName(field_name)
                if field_index == -1:
                    continue
                if not layer.changeAttributeValue(feature.id(), field_index, value):
                    raise RuntimeError(f"Failed to update {field_name} on feature {feature.id()}")

            self._safe_commit(layer, "update", "SEARCH_AREAS", {"item_id": item_id, "feature_id": feature.id()})

            if "name" in updates and updates["name"]:
                factory = self._get_per_item_factory()
                if factory:
                    factory.rename_item_layer(item_id, str(updates["name"]))

            layer.triggerRepaint()
            logger.debug("Updated per-item search area %s", item_id)
            return True

        except Exception as e:
            layer.rollBack()
            if isinstance(e, LayerTransactionError):
                raise
            raise LayerTransactionError(
                layer_name=layer.name(),
                operation="update feature",
                details=str(e)
            ) from e
        finally:
            if layer and layer.isValid() and layer.isEditable():
                try:
                    layer.rollBack()
                except RuntimeError:
                    pass

    def delete_search_area(
        self,
        feature_id: Union[int, str],
        updated_by: Optional[str] = None
    ) -> bool:
        """
        Delete single search area.

        Args:
            feature_id: Feature ID to delete
            updated_by: Coordinator name for audit trail

        Returns:
            True on success

        Raises:
            ValueError: If feature_id invalid
            LayerTransactionError: If deletion fails
        """
        if isinstance(feature_id, str) and self._uses_per_item_layers("search_area") and self._is_uuid(feature_id):
            return self._delete_search_area_per_item(feature_id, updated_by)

        if not isinstance(feature_id, int):
            try:
                feature_id = int(feature_id)
            except (TypeError, ValueError):
                raise ValueError(f"Invalid feature_id: {feature_id}")

        if feature_id <= 0:
            raise ValueError(f"Invalid feature_id: {feature_id}")

        layer = self._get_or_create_search_areas_layer()
        if not layer or not layer.isValid():
            raise RuntimeError("Search areas layer not available")

        # Verify feature exists
        feature = layer.getFeature(feature_id)
        if not feature.isValid():
            raise ValueError(f"Feature {feature_id} not found")

        # CRITICAL: Check for nested transactions
        if layer.isEditable():
            raise LayerLockError(layer.name())

        if not layer.startEditing():
            raise LayerTransactionError(
                layer_name=layer.name(),
                operation="start editing",
                details="Delete operation"
            )

        try:
            success = layer.deleteFeature(feature_id)
            if not success:
                raise RuntimeError(f"Failed to delete feature {feature_id}")

            self._safe_commit(layer, "delete", "SEARCH_AREAS", {"feature_id": feature_id})

            layer.triggerRepaint()
            logger.debug(f"Deleted search area {feature_id}")

            return True

        except Exception as e:
            layer.rollBack()
            raise LayerTransactionError(
                layer_name=layer.name(),
                operation="delete feature",
                details=str(e)
            ) from e
        finally:
            if layer and layer.isValid() and layer.isEditable():
                try:
                    layer.rollBack()
                except RuntimeError:
                    pass

    def _delete_search_area_per_item(self, item_id: str, updated_by: Optional[str] = None) -> bool:
        """Delete a per-item search area layer."""
        factory = self._get_per_item_factory()
        if not factory:
            raise RuntimeError("Per-item factory unavailable for search area deletion")

        layer = self._get_per_item_layer(ItemType.SEARCH_AREA, item_id)
        if not layer or not layer.isValid():
            raise ValueError(f"Per-item search area '{item_id}' not found")

        success = factory.delete_item_layer(
            item_id=item_id,
            remove_table=False,
            hard_delete=False
        )
        if not success:
            raise RuntimeError(f"Failed to delete per-item search area '{item_id}'")

        return True

    def delete_search_areas(
        self,
        feature_ids: List[int],
        updated_by: Optional[str] = None
    ) -> int:
        """
        Bulk delete search areas.

        BUG-033 FIX: Uses global layer edit lock to prevent race conditions
        during bulk operations.

        Args:
            feature_ids: List of feature IDs to delete
            updated_by: Coordinator name for audit trail

        Returns:
            Number of features deleted

        Raises:
            ValueError: If feature_ids empty
            LayerTransactionError: If deletion fails
            LayerLockError: If unable to acquire edit lock
        """
        if not feature_ids:
            return 0

        if len(feature_ids) > self.MAX_SYNC_FEATURES:
            logger.warning("Deleting %s search area features synchronously; consider background task", len(feature_ids))

        layer = self._get_or_create_search_areas_layer()
        if not layer or not layer.isValid():
            raise RuntimeError("Search areas layer not available")

        # CRITICAL: Check for nested transactions
        if layer.isEditable():
            raise LayerLockError(layer.name())

        # BUG-033 FIX: Acquire global lock to prevent race conditions during bulk operations
        if not self.acquire_layer_edit_lock(timeout=10.0):
            raise LayerLockError(
                f"{layer.name()} - concurrent bulk operation in progress. "
                "Please wait for the current operation to complete."
            )

        try:
            if not layer.startEditing():
                raise LayerTransactionError(
                    layer_name=layer.name(),
                    operation="start editing",
                    details="Bulk delete operation"
                )

            try:
                deleted = 0
                for feature_id in feature_ids:
                    if layer.deleteFeature(feature_id):
                        deleted += 1

                self._safe_commit(layer, "bulk_delete", "SEARCH_AREAS", {"deleted": deleted})

                layer.triggerRepaint()
                logger.debug(f"Bulk deleted {deleted}/{len(feature_ids)} search areas")

                return deleted

            except Exception as e:
                layer.rollBack()
                raise LayerTransactionError(
                    layer_name=layer.name(),
                    operation="bulk delete features",
                    details=str(e)
                ) from e
            finally:
                if layer and layer.isValid() and layer.isEditable():
                    try:
                        layer.rollBack()
                    except RuntimeError:
                        pass
        finally:
            # BUG-033 FIX: Always release lock, even on error
            self.release_layer_edit_lock()

    # =========================================================================
    # RANGE RINGS - Full CRUD Operations
    # =========================================================================

    def list_range_rings(self, filters: Optional[Dict] = None) -> List[Dict]:
        """
        List all range ring features.

        Args:
            filters: Optional filters (e.g., {'lpb_category': 'Lost Person'})

        Returns:
            List of feature dictionaries
        """
        records: List[Dict[str, Any]] = []

        layer = self._get_or_create_range_rings_layer()
        if layer and layer.isValid():
            request = self._build_filter_request(layer, filters)

            try:
                for feature in layer.getFeatures(request):
                    record = self._feature_to_record(feature, layer)
                    if record:
                        records.append(record)
            except Exception as e:
                logger.error(f"Error listing range rings: {e}", exc_info=True)

        if self._uses_per_item_layers("range_ring"):
            records.extend(self._list_per_item_records(ItemType.RANGE_RING))

        return self._sort_records_by_display_order(records)

    def get_range_ring(self, feature_id: Union[int, str]) -> Optional[Dict]:
        """
        Get single range ring by feature ID.

        Args:
            feature_id: Feature ID to retrieve

        Returns:
            Feature dictionary or None if not found
        """
        if isinstance(feature_id, str) and self._uses_per_item_layers("range_ring") and self._is_uuid(feature_id):
            layer = self._get_per_item_layer(ItemType.RANGE_RING, feature_id)
            if not layer:
                return None
            feature = self._get_single_feature(layer)
            if not feature or not feature.isValid():
                return None
            return self._feature_to_record(feature, layer)

        if not isinstance(feature_id, int):
            try:
                feature_id = int(feature_id)
            except (TypeError, ValueError):
                return None

        layer = self._get_or_create_range_rings_layer()
        if not layer or not layer.isValid():
            return None

        feature = layer.getFeature(feature_id)
        if not feature.isValid():
            return None

        return self._feature_to_record(feature, layer)

    def update_range_ring(
        self,
        feature_id: Union[int, str],
        updates: Dict[str, Any],
        updated_by: Optional[str] = None
    ) -> bool:
        """
        Update range ring attributes.

        Args:
            feature_id: Feature ID to update
            updates: Dict of field->value pairs
            updated_by: Coordinator name for audit trail

        Returns:
            True on success

        Raises:
            ValueError: If feature_id invalid or updates malformed
            LayerTransactionError: If commit fails
        """
        if isinstance(feature_id, str) and self._uses_per_item_layers("range_ring") and self._is_uuid(feature_id):
            return self._update_range_ring_per_item(feature_id, updates, updated_by)

        if not isinstance(feature_id, int):
            try:
                feature_id = int(feature_id)
            except (TypeError, ValueError):
                raise ValueError(f"Invalid feature_id: {feature_id}")

        if feature_id <= 0:
            raise ValueError(f"Invalid feature_id: {feature_id}")

        if not isinstance(updates, dict) or not updates:
            raise ValueError("updates must be a non-empty dictionary")

        layer = self._get_or_create_range_rings_layer()
        if not layer or not layer.isValid():
            raise RuntimeError("Range rings layer not available")

        # CRITICAL: Start editing BEFORE feature validation to prevent TOCTOU
        if layer.isEditable():
            raise LayerLockError(layer.name())

        if not layer.startEditing():
            raise LayerTransactionError(
                layer_name=layer.name(),
                operation="start editing",
                details="startEditing() returned False"
            )

        try:
            feature = layer.getFeature(feature_id)
            if not feature.isValid():
                raise ValueError(f"Feature {feature_id} not found")

            field_names = [field.name() for field in layer.fields()]
            for field_name in updates.keys():
                if field_name not in field_names:
                    raise ValueError(f"Invalid field: {field_name}. Valid fields: {field_names}")
            if updated_by:
                updates['updated_by'] = updated_by
                updates['updated_at'] = self._current_timestamp()

            # Validate range ring-specific fields
            if 'radius_m' in updates:
                validate_positive_number(updates['radius_m'], "radius_m")
            if 'color' in updates:
                validate_color_hex(updates['color'], "color")
            if 'center_lat' in updates:
                lat = float(updates['center_lat'])
                if not (-90.0 <= lat <= 90.0):
                    raise ValueError("center_lat must be between -90 and 90")
            if 'center_lon' in updates:
                lon = float(updates['center_lon'])
                if not (-180.0 <= lon <= 180.0):
                    raise ValueError("center_lon must be between -180 and 180")

            for field_name, value in updates.items():
                field_index = layer.fields().indexFromName(field_name)
                if field_index == -1:
                    continue

                success = layer.changeAttributeValue(feature_id, field_index, value)
                if not success:
                    raise RuntimeError(f"Failed to update {field_name}")

            self._safe_commit(layer, "update", "RANGE_RINGS", {"feature_id": feature_id})

            layer.triggerRepaint()
            logger.debug(f"Updated range ring {feature_id}")

            return True

        except Exception as e:
            layer.rollBack()
            if isinstance(e, LayerTransactionError):
                raise
            else:
                raise LayerTransactionError(
                    layer_name=layer.name(),
                    operation="update feature",
                    details=str(e)
                ) from e
        finally:
            if layer and layer.isValid() and layer.isEditable():
                try:
                    layer.rollBack()
                except RuntimeError:
                    pass

    def _update_range_ring_per_item(
        self,
        item_id: str,
        updates: Dict[str, Any],
        updated_by: Optional[str] = None
    ) -> bool:
        """Update attributes of a per-item range ring."""
        if not isinstance(updates, dict) or not updates:
            raise ValueError("updates must be a non-empty dictionary")

        layer = self._get_per_item_layer(ItemType.RANGE_RING, item_id)
        if not layer or not layer.isValid():
            raise ValueError(f"Per-item range ring '{item_id}' not found")

        if layer.isEditable():
            raise LayerLockError(layer.name())

        if not layer.startEditing():
            raise LayerTransactionError(
                layer_name=layer.name(),
                operation="start editing",
                details="startEditing() returned False"
            )

        try:
            feature = self._get_single_feature(layer)
            if not feature or not feature.isValid():
                raise ValueError(f"Per-item range ring '{item_id}' has no feature")

            field_names = [field.name() for field in layer.fields()]
            for field_name in updates.keys():
                if field_name not in field_names:
                    raise ValueError(f"Invalid field: {field_name}. Valid fields: {field_names}")

            if updated_by:
                updates['updated_by'] = updated_by
                updates['updated_at'] = self._current_timestamp()

            if 'radius_m' in updates:
                validate_positive_number(updates['radius_m'], "radius_m")
            if 'color' in updates:
                validate_color_hex(updates['color'], "color")
            if 'center_lat' in updates:
                lat = float(updates['center_lat'])
                if not (-90.0 <= lat <= 90.0):
                    raise ValueError("center_lat must be between -90 and 90")
            if 'center_lon' in updates:
                lon = float(updates['center_lon'])
                if not (-180.0 <= lon <= 180.0):
                    raise ValueError("center_lon must be between -180 and 180")

            for field_name, value in updates.items():
                field_index = layer.fields().indexFromName(field_name)
                if field_index == -1:
                    continue
                if not layer.changeAttributeValue(feature.id(), field_index, value):
                    raise RuntimeError(f"Failed to update {field_name}")

            self._safe_commit(layer, "update", "RANGE_RINGS", {"item_id": item_id, "feature_id": feature.id()})

            if "name" in updates and updates["name"]:
                factory = self._get_per_item_factory()
                if factory:
                    factory.rename_item_layer(item_id, str(updates["name"]))

            layer.triggerRepaint()
            logger.debug("Updated per-item range ring %s", item_id)
            return True

        except Exception as e:
            layer.rollBack()
            if isinstance(e, LayerTransactionError):
                raise
            raise LayerTransactionError(
                layer_name=layer.name(),
                operation="update feature",
                details=str(e)
            ) from e
        finally:
            if layer and layer.isValid() and layer.isEditable():
                try:
                    layer.rollBack()
                except RuntimeError:
                    pass

    def delete_range_ring(
        self,
        feature_id: Union[int, str],
        updated_by: Optional[str] = None
    ) -> bool:
        """
        Delete single range ring.

        Args:
            feature_id: Feature ID to delete
            updated_by: Coordinator name for audit trail

        Returns:
            True on success
        """
        if isinstance(feature_id, str) and self._uses_per_item_layers("range_ring") and self._is_uuid(feature_id):
            return self._delete_range_ring_per_item(feature_id, updated_by)

        if not isinstance(feature_id, int):
            try:
                feature_id = int(feature_id)
            except (TypeError, ValueError):
                raise ValueError(f"Invalid feature_id: {feature_id}")

        if feature_id <= 0:
            raise ValueError(f"Invalid feature_id: {feature_id}")

        layer = self._get_or_create_range_rings_layer()
        if not layer or not layer.isValid():
            raise RuntimeError("Range rings layer not available")

        feature = layer.getFeature(feature_id)
        if not feature.isValid():
            raise ValueError(f"Feature {feature_id} not found")

        # CRITICAL: Check for nested transactions
        if layer.isEditable():
            raise LayerLockError(layer.name())

        if not layer.startEditing():
            raise LayerTransactionError(
                layer_name=layer.name(),
                operation="start editing",
                details="Delete operation"
            )

        try:
            success = layer.deleteFeature(feature_id)
            if not success:
                raise RuntimeError(f"Failed to delete feature {feature_id}")

            self._safe_commit(layer, "delete", "RANGE_RINGS", {"feature_id": feature_id})

            layer.triggerRepaint()
            logger.debug(f"Deleted range ring {feature_id}")

            return True

        except Exception as e:
            layer.rollBack()
            raise LayerTransactionError(
                layer_name=layer.name(),
                operation="delete feature",
                details=str(e)
            ) from e
        finally:
            if layer and layer.isValid() and layer.isEditable():
                try:
                    layer.rollBack()
                except RuntimeError:
                    pass

    def _delete_range_ring_per_item(self, item_id: str, updated_by: Optional[str] = None) -> bool:
        """Delete a per-item range ring layer."""
        factory = self._get_per_item_factory()
        if not factory:
            raise RuntimeError("Per-item factory unavailable for range ring deletion")

        layer = self._get_per_item_layer(ItemType.RANGE_RING, item_id)
        if not layer or not layer.isValid():
            raise ValueError(f"Per-item range ring '{item_id}' not found")

        success = factory.delete_item_layer(
            item_id=item_id,
            remove_table=False,
            hard_delete=False
        )
        if not success:
            raise RuntimeError(f"Failed to delete per-item range ring '{item_id}'")

        return True

    def delete_range_rings(
        self,
        feature_ids: List[int],
        updated_by: Optional[str] = None
    ) -> int:
        """
        Bulk delete range rings.

        Args:
            feature_ids: List of feature IDs to delete
            updated_by: Coordinator name for audit trail

        Returns:
            Number of features deleted
        """
        if not feature_ids:
            return 0

        if len(feature_ids) > self.MAX_SYNC_FEATURES:
            logger.warning("Deleting %s range ring features synchronously; consider background task", len(feature_ids))

        layer = self._get_or_create_range_rings_layer()
        if not layer or not layer.isValid():
            raise RuntimeError("Range rings layer not available")

        # CRITICAL: Check for nested transactions
        if layer.isEditable():
            raise LayerLockError(layer.name())

        if not layer.startEditing():
            raise LayerTransactionError(
                layer_name=layer.name(),
                operation="start editing",
                details="Bulk delete operation"
            )

        try:
            deleted = 0
            for feature_id in feature_ids:
                if layer.deleteFeature(feature_id):
                    deleted += 1

            self._safe_commit(layer, "bulk_delete", "RANGE_RINGS", {"deleted": deleted})

            layer.triggerRepaint()
            logger.debug(f"Bulk deleted {deleted}/{len(feature_ids)} range rings")

            return deleted

        except Exception as e:
            layer.rollBack()
            raise LayerTransactionError(
                layer_name=layer.name(),
                operation="bulk delete features",
                details=str(e)
            ) from e
        finally:
            if layer and layer.isValid() and layer.isEditable():
                try:
                    layer.rollBack()
                except RuntimeError:
                    pass

    # =========================================================================
    # BEARING LINES - Full CRUD Operations
    # =========================================================================

    def list_bearing_lines(self, filters: Optional[Dict] = None) -> List[Dict]:
        """
        List all bearing line features.

        Args:
            filters: Optional filters

        Returns:
            List of feature dictionaries
        """
        records: List[Dict[str, Any]] = []

        layer = self._get_or_create_bearing_lines_layer()
        if layer and layer.isValid():
            request = self._build_filter_request(layer, filters)

            try:
                for feature in layer.getFeatures(request):
                    record = self._feature_to_record(feature, layer)
                    if record:
                        records.append(record)
            except Exception as e:
                logger.error(f"Error listing bearing lines: {e}", exc_info=True)

        if self._uses_per_item_layers("bearing_line"):
            records.extend(self._list_per_item_records(ItemType.BEARING_LINE))

        return self._sort_records_by_display_order(records)

    def get_bearing_line(self, feature_id: Union[int, str]) -> Optional[Dict]:
        """
        Get single bearing line by feature ID.

        Args:
            feature_id: Feature ID to retrieve

        Returns:
            Feature dictionary or None if not found
        """
        if isinstance(feature_id, str) and self._uses_per_item_layers("bearing_line") and self._is_uuid(feature_id):
            layer = self._get_per_item_layer(ItemType.BEARING_LINE, feature_id)
            if not layer:
                return None
            feature = self._get_single_feature(layer)
            if not feature or not feature.isValid():
                return None
            return self._feature_to_record(feature, layer)

        if not isinstance(feature_id, int):
            try:
                feature_id = int(feature_id)
            except (TypeError, ValueError):
                return None

        layer = self._get_or_create_bearing_lines_layer()
        if not layer or not layer.isValid():
            return None

        feature = layer.getFeature(feature_id)
        if not feature.isValid():
            return None

        return self._feature_to_record(feature, layer)

    def update_bearing_line(
        self,
        feature_id: Union[int, str],
        updates: Dict[str, Any],
        updated_by: Optional[str] = None
    ) -> bool:
        """
        Update bearing line attributes.

        Args:
            feature_id: Feature ID to update
            updates: Dict of field->value pairs
            updated_by: Coordinator name for audit trail

        Returns:
            True on success
        """
        if isinstance(feature_id, str) and self._uses_per_item_layers("bearing_line") and self._is_uuid(feature_id):
            return self._update_bearing_line_per_item(feature_id, updates, updated_by)

        if not isinstance(feature_id, int):
            try:
                feature_id = int(feature_id)
            except (TypeError, ValueError):
                raise ValueError(f"Invalid feature_id: {feature_id}")

        if feature_id <= 0:
            raise ValueError(f"Invalid feature_id: {feature_id}")

        if not isinstance(updates, dict) or not updates:
            raise ValueError("updates must be a non-empty dictionary")

        layer = self._get_or_create_bearing_lines_layer()
        if not layer or not layer.isValid():
            raise RuntimeError("Bearing lines layer not available")

        # CRITICAL: Start editing BEFORE feature validation to prevent TOCTOU
        if layer.isEditable():
            raise LayerLockError(layer.name())

        if not layer.startEditing():
            raise LayerTransactionError(
                layer_name=layer.name(),
                operation="start editing",
                details="startEditing() returned False"
            )

        try:
            feature = layer.getFeature(feature_id)
            if not feature.isValid():
                raise ValueError(f"Feature {feature_id} not found")

            field_names = [field.name() for field in layer.fields()]
            for field_name in updates.keys():
                if field_name not in field_names:
                    raise ValueError(f"Invalid field: {field_name}. Valid fields: {field_names}")
            if updated_by:
                updates['updated_by'] = updated_by
                updates['updated_at'] = self._current_timestamp()

            # Validate bearing line-specific fields
            if 'bearing' in updates:
                validate_bearing(updates['bearing'], "bearing")
            if 'distance_m' in updates:
                validate_positive_number(updates['distance_m'], "distance_m")
            if 'color' in updates:
                validate_color_hex(updates['color'], "color")
            if 'origin_lat' in updates:
                lat = float(updates['origin_lat'])
                if not (-90.0 <= lat <= 90.0):
                    raise ValueError("origin_lat must be between -90 and 90")
            if 'origin_lon' in updates:
                lon = float(updates['origin_lon'])
                if not (-180.0 <= lon <= 180.0):
                    raise ValueError("origin_lon must be between -180 and 180")

            for field_name, value in updates.items():
                field_index = layer.fields().indexFromName(field_name)
                if field_index == -1:
                    continue

                success = layer.changeAttributeValue(feature_id, field_index, value)
                if not success:
                    raise RuntimeError(f"Failed to update {field_name}")

            self._safe_commit(layer, "update", "BEARING_LINES", {"feature_id": feature_id})

            layer.triggerRepaint()
            logger.debug(f"Updated bearing line {feature_id}")

            return True

        except Exception as e:
            layer.rollBack()
            if isinstance(e, LayerTransactionError):
                raise
            else:
                raise LayerTransactionError(
                    layer_name=layer.name(),
                    operation="update feature",
                    details=str(e)
                ) from e
        finally:
            if layer and layer.isValid() and layer.isEditable():
                try:
                    layer.rollBack()
                except RuntimeError:
                    pass

    def _update_bearing_line_per_item(
        self,
        item_id: str,
        updates: Dict[str, Any],
        updated_by: Optional[str] = None
    ) -> bool:
        """Update attributes of a per-item bearing line."""
        if not isinstance(updates, dict) or not updates:
            raise ValueError("updates must be a non-empty dictionary")

        layer = self._get_per_item_layer(ItemType.BEARING_LINE, item_id)
        if not layer or not layer.isValid():
            raise ValueError(f"Per-item bearing line '{item_id}' not found")

        if layer.isEditable():
            raise LayerLockError(layer.name())

        if not layer.startEditing():
            raise LayerTransactionError(
                layer_name=layer.name(),
                operation="start editing",
                details="startEditing() returned False"
            )

        try:
            feature = self._get_single_feature(layer)
            if not feature or not feature.isValid():
                raise ValueError(f"Per-item bearing line '{item_id}' has no feature")

            field_names = [field.name() for field in layer.fields()]
            for field_name in updates.keys():
                if field_name not in field_names:
                    raise ValueError(f"Invalid field: {field_name}. Valid fields: {field_names}")

            if updated_by:
                updates['updated_by'] = updated_by
                updates['updated_at'] = self._current_timestamp()

            if 'bearing' in updates:
                validate_bearing(updates['bearing'], "bearing")
            if 'distance_m' in updates:
                validate_positive_number(updates['distance_m'], "distance_m")
            if 'color' in updates:
                validate_color_hex(updates['color'], "color")
            if 'origin_lat' in updates:
                lat = float(updates['origin_lat'])
                if not (-90.0 <= lat <= 90.0):
                    raise ValueError("origin_lat must be between -90 and 90")
            if 'origin_lon' in updates:
                lon = float(updates['origin_lon'])
                if not (-180.0 <= lon <= 180.0):
                    raise ValueError("origin_lon must be between -180 and 180")

            for field_name, value in updates.items():
                field_index = layer.fields().indexFromName(field_name)
                if field_index == -1:
                    continue
                if not layer.changeAttributeValue(feature.id(), field_index, value):
                    raise RuntimeError(f"Failed to update {field_name}")

            self._safe_commit(layer, "update", "BEARING_LINES", {"item_id": item_id, "feature_id": feature.id()})

            if "name" in updates and updates["name"]:
                factory = self._get_per_item_factory()
                if factory:
                    factory.rename_item_layer(item_id, str(updates["name"]))

            layer.triggerRepaint()
            logger.debug("Updated per-item bearing line %s", item_id)
            return True

        except Exception as e:
            layer.rollBack()
            if isinstance(e, LayerTransactionError):
                raise
            raise LayerTransactionError(
                layer_name=layer.name(),
                operation="update feature",
                details=str(e)
            ) from e
        finally:
            if layer and layer.isValid() and layer.isEditable():
                try:
                    layer.rollBack()
                except RuntimeError:
                    pass

    def delete_bearing_line(
        self,
        feature_id: Union[int, str],
        updated_by: Optional[str] = None
    ) -> bool:
        """
        Delete single bearing line.

        Args:
            feature_id: Feature ID to delete
            updated_by: Coordinator name for audit trail

        Returns:
            True on success
        """
        if isinstance(feature_id, str) and self._uses_per_item_layers("bearing_line") and self._is_uuid(feature_id):
            return self._delete_bearing_line_per_item(feature_id, updated_by)

        if not isinstance(feature_id, int):
            try:
                feature_id = int(feature_id)
            except (TypeError, ValueError):
                raise ValueError(f"Invalid feature_id: {feature_id}")

        if feature_id <= 0:
            raise ValueError(f"Invalid feature_id: {feature_id}")

        layer = self._get_or_create_bearing_lines_layer()
        if not layer or not layer.isValid():
            raise RuntimeError("Bearing lines layer not available")

        feature = layer.getFeature(feature_id)
        if not feature.isValid():
            raise ValueError(f"Feature {feature_id} not found")

        # CRITICAL: Check for nested transactions
        if layer.isEditable():
            raise LayerLockError(layer.name())

        if not layer.startEditing():
            raise LayerTransactionError(
                layer_name=layer.name(),
                operation="start editing",
                details="Delete operation"
            )

        try:
            success = layer.deleteFeature(feature_id)
            if not success:
                raise RuntimeError(f"Failed to delete feature {feature_id}")

            self._safe_commit(layer, "delete", "BEARING_LINES", {"feature_id": feature_id})

            layer.triggerRepaint()
            logger.debug(f"Deleted bearing line {feature_id}")

            return True

        except Exception as e:
            layer.rollBack()
            raise LayerTransactionError(
                layer_name=layer.name(),
                operation="delete feature",
                details=str(e)
            ) from e
        finally:
            if layer and layer.isValid() and layer.isEditable():
                try:
                    layer.rollBack()
                except RuntimeError:
                    pass

    def _delete_bearing_line_per_item(self, item_id: str, updated_by: Optional[str] = None) -> bool:
        """Delete a per-item bearing line layer."""
        factory = self._get_per_item_factory()
        if not factory:
            raise RuntimeError("Per-item factory unavailable for bearing line deletion")

        layer = self._get_per_item_layer(ItemType.BEARING_LINE, item_id)
        if not layer or not layer.isValid():
            raise ValueError(f"Per-item bearing line '{item_id}' not found")

        success = factory.delete_item_layer(
            item_id=item_id,
            remove_table=False,
            hard_delete=False
        )
        if not success:
            raise RuntimeError(f"Failed to delete per-item bearing line '{item_id}'")

        return True

    def delete_bearing_lines(
        self,
        feature_ids: List[int],
        updated_by: Optional[str] = None
    ) -> int:
        """
        Bulk delete bearing lines.

        Args:
            feature_ids: List of feature IDs to delete
            updated_by: Coordinator name for audit trail

        Returns:
            Number of features deleted
        """
        if not feature_ids:
            return 0

        if len(feature_ids) > self.MAX_SYNC_FEATURES:
            logger.warning("Deleting %s bearing line features synchronously; consider background task", len(feature_ids))

        layer = self._get_or_create_bearing_lines_layer()
        if not layer or not layer.isValid():
            raise RuntimeError("Bearing lines layer not available")

        # CRITICAL: Check for nested transactions
        if layer.isEditable():
            raise LayerLockError(layer.name())

        if not layer.startEditing():
            raise LayerTransactionError(
                layer_name=layer.name(),
                operation="start editing",
                details="Bulk delete operation"
            )

        try:
            deleted = 0
            for feature_id in feature_ids:
                if layer.deleteFeature(feature_id):
                    deleted += 1

            self._safe_commit(layer, "bulk_delete", "BEARING_LINES", {"deleted": deleted})

            layer.triggerRepaint()
            logger.debug(f"Bulk deleted {deleted}/{len(feature_ids)} bearing lines")

            return deleted

        except Exception as e:
            layer.rollBack()
            raise LayerTransactionError(
                layer_name=layer.name(),
                operation="bulk delete features",
                details=str(e)
            ) from e
        finally:
            if layer and layer.isValid() and layer.isEditable():
                try:
                    layer.rollBack()
                except RuntimeError:
                    pass

    # =========================================================================
    # TEXT LABELS - Full CRUD Operations
    # =========================================================================

    def list_text_labels(self, filters: Optional[Dict] = None) -> List[Dict]:
        """
        List all text label features.

        Args:
            filters: Optional filters

        Returns:
            List of feature dictionaries
        """
        records: List[Dict[str, Any]] = []

        if self._uses_per_item_layers("text_label"):
            layer = self._get_shared_layer_if_exists(LayerIds.TEXT_LABELS, self.TEXT_LABELS_LAYER_NAME)
        else:
            layer = self._get_or_create_text_labels_layer()
        if layer and layer.isValid():
            request = self._build_filter_request(layer, filters)

            try:
                for feature in layer.getFeatures(request):
                    record = self._feature_to_record(feature, layer)
                    if record:
                        records.append(record)
            except Exception as e:
                logger.error(f"Error listing text labels: {e}", exc_info=True)

        if self._uses_per_item_layers("text_label"):
            records.extend(self._list_per_item_records(ItemType.TEXT_LABEL))

        return self._sort_records_by_display_order(records)

    def get_text_label(self, feature_id: Union[int, str]) -> Optional[Dict]:
        """
        Get single text label by feature ID.

        Args:
            feature_id: Feature ID to retrieve

        Returns:
            Feature dictionary or None if not found
        """
        if isinstance(feature_id, str) and self._uses_per_item_layers("text_label") and self._is_uuid(feature_id):
            layer = self._get_per_item_layer(ItemType.TEXT_LABEL, feature_id)
            if not layer:
                return None
            feature = self._get_single_feature(layer)
            if not feature or not feature.isValid():
                return None
            return self._feature_to_record(feature, layer)

        if not isinstance(feature_id, int):
            try:
                feature_id = int(feature_id)
            except (TypeError, ValueError):
                return None

        if self._uses_per_item_layers("text_label"):
            layer = self._get_shared_layer_if_exists(LayerIds.TEXT_LABELS, self.TEXT_LABELS_LAYER_NAME)
        else:
            layer = self._get_or_create_text_labels_layer()
        if not layer or not layer.isValid():
            return None

        feature = layer.getFeature(feature_id)
        if not feature.isValid():
            return None

        return self._feature_to_record(feature, layer)

    def update_text_label(
        self,
        feature_id: Union[int, str],
        updates: Dict[str, Any],
        updated_by: Optional[str] = None
    ) -> bool:
        """
        Update text label attributes.

        Args:
            feature_id: Feature ID to update
            updates: Dict of field->value pairs
            updated_by: Coordinator name for audit trail

        Returns:
            True on success
        """
        if isinstance(feature_id, str) and self._uses_per_item_layers("text_label") and self._is_uuid(feature_id):
            return self._update_text_label_per_item(feature_id, updates, updated_by)

        if not isinstance(feature_id, int):
            try:
                feature_id = int(feature_id)
            except (TypeError, ValueError):
                raise ValueError(f"Invalid feature_id: {feature_id}")
        if feature_id <= 0:
            raise ValueError(f"Invalid feature_id: {feature_id}")

        if not isinstance(updates, dict) or not updates:
            raise ValueError("updates must be a non-empty dictionary")

        if self._uses_per_item_layers("text_label"):
            layer = self._get_shared_layer_if_exists(LayerIds.TEXT_LABELS, self.TEXT_LABELS_LAYER_NAME)
        else:
            layer = self._get_or_create_text_labels_layer()
        if not layer or not layer.isValid():
            raise RuntimeError("Text labels layer not available")

        # CRITICAL: Start editing BEFORE feature validation to prevent TOCTOU
        if layer.isEditable():
            raise LayerLockError(layer.name())

        if not layer.startEditing():
            raise LayerTransactionError(
                layer_name=layer.name(),
                operation="start editing",
                details="startEditing() returned False"
            )

        try:
            feature = layer.getFeature(feature_id)
            if not feature.isValid():
                raise ValueError(f"Feature {feature_id} not found")

            field_names = [field.name() for field in layer.fields()]
            for field_name in updates.keys():
                if field_name not in field_names:
                    raise ValueError(f"Invalid field: {field_name}. Valid fields: {field_names}")
            if updated_by:
                updates['updated_by'] = updated_by
                updates['updated_at'] = self._current_timestamp()

            if 'text' in updates:
                new_text = str(updates['text']).strip() if updates['text'] is not None else ""
                if not new_text:
                    raise ValueError("Text label cannot be empty or whitespace-only")
                if len(new_text) > self.MAX_TEXT_LABEL_LENGTH:
                    raise ValueError(
                        f"Text label must be {self.MAX_TEXT_LABEL_LENGTH} characters or less "
                        f"(got {len(new_text)})"
                    )
                updates['text'] = new_text
            if 'font_size' in updates:
                validate_font_size(updates['font_size'], "font_size")
            if 'color' in updates:
                validate_color_hex(updates['color'], "color")
            if 'rotation' in updates:
                try:
                    rotation_val = float(updates['rotation'])
                    if not math.isfinite(rotation_val):
                        raise ValueError("rotation must be a finite number (not NaN or Inf)")
                    updates['rotation'] = rotation_val  # Normalize to float
                except (TypeError, ValueError) as exc:
                    raise ValueError(f"Invalid rotation: {exc}") from exc

            for field_name, value in updates.items():
                field_index = layer.fields().indexFromName(field_name)
                if field_index == -1:
                    continue

                success = layer.changeAttributeValue(feature_id, field_index, value)
                if not success:
                    raise RuntimeError(f"Failed to update {field_name}")

            self._safe_commit(layer, "update", "TEXT_LABELS", {"feature_id": feature_id})

            layer.triggerRepaint()
            logger.debug(f"Updated text label {feature_id}")
            return True

        except Exception as e:
            layer.rollBack()
            if isinstance(e, LayerTransactionError):
                raise
            raise LayerTransactionError(
                layer_name=layer.name(),
                operation="update feature",
                details=str(e)
            ) from e
        finally:
            if layer and layer.isValid() and layer.isEditable():
                try:
                    layer.rollBack()
                except RuntimeError:
                    pass

    def _update_text_label_per_item(
        self,
        item_id: str,
        updates: Dict[str, Any],
        updated_by: Optional[str] = None
    ) -> bool:
        """Update attributes of a per-item text label."""
        if not isinstance(updates, dict) or not updates:
            raise ValueError("updates must be a non-empty dictionary")

        layer = self._get_per_item_layer(ItemType.TEXT_LABEL, item_id)
        if not layer or not layer.isValid():
            raise ValueError(f"Per-item text label '{item_id}' not found")

        feature = self._get_single_feature(layer)
        if not feature or not feature.isValid():
            raise ValueError(f"Per-item text label '{item_id}' has no feature")

        if layer.isEditable():
            raise LayerLockError(layer.name())

        if not layer.startEditing():
            raise LayerTransactionError(
                layer_name=layer.name(),
                operation="start editing",
                details="startEditing() returned False"
            )

        try:
            field_names = [field.name() for field in layer.fields()]
            for field_name in updates.keys():
                if field_name not in field_names:
                    raise ValueError(f"Invalid field: {field_name}. Valid fields: {field_names}")

            if 'text' in updates:
                new_text = str(updates['text']).strip() if updates['text'] is not None else ""
                if not new_text:
                    raise ValueError("Text label cannot be empty or whitespace-only")
                if len(new_text) > self.MAX_TEXT_LABEL_LENGTH:
                    raise ValueError(
                        f"Text label must be {self.MAX_TEXT_LABEL_LENGTH} characters or less "
                        f"(got {len(new_text)})"
                    )
                updates['text'] = new_text
            if 'font_size' in updates:
                validate_font_size(updates['font_size'], "font_size")
            if 'color' in updates:
                validate_color_hex(updates['color'], "color")
            if 'rotation' in updates:
                try:
                    rotation_val = float(updates['rotation'])
                    if not math.isfinite(rotation_val):
                        raise ValueError("rotation must be a finite number (not NaN or Inf)")
                    updates['rotation'] = rotation_val  # Normalize to float
                except (TypeError, ValueError) as exc:
                    raise ValueError(f"Invalid rotation: {exc}") from exc

            for field_name, value in updates.items():
                field_index = layer.fields().indexFromName(field_name)
                if field_index == -1:
                    continue
                if not layer.changeAttributeValue(feature.id(), field_index, value):
                    raise RuntimeError(f"Failed to update {field_name}")

            self._safe_commit(layer, "update", "TEXT_LABELS", {"item_id": item_id, "feature_id": feature.id()})

            if "text" in updates and updates["text"]:
                factory = self._get_per_item_factory()
                if factory:
                    factory.rename_item_layer(item_id, str(updates["text"]))

            layer.triggerRepaint()
            return True

        except Exception as e:
            layer.rollBack()
            if isinstance(e, LayerTransactionError):
                raise
            raise LayerTransactionError(
                layer_name=layer.name(),
                operation="update feature",
                details=str(e)
            ) from e
        finally:
            if layer and layer.isValid() and layer.isEditable():
                try:
                    layer.rollBack()
                except RuntimeError:
                    pass

    def delete_text_label(
        self,
        feature_id: Union[int, str],
        updated_by: Optional[str] = None
    ) -> bool:
        """
        Delete single text label.

        Args:
            feature_id: Feature ID to delete
            updated_by: Coordinator name for audit trail

        Returns:
            True on success
        """
        if isinstance(feature_id, str) and self._uses_per_item_layers("text_label") and self._is_uuid(feature_id):
            return self._delete_text_label_per_item(feature_id, updated_by)

        if not isinstance(feature_id, int):
            try:
                feature_id = int(feature_id)
            except (TypeError, ValueError):
                raise ValueError(f"Invalid feature_id: {feature_id}")
        if feature_id <= 0:
            raise ValueError(f"Invalid feature_id: {feature_id}")

        if self._uses_per_item_layers("text_label"):
            layer = self._get_shared_layer_if_exists(LayerIds.TEXT_LABELS, self.TEXT_LABELS_LAYER_NAME)
        else:
            layer = self._get_or_create_text_labels_layer()
        if not layer or not layer.isValid():
            raise RuntimeError("Text labels layer not available")

        feature = layer.getFeature(feature_id)
        if not feature.isValid():
            raise ValueError(f"Feature {feature_id} not found")

        # CRITICAL: Check for nested transactions
        if layer.isEditable():
            raise LayerLockError(layer.name())

        if not layer.startEditing():
            raise LayerTransactionError(
                layer_name=layer.name(),
                operation="start editing",
                details="Delete operation"
            )

        try:
            success = layer.deleteFeature(feature_id)
            if not success:
                raise RuntimeError(f"Failed to delete feature {feature_id}")

            self._safe_commit(layer, "delete", "TEXT_LABELS", {"feature_id": feature_id})

            layer.triggerRepaint()
            logger.debug(f"Deleted text label {feature_id}")

            return True

        except Exception as e:
            layer.rollBack()
            raise LayerTransactionError(
                layer_name=layer.name(),
                operation="delete feature",
                details=str(e)
            ) from e
        finally:
            if layer and layer.isValid() and layer.isEditable():
                try:
                    layer.rollBack()
                except RuntimeError:
                    pass

    def _delete_text_label_per_item(
        self,
        item_id: str,
        updated_by: Optional[str] = None
    ) -> bool:
        """Delete a per-item text label layer."""
        factory = self._get_per_item_factory()
        if not factory:
            raise RuntimeError("Per-item factory unavailable for text label deletion")

        layer = self._get_per_item_layer(ItemType.TEXT_LABEL, item_id)
        if not layer or not layer.isValid():
            raise ValueError(f"Per-item text label '{item_id}' not found")

        success = factory.delete_item_layer(
            item_id=item_id,
            remove_table=False,
            hard_delete=False
        )
        if not success:
            raise RuntimeError(f"Failed to delete per-item text label '{item_id}'")

        return True

    def delete_text_labels(
        self,
        feature_ids: List[Union[int, str]],
        updated_by: Optional[str] = None
    ) -> int:
        """
        Bulk delete text labels.

        Args:
            feature_ids: List of feature IDs to delete
            updated_by: Coordinator name for audit trail

        Returns:
            Number of features deleted
        """
        if not feature_ids:
            return 0

        deleted = 0
        per_item_ids = [
            fid for fid in feature_ids
            if isinstance(fid, str) and self._uses_per_item_layers("text_label") and self._is_uuid(fid)
        ]
        if per_item_ids:
            for item_id in per_item_ids:
                try:
                    if self._delete_text_label_per_item(item_id, updated_by):
                        deleted += 1
                except Exception as exc:
                    logger.error(
                        "Failed to delete per-item text label '%s': %s",
                        item_id, exc, exc_info=True
                    )
                    # Continue processing remaining items

        shared_ids: List[int] = []
        for fid in feature_ids:
            if isinstance(fid, str) and self._is_uuid(fid):
                continue
            try:
                shared_ids.append(int(fid))
            except (TypeError, ValueError):
                continue

        if not shared_ids:
            return deleted

        if len(shared_ids) > self.MAX_SYNC_FEATURES:
            logger.warning("Deleting %s text label features synchronously; consider background task", len(shared_ids))

        if self._uses_per_item_layers("text_label"):
            layer = self._get_shared_layer_if_exists(LayerIds.TEXT_LABELS, self.TEXT_LABELS_LAYER_NAME)
        else:
            layer = self._get_or_create_text_labels_layer()
        if not layer or not layer.isValid():
            raise RuntimeError("Text labels layer not available")

        # CRITICAL: Check for nested transactions
        if layer.isEditable():
            raise LayerLockError(layer.name())

        if not layer.startEditing():
            raise LayerTransactionError(
                layer_name=layer.name(),
                operation="start editing",
                details="Bulk delete operation"
            )

        try:
            for feature_id in shared_ids:
                if layer.deleteFeature(feature_id):
                    deleted += 1

            self._safe_commit(layer, "bulk_delete", "TEXT_LABELS", {"deleted": deleted})

            layer.triggerRepaint()
            logger.debug(f"Bulk deleted {deleted}/{len(feature_ids)} text labels")

            return deleted

        except Exception as e:
            layer.rollBack()
            raise LayerTransactionError(
                layer_name=layer.name(),
                operation="bulk delete features",
                details=str(e)
            ) from e
        finally:
            if layer and layer.isValid() and layer.isEditable():
                try:
                    layer.rollBack()
                except RuntimeError:
                    pass

    # =========================================================================
    # GPX IMPORT - File and Folder Import with Optional Folder Watching
    # =========================================================================

    # GPX layer group name
    GPX_TRACKS_GROUP_NAME = "GPX Tracks"

    # GPX import limits (defensive)
    MAX_GPX_FILES_PER_IMPORT = 50

    def _init_gpx_support(self):
        """Initialize GPX import support. Called from __init__."""
        # GPX folder watching state
        self._gpx_watcher = None
        self._watched_gpx_folder = None
        # Track already-imported files with bounded size to prevent memory growth
        self._imported_gpx_files = BoundedSet(max_size=self.MAX_GPX_IMPORT_HISTORY)

    def import_gpx_file(self, gpx_path: str):
        """
        Import a single GPX file as a layer.

        LIFE-SAFETY CRITICAL: Validates GPX file before import.

        Strategy: One layer per GPX file (all tracks in file consolidated).

        Args:
            gpx_path: Absolute path to GPX file

        Returns:
            Tuple of (layer, error_message). Layer is None if import failed.

        Qt5/Qt6 Compatible: Uses QGIS core APIs only.
        """
        from ...utils.gpx_utils import import_gpx_track

        # Initialize GPX support if needed
        if not hasattr(self, '_imported_gpx_files'):
            self._init_gpx_support()

        # Get or create GPX Tracks group
        gpx_group = self._get_or_create_gpx_tracks_group()

        # Import the GPX track
        layer, error = import_gpx_track(gpx_path, parent_group=gpx_group)

        if layer:
            # Track this file as imported
            self._imported_gpx_files.add(gpx_path)
            logger.info(f"Imported GPX file: {gpx_path}")
        else:
            logger.warning(f"Failed to import GPX file {gpx_path}: {error}")

        return layer, error

    def import_gpx_folder(self, folder_path: str):
        """
        Import all GPX files in a folder.

        LIFE-SAFETY CRITICAL: Limits number of files to prevent overload.

        Args:
            folder_path: Absolute path to folder containing GPX files

        Returns:
            Tuple of (imported_layers, error_messages)

        Qt5/Qt6 Compatible: Uses standard library and QGIS core APIs.
        """
        import os

        # Initialize GPX support if needed
        if not hasattr(self, '_imported_gpx_files'):
            self._init_gpx_support()

        if not os.path.isdir(folder_path):
            return [], [f"Not a valid directory: {folder_path}"]

        # Find all GPX files
        try:
            all_files = os.listdir(folder_path)
        except OSError as e:
            return [], [f"Cannot read directory: {e}"]

        gpx_files = [
            os.path.join(folder_path, f)
            for f in all_files
            if f.lower().endswith('.gpx')
        ]

        # Apply limit (defensive)
        if len(gpx_files) > self.MAX_GPX_FILES_PER_IMPORT:
            logger.warning(
                f"Folder contains {len(gpx_files)} GPX files, "
                f"limiting to {self.MAX_GPX_FILES_PER_IMPORT}"
            )
            gpx_files = gpx_files[:self.MAX_GPX_FILES_PER_IMPORT]

        # Import each file
        imported_layers = []
        errors = []

        for gpx_path in gpx_files:
            # Skip already-imported files
            if gpx_path in self._imported_gpx_files:
                logger.debug(f"Skipping already-imported GPX: {gpx_path}")
                continue

            layer, error = self.import_gpx_file(gpx_path)

            if layer:
                imported_layers.append(layer)
            else:
                errors.append(f"{os.path.basename(gpx_path)}: {error}")

        logger.info(
            f"Imported {len(imported_layers)} GPX files from folder: {folder_path}"
        )

        return imported_layers, errors

    def start_gpx_folder_watch(self, folder_path: str):
        """
        Start watching a folder for new GPX files.

        Uses Qt's QFileSystemWatcher for native event loop integration.
        New GPX files will be automatically imported when detected.

        LIFE-SAFETY CRITICAL: File watching is stopped cleanly on plugin unload.

        Args:
            folder_path: Absolute path to folder to watch

        Returns:
            Tuple of (success, error_message)

        Qt5/Qt6 Compatible: Uses QFileSystemWatcher from qgis.PyQt.
        """
        import os
        from qgis.PyQt.QtCore import QFileSystemWatcher

        # Initialize GPX support if needed
        if not hasattr(self, '_imported_gpx_files'):
            self._init_gpx_support()

        if not os.path.isdir(folder_path):
            return False, f"Not a valid directory: {folder_path}"

        # Stop any existing watch
        self.stop_gpx_folder_watch()

        # Create new watcher
        # Note: Pass None as parent since DrawingLayerManager is not a QObject.
        # Lifecycle is explicitly managed via stop_gpx_folder_watch() and deleteLater().
        self._gpx_watcher = QFileSystemWatcher(None)
        self._watched_gpx_folder = folder_path

        # Watch the directory (not individual files - more efficient)
        if not self._gpx_watcher.addPath(folder_path):
            error = f"Failed to watch folder: {folder_path}"
            logger.error(error)
            self._gpx_watcher = None
            self._watched_gpx_folder = None
            return False, error

        # Connect signal
        self._gpx_watcher.directoryChanged.connect(self._on_gpx_folder_changed)

        logger.info(f"Started watching GPX folder: {folder_path}")

        # Import existing GPX files in the folder (QFileSystemWatcher only triggers on changes)
        # This ensures files already present when watch starts are also imported.
        existing_layers, existing_errors = self.import_gpx_folder(folder_path)
        if existing_layers:
            logger.info(f"Imported {len(existing_layers)} existing GPX files from watched folder")
        if existing_errors:
            logger.warning(f"Some existing GPX files failed to import: {existing_errors}")

        return True, ""

    def stop_gpx_folder_watch(self):
        """
        Stop watching for new GPX files.

        Safe to call even if not currently watching.

        LIFE-SAFETY CRITICAL: Must be called during plugin unload.
        """
        if hasattr(self, '_gpx_watcher') and self._gpx_watcher:
            try:
                self._gpx_watcher.directoryChanged.disconnect(self._on_gpx_folder_changed)
            except (RuntimeError, TypeError):
                pass  # Already disconnected

            self._gpx_watcher.deleteLater()
            self._gpx_watcher = None
            self._watched_gpx_folder = None

            logger.info("Stopped GPX folder watching")

    def is_watching_gpx_folder(self) -> bool:
        """Check if currently watching a folder for GPX files."""
        return (hasattr(self, '_gpx_watcher') and self._gpx_watcher is not None 
                and hasattr(self, '_watched_gpx_folder') and self._watched_gpx_folder is not None)

    def get_watched_gpx_folder(self):
        """Get the currently watched folder path, or None if not watching."""
        return getattr(self, '_watched_gpx_folder', None)

    def _on_gpx_folder_changed(self, path: str):
        """
        Handle directory change events - detect and import new GPX files.

        THREAD-SAFETY: This is called on the main thread by Qt's event loop.
        Safe to call QGIS APIs directly.

        LIFECYCLE SAFETY: Guards against post-unload callback execution.
        LIFE-SAFETY CRITICAL: Errors are logged but do not crash the plugin.
        """
        import os

        # LIFECYCLE SAFETY: Check for plugin unload before any work
        layer_manager = getattr(self, 'layer_manager', None)
        if getattr(layer_manager, '_application_closing', False):
            logger.debug("GPX folder changed callback during shutdown - ignoring")
            return

        if not self._watched_gpx_folder:
            return

        try:
            # Find all GPX files in folder
            current_files = set()

            try:
                all_files = os.listdir(self._watched_gpx_folder)
                current_files = set(
                    os.path.join(self._watched_gpx_folder, f)
                    for f in all_files
                    if f.lower().endswith('.gpx')
                )
            except OSError as e:
                logger.error(f"Error scanning watched folder: {e}")
                return

            # Find new files
            # BoundedSet doesn't support set subtraction, so convert to regular set first
            new_files = current_files - set(self._imported_gpx_files)

            # Import new files
            for gpx_path in sorted(new_files):  # Sort for predictable order
                # Re-check shutdown state before each import (may be many files)
                if getattr(layer_manager, '_application_closing', False):
                    logger.debug("GPX import loop interrupted by shutdown")
                    return

                logger.info(f"New GPX file detected: {gpx_path}")

                layer, error = self.import_gpx_file(gpx_path)

                if layer:
                    # Notify user of successful import using safe_notify
                    from ...utils.notify import safe_notify, success as notify_success
                    bar = self.iface.messageBar() if self.iface else None
                    is_closing = getattr(layer_manager, '_application_closing', False)
                    safe_notify(
                        bar, notify_success,
                        "GPX Import",
                        f"Auto-imported: {os.path.basename(gpx_path)}",
                        duration=3,
                        is_unloading=is_closing,
                        log_prefix="[GPX-Watch]"
                    )
                else:
                    # Notify user of failure using safe_notify
                    from ...utils.notify import safe_notify, warning as notify_warning
                    bar = self.iface.messageBar() if self.iface else None
                    is_closing = getattr(layer_manager, '_application_closing', False)
                    safe_notify(
                        bar, notify_warning,
                        "GPX Import",
                        f"Failed to import: {os.path.basename(gpx_path)}",
                        duration=5,
                        is_unloading=is_closing,
                        log_prefix="[GPX-Watch]"
                    )

        except Exception as e:
            logger.error(f"Error in GPX folder watch handler: {e}", exc_info=True)

    def _get_or_create_gpx_tracks_group(self):
        """
        Get or create "GPX Tracks" layer group.

        Returns:
            QgsLayerTreeGroup for GPX layers
        """
        from qgis.core import QgsLayerTreeGroup as TreeGroup

        root = QgsProject.instance().layerTreeRoot()

        # Look for existing group
        for child in root.children():
            if isinstance(child, TreeGroup) and child.name() == self.GPX_TRACKS_GROUP_NAME:
                return child

        # Create new group at top
        gpx_group = root.insertGroup(0, self.GPX_TRACKS_GROUP_NAME)
        logger.info(f"Created GPX Tracks layer group")

        return gpx_group

    def cleanup(self):
        """
        Clean up resources including GPX folder watching.

        LIFE-SAFETY CRITICAL: Must be called during plugin unload.
        """
        # Stop GPX folder watching
        self.stop_gpx_folder_watch()

        # Clear imported files tracking
        if hasattr(self, '_imported_gpx_files'):
            self._imported_gpx_files.clear()

        # Clear cached per-item factory
        if hasattr(self, '_per_item_factory'):
            self._per_item_factory = None

        # IMPORTANT: Call parent cleanup to release base resources
        super().cleanup()
