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

from typing import List, Optional, Dict, Any
import math
import uuid
import logging
from datetime import datetime

# Set up logger for this module
logger = logging.getLogger(__name__)

from qgis.core import (
    QgsVectorLayer, QgsField, QgsFeature, QgsGeometry,
    QgsPointXY, QgsDistanceArea, QgsProject, QgsLineSymbol,
    QgsMarkerSymbol, QgsFeatureRequest, QgsWkbTypes
)
from qgis.PyQt.QtCore import QVariant
from qgis.core import NULL
from qgis.PyQt.QtGui import QColor

from .base_manager import BaseLayerManager
from ...layers import LayerIds
from ...utils.exceptions import LayerTransactionError, LayerLockError


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

    def __init__(self, iface, shared_device_colors=None, layer_manager=None):
        """Initialize drawing layer manager."""
        super().__init__(iface, shared_device_colors, layer_manager)

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

    def _style_lines_layer(self, layer: QgsVectorLayer):
        symbol = QgsLineSymbol.createSimple({'color': 'red', 'width': '2'})
        layer.renderer().setSymbol(symbol)

    def _style_search_areas_layer(self, layer: QgsVectorLayer):
        symbol = layer.renderer().symbol()
        symbol.setColor(QColor(0, 100, 255, 80))
        symbol.symbolLayer(0).setStrokeColor(QColor(0, 100, 255))
        symbol.symbolLayer(0).setStrokeWidth(2)

    def _style_range_rings_layer(self, layer: QgsVectorLayer):
        symbol = layer.renderer().symbol()
        symbol.setColor(QColor(255, 165, 0, 40))
        symbol.symbolLayer(0).setStrokeColor(QColor(255, 165, 0))
        symbol.symbolLayer(0).setStrokeWidth(1.5)

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
            self._ensure_lines_layer_schema(layer)
            self._log_drawing_event(layer, "LINES", "ensure")
            return layer

        layers = self.project.mapLayersByName(self.LINES_LAYER_NAME)
        if layers:
            layer = layers[0]
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
        return layer

    def add_line(self, name: str, points_wgs84: List[QgsPointXY],
                 description: str = "", color: str = "#FF0000", width: int = 2,
                 temporary_measure: bool = False) -> int:
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

        feature.setAttributes([
            str(uuid.uuid4()),
            name,
            description,
            color,
            width,
            total_distance,
            datetime.now().isoformat(),
            1 if temporary_measure else 0,
            None  # display_order (set after addFeature)
        ])

        # Add to layer with proper resource cleanup
        # CRITICAL: Check for nested transactions
        if layer.isEditable():
            raise LayerLockError(layer.name())

        layer.startEditing()
        try:
            layer.addFeature(feature)
            self._set_display_order(layer, feature.id())
            if not layer.commitChanges():
                errors = layer.commitErrors()
                raise RuntimeError(f"Failed to commit line feature: {', '.join(errors)}")
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

        layer.startEditing()
        try:
            layer.deleteFeatures(ids_to_delete)
            if not layer.commitChanges():
                errors = layer.commitErrors()
                raise RuntimeError(f"Failed to delete overlays: {', '.join(errors)}")
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
        self._log_drawing_event(layer, "LINES", "clear_overlays", deleted=len(ids_to_delete))
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
        layer = self._get_or_create_lines_layer()
        if not layer or not layer.isValid():
            return []

        request = QgsFeatureRequest()

        if filters:
            expressions = []
            for field_name, value in filters.items():
                if layer.fields().indexFromName(field_name) == -1:
                    logger.warning(f"Unknown filter field {field_name}")
                    continue
                if isinstance(value, str):
                    expressions.append(f'"{field_name}" = \'{value}\'')
                elif isinstance(value, (int, float)):
                    expressions.append(f'"{field_name}" = {value}')
                elif value is None:
                    expressions.append(f'"{field_name}" IS NULL')
            if expressions:
                request.setFilterExpression(' AND '.join(expressions))

        records = []
        try:
            for feature in layer.getFeatures(request):
                rec = self._feature_to_record(feature, layer)
                if rec:
                    records.append(rec)
        except Exception as exc:
            logger.error("Error listing lines: %s", exc, exc_info=True)
        return self._sort_records_by_display_order(records)

    def get_line(self, feature_id: int) -> Optional[Dict]:
        """Get a single line by feature id."""
        layer = self._get_or_create_lines_layer()
        if not layer or not layer.isValid():
            return None
        feature = layer.getFeature(feature_id)
        if not feature.isValid():
            return None
        return self._feature_to_record(feature, layer)

    def update_line(self, feature_id: int, updates: Dict[str, Any], updated_by: Optional[str] = None) -> bool:
        """Update attributes of a line feature."""
        if not isinstance(feature_id, int) or feature_id <= 0:
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

            # Apply updates
            for field_name, value in updates.items():
                field_index = layer.fields().indexFromName(field_name)
                if field_index == -1:
                    continue
                if not layer.changeAttributeValue(feature_id, field_index, value):
                    raise RuntimeError(f"Failed to update {field_name}")

            if not layer.commitChanges():
                errors = layer.commitErrors()
                raise RuntimeError(f"Commit failed: {', '.join(errors)}")

            layer.triggerRepaint()
            self._log_drawing_event(layer, "LINES", "update", feature_id=feature_id)
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

    def delete_line(self, feature_id: int, updated_by: Optional[str] = None) -> bool:
        """Delete a single line feature."""
        if not isinstance(feature_id, int) or feature_id <= 0:
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
            if not layer.commitChanges():
                errors = layer.commitErrors()
                raise RuntimeError(f"Commit failed: {', '.join(errors)}")

            layer.triggerRepaint()
            self._log_drawing_event(layer, "LINES", "delete", feature_id=feature_id)
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

    def delete_lines(self, feature_ids: List[int], updated_by: Optional[str] = None) -> int:
        """Bulk delete lines."""
        if not feature_ids:
            return 0

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

            if not layer.commitChanges():
                errors = layer.commitErrors()
                raise RuntimeError(f"Commit failed: {', '.join(errors)}")

            layer.triggerRepaint()
            self._log_drawing_event(layer, "LINES", "bulk_delete", deleted=deleted)
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
        if layer.fields().indexFromName("temporary_measure") != -1:
            return

        layer.startEditing()
        try:
            if not layer.addAttribute(QgsField("temporary_measure", QVariant.Bool)):
                raise RuntimeError("Failed to add temporary_measure field")
            if not layer.commitChanges():
                errors = layer.commitErrors()
                raise RuntimeError(f"Failed to commit schema update: {', '.join(errors)}")
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
            self._log_drawing_event(layer, "SEARCH_AREAS", "ensure")
            return layer

        layers = self.project.mapLayersByName(self.SEARCH_AREAS_LAYER_NAME)
        if layers:
            layer = layers[0]
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

        logger.debug(f"Search area '{name}': {len(polygon_wgs84)} points, area={area_sqkm:.4f}km²")

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
            datetime.now().isoformat(),
            None  # display_order (set after feature is added)
        ])

        # Add to layer with proper resource cleanup
        # CRITICAL: Check for nested transactions
        if layer.isEditable():
            raise LayerLockError(layer.name())

        layer.startEditing()
        try:
            layer.addFeature(feature)
            self._set_display_order(layer, feature.id())
            if not layer.commitChanges():
                errors = layer.commitErrors()
                raise RuntimeError(f"Failed to commit search area feature: {', '.join(errors)}")
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
            self._log_drawing_event(layer, "RANGE_RINGS", "ensure")
            return layer

        layers = self.project.mapLayersByName(self.RANGE_RINGS_LAYER_NAME)
        if layers:
            layer = layers[0]
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

        # Prevent division by zero at poles
        if denominator < 1e-10:
            # At poles, use polar radius
            earth_radius = b
            logger.debug(f"Range ring at pole (lat={center_wgs84.y():.6f}): using polar radius {earth_radius:.2f}m")
        else:
            earth_radius = math.sqrt(numerator / denominator)
            logger.debug(f"Range ring: lat={center_wgs84.y():.6f}, radius_m={radius_m:.2f}, earth_radius={earth_radius:.2f}m")

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
            # Clamp the argument to [-1, 1] to prevent domain errors from floating point rounding
            sin_lat2 = (math.sin(lat_rad) * math.cos(angular_distance) +
                       math.cos(lat_rad) * math.sin(angular_distance) * math.cos(bearing_rad))
            sin_lat2 = max(-1.0, min(1.0, sin_lat2))  # Clamp to valid range
            lat2 = math.asin(sin_lat2)

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
            datetime.now().isoformat(),
            None  # display_order (set after addFeature)
        ])

        # Add to layer with proper resource cleanup
        # CRITICAL: Check for nested transactions
        if layer.isEditable():
            raise LayerLockError(layer.name())

        layer.startEditing()
        try:
            layer.addFeature(feature)
            self._set_display_order(layer, feature.id())
            if not layer.commitChanges():
                errors = layer.commitErrors()
                raise RuntimeError(f"Failed to commit range ring feature: {', '.join(errors)}")
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
            self._log_drawing_event(layer, "BEARING_LINES", "ensure")
            return layer

        layers = self.project.mapLayersByName(self.BEARING_LINES_LAYER_NAME)
        if layers:
            layer = layers[0]
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

        # Prevent division by zero at poles
        if denominator < 1e-10:
            # At poles, use polar radius
            earth_radius = b
            logger.debug(f"Bearing line at pole (lat={origin_wgs84.y():.6f}): using polar radius {earth_radius:.2f}m")
        else:
            earth_radius = math.sqrt(numerator / denominator)
            logger.debug(f"Bearing line: lat={origin_wgs84.y():.6f}, bearing={bearing:.1f}°, distance={distance_m:.2f}m, earth_radius={earth_radius:.2f}m")

        # Angular distance
        angular_dist = distance_m / earth_radius

        # Clamp the argument to [-1, 1] to prevent domain errors from floating point rounding
        sin_lat2 = (math.sin(lat1) * math.cos(angular_dist) +
                   math.cos(lat1) * math.sin(angular_dist) * math.cos(bearing_rad))
        sin_lat2 = max(-1.0, min(1.0, sin_lat2))  # Clamp to valid range
        lat2 = math.asin(sin_lat2)

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
            datetime.now().isoformat(),
            None  # display_order (set after addFeature)
        ])

        # Add to layer with proper resource cleanup
        # CRITICAL: Check for nested transactions
        if layer.isEditable():
            raise LayerLockError(layer.name())

        layer.startEditing()
        try:
            layer.addFeature(feature)
            self._set_display_order(layer, feature.id())
            if not layer.commitChanges():
                errors = layer.commitErrors()
                raise RuntimeError(f"Failed to commit bearing line feature: {', '.join(errors)}")
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
            self._log_drawing_event(layer, "SECTORS", "ensure")
            return layer

        layers = self.project.mapLayersByName(self.SECTORS_LAYER_NAME)
        if layers:
            layer = layers[0]
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

        # Create sector geometry using proper WGS84 ellipsoid calculations
        # Create arc with 36 segments
        num_segments = 36
        angle_range = end_bearing - start_bearing
        if angle_range < 0:
            angle_range += 360

        # WGS84 ellipsoid parameters (same as range rings and bearing lines)
        a = 6378137.0  # Semi-major axis (equatorial radius) in meters
        f = 1 / 298.257223563  # Flattening
        b = a * (1 - f)  # Semi-minor axis (polar radius)

        # Calculate Earth radius at center latitude
        lat1 = math.radians(center_wgs84.y())
        lon1 = math.radians(center_wgs84.x())
        cos_lat = math.cos(lat1)
        sin_lat = math.sin(lat1)

        numerator = (a * a * cos_lat)**2 + (b * b * sin_lat)**2
        denominator = (a * cos_lat)**2 + (b * sin_lat)**2

        # Prevent division by zero at poles
        if denominator < 1e-10:
            earth_radius = b
        else:
            earth_radius = math.sqrt(numerator / denominator)

        angular_dist = radius_m / earth_radius

        points = [center_wgs84]  # Start from center

        for i in range(num_segments + 1):
            angle = start_bearing + (angle_range * i / num_segments)
            angle_rad = math.radians(angle)

            # Calculate point using WGS84 ellipsoid
            # Clamp the argument to [-1, 1] to prevent domain errors from floating point rounding
            sin_lat2 = (math.sin(lat1) * math.cos(angular_dist) +
                       math.cos(lat1) * math.sin(angular_dist) * math.cos(angle_rad))
            sin_lat2 = max(-1.0, min(1.0, sin_lat2))  # Clamp to valid range
            lat2 = math.asin(sin_lat2)

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

        logger.debug(f"Sector '{name}': bearings {start_bearing:.1f}°-{end_bearing:.1f}°, radius={radius_m:.2f}m, area={area_sqkm:.4f}km²")

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
            datetime.now().isoformat(),
            None  # display_order (set after addFeature)
        ])

        # Add to layer with proper resource cleanup
        # CRITICAL: Check for nested transactions
        if layer.isEditable():
            raise LayerLockError(layer.name())

        layer.startEditing()
        try:
            layer.addFeature(feature)
            self._set_display_order(layer, feature.id())
            if not layer.commitChanges():
                errors = layer.commitErrors()
                raise RuntimeError(f"Failed to commit sector feature: {', '.join(errors)}")
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

    # -------------------------------------------------------------------------
    # Sectors - Full CRUD (Phase 2)
    # -------------------------------------------------------------------------

    def list_sectors(self, filters: Optional[Dict] = None) -> List[Dict]:
        """List all search sector features."""
        layer = self._get_or_create_sectors_layer()
        if not layer or not layer.isValid():
            return []

        request = QgsFeatureRequest()
        if filters:
            expressions = []
            for field_name, value in filters.items():
                if layer.fields().indexFromName(field_name) == -1:
                    logger.warning(f"Unknown filter field {field_name}")
                    continue
                if isinstance(value, str):
                    expressions.append(f'"{field_name}" = \'{value}\'')
                elif isinstance(value, (int, float)):
                    expressions.append(f'"{field_name}" = {value}')
                elif value is None:
                    expressions.append(f'"{field_name}" IS NULL')
            if expressions:
                request.setFilterExpression(' AND '.join(expressions))

        records = []
        try:
            for feature in layer.getFeatures(request):
                rec = self._feature_to_record(feature, layer)
                if rec:
                    records.append(rec)
        except Exception as exc:
            logger.error("Error listing sectors: %s", exc, exc_info=True)
        return self._sort_records_by_display_order(records)

    def get_sector(self, feature_id: int) -> Optional[Dict]:
        """Get a single search sector by feature id."""
        layer = self._get_or_create_sectors_layer()
        if not layer or not layer.isValid():
            return None
        feature = layer.getFeature(feature_id)
        if not feature.isValid():
            return None
        return self._feature_to_record(feature, layer)

    def update_sector(self, feature_id: int, updates: Dict[str, Any], updated_by: Optional[str] = None) -> bool:
        """Update a search sector feature."""
        if not isinstance(feature_id, int) or feature_id <= 0:
            raise ValueError(f"Invalid feature_id: {feature_id}")
        if not isinstance(updates, dict) or not updates:
            raise ValueError("updates must be a non-empty dictionary")

        layer = self._get_or_create_sectors_layer()
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

            for field_name, value in updates.items():
                field_index = layer.fields().indexFromName(field_name)
                if field_index == -1:
                    continue
                if not layer.changeAttributeValue(feature_id, field_index, value):
                    raise RuntimeError(f"Failed to update {field_name}")

            if not layer.commitChanges():
                errors = layer.commitErrors()
                raise RuntimeError(f"Commit failed: {', '.join(errors)}")

            layer.triggerRepaint()
            self._log_drawing_event(layer, "SECTORS", "update", feature_id=feature_id)
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

    def delete_sector(self, feature_id: int, updated_by: Optional[str] = None) -> bool:
        """Delete a single search sector."""
        if not isinstance(feature_id, int) or feature_id <= 0:
            raise ValueError(f"Invalid feature_id: {feature_id}")

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

            if not layer.commitChanges():
                errors = layer.commitErrors()
                raise RuntimeError(f"Commit failed: {', '.join(errors)}")

            layer.triggerRepaint()
            self._log_drawing_event(layer, "SECTORS", "delete", feature_id=feature_id)
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

    def delete_sectors(self, feature_ids: List[int], updated_by: Optional[str] = None) -> int:
        """Bulk delete search sectors."""
        if not feature_ids:
            return 0

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
            deleted = 0
            for fid in feature_ids:
                if layer.deleteFeature(fid):
                    deleted += 1

            if not layer.commitChanges():
                errors = layer.commitErrors()
                raise RuntimeError(f"Commit failed: {', '.join(errors)}")

            layer.triggerRepaint()
            self._log_drawing_event(layer, "SECTORS", "bulk_delete", deleted=deleted)
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
            self._log_drawing_event(layer, "TEXT_LABELS", "ensure")
            return layer

        layers = self.project.mapLayersByName(self.TEXT_LABELS_LAYER_NAME)
        if layers:
            layer = layers[0]
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
            datetime.now().isoformat(),
            None  # display_order (set after addFeature)
        ])

        # Add to layer with proper resource cleanup
        # CRITICAL: Check for nested transactions
        if layer.isEditable():
            raise LayerLockError(layer.name())

        layer.startEditing()
        try:
            layer.addFeature(feature)
            self._set_display_order(layer, feature.id())
            if not layer.commitChanges():
                errors = layer.commitErrors()
                raise RuntimeError(f"Failed to commit text label feature: {', '.join(errors)}")
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
        layer = self._get_or_create_search_areas_layer()
        if not layer or not layer.isValid():
            return []

        # Build feature request
        request = QgsFeatureRequest()

        # Apply filters if provided
        if filters:
            expressions = []
            for field_name, value in filters.items():
                # Validate field exists
                if layer.fields().indexFromName(field_name) == -1:
                    logger.warning(f"Unknown filter field {field_name}")
                    continue

                # Build expression based on value type
                if isinstance(value, str):
                    expressions.append(f'"{field_name}" = \'{value}\'')
                elif isinstance(value, (int, float)):
                    expressions.append(f'"{field_name}" = {value}')
                elif value is None:
                    expressions.append(f'"{field_name}" IS NULL')

            if expressions:
                filter_expr = ' AND '.join(expressions)
                request.setFilterExpression(filter_expr)

        # Fetch and serialize features
        records = []
        try:
            for feature in layer.getFeatures(request):
                record = self._feature_to_record(feature, layer)
                if record:
                    records.append(record)
        except Exception as e:
            logger.error(f"Error listing search areas: {e}", exc_info=True)

        return self._sort_records_by_display_order(records)

    def get_search_area(self, feature_id: int) -> Optional[Dict]:
        """
        Get single search area by feature ID.

        Args:
            feature_id: Feature ID to retrieve

        Returns:
            Feature dictionary or None if not found
        """
        layer = self._get_or_create_search_areas_layer()
        if not layer or not layer.isValid():
            return None

        feature = layer.getFeature(feature_id)
        if not feature.isValid():
            return None

        return self._feature_to_record(feature, layer)

    def update_search_area(
        self,
        feature_id: int,
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

        if not isinstance(feature_id, int) or feature_id <= 0:
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
            # ====================================================================
            # STEP 5: APPLY UPDATES
            # ====================================================================

            # Add audit trail if updated_by provided
            if updated_by:
                updates['updated_by'] = updated_by
                updates['updated_at'] = datetime.now().isoformat()

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

            if not layer.commitChanges():
                errors = layer.commitErrors()
                raise RuntimeError(f"Commit failed for {layer.name()}: {', '.join(errors)}")

            # ====================================================================
            # STEP 7: POST-COMMIT ACTIONS
            # ====================================================================

            layer.triggerRepaint()
            self._log_drawing_event(layer, "SEARCH_AREAS", "update", feature_id=feature_id, updates=updates)
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

    def delete_search_area(
        self,
        feature_id: int,
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
        if not isinstance(feature_id, int) or feature_id <= 0:
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

            if not layer.commitChanges():
                errors = layer.commitErrors()
                raise RuntimeError(f"Commit failed: {', '.join(errors)}")

            layer.triggerRepaint()
            self._log_drawing_event(layer, "SEARCH_AREAS", "delete", feature_id=feature_id)
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

    def delete_search_areas(
        self,
        feature_ids: List[int],
        updated_by: Optional[str] = None
    ) -> int:
        """
        Bulk delete search areas.

        Args:
            feature_ids: List of feature IDs to delete
            updated_by: Coordinator name for audit trail

        Returns:
            Number of features deleted

        Raises:
            ValueError: If feature_ids empty
            LayerTransactionError: If deletion fails
        """
        if not feature_ids:
            return 0

        layer = self._get_or_create_search_areas_layer()
        if not layer or not layer.isValid():
            raise RuntimeError("Search areas layer not available")

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

            if not layer.commitChanges():
                errors = layer.commitErrors()
                raise RuntimeError(f"Commit failed: {', '.join(errors)}")

            layer.triggerRepaint()
            self._log_drawing_event(layer, "SEARCH_AREAS", "bulk_delete", deleted=deleted)
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
        layer = self._get_or_create_range_rings_layer()
        if not layer or not layer.isValid():
            return []

        request = QgsFeatureRequest()

        # Apply filters if provided
        if filters:
            expressions = []
            for field_name, value in filters.items():
                if layer.fields().indexFromName(field_name) == -1:
                    logger.warning(f"Unknown filter field {field_name}")
                    continue

                if isinstance(value, str):
                    expressions.append(f'"{field_name}" = \'{value}\'')
                elif isinstance(value, (int, float)):
                    expressions.append(f'"{field_name}" = {value}')
                elif value is None:
                    expressions.append(f'"{field_name}" IS NULL')

            if expressions:
                filter_expr = ' AND '.join(expressions)
                request.setFilterExpression(filter_expr)

        records = []
        try:
            for feature in layer.getFeatures(request):
                record = self._feature_to_record(feature, layer)
                if record:
                    records.append(record)
        except Exception as e:
            logger.error(f"Error listing range rings: {e}", exc_info=True)

        return self._sort_records_by_display_order(records)

    def get_range_ring(self, feature_id: int) -> Optional[Dict]:
        """
        Get single range ring by feature ID.

        Args:
            feature_id: Feature ID to retrieve

        Returns:
            Feature dictionary or None if not found
        """
        layer = self._get_or_create_range_rings_layer()
        if not layer or not layer.isValid():
            return None

        feature = layer.getFeature(feature_id)
        if not feature.isValid():
            return None

        return self._feature_to_record(feature, layer)

    def update_range_ring(
        self,
        feature_id: int,
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
        if not isinstance(feature_id, int) or feature_id <= 0:
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
                updates['updated_at'] = datetime.now().isoformat()

            for field_name, value in updates.items():
                field_index = layer.fields().indexFromName(field_name)
                if field_index == -1:
                    continue

                success = layer.changeAttributeValue(feature_id, field_index, value)
                if not success:
                    raise RuntimeError(f"Failed to update {field_name}")

            if not layer.commitChanges():
                errors = layer.commitErrors()
                raise RuntimeError(f"Commit failed: {', '.join(errors)}")

            layer.triggerRepaint()
            self._log_drawing_event(layer, "RANGE_RINGS", "update", feature_id=feature_id)
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

    def delete_range_ring(
        self,
        feature_id: int,
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
        if not isinstance(feature_id, int) or feature_id <= 0:
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

            if not layer.commitChanges():
                errors = layer.commitErrors()
                raise RuntimeError(f"Commit failed: {', '.join(errors)}")

            layer.triggerRepaint()
            self._log_drawing_event(layer, "RANGE_RINGS", "delete", feature_id=feature_id)
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

            if not layer.commitChanges():
                errors = layer.commitErrors()
                raise RuntimeError(f"Commit failed: {', '.join(errors)}")

            layer.triggerRepaint()
            self._log_drawing_event(layer, "RANGE_RINGS", "bulk_delete", deleted=deleted)
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
        layer = self._get_or_create_bearing_lines_layer()
        if not layer or not layer.isValid():
            return []

        request = QgsFeatureRequest()

        if filters:
            expressions = []
            for field_name, value in filters.items():
                if layer.fields().indexFromName(field_name) == -1:
                    logger.warning(f"Unknown filter field {field_name}")
                    continue

                if isinstance(value, str):
                    expressions.append(f'"{field_name}" = \'{value}\'')
                elif isinstance(value, (int, float)):
                    expressions.append(f'"{field_name}" = {value}')
                elif value is None:
                    expressions.append(f'"{field_name}" IS NULL')

            if expressions:
                filter_expr = ' AND '.join(expressions)
                request.setFilterExpression(filter_expr)

        records = []
        try:
            for feature in layer.getFeatures(request):
                record = self._feature_to_record(feature, layer)
                if record:
                    records.append(record)
        except Exception as e:
            logger.error(f"Error listing bearing lines: {e}", exc_info=True)

        return self._sort_records_by_display_order(records)

    def get_bearing_line(self, feature_id: int) -> Optional[Dict]:
        """
        Get single bearing line by feature ID.

        Args:
            feature_id: Feature ID to retrieve

        Returns:
            Feature dictionary or None if not found
        """
        layer = self._get_or_create_bearing_lines_layer()
        if not layer or not layer.isValid():
            return None

        feature = layer.getFeature(feature_id)
        if not feature.isValid():
            return None

        return self._feature_to_record(feature, layer)

    def update_bearing_line(
        self,
        feature_id: int,
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
        if not isinstance(feature_id, int) or feature_id <= 0:
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
                updates['updated_at'] = datetime.now().isoformat()

            for field_name, value in updates.items():
                field_index = layer.fields().indexFromName(field_name)
                if field_index == -1:
                    continue

                success = layer.changeAttributeValue(feature_id, field_index, value)
                if not success:
                    raise RuntimeError(f"Failed to update {field_name}")

            if not layer.commitChanges():
                errors = layer.commitErrors()
                raise RuntimeError(f"Commit failed: {', '.join(errors)}")

            layer.triggerRepaint()
            self._log_drawing_event(layer, "BEARING_LINES", "update", feature_id=feature_id)
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

    def delete_bearing_line(
        self,
        feature_id: int,
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
        if not isinstance(feature_id, int) or feature_id <= 0:
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

            if not layer.commitChanges():
                errors = layer.commitErrors()
                raise RuntimeError(f"Commit failed: {', '.join(errors)}")

            layer.triggerRepaint()
            self._log_drawing_event(layer, "BEARING_LINES", "delete", feature_id=feature_id)
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

            if not layer.commitChanges():
                errors = layer.commitErrors()
                raise RuntimeError(f"Commit failed: {', '.join(errors)}")

            layer.triggerRepaint()
            self._log_drawing_event(layer, "BEARING_LINES", "bulk_delete", deleted=deleted)
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
        layer = self._get_or_create_text_labels_layer()
        if not layer or not layer.isValid():
            return []

        request = QgsFeatureRequest()

        if filters:
            expressions = []
            for field_name, value in filters.items():
                if layer.fields().indexFromName(field_name) == -1:
                    logger.warning(f"Unknown filter field {field_name}")
                    continue

                if isinstance(value, str):
                    expressions.append(f'"{field_name}" = \'{value}\'')
                elif isinstance(value, (int, float)):
                    expressions.append(f'"{field_name}" = {value}')
                elif value is None:
                    expressions.append(f'"{field_name}" IS NULL')

            if expressions:
                filter_expr = ' AND '.join(expressions)
                request.setFilterExpression(filter_expr)

        records = []
        try:
            for feature in layer.getFeatures(request):
                record = self._feature_to_record(feature, layer)
                if record:
                    records.append(record)
        except Exception as e:
            logger.error(f"Error listing text labels: {e}", exc_info=True)

        return self._sort_records_by_display_order(records)

    def get_text_label(self, feature_id: int) -> Optional[Dict]:
        """
        Get single text label by feature ID.

        Args:
            feature_id: Feature ID to retrieve

        Returns:
            Feature dictionary or None if not found
        """
        layer = self._get_or_create_text_labels_layer()
        if not layer or not layer.isValid():
            return None

        feature = layer.getFeature(feature_id)
        if not feature.isValid():
            return None

        return self._feature_to_record(feature, layer)

    def update_text_label(
        self,
        feature_id: int,
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
        if not isinstance(feature_id, int) or feature_id <= 0:
            raise ValueError(f"Invalid feature_id: {feature_id}")

        if not isinstance(updates, dict) or not updates:
            raise ValueError("updates must be a non-empty dictionary")

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
                updates['updated_at'] = datetime.now().isoformat()

            for field_name, value in updates.items():
                field_index = layer.fields().indexFromName(field_name)
                if field_index == -1:
                    continue

                success = layer.changeAttributeValue(feature_id, field_index, value)
                if not success:
                    raise RuntimeError(f"Failed to update {field_name}")

            if not layer.commitChanges():
                errors = layer.commitErrors()
                raise RuntimeError(f"Commit failed: {', '.join(errors)}")

            layer.triggerRepaint()
            self._log_drawing_event(layer, "TEXT_LABELS", "update", feature_id=feature_id)
            logger.debug(f"Updated text label {feature_id}")

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

    def delete_text_label(
        self,
        feature_id: int,
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
        if not isinstance(feature_id, int) or feature_id <= 0:
            raise ValueError(f"Invalid feature_id: {feature_id}")

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

            if not layer.commitChanges():
                errors = layer.commitErrors()
                raise RuntimeError(f"Commit failed: {', '.join(errors)}")

            layer.triggerRepaint()
            self._log_drawing_event(layer, "TEXT_LABELS", "delete", feature_id=feature_id)
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

    def delete_text_labels(
        self,
        feature_ids: List[int],
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
            deleted = 0
            for feature_id in feature_ids:
                if layer.deleteFeature(feature_id):
                    deleted += 1

            if not layer.commitChanges():
                errors = layer.commitErrors()
                raise RuntimeError(f"Commit failed: {', '.join(errors)}")

            layer.triggerRepaint()
            self._log_drawing_event(layer, "TEXT_LABELS", "bulk_delete", deleted=deleted)
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
