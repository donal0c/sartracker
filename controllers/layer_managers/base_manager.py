# -*- coding: utf-8 -*-
"""
Base Layer Manager

Abstract base class for all SAR layer managers.
Provides common functionality for layer management.

Qt5/Qt6 Compatible: Uses qgis.PyQt for all imports.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional
from qgis.core import QgsProject, QgsVectorLayer, QgsLayerTreeGroup
from qgis.PyQt.QtGui import QColor
import hashlib
import os

from ...layers import (
    GroupNames,
    LAYER_GROUP_PATHS,
    LAYER_NAME_TO_ID,
    get_layer_by_id,
    LayerManager as SchemaLayerManager
)


LAYER_DIAGNOSTICS_ENV = "SARTRACKER_LAYER_DIAGNOSTICS"


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
    LAYER_GROUP_NAME = GroupNames.ROOT

    # Class-level shared device color cache for consistency across all managers
    # This ensures the same device ID always gets the same color in all layers
    # Thread safety: This plugin runs in Qt's main event loop (single-threaded).
    # If future versions need multi-threading, this dict should be protected with locks.
    _shared_device_colors = {}

    _layer_diag_flag = os.environ.get(LAYER_DIAGNOSTICS_ENV, "").strip().lower() in ("1", "true", "yes", "on")

    def __init__(self, iface, shared_device_colors: Optional[Dict[str, QColor]] = None, layer_manager: Optional[SchemaLayerManager] = None):
        """
        Initialize base manager.

        Args:
            iface: QGIS interface object (QgisInterface)
            shared_device_colors: Optional shared dict for device colors.
                                 If None, uses class-level shared dict.
            layer_manager: Shared LayerManager instance for persistent layers.
        """
        self.iface = iface
        self.project = QgsProject.instance()
        self._layer_diag_enabled = self.__class__._layer_diag_flag
        self.layer_manager = layer_manager

        # Validate project instance
        if not self.project:
            raise RuntimeError("QgsProject instance not available - cannot initialize manager")

        # Use provided shared dict or fall back to class-level dict
        if shared_device_colors is not None:
            self.device_colors = shared_device_colors
        else:
            self.device_colors = self.__class__._shared_device_colors

        if self._layer_diag_enabled:
            self._log_manager_event("initialized")
            self._log_existing_managed_layers_snapshot()

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

        Uses stable MD5 hash to ensure same device always gets same color
        across sessions, Python restarts, and all layers. Python's built-in
        hash() uses randomization (PEP 456) which makes colors non-deterministic.

        Generates distinct colors avoiding very dark shades for visibility.

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
            # Use MD5 hash for deterministic color generation
            # Unlike Python's hash(), MD5 is stable across sessions/restarts
            # This ensures same device always gets same color
            hash_bytes = hashlib.md5(device_id.encode('utf-8')).digest()

            # Convert first 12 bytes to integers for RGB
            hash_int = int.from_bytes(hash_bytes[:12], byteorder='big')

            # Generate RGB values from hash (range 50-255 for visibility)
            # Use different byte ranges for better color distribution
            r = 50 + (hash_int % 206)
            g = 50 + ((hash_int >> 16) % 206)
            b = 50 + ((hash_int >> 32) % 206)

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
        target_path = LAYER_GROUP_PATHS.get(layer.name(), [GroupNames.ROOT])
        target_group = self._ensure_group_path(target_path)

        root = self.project.layerTreeRoot()
        layer_node = root.findLayer(layer.id()) if root else None

        if layer_node:
            current_parent = layer_node.parent()
            if current_parent != target_group:
                if current_parent:
                    current_parent.removeChildNode(layer_node)
                target_group.insertChildNode(position, layer_node)
        else:
            self.project.addMapLayer(layer, False)
            target_group.insertLayer(position, layer)

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

    def _ensure_group_path(self, path: List[str]) -> QgsLayerTreeGroup:
        """Ensure a group path exists and return the terminal group."""
        root = self.project.layerTreeRoot()
        current = root
        for name in path:
            group = current.findGroup(name)
            if not group:
                group = current.insertGroup(len(current.children()), name)
            current = group
        return current

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

    # ------------------------------------------------------------------
    # Diagnostics helpers (Phase 0 instrumentation)
    # ------------------------------------------------------------------

    def _log_layer_snapshot(self, layer: Optional[QgsVectorLayer], context: str, extra: Optional[Dict[str, Any]] = None):
        """Emit structured diagnostics about a managed layer when enabled."""
        if not self._layer_diag_enabled or layer is None:
            return

        try:
            provider = layer.providerType()
            storage = layer.storageType() or ""
            schema_id = layer.customProperty('sartracker:layer_id') or ""
            message_parts = [
                "[SARTRACKER][LayerDiagnostics]",
                self.__class__.__name__,
                f"context={context}",
                f"name={layer.name()}",
                f"provider={provider}",
                f"storage={storage or 'memory'}",
                f"features={layer.featureCount()}",
                f"editable={layer.isEditable()}",
                f"valid={layer.isValid()}",
                f"layer_id={layer.id()}",
            ]

            if schema_id:
                message_parts.append(f"sar_id={schema_id}")

            if extra:
                message_parts.append(f"extra={extra}")

            print(" | ".join(message_parts))

        except Exception as exc:
            print(f"[SARTRACKER][LayerDiagnostics] {self.__class__.__name__} failed to log layer context '{context}': {exc}")

    def _log_existing_managed_layers_snapshot(self):
        """Log the state of any existing managed layers at initialization."""
        if not self._layer_diag_enabled:
            return

        try:
            managed_layer_names = self.get_managed_layer_names()
        except Exception as exc:
            print(f"[SARTRACKER][LayerDiagnostics] {self.__class__.__name__} could not enumerate managed layers: {exc}")
            return

        if not managed_layer_names:
            self._log_manager_event("no managed layers declared")
            return

        for layer_name in managed_layer_names:
            layers = self.project.mapLayersByName(layer_name)
            if not layers:
                self._log_manager_event(f"{layer_name}: not present in project during init")
                continue
            for layer in layers:
                self._log_layer_snapshot(layer, f"init::{layer_name}")

    def _log_manager_event(self, message: str):
        """Helper for manager-level diagnostic prints."""
        if self._layer_diag_enabled:
            print(f"[SARTRACKER][LayerDiagnostics] {self.__class__.__name__}: {message}")

    # ------------------------------------------------------------------
    # Layer manager helpers
    # ------------------------------------------------------------------

    def _require_layer_manager(self) -> SchemaLayerManager:
        if self.layer_manager:
            return self.layer_manager
        self.layer_manager = SchemaLayerManager(self.iface)
        return self.layer_manager

    def _ensure_schema_layer(self, layer_id: str, fallback_name: Optional[str] = None, style_factory=None) -> QgsVectorLayer:
        """Ensure a schema-defined layer exists (memory or mission store)."""
        layer_manager = self._require_layer_manager()
        layer_def = get_layer_by_id(layer_id)
        if not layer_def:
            raise ValueError(f"Unknown layer id: {layer_id}")

        candidate_names = [layer_def.name]
        candidate_names.extend(
            name for name, mapped_id in LAYER_NAME_TO_ID.items()
            if mapped_id == layer_id and name not in candidate_names
        )
        if fallback_name and fallback_name not in candidate_names:
            candidate_names.append(fallback_name)

        group_path = None
        for name in candidate_names:
            group_path = LAYER_GROUP_PATHS.get(name)
            if group_path:
                break
        if not group_path:
            group_path = [GroupNames.ROOT]

        return layer_manager.ensure_vector_layer(
            layer_def,
            group_path,
            style_factory=style_factory
        )

    def _get_layer_by_id(self, layer_id: str) -> Optional[QgsVectorLayer]:
        return self._require_layer_manager().get_layer(layer_id)
