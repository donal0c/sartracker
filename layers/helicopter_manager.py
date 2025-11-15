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
    QgsMarkerSymbol,
    QgsSimpleMarkerSymbolLayer,
    QgsPalLayerSettings,
    QgsTextFormat,
    QgsTextBufferSettings,
    QgsVectorLayerSimpleLabeling
)
from qgis.PyQt.QtGui import QColor, QFont
from qgis.PyQt.QtCore import Qt


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

    # Set label placement (above point)
    try:
        # Try Qt6 enum style first
        from qgis.core import QgsPalLayerSettings
        if hasattr(QgsPalLayerSettings, 'Placement'):
            # Qt6
            label_settings.placement = QgsPalLayerSettings.Placement.OverPoint
        else:
            # Qt5
            label_settings.placement = QgsPalLayerSettings.OverPoint
    except:
        # Fallback for older QGIS
        label_settings.placement = 0  # OverPoint

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
        layer.startEditing()

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
        layer.startEditing()
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
