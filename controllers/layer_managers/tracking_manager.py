# -*- coding: utf-8 -*-
"""
Tracking Layer Manager

Manages real-time tracking layers: current positions and breadcrumb trails.
Handles device position updates from tracking sources (e.g., Traccar).

Qt5/Qt6 Compatible: Uses qgis.PyQt for all imports.
"""

import logging
import time
from contextlib import contextmanager
from typing import List, Dict, Optional, Any
from datetime import datetime, timedelta, timezone
import os
import shutil
import tempfile

from qgis.core import (
    QgsVectorLayer, QgsFeature, QgsGeometry, QgsField,
    QgsPointXY, QgsCategorizedSymbolRenderer, QgsRendererCategory,
    QgsMarkerSymbol, QgsLineSymbol, QgsPalLayerSettings,
    QgsVectorLayerSimpleLabeling, QgsTextFormat, QgsTextBufferSettings,
    QgsFeatureRequest, QgsVectorFileWriter, QgsCoordinateTransformContext,
    QgsTask, QgsProject, QgsLayerTreeGroup
)
from qgis.PyQt.QtGui import QColor
from qgis.PyQt.QtCore import QVariant, QTimer
from qgis.PyQt.QtWidgets import QApplication

from .base_manager import BaseLayerManager
from .tracking_segments import (
    build_segments_from_positions,
    parse_iso_timestamp,
    sanitize_breadcrumb_positions,
    sanitize_current_positions,
    validate_processed_segments,
)
from ...layers import LayerIds
from ...layers.schema import (
    DEVICE_POSITION_FIELDS,
    DEVICE_TRAIL_FIELDS,
    GroupNames,
    get_per_device_group_path,
)
from ...utils.exceptions import LayerLockError, LayerTransactionError, LayerError
from ...utils.notify import warning as notify_warning
from ..per_item_layer_factory import ItemType, PerItemLayerFactory


logger = logging.getLogger(__name__)


class TrackingLayerManager(BaseLayerManager):
    """
    Manages tracking layers for live device positions and breadcrumb trails.

    Handles:
    - Current Positions: Latest position for each tracked device
    - Breadcrumbs: Historical trail showing device movement

    Features:
    - Categorized styling by device (consistent colors)
    - Automatic trail segmentation on time gaps
    - Efficient layer clearing for live updates
    """

    # Layer names / custom property keys
    CURRENT_LAYER_NAME = "Current Positions"
    BREADCRUMBS_LAYER_NAME = "Breadcrumbs"
    BREADCRUMB_STYLE_MANAGED_PROP = "sartracker:breadcrumbs_style_managed"
    BREADCRUMB_STYLE_INITIALIZED_PROP = "sartracker:breadcrumbs_style_initialized"
    CURRENT_STYLE_MANAGED_PROP = "sartracker:current_style_managed"
    CURRENT_STYLE_INITIALIZED_PROP = "sartracker:current_style_initialized"

    ASYNC_SEGMENT_THRESHOLD = 1500  # Minimum breadcrumb points before offloading

    # SAR-7i4 FIX: Increased memory caps for 24-hour multi-device missions
    # Previous limits (10000 segments, 50000 positions) were insufficient for
    # 30 devices over 24 hours (~43,200 positions at 1/minute update rate).
    #
    # New limits support extended missions:
    # - 20,000 segments ≈ 10MB (supports ~48 hours with 30 devices)
    # - 100,000 positions ≈ 40MB (supports ~55 hours with 30 devices at 1/min)
    #
    # User notification added when truncation occurs (see _notify_truncation_warning)
    MAX_BREADCRUMB_SEGMENTS = 20000  # Was 10000 (SAR-7i4)

    # Track if truncation warning has been shown this session
    _truncation_warned = False

    # =========================================================================
    # Phase SAR-nh9: Per-Device Tracking Feature Flags
    # =========================================================================
    # These flags enable gradual rollout and easy rollback of per-device layers.
    # Set to True to enable per-device architecture, False for shared layers.

    USE_PER_DEVICE_POSITIONS = True   # Phase 1: Per-device current position layers
    USE_PER_DEVICE_TRAILS = True      # Phase 2: Per-device trail layers

    # Custom property keys for per-device layer identification
    DEVICE_ID_PROP = "sartracker:device_id"
    DEVICE_NAME_PROP = "sartracker:device_name"
    DEVICE_COLOR_PROP = "sartracker:device_color"

    def __init__(self, iface, shared_device_colors=None, layer_manager=None, task_manager=None):
        """Initialize tracking layer manager."""
        super().__init__(iface, shared_device_colors, layer_manager)
        self.task_manager = task_manager
        self.first_load = True  # Track if this is first data load for auto-zoom
        self._breadcrumb_task_id: Optional[str] = None
        # BUG-BC-001 fix: Track mission generation to prevent stale async data
        self._mission_generation = 0
        # BUG-060 fix: Track temp directories for cleanup
        self._temp_export_dirs: List[str] = []
        self._cleanup_old_temp_dirs()

        # Phase SAR-nh9: Per-device tracking layer caches
        # device_id -> QgsVectorLayer for O(1) lookups
        self._device_position_layers: Dict[str, QgsVectorLayer] = {}
        self._device_trail_layers: Dict[str, QgsVectorLayer] = {}

        # Per-device factory instance (created on first use when mission store exists)
        self._per_device_factory: Optional[PerItemLayerFactory] = None

        # Phase SAR-nj0: Per-device generation tracking for async safety
        # Each device has its own generation counter to detect stale async data
        self._device_generations: Dict[str, int] = {}

    def get_managed_layer_names(self):
        """Return list of layer names this manager handles."""
        return [self.CURRENT_LAYER_NAME, self.BREADCRUMBS_LAYER_NAME]

    def reset_state(self):
        """Reset manager state (called after clearing layers)."""
        super().reset_state()
        self.first_load = True  # Reset auto-zoom flag
        self._cancel_breadcrumb_task()
        # BUG-BC-001 fix: Increment generation to invalidate in-flight async tasks
        self._mission_generation += 1
        # SAR-7i4: Reset truncation warning for new mission
        TrackingLayerManager._truncation_warned = False

        # Phase SAR-nh9: Clear per-device layer caches
        self._device_position_layers.clear()
        self._device_trail_layers.clear()
        self._per_device_factory = None
        # Phase SAR-nj0: Clear per-device generations
        self._device_generations.clear()

    def cleanup(self):
        """Ensure background tasks are cancelled before teardown."""
        self._cancel_breadcrumb_task()
        # BUG-060 fix: Clean up temp export directories
        self._cleanup_temp_dirs()
        super().cleanup()

    def _log_tracking_event(self, layer: QgsVectorLayer, layer_type: str, action: str, **extra):
        """Emit diagnostics for tracking layers when enabled."""
        payload = extra if extra else None
        self._log_layer_snapshot(layer, f"{layer_type}::{action}", payload)

    def _notify_warning(self, title: str, message: str, duration: int = 6):
        """Display a non-blocking warning if iface/messageBar are available."""
        if not getattr(self, "iface", None):
            return
        try:
            bar = self.iface.messageBar() if hasattr(self.iface, "messageBar") else None
            if bar:
                notify_warning(bar, title, message, duration=duration)
        except Exception:
            logger.debug("Failed to display warning '%s': %s", title, message)

    def _report_validation_warning(self, data_label: str, total: int, skipped: int, last_error: Optional[str]):
        """Aggregate validation skips into user-facing + logged warnings."""
        if skipped <= 0:
            return

        msg = f"Skipped {skipped} invalid {data_label.lower()} record{'s' if skipped != 1 else ''}"
        if total:
            msg += f" out of {total}"
        if last_error:
            snippet = last_error if len(last_error) <= 140 else f"{last_error[:137]}..."
            msg += f"; example: {snippet}"

        logger.warning("%s", msg)
        self._notify_warning(f"{data_label} Data", msg)

    def _notify_truncation_warning(self, data_type: str, discarded: int, kept: int, limit: int):
        """
        SAR-7i4 FIX: Notify coordinator when historical data is truncated.

        This is a LIFE-SAFETY notification - coordinators must know when
        early mission data is being discarded to manage memory.

        Args:
            data_type: Type of data being truncated ("breadcrumbs" or "positions")
            discarded: Number of records discarded
            kept: Number of records retained
            limit: The memory limit that triggered truncation
        """
        # Only warn once per session to avoid notification spam
        if TrackingLayerManager._truncation_warned:
            return
        TrackingLayerManager._truncation_warned = True

        msg = (
            f"Memory limit reached: {discarded:,} oldest {data_type} discarded, "
            f"{kept:,} most recent retained. "
            f"For missions >24 hours, consider periodic data export."
        )
        logger.warning("SAR-7i4: %s", msg)
        self._notify_warning("Long Mission Data", msg, duration=10)

    @contextmanager
    def _layer_transaction(self, layer: QgsVectorLayer, layer_name: str, operation: str):
        """Context manager ensuring safe start/commit/rollback semantics."""
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
        Ensure layer exits edit mode, logging/raising if rollback fails.

        Args:
            layer: Target QgsVectorLayer
            layer_name: Human-readable layer name
            context: Diagnostic context string
            raise_on_failure: When True, raise if the layer remains editable

        Returns:
            Optional string describing cleanup issues (None when successful).
        """
        if not layer or not layer.isValid():
            return None

        try:
            editable = layer.isEditable()
        except Exception as exc:
            message = f"isEditable() check failed: {exc}"
            if raise_on_failure:
                raise LayerTransactionError(layer_name, context, details=message) from exc
            logger.critical("Layer %s cleanup state unknown (%s): %s", layer_name, context, message)
            return message

        if not editable:
            return None

        issues = []
        try:
            result = layer.rollBack()
            # rollBack returns bool in QGIS; None indicates failure as well
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
            logger.critical(
                "Layer %s cleanup failed (%s): %s",
                layer_name,
                context,
                message
            )
            return message

        return None

    def _clear_layer_features(self, layer: QgsVectorLayer, layer_name: str):
        """Efficiently clear all features, falling back when truncate unsupported."""
        if layer.featureCount() == 0:
            return

        try:
            layer.dataProvider().truncate()
        except (AttributeError, NotImplementedError, RuntimeError) as exc:
            logger.debug("Truncate not available for %s: %s", layer_name, exc)
            if not layer.deleteFeatures(layer.allFeatureIds()):
                raise RuntimeError(f"Failed to clear features from {layer_name}")

    def _cancel_breadcrumb_task(self):
        """Cancel any inflight breadcrumb segmentation task."""
        task_id = getattr(self, "_breadcrumb_task_id", None)
        task_manager = getattr(self, "task_manager", None)
        if task_manager and task_id:
            try:
                task_manager.cancel_task(task_id)
            except Exception as exc:  # pragma: no cover - best effort cleanup
                logger.debug("Breadcrumb task cancel failed: %s", exc)
        self._breadcrumb_task_id = None

    def _maybe_schedule_breadcrumb_task(
        self,
        positions: Optional[List[Dict]],
        gap_minutes: float,
        total_inputs: int,
        processed_segments: Optional[Dict[str, Any]]
    ) -> bool:
        """
        Decide whether to offload breadcrumb processing to a background task.
        """
        if processed_segments:
            return False
        if not getattr(self, "task_manager", None):
            return False
        if not isinstance(positions, list):
            return False
        if len(positions) < self.ASYNC_SEGMENT_THRESHOLD:
            return False
        return self._start_breadcrumb_task(positions, gap_minutes, total_inputs)

    # SAR-7i4 FIX: Increased maximum positions for extended 24-hour missions
    # Previous limit (50000) was insufficient for 30 devices over 24 hours.
    # New limit supports ~55 hours with 30 devices at 1 position/minute.
    MAX_TASK_POSITIONS = 100000  # Was 50000 (SAR-7i4)

    def _start_breadcrumb_task(self, positions: List[Dict], gap_minutes: float, total_inputs: int) -> bool:
        """
        Create and queue a QgsTask that sanitizes and segments breadcrumbs.

        BUG-042 FIX: Enforces MAX_TASK_POSITIONS limit to prevent memory
        exhaustion in background tasks.
        """
        task_manager = getattr(self, "task_manager", None)
        if not task_manager:
            return False

        create_task = getattr(QgsTask, "fromFunction", None)
        if not create_task:
            return False

        # SAR-7i4 FIX: Memory guard for background task
        # Truncate positions to prevent excessive memory usage in background task
        if len(positions) > self.MAX_TASK_POSITIONS:
            discarded = len(positions) - self.MAX_TASK_POSITIONS
            logger.warning(
                "SAR-7i4: Task memory guard - truncating %d positions to %d for background processing",
                len(positions), self.MAX_TASK_POSITIONS
            )
            positions = positions[-self.MAX_TASK_POSITIONS:]
            total_inputs = self.MAX_TASK_POSITIONS
            # SAR-7i4: Notify coordinator of data truncation
            self._notify_truncation_warning(
                "position records", discarded, self.MAX_TASK_POSITIONS, self.MAX_TASK_POSITIONS
            )

        try:
            positions_snapshot = [dict(pos) for pos in positions]
        except Exception:
            positions_snapshot = list(positions)

        def _worker(task, payload=positions_snapshot, gap=float(gap_minutes)):
            try:
                if hasattr(task, "isCanceled") and task.isCanceled():
                    return False
                sanitized_positions = sanitize_breadcrumb_positions(payload)
                if hasattr(task, "isCanceled") and task.isCanceled():
                    return False
                segments = build_segments_from_positions(sanitized_positions.valid, gap)
                task.setProperty("sartracker:segments", segments)
                task.setProperty("sartracker:invalid_count", sanitized_positions.invalid_count)
                task.setProperty("sartracker:last_error", sanitized_positions.last_error or "")
                return True
            except Exception as exc:
                task.setProperty("sartracker:error", str(exc))
                raise

        task = create_task("Process breadcrumb payload", _worker)
        task.setProperty("sartracker:payload", positions_snapshot)
        task.setProperty("sartracker:total_inputs", total_inputs)
        task.setProperty("sartracker:gap_minutes", gap_minutes)
        # BUG-BC-001 fix: Store mission generation to detect stale data
        task.setProperty("sartracker:mission_generation", self._mission_generation)

        self._cancel_breadcrumb_task()
        task_id = f"tracking:breadcrumbs:{id(task)}"
        self._breadcrumb_task_id = task_manager.start_task(
            task,
            on_complete=self._on_breadcrumb_task_complete,
            on_error=self._on_breadcrumb_task_error,
            task_id=task_id
        )
        logger.info(
            "[TrackingManager] Offloading breadcrumb segmentation (%s points) to background task %s",
            total_inputs,
            task_id
        )
        return True

    def _on_breadcrumb_task_complete(self, task: QgsTask):
        """Handle successful breadcrumb task completion."""
        self._breadcrumb_task_id = None

        # SAFETY: Guard against plugin unload during async task (CLAUDE.md Pattern 4)
        # Task may complete after cleanup() was called
        if not getattr(self, 'iface', None):
            logger.debug("Breadcrumb task complete but iface gone - plugin unloading")
            return
        layer_manager = getattr(self, 'layer_manager', None)
        if not layer_manager:
            logger.debug("Breadcrumb task complete but layer_manager gone - plugin unloading")
            return
        if getattr(layer_manager, "_application_closing", False):
            logger.debug("Breadcrumb task complete during application shutdown - ignoring")
            return

        try:
            # BUG-BC-001 fix: Validate mission generation to prevent stale data
            task_generation = task.property("sartracker:mission_generation")
            if task_generation is not None and task_generation != self._mission_generation:
                logger.info(
                    "Breadcrumb task complete but mission generation changed (%s -> %s) - discarding stale data",
                    task_generation,
                    self._mission_generation
                )
                return

            segments = task.property("sartracker:segments") or []
            total_inputs = task.property("sartracker:total_inputs") or len(segments)
            invalid_count = task.property("sartracker:invalid_count") or 0
            last_error = task.property("sartracker:last_error") or None
            layer = self._get_or_create_breadcrumbs_layer()
            if not layer or not layer.isValid():
                logger.warning("Breadcrumb task complete but layer unavailable")
                return
            # SAR-hi3 FIX: Pass expected generation to close race window
            self._apply_breadcrumb_results(
                layer,
                segments,
                total_inputs,
                invalid_count,
                last_error,
                expected_generation=task_generation
            )
        except Exception as exc:  # pragma: no cover - defensive
            logger.error("Breadcrumb task completion failed: %s", exc)

    def _on_breadcrumb_task_error(self, task: QgsTask):
        """Handle failed breadcrumb background processing by falling back to sync."""
        self._breadcrumb_task_id = None

        # SAFETY: Guard against plugin unload during async task (CLAUDE.md Pattern 4)
        if not getattr(self, 'iface', None):
            logger.debug("Breadcrumb task error but iface gone - plugin unloading")
            return
        layer_manager = getattr(self, 'layer_manager', None)
        if not layer_manager:
            logger.debug("Breadcrumb task error but layer_manager gone - plugin unloading")
            return
        if getattr(layer_manager, "_application_closing", False):
            logger.debug("Breadcrumb task error during application shutdown - ignoring")
            return

        message = task.property("sartracker:error") if hasattr(task, "property") else None
        logger.error("Breadcrumb processing task failed: %s", message or "Unknown error")

        # BUG-BC-001 fix: Validate mission generation to prevent stale data
        task_generation = task.property("sartracker:mission_generation") if hasattr(task, "property") else None
        if task_generation is not None and task_generation != self._mission_generation:
            logger.info(
                "Breadcrumb task error but mission generation changed (%s -> %s) - discarding stale data",
                task_generation,
                self._mission_generation
            )
            return

        payload = task.property("sartracker:payload") if hasattr(task, "property") else None
        gap_minutes = task.property("sartracker:gap_minutes") if hasattr(task, "property") else None

        if isinstance(payload, list):
            try:
                sanitized_positions = sanitize_breadcrumb_positions(payload)
                segments = build_segments_from_positions(
                    sanitized_positions.valid,
                    float(gap_minutes or 5.0)
                )
                layer = self._get_or_create_breadcrumbs_layer()
                if not layer or not layer.isValid():
                    logger.warning("Breadcrumb fallback: layer unavailable")
                    return
                # SAR-hi3 FIX: Pass expected generation to close race window
                self._apply_breadcrumb_results(
                    layer,
                    segments,
                    len(payload),
                    sanitized_positions.invalid_count,
                    sanitized_positions.last_error,
                    expected_generation=task_generation
                )
                return
            except Exception as exc:
                logger.error("Breadcrumb fallback processing also failed: %s", exc)

        self._notify_warning(
            "Breadcrumbs",
            "Breadcrumb processing failed; latest breadcrumb layer may be stale."
        )

    def _apply_breadcrumb_results(
        self,
        layer: QgsVectorLayer,
        segments: List[Dict[str, Any]],
        total_inputs: int,
        invalid_count: int,
        last_error: Optional[str],
        expected_generation: Optional[int] = None
    ):
        """Common render/apply routine for both sync and async breadcrumb updates.

        Args:
            layer: The breadcrumbs layer to update
            segments: List of segment dicts with 'points', 'device_id', 'name'
            total_inputs: Total number of input positions
            invalid_count: Number of invalid positions filtered
            last_error: Last error message if any
            expected_generation: If provided, re-check mission generation atomically
                before writing to layer (SAR-hi3 fix for race condition)
        """
        # SAR-hi3 FIX: Re-check mission generation immediately before layer write
        # This closes the race window between initial check and actual update
        if expected_generation is not None and expected_generation != self._mission_generation:
            logger.info(
                "SAR-hi3: Mission generation changed before layer write (%s -> %s) - discarding stale data",
                expected_generation,
                self._mission_generation
            )
            return

        self._report_validation_warning(
            "Breadcrumbs",
            total_inputs,
            invalid_count,
            last_error
        )

        self._replace_breadcrumb_layer_features(layer, segments or [])

        try:
            self._apply_breadcrumbs_style(layer)
        except Exception as exc:
            logger.warning("Failed to apply breadcrumb styling: %s", exc)

        layer.triggerRepaint()
        self._log_tracking_event(
            layer,
            "BREADCRUMBS",
            "update",
            segments=len(segments or [])
        )

    # =========================================================================
    # Current Positions Layer
    # =========================================================================

    def _get_or_create_current_layer(self) -> QgsVectorLayer:
        """
        Get or create current positions layer.

        Returns:
            QgsVectorLayer: Current positions layer
        """
        layer = self._ensure_schema_layer(
            LayerIds.CURRENT_ACTIVE,
            fallback_name=self.CURRENT_LAYER_NAME
        )
        try:
            if layer.customProperty(self.CURRENT_STYLE_MANAGED_PROP, None) is None:
                layer.setCustomProperty(self.CURRENT_STYLE_MANAGED_PROP, True)
            if layer.customProperty(self.CURRENT_STYLE_INITIALIZED_PROP, None) is None:
                layer.setCustomProperty(self.CURRENT_STYLE_INITIALIZED_PROP, False)
        except Exception:
            pass
        self._log_tracking_event(layer, "CURRENT", "ensure")
        return layer

    def update_current_positions(self, positions: List[Dict]):
        """
        Update current positions layer.

        SAR-lc6 FIX: Uses delta/incremental update pattern instead of clear-all + add-all.
        This reduces map flicker and improves performance with many devices.

        BUG-027 FIX: Uses global layer edit lock to prevent race conditions
        during concurrent position updates from multiple sources.

        Args:
            positions: List of position dicts from tracking provider
                Expected keys: device_id, name, ts, lat, lon,
                              altitude (optional), speed (optional), battery (optional)

        Raises:
            ValueError: If position data is invalid
            LayerLockError: If unable to acquire edit lock (concurrent operation in progress)
        """
        if getattr(getattr(self, "layer_manager", None), "_application_closing", False):
            return

        # Validate positions list
        if not isinstance(positions, list):
            raise ValueError("positions must be a list")

        sanitized = sanitize_current_positions(positions)
        valid_positions = sanitized.valid
        self._report_validation_warning(
            "Current Positions",
            len(positions),
            sanitized.invalid_count,
            sanitized.last_error
        )

        # Phase SAR-nh9: Route to per-device or shared layer implementation
        if self.USE_PER_DEVICE_POSITIONS:
            # Try per-device architecture first
            factory = self._get_per_device_factory()
            if factory:
                try:
                    self._update_positions_per_device(valid_positions)

                    # Zoom to extent ONLY on first load
                    if self.first_load and valid_positions:
                        # Find a device layer to get extent from
                        for device_id in self._device_position_layers:
                            layer = self._device_position_layers[device_id]
                            if layer and layer.isValid() and layer.featureCount() > 0:
                                self.iface.mapCanvas().setExtent(layer.extent())
                                self.iface.mapCanvas().refresh()
                                self.first_load = False
                                break

                    self._log_tracking_event(
                        None,  # No single layer
                        "CURRENT_PER_DEVICE",
                        "update",
                        payload_items=len(valid_positions),
                        device_count=len(set(p.get('device_id') for p in valid_positions if p.get('device_id')))
                    )
                    return  # Successfully updated via per-device layers
                except Exception as e:
                    logger.warning(
                        "SAR-nh9: Per-device update failed, falling back to shared layer: %s", e
                    )
                    # Fall through to shared layer implementation
            else:
                logger.debug("SAR-nh9: No factory available, using shared layer")

        # Shared layer implementation (legacy or fallback)
        # Get or create layer
        layer = self._get_or_create_current_layer()

        # BUG-027 FIX: Acquire global lock to prevent concurrent position updates
        # SAR-z4t FIX: Retry with exponential backoff to prevent dropped updates
        max_retries = 3
        base_timeout = 5.0
        lock_acquired = False
        total_wait_time = 0.0

        for attempt in range(max_retries):
            # Scale timeout based on data size: more positions = longer timeout
            position_factor = 1.0 + (len(valid_positions) / 50.0)  # +1s per 50 positions
            timeout = min(base_timeout * (2 ** attempt) * position_factor, 30.0)  # Cap at 30s

            lock_start = time.monotonic()
            lock_acquired = self.acquire_layer_edit_lock(timeout=timeout)
            lock_duration = time.monotonic() - lock_start
            total_wait_time += lock_duration

            if lock_acquired:
                if attempt > 0 or lock_duration > 1.0:
                    logger.info(
                        "SAR-z4t: Layer lock acquired after %.2fs (attempt %d/%d, %d positions)",
                        total_wait_time, attempt + 1, max_retries, len(valid_positions)
                    )
                break

            logger.warning(
                "SAR-z4t: Lock attempt %d/%d failed after %.1fs, retrying...",
                attempt + 1, max_retries, lock_duration
            )

        if not lock_acquired:
            raise LayerLockError(
                f"{self.CURRENT_LAYER_NAME} - concurrent update in progress after {max_retries} attempts "
                f"({total_wait_time:.1f}s total). Please wait for the current operation to complete."
            )

        try:
            # SAR-lc6 FIX: Delta update pattern - update in place, add new, remove stale
            # This significantly reduces map flicker and renderer recalculation
            updated_count, added_count, removed_count = self._delta_update_current_positions(
                layer, valid_positions
            )

            # Apply styling (outside transaction - failures here don't affect data)
            # Defer by 1 event loop tick to reduce re-entrancy with layer-tree UI edits.
            try:
                layer_id = layer.id()

                def _apply_style_deferred(qgis_layer_id=layer_id):
                    if getattr(getattr(self, "layer_manager", None), "_application_closing", False):
                        return
                    if not getattr(self, "project", None):
                        return
                    try:
                        refreshed_layer = self.project.mapLayer(qgis_layer_id)
                    except Exception:
                        refreshed_layer = None
                    if not refreshed_layer:
                        return
                    try:
                        if not refreshed_layer.isValid():
                            return
                    except RuntimeError:
                        return
                    self._apply_current_positions_style(refreshed_layer)

                QTimer.singleShot(0, _apply_style_deferred)
            except Exception as e:
                logger.warning("Failed to schedule styling for %s: %s", self.CURRENT_LAYER_NAME, e)

            # Zoom to extent ONLY on first load
            if self.first_load and valid_positions:
                self.iface.mapCanvas().setExtent(layer.extent())
                self.iface.mapCanvas().refresh()
                self.first_load = False
            else:
                # Just repaint the layer, not the whole canvas
                layer.triggerRepaint()

            self._log_tracking_event(
                layer,
                "CURRENT",
                "update",
                payload_items=len(valid_positions)
            )
        finally:
            # BUG-027 FIX: Always release lock, even on error
            self.release_layer_edit_lock()

    def _delta_update_current_positions(
        self,
        layer: QgsVectorLayer,
        new_positions: List[Dict]
    ) -> tuple:
        """
        SAR-lc6 FIX: Delta/incremental update for current positions.

        Instead of clear-all + add-all, this method:
        1. Updates existing features in-place if position changed
        2. Adds features for new devices
        3. Removes features for devices no longer present

        This reduces map flicker and renderer recalculation overhead.

        Args:
            layer: The current positions layer
            new_positions: List of validated position dicts

        Returns:
            Tuple of (updated_count, added_count, removed_count)
        """
        # Build lookup of new positions by device_id
        new_by_device = {pos['device_id']: pos for pos in new_positions}
        new_device_ids = set(new_by_device.keys())

        # Get field indices
        fields = layer.fields()
        device_id_idx = fields.indexFromName('device_id')
        if device_id_idx == -1:
            # No device_id field - fall back to full rebuild
            logger.warning("SAR-lc6: device_id field not found, using full rebuild")
            return self._full_rebuild_current_positions(layer, new_positions)

        # Build lookup of existing features by device_id
        existing_features = {}  # device_id -> (feature_id, feature)
        for feature in layer.getFeatures(QgsFeatureRequest()):
            did = feature.attribute(device_id_idx)
            if did is not None:
                existing_features[str(did)] = (feature.id(), feature)

        existing_device_ids = set(existing_features.keys())

        # Determine what needs to change
        devices_to_update = new_device_ids & existing_device_ids
        devices_to_add = new_device_ids - existing_device_ids
        devices_to_remove = existing_device_ids - new_device_ids

        updated_count = 0
        added_count = 0
        removed_count = 0

        # Perform updates in a single transaction
        with self._layer_transaction(layer, self.CURRENT_LAYER_NAME, "delta update positions") as edit_layer:
            # 1. Update existing features (geometry and attributes)
            for device_id in devices_to_update:
                pos = new_by_device[device_id]
                fid, old_feature = existing_features[device_id]

                # Check if geometry actually changed (avoid unnecessary updates)
                old_geom = old_feature.geometry()
                new_point = QgsPointXY(pos['lon'], pos['lat'])
                new_geom = QgsGeometry.fromPointXY(new_point)

                geometry_changed = True
                if old_geom and not old_geom.isNull():
                    old_point = old_geom.asPoint()
                    # Use small epsilon for floating point comparison
                    if abs(old_point.x() - new_point.x()) < 1e-8 and abs(old_point.y() - new_point.y()) < 1e-8:
                        geometry_changed = False

                if geometry_changed:
                    if not edit_layer.changeGeometry(fid, new_geom):
                        logger.warning("SAR-lc6: Failed to update geometry for device %s", device_id)
                        continue

                # Update attributes
                attr_map = {
                    "name": pos.get("name"),
                    "timestamp": pos.get("ts"),
                    "altitude": pos.get("altitude"),
                    "speed": pos.get("speed"),
                    "battery": pos.get("battery"),
                }
                for field_name, value in attr_map.items():
                    idx = fields.indexFromName(field_name)
                    if idx != -1:
                        edit_layer.changeAttributeValue(fid, idx, value)

                updated_count += 1

            # 2. Add new devices
            for device_id in devices_to_add:
                pos = new_by_device[device_id]
                feature = QgsFeature(edit_layer.fields())
                feature.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(pos['lon'], pos['lat'])))

                attr_map = {
                    "device_id": pos.get("device_id"),
                    "name": pos.get("name"),
                    "timestamp": pos.get("ts"),
                    "altitude": pos.get("altitude"),
                    "speed": pos.get("speed"),
                    "battery": pos.get("battery"),
                }
                for field_name, value in attr_map.items():
                    idx = fields.indexFromName(field_name)
                    if idx != -1:
                        feature.setAttribute(idx, value)

                if not edit_layer.addFeature(feature):
                    logger.warning("SAR-lc6: Failed to add feature for device %s", device_id)
                    continue
                added_count += 1

            # 3. Remove stale devices
            if devices_to_remove:
                fids_to_remove = [existing_features[did][0] for did in devices_to_remove]
                if not edit_layer.deleteFeatures(fids_to_remove):
                    logger.warning("SAR-lc6: Failed to remove %d stale features", len(fids_to_remove))
                else:
                    removed_count = len(fids_to_remove)

        # Log delta stats if there were changes
        if updated_count or added_count or removed_count:
            logger.debug(
                "SAR-lc6: Delta update - updated: %d, added: %d, removed: %d (total: %d devices)",
                updated_count, added_count, removed_count, len(new_positions)
            )

        return (updated_count, added_count, removed_count)

    def _full_rebuild_current_positions(
        self,
        layer: QgsVectorLayer,
        positions: List[Dict]
    ) -> tuple:
        """
        Full rebuild fallback for current positions (original clear-all + add-all pattern).

        Used when delta update is not possible (e.g., missing device_id field).

        Args:
            layer: The current positions layer
            positions: List of validated position dicts

        Returns:
            Tuple of (0, added_count, 0) - no updates/removals in full rebuild
        """
        with self._layer_transaction(layer, self.CURRENT_LAYER_NAME, "rebuild positions") as edit_layer:
            self._clear_layer_features(edit_layer, self.CURRENT_LAYER_NAME)

            for pos in positions:
                feature = QgsFeature(edit_layer.fields())
                feature.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(pos['lon'], pos['lat'])))
                attr_map = {
                    "device_id": pos.get("device_id"),
                    "name": pos.get("name"),
                    "timestamp": pos.get("ts"),
                    "altitude": pos.get("altitude"),
                    "speed": pos.get("speed"),
                    "battery": pos.get("battery"),
                }
                fields = edit_layer.fields()
                for field_name, value in attr_map.items():
                    idx = fields.indexFromName(field_name)
                    if idx != -1:
                        feature.setAttribute(idx, value)
                if not edit_layer.addFeature(feature):
                    raise RuntimeError(f"Failed to add feature for device {pos['device_id']}")

        return (0, len(positions), 0)

    def _apply_current_positions_style(self, layer: QgsVectorLayer):
        """
        Apply or update categorized style to current positions.

        Updates existing renderer to:
        1. Prevent crashes (replacing renderer deletes C++ objects UI might be using)
        2. Preserve user manual color changes
        3. Only add categories for new devices
        """
        # Avoid mutating renderer while a modal dialog (e.g. symbol selector) is open.
        # This reduces re-entrancy risk when users change symbology in the layer tree.
        try:
            if QApplication.activeModalWidget() is not None:
                return
        except Exception:
            pass

        if getattr(getattr(self, "layer_manager", None), "_application_closing", False):
            return

        try:
            if not bool(layer.customProperty(self.CURRENT_STYLE_MANAGED_PROP, True)):
                return
        except Exception:
            return

        # Get unique device IDs and build device_id -> name mapping
        # FR-5: Use device names in renderer legend labels
        try:
            device_id_idx = layer.fields().indexFromName("device_id")
            name_idx = layer.fields().indexFromName("name")
            if device_id_idx == -1:
                return
            device_ids_raw = layer.uniqueValues(device_id_idx)
            device_ids = sorted({str(value) for value in device_ids_raw if value is not None and str(value) != ""})

            # Build device_id -> name mapping from layer features
            device_names = {}
            if name_idx != -1:
                for feature in layer.getFeatures():
                    did = feature.attribute(device_id_idx)
                    dname = feature.attribute(name_idx)
                    if did is not None and str(did) not in device_names:
                        # Use name if available, otherwise device_id as fallback
                        device_names[str(did)] = str(dname) if dname else str(did)
        except Exception as exc:
            # CRITICAL FIX (BUG-024): Log renderer setup failures instead of silent return
            logger.warning("Failed to get device IDs for styling: %s", exc)
            return

        # Check if we already have a categorized renderer
        current_renderer = layer.renderer()

        style_initialized = False
        try:
            style_initialized = bool(layer.customProperty(self.CURRENT_STYLE_INITIALIZED_PROP, False))
        except Exception:
            style_initialized = False

        if isinstance(current_renderer, QgsCategorizedSymbolRenderer):
            # UPDATE EXISTING: Safest approach
            existing_categories = current_renderer.categories()
            existing_ids = {str(cat.value()) for cat in existing_categories}

            new_devices = [d for d in device_ids if d not in existing_ids]

            if not new_devices:
                return

            for device_id in new_devices:
                color = self._get_device_color(device_id)
                symbol = QgsMarkerSymbol.createSimple({
                    'name': 'circle',
                    'color': color.name(),
                    'size': '5',
                    'outline_color': 'black',
                    'outline_width': '0.5'
                })
                # FR-5: Use device name as legend label (fallback to device_id)
                label = device_names.get(device_id, device_id)
                category = QgsRendererCategory(device_id, symbol, label)
                current_renderer.addCategory(category)

            layer.triggerRepaint()
            try:
                layer.setCustomProperty(self.CURRENT_STYLE_INITIALIZED_PROP, True)
            except Exception:
                pass

        else:
            if style_initialized:
                # User switched renderer manually - stop auto styling so their custom
                # symbology persists across refreshes.
                try:
                    layer.setCustomProperty(self.CURRENT_STYLE_MANAGED_PROP, False)
                except Exception:
                    pass
                logger.info("Current positions renderer manually overridden; auto styling disabled.")
                return

            # FIRST LOAD / RESET: Create new renderer
            categories = []
            for device_id in device_ids:
                color = self._get_device_color(device_id)
                symbol = QgsMarkerSymbol.createSimple({
                    'name': 'circle',
                    'color': color.name(),
                    'size': '5',
                    'outline_color': 'black',
                    'outline_width': '0.5'
                })
                # FR-5: Use device name as legend label (fallback to device_id)
                label = device_names.get(device_id, device_id)
                category = QgsRendererCategory(device_id, symbol, label)
                categories.append(category)

            renderer = QgsCategorizedSymbolRenderer('device_id', categories)
            layer.setRenderer(renderer)
            try:
                layer.setCustomProperty(self.CURRENT_STYLE_INITIALIZED_PROP, True)
            except Exception:
                pass

            # Apply labels (only apply defaults on first load/reset to respect user changes)
            label_settings = QgsPalLayerSettings()
            label_settings.fieldName = 'name'
            label_settings.enabled = True

            # Handle QGIS version differences in placement enum
            # Qt5/Qt6 Compatible
            try:
                # QGIS 3.26+ uses Placement enum
                label_settings.placement = QgsPalLayerSettings.Placement.OverPoint
            except AttributeError:
                # Older QGIS versions
                label_settings.placement = QgsPalLayerSettings.OverPoint

            text_format = QgsTextFormat()
            text_format.setSize(10)
            text_format.setColor(QColor('black'))

            # Text buffer (white halo)
            buffer = QgsTextBufferSettings()
            buffer.setEnabled(True)
            buffer.setColor(QColor('white'))
            buffer.setSize(1)
            text_format.setBuffer(buffer)

            label_settings.setFormat(text_format)

            labeling = QgsVectorLayerSimpleLabeling(label_settings)
            layer.setLabeling(labeling)
            layer.setLabelsEnabled(True)

    # =========================================================================
    # Phase SAR-nh9: Per-Device Position Layers
    # =========================================================================

    def _get_per_device_factory(self) -> Optional[PerItemLayerFactory]:
        """
        Get the per-device layer factory, creating if necessary.

        Returns:
            PerItemLayerFactory or None if mission store not available
        """
        if self._per_device_factory is not None:
            return self._per_device_factory

        # Try to get the mission GeoPackage path from layer_manager
        layer_manager = getattr(self, 'layer_manager', None)
        if not layer_manager:
            logger.debug("Per-device factory: no layer_manager available")
            return None

        # Use get_mission_store() method (same pattern as marker_manager)
        gpkg_path = layer_manager.get_mission_store()
        if not gpkg_path:
            logger.debug("Per-device factory: no mission store configured")
            return None

        from pathlib import Path
        self._per_device_factory = PerItemLayerFactory(Path(gpkg_path))
        logger.info("SAR-nh9: PerItemLayerFactory initialized for per-device tracking: %s", gpkg_path)
        return self._per_device_factory

    def _ensure_tracking_group(self) -> Optional[QgsLayerTreeGroup]:
        """
        Ensure the Tracking group exists under SAR Tracker.

        Returns:
            QgsLayerTreeGroup for Tracking, or None on failure
        """
        project = QgsProject.instance()
        root = project.layerTreeRoot()

        # Find or create SAR Tracker root
        sar_root = root.findGroup(GroupNames.ROOT)
        if not sar_root:
            sar_root = root.insertGroup(0, GroupNames.ROOT)

        # Find or create Tracking group
        tracking_group = sar_root.findGroup(GroupNames.TRACKING)
        if not tracking_group:
            tracking_group = sar_root.insertGroup(0, GroupNames.TRACKING)

        return tracking_group

    def _ensure_device_group(self, device_name: str) -> Optional[QgsLayerTreeGroup]:
        """
        Ensure a device group exists under Tracking.

        Structure: SAR Tracker / Tracking / {DeviceName}

        Args:
            device_name: Display name for the device

        Returns:
            QgsLayerTreeGroup for the device, or None on failure
        """
        tracking_group = self._ensure_tracking_group()
        if not tracking_group:
            return None

        # Find or create device group
        device_group = tracking_group.findGroup(device_name)
        if not device_group:
            device_group = tracking_group.addGroup(device_name)

        return device_group

    def _get_device_layers_by_property(self, device_id: str) -> Dict[str, Optional[QgsVectorLayer]]:
        """
        Find position and trail layers by stable device_id custom property.

        This is the primary lookup method for per-device layers.
        Uses custom property sartracker:device_id for identification,
        which survives layer rename.

        Args:
            device_id: Stable device identifier

        Returns:
            Dict with 'position' and 'trail' layer references (may be None)
        """
        result = {'position': None, 'trail': None}

        for layer in QgsProject.instance().mapLayers().values():
            if not isinstance(layer, QgsVectorLayer):
                continue

            layer_device_id = layer.customProperty(self.DEVICE_ID_PROP)
            if layer_device_id != device_id:
                continue

            item_type = layer.customProperty("sartracker:item_type")
            if item_type == ItemType.DEVICE_POSITION:
                result['position'] = layer
            elif item_type == ItemType.DEVICE_TRAIL:
                result['trail'] = layer

        return result

    def _ensure_device_position_layer(
        self,
        device_id: str,
        sample_position: Dict
    ) -> Optional[QgsVectorLayer]:
        """
        Create or retrieve position layer for a device.

        Each device gets its own position layer under:
            SAR Tracker / Tracking / {DeviceName} / Position

        Args:
            device_id: Stable device identifier from Traccar
            sample_position: Position dict with 'name' for display name

        Returns:
            QgsVectorLayer for the device position, or None on failure
        """
        # Check cache first
        if device_id in self._device_position_layers:
            layer = self._device_position_layers[device_id]
            if layer and layer.isValid():
                return layer
            # Stale cache entry
            del self._device_position_layers[device_id]

        # Search by custom property (handles plugin reload)
        existing = self._get_device_layers_by_property(device_id)
        if existing['position'] and existing['position'].isValid():
            self._device_position_layers[device_id] = existing['position']
            return existing['position']

        # Create new layer via factory
        factory = self._get_per_device_factory()
        if not factory:
            logger.warning(
                "Cannot create per-device position layer: no factory available. "
                "Falling back to shared layer."
            )
            return None

        # Get device name for display
        device_name = sample_position.get('name') or f"Device {device_id[:8]}"

        # Ensure device group exists
        device_group = self._ensure_device_group(device_name)
        if not device_group:
            logger.warning("Failed to create device group for %s", device_name)
            return None

        try:
            # Create the layer via PerItemLayerFactory
            item_info = factory.create_item_layer(
                item_type=ItemType.DEVICE_POSITION,
                display_name="Position",
                item_id=f"pos_{device_id}",
                fields=DEVICE_POSITION_FIELDS,
                add_to_project=True,
                target_group=device_group
            )

            layer = item_info.layer
            if not layer or not layer.isValid():
                logger.error("Failed to create position layer for device %s", device_id)
                return None

            # Set device identification properties (survives rename)
            layer.setCustomProperty(self.DEVICE_ID_PROP, device_id)
            layer.setCustomProperty(self.DEVICE_NAME_PROP, device_name)

            # Apply device-specific styling
            color = self._get_device_color(device_id)
            layer.setCustomProperty(self.DEVICE_COLOR_PROP, color.name())
            self._apply_device_position_style(layer, color)

            # Cache and return
            self._device_position_layers[device_id] = layer
            logger.info(
                "Created per-device position layer for %s (device_id=%s)",
                device_name, device_id
            )
            return layer

        except Exception as e:
            logger.error("Failed to create per-device position layer: %s", e)
            return None

    def _apply_device_position_style(self, layer: QgsVectorLayer, color: QColor):
        """
        Apply simple marker styling to a per-device position layer.

        Unlike shared layers which use QgsCategorizedSymbolRenderer,
        per-device layers use a simple single-symbol renderer since
        each layer contains only one device.

        Args:
            layer: The position layer to style
            color: Device color for the marker
        """
        from qgis.core import QgsSingleSymbolRenderer

        symbol = QgsMarkerSymbol.createSimple({
            'name': 'circle',
            'color': color.name(),
            'size': '5',
            'outline_color': 'black',
            'outline_width': '0.5'
        })

        # CRITICAL FIX: renderer() can return None for newly created layers
        renderer = layer.renderer()
        if renderer is None:
            renderer = QgsSingleSymbolRenderer(symbol)
            layer.setRenderer(renderer)
        else:
            renderer.setSymbol(symbol)

        # Apply labels
        label_settings = QgsPalLayerSettings()
        label_settings.fieldName = 'name'
        label_settings.enabled = True

        try:
            label_settings.placement = QgsPalLayerSettings.Placement.OverPoint
        except AttributeError:
            label_settings.placement = QgsPalLayerSettings.OverPoint

        text_format = QgsTextFormat()
        text_format.setSize(10)
        text_format.setColor(QColor('black'))

        buffer = QgsTextBufferSettings()
        buffer.setEnabled(True)
        buffer.setColor(QColor('white'))
        buffer.setSize(1)
        text_format.setBuffer(buffer)

        label_settings.setFormat(text_format)

        labeling = QgsVectorLayerSimpleLabeling(label_settings)
        layer.setLabeling(labeling)
        layer.setLabelsEnabled(True)

    def _update_device_position(self, layer: QgsVectorLayer, position: Dict):
        """
        Update the single feature in a per-device position layer.

        Each per-device position layer contains exactly one feature
        representing the latest known position. This method replaces
        that feature with the new position data.

        Args:
            layer: The device's position layer
            position: Position dict with lat, lon, name, ts, etc.
        """
        device_id = position.get('device_id', '')

        with self._layer_transaction(layer, f"Position ({device_id})", "update device position") as edit_layer:
            # Clear existing feature(s)
            self._clear_layer_features(edit_layer, f"Position ({device_id})")

            # Create new feature with latest position
            feature = QgsFeature(edit_layer.fields())
            feature.setGeometry(
                QgsGeometry.fromPointXY(QgsPointXY(position['lon'], position['lat']))
            )

            # Set attributes
            import uuid
            attr_map = {
                "id": str(uuid.uuid4()),
                "device_id": device_id,
                "name": position.get("name"),
                "timestamp": position.get("ts"),
                "altitude": position.get("altitude"),
                "speed": position.get("speed"),
                "battery": position.get("battery"),
                "accuracy": position.get("accuracy"),
                "source": position.get("source", "traccar"),
            }

            fields = edit_layer.fields()
            for field_name, value in attr_map.items():
                idx = fields.indexFromName(field_name)
                if idx != -1:
                    feature.setAttribute(idx, value)

            if not edit_layer.addFeature(feature):
                raise RuntimeError(f"Failed to add position feature for device {device_id}")

    def _update_positions_per_device(self, positions: List[Dict]):
        """
        Update positions using per-device layers.

        Main entry point for per-device position updates. Groups positions
        by device and updates each device's layer with its latest position.

        Uses canvas freeze during batch updates for performance.

        Args:
            positions: List of validated position dicts
        """
        if not positions:
            return

        # Group by device - we only need the latest position per device
        from collections import defaultdict
        by_device: Dict[str, Dict] = {}
        for pos in positions:
            device_id = pos.get('device_id')
            if device_id:
                by_device[device_id] = pos  # Keep overwriting with latest

        if not by_device:
            return

        # Freeze canvas during batch update for performance
        canvas = self.iface.mapCanvas()
        canvas.freeze(True)

        # Also block layer tree signals during batch layer creation
        project = QgsProject.instance()
        root = project.layerTreeRoot()
        root.blockSignals(True)

        failed_devices = []
        try:
            for device_id, latest_pos in by_device.items():
                layer = self._ensure_device_position_layer(device_id, latest_pos)
                if layer:
                    self._update_device_position(layer, latest_pos)
                else:
                    # CRITICAL FIX: Track failed devices instead of silent loss
                    failed_devices.append(device_id)
        finally:
            root.blockSignals(False)
            canvas.freeze(False)
            canvas.refresh()

        # CRITICAL FIX: If ANY device failed, raise exception to trigger fallback
        # This ensures no position data is silently lost
        if failed_devices:
            logger.warning(
                "SAR-nh9: %d device(s) failed per-device layer creation: %s",
                len(failed_devices), ", ".join(failed_devices[:5])  # Log first 5
            )
            raise RuntimeError(
                f"Per-device layer creation failed for {len(failed_devices)} device(s). "
                "Falling back to shared layer."
            )

        logger.debug(
            "SAR-nh9: Updated per-device positions for %d devices",
            len(by_device)
        )

    # =========================================================================
    # Phase SAR-nj0: Per-Device Trail Layers
    # =========================================================================

    def _get_device_generation(self, device_id: str) -> int:
        """
        Get the current generation counter for a device.

        Used for async safety - stale callbacks can detect outdated data.

        Args:
            device_id: Device identifier

        Returns:
            Current generation number (0 if device not seen before)
        """
        return self._device_generations.get(device_id, 0)

    def _increment_device_generation(self, device_id: str) -> int:
        """
        Increment and return the generation counter for a device.

        Called when starting a new async operation for this device.

        Args:
            device_id: Device identifier

        Returns:
            New generation number
        """
        current = self._device_generations.get(device_id, 0)
        new_gen = current + 1
        self._device_generations[device_id] = new_gen
        return new_gen

    def _ensure_device_trail_layer(
        self,
        device_id: str,
        sample_position: Dict
    ) -> Optional[QgsVectorLayer]:
        """
        Create or retrieve trail layer for a device.

        Each device gets its own trail layer under:
            SAR Tracker / Tracking / {DeviceName} / Trail

        Trail layers contain LineString segments for that device's breadcrumbs.

        Args:
            device_id: Stable device identifier from Traccar
            sample_position: Position dict with 'name' for display name

        Returns:
            QgsVectorLayer for the device trail, or None on failure
        """
        # Check cache first
        if device_id in self._device_trail_layers:
            layer = self._device_trail_layers[device_id]
            if layer and layer.isValid():
                return layer
            # Stale cache entry
            del self._device_trail_layers[device_id]

        # Search by custom property (handles plugin reload)
        existing = self._get_device_layers_by_property(device_id)
        if existing['trail'] and existing['trail'].isValid():
            self._device_trail_layers[device_id] = existing['trail']
            return existing['trail']

        # Create new layer via factory
        factory = self._get_per_device_factory()
        if not factory:
            logger.warning(
                "Cannot create per-device trail layer: no factory available. "
                "Falling back to shared layer."
            )
            return None

        # Get device name for display
        device_name = sample_position.get('name') or f"Device {device_id[:8]}"

        # Ensure device group exists (same group as position layer)
        device_group = self._ensure_device_group(device_name)
        if not device_group:
            logger.warning("Failed to create device group for %s", device_name)
            return None

        try:
            # Create the layer via PerItemLayerFactory
            item_info = factory.create_item_layer(
                item_type=ItemType.DEVICE_TRAIL,
                display_name="Trail",
                item_id=f"trail_{device_id}",
                fields=DEVICE_TRAIL_FIELDS,
                add_to_project=True,
                target_group=device_group
            )

            layer = item_info.layer
            if not layer or not layer.isValid():
                logger.error("Failed to create trail layer for device %s", device_id)
                return None

            # Set device identification properties (survives rename)
            layer.setCustomProperty(self.DEVICE_ID_PROP, device_id)
            layer.setCustomProperty(self.DEVICE_NAME_PROP, device_name)

            # Apply device-specific styling
            color = self._get_device_color(device_id)
            layer.setCustomProperty(self.DEVICE_COLOR_PROP, color.name())
            self._apply_device_trail_style(layer, color)

            # Cache and return
            self._device_trail_layers[device_id] = layer
            logger.info(
                "Created per-device trail layer for %s (device_id=%s)",
                device_name, device_id
            )
            return layer

        except Exception as e:
            logger.error("Failed to create per-device trail layer: %s", e)
            return None

    def _apply_device_trail_style(self, layer: QgsVectorLayer, color: QColor):
        """
        Apply simple line styling to a per-device trail layer.

        Unlike shared layers which use QgsCategorizedSymbolRenderer,
        per-device layers use a simple single-symbol renderer since
        each layer contains only one device.

        Args:
            layer: The trail layer to style
            color: Device color for the line
        """
        from qgis.core import QgsSingleSymbolRenderer

        symbol = QgsLineSymbol.createSimple({
            'color': color.name(),
            'width': '2',
            'line_style': 'solid',
            'joinstyle': 'round',
            'capstyle': 'round'
        })

        # CRITICAL FIX: renderer() can return None for newly created layers
        renderer = layer.renderer()
        if renderer is None:
            renderer = QgsSingleSymbolRenderer(symbol)
            layer.setRenderer(renderer)
        else:
            renderer.setSymbol(symbol)

    def _update_device_trail(
        self,
        layer: QgsVectorLayer,
        segments: List[Dict[str, Any]],
        device_id: str
    ):
        """
        Replace trail segments in a per-device trail layer.

        Each per-device trail layer contains multiple LineString features
        representing trail segments for that device only.

        Args:
            layer: The device's trail layer
            segments: List of segment dicts with 'points', 'device_id', 'name'
            device_id: Device identifier for logging
        """
        import uuid

        with self._layer_transaction(layer, f"Trail ({device_id})", "update device trail") as edit_layer:
            # Clear existing features
            self._clear_layer_features(edit_layer, f"Trail ({device_id})")

            # Add new segment features
            dropped_segments = 0
            for idx, segment in enumerate(segments):
                qgs_points = []
                drop_reason = None
                for pt_idx, point in enumerate(segment.get('points', [])):
                    try:
                        lon = float(point.get('lon'))
                        lat = float(point.get('lat'))
                    except (TypeError, ValueError) as e:
                        # HIGH FIX: Log dropped segments instead of silent loss
                        drop_reason = f"invalid coordinate at point {pt_idx}: {e}"
                        qgs_points = []
                        break

                    if not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
                        # HIGH FIX: Log dropped segments instead of silent loss
                        drop_reason = f"out-of-range coordinate at point {pt_idx}: lat={lat}, lon={lon}"
                        qgs_points = []
                        break

                    qgs_points.append(QgsPointXY(lon, lat))

                if len(qgs_points) < 2:
                    if drop_reason:
                        logger.warning(
                            "SAR-nj0: Dropping trail segment %d for device %s - %s",
                            idx, device_id, drop_reason
                        )
                    dropped_segments += 1
                    continue

                geom = QgsGeometry.fromPolylineXY(qgs_points)
                feature = QgsFeature(edit_layer.fields())
                feature.setGeometry(geom)

                # Extract timestamps from segment points
                points_payload = segment.get('points', [])
                start_time = ""
                end_time = ""
                if points_payload:
                    first_ts = points_payload[0].get('ts')
                    last_ts = points_payload[-1].get('ts')
                    if isinstance(first_ts, str):
                        start_time = first_ts
                    if isinstance(last_ts, str):
                        end_time = last_ts

                # Calculate segment distance (approximate)
                distance_m = 0.0
                if len(qgs_points) >= 2:
                    try:
                        distance_m = geom.length() * 111000  # Rough degrees to meters
                    except Exception:
                        pass

                attr_map = {
                    "id": str(uuid.uuid4()),
                    "device_id": device_id,
                    "name": segment.get('name') or device_id,
                    "segment_index": idx,
                    "start_time": start_time,
                    "end_time": end_time,
                    "point_count": len(qgs_points),
                    "distance_m": distance_m,
                }

                fields = edit_layer.fields()
                for field_name, value in attr_map.items():
                    field_idx = fields.indexFromName(field_name)
                    if field_idx != -1:
                        feature.setAttribute(field_idx, value)

                if not edit_layer.addFeature(feature):
                    raise RuntimeError(f"Failed to add trail segment for device {device_id}")

    def _update_breadcrumbs_per_device(
        self,
        positions: List[Dict],
        gap_minutes: float,
        processed_segments: Optional[Dict[str, Any]] = None
    ):
        """
        Update breadcrumbs using per-device trail layers.

        Main entry point for per-device breadcrumb updates. Groups positions
        by device and updates each device's trail layer with its segments.

        Uses canvas freeze during batch updates for performance.

        Args:
            positions: List of validated position dicts
            gap_minutes: Minutes gap to break trail into segments
            processed_segments: Optional pre-processed segments (bypasses segmentation)
        """
        if not positions and not processed_segments:
            return

        # Group positions by device
        from collections import defaultdict
        by_device: Dict[str, List[Dict]] = defaultdict(list)

        for pos in positions:
            device_id = pos.get('device_id')
            if device_id:
                by_device[device_id].append(pos)

        if not by_device and not processed_segments:
            return

        # If we have pre-processed segments, group them by device
        segments_by_device: Dict[str, List[Dict]] = defaultdict(list)
        if processed_segments and isinstance(processed_segments, dict):
            all_segments = processed_segments.get('segments', [])
            for seg in all_segments:
                seg_device_id = seg.get('device_id')
                if seg_device_id:
                    segments_by_device[seg_device_id].append(seg)
        else:
            # Build segments per device from positions
            for device_id, device_positions in by_device.items():
                device_segments = build_segments_from_positions(device_positions, gap_minutes)
                segments_by_device[device_id] = device_segments

        if not segments_by_device:
            return

        # Freeze canvas during batch update for performance
        canvas = self.iface.mapCanvas()
        canvas.freeze(True)

        # Also block layer tree signals during batch layer creation
        project = QgsProject.instance()
        root = project.layerTreeRoot()
        root.blockSignals(True)

        try:
            for device_id, device_segments in segments_by_device.items():
                # Get sample position for device name
                sample_pos = by_device.get(device_id, [{}])[0] if by_device else {}
                if not sample_pos and device_segments:
                    # Extract name from segment if no positions
                    sample_pos = {'name': device_segments[0].get('name', device_id)}

                layer = self._ensure_device_trail_layer(device_id, sample_pos)
                if layer:
                    self._update_device_trail(layer, device_segments, device_id)
                else:
                    # Per-device layer creation failed - logged in _ensure_device_trail_layer
                    pass
        finally:
            root.blockSignals(False)
            canvas.freeze(False)
            canvas.refresh()

        logger.debug(
            "SAR-nj0: Updated per-device trails for %d devices",
            len(segments_by_device)
        )

    # =========================================================================
    # Breadcrumbs Layer
    # =========================================================================

    def _get_or_create_breadcrumbs_layer(self) -> QgsVectorLayer:
        """
        Get or create breadcrumbs layer.

        Returns:
            QgsVectorLayer: Breadcrumbs layer
        """
        layer = self._ensure_schema_layer(
            LayerIds.BREADCRUMBS,
            fallback_name=self.BREADCRUMBS_LAYER_NAME
        )
        self._ensure_breadcrumbs_schema(layer)
        if layer.customProperty(self.BREADCRUMB_STYLE_MANAGED_PROP, None) is None:
            layer.setCustomProperty(self.BREADCRUMB_STYLE_MANAGED_PROP, True)
        if layer.customProperty(self.BREADCRUMB_STYLE_INITIALIZED_PROP, None) is None:
            layer.setCustomProperty(self.BREADCRUMB_STYLE_INITIALIZED_PROP, False)
        self._log_tracking_event(layer, "BREADCRUMBS", "ensure")
        return layer

    def _ensure_breadcrumbs_schema(self, layer: QgsVectorLayer):
        """
        Ensure breadcrumbs layer has required fields (timestamp).

        Add missing fields in-place using a safe transaction.
        """
        if not layer or not layer.isValid():
            return

        if layer.fields().indexFromName("timestamp") != -1:
            return

        # Add timestamp field if missing
        if layer.isEditable():
            raise LayerLockError(layer.name())

        if not layer.startEditing():
            logger.warning("Could not start editing %s to add timestamp field", layer.name())
            return

        try:
            if not layer.addAttribute(QgsField("timestamp", QVariant.String, len=40)):
                raise RuntimeError("Failed to add timestamp field")
            if not layer.commitChanges():
                errors = layer.commitErrors()
                raise RuntimeError(f"Commit failed: {', '.join(errors)}")
        except Exception as exc:
            layer.rollBack()
            logger.warning("Could not update breadcrumbs schema: %s", exc)
        finally:
            if layer.isEditable():
                try:
                    layer.rollBack()
                except RuntimeError:
                    pass

    def update_breadcrumbs(
        self,
        positions: List[Dict],
        time_gap_minutes: int = 5,
        processed_segments: Optional[Dict[str, Any]] = None
    ):
        """
        Update breadcrumb trails layer.

        Creates line segments showing device movement history.
        Automatically breaks trails on time gaps (e.g., when device was off).

        Args:
            positions: List of position dicts from tracking provider
            time_gap_minutes: Minutes gap to break trail into segments (default: 5)
            processed_segments: Optional pre-processed segment payload produced
                by provider refresh tasks. When provided (and compatible with
                the requested time gap), sorting and segmentation are skipped.

        Raises:
            ValueError: If position data is invalid
        """
        if not isinstance(time_gap_minutes, (int, float)) or time_gap_minutes <= 0:
            raise ValueError(f"time_gap_minutes must be a positive number, got: {time_gap_minutes}")

        gap_minutes = float(time_gap_minutes)

        # Phase SAR-nj0: Route to per-device or shared layer implementation
        if self.USE_PER_DEVICE_TRAILS:
            # Try per-device architecture first
            factory = self._get_per_device_factory()
            if factory:
                try:
                    # Sanitize positions first
                    total_inputs = len(positions) if positions else 0
                    invalid_count = 0
                    last_error = None

                    if positions:
                        sanitized = sanitize_breadcrumb_positions(positions)
                        valid_positions = sanitized.valid
                        invalid_count = sanitized.invalid_count
                        last_error = sanitized.last_error
                    else:
                        valid_positions = []

                    # HIGH FIX: Report validation warnings (was missing in per-device path)
                    self._report_validation_warning(
                        "Breadcrumbs",
                        total_inputs,
                        invalid_count,
                        last_error
                    )

                    self._update_breadcrumbs_per_device(
                        valid_positions,
                        gap_minutes,
                        processed_segments
                    )

                    self._log_tracking_event(
                        None,  # No single layer
                        "BREADCRUMBS_PER_DEVICE",
                        "update",
                        payload_items=total_inputs,
                        device_count=len(set(p.get('device_id') for p in (positions or []) if p.get('device_id')))
                    )
                    return  # Successfully updated via per-device layers
                except Exception as e:
                    logger.warning(
                        "SAR-nj0: Per-device breadcrumb update failed, falling back to shared layer: %s", e
                    )
                    # Fall through to shared layer implementation
            else:
                logger.debug("SAR-nj0: No factory available, using shared breadcrumbs layer")

        # Shared layer implementation (legacy or fallback)
        layer = self._get_or_create_breadcrumbs_layer()

        total_inputs = len(positions) if isinstance(positions, list) else 0
        segments = validate_processed_segments(processed_segments, gap_minutes)
        invalid_count = 0
        last_error = None

        if segments is None:
            if self._maybe_schedule_breadcrumb_task(positions, gap_minutes, total_inputs, processed_segments):
                return

            sanitized_positions = sanitize_breadcrumb_positions(positions)
            invalid_count = sanitized_positions.invalid_count
            last_error = sanitized_positions.last_error
            segments = build_segments_from_positions(sanitized_positions.valid, gap_minutes)

        self._apply_breadcrumb_results(
            layer,
            segments or [],
            total_inputs,
            invalid_count,
            last_error
        )

    def _replace_breadcrumb_layer_features(self, layer: QgsVectorLayer, segments: List[Dict[str, Any]]):
        """
        Replace layer features with provided segments using safe transactions.

        BUG-032 FIX: Enforces MAX_BREADCRUMB_SEGMENTS limit to prevent memory
        exhaustion during long missions. Keeps most recent segments.
        """
        segments = segments or []

        # SAR-7i4 FIX: Enforce memory cap on breadcrumb segments
        # Keep the most recent segments (end of list) if over limit
        if len(segments) > self.MAX_BREADCRUMB_SEGMENTS:
            discarded_count = len(segments) - self.MAX_BREADCRUMB_SEGMENTS
            segments = segments[-self.MAX_BREADCRUMB_SEGMENTS:]
            logger.warning(
                "SAR-7i4: Breadcrumb memory cap enforced - discarded %d oldest segments, "
                "keeping %d most recent (limit: %d)",
                discarded_count, len(segments), self.MAX_BREADCRUMB_SEGMENTS
            )
            # SAR-7i4: Notify coordinator of data truncation
            self._notify_truncation_warning(
                "breadcrumb segments", discarded_count, len(segments), self.MAX_BREADCRUMB_SEGMENTS
            )

        with self._layer_transaction(layer, self.BREADCRUMBS_LAYER_NAME, "update breadcrumbs") as edit_layer:
            self._clear_layer_features(edit_layer, self.BREADCRUMBS_LAYER_NAME)

            for segment in segments:
                qgs_points = []
                for point in segment.get('points', []):
                    try:
                        lon = float(point.get('lon'))
                        lat = float(point.get('lat'))
                    except (TypeError, ValueError):
                        qgs_points = []
                        break

                    if not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
                        qgs_points = []
                        break

                    qgs_points.append(QgsPointXY(lon, lat))

                if len(qgs_points) < 2:
                    continue

                geom = QgsGeometry.fromPolylineXY(qgs_points)
                feature = QgsFeature(edit_layer.fields())
                feature.setGeometry(geom)
                device_id = segment.get('device_id', '')
                device_name = segment.get('name') or device_id
                points_payload = segment.get('points', [])
                ts_value = ""
                if points_payload:
                    last_ts = points_payload[-1].get('ts')
                    if isinstance(last_ts, str):
                        ts_value = last_ts

                attr_map = {
                    'device_id': device_id,
                    'name': device_name,
                    'timestamp': ts_value
                }
                for field_name, value in attr_map.items():
                    idx = edit_layer.fields().indexFromName(field_name)
                    if idx != -1:
                        feature.setAttribute(idx, value)

                if not edit_layer.addFeature(feature):
                    raise RuntimeError(f"Failed to add breadcrumb segment for device {device_id}")

    def _apply_breadcrumbs_style(self, layer: QgsVectorLayer):
        """
        Apply or update categorized style to breadcrumbs safely.

        Updates existing renderer to:
        1. Prevent crashes (replacing renderer deletes C++ objects UI might be using)
        2. Preserve user manual color changes
        3. Only add categories for new devices
        """
        # Avoid mutating renderer while a modal dialog (e.g. symbol selector) is open.
        # This reduces re-entrancy risk when users change symbology in the layer tree.
        try:
            if QApplication.activeModalWidget() is not None:
                return
        except Exception:
            pass

        if not bool(layer.customProperty(self.BREADCRUMB_STYLE_MANAGED_PROP, True)):
            return

        if getattr(getattr(self, "layer_manager", None), "_application_closing", False):
            return

        # Get unique device IDs and build device_id -> name mapping
        # FR-5: Use device names in renderer legend labels
        try:
            device_id_idx = layer.fields().indexFromName("device_id")
            name_idx = layer.fields().indexFromName("name")
            if device_id_idx == -1:
                return
            device_ids_raw = layer.uniqueValues(device_id_idx)
            device_ids = sorted({str(value) for value in device_ids_raw if value is not None and str(value) != ""})

            # Build device_id -> name mapping from layer features
            device_names = {}
            if name_idx != -1:
                for feature in layer.getFeatures():
                    did = feature.attribute(device_id_idx)
                    dname = feature.attribute(name_idx)
                    if did is not None and str(did) not in device_names:
                        # Use name if available, otherwise device_id as fallback
                        device_names[str(did)] = str(dname) if dname else str(did)
        except Exception as exc:
            # CRITICAL FIX (BUG-024): Log breadcrumb styling failures
            logger.warning("Failed to get device IDs for breadcrumb styling: %s", exc)
            return

        # Check if we already have a categorized renderer
        current_renderer = layer.renderer()
        
        style_initialized = bool(
            layer.customProperty(self.BREADCRUMB_STYLE_INITIALIZED_PROP, False)
        )

        if isinstance(current_renderer, QgsCategorizedSymbolRenderer):
            # UPDATE EXISTING: Safest approach
            # 1. Get existing categories
            existing_categories = current_renderer.categories()
            existing_ids = {str(cat.value()) for cat in existing_categories}
            
            # 2. Find new devices that need categories
            new_devices = [d for d in device_ids if d not in existing_ids]
            
            if not new_devices:
                return  # Nothing to do, renderer is up to date
                
            # 3. Create categories ONLY for new devices
            for device_id in new_devices:
                color = self._get_device_color(device_id)
                symbol = QgsLineSymbol.createSimple({
                    'color': color.name(),
                    'width': '2',
                    'line_style': 'solid',
                    'joinstyle': 'round',
                    'capstyle': 'round'
                })
                # FR-5: Use device name as legend label (fallback to device_id)
                label = device_names.get(device_id, device_id)
                category = QgsRendererCategory(device_id, symbol, label)
                current_renderer.addCategory(category)
            
            # Force refresh of the legend/canvas
            layer.triggerRepaint()
            layer.setCustomProperty(self.BREADCRUMB_STYLE_INITIALIZED_PROP, True)
            
        else:
            if style_initialized:
                # User switched renderer manually - stop auto styling so their custom
                # symbology persists across refreshes.
                layer.setCustomProperty(self.BREADCRUMB_STYLE_MANAGED_PROP, False)
                logger.info("Breadcrumb renderer manually overridden; auto styling disabled.")
                return

            # FIRST LOAD / RESET: Create new renderer
            categories = []
            for device_id in device_ids:
                color = self._get_device_color(device_id)
                symbol = QgsLineSymbol.createSimple({
                    'color': color.name(),
                    'width': '2',
                    'line_style': 'solid',
                    'joinstyle': 'round',
                    'capstyle': 'round'
                })
                # FR-5: Use device name as legend label (fallback to device_id)
                label = device_names.get(device_id, device_id)
                category = QgsRendererCategory(device_id, symbol, label)
                categories.append(category)

            renderer = QgsCategorizedSymbolRenderer('device_id', categories)
            layer.setRenderer(renderer)
            layer.setCustomProperty(self.BREADCRUMB_STYLE_INITIALIZED_PROP, True)

    def delete_device_positions(
        self,
        device_ids: List[str],
        updated_by: Optional[str] = None
    ) -> int:
        """
        Delete all current positions for given device IDs.

        Args:
            device_ids: List of device IDs to remove
            updated_by: Coordinator name for audit trail

        Returns:
            Number of positions deleted

        Raises:
            ValueError: If device_ids invalid
            LayerTransactionError: If deletion fails
        """
        # Validate input
        if not isinstance(device_ids, list) or not device_ids:
            raise ValueError("device_ids must be a non-empty list")

        layer = self._get_or_create_current_layer()

        # Find features to delete
        device_id_field_idx = layer.fields().indexFromName('device_id')
        if device_id_field_idx == -1:
            raise RuntimeError("device_id field not found")

        feature_ids_to_delete = []
        for feature in layer.getFeatures(QgsFeatureRequest()):
            if feature.attribute(device_id_field_idx) in device_ids:
                feature_ids_to_delete.append(feature.id())

        if not feature_ids_to_delete:
            return 0

        with self._layer_transaction(layer, self.CURRENT_LAYER_NAME, "delete device positions") as edit_layer:
            if not edit_layer.deleteFeatures(feature_ids_to_delete):
                raise RuntimeError("Failed to delete features")

        layer.triggerRepaint()
        logger.info(
            "[TrackingManager] Deleted %s positions for %s devices",
            len(feature_ids_to_delete),
            len(device_ids)
        )
        return len(feature_ids_to_delete)

    def delete_device_breadcrumbs(
        self,
        device_ids: List[str],
        updated_by: Optional[str] = None
    ) -> int:
        """
        Delete breadcrumbs for given device IDs.

        Args:
            device_ids: List of device IDs to remove
            updated_by: Coordinator name for audit trail

        Returns:
            Number of breadcrumb segments deleted
        """
        if not isinstance(device_ids, list) or not device_ids:
            raise ValueError("device_ids must be a non-empty list")

        layer = self._get_or_create_breadcrumbs_layer()

        device_id_field_idx = layer.fields().indexFromName('device_id')
        if device_id_field_idx == -1:
            raise RuntimeError("device_id field not found")

        feature_ids_to_delete = []
        for feature in layer.getFeatures(QgsFeatureRequest()):
            if feature.attribute(device_id_field_idx) in device_ids:
                feature_ids_to_delete.append(feature.id())

        if not feature_ids_to_delete:
            return 0

        with self._layer_transaction(layer, self.BREADCRUMBS_LAYER_NAME, "delete device breadcrumbs") as edit_layer:
            if not edit_layer.deleteFeatures(feature_ids_to_delete):
                raise RuntimeError("Failed to delete breadcrumbs")

        layer.triggerRepaint()
        logger.info(
            "[TrackingManager] Deleted %s breadcrumb segments for %s devices",
            len(feature_ids_to_delete),
            len(device_ids)
        )
        return len(feature_ids_to_delete)

    def prune_old_breadcrumbs(
        self,
        older_than_hours: int = 24,
        updated_by: Optional[str] = None
    ) -> int:
        """
        Delete breadcrumbs older than specified hours.

        Performance optimization for long missions.

        Args:
            older_than_hours: Age threshold in hours
            updated_by: Coordinator name for audit trail

        Returns:
            Number of breadcrumb segments deleted
        """
        if not isinstance(older_than_hours, (int, float)) or older_than_hours <= 0:
            raise ValueError(f"older_than_hours must be positive number, got: {older_than_hours}")

        layer = self._get_or_create_breadcrumbs_layer()
        if not layer or not layer.isValid():
            return 0

        ts_idx = layer.fields().indexFromName("timestamp")
        if ts_idx == -1:
            logger.warning("Breadcrumbs layer missing timestamp field; cannot prune")
            return 0

        # Use timezone-aware datetime to prevent Python 3.9+ comparison crashes
        threshold = datetime.now(timezone.utc) - timedelta(hours=float(older_than_hours))
        feature_ids = []
        for feature in layer.getFeatures(QgsFeatureRequest()):
            ts_val = feature.attribute(ts_idx)
            if not ts_val:
                continue
            try:
                ts = parse_iso_timestamp(str(ts_val))
                # Make ts timezone-aware if it's naive (defensive safety)
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
            except Exception:
                continue
            if ts < threshold:
                feature_ids.append(feature.id())

        if not feature_ids:
            return 0

        with self._layer_transaction(layer, self.BREADCRUMBS_LAYER_NAME, "prune breadcrumbs") as edit_layer:
            if not edit_layer.deleteFeatures(feature_ids):
                raise RuntimeError("Failed to delete old breadcrumbs")

        layer.triggerRepaint()
        logger.info(
            "[TrackingManager] Pruned %s breadcrumb segments older than %sh",
            len(feature_ids),
            older_than_hours
        )
        return len(feature_ids)

    def export_device_track(
        self,
        device_id: str,
        format: str = "geojson"
    ) -> str:
        """
        Export a single device track (breadcrumbs) to a file.

        Args:
            device_id: Device identifier to export
            format: Output format (currently only 'geojson')

        Returns:
            Path to exported file
        """
        if not device_id or not isinstance(device_id, str):
            raise ValueError("device_id must be a non-empty string")
        if format.lower() != "geojson":
            raise ValueError("Only GeoJSON export is supported currently")

        layer = self._get_or_create_breadcrumbs_layer()
        if not layer or not layer.isValid():
            raise RuntimeError("Breadcrumbs layer not available")

        # Filter features for device
        device_field_idx = layer.fields().indexFromName("device_id")
        if device_field_idx == -1:
            raise RuntimeError("Breadcrumbs layer missing device_id field")

        export_layer = QgsVectorLayer(f"LineString?crs={layer.crs().authid()}", f"{device_id}_track", "memory")
        export_layer.dataProvider().addAttributes(layer.fields())
        export_layer.updateFields()

        for feature in layer.getFeatures(QgsFeatureRequest()):
            if feature.attribute(device_field_idx) != device_id:
                continue
            new_feature = QgsFeature(export_layer.fields())
            new_feature.setGeometry(feature.geometry())
            # IMPORTANT: Copy attributes by field name (not positional list).
            # Source layers may have provider-managed fields (e.g. fid) that
            # don't exist in the memory export layer, causing field count mismatch.
            source_fields = layer.fields()
            dest_fields = export_layer.fields()
            for i in range(source_fields.count()):
                field_name = source_fields.at(i).name()
                dest_idx = dest_fields.indexFromName(field_name)
                if dest_idx != -1:
                    new_feature.setAttribute(dest_idx, feature.attribute(i))
            if not export_layer.dataProvider().addFeature(new_feature):
                raise RuntimeError(f"Failed to copy feature {feature.id()} for export")

        if export_layer.featureCount() == 0:
            raise ValueError(f"No breadcrumbs found for device {device_id}")

        temp_dir = tempfile.mkdtemp(prefix="sartracker_export_")
        # BUG-060 fix: Track temp directory for cleanup
        self._temp_export_dirs.append(temp_dir)
        path = os.path.join(temp_dir, f"{device_id}_track.geojson")

        try:
            options = QgsVectorFileWriter.SaveVectorOptions()
            options.driverName = "GeoJSON"
            result, error_message = QgsVectorFileWriter.writeAsVectorFormatV2(
                export_layer,
                path,
                QgsCoordinateTransformContext(),
                options
            )
            if result != QgsVectorFileWriter.NoError:
                raise RuntimeError(f"Export failed: {error_message}")
        except Exception:
            # BUG-060 fix: Remove from tracking list on failure
            if temp_dir in self._temp_export_dirs:
                self._temp_export_dirs.remove(temp_dir)
            shutil.rmtree(temp_dir, ignore_errors=True)
            raise

        logger.info("[TrackingManager] Exported track for %s to %s", device_id, path)
        return path

    def _cleanup_temp_dirs(self):
        """
        Clean up all tracked temporary export directories.

        BUG-060 fix: Called during plugin cleanup to prevent temp directory accumulation.
        """
        for temp_dir in self._temp_export_dirs[:]:  # Copy list to allow modification during iteration
            try:
                if os.path.exists(temp_dir):
                    shutil.rmtree(temp_dir, ignore_errors=True)
                    logger.debug("[TrackingManager] Cleaned up temp directory: %s", temp_dir)
            except Exception as e:
                logger.warning("[TrackingManager] Failed to clean up temp directory %s: %s", temp_dir, e)
        self._temp_export_dirs.clear()

    def _cleanup_old_temp_dirs(self):
        """
        Clean up old sartracker_export_* directories from previous sessions.

        BUG-081 FIX: Enhanced cleanup with:
        - Age-based deletion (1 hour threshold)
        - Size tracking for monitoring
        - Summary statistics for diagnostics
        - Protection against excessive temp directory accumulation

        LIFE-SAFETY CRITICAL: Prevents disk space issues during missions.
        """
        cleaned_count = 0
        cleaned_size_bytes = 0
        failed_count = 0

        try:
            temp_root = tempfile.gettempdir()
            # BUG-081 FIX: Track all sartracker export directories
            found_dirs = []

            # Find all sartracker_export_* directories
            for entry in os.listdir(temp_root):
                if entry.startswith("sartracker_export_"):
                    old_dir = os.path.join(temp_root, entry)
                    if os.path.isdir(old_dir):
                        found_dirs.append(old_dir)

            if found_dirs:
                logger.info(
                    "BUG-081: Found %d temporary export directories to evaluate for cleanup",
                    len(found_dirs)
                )

            for old_dir in found_dirs:
                try:
                    # BUG-081 FIX: Calculate directory size before deletion
                    dir_size = 0
                    try:
                        for dirpath, dirnames, filenames in os.walk(old_dir):
                            for filename in filenames:
                                filepath = os.path.join(dirpath, filename)
                                dir_size += os.path.getsize(filepath)
                    except Exception:
                        dir_size = 0  # Couldn't calculate size

                    # Check if it's old (more than 1 hour)
                    dir_age_seconds = datetime.now().timestamp() - os.path.getmtime(old_dir)

                    if dir_age_seconds > 3600:  # 1 hour
                        shutil.rmtree(old_dir, ignore_errors=True)
                        cleaned_count += 1
                        cleaned_size_bytes += dir_size
                        logger.debug(
                            "BUG-081: Cleaned up old temp directory: %s (age: %.1f hours, size: %d KB)",
                            old_dir,
                            dir_age_seconds / 3600,
                            dir_size / 1024
                        )
                    else:
                        logger.debug(
                            "BUG-081: Keeping recent temp directory: %s (age: %.1f minutes)",
                            old_dir,
                            dir_age_seconds / 60
                        )
                except Exception as e:
                    failed_count += 1
                    logger.warning(
                        "BUG-081: Failed to clean up old temp directory %s: %s",
                        old_dir, str(e)
                    )

            # BUG-081 FIX: Log cleanup summary
            if cleaned_count > 0 or failed_count > 0:
                logger.info(
                    "BUG-081: Temp directory cleanup complete - "
                    "cleaned: %d (%.2f MB), failed: %d, total found: %d",
                    cleaned_count,
                    cleaned_size_bytes / (1024 * 1024),
                    failed_count,
                    len(found_dirs)
                )

        except Exception as e:
            logger.warning(
                "BUG-081: Error during temp directory cleanup: %s",
                str(e)
            )
