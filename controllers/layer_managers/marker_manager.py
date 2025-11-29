# -*- coding: utf-8 -*-
"""
Marker Layer Manager

Manages SAR marker point layers: IPP/LKP, Clues, and Hazards.
Each marker type has its own layer with appropriate fields and styling.

Qt5/Qt6 Compatible: Uses qgis.PyQt for all imports.
"""

from datetime import datetime
import uuid
from typing import Dict, List, Optional

from qgis.core import (
    QgsVectorLayer, QgsFeature, QgsGeometry,
    QgsPointXY, QgsMarkerSymbol, QgsPalLayerSettings,
    QgsVectorLayerSimpleLabeling, QgsTextFormat, QgsTextBufferSettings,
    QgsFeatureRequest
)
from qgis.PyQt.QtGui import QColor

from .base_manager import BaseLayerManager
from ...layers import LayerIds
from ...utils.exceptions import LayerTransactionError


class MarkerLayerManager(BaseLayerManager):
    """
    Manages marker layers for SAR operations.

    Handles four distinct marker types:
    - IPP/LKP: Initial Planning Point / Last Known Position
    - Clues: Evidence found during search
    - Hazards: Safety-critical warnings
    - Casualties: Found injured or deceased persons

    Each type has its own layer with specific fields and styling.
    """

    # Layer names
    IPP_LKP_LAYER_NAME = "IPP/LKP"
    CLUES_LAYER_NAME = "Clues"
    HAZARDS_LAYER_NAME = "Hazards"
    CASUALTIES_LAYER_NAME = "Casualties"

    MARKER_TYPE_MAP = {
        "ipp_lkp": {
            "layer_id": LayerIds.MARKERS_IPP_LKP,
            "fallback": IPP_LKP_LAYER_NAME,
            "style_fn": "_style_ipp_lkp_layer"
        },
        "clue": {
            "layer_id": LayerIds.MARKERS_CLUES,
            "fallback": CLUES_LAYER_NAME,
            "style_fn": "_style_clues_layer"
        },
        "hazard": {
            "layer_id": LayerIds.MARKERS_HAZARDS,
            "fallback": HAZARDS_LAYER_NAME,
            "style_fn": "_style_hazards_layer"
        },
        "casualty": {
            "layer_id": LayerIds.MARKERS_CASUALTIES,
            "fallback": CASUALTIES_LAYER_NAME,
            "style_fn": "_style_casualties_layer"
        }
    }

    def __init__(self, iface, shared_device_colors=None, layer_manager=None):
        """Initialize marker layer manager."""
        super().__init__(iface, shared_device_colors, layer_manager)
        self._invalid_layer_warnings = set()

    def get_managed_layer_names(self):
        """Return list of layer names this manager handles."""
        return [
            self.IPP_LKP_LAYER_NAME,
            self.CLUES_LAYER_NAME,
            self.HAZARDS_LAYER_NAME,
            self.CASUALTIES_LAYER_NAME
        ]

    # ---------------------------------------------------------------------
    # Internal helpers
    # ---------------------------------------------------------------------

    def _log_marker_event(self, layer: QgsVectorLayer, marker_type: str, action: str, **extra):
        """Proxy to BaseLayerManager diagnostics helper."""
        payload = extra if extra else None
        self._log_layer_snapshot(layer, f"{marker_type}::{action}", payload)

    def _current_timestamp(self) -> str:
        """Return ISO timestamp for audit fields."""
        return datetime.utcnow().isoformat()

    def _get_marker_layer(self, marker_type: str) -> QgsVectorLayer:
        """Return persistent layer for a marker type."""
        meta = self.MARKER_TYPE_MAP.get(marker_type)
        if not meta:
            raise ValueError(f"Unknown marker type: {marker_type}")
        style_factory = getattr(self, meta["style_fn"])
        return self._ensure_schema_layer(
            meta["layer_id"],
            fallback_name=meta["fallback"],
            style_factory=style_factory
        )

    def _marker_log_label(self, marker_type: str) -> str:
        """Return standardized label used in diagnostics."""
        meta = self.MARKER_TYPE_MAP.get(marker_type, {})
        fallback = meta.get("fallback", marker_type)
        return fallback.replace(" ", "_").replace("/", "_").upper()

    def _marker_type_for_layer(self, layer_id: str) -> Optional[str]:
        """Reverse lookup marker type from layer id."""
        for marker_type, meta in self.MARKER_TYPE_MAP.items():
            if meta["layer_id"] == layer_id:
                return marker_type
        return None

    def _apply_feature_attributes(self, layer: QgsVectorLayer, feature: QgsFeature, data: Dict[str, object]):
        """Set feature attributes by field name safely."""
        fields = layer.fields()
        for key, value in data.items():
            idx = fields.indexOf(key)
            if idx == -1:
                continue
            feature.setAttribute(idx, value)

    def _build_audit_attributes(
        self,
        *,
        include_created: bool = True,
        updated_by: Optional[str] = None,
        coordinator_ids: Optional[str] = None,
        attachment_path: Optional[str] = None
    ) -> Dict[str, object]:
        """Return audit metadata payload for marker rows."""
        timestamp = self._current_timestamp()
        data: Dict[str, object] = {
            "updated_at": timestamp,
            "updated_by": (updated_by or "").strip(),
            "coordinator_ids": (coordinator_ids or "").strip(),
            "attachment_path": (attachment_path or "").strip()
        }
        if include_created:
            data["created_at"] = timestamp
        return data

    def _feature_request_for_marker(self, marker_id: str) -> QgsFeatureRequest:
        """Build feature request filtering by marker UUID."""
        safe_id = marker_id.replace("'", "''")
        return QgsFeatureRequest().setFilterExpression(f"\"id\" = '{safe_id}'")

    def _get_feature_by_id(self, layer: QgsVectorLayer, marker_id: str) -> Optional[QgsFeature]:
        """Return first feature that matches marker id."""
        request = self._feature_request_for_marker(marker_id)
        for feature in layer.getFeatures(request):
            return feature
        return None

    def _style_ipp_lkp_layer(self, layer: QgsVectorLayer):
        symbol = QgsMarkerSymbol.createSimple({
            'name': 'star',
            'color': '#0066FF',
            'size': '7',
            'outline_color': 'black',
            'outline_width': '0.5'
        })
        layer.renderer().setSymbol(symbol)
        self._apply_marker_labels(layer, QColor('#0066FF'))

    def _style_clues_layer(self, layer: QgsVectorLayer):
        symbol = QgsMarkerSymbol.createSimple({
            'name': 'triangle',
            'color': '#FFD700',
            'size': '6',
            'outline_color': 'black',
            'outline_width': '0.5'
        })
        layer.renderer().setSymbol(symbol)
        self._apply_marker_labels(layer, QColor('#806600'))

    def _style_hazards_layer(self, layer: QgsVectorLayer):
        symbol = QgsMarkerSymbol.createSimple({
            'name': 'filled_arrowhead',
            'color': '#FF0000',
            'size': '7',
            'outline_color': 'black',
            'outline_width': '0.5',
            'angle': '180'
        })
        layer.renderer().setSymbol(symbol)
        self._apply_marker_labels(layer, QColor('#8B0000'))

    def _style_casualties_layer(self, layer: QgsVectorLayer):
        symbol = QgsMarkerSymbol.createSimple({
            'name': 'cross2',
            'color': '#DC143C',
            'size': '8',
            'outline_color': 'black',
            'outline_width': '0.8'
        })
        layer.renderer().setSymbol(symbol)
        self._apply_marker_labels(layer, QColor('#8B0000'))

    # =========================================================================
    # IPP/LKP Layer (Initial Planning Point / Last Known Position)
    # =========================================================================

    def _get_or_create_ipp_lkp_layer(self) -> QgsVectorLayer:
        """
        Get or create IPP/LKP layer.

        IPP (Initial Planning Point) or LKP (Last Known Position) is the
        starting point for search planning - where the subject was last
        reliably seen or located.

        Returns:
            QgsVectorLayer: IPP/LKP layer
        """
        layer = self._get_marker_layer("ipp_lkp")
        self._log_marker_event(layer, self._marker_log_label("ipp_lkp"), "ensure")
        return layer

    def add_ipp_lkp(self, name: str, lat: float, lon: float,
                    subject_category: str = "", description: str = "",
                    irish_grid_e: float = None, irish_grid_n: float = None,
                    coordinator_ids: Optional[str] = None,
                    updated_by: Optional[str] = None,
                    attachment_path: Optional[str] = None) -> str:
        """
        Add an IPP/LKP marker to the map.

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
        # Validate name (required)
        if not name or not name.strip():
            raise ValueError("Marker name cannot be empty")

        # Validate coordinate types first
        if not isinstance(lat, (int, float)):
            raise TypeError(f"Latitude must be a number, got {type(lat).__name__}")
        if not isinstance(lon, (int, float)):
            raise TypeError(f"Longitude must be a number, got {type(lon).__name__}")

        # Validate coordinate ranges
        if not (-90 <= lat <= 90):
            raise ValueError(f"Invalid latitude: {lat}. Must be between -90 and 90")

        if not (-180 <= lon <= 180):
            raise ValueError(f"Invalid longitude: {lon}. Must be between -180 and 180")

        # Validate optional Irish Grid coordinates if provided
        if irish_grid_e is not None:
            if not isinstance(irish_grid_e, (int, float)):
                raise TypeError(f"Irish Grid easting must be a number, got {type(irish_grid_e).__name__}")
            if not (0 <= irish_grid_e <= 1000000):
                raise ValueError(f"Invalid Irish Grid easting: {irish_grid_e}. Must be between 0 and 1,000,000")

        if irish_grid_n is not None:
            if not isinstance(irish_grid_n, (int, float)):
                raise TypeError(f"Irish Grid northing must be a number, got {type(irish_grid_n).__name__}")
            if not (0 <= irish_grid_n <= 1500000):
                raise ValueError(f"Invalid Irish Grid northing: {irish_grid_n}. Must be between 0 and 1,500,000")

        layer = self._get_or_create_ipp_lkp_layer()

        # Create feature
        feature = QgsFeature(layer.fields())
        feature.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(lon, lat)))

        # Generate UUID
        marker_id = str(uuid.uuid4())

        created_ts = datetime.now().isoformat()
        attributes = {
            "id": marker_id,
            "name": name,
            "subject_category": subject_category,
            "description": description,
            "lat": lat,
            "lon": lon,
            "irish_grid_e": irish_grid_e,
            "irish_grid_n": irish_grid_n,
            "created": created_ts
        }
        attributes.update(self._build_audit_attributes(
            include_created=True,
            updated_by=updated_by,
            coordinator_ids=coordinator_ids,
            attachment_path=attachment_path
        ))
        self._apply_feature_attributes(layer, feature, attributes)

        # Add to layer with error handling
        try:
            if not layer.startEditing():
                raise RuntimeError(f"Failed to start editing {self.IPP_LKP_LAYER_NAME} layer - layer may be locked or read-only")

            if not layer.addFeature(feature):
                layer.rollBack()
                raise RuntimeError(f"Failed to add feature to {self.IPP_LKP_LAYER_NAME} layer")

            if not layer.commitChanges():
                errors = layer.commitErrors()
                raise RuntimeError(f"Failed to commit changes to {self.IPP_LKP_LAYER_NAME} layer: {', '.join(errors)}")

            # Force immediate visual update
            layer.triggerRepaint()

            self._log_marker_event(layer, self._marker_log_label("ipp_lkp"), "add", marker_id=marker_id, name=name)
            return marker_id

        except Exception as e:
            # Ensure layer is not left in editing state
            if layer.isEditable():
                layer.rollBack()
            raise LayerTransactionError(
                self.IPP_LKP_LAYER_NAME,
                "add marker",
                details=str(e)
            )

    # =========================================================================
    # Clues Layer (Evidence found during search)
    # =========================================================================

    def _get_or_create_clues_layer(self) -> QgsVectorLayer:
        """
        Get or create Clues layer.

        Clues are evidence or signs found during search operations:
        footprints, clothing, equipment, witness sightings, etc.

        Returns:
            QgsVectorLayer: Clues layer
        """
        layer = self._get_marker_layer("clue")
        self._log_marker_event(layer, self._marker_log_label("clue"), "ensure")
        return layer

    def add_clue(self, name: str, lat: float, lon: float,
                 clue_type: str = "", confidence: str = "Possible",
                 description: str = "",
                 irish_grid_e: float = None, irish_grid_n: float = None,
                 coordinator_ids: Optional[str] = None,
                 updated_by: Optional[str] = None,
                 attachment_path: Optional[str] = None) -> str:
        """
        Add a clue marker to the map.

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
        # Validate name (required)
        if not name or not name.strip():
            raise ValueError("Marker name cannot be empty")

        # Validate coordinate types first
        if not isinstance(lat, (int, float)):
            raise TypeError(f"Latitude must be a number, got {type(lat).__name__}")
        if not isinstance(lon, (int, float)):
            raise TypeError(f"Longitude must be a number, got {type(lon).__name__}")

        # Validate coordinate ranges
        if not (-90 <= lat <= 90):
            raise ValueError(f"Invalid latitude: {lat}. Must be between -90 and 90")

        if not (-180 <= lon <= 180):
            raise ValueError(f"Invalid longitude: {lon}. Must be between -180 and 180")

        # Validate optional Irish Grid coordinates if provided
        if irish_grid_e is not None:
            if not isinstance(irish_grid_e, (int, float)):
                raise TypeError(f"Irish Grid easting must be a number, got {type(irish_grid_e).__name__}")
            if not (0 <= irish_grid_e <= 1000000):
                raise ValueError(f"Invalid Irish Grid easting: {irish_grid_e}. Must be between 0 and 1,000,000")

        if irish_grid_n is not None:
            if not isinstance(irish_grid_n, (int, float)):
                raise TypeError(f"Irish Grid northing must be a number, got {type(irish_grid_n).__name__}")
            if not (0 <= irish_grid_n <= 1500000):
                raise ValueError(f"Invalid Irish Grid northing: {irish_grid_n}. Must be between 0 and 1,500,000")

        layer = self._get_or_create_clues_layer()

        feature = QgsFeature(layer.fields())
        feature.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(lon, lat)))

        marker_id = str(uuid.uuid4())
        created_ts = datetime.now().isoformat()
        attributes = {
            "id": marker_id,
            "name": name,
            "clue_type": clue_type,
            "confidence": confidence,
            "description": description,
            "lat": lat,
            "lon": lon,
            "irish_grid_e": irish_grid_e,
            "irish_grid_n": irish_grid_n,
            "created": created_ts
        }
        attributes.update(self._build_audit_attributes(
            include_created=True,
            updated_by=updated_by,
            coordinator_ids=coordinator_ids,
            attachment_path=attachment_path
        ))
        self._apply_feature_attributes(layer, feature, attributes)

        # Add to layer with error handling
        try:
            if not layer.startEditing():
                raise RuntimeError(f"Failed to start editing {self.CLUES_LAYER_NAME} layer - layer may be locked or read-only")

            if not layer.addFeature(feature):
                layer.rollBack()
                raise RuntimeError(f"Failed to add feature to {self.CLUES_LAYER_NAME} layer")

            if not layer.commitChanges():
                errors = layer.commitErrors()
                raise RuntimeError(f"Failed to commit changes to {self.CLUES_LAYER_NAME} layer: {', '.join(errors)}")

            # Force immediate visual update
            layer.triggerRepaint()

            self._log_marker_event(layer, self._marker_log_label("clue"), "add", marker_id=marker_id, name=name)
            return marker_id

        except Exception as e:
            # Ensure layer is not left in editing state
            if layer.isEditable():
                layer.rollBack()
            raise LayerTransactionError(
                self.CLUES_LAYER_NAME,
                "add marker",
                details=str(e)
            )

    # =========================================================================
    # Hazards Layer (Safety warnings)
    # =========================================================================

    def _get_or_create_hazards_layer(self) -> QgsVectorLayer:
        """
        Get or create Hazards layer.

        Hazards are safety-critical warnings for search teams:
        cliffs, water hazards, bogs, dense vegetation, etc.

        Returns:
            QgsVectorLayer: Hazards layer
        """
        layer = self._get_marker_layer("hazard")
        self._log_marker_event(layer, self._marker_log_label("hazard"), "ensure")
        return layer

    def add_hazard(self, name: str, lat: float, lon: float,
                   hazard_type: str = "", severity: str = "Medium",
                   description: str = "",
                   irish_grid_e: float = None, irish_grid_n: float = None,
                   coordinator_ids: Optional[str] = None,
                   updated_by: Optional[str] = None,
                   attachment_path: Optional[str] = None) -> str:
        """
        Add a hazard marker to the map.

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
        # Validate name (required)
        if not name or not name.strip():
            raise ValueError("Marker name cannot be empty")

        # Validate coordinate types first
        if not isinstance(lat, (int, float)):
            raise TypeError(f"Latitude must be a number, got {type(lat).__name__}")
        if not isinstance(lon, (int, float)):
            raise TypeError(f"Longitude must be a number, got {type(lon).__name__}")

        # Validate coordinate ranges
        if not (-90 <= lat <= 90):
            raise ValueError(f"Invalid latitude: {lat}. Must be between -90 and 90")

        if not (-180 <= lon <= 180):
            raise ValueError(f"Invalid longitude: {lon}. Must be between -180 and 180")

        # Validate optional Irish Grid coordinates if provided
        if irish_grid_e is not None:
            if not isinstance(irish_grid_e, (int, float)):
                raise TypeError(f"Irish Grid easting must be a number, got {type(irish_grid_e).__name__}")
            if not (0 <= irish_grid_e <= 1000000):
                raise ValueError(f"Invalid Irish Grid easting: {irish_grid_e}. Must be between 0 and 1,000,000")

        if irish_grid_n is not None:
            if not isinstance(irish_grid_n, (int, float)):
                raise TypeError(f"Irish Grid northing must be a number, got {type(irish_grid_n).__name__}")
            if not (0 <= irish_grid_n <= 1500000):
                raise ValueError(f"Invalid Irish Grid northing: {irish_grid_n}. Must be between 0 and 1,500,000")

        layer = self._get_or_create_hazards_layer()

        feature = QgsFeature(layer.fields())
        feature.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(lon, lat)))

        marker_id = str(uuid.uuid4())
        created_ts = datetime.now().isoformat()
        attributes = {
            "id": marker_id,
            "name": name,
            "hazard_type": hazard_type,
            "severity": severity,
            "description": description,
            "lat": lat,
            "lon": lon,
            "irish_grid_e": irish_grid_e,
            "irish_grid_n": irish_grid_n,
            "created": created_ts
        }
        attributes.update(self._build_audit_attributes(
            include_created=True,
            updated_by=updated_by,
            coordinator_ids=coordinator_ids,
            attachment_path=attachment_path
        ))
        self._apply_feature_attributes(layer, feature, attributes)

        # Add to layer with error handling
        try:
            if not layer.startEditing():
                raise RuntimeError(f"Failed to start editing {self.HAZARDS_LAYER_NAME} layer - layer may be locked or read-only")

            if not layer.addFeature(feature):
                layer.rollBack()
                raise RuntimeError(f"Failed to add feature to {self.HAZARDS_LAYER_NAME} layer")

            if not layer.commitChanges():
                errors = layer.commitErrors()
                raise RuntimeError(f"Failed to commit changes to {self.HAZARDS_LAYER_NAME} layer: {', '.join(errors)}")

            # Force immediate visual update
            layer.triggerRepaint()

            self._log_marker_event(layer, self._marker_log_label("hazard"), "add", marker_id=marker_id, name=name)
            return marker_id

        except Exception as e:
            # Ensure layer is not left in editing state
            if layer.isEditable():
                layer.rollBack()
            raise LayerTransactionError(
                self.HAZARDS_LAYER_NAME,
                "add marker",
                details=str(e)
            )

    # =========================================================================
    # Casualties Layer (Found injured or deceased persons)
    # =========================================================================

    def _get_or_create_casualties_layer(self) -> QgsVectorLayer:
        """
        Get or create Casualties layer.

        Casualties are found injured or deceased persons during SAR operations.
        This is distinct from clues - casualties require medical response,
        evacuation, and specific documentation for legal/coroner requirements.

        Returns:
            QgsVectorLayer: Casualties layer
        """
        layer = self._get_marker_layer("casualty")
        self._log_marker_event(layer, self._marker_log_label("casualty"), "ensure")
        return layer

    def add_casualty(self, name: str, lat: float, lon: float,
                     condition: str = "", treatment: str = "",
                     evacuation_priority: str = "",
                     description: str = "", found_by: str = "",
                     irish_grid_e: float = None, irish_grid_n: float = None,
                     coordinator_ids: Optional[str] = None,
                     updated_by: Optional[str] = None,
                     attachment_path: Optional[str] = None) -> str:
        """
        Add a casualty marker to the map.

        CRITICAL: Casualties are found injured or deceased persons.
        This is distinct from clues (evidence). Casualties trigger:
        - Medical response and evacuation
        - Legal/coroner documentation
        - Family notifications
        - Mission reporting requirements

        Args:
            name: Person identifier/name
            lat: Latitude (WGS84 decimal degrees)
            lon: Longitude (WGS84 decimal degrees)
            condition: Condition (Injured, Deceased, Unresponsive, etc.)
            treatment: First aid administered
            evacuation_priority: Priority (Immediate, Urgent, Delayed, None)
            description: Additional notes
            found_by: Team member or device ID who found the casualty
            irish_grid_e: Irish Grid (ITM) Easting (optional)
            irish_grid_n: Irish Grid (ITM) Northing (optional)

        Returns:
            str: UUID of added casualty

        Raises:
            ValueError: If inputs are invalid
            RuntimeError: If layer operation fails
        """
        # Validate name (required)
        if not name or not name.strip():
            raise ValueError("Casualty name/identifier cannot be empty")

        # Validate coordinate types first
        if not isinstance(lat, (int, float)):
            raise TypeError(f"Latitude must be a number, got {type(lat).__name__}")
        if not isinstance(lon, (int, float)):
            raise TypeError(f"Longitude must be a number, got {type(lon).__name__}")

        # Validate coordinate ranges
        if not (-90 <= lat <= 90):
            raise ValueError(f"Invalid latitude: {lat}. Must be between -90 and 90")

        if not (-180 <= lon <= 180):
            raise ValueError(f"Invalid longitude: {lon}. Must be between -180 and 180")

        # Validate optional Irish Grid coordinates if provided
        if irish_grid_e is not None:
            if not isinstance(irish_grid_e, (int, float)):
                raise TypeError(f"Irish Grid easting must be a number, got {type(irish_grid_e).__name__}")
            if not (0 <= irish_grid_e <= 1000000):
                raise ValueError(f"Invalid Irish Grid easting: {irish_grid_e}. Must be between 0 and 1,000,000")

        if irish_grid_n is not None:
            if not isinstance(irish_grid_n, (int, float)):
                raise TypeError(f"Irish Grid northing must be a number, got {type(irish_grid_n).__name__}")
            if not (0 <= irish_grid_n <= 1500000):
                raise ValueError(f"Invalid Irish Grid northing: {irish_grid_n}. Must be between 0 and 1,500,000")

        layer = self._get_or_create_casualties_layer()

        feature = QgsFeature(layer.fields())
        feature.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(lon, lat)))

        marker_id = str(uuid.uuid4())
        created_ts = datetime.now().isoformat()
        attributes = {
            "id": marker_id,
            "name": name,
            "condition": condition,
            "treatment": treatment,
            "evacuation_priority": evacuation_priority,
            "description": description,
            "found_by": found_by,
            "lat": lat,
            "lon": lon,
            "irish_grid_e": irish_grid_e,
            "irish_grid_n": irish_grid_n,
            "created": created_ts
        }
        attributes.update(self._build_audit_attributes(
            include_created=True,
            updated_by=updated_by,
            coordinator_ids=coordinator_ids,
            attachment_path=attachment_path
        ))
        self._apply_feature_attributes(layer, feature, attributes)

        # Add to layer with proper transaction handling (Issue #3 pattern)
        try:
            if not layer.startEditing():
                raise RuntimeError(f"Failed to start editing {self.CASUALTIES_LAYER_NAME} layer - layer may be locked or read-only")

            if not layer.addFeature(feature):
                layer.rollBack()
                raise RuntimeError(f"Failed to add feature to {self.CASUALTIES_LAYER_NAME} layer")

            if not layer.commitChanges():
                errors = layer.commitErrors()
                raise RuntimeError(f"Failed to commit changes to {self.CASUALTIES_LAYER_NAME} layer: {', '.join(errors)}")

            # Force immediate visual update
            layer.triggerRepaint()

            self._log_marker_event(
                layer,
                self._marker_log_label("casualty"),
                "add",
                marker_id=marker_id,
                name=name,
                condition=condition,
                evacuation_priority=evacuation_priority
            )
            return marker_id

        except Exception as e:
            # Ensure layer is not left in editing state (Issue #3 fix)
            if layer.isEditable():
                layer.rollBack()
            raise LayerTransactionError(
                self.CASUALTIES_LAYER_NAME,
                "add marker",
                details=str(e)
            )

    # =========================================================================
    # Marker listing / CRUD helpers
    # =========================================================================

    def _feature_to_record(self, marker_type: str, layer: QgsVectorLayer, feature: QgsFeature) -> Dict[str, object]:
        """Convert QgsFeature to lightweight dict for UI consumption.

        Uses safe field access to avoid KeyError on malformed layers.
        """
        def safe_attr(field_name, default=None):
            """Safely get attribute value, returning default if field missing."""
            try:
                idx = layer.fields().indexOf(field_name)
                if idx == -1:
                    return default
                return feature.attribute(idx)
            except Exception:
                return default

        lat = safe_attr("lat")
        lon = safe_attr("lon")
        if (lat is None or lon is None) and feature.geometry() and not feature.geometry().isEmpty():
            point = feature.geometry().asPoint()
            if point:
                lat = lat or point.y()
                lon = lon or point.x()

        return {
            "id": safe_attr("id"),
            "type": marker_type,
            "name": safe_attr("name"),
            "description": safe_attr("description"),
            "created": safe_attr("created"),
            "created_at": safe_attr("created_at"),
            "updated_at": safe_attr("updated_at"),
            "updated_by": safe_attr("updated_by"),
            "coordinator_ids": safe_attr("coordinator_ids"),
            "attachment_path": safe_attr("attachment_path"),
            "lat": lat,
            "lon": lon,
            "irish_grid_e": safe_attr("irish_grid_e"),
            "irish_grid_n": safe_attr("irish_grid_n"),
            "layer_id": layer.id(),
            "feature_id": feature.id()
        }

    def list_markers(self) -> List[Dict[str, object]]:
        """Return all markers across managed layers."""
        records: List[Dict[str, object]] = []
        for marker_type in self.MARKER_TYPE_MAP.keys():
            layer = self._get_marker_layer(marker_type)
            for feature in layer.getFeatures():
                try:
                    records.append(self._feature_to_record(marker_type, layer, feature))
                except Exception as exc:
                    print(f"[MarkerLayerManager] Warning: Failed to serialize marker {feature['id']}: {exc}")
        return records

    def get_marker_feature(self, marker_type: str, marker_id: str) -> Optional[QgsFeature]:
        """Return feature for marker id."""
        layer = self._get_marker_layer(marker_type)
        return self._get_feature_by_id(layer, marker_id)

    def update_marker(self, marker_type: str, marker_id: str, updates: Dict[str, object], updated_by: Optional[str] = None) -> bool:
        """Update marker attributes."""
        layer = self._get_marker_layer(marker_type)
        feature = self._get_feature_by_id(layer, marker_id)
        if not feature:
            raise ValueError(f"Marker '{marker_id}' not found for type '{marker_type}'")

        if not layer.startEditing():
            raise RuntimeError(f"Failed to start editing {layer.name()} layer - layer may be locked or read-only")
        try:
            # Build complete attribute update dictionary
            audit_attrs = self._build_audit_attributes(
                include_created=False,
                updated_by=updated_by or updates.get("updated_by"),
                coordinator_ids=updates.get("coordinator_ids"),
                attachment_path=updates.get("attachment_path")
            )
            all_updates = {**(updates or {}), **audit_attrs}

            # Use changeAttributeValue() for reliable updates (avoid feature copy issues)
            fields = layer.fields()
            for field_name, value in all_updates.items():
                field_index = fields.indexOf(field_name)
                if field_index == -1:
                    continue
                if not layer.changeAttributeValue(feature.id(), field_index, value):
                    layer.rollBack()
                    raise RuntimeError(f"Failed to update marker '{marker_id}' field '{field_name}'")

            if not layer.commitChanges():
                errors = layer.commitErrors()
                raise RuntimeError(f"Failed to commit marker update: {', '.join(errors)}")
        except Exception as exc:
            if layer.isEditable():
                layer.rollBack()
            raise LayerTransactionError(
                layer.name(),
                "update marker",
                details=str(exc)
            ) from exc
        # No finally block needed - commitChanges() exits edit mode on success,
        # and rollBack is handled in the except block on failure

        layer.triggerRepaint()
        self._log_marker_event(layer, self._marker_log_label(marker_type), "update", marker_id=marker_id)
        return True

    def delete_marker(self, marker_type: str, marker_id: str) -> bool:
        """Delete marker by id."""
        layer = self._get_marker_layer(marker_type)
        feature = self._get_feature_by_id(layer, marker_id)
        if not feature:
            raise ValueError(f"Marker '{marker_id}' not found for type '{marker_type}'")

        if not layer.startEditing():
            raise RuntimeError(f"Failed to start editing {layer.name()} layer - layer may be locked or read-only")
        try:
            if not layer.deleteFeature(feature.id()):
                layer.rollBack()
                raise RuntimeError(f"Failed to delete marker '{marker_id}'")

            if not layer.commitChanges():
                errors = layer.commitErrors()
                raise RuntimeError(f"Failed to commit marker deletion: {', '.join(errors)}")
        except Exception as exc:
            if layer.isEditable():
                layer.rollBack()
            raise LayerTransactionError(
                layer.name(),
                "delete marker",
                details=str(exc)
            ) from exc
        # No finally block needed - commitChanges() exits edit mode on success,
        # and rollBack is handled in the except block on failure

        layer.triggerRepaint()
        self._log_marker_event(layer, self._marker_log_label(marker_type), "delete", marker_id=marker_id)
        return True

    # =========================================================================
    # Common Helper Methods
    # =========================================================================

    def _apply_marker_labels(self, layer: QgsVectorLayer, text_color: QColor):
        """
        Apply labeling to a marker layer.

        Args:
            layer: Layer to apply labels to
            text_color: Color for label text
        """
        label_settings = QgsPalLayerSettings()
        label_settings.fieldName = 'name'
        label_settings.enabled = True

        # Handle QGIS version differences in placement enum
        # Qt5/Qt6 Compatible: Try new style first, fallback to old
        try:
            # QGIS 3.26+ uses Placement enum
            label_settings.placement = QgsPalLayerSettings.Placement.OverPoint
        except AttributeError:
            # Older QGIS versions
            label_settings.placement = QgsPalLayerSettings.OverPoint

        # Text format
        text_format = QgsTextFormat()
        text_format.setSize(10)
        text_format.setColor(text_color)

        # Text buffer (white halo for readability)
        buffer = QgsTextBufferSettings()
        buffer.setEnabled(True)
        buffer.setColor(QColor('white'))
        buffer.setSize(1)
        text_format.setBuffer(buffer)

        label_settings.setFormat(text_format)

        # Apply labeling to layer
        labeling = QgsVectorLayerSimpleLabeling(label_settings)
        layer.setLabeling(labeling)
        layer.setLabelsEnabled(True)
