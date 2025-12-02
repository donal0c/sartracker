# -*- coding: utf-8 -*-
"""
Tracking Layer Manager

Manages real-time tracking layers: current positions and breadcrumb trails.
Handles device position updates from tracking sources (e.g., Traccar).

Qt5/Qt6 Compatible: Uses qgis.PyQt for all imports.
"""

import logging
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
    QgsTask
)
from qgis.PyQt.QtGui import QColor
from qgis.PyQt.QtCore import QVariant

from .base_manager import BaseLayerManager
from .tracking_segments import (
    build_segments_from_positions,
    parse_iso_timestamp,
    sanitize_breadcrumb_positions,
    sanitize_current_positions,
    validate_processed_segments,
)
from ...layers import LayerIds
from ...utils.exceptions import LayerLockError, LayerTransactionError, LayerError
from ...utils.notify import warning as notify_warning


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

    ASYNC_SEGMENT_THRESHOLD = 1500  # Minimum breadcrumb points before offloading

    # BUG-032 FIX: Memory cap for breadcrumb trail accumulation
    # Limits the maximum number of breadcrumb segments to prevent memory exhaustion
    # during long missions. Value chosen to balance history retention vs memory usage.
    # At ~500 bytes per segment (geometry + attributes), 10000 segments ≈ 5MB
    MAX_BREADCRUMB_SEGMENTS = 10000

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

    # BUG-042 FIX: Maximum positions for background task to prevent memory exhaustion
    # Limits task memory to a safe level. Larger datasets should be chunked.
    MAX_TASK_POSITIONS = 50000

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

        # BUG-042 FIX: Memory guard for background task
        # Truncate positions to prevent excessive memory usage in background task
        if len(positions) > self.MAX_TASK_POSITIONS:
            logger.warning(
                "BUG-042: Task memory guard - truncating %d positions to %d for background processing",
                len(positions), self.MAX_TASK_POSITIONS
            )
            positions = positions[-self.MAX_TASK_POSITIONS:]
            total_inputs = self.MAX_TASK_POSITIONS

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
        if not getattr(self, '_layer_manager', None):
            logger.debug("Breadcrumb task complete but layer_manager gone - plugin unloading")
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
            self._apply_breadcrumb_results(
                layer,
                segments,
                total_inputs,
                invalid_count,
                last_error
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
        if not getattr(self, '_layer_manager', None):
            logger.debug("Breadcrumb task error but layer_manager gone - plugin unloading")
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
                self._apply_breadcrumb_results(
                    layer,
                    segments,
                    len(payload),
                    sanitized_positions.invalid_count,
                    sanitized_positions.last_error
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
        last_error: Optional[str]
    ):
        """Common render/apply routine for both sync and async breadcrumb updates."""
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
        self._log_tracking_event(layer, "CURRENT", "ensure")
        return layer

    def update_current_positions(self, positions: List[Dict]):
        """
        Update current positions layer.

        Clears existing features and adds new position for each device.
        Uses efficient truncate() method for clearing when available.

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

        # Get or create layer
        layer = self._get_or_create_current_layer()

        # BUG-027 FIX: Acquire global lock to prevent concurrent position updates
        # This prevents race conditions when multiple refresh operations occur simultaneously
        if not self.acquire_layer_edit_lock(timeout=10.0):
            raise LayerLockError(
                f"{self.CURRENT_LAYER_NAME} - concurrent update in progress. "
                "Please wait for the current operation to complete."
            )

        try:
            with self._layer_transaction(layer, self.CURRENT_LAYER_NAME, "update current positions") as edit_layer:
                self._clear_layer_features(edit_layer, self.CURRENT_LAYER_NAME)

                for pos in valid_positions:
                    feature = QgsFeature(edit_layer.fields())
                    feature.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(pos['lon'], pos['lat'])))
                    feature.setAttributes([
                        pos['device_id'],
                        pos['name'],
                        pos['ts'],
                        pos.get('altitude'),
                        pos.get('speed'),
                        pos.get('battery')
                    ])
                    if not edit_layer.addFeature(feature):
                        raise RuntimeError(f"Failed to add feature for device {pos['device_id']}")

            # Apply styling (outside transaction - failures here don't affect data)
            try:
                self._apply_current_positions_style(layer)
            except Exception as e:
                logger.warning("Failed to apply styling to %s: %s", self.CURRENT_LAYER_NAME, e)

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

    def _apply_current_positions_style(self, layer: QgsVectorLayer):
        """
        Apply or update categorized style to current positions.

        Updates existing renderer to:
        1. Prevent crashes (replacing renderer deletes C++ objects UI might be using)
        2. Preserve user manual color changes
        3. Only add categories for new devices
        """
        # Get unique device IDs
        try:
            device_ids = layer.uniqueValues(
                layer.fields().indexOf('device_id')
            )
        except Exception as exc:
            # CRITICAL FIX (BUG-024): Log renderer setup failures instead of silent return
            logger.warning("Failed to get device IDs for styling: %s", exc)
            return

        # Check if we already have a categorized renderer
        current_renderer = layer.renderer()

        if isinstance(current_renderer, QgsCategorizedSymbolRenderer):
            # UPDATE EXISTING: Safest approach
            existing_categories = current_renderer.categories()
            existing_ids = {cat.value() for cat in existing_categories}

            new_devices = [d for d in device_ids if d not in existing_ids]

            if not new_devices:
                return

            for device_id in new_devices:
                color = self._get_device_color(str(device_id))
                symbol = QgsMarkerSymbol.createSimple({
                    'name': 'circle',
                    'color': color.name(),
                    'size': '5',
                    'outline_color': 'black',
                    'outline_width': '0.5'
                })
                category = QgsRendererCategory(device_id, symbol, str(device_id))
                current_renderer.addCategory(category)

            layer.triggerRepaint()

        else:
            # FIRST LOAD / RESET: Create new renderer
            categories = []
            for device_id in device_ids:
                color = self._get_device_color(str(device_id))
                symbol = QgsMarkerSymbol.createSimple({
                    'name': 'circle',
                    'color': color.name(),
                    'size': '5',
                    'outline_color': 'black',
                    'outline_width': '0.5'
                })
                category = QgsRendererCategory(device_id, symbol, str(device_id))
                categories.append(category)

            renderer = QgsCategorizedSymbolRenderer('device_id', categories)
            layer.setRenderer(renderer)

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

        # BUG-032 FIX: Enforce memory cap on breadcrumb segments
        # Keep the most recent segments (end of list) if over limit
        if len(segments) > self.MAX_BREADCRUMB_SEGMENTS:
            discarded_count = len(segments) - self.MAX_BREADCRUMB_SEGMENTS
            segments = segments[-self.MAX_BREADCRUMB_SEGMENTS:]
            logger.warning(
                "BUG-032: Breadcrumb memory cap enforced - discarded %d oldest segments, "
                "keeping %d most recent (limit: %d)",
                discarded_count, len(segments), self.MAX_BREADCRUMB_SEGMENTS
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
        if not bool(layer.customProperty(self.BREADCRUMB_STYLE_MANAGED_PROP, True)):
            return

        # Get unique device IDs from data
        try:
            device_ids = layer.uniqueValues(layer.fields().indexOf('device_id'))
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
            existing_ids = {cat.value() for cat in existing_categories}
            
            # 2. Find new devices that need categories
            new_devices = [d for d in device_ids if d not in existing_ids]
            
            if not new_devices:
                return  # Nothing to do, renderer is up to date
                
            # 3. Create categories ONLY for new devices
            for device_id in new_devices:
                color = self._get_device_color(str(device_id))
                symbol = QgsLineSymbol.createSimple({
                    'color': color.name(),
                    'width': '2',
                    'line_style': 'solid',
                    'joinstyle': 'round',
                    'capstyle': 'round'
                })
                category = QgsRendererCategory(device_id, symbol, str(device_id))
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
                color = self._get_device_color(str(device_id))
                symbol = QgsLineSymbol.createSimple({
                    'color': color.name(),
                    'width': '2',
                    'line_style': 'solid',
                    'joinstyle': 'round',
                    'capstyle': 'round'
                })
                category = QgsRendererCategory(device_id, symbol, str(device_id))
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
            new_feature.setAttributes([feature.attribute(i) for i in range(len(layer.fields()))])
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
