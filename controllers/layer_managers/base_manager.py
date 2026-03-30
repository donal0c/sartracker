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
import threading
import logging

logger = logging.getLogger(__name__)

from ...layers import (
    GroupNames,
    LAYER_GROUP_PATHS,
    LAYER_NAME_TO_ID,
    get_layer_by_id,
    LayerManager as SchemaLayerManager
)
from ...utils.exceptions import LayerError


LAYER_DIAGNOSTICS_ENV = "SARTRACKER_LAYER_DIAGNOSTICS"


# BUG-014 FIX: Global layer edit lock to prevent concurrent edit race conditions
# This lock is shared across all manager instances to ensure only one edit
# transaction can occur at a time across the entire plugin.
# LIFE-SAFETY CRITICAL: Prevents data corruption during concurrent operations.
_global_layer_edit_lock = threading.RLock()


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

            new_color = QColor(r, g, b)

            # BUG-052 FIX: Detect color collisions with existing devices
            # If collision detected, adjust color by rotating hue
            for existing_id, existing_color in self.device_colors.items():
                if existing_id != device_id:
                    # Check if colors are too similar (within 30 units on each channel)
                    r_diff = abs(new_color.red() - existing_color.red())
                    g_diff = abs(new_color.green() - existing_color.green())
                    b_diff = abs(new_color.blue() - existing_color.blue())

                    if r_diff < 30 and g_diff < 30 and b_diff < 30:
                        # Collision detected - adjust by rotating color
                        logger.debug(
                            "BUG-052: Color collision detected between '%s' and '%s', adjusting",
                            device_id, existing_id
                        )
                        # Use second half of hash to shift color
                        shift = int.from_bytes(hash_bytes[8:12], byteorder='big')
                        r = 50 + ((r + shift) % 206)
                        g = 50 + ((g + (shift >> 8)) % 206)
                        b = 50 + ((b + (shift >> 16)) % 206)
                        new_color = QColor(r, g, b)
                        break

            self.device_colors[device_id] = new_color

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
        # MEMORY LEAK FIX: Clear device color cache reference
        # Don't clear the dict itself (it's shared), just remove our reference
        # The orchestrator (LayersController) will clear the shared dict
        if hasattr(self, 'device_colors'):
            self.device_colors = None

        # Clear project and interface references
        self.project = None
        self.iface = None

        # Clear layer manager reference
        if hasattr(self, 'layer_manager'):
            self.layer_manager = None

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

    def _require_mission_store(self, operation: str) -> str:
        """
        Ensure mission store is configured for persistent per-item/per-device layers.

        Args:
            operation: Human-friendly operation label for error context

        Returns:
            Mission store path

        Raises:
            LayerError: If no mission store is configured
        """
        layer_manager = self._require_layer_manager()
        effective_getter = getattr(layer_manager, "get_effective_store_path", None)
        if callable(effective_getter):
            store_path = effective_getter()
        else:
            store_path = layer_manager.get_mission_store()
        if store_path:
            return store_path

        message = (
            f"{operation} requires a configured mission store. "
            "Please set a mission store before adding mission data."
        )
        raise LayerError(message, title="Mission Store Required")

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

    def _verify_layer_freshness(self, layer: Optional[QgsVectorLayer], layer_name: str) -> Optional[QgsVectorLayer]:
        """
        BUG-040 FIX: Verify a stored layer reference is still valid and fresh.

        This method should be called when using a previously-obtained layer
        reference to detect stale references that may have become invalid
        since they were acquired.

        Args:
            layer: Previously stored layer reference to verify
            layer_name: Layer name for logging

        Returns:
            The layer if valid and fresh, None if stale/invalid

        Note:
            Does NOT raise exceptions - returns None for stale layers.
            Use _validate_layer_for_edit for stricter validation before edits.
        """
        if layer is None:
            logger.debug("BUG-040: Layer reference is None for '%s'", layer_name)
            return None

        # Check Python object still exists and is valid
        try:
            is_valid = layer.isValid()
        except RuntimeError:
            # C++ object deleted (sip wrapper pointing to deleted object)
            logger.warning(
                "BUG-040: Stale layer reference for '%s' - C++ object deleted",
                layer_name
            )
            return None

        if not is_valid:
            logger.warning(
                "BUG-040: Layer '%s' is no longer valid (source unavailable)",
                layer_name
            )
            return None

        # Verify layer still registered with project
        if self.project:
            try:
                if not self.project.mapLayer(layer.id()):
                    logger.warning(
                        "BUG-040: Layer '%s' no longer registered with project",
                        layer_name
                    )
                    return None
            except Exception as e:
                logger.warning(
                    "BUG-040: Error checking project registration for '%s': %s",
                    layer_name, e
                )
                return None

        return layer

    # ------------------------------------------------------------------
    # BUG-012/BUG-014 FIX: Concurrent Edit Prevention
    # ------------------------------------------------------------------

    @staticmethod
    def acquire_layer_edit_lock(timeout: float = 5.0) -> bool:
        """
        Acquire the global layer edit lock.

        BUG-014 FIX: Provides thread-safe concurrent edit prevention.
        All layer edit operations should acquire this lock before starting
        a transaction to prevent race conditions.

        Args:
            timeout: Maximum time to wait for lock (seconds). Default 5s.

        Returns:
            bool: True if lock acquired, False if timeout occurred.

        LIFE-SAFETY CRITICAL: This lock prevents data corruption during
        concurrent layer modifications which could compromise rescue operations.
        """
        acquired = _global_layer_edit_lock.acquire(timeout=timeout)
        if not acquired:
            logger.warning(
                "Layer edit lock acquisition timed out after %.1fs - "
                "possible deadlock or long-running transaction",
                timeout
            )
        return acquired

    @staticmethod
    def release_layer_edit_lock():
        """
        Release the global layer edit lock.

        BUG-014 FIX: Must be called after completing or aborting a layer
        edit transaction. Always call in a finally block to ensure release.
        """
        try:
            _global_layer_edit_lock.release()
        except RuntimeError:
            # Lock not held - already released or never acquired
            logger.debug("Layer edit lock release called but lock not held")

    def _validate_layer_for_edit(self, layer: Optional[QgsVectorLayer], layer_name: str) -> QgsVectorLayer:
        """
        Validate a layer is suitable for editing operations.

        BUG-012/BUG-013 FIX: Comprehensive validation to prevent operations
        on stale, invalid, or already-locked layers.

        Args:
            layer: Layer to validate
            layer_name: Name for error messages

        Returns:
            QgsVectorLayer: The validated layer

        Raises:
            LayerError: If layer is None, invalid, or unavailable
            LayerLockError: If layer is already in edit mode
        """
        from ...utils.exceptions import LayerError, LayerLockError

        # Check layer exists
        if layer is None:
            raise LayerError(
                f"{layer_name} layer is not available. "
                "The layer may have been deleted or the project changed.",
                layer_name=layer_name
            )

        # Check layer is still valid (not deleted/corrupted)
        if not layer.isValid():
            raise LayerError(
                f"{layer_name} layer is invalid. "
                "The layer data source may be corrupted or unavailable.",
                layer_name=layer_name
            )

        # Check layer is not already being edited (potential nested transaction)
        if layer.isEditable():
            raise LayerLockError(layer_name)

        # Additional validation: check layer still exists in project
        if self.project and not self.project.mapLayer(layer.id()):
            raise LayerError(
                f"{layer_name} layer no longer exists in the project.",
                layer_name=layer_name
            )

        return layer
