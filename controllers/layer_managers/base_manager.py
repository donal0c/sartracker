# -*- coding: utf-8 -*-
"""
Base Layer Manager

Abstract base class for all SAR layer managers.
Provides common functionality for layer management.

Qt5/Qt6 Compatible: Uses qgis.PyQt for all imports.
"""

from abc import ABC, abstractmethod
from qgis.core import QgsProject, QgsVectorLayer
from qgis.PyQt.QtGui import QColor
import random


class BaseLayerManager(ABC):
    """
    Abstract base class for layer managers.

    Each manager handles creation and management of one or more related layer types.
    Provides common functionality like layer group management and device color management.

    All derived classes must be Qt5/Qt6 compatible:
    - Use qgis.PyQt for all Qt imports
    - Use integer type codes for QgsField (10=String, 2=Int, 6=Double)
    - Never use Qt.Enum or QVariant directly
    """

    # Layer group name - all SAR layers belong to this group
    LAYER_GROUP_NAME = "SAR Tracking"

    def __init__(self, iface):
        """
        Initialize base manager.

        Args:
            iface: QGIS interface object
        """
        self.iface = iface
        self.project = QgsProject.instance()

        # Color management for devices (shared across managers if needed)
        # Key: device_id, Value: QColor
        self.device_colors = {}

    def get_or_create_layer_group(self):
        """
        Get or create SAR Tracking layer group.

        Returns:
            QgsLayerTreeGroup: The SAR Tracking group
        """
        root = self.project.layerTreeRoot()
        group = root.findGroup(self.LAYER_GROUP_NAME)
        if not group:
            group = root.insertGroup(0, self.LAYER_GROUP_NAME)
        return group

    def _get_device_color(self, device_id: str) -> QColor:
        """
        Get consistent color for a device.

        Uses caching to ensure same device always gets same color.
        Generates distinct colors avoiding very dark shades.

        Args:
            device_id: Device identifier string

        Returns:
            QColor: Color for this device
        """
        if device_id not in self.device_colors:
            # Generate a distinct color (avoid very dark colors for visibility)
            self.device_colors[device_id] = QColor(
                random.randint(50, 255),
                random.randint(50, 255),
                random.randint(50, 255)
            )
        return self.device_colors[device_id]

    def _add_layer_to_group(self, layer: QgsVectorLayer, position: int = 0):
        """
        Add layer to SAR Tracking group.

        Args:
            layer: QgsVectorLayer to add
            position: Position in group (0 = top, higher = lower)
        """
        # Add to project without adding to layer tree
        self.project.addMapLayer(layer, False)

        # Get or create the group
        group = self.get_or_create_layer_group()

        # Insert at specified position
        group.insertLayer(position, layer)

    @abstractmethod
    def get_managed_layer_names(self):
        """
        Return list of layer names this manager handles.

        Must be implemented by derived classes to document which layers
        they are responsible for managing.

        Returns:
            List[str]: List of layer names managed by this manager
        """
        pass
