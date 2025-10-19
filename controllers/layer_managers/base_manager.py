# -*- coding: utf-8 -*-
"""
Base Layer Manager

Abstract base class for all SAR layer managers.
Provides common functionality for layer management.

Qt5/Qt6 Compatible: Uses qgis.PyQt for all imports.
"""

from abc import ABC, abstractmethod
from typing import Dict, List, Optional
from qgis.core import QgsProject, QgsVectorLayer, QgsLayerTreeGroup
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

    # Class-level shared device color cache for consistency across all managers
    # This ensures the same device ID always gets the same color in all layers
    # Thread safety: This plugin runs in Qt's main event loop (single-threaded).
    # If future versions need multi-threading, this dict should be protected with locks.
    _shared_device_colors = {}

    def __init__(self, iface, shared_device_colors: Optional[Dict[str, QColor]] = None):
        """
        Initialize base manager.

        Args:
            iface: QGIS interface object (QgisInterface)
            shared_device_colors: Optional shared dict for device colors.
                                 If None, uses class-level shared dict.
        """
        self.iface = iface
        self.project = QgsProject.instance()

        # Validate project instance
        if not self.project:
            raise RuntimeError("QgsProject instance not available - cannot initialize manager")

        # Use provided shared dict or fall back to class-level dict
        if shared_device_colors is not None:
            self.device_colors = shared_device_colors
        else:
            self.device_colors = self.__class__._shared_device_colors

    def get_or_create_layer_group(self) -> QgsLayerTreeGroup:
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
        Get consistent, deterministic color for a device.

        Uses device_id hash to ensure same device always gets same color
        across sessions, restarts, and all layers. Generates distinct colors
        avoiding very dark shades for visibility.

        Args:
            device_id: Device identifier string

        Returns:
            QColor: Defensive copy of color for this device

        Raises:
            ValueError: If device_id is empty or invalid
        """
        # Validate device_id
        if not device_id or not isinstance(device_id, str):
            raise ValueError("device_id must be a non-empty string")

        if len(device_id) > 256:
            raise ValueError("device_id exceeds maximum length of 256 characters")

        if device_id not in self.device_colors:
            # Use device_id hash for deterministic color generation
            # This ensures same device always gets same color across sessions
            hash_val = hash(device_id)

            # Generate RGB values from hash (range 50-255 for visibility)
            r = 50 + (abs(hash_val) % 206)
            g = 50 + (abs(hash_val >> 8) % 206)
            b = 50 + (abs(hash_val >> 16) % 206)

            self.device_colors[device_id] = QColor(r, g, b)

        # Return a defensive copy to prevent mutation
        cached_color = self.device_colors[device_id]
        return QColor(cached_color)

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

    def reset_state(self):
        """
        Reset manager state (e.g., after clearing layers).

        Derived classes should override this if they have additional state to reset,
        and should call super().reset_state() in their implementation.
        """
        # Base implementation does nothing - device_colors are shared and managed by orchestrator
        pass

    def cleanup(self):
        """
        Clean up resources when manager is being destroyed.

        Derived classes should call super().cleanup() if they override this.
        """
        # Clear project reference
        self.project = None
        self.iface = None

    @abstractmethod
    def get_managed_layer_names(self) -> List[str]:
        """
        Return list of layer names this manager handles.

        Must be implemented by derived classes to document which layers
        they are responsible for managing.

        Returns:
            List[str]: List of layer names managed by this manager
        """
        pass
