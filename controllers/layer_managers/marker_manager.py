# -*- coding: utf-8 -*-
"""
Marker Layer Manager

Manages SAR marker point layers: IPP/LKP, Clues, and Hazards.
Each marker type has its own layer with appropriate fields and styling.

Qt5/Qt6 Compatible: Uses qgis.PyQt for all imports.
"""

from datetime import datetime, timezone
import logging
import math
import uuid
from typing import Dict, List, Optional, Union
from contextlib import contextmanager

logger = logging.getLogger(__name__)

from qgis.core import (
    QgsVectorLayer, QgsFeature, QgsGeometry,
    QgsPointXY, QgsMarkerSymbol, QgsPalLayerSettings,
    QgsVectorLayerSimpleLabeling, QgsTextFormat, QgsTextBufferSettings,
    QgsFeatureRequest, QgsCoordinateReferenceSystem, QgsCoordinateTransform,
    QgsProject, QgsLayerTreeGroup,
    QgsDropShadowEffect, QgsEffectStack, QgsDrawSourceEffect
)
from qgis.PyQt.QtGui import QColor

from .base_manager import BaseLayerManager
from ...layers import LayerIds, GroupNames, get_per_item_group_path
from ...utils.exceptions import LayerTransactionError, LayerLockError, LayerError

# Phase 4 imports for per-item layers
from pathlib import Path
from ..per_item_layer_factory import (
    PerItemLayerFactory, ItemType, ItemLayerInfo, SAR_ITEM_ID, SAR_ITEM_TYPE
)


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

    # Phase 4: Enable per-item layers for specific marker types
    # When True, new markers of these types create individual layers
    # When False, use legacy shared layers (backward compatibility)
    USE_PER_ITEM_LAYERS = {
        "clue": True,       # Phase 4 Step 1: Clues use per-item layers
        "ipp_lkp": True,    # Phase 4 Step 2: IPP/LKP use per-item layers
        "hazard": True,     # Phase 4 Step 2: Hazards use per-item layers
        "casualty": True,   # Phase 4 Step 2: Casualties use per-item layers
    }

    def __init__(self, iface, shared_device_colors=None, layer_manager=None):
        """Initialize marker layer manager."""
        super().__init__(iface, shared_device_colors, layer_manager)
        self._invalid_layer_warnings = set()
        # Phase 4: Per-item layer factory (lazy initialized)
        self._per_item_factory: Optional[PerItemLayerFactory] = None

    def _validate_irish_grid_consistency(self, lat: float, lon: float,
                                         irish_grid_e: Optional[float],
                                         irish_grid_n: Optional[float]) -> None:
        """
        BUG-072 FIX: Cross-validate WGS84 and Irish Grid coordinates for consistency.

        LIFE-SAFETY CRITICAL: Inconsistent coordinates could lead to rescuers going
        to the wrong location during operations.

        This method checks that if both WGS84 (lat/lon) and Irish Grid (E/N)
        coordinates are provided, they refer to approximately the same location
        within a reasonable tolerance.

        Args:
            lat: WGS84 latitude
            lon: WGS84 longitude
            irish_grid_e: Optional Irish Grid (ITM) easting
            irish_grid_n: Optional Irish Grid (ITM) northing

        Raises:
            ValueError: If coordinates are inconsistent beyond tolerance
        """
        # BUG-072: Only validate if both coordinate systems are provided
        if irish_grid_e is None or irish_grid_n is None:
            return  # No cross-validation needed

        try:
            # Define coordinate reference systems
            wgs84 = QgsCoordinateReferenceSystem("EPSG:4326")  # WGS84
            itm = QgsCoordinateReferenceSystem("EPSG:2157")    # Irish Transverse Mercator

            if not wgs84.isValid() or not itm.isValid():
                logger.warning("BUG-072: Could not initialize CRS for coordinate validation")
                return  # Skip validation if CRS initialization fails

            # Transform WGS84 to Irish Grid
            transform = QgsCoordinateTransform(wgs84, itm, QgsProject.instance())
            wgs84_point = QgsPointXY(lon, lat)
            itm_point = transform.transform(wgs84_point)

            # Calculate discrepancy in meters
            delta_e = abs(itm_point.x() - irish_grid_e)
            delta_n = abs(itm_point.y() - irish_grid_n)
            distance = math.sqrt(delta_e**2 + delta_n**2)

            # BUG-072: Allow tolerance of 100 meters for:
            # - Rounding differences
            # - Manual entry errors
            # - GPS accuracy variations
            TOLERANCE_METERS = 100.0

            if distance > TOLERANCE_METERS:
                raise ValueError(
                    f"Inconsistent coordinates: WGS84 ({lat:.6f}, {lon:.6f}) and "
                    f"Irish Grid ({irish_grid_e:.1f}E, {irish_grid_n:.1f}N) "
                    f"are {distance:.1f}m apart (tolerance: {TOLERANCE_METERS}m). "
                    f"Computed Irish Grid from WGS84: {itm_point.x():.1f}E, {itm_point.y():.1f}N"
                )

            # Log validation success for diagnostics
            if distance > 10.0:  # Log if discrepancy is > 10m but within tolerance
                logger.info(
                    "BUG-072: Coordinate consistency check passed with %dm discrepancy (within %dm tolerance)",
                    int(distance), int(TOLERANCE_METERS)
                )

        except Exception as e:
            # BUG-072: Log but don't fail on validation errors
            # (transform might fail for out-of-bounds coordinates)
            logger.warning(
                "BUG-072: Could not validate coordinate consistency: %s. "
                "WGS84=(%s, %s), Irish Grid=(%s, %s)",
                str(e), lat, lon, irish_grid_e, irish_grid_n
            )

    def get_managed_layer_names(self):
        """Return list of layer names this manager handles."""
        return [
            self.IPP_LKP_LAYER_NAME,
            self.CLUES_LAYER_NAME,
            self.HAZARDS_LAYER_NAME,
            self.CASUALTIES_LAYER_NAME
        ]

    # =========================================================================
    # Phase 4: Per-Item Layer Support
    # =========================================================================

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
        gpkg_path = self._require_mission_store("Per-item marker operations")

        # Create factory
        self._per_item_factory = PerItemLayerFactory(
            gpkg_path=Path(gpkg_path),
            auto_wal=True,
            auto_registry=True
        )
        logger.info("Phase 4: PerItemLayerFactory initialized with mission store: %s", gpkg_path)
        return self._per_item_factory

    def _ensure_per_item_group(self, item_type: str) -> QgsLayerTreeGroup:
        """
        Ensure the group path exists for a per-item layer type.

        Creates the "Map Tools / <subgroup>" structure if needed.

        Args:
            item_type: ItemType value (e.g., ItemType.MARKER_CLUE)

        Returns:
            QgsLayerTreeGroup for placing the per-item layer
        """
        group_path = get_per_item_group_path(item_type)
        return self._ensure_group_path(group_path)

    def _uses_per_item_layers(self, marker_type: str) -> bool:
        """
        Check if a marker type uses per-item layers.

        Args:
            marker_type: Type key (e.g., "clue", "ipp_lkp")

        Returns:
            True if this marker type uses per-item layers
        """
        return self.USE_PER_ITEM_LAYERS.get(marker_type, False)

    def _get_item_type_for_marker(self, marker_type: str) -> str:
        """
        Map marker type to ItemType constant.

        Args:
            marker_type: Internal marker type key

        Returns:
            ItemType constant for PerItemLayerFactory
        """
        mapping = {
            "clue": ItemType.MARKER_CLUE,
            "ipp_lkp": ItemType.MARKER_IPP_LKP,
            "hazard": ItemType.MARKER_HAZARD,
            "casualty": ItemType.MARKER_CASUALTY,
        }
        return mapping.get(marker_type, ItemType.MARKER_CLUE)

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

    # ---------------------------------------------------------------------
    # Internal helpers
    # ---------------------------------------------------------------------

    def _log_marker_event(self, layer: QgsVectorLayer, marker_type: str, action: str, **extra):
        """Proxy to BaseLayerManager diagnostics helper."""
        payload = extra if extra else None
        self._log_layer_snapshot(layer, f"{marker_type}::{action}", payload)

    def _current_timestamp(self) -> str:
        """Return ISO timestamp for audit fields (timezone-aware UTC)."""
        return datetime.now(timezone.utc).isoformat()

    @contextmanager
    def _layer_transaction(self, layer: QgsVectorLayer, layer_name: str, operation: str):
        """
        Context manager enforcing safe edit session lifecycle for marker layers.
        """
        if not layer or not layer.isValid():
            raise LayerError(f"{layer_name} layer is unavailable or invalid.", layer_name=layer_name)
        if layer.isEditable():
            raise LayerLockError(layer_name)

        cleanup_attempted = False

        def _cleanup(raise_on_failure: bool, reason: str) -> Optional[str]:
            nonlocal cleanup_attempted
            cleanup_attempted = True
            context = f"{operation}::{reason}" if reason else operation
            return self._safe_close_layer_edit(layer, layer_name, context, raise_on_failure=raise_on_failure)

        try:
            try:
                started = layer.startEditing()
            except Exception as exc:
                details = str(exc)
                cleanup_note = _cleanup(False, "start_editing_exception")
                if cleanup_note:
                    details = f"{details} | cleanup: {cleanup_note}"
                raise LayerTransactionError(layer_name, "start editing", details=details) from exc

            if not started:
                cleanup_note = _cleanup(False, "start_editing_failed")
                details = operation
                if cleanup_note:
                    details = f"{details} | cleanup: {cleanup_note}"
                raise LayerTransactionError(layer_name, "start editing", details=details)

            yield layer

            if not layer.commitChanges():
                errors = layer.commitErrors()
                details = "; ".join(errors) if errors else operation
                cleanup_note = _cleanup(False, "commit_failure")
                if cleanup_note:
                    details = f"{details} | cleanup: {cleanup_note}"
                raise LayerTransactionError(layer_name, "commit changes", details=details)
        except LayerError:
            _cleanup(False, "layer_error")
            raise
        except Exception as exc:
            details = str(exc)
            cleanup_note = _cleanup(False, "exception")
            if cleanup_note:
                details = f"{details} | cleanup: {cleanup_note}"
            raise LayerTransactionError(layer_name, operation, details=details) from exc
        finally:
            if not cleanup_attempted:
                self._safe_close_layer_edit(layer, layer_name, f"{operation}::finalize", raise_on_failure=True)

    def _safe_close_layer_edit(
        self,
        layer: Optional[QgsVectorLayer],
        layer_name: str,
        context: str,
        raise_on_failure: bool = False
    ) -> Optional[str]:
        """
        Ensure marker layers exit edit mode, logging failures for diagnostics.
        """
        if not layer or not layer.isValid():
            return None

        try:
            editable = layer.isEditable()
        except Exception as exc:
            message = f"isEditable() check failed: {exc}"
            if raise_on_failure:
                raise LayerTransactionError(layer_name, context, details=message) from exc
            print(f"[MarkerLayerManager] CRITICAL: {layer_name} cleanup state unknown ({context}): {message}")
            return message

        if not editable:
            return None

        issues: List[str] = []
        try:
            result = layer.rollBack()
            if result is False:
                issues.append("rollBack returned False")
        except RuntimeError as exc:
            issues.append(f"RuntimeError: {exc}")
        except Exception as exc:
            issues.append(f"rollback exception: {exc}")

        try:
            editable = layer.isEditable()
        except Exception as exc:
            issues.append(f"isEditable() post-check failed: {exc}")
            editable = True

        if editable:
            if not issues:
                issues.append("layer remained editable after rollback attempt")
            message = "; ".join(issues)
            if raise_on_failure:
                raise LayerTransactionError(layer_name, context, details=message)
            print(f"[MarkerLayerManager] CRITICAL: {layer_name} cleanup failed ({context}): {message}")
            return message

        return None

    def _get_marker_layer(self, marker_type: str) -> QgsVectorLayer:
        """
        Return persistent layer for a marker type with validity checks.

        BUG-013 FIX: Added explicit layer validity checks to prevent
        operations on stale or invalid layer references.

        Args:
            marker_type: Type of marker ('ipp_lkp', 'clue', 'hazard', 'casualty')

        Returns:
            QgsVectorLayer: Valid marker layer

        Raises:
            ValueError: If marker_type is unknown
            LayerError: If layer is invalid or unavailable
        """
        meta = self.MARKER_TYPE_MAP.get(marker_type)
        if not meta:
            raise ValueError(f"Unknown marker type: {marker_type}")

        style_factory = getattr(self, meta["style_fn"])
        layer = self._ensure_schema_layer(
            meta["layer_id"],
            fallback_name=meta["fallback"],
            style_factory=style_factory
        )

        # BUG-013 FIX: Explicit validity checks
        layer_name = meta["fallback"]

        if layer is None:
            # Log warning once per layer to avoid spam
            if layer_name not in self._invalid_layer_warnings:
                self._invalid_layer_warnings.add(layer_name)
                import logging
                logging.getLogger(__name__).warning(
                    "Marker layer '%s' could not be created or retrieved",
                    layer_name
                )
            raise LayerError(
                f"Marker layer '{layer_name}' is not available. "
                "The layer may need to be recreated.",
                layer_name=layer_name
            )

        if not layer.isValid():
            # Log warning once per layer to avoid spam
            if layer_name not in self._invalid_layer_warnings:
                self._invalid_layer_warnings.add(layer_name)
                import logging
                logging.getLogger(__name__).warning(
                    "Marker layer '%s' exists but is invalid - data source may be corrupted",
                    layer_name
                )
            raise LayerError(
                f"Marker layer '{layer_name}' is invalid. "
                "Check the layer data source and project settings.",
                layer_name=layer_name
            )

        # Check layer still exists in project (guard against deletion)
        if self.project and not self.project.mapLayer(layer.id()):
            raise LayerError(
                f"Marker layer '{layer_name}' was removed from project.",
                layer_name=layer_name
            )

        return layer

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
        """
        Set feature attributes by field name safely.

        BUG-039 FIX: Added type validation to prevent silent type mismatches
        that could cause data truncation or precision loss.
        """
        fields = layer.fields()
        for key, value in data.items():
            idx = fields.indexOf(key)
            if idx == -1:
                continue

            # BUG-039 FIX: Validate and coerce types to prevent silent truncation
            field = fields.at(idx)
            field_type = field.type()

            # Type validation for safety-critical data
            if value is not None:
                # String field: ensure string conversion and check length
                if field_type == 10:  # QString
                    str_value = str(value) if not isinstance(value, str) else value
                    max_len = field.length()
                    if max_len > 0 and len(str_value) > max_len:
                        logger.warning(
                            "BUG-039: String truncation for field '%s': %d chars > max %d",
                            key, len(str_value), max_len
                        )
                        str_value = str_value[:max_len]
                    value = str_value

                # Integer field: check for overflow
                elif field_type == 2:  # Int
                    if isinstance(value, float):
                        logger.debug("BUG-039: Converting float to int for field '%s'", key)
                        value = int(value)
                    elif isinstance(value, str):
                        try:
                            value = int(value)
                        except ValueError:
                            logger.warning("BUG-039: Cannot convert '%s' to int for field '%s'", value, key)
                            continue

                # Double field: check for special values
                elif field_type == 6:  # Double
                    if isinstance(value, str):
                        try:
                            value = float(value)
                        except ValueError:
                            logger.warning("BUG-039: Cannot convert '%s' to float for field '%s'", value, key)
                            continue
                    if isinstance(value, float):
                        if math.isnan(value) or math.isinf(value):
                            logger.warning("BUG-039: Invalid float value (NaN/Inf) for field '%s'", key)
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
            'name': 'circle',
            'color': '#FFFFFF',
            'size': '10',
            'outline_color': 'black',
            'outline_width': '0.5'
        })
        layer.renderer().setSymbol(symbol)
        self._apply_marker_labels(layer, QColor('#806600'))

    def _style_hazards_layer(self, layer: QgsVectorLayer):
        symbol = QgsMarkerSymbol.createSimple({
            'name': 'filled_arrowhead',
            'color': '#FF0000',
            'size': '12',
            'outline_color': 'black',
            'outline_width': '0.5',
            'angle': '180'
        })
        layer.renderer().setSymbol(symbol)
        self._apply_marker_labels(layer, QColor('#8B0000'))

    def _style_casualties_layer(self, layer: QgsVectorLayer):
        symbol = QgsMarkerSymbol.createSimple({
            'name': 'star',
            'color': '#FF0000',
            'size': '16',
            'outline_color': 'black',
            'outline_width': '1.0'
        })
        # Add drop shadow effect for visual prominence (life-safety critical marker)
        shadow = QgsDropShadowEffect()
        shadow.setEnabled(True)
        shadow.setBlurLevel(2.0)
        shadow.setOffsetDistance(2.0)
        shadow.setOffsetAngle(135)
        shadow.setColor(QColor(0, 0, 0, 180))
        # Create effect stack with source effect + shadow
        effect_stack = QgsEffectStack()
        effect_stack.appendEffect(shadow)
        source = QgsDrawSourceEffect()
        source.setEnabled(True)
        effect_stack.appendEffect(source)
        effect_stack.setEnabled(True)
        symbol.symbolLayer(0).setPaintEffect(effect_stack)
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
                    attachment_path: Optional[str] = None) -> Union[int, str]:
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
            Union[int, str]: Feature ID (int for shared layer) or item_id (str for per-item layer)
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

        # BUG-072 FIX: Cross-validate WGS84 and Irish Grid coordinates
        self._validate_irish_grid_consistency(lat, lon, irish_grid_e, irish_grid_n)

        # Phase 4: Check if we should use per-item layers
        if self._uses_per_item_layers("ipp_lkp"):
            return self._add_ipp_lkp_per_item(
                name=name, lat=lat, lon=lon,
                subject_category=subject_category, description=description,
                irish_grid_e=irish_grid_e, irish_grid_n=irish_grid_n,
                coordinator_ids=coordinator_ids, updated_by=updated_by,
                attachment_path=attachment_path
            )

        # Legacy path: shared layer
        return self._add_ipp_lkp_shared_layer(
            name=name, lat=lat, lon=lon,
            subject_category=subject_category, description=description,
            irish_grid_e=irish_grid_e, irish_grid_n=irish_grid_n,
            coordinator_ids=coordinator_ids, updated_by=updated_by,
            attachment_path=attachment_path
        )

    def _add_ipp_lkp_shared_layer(
        self, name: str, lat: float, lon: float,
        subject_category: str, description: str,
        irish_grid_e: Optional[float], irish_grid_n: Optional[float],
        coordinator_ids: Optional[str], updated_by: Optional[str],
        attachment_path: Optional[str]
    ) -> str:
        """Legacy implementation: Add IPP/LKP to shared layer."""
        layer = self._get_or_create_ipp_lkp_layer()

        # Create feature
        feature = QgsFeature(layer.fields())
        feature.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(lon, lat)))

        # Generate UUID
        marker_id = str(uuid.uuid4())

        created_ts = self._current_timestamp()
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

        with self._layer_transaction(layer, self.IPP_LKP_LAYER_NAME, "add marker") as edit_layer:
            if not edit_layer.addFeature(feature):
                raise RuntimeError(f"Failed to add feature to {self.IPP_LKP_LAYER_NAME} layer")

        layer.triggerRepaint()
        self._log_marker_event(layer, self._marker_log_label("ipp_lkp"), "add", marker_id=marker_id, name=name)
        return marker_id

    def _add_ipp_lkp_per_item(
        self, name: str, lat: float, lon: float,
        subject_category: str, description: str,
        irish_grid_e: Optional[float], irish_grid_n: Optional[float],
        coordinator_ids: Optional[str], updated_by: Optional[str],
        attachment_path: Optional[str]
    ) -> str:
        """
        Phase 4: Add IPP/LKP as a per-item layer.

        Creates an individual GeoPackage-backed layer for this IPP/LKP marker,
        placed under "SAR Tracker / Map Tools / IPP-LKP /".

        Returns:
            str: item_id (which serves as the marker_id)
        """
        factory = self._get_per_item_factory()
        if not factory:
            # Fallback to shared layer if no mission store configured
            logger.warning("Phase 4: No factory available, falling back to shared layer for IPP/LKP")
            return self._add_ipp_lkp_shared_layer(
                name=name, lat=lat, lon=lon,
                subject_category=subject_category, description=description,
                irish_grid_e=irish_grid_e, irish_grid_n=irish_grid_n,
                coordinator_ids=coordinator_ids, updated_by=updated_by,
                attachment_path=attachment_path
            )

        # Ensure the target group exists
        target_group = self._ensure_per_item_group(ItemType.MARKER_IPP_LKP)

        # Define fields for the IPP/LKP layer (matching schema)
        ipp_lkp_fields = [
            {"name": "id", "type": "String", "length": 50},
            {"name": "name", "type": "String", "length": 255},
            {"name": "subject_category", "type": "String", "length": 100},
            {"name": "description", "type": "String", "length": 1000},
            {"name": "lat", "type": "Double"},
            {"name": "lon", "type": "Double"},
            {"name": "irish_grid_e", "type": "Double"},
            {"name": "irish_grid_n", "type": "Double"},
            {"name": "created", "type": "String", "length": 50},
            {"name": "created_at", "type": "String", "length": 50},
            {"name": "updated_at", "type": "String", "length": 50},
            {"name": "updated_by", "type": "String", "length": 255},
            {"name": "coordinator_ids", "type": "String", "length": 500},
            {"name": "attachment_path", "type": "String", "length": 500},
        ]

        # Create the per-item layer
        try:
            item_info = factory.create_item_layer(
                item_type=ItemType.MARKER_IPP_LKP,
                display_name=name,
                fields=ipp_lkp_fields,
                add_to_project=True,
                target_group=target_group
            )
        except Exception as e:
            logger.error("Phase 4: Failed to create per-item layer for IPP/LKP '%s': %s", name, e)
            raise RuntimeError(f"Failed to create per-item IPP/LKP layer: {e}") from e

        layer = item_info.layer
        item_id = item_info.item_id

        if not layer or not layer.isValid():
            raise RuntimeError(f"Per-item layer created but invalid for IPP/LKP '{name}'")

        # Create and add the feature to the layer
        feature = QgsFeature(layer.fields())
        feature.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(lon, lat)))

        created_ts = datetime.now(timezone.utc).isoformat()
        attributes = {
            "id": item_id,  # Use item_id as the marker id
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

        # Add feature to layer
        try:
            with self._layer_transaction(layer, name, "add IPP/LKP feature") as edit_layer:
                if not edit_layer.addFeature(feature):
                    raise RuntimeError(f"Failed to add feature to per-item IPP/LKP layer '{name}'")
        except Exception:
            self._cleanup_failed_per_item_layer(factory, item_id, "IPP/LKP")
            raise

        # Apply styling
        self._style_ipp_lkp_layer(layer)

        layer.triggerRepaint()
        logger.info(
            "Phase 4: Created per-item IPP/LKP layer '%s' (item_id=%s) under Map Tools/IPP-LKP",
            name, item_id
        )
        return item_id

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
                 attachment_path: Optional[str] = None) -> Union[int, str]:
        """
        Add a clue marker to the map.

        Phase 4: When USE_PER_ITEM_LAYERS["clue"] is True, creates an individual
        layer for this clue under "SAR Tracker / Map Tools / Clues /".

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
            Union[int, str]: Feature ID (int for shared layer) or item_id (str for per-item layer)
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

        # BUG-072 FIX: Cross-validate WGS84 and Irish Grid coordinates
        self._validate_irish_grid_consistency(lat, lon, irish_grid_e, irish_grid_n)

        # Phase 4: Check if we should use per-item layers
        if self._uses_per_item_layers("clue"):
            return self._add_clue_per_item(
                name=name, lat=lat, lon=lon,
                clue_type=clue_type, confidence=confidence, description=description,
                irish_grid_e=irish_grid_e, irish_grid_n=irish_grid_n,
                coordinator_ids=coordinator_ids, updated_by=updated_by,
                attachment_path=attachment_path
            )

        # Legacy path: shared layer
        return self._add_clue_shared_layer(
            name=name, lat=lat, lon=lon,
            clue_type=clue_type, confidence=confidence, description=description,
            irish_grid_e=irish_grid_e, irish_grid_n=irish_grid_n,
            coordinator_ids=coordinator_ids, updated_by=updated_by,
            attachment_path=attachment_path
        )

    def _add_clue_shared_layer(
        self, name: str, lat: float, lon: float,
        clue_type: str, confidence: str, description: str,
        irish_grid_e: Optional[float], irish_grid_n: Optional[float],
        coordinator_ids: Optional[str], updated_by: Optional[str],
        attachment_path: Optional[str]
    ) -> str:
        """Legacy implementation: Add clue to shared Clues layer."""
        layer = self._get_or_create_clues_layer()

        feature = QgsFeature(layer.fields())
        feature.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(lon, lat)))

        marker_id = str(uuid.uuid4())
        created_ts = self._current_timestamp()
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

        with self._layer_transaction(layer, self.CLUES_LAYER_NAME, "add marker") as edit_layer:
            if not edit_layer.addFeature(feature):
                raise RuntimeError(f"Failed to add feature to {self.CLUES_LAYER_NAME} layer")

        layer.triggerRepaint()
        self._log_marker_event(layer, self._marker_log_label("clue"), "add", marker_id=marker_id, name=name)
        return marker_id

    def _add_clue_per_item(
        self, name: str, lat: float, lon: float,
        clue_type: str, confidence: str, description: str,
        irish_grid_e: Optional[float], irish_grid_n: Optional[float],
        coordinator_ids: Optional[str], updated_by: Optional[str],
        attachment_path: Optional[str]
    ) -> str:
        """
        Phase 4: Add clue as a per-item layer.

        Creates an individual GeoPackage-backed layer for this clue,
        placed under "SAR Tracker / Map Tools / Clues /".

        Returns:
            str: item_id (which serves as the marker_id)
        """
        factory = self._get_per_item_factory()
        if not factory:
            # Fallback to shared layer if no mission store configured
            logger.warning("Phase 4: No factory available, falling back to shared layer for clue")
            return self._add_clue_shared_layer(
                name=name, lat=lat, lon=lon,
                clue_type=clue_type, confidence=confidence, description=description,
                irish_grid_e=irish_grid_e, irish_grid_n=irish_grid_n,
                coordinator_ids=coordinator_ids, updated_by=updated_by,
                attachment_path=attachment_path
            )

        # Ensure the target group exists
        target_group = self._ensure_per_item_group(ItemType.MARKER_CLUE)

        # Define fields for the clue layer (matching schema for Clues)
        clue_fields = [
            {"name": "id", "type": "String", "length": 50},
            {"name": "name", "type": "String", "length": 255},
            {"name": "clue_type", "type": "String", "length": 100},
            {"name": "confidence", "type": "String", "length": 50},
            {"name": "description", "type": "String", "length": 1000},
            {"name": "lat", "type": "Double"},
            {"name": "lon", "type": "Double"},
            {"name": "irish_grid_e", "type": "Double"},
            {"name": "irish_grid_n", "type": "Double"},
            {"name": "created", "type": "String", "length": 50},
            {"name": "created_at", "type": "String", "length": 50},
            {"name": "updated_at", "type": "String", "length": 50},
            {"name": "updated_by", "type": "String", "length": 255},
            {"name": "coordinator_ids", "type": "String", "length": 500},
            {"name": "attachment_path", "type": "String", "length": 500},
        ]

        # Create the per-item layer
        try:
            item_info = factory.create_item_layer(
                item_type=ItemType.MARKER_CLUE,
                display_name=name,
                fields=clue_fields,
                add_to_project=True,
                target_group=target_group
            )
        except Exception as e:
            logger.error("Phase 4: Failed to create per-item layer for clue '%s': %s", name, e)
            raise RuntimeError(f"Failed to create per-item clue layer: {e}") from e

        layer = item_info.layer
        item_id = item_info.item_id

        if not layer or not layer.isValid():
            raise RuntimeError(f"Per-item layer created but invalid for clue '{name}'")

        # Create and add the feature to the layer
        feature = QgsFeature(layer.fields())
        feature.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(lon, lat)))

        created_ts = datetime.now(timezone.utc).isoformat()
        attributes = {
            "id": item_id,  # Use item_id as the marker id
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

        # Add feature to layer
        try:
            with self._layer_transaction(layer, name, "add clue feature") as edit_layer:
                if not edit_layer.addFeature(feature):
                    raise RuntimeError(f"Failed to add feature to per-item clue layer '{name}'")
        except Exception:
            self._cleanup_failed_per_item_layer(factory, item_id, "clue")
            raise

        # Apply styling
        self._style_clues_layer(layer)

        layer.triggerRepaint()
        logger.info(
            "Phase 4: Created per-item clue layer '%s' (item_id=%s) under Map Tools/Clues",
            name, item_id
        )
        return item_id

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
                   attachment_path: Optional[str] = None) -> Union[int, str]:
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

        # BUG-072 FIX: Cross-validate WGS84 and Irish Grid coordinates
        self._validate_irish_grid_consistency(lat, lon, irish_grid_e, irish_grid_n)

        # Phase 4: Check if we should use per-item layers
        if self._uses_per_item_layers("hazard"):
            return self._add_hazard_per_item(
                name=name, lat=lat, lon=lon,
                hazard_type=hazard_type, severity=severity, description=description,
                irish_grid_e=irish_grid_e, irish_grid_n=irish_grid_n,
                coordinator_ids=coordinator_ids, updated_by=updated_by,
                attachment_path=attachment_path
            )

        # Legacy path: shared layer
        return self._add_hazard_shared_layer(
            name=name, lat=lat, lon=lon,
            hazard_type=hazard_type, severity=severity, description=description,
            irish_grid_e=irish_grid_e, irish_grid_n=irish_grid_n,
            coordinator_ids=coordinator_ids, updated_by=updated_by,
            attachment_path=attachment_path
        )

    def _add_hazard_shared_layer(
        self, name: str, lat: float, lon: float,
        hazard_type: str, severity: str, description: str,
        irish_grid_e: Optional[float], irish_grid_n: Optional[float],
        coordinator_ids: Optional[str], updated_by: Optional[str],
        attachment_path: Optional[str]
    ) -> str:
        """Legacy implementation: Add hazard to shared layer."""
        layer = self._get_or_create_hazards_layer()

        feature = QgsFeature(layer.fields())
        feature.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(lon, lat)))

        marker_id = str(uuid.uuid4())
        created_ts = self._current_timestamp()
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

        with self._layer_transaction(layer, self.HAZARDS_LAYER_NAME, "add marker") as edit_layer:
            if not edit_layer.addFeature(feature):
                raise RuntimeError(f"Failed to add feature to {self.HAZARDS_LAYER_NAME} layer")

        layer.triggerRepaint()
        self._log_marker_event(layer, self._marker_log_label("hazard"), "add", marker_id=marker_id, name=name)
        return marker_id

    def _add_hazard_per_item(
        self, name: str, lat: float, lon: float,
        hazard_type: str, severity: str, description: str,
        irish_grid_e: Optional[float], irish_grid_n: Optional[float],
        coordinator_ids: Optional[str], updated_by: Optional[str],
        attachment_path: Optional[str]
    ) -> str:
        """
        Phase 4: Add hazard as a per-item layer.

        Creates an individual GeoPackage-backed layer for this hazard marker,
        placed under "SAR Tracker / Map Tools / Hazards /".

        Returns:
            str: item_id (which serves as the marker_id)
        """
        factory = self._get_per_item_factory()
        if not factory:
            # Fallback to shared layer if no mission store configured
            logger.warning("Phase 4: No factory available, falling back to shared layer for hazard")
            return self._add_hazard_shared_layer(
                name=name, lat=lat, lon=lon,
                hazard_type=hazard_type, severity=severity, description=description,
                irish_grid_e=irish_grid_e, irish_grid_n=irish_grid_n,
                coordinator_ids=coordinator_ids, updated_by=updated_by,
                attachment_path=attachment_path
            )

        # Ensure the target group exists
        target_group = self._ensure_per_item_group(ItemType.MARKER_HAZARD)

        # Define fields for the hazard layer (matching schema)
        hazard_fields = [
            {"name": "id", "type": "String", "length": 50},
            {"name": "name", "type": "String", "length": 255},
            {"name": "hazard_type", "type": "String", "length": 100},
            {"name": "severity", "type": "String", "length": 50},
            {"name": "description", "type": "String", "length": 1000},
            {"name": "lat", "type": "Double"},
            {"name": "lon", "type": "Double"},
            {"name": "irish_grid_e", "type": "Double"},
            {"name": "irish_grid_n", "type": "Double"},
            {"name": "created", "type": "String", "length": 50},
            {"name": "created_at", "type": "String", "length": 50},
            {"name": "updated_at", "type": "String", "length": 50},
            {"name": "updated_by", "type": "String", "length": 255},
            {"name": "coordinator_ids", "type": "String", "length": 500},
            {"name": "attachment_path", "type": "String", "length": 500},
        ]

        # Create the per-item layer
        try:
            item_info = factory.create_item_layer(
                item_type=ItemType.MARKER_HAZARD,
                display_name=name,
                fields=hazard_fields,
                add_to_project=True,
                target_group=target_group
            )
        except Exception as e:
            logger.error("Phase 4: Failed to create per-item layer for hazard '%s': %s", name, e)
            raise RuntimeError(f"Failed to create per-item hazard layer: {e}") from e

        layer = item_info.layer
        item_id = item_info.item_id

        if not layer or not layer.isValid():
            raise RuntimeError(f"Per-item layer created but invalid for hazard '{name}'")

        # Create and add the feature to the layer
        feature = QgsFeature(layer.fields())
        feature.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(lon, lat)))

        created_ts = datetime.now(timezone.utc).isoformat()
        attributes = {
            "id": item_id,  # Use item_id as the marker id
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

        # Add feature to layer
        try:
            with self._layer_transaction(layer, name, "add hazard feature") as edit_layer:
                if not edit_layer.addFeature(feature):
                    raise RuntimeError(f"Failed to add feature to per-item hazard layer '{name}'")
        except Exception:
            self._cleanup_failed_per_item_layer(factory, item_id, "hazard")
            raise

        # Apply styling
        self._style_hazards_layer(layer)

        layer.triggerRepaint()
        logger.info(
            "Phase 4: Created per-item hazard layer '%s' (item_id=%s) under Map Tools/Hazards",
            name, item_id
        )
        return item_id

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
                     attachment_path: Optional[str] = None) -> Union[int, str]:
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

        # BUG-072 FIX: Cross-validate WGS84 and Irish Grid coordinates
        self._validate_irish_grid_consistency(lat, lon, irish_grid_e, irish_grid_n)

        # Phase 4: Check if we should use per-item layers
        if self._uses_per_item_layers("casualty"):
            return self._add_casualty_per_item(
                name=name, lat=lat, lon=lon,
                condition=condition, treatment=treatment,
                evacuation_priority=evacuation_priority,
                description=description, found_by=found_by,
                irish_grid_e=irish_grid_e, irish_grid_n=irish_grid_n,
                coordinator_ids=coordinator_ids, updated_by=updated_by,
                attachment_path=attachment_path
            )

        # Legacy path: shared layer
        return self._add_casualty_shared_layer(
            name=name, lat=lat, lon=lon,
            condition=condition, treatment=treatment,
            evacuation_priority=evacuation_priority,
            description=description, found_by=found_by,
            irish_grid_e=irish_grid_e, irish_grid_n=irish_grid_n,
            coordinator_ids=coordinator_ids, updated_by=updated_by,
            attachment_path=attachment_path
        )

    def _add_casualty_shared_layer(
        self, name: str, lat: float, lon: float,
        condition: str, treatment: str, evacuation_priority: str,
        description: str, found_by: str,
        irish_grid_e: Optional[float], irish_grid_n: Optional[float],
        coordinator_ids: Optional[str], updated_by: Optional[str],
        attachment_path: Optional[str]
    ) -> str:
        """Legacy implementation: Add casualty to shared layer."""
        layer = self._get_or_create_casualties_layer()

        feature = QgsFeature(layer.fields())
        feature.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(lon, lat)))

        marker_id = str(uuid.uuid4())
        created_ts = self._current_timestamp()
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

        with self._layer_transaction(layer, self.CASUALTIES_LAYER_NAME, "add marker") as edit_layer:
            if not edit_layer.addFeature(feature):
                raise RuntimeError(f"Failed to add feature to {self.CASUALTIES_LAYER_NAME} layer")

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

    def _add_casualty_per_item(
        self, name: str, lat: float, lon: float,
        condition: str, treatment: str, evacuation_priority: str,
        description: str, found_by: str,
        irish_grid_e: Optional[float], irish_grid_n: Optional[float],
        coordinator_ids: Optional[str], updated_by: Optional[str],
        attachment_path: Optional[str]
    ) -> str:
        """
        Phase 4: Add casualty as a per-item layer.

        Creates an individual GeoPackage-backed layer for this casualty marker,
        placed under "SAR Tracker / Map Tools / Casualties /".

        CRITICAL: Casualties are found injured or deceased persons.
        This is distinct from clues (evidence). Casualties trigger:
        - Medical response and evacuation
        - Legal/coroner documentation
        - Family notifications
        - Mission reporting requirements

        Returns:
            str: item_id (which serves as the marker_id)
        """
        factory = self._get_per_item_factory()
        if not factory:
            # Fallback to shared layer if no mission store configured
            logger.warning("Phase 4: No factory available, falling back to shared layer for casualty")
            return self._add_casualty_shared_layer(
                name=name, lat=lat, lon=lon,
                condition=condition, treatment=treatment,
                evacuation_priority=evacuation_priority,
                description=description, found_by=found_by,
                irish_grid_e=irish_grid_e, irish_grid_n=irish_grid_n,
                coordinator_ids=coordinator_ids, updated_by=updated_by,
                attachment_path=attachment_path
            )

        # Ensure the target group exists
        target_group = self._ensure_per_item_group(ItemType.MARKER_CASUALTY)

        # Define fields for the casualty layer (matching schema)
        casualty_fields = [
            {"name": "id", "type": "String", "length": 50},
            {"name": "name", "type": "String", "length": 255},
            {"name": "condition", "type": "String", "length": 100},
            {"name": "treatment", "type": "String", "length": 255},
            {"name": "evacuation_priority", "type": "String", "length": 50},
            {"name": "description", "type": "String", "length": 1000},
            {"name": "found_by", "type": "String", "length": 255},
            {"name": "lat", "type": "Double"},
            {"name": "lon", "type": "Double"},
            {"name": "irish_grid_e", "type": "Double"},
            {"name": "irish_grid_n", "type": "Double"},
            {"name": "created", "type": "String", "length": 50},
            {"name": "created_at", "type": "String", "length": 50},
            {"name": "updated_at", "type": "String", "length": 50},
            {"name": "updated_by", "type": "String", "length": 255},
            {"name": "coordinator_ids", "type": "String", "length": 500},
            {"name": "attachment_path", "type": "String", "length": 500},
        ]

        # Create the per-item layer
        try:
            item_info = factory.create_item_layer(
                item_type=ItemType.MARKER_CASUALTY,
                display_name=name,
                fields=casualty_fields,
                add_to_project=True,
                target_group=target_group
            )
        except Exception as e:
            logger.error("Phase 4: Failed to create per-item layer for casualty '%s': %s", name, e)
            raise RuntimeError(f"Failed to create per-item casualty layer: {e}") from e

        layer = item_info.layer
        item_id = item_info.item_id

        if not layer or not layer.isValid():
            raise RuntimeError(f"Per-item layer created but invalid for casualty '{name}'")

        # Create and add the feature to the layer
        feature = QgsFeature(layer.fields())
        feature.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(lon, lat)))

        created_ts = datetime.now(timezone.utc).isoformat()
        attributes = {
            "id": item_id,  # Use item_id as the marker id
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

        # Add feature to layer
        try:
            with self._layer_transaction(layer, name, "add casualty feature") as edit_layer:
                if not edit_layer.addFeature(feature):
                    raise RuntimeError(f"Failed to add feature to per-item casualty layer '{name}'")
        except Exception:
            self._cleanup_failed_per_item_layer(factory, item_id, "casualty")
            raise

        # Apply styling
        self._style_casualties_layer(layer)

        layer.triggerRepaint()
        logger.info(
            "Phase 4: Created per-item casualty layer '%s' (item_id=%s) under Map Tools/Casualties",
            name, item_id
        )
        return item_id

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
        # BUG-059 FIX: Add explicit geometry type validation before coordinate extraction
        if (lat is None or lon is None) and feature.geometry() and not feature.geometry().isEmpty():
            geom = feature.geometry()
            # Only extract coordinates from valid point geometries
            from qgis.core import QgsWkbTypes
            geom_type = geom.type()
            if geom_type == QgsWkbTypes.PointGeometry:
                point = geom.asPoint()
                # Validate extracted point is not empty (0,0 could indicate invalid extraction)
                if point and not (point.x() == 0 and point.y() == 0):
                    extracted_lat = point.y()
                    extracted_lon = point.x()
                    # Validate coordinates are in reasonable range
                    if -90 <= extracted_lat <= 90 and -180 <= extracted_lon <= 180:
                        lat = lat if lat is not None else extracted_lat
                        lon = lon if lon is not None else extracted_lon
                        logger.debug(
                            "BUG-059: Extracted coordinates from geometry for marker %s: lat=%s, lon=%s",
                            safe_attr("id"), lat, lon
                        )
                    else:
                        logger.warning(
                            "BUG-059: Invalid coordinates extracted from geometry for marker %s: lat=%s, lon=%s",
                            safe_attr("id"), extracted_lat, extracted_lon
                        )
                else:
                    logger.warning(
                        "BUG-059: Empty or zero-point geometry for marker %s",
                        safe_attr("id")
                    )
            else:
                logger.warning(
                    "BUG-059: Non-point geometry type %s for marker %s, skipping coordinate extraction",
                    geom_type, safe_attr("id")
                )

        record = {
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

        # Add casualty-specific medical triage fields (BUG FIX: CASUALTY-FIELDS)
        if marker_type == "casualty":
            record["condition"] = safe_attr("condition")
            record["treatment"] = safe_attr("treatment")
            record["evacuation_priority"] = safe_attr("evacuation_priority")
            record["found_by"] = safe_attr("found_by")

        return record

    def list_markers(self) -> List[Dict[str, object]]:
        """
        Return all markers across managed layers.

        Phase 4: For marker types using per-item layers, queries the factory
        registry instead of the shared layer.
        """
        records: List[Dict[str, object]] = []
        for marker_type in self.MARKER_TYPE_MAP.keys():
            # Phase 4: Check if this marker type uses per-item layers
            if self._uses_per_item_layers(marker_type):
                try:
                    per_item_records = self._list_markers_per_item(marker_type)
                    records.extend(per_item_records)
                except Exception as exc:
                    # Don't let one marker type failure break the entire list
                    logger.warning("Could not list per-item markers for type %s: %s", marker_type, exc)
            else:
                # Legacy: get from shared layer
                try:
                    layer = self._get_marker_layer(marker_type)
                    for feature in layer.getFeatures():
                        try:
                            records.append(self._feature_to_record(marker_type, layer, feature))
                        except Exception as exc:
                            print(f"[MarkerLayerManager] Warning: Failed to serialize marker {feature['id']}: {exc}")
                except Exception as exc:
                    # Layer might not exist yet
                    logger.debug("Could not list markers for type %s: %s", marker_type, exc)
        return records

    def _list_markers_per_item(self, marker_type: str) -> List[Dict[str, object]]:
        """
        Phase 4: List all markers of a type from per-item layers.

        Queries the factory registry to find all per-item layers of the given type,
        then extracts the feature from each.
        """
        records: List[Dict[str, object]] = []
        factory = self._get_per_item_factory()
        if not factory:
            # No factory, try shared layer as fallback
            try:
                layer = self._get_marker_layer(marker_type)
                for feature in layer.getFeatures():
                    try:
                        records.append(self._feature_to_record(marker_type, layer, feature))
                    except Exception as exc:
                        print(f"[MarkerLayerManager] Warning: Failed to serialize marker {feature['id']}: {exc}")
            except Exception:
                pass
            return records

        # Get the ItemType for this marker type
        item_type = self._get_item_type_for_marker(marker_type)

        # Get all items of this type from the registry - with error handling
        try:
            from ..per_item_layer_factory import registry_get_all_items
            items = registry_get_all_items(factory.gpkg_path, include_deleted=False, item_type=item_type)
        except Exception as e:
            logger.error(
                "Phase 4: Failed to query registry for marker type '%s': %s. "
                "Falling back to shared layer if available.",
                marker_type, e
            )
            # Fallback to shared layer
            try:
                layer = self._get_marker_layer(marker_type)
                for feature in layer.getFeatures():
                    try:
                        records.append(self._feature_to_record(marker_type, layer, feature))
                    except Exception as exc:
                        feature_id = feature.attribute('id') if feature else 'unknown'
                        logger.warning("Failed to serialize marker %s: %s", feature_id, exc)
            except Exception:
                pass
            return records

        for item_info in items:
            # Get the layer for this item
            layer = factory.get_layer_by_item_id(item_info.item_id)
            if not layer or not layer.isValid():
                logger.debug("Phase 4: Skipping orphaned item %s (layer not found)", item_info.item_id)
                continue

            # Per-item layers have exactly one feature
            for feature in layer.getFeatures():
                try:
                    records.append(self._feature_to_record(marker_type, layer, feature))
                except Exception as exc:
                    print(f"[MarkerLayerManager] Warning: Failed to serialize per-item marker {item_info.item_id}: {exc}")

        return records

    def get_marker_feature(self, marker_type: str, marker_id: str) -> Optional[QgsFeature]:
        """
        Return feature for marker id.

        Phase 4: For per-item layers, looks up the layer by item_id and returns
        its single feature.
        """
        # Phase 4: Check if this marker type uses per-item layers
        if self._uses_per_item_layers(marker_type):
            return self._get_marker_feature_per_item(marker_type, marker_id)

        # Legacy path: get from shared layer
        layer = self._get_marker_layer(marker_type)
        return self._get_feature_by_id(layer, marker_id)

    def _get_marker_feature_per_item(self, marker_type: str, marker_id: str) -> Optional[QgsFeature]:
        """
        Phase 4: Get feature from a per-item layer.

        Per-item layers have exactly one feature, identified by the item_id.
        """
        factory = self._get_per_item_factory()
        if not factory:
            # Fallback to shared layer
            layer = self._get_marker_layer(marker_type)
            return self._get_feature_by_id(layer, marker_id)

        layer = factory.get_layer_by_item_id(marker_id)
        if not layer:
            # Not found as per-item layer, try shared layer as fallback
            logger.debug("Phase 4: Marker %s not found as per-item layer, trying shared layer", marker_id)
            try:
                shared_layer = self._get_marker_layer(marker_type)
                return self._get_feature_by_id(shared_layer, marker_id)
            except Exception:
                return None

        # Per-item layers have exactly one feature
        features = list(layer.getFeatures())
        if features:
            return features[0]
        return None

    def update_marker(self, marker_type: str, marker_id: str, updates: Dict[str, object], updated_by: Optional[str] = None) -> bool:
        """
        Update marker attributes.

        Phase 4: For per-item layers, updates the feature in the per-item layer.
        Also optionally updates the layer display name if 'name' is in updates.

        Args:
            marker_type: Type of marker
            marker_id: UUID/item_id of the marker
            updates: Dictionary of field names to new values
            updated_by: Optional user identifier for audit trail

        Returns:
            True if update successful
        """
        # Phase 4: Check if this marker type uses per-item layers
        if self._uses_per_item_layers(marker_type):
            return self._update_marker_per_item(marker_type, marker_id, updates, updated_by)

        # Legacy path: update feature in shared layer
        return self._update_marker_shared_layer(marker_type, marker_id, updates, updated_by)

    def _update_marker_shared_layer(
        self, marker_type: str, marker_id: str,
        updates: Dict[str, object], updated_by: Optional[str]
    ) -> bool:
        """Legacy implementation: Update feature in shared layer."""
        layer = self._get_marker_layer(marker_type)
        feature = self._get_feature_by_id(layer, marker_id)
        if not feature:
            raise ValueError(f"Marker '{marker_id}' not found for type '{marker_type}'")

        audit_attrs = self._build_audit_attributes(
            include_created=False,
            updated_by=updated_by or updates.get("updated_by"),
            coordinator_ids=updates.get("coordinator_ids"),
            attachment_path=updates.get("attachment_path")
        )
        all_updates = {**(updates or {}), **audit_attrs}

        with self._layer_transaction(layer, layer.name(), "update marker") as edit_layer:
            fields = edit_layer.fields()
            for field_name, value in all_updates.items():
                field_index = fields.indexOf(field_name)
                if field_index == -1:
                    continue
                if not edit_layer.changeAttributeValue(feature.id(), field_index, value):
                    raise RuntimeError(f"Failed to update marker '{marker_id}' field '{field_name}'")

        layer.triggerRepaint()
        self._log_marker_event(layer, self._marker_log_label(marker_type), "update", marker_id=marker_id)
        return True

    def _update_marker_per_item(
        self, marker_type: str, marker_id: str,
        updates: Dict[str, object], updated_by: Optional[str]
    ) -> bool:
        """
        Phase 4: Update a per-item marker layer.

        Updates the feature in the per-item layer. Also updates the layer
        display name if 'name' field is being updated.

        Args:
            marker_type: Type of marker
            marker_id: item_id of the per-item layer
            updates: Dictionary of field names to new values
            updated_by: Optional user identifier for audit trail

        Returns:
            True if update successful
        """
        factory = self._get_per_item_factory()
        if not factory:
            # Fallback to shared layer
            logger.warning("Phase 4: No factory available, trying shared layer update for marker %s", marker_id)
            return self._update_marker_shared_layer(marker_type, marker_id, updates, updated_by)

        # Find the per-item layer
        layer = factory.get_layer_by_item_id(marker_id)
        if not layer:
            # Layer not found via factory - try shared layer as fallback
            logger.info(
                "Phase 4: Marker %s not found as per-item layer, trying shared layer",
                marker_id
            )
            return self._update_marker_shared_layer(marker_type, marker_id, updates, updated_by)

        # Per-item layers have exactly one feature - get it
        features = list(layer.getFeatures())
        if not features:
            raise ValueError(f"Per-item layer for marker '{marker_id}' has no features")
        feature = features[0]

        # Build update payload with audit attributes
        audit_attrs = self._build_audit_attributes(
            include_created=False,
            updated_by=updated_by or updates.get("updated_by"),
            coordinator_ids=updates.get("coordinator_ids"),
            attachment_path=updates.get("attachment_path")
        )
        all_updates = {**(updates or {}), **audit_attrs}

        # Update the feature
        with self._layer_transaction(layer, layer.name(), "update per-item marker") as edit_layer:
            fields = edit_layer.fields()
            for field_name, value in all_updates.items():
                field_index = fields.indexOf(field_name)
                if field_index == -1:
                    continue
                if not edit_layer.changeAttributeValue(feature.id(), field_index, value):
                    raise RuntimeError(f"Failed to update per-item marker '{marker_id}' field '{field_name}'")

        # If name was updated, also update the layer display name
        if "name" in updates and updates["name"]:
            new_name = str(updates["name"])
            factory.rename_item_layer(marker_id, new_name)
            logger.info("Phase 4: Renamed per-item layer to '%s' (item_id=%s)", new_name, marker_id)

        layer.triggerRepaint()
        logger.info("Phase 4: Updated per-item marker (type=%s, item_id=%s)", marker_type, marker_id)
        return True

    def delete_marker(self, marker_type: str, marker_id: str) -> bool:
        """
        Delete marker by id.

        Phase 4: For marker types using per-item layers, this deletes the entire
        layer (not just a feature from a shared layer).

        Args:
            marker_type: Type of marker ('clue', 'ipp_lkp', 'hazard', 'casualty')
            marker_id: UUID of the marker to delete

        Returns:
            True if deletion successful

        Raises:
            ValueError: If marker not found
            RuntimeError: If deletion fails
        """
        # Phase 4: Check if this marker type uses per-item layers
        if self._uses_per_item_layers(marker_type):
            return self._delete_marker_per_item(marker_type, marker_id)

        # Legacy path: delete feature from shared layer
        return self._delete_marker_shared_layer(marker_type, marker_id)

    def _delete_marker_shared_layer(self, marker_type: str, marker_id: str) -> bool:
        """Legacy implementation: Delete feature from shared layer."""
        layer = self._get_marker_layer(marker_type)
        feature = self._get_feature_by_id(layer, marker_id)
        if not feature:
            raise ValueError(f"Marker '{marker_id}' not found for type '{marker_type}'")

        with self._layer_transaction(layer, layer.name(), "delete marker") as edit_layer:
            if not edit_layer.deleteFeature(feature.id()):
                raise RuntimeError(f"Failed to delete marker '{marker_id}'")

        layer.triggerRepaint()
        self._log_marker_event(layer, self._marker_log_label(marker_type), "delete", marker_id=marker_id)
        return True

    def _delete_marker_per_item(self, marker_type: str, marker_id: str) -> bool:
        """
        Phase 4: Delete a per-item marker layer.

        The marker_id is the item_id, which identifies the entire layer.
        This removes the layer from the project and optionally the GeoPackage table.

        Args:
            marker_type: Type of marker
            marker_id: item_id of the per-item layer

        Returns:
            True if deletion successful
        """
        factory = self._get_per_item_factory()
        if not factory:
            # If no factory, try the shared layer approach
            logger.warning("Phase 4: No factory available, trying shared layer delete for marker %s", marker_id)
            return self._delete_marker_shared_layer(marker_type, marker_id)

        # Try to find and delete the per-item layer
        layer = factory.get_layer_by_item_id(marker_id)
        if not layer:
            # Layer not found via factory - could be a legacy marker in shared layer
            # Try the shared layer approach as fallback
            logger.info(
                "Phase 4: Marker %s not found as per-item layer, trying shared layer",
                marker_id
            )
            return self._delete_marker_shared_layer(marker_type, marker_id)

        # Delete the per-item layer (removes layer + GeoPackage table + registry entry)
        success = factory.delete_item_layer(
            item_id=marker_id,
            remove_table=False,
            hard_delete=False  # Soft delete for potential recovery
        )

        if not success:
            raise RuntimeError(f"Failed to delete per-item marker layer '{marker_id}'")

        logger.info(
            "Phase 4: Deleted per-item marker layer (type=%s, item_id=%s)",
            marker_type, marker_id
        )
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

    def cleanup(self):
        """
        Clean up marker layer manager resources.

        CRASH FIX: Added to ensure proper resource cleanup during plugin unload.
        Matches the cleanup pattern used by other layer managers.

        Note:
            This method is called by layers_controller.cleanup() during
            plugin shutdown to ensure all resources are properly released.
        """
        try:
            # Clear any cached references in the per-item layer factory
            if hasattr(self, '_per_item_factory') and self._per_item_factory:
                # The factory doesn't currently maintain state that needs cleanup,
                # but we nullify the reference for consistency
                self._per_item_factory = None
                logger.debug("Marker layer manager cleaned up")

            # IMPORTANT: Call parent cleanup to release base resources
            super().cleanup()
        except Exception as e:
            logger.error("Error during marker layer manager cleanup: %s", e)
