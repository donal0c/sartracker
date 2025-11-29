# -*- coding: utf-8 -*-
"""
SAR Tracker Layer Utilities

Provides utility functions for layer operations including selection,
attribute table management, and UI interactions.

Qt5/Qt6 Compatible: Uses qgis.PyQt for all Qt imports.
"""

from typing import List, Optional
from qgis.core import QgsProject, QgsVectorLayer, QgsLayerTreeGroup
from qgis.PyQt.QtWidgets import QDialog


def select_group_in_layer_panel(iface, path: List[str]) -> bool:
    """
    Select and expand a group in the layer panel.

    Makes a specific layer group visible and selected in the QGIS
    layer panel, useful for drawing user attention to specific layers.

    Args:
        iface: QGIS interface instance
        path: List of group names from root to target

    Returns:
        True if group found and selected, False otherwise

    Example:
        select_group_in_layer_panel(iface, ['SAR Tracker', 'Helicopters'])
    """
    try:
        # Get layer tree view
        layer_tree_view = iface.layerTreeView()
        if not layer_tree_view:
            print("[LayerUtils] Layer tree view not available")
            return False

        # Navigate to group
        root = QgsProject.instance().layerTreeRoot()
        current = root

        for group_name in path:
            group = current.findGroup(group_name)
            if not group:
                print(f"[LayerUtils] Group not found: {group_name}")
                return False
            current = group

        # Get model index for the group
        model = layer_tree_view.model()
        index = model.node2index(current)

        if not index.isValid():
            print("[LayerUtils] Invalid model index for group")
            return False

        # Select the group
        layer_tree_view.setCurrentIndex(index)

        # Expand the group
        layer_tree_view.setExpanded(index, True)

        print(f"[LayerUtils] Selected group: {'/'.join(path)}")
        return True

    except Exception as e:
        print(f"[LayerUtils] Error selecting group: {e}")
        import traceback
        traceback.print_exc()
        return False


def open_attribute_table(iface, layer: QgsVectorLayer) -> bool:
    """
    Open the attribute table for a layer.

    Opens the QGIS attribute table dialog for the specified layer,
    useful for reviewing or editing layer data.

    Args:
        iface: QGIS interface instance
        layer: Vector layer to open attribute table for

    Returns:
        True if attribute table opened, False otherwise

    Example:
        layer = layer_manager.get_layer(LayerIds.MARKERS_CLUES)
        open_attribute_table(iface, layer)
    """
    try:
        if not layer or not layer.isValid():
            print("[LayerUtils] Invalid layer")
            return False

        # Open attribute table
        iface.showAttributeTable(layer)
        print(f"[LayerUtils] Opened attribute table for: {layer.name()}")
        return True

    except Exception as e:
        print(f"[LayerUtils] Error opening attribute table: {e}")
        import traceback
        traceback.print_exc()
        return False


def set_active_layer(iface, layer: QgsVectorLayer) -> bool:
    """
    Set a layer as the active layer in QGIS.

    Makes the specified layer the active layer, which affects
    various QGIS operations and tools.

    Args:
        iface: QGIS interface instance
        layer: Vector layer to set as active

    Returns:
        True if layer set as active, False otherwise
    """
    try:
        if not layer or not layer.isValid():
            print("[LayerUtils] Invalid layer")
            return False

        iface.setActiveLayer(layer)
        print(f"[LayerUtils] Set active layer: {layer.name()}")
        return True

    except Exception as e:
        print(f"[LayerUtils] Error setting active layer: {e}")
        return False


def zoom_to_layer(iface, layer: QgsVectorLayer) -> bool:
    """
    Zoom the map canvas to show a layer's extent.

    Adjusts the map canvas view to show all features in the layer.

    Args:
        iface: QGIS interface instance
        layer: Vector layer to zoom to

    Returns:
        True if zoom successful, False otherwise
    """
    try:
        if not layer or not layer.isValid():
            print("[LayerUtils] Invalid layer")
            return False

        # Get layer extent
        extent = layer.extent()
        if extent.isEmpty():
            print(f"[LayerUtils] Layer has no features: {layer.name()}")
            return False

        # Zoom to extent
        canvas = iface.mapCanvas()
        canvas.setExtent(extent)
        canvas.refresh()

        print(f"[LayerUtils] Zoomed to layer: {layer.name()}")
        return True

    except Exception as e:
        print(f"[LayerUtils] Error zooming to layer: {e}")
        return False


def get_group_by_path(path: List[str]) -> Optional[QgsLayerTreeGroup]:
    """
    Get a layer tree group by its path.

    Args:
        path: List of group names from root to target

    Returns:
        QgsLayerTreeGroup if found, None otherwise
    """
    try:
        root = QgsProject.instance().layerTreeRoot()
        current = root

        for group_name in path:
            group = current.findGroup(group_name)
            if not group:
                return None
            current = group

        return current

    except Exception as e:
        print(f"[LayerUtils] Error getting group: {e}")
        return None


def count_features_in_layer(layer: QgsVectorLayer) -> int:
    """
    Count the number of features in a layer.

    Args:
        layer: Vector layer to count features in

    Returns:
        Number of features, or 0 if error
    """
    try:
        if not layer or not layer.isValid():
            import logging
            logger = logging.getLogger(__name__)
            logger.warning("Feature count retrieval attempted with invalid layer")
            return 0
        return layer.featureCount()
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.warning(f"Error retrieving feature count: {str(e)}")
        return 0  # Preserve existing behavior


def get_layer_statistics(layer: QgsVectorLayer) -> dict:
    """
    Get basic statistics about a layer.

    Returns information about feature count, geometry type,
    CRS, and field names.

    Args:
        layer: Vector layer to analyze

    Returns:
        Dictionary with layer statistics
    """
    try:
        if not layer or not layer.isValid():
            return {"error": "Invalid layer"}

        stats = {
            "name": layer.name(),
            "feature_count": layer.featureCount(),
            "geometry_type": layer.geometryType(),
            "crs": layer.crs().authid(),
            "fields": [field.name() for field in layer.fields()],
            "is_editable": layer.isEditable(),
            "is_valid": layer.isValid()
        }

        return stats

    except Exception as e:
        return {"error": str(e)}


def flash_layer_features(iface, layer: QgsVectorLayer, duration_ms: int = 1000):
    """
    Flash all features in a layer to draw attention.

    Creates a visual flash effect on all features in the layer,
    useful for highlighting search results or important layers.

    Args:
        iface: QGIS interface instance
        layer: Vector layer whose features to flash
        duration_ms: Flash duration in milliseconds (default 1000)
    """
    try:
        if not layer or not layer.isValid():
            print("[LayerUtils] Invalid layer")
            return

        canvas = iface.mapCanvas()
        features = list(layer.getFeatures())

        for feature in features:
            if feature.hasGeometry():
                try:
                    # Flash individual feature
                    canvas.flashFeatureIds(layer, [feature.id()], duration=duration_ms)
                except:
                    # Fallback - this might not work in all QGIS versions
                    pass

        print(f"[LayerUtils] Flashed {len(features)} features in {layer.name()}")

    except Exception as e:
        print(f"[LayerUtils] Error flashing features: {e}")
