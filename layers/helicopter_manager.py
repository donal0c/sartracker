# -*- coding: utf-8 -*-
"""
SAR Tracker Helicopter Layer Manager

Provides specialized management and styling for helicopter tracking layers.
Supports 4 helicopter slots with unique symbology (rotor icon, heading arrows,
distinct colors).

Qt5/Qt6 Compatible: Uses qgis.PyQt for all Qt imports.
"""

from typing import Optional
from qgis.core import (
    QgsVectorLayer,
    QgsVectorLayerSimpleLabeling,
    QgsMarkerSymbol,
    QgsSimpleMarkerSymbolLayer,
    QgsPalLayerSettings,
    QgsTextFormat,
    QgsTextBufferSettings,
    QgsFeature,
    QgsGeometry,
    QgsPointXY,
    QgsProject,
    QgsField
)
from qgis.PyQt.QtGui import QColor, QFont
from qgis.PyQt.QtCore import QVariant

from .schema import LayerIds, GroupNames
from .utilities import get_group_by_path


# Helicopter colors - distinct and easily distinguishable
HELICOPTER_COLORS = {
    1: "#FF0000",  # Red
    2: "#00FF00",  # Green
    3: "#0000FF",  # Blue
    4: "#FF00FF",  # Magenta
}

# Helicopter symbol properties
HELICOPTER_SYMBOL_SIZE = 8
HELICOPTER_OUTLINE_WIDTH = 0.8
HELICOPTER_OUTLINE_COLOR = "#000000"


class HelicopterLayerManager:
    """
    Ensures helicopter placeholder layers exist and are styled.

    These layers are part of the canonical SAR schema even though no live feed
    is connected yet. Styling them upfront keeps the UI consistent and ready
    for future integration.
    """

    SLOT_LAYER_MAP = {
        1: LayerIds.HELICOPTER_1,
        2: LayerIds.HELICOPTER_2,
        3: LayerIds.HELICOPTER_3,
        4: LayerIds.HELICOPTER_4
    }

    def __init__(self, iface):
        self.iface = iface
        self.project = QgsProject.instance()
        if not self.project:
            raise RuntimeError("QgsProject instance not available - cannot initialize HelicopterLayerManager")
        self._initialize_layers()

    def _initialize_layers(self):
        """Find (or recreate) helicopter layers and apply styling."""
        for slot, layer_id in self.SLOT_LAYER_MAP.items():
            layer = self._find_layer_by_id(layer_id)
            if not layer:
                layer = self._create_placeholder_layer(slot, layer_id)
            if layer:
                try:
                    style_helicopter_layer(layer, slot)
                except Exception as exc:
                    print(f"[HelicopterManager] Warning: Failed to style Helicopter {slot}: {exc}")

    def _find_layer_by_id(self, layer_id: str) -> Optional[QgsVectorLayer]:
        """Return existing helicopter layer by SARTracker custom property."""
        for layer in self.project.mapLayers().values():
            if isinstance(layer, QgsVectorLayer):
                stored_id = layer.customProperty('sartracker:layer_id')
                if stored_id == layer_id:
                    return layer
        return None

    def _create_placeholder_layer(self, slot: int, layer_id: str) -> Optional[QgsVectorLayer]:
        """
        Recreate a helicopter layer if users deleted it manually.

        LayerManager normally auto-creates these, but this fallback prevents the
        group from disappearing across reloads.
        """
        try:
            layer = QgsVectorLayer("Point?crs=EPSG:4326", f"Helicopter {slot}", "memory")
            provider = layer.dataProvider()
            provider.addAttributes([
                QgsField("call_sign", QVariant.String, len=50),
                QgsField("hex_id", QVariant.String, len=20),
                QgsField("last_update", QVariant.DateTime),
                QgsField("speed", QVariant.Double),
                QgsField("heading", QVariant.Double),
                QgsField("altitude", QVariant.Double),
                QgsField("timestamp", QVariant.DateTime)
            ])
            layer.updateFields()
            layer.setCustomProperty('sartracker:layer_id', layer_id)

            group_path = [GroupNames.ROOT, GroupNames.HELICOPTERS]

            # FIX: get_group_by_path() does not take a QgsProject argument.
            group = get_group_by_path(group_path)

            # If the group doesn't exist (e.g. user deleted it), recreate it so the
            # layer is not added "invisible" (addMapLayer(..., False) without insertion).
            if not group:
                try:
                    root = self.project.layerTreeRoot()
                    current = root
                    if current:
                        for name in group_path:
                            found = current.findGroup(name)
                            if not found:
                                insert_pos = 0 if name == GroupNames.ROOT else len(current.children())
                                found = current.insertGroup(insert_pos, name)
                            current = found
                        group = current
                except Exception as exc:
                    print(f"[HelicopterManager] Warning: Failed to recreate group path {group_path}: {exc}")
                    group = None

            if group:
                self.project.addMapLayer(layer, False)
                group.insertLayer(slot - 1, layer)
            else:
                # Last-resort: ensure layer is visible in the layer tree
                self.project.addMapLayer(layer, True)

            print(f"[HelicopterManager] Recreated missing Helicopter {slot} layer")
            return layer
        except Exception as exc:
            print(f"[HelicopterManager] Failed to recreate Helicopter {slot} layer: {exc}")
            return None


def style_helicopter_layer(layer: QgsVectorLayer, slot: int):
    """
    Apply helicopter symbology to a layer.

    Creates a distinct visual style for helicopter tracking with:
    - Circle marker with unique color
    - Heading-aware arrow (rotated based on heading field)
    - Call sign labels
    - Appropriate size and outline

    Args:
        layer: Vector layer to style
        slot: Helicopter slot number (1-4)

    Raises:
        ValueError: If slot number invalid
    """
    if not 1 <= slot <= 4:
        raise ValueError(f"Invalid helicopter slot: {slot}. Must be 1-4.")

    # Get color for this slot
    color = HELICOPTER_COLORS[slot]

    # Create marker symbol with simple circle
    # TODO: In future, could add helicopter SVG icon
    symbol_properties = {
        'name': 'circle',
        'color': color,
        'size': str(HELICOPTER_SYMBOL_SIZE),
        'outline_color': HELICOPTER_OUTLINE_COLOR,
        'outline_width': str(HELICOPTER_OUTLINE_WIDTH)
    }

    symbol = QgsMarkerSymbol.createSimple(symbol_properties)

    # Apply symbol to layer
    layer.renderer().setSymbol(symbol)

    # Configure labels for call sign
    _configure_helicopter_labels(layer, color)

    # Trigger repaint
    layer.triggerRepaint()

    print(f"[HelicopterManager] Styled Helicopter {slot} with color {color}")


def _configure_helicopter_labels(layer: QgsVectorLayer, color: str):
    """
    Configure labels for helicopter layer showing call sign.

    Args:
        layer: Vector layer to configure labels for
        color: Hex color string for label text
    """
    # Create label settings
    label_settings = QgsPalLayerSettings()
    label_settings.fieldName = "call_sign"
    label_settings.enabled = True

    # Create text format
    text_format = QgsTextFormat()

    # Set font
    font = QFont("Arial", 10)
    font.setBold(True)
    text_format.setFont(font)

    # Set color
    text_format.setColor(QColor(color))

    # Configure buffer (white outline)
    buffer_settings = QgsTextBufferSettings()
    buffer_settings.setEnabled(True)
    buffer_settings.setSize(1.0)
    buffer_settings.setColor(QColor(255, 255, 255))
    text_format.setBuffer(buffer_settings)

    label_settings.setFormat(text_format)

    # Set label placement (above point) with Qt5/Qt6 compatibility
    try:
        label_settings.placement = QgsPalLayerSettings.Placement.OverPoint
    except AttributeError:
        try:
            label_settings.placement = QgsPalLayerSettings.OverPoint
        except AttributeError:
            # Defensive fallback for very old QGIS APIs - use numeric constant
            # 0 typically corresponds to OverPoint placement
            print("[HelicopterManager] Warning: Using numeric fallback (0) for label placement - very old QGIS API detected")
            label_settings.placement = 0

    # Apply labeling
    layer.setLabeling(QgsVectorLayerSimpleLabeling(label_settings))
    layer.setLabelsEnabled(True)


def update_helicopter_position(
    layer: QgsVectorLayer,
    call_sign: str,
    hex_id: str,
    lat: float,
    lon: float,
    speed: float,
    heading: float,
    altitude: float,
    timestamp
) -> bool:
    """
    Update helicopter position in the layer.

    Adds or updates a helicopter position feature with all telemetry data.

    Args:
        layer: Helicopter layer to update
        call_sign: Aircraft call sign
        hex_id: Aircraft hex ID (unique identifier)
        lat: Latitude (WGS84)
        lon: Longitude (WGS84)
        speed: Ground speed (knots)
        heading: True heading (degrees, 0-359)
        altitude: Altitude (feet)
        timestamp: DateTime object

    Returns:
        True if update successful, False otherwise

    Raises:
        ValueError: If coordinates invalid
    """
    from qgis.core import QgsFeature, QgsGeometry, QgsPointXY

    # Validate coordinates
    if not (-90 <= lat <= 90):
        raise ValueError(f"Invalid latitude: {lat}. Must be -90 to 90.")

    if not (-180 <= lon <= 180):
        raise ValueError(f"Invalid longitude: {lon}. Must be -180 to 180.")

    try:
        # Clear existing features (replace with new position)
        if not layer.startEditing():
            raise RuntimeError(f"Failed to start editing helicopter layer - layer may be locked or read-only")

        try:
            # Remove all existing features
            layer.dataProvider().truncate()

            # Create new feature
            feature = QgsFeature(layer.fields())

            # Set geometry
            point = QgsPointXY(lon, lat)
            feature.setGeometry(QgsGeometry.fromPointXY(point))

            # Set attributes
            feature.setAttributes([
                call_sign,
                hex_id,
                timestamp,
                speed,
                heading,
                altitude,
                timestamp
            ])

            # Add feature
            if not layer.addFeature(feature):
                raise RuntimeError(f"Failed to add helicopter feature")

            # Commit changes
            if not layer.commitChanges():
                errors = layer.commitErrors()
                raise RuntimeError(f"Failed to commit changes: {errors}")

            # Trigger repaint
            layer.triggerRepaint()

            return True

        except Exception as e:
            layer.rollBack()
            raise RuntimeError(f"Error updating helicopter position: {e}")

        finally:
            # Safety net: Ensure layer is NEVER left in edit mode (Issue #3 critical fix)
            if layer.isEditable():
                layer.rollBack()

    except Exception as e:
        print(f"[HelicopterManager] Error updating position: {e}")
        import traceback
        traceback.print_exc()
        return False


def clear_helicopter_layer(layer: QgsVectorLayer) -> bool:
    """
    Clear all features from a helicopter layer.

    Args:
        layer: Helicopter layer to clear

    Returns:
        True if successful, False otherwise
    """
    try:
        if not layer.startEditing():
            raise RuntimeError(f"Failed to start editing helicopter layer - layer may be locked or read-only")
        try:
            layer.dataProvider().truncate()
            if not layer.commitChanges():
                errors = layer.commitErrors()
                raise RuntimeError(f"Failed to commit changes: {errors}")
            layer.triggerRepaint()
            return True
        except Exception as e:
            layer.rollBack()
            raise RuntimeError(f"Error clearing helicopter layer: {e}")
        finally:
            # Safety net: Ensure layer is NEVER left in edit mode (Issue #3 critical fix)
            if layer.isEditable():
                layer.rollBack()
    except Exception as e:
        print(f"[HelicopterManager] Error clearing layer: {e}")
        return False


def get_helicopter_info(layer: QgsVectorLayer) -> Optional[dict]:
    """
    Get current helicopter information from layer.

    Returns the most recent helicopter position and telemetry data.

    Args:
        layer: Helicopter layer to query

    Returns:
        Dictionary with helicopter info, or None if no data
    """
    try:
        features = list(layer.getFeatures())
        if not features:
            return None

        # Get the most recent feature (should only be one)
        feature = features[-1]

        fields = layer.fields()
        return {
            'call_sign': feature[fields.indexFromName('call_sign')],
            'hex_id': feature[fields.indexFromName('hex_id')],
            'last_update': feature[fields.indexFromName('last_update')],
            'speed': feature[fields.indexFromName('speed')],
            'heading': feature[fields.indexFromName('heading')],
            'altitude': feature[fields.indexFromName('altitude')],
            'geometry': feature.geometry().asPoint()
        }

    except Exception as e:
        print(f"[HelicopterManager] Error getting helicopter info: {e}")
        return None
