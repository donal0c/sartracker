# -*- coding: utf-8 -*-
"""
Tracking Layer Manager

Manages real-time tracking layers: current positions and breadcrumb trails.
Handles device position updates from tracking sources (e.g., Traccar).

Qt5/Qt6 Compatible: Uses qgis.PyQt for all imports.
"""

import logging
import hashlib
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
    QgsTask, QgsProject, QgsLayerTreeGroup, QgsRectangle, QgsCoordinateTransform
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
from ...layers.utilities import refresh_layer_tree_view
from ...utils.exceptions import LayerLockError, LayerTransactionError, LayerError
from ...utils.notify import warning as notify_warning
from ...utils.qt_compat import sip_isdeleted
from ..per_item_layer_factory import ItemType, PerItemLayerFactory, SAR_ITEM_TYPE, SAR_ITEM_ID
from ...config.settings import INITIAL_ZOOM_BUFFER_DEGREES, INITIAL_ZOOM_MIN_EXTENT_DEGREES


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

    @staticmethod
    def _hash_device_id(device_id: str) -> str:
        """Return a stable, ASCII-only hash for device identifiers."""
        return hashlib.md5(device_id.encode("utf-8")).hexdigest()

    @classmethod
    def _candidate_device_item_ids(cls, prefix: str, device_id: str) -> tuple:
        """Return legacy + safe per-device item IDs."""
        legacy_id = f"{prefix}_{device_id}"
        safe_id = f"{prefix}_{cls._hash_device_id(device_id)}"
        return legacy_id, safe_id

    @staticmethod
    def _get_or_rebuild_device_layer(factory, item_id: str, target_group: QgsLayerTreeGroup):
        """
        Return a loaded layer if present, otherwise rebuild from registry.
        """
        try:
            layer = factory.get_layer_by_item_id(item_id)
        except Exception:
            layer = None

        if layer and layer.isValid():
            return layer

        try:
            return factory.rebuild_missing_layer(item_id, add_to_project=True, target_group=target_group)
        except Exception:
            return None

    def _apply_device_layer_identity(
        self,
        layer: QgsVectorLayer,
        device_id: str,
        device_name: str,
        is_trail: bool
    ) -> None:
        """
        Ensure per-device layers have stable identification and styling.
        """
        layer.setCustomProperty(self.DEVICE_ID_PROP, device_id)
        layer.setCustomProperty(self.DEVICE_NAME_PROP, device_name)

        if layer.customProperty(self.DEVICE_COLOR_PROP, None) is None:
            color = self._get_device_color(device_id)
            layer.setCustomProperty(self.DEVICE_COLOR_PROP, color.name())
            if is_trail:
                self._apply_device_trail_style(layer, color)
            else:
                self._apply_device_position_style(layer, color)

    @staticmethod
    def _is_layer_usable(layer: Optional[QgsVectorLayer]) -> bool:
        """Return True only for live, valid QgsVectorLayer wrappers."""
        if layer is None:
            return False
        try:
            if sip_isdeleted(layer):
                return False
        except Exception:
            # Non-Qt test doubles can fail sip checks; continue with isValid().
            pass
        try:
            return bool(layer.isValid())
        except Exception:
            # Covers wrapped C/C++ object deleted and any stale-wrapper errors.
            return False

    def _record_stale_cache_event(
        self,
        *,
        device_id: str,
        layer_kind: str,
        reason: str
    ) -> None:
        """Record and log stale cached layer references for diagnostics."""
        self._stale_layer_cache_events += 1
        event = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "device_id": device_id,
            "layer_kind": layer_kind,
            "reason": reason,
        }
        self._last_stale_layer_cache_event = event
        logger.warning(
            "Stale cached %s layer purged for device %s: %s",
            layer_kind,
            device_id,
            reason,
        )

    def _is_cached_layer_usable(
        self,
        layer: Optional[QgsVectorLayer],
        *,
        device_id: str,
        layer_kind: str
    ) -> bool:
        """
        Validate cached layer references and capture stale-wrapper diagnostics.
        """
        if layer is None:
            return False

        try:
            if sip_isdeleted(layer):
                self._record_stale_cache_event(
                    device_id=device_id,
                    layer_kind=layer_kind,
                    reason="sip_deleted",
                )
                return False
        except Exception:
            # Non-Qt test doubles can fail sip checks; continue with isValid().
            pass

        try:
            if not bool(layer.isValid()):
                self._record_stale_cache_event(
                    device_id=device_id,
                    layer_kind=layer_kind,
                    reason="is_valid_false",
                )
                return False
            return True
        except Exception as exc:
            self._record_stale_cache_event(
                device_id=device_id,
                layer_kind=layer_kind,
                reason=str(exc),
            )
            return False

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
        self._per_device_migration_checked = False
        self._per_device_layout_normalized = False

        # Phase SAR-nj0: Per-device generation tracking for async safety
        # Each device has its own generation counter to detect stale async data
        self._device_generations: Dict[str, int] = {}

        # Cache-health diagnostics for incident bundle correlation.
        self._stale_layer_cache_events = 0
        self._last_stale_layer_cache_event: Optional[Dict[str, str]] = None

    def get_managed_layer_names(self):
        """Return list of fixed layer names this manager handles (legacy only)."""
        return []

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
        self._per_device_migration_checked = False
        self._per_device_layout_normalized = False
        # Phase SAR-nj0: Clear per-device generations
        self._device_generations.clear()
        self._stale_layer_cache_events = 0
        self._last_stale_layer_cache_event = None

    def get_diagnostics(self) -> Dict[str, Any]:
        """Return tracking-manager diagnostics for incident bundles."""
        return {
            "status": "operational",
            "per_device_position_cache_size": len(self._device_position_layers),
            "per_device_trail_cache_size": len(self._device_trail_layers),
            "stale_layer_cache_events": int(self._stale_layer_cache_events),
            "last_stale_layer_cache_event": self._last_stale_layer_cache_event,
        }

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

            if not self.USE_PER_DEVICE_TRAILS:
                logger.warning("Breadcrumb task complete but per-device trails disabled")
                return

            segments = task.property("sartracker:segments") or []
            total_inputs = task.property("sartracker:total_inputs") or len(segments)
            invalid_count = task.property("sartracker:invalid_count") or 0
            last_error = task.property("sartracker:last_error") or None
            gap_minutes = task.property("sartracker:gap_minutes") or 5.0

            self._ensure_per_device_ready()
            self._report_validation_warning(
                "Breadcrumbs",
                total_inputs,
                invalid_count,
                last_error
            )

            processed_segments = {
                "segments": segments,
                "time_gap_minutes": float(gap_minutes),
            }
            self._update_breadcrumbs_per_device(
                [],
                float(gap_minutes),
                processed_segments=processed_segments
            )

            self._log_tracking_event(
                None,
                "BREADCRUMBS_PER_DEVICE",
                "update",
                payload_items=total_inputs,
                device_count=len({seg.get("device_id") for seg in segments if seg.get("device_id")})
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
                gap_value = float(gap_minutes or 5.0)
                segments = build_segments_from_positions(
                    sanitized_positions.valid,
                    gap_value
                )

                if not self.USE_PER_DEVICE_TRAILS:
                    logger.warning("Breadcrumb fallback skipped (per-device trails disabled)")
                    return

                self._ensure_per_device_ready()
                self._report_validation_warning(
                    "Breadcrumbs",
                    len(payload),
                    sanitized_positions.invalid_count,
                    sanitized_positions.last_error
                )
                processed_segments = {
                    "segments": segments,
                    "time_gap_minutes": gap_value,
                }
                self._update_breadcrumbs_per_device(
                    sanitized_positions.valid,
                    gap_value,
                    processed_segments=processed_segments
                )
                self._log_tracking_event(
                    None,
                    "BREADCRUMBS_PER_DEVICE",
                    "update",
                    payload_items=len(payload),
                    device_count=len({seg.get("device_id") for seg in segments if seg.get("device_id")})
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

    def _calculate_combined_device_extent(self) -> Optional[QgsRectangle]:
        """
        Calculate the combined extent of all per-device position layers.

        SAR-drpu: Used for initial zoom to show all tracked devices at once,
        rather than zooming to just the first device found.

        Returns:
            QgsRectangle combining all device positions, or None if no valid layers.
        """
        combined_extent = QgsRectangle()

        for device_id, layer in self._device_position_layers.items():
            if self._is_layer_usable(layer) and layer.featureCount() > 0:
                layer_extent = layer.extent()
                if not layer_extent.isEmpty():
                    if combined_extent.isNull():
                        combined_extent = QgsRectangle(layer_extent)
                    else:
                        combined_extent.combineExtentWith(layer_extent)

        if combined_extent.isNull():
            return None

        return combined_extent

    def _get_device_positions_crs(self):
        """
        Return CRS for per-device current position layers.

        Uses the first valid layer CRS as all device layers share the same schema.
        """
        for layer in self._device_position_layers.values():
            try:
                if not self._is_layer_usable(layer):
                    continue
                crs = layer.crs()
                if crs and crs.isValid():
                    return crs
            except Exception:
                continue
        return None

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

        # Phase SAR-nh9: Per-device architecture only
        if self.USE_PER_DEVICE_POSITIONS:
            try:
                self._ensure_per_device_ready()
            except LayerError as exc:
                logger.warning(
                    "Per-device tracking unavailable (%s); falling back to shared current layer",
                    exc
                )
                return self._update_current_positions_shared(valid_positions)

            self._update_positions_per_device(valid_positions)

            # Zoom to extent ONLY on first load (SAR-drpu fix: use combined extent + buffering)
            if self.first_load and valid_positions:
                combined_extent = self._calculate_combined_device_extent()
                if combined_extent and not combined_extent.isEmpty():
                    # Apply buffering if extent is too small for useful SAR overview
                    if (combined_extent.width() < INITIAL_ZOOM_MIN_EXTENT_DEGREES or
                            combined_extent.height() < INITIAL_ZOOM_MIN_EXTENT_DEGREES):
                        combined_extent = combined_extent.buffered(INITIAL_ZOOM_BUFFER_DEGREES)
                    target_extent = combined_extent
                    canvas = None
                    try:
                        canvas = self.iface.mapCanvas() if hasattr(self.iface, "mapCanvas") else None
                        if canvas:
                            canvas_crs = canvas.mapSettings().destinationCrs() if hasattr(canvas, "mapSettings") else None
                            layer_crs = self._get_device_positions_crs()
                            if (
                                layer_crs and canvas_crs and
                                hasattr(layer_crs, "isValid") and hasattr(canvas_crs, "isValid") and
                                layer_crs.isValid() and canvas_crs.isValid() and
                                layer_crs != canvas_crs
                            ):
                                transform = QgsCoordinateTransform(layer_crs, canvas_crs, QgsProject.instance())
                                target_extent = transform.transformBoundingBox(combined_extent)
                    except Exception as exc:
                        logger.warning("Initial zoom CRS transform failed: %s", exc)

                    if canvas:
                        canvas.setExtent(target_extent)
                        canvas.refresh()
                        self.first_load = False

            self._log_tracking_event(
                None,  # No single layer
                "CURRENT_PER_DEVICE",
                "update",
                payload_items=len(valid_positions),
                device_count=len(set(p.get('device_id') for p in valid_positions if p.get('device_id')))
            )
            return

        raise LayerError("Per-device tracking is disabled for current positions.", title="Tracking Disabled")

    def _update_current_positions_shared(self, positions: List[Dict]) -> None:
        """Update the legacy shared Current Positions layer."""
        if not positions:
            return

        layer = self._get_or_create_current_layer()
        updated, added, removed = self._delta_update_current_positions(layer, positions)

        try:
            self._apply_current_positions_style(layer)
        except Exception as exc:
            logger.warning("Failed to apply current positions styling: %s", exc)

        layer.triggerRepaint()
        self._log_tracking_event(
            layer,
            "CURRENT",
            "update",
            updated=updated,
            added=added,
            removed=removed,
            devices=len(positions)
        )

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

    def _get_per_device_factory(self) -> PerItemLayerFactory:
        """
        Get the per-device layer factory, creating if necessary.

        Returns:
            PerItemLayerFactory
        """
        if self._per_device_factory is not None:
            return self._per_device_factory

        # Mission store required for per-device tracking
        gpkg_path = self._require_mission_store("Per-device tracking")

        from pathlib import Path
        self._per_device_factory = PerItemLayerFactory(Path(gpkg_path))
        logger.info("SAR-nh9: PerItemLayerFactory initialized for per-device tracking: %s", gpkg_path)
        return self._per_device_factory

    def _ensure_per_device_ready(self) -> PerItemLayerFactory:
        """
        Ensure per-device tracking is ready (mission store + migrations).

        Returns:
            PerItemLayerFactory
        """
        factory = self._get_per_device_factory()

        if not self._per_device_migration_checked:
            migrated = self.migrate_to_per_device_layers()
            self._per_device_migration_checked = True
            if not migrated:
                raise LayerError(
                    "Per-device migration failed; tracking layers were not upgraded.",
                    title="Tracking Migration Failed"
                )
        if not self._per_device_layout_normalized:
            self._normalize_per_device_tracking_layout()
            self._per_device_layout_normalized = True

        return factory

    def _normalize_per_device_tracking_layout(self) -> None:
        """Ensure per-device tracking layers live under Tracking subgroups."""
        project = QgsProject.instance()
        root = project.layerTreeRoot()
        if not root:
            return

        factory = self._get_per_device_factory()
        self._ensure_tracking_subgroup(GroupNames.CURRENT_POSITIONS)
        self._ensure_tracking_subgroup(GroupNames.TRACKING_TRAILS)

        for layer in project.mapLayers().values():
            if not isinstance(layer, QgsVectorLayer):
                continue
            item_type = layer.customProperty(SAR_ITEM_TYPE)
            if item_type == ItemType.DEVICE_POSITION:
                device_name = layer.customProperty(self.DEVICE_NAME_PROP) or layer.name()
                self._ensure_tracking_layer_placement(layer, GroupNames.CURRENT_POSITIONS)
                self._ensure_tracking_layer_name(layer, device_name, factory)
            elif item_type == ItemType.DEVICE_TRAIL:
                device_name = layer.customProperty(self.DEVICE_NAME_PROP) or layer.name()
                self._ensure_tracking_layer_placement(layer, GroupNames.TRACKING_TRAILS)
                self._ensure_tracking_layer_name(layer, device_name, factory)

        tracking_root = self._get_tracking_group(GroupNames.TRACKING)
        if not tracking_root:
            return
        sar_root = root.findGroup(GroupNames.ROOT)
        if sar_root:
            for child in list(sar_root.children()):
                if not isinstance(child, QgsLayerTreeGroup):
                    continue
                if child.name() != GroupNames.CURRENT_POSITIONS:
                    continue
                # Move any remaining layers from legacy root group.
                for node in list(child.children()):
                    try:
                        layer = node.layer()
                    except Exception:
                        layer = None
                    if isinstance(layer, QgsVectorLayer):
                        item_type = layer.customProperty(SAR_ITEM_TYPE)
                        if item_type == ItemType.DEVICE_POSITION:
                            self._ensure_tracking_layer_placement(layer, GroupNames.CURRENT_POSITIONS)
                        elif item_type == ItemType.DEVICE_TRAIL:
                            self._ensure_tracking_layer_placement(layer, GroupNames.TRACKING_TRAILS)
                if not child.children():
                    sar_root.removeChildNode(child)
        for child in list(tracking_root.children()):
            if not isinstance(child, QgsLayerTreeGroup):
                continue
            if child.name() in (GroupNames.CURRENT_POSITIONS, GroupNames.TRACKING_TRAILS):
                continue
            if not child.children():
                tracking_root.removeChildNode(child)

    def _ensure_tracking_group(self, group_name: str) -> Optional[QgsLayerTreeGroup]:
        """
        Ensure a tracking group exists under SAR Tracker.

        Structure:
            SAR Tracker / Tracking
            SAR Tracker / Tracking / {group_name}

        Args:
            group_name: Tracking subgroup name under Tracking

        Returns:
            QgsLayerTreeGroup for group_name, or None on failure
        """
        project = QgsProject.instance()
        root = project.layerTreeRoot()

        # Find or create SAR Tracker root
        sar_root = root.findGroup(GroupNames.ROOT)
        if not sar_root:
            sar_root = root.insertGroup(0, GroupNames.ROOT)

        # Find or create Tracking root group
        tracking_root = sar_root.findGroup(GroupNames.TRACKING)
        if not tracking_root:
            tracking_root = sar_root.insertGroup(0, GroupNames.TRACKING)

        if group_name == GroupNames.TRACKING:
            return tracking_root

        # Find or create tracking subgroup
        tracking_group = tracking_root.findGroup(group_name)
        if not tracking_group:
            tracking_group = tracking_root.addGroup(group_name)

        return tracking_group

    def _ensure_tracking_subgroup(self, group_name: str) -> Optional[QgsLayerTreeGroup]:
        """
        Ensure a tracking subgroup exists under Tracking.

        Args:
            group_name: Subgroup name under Tracking

        Returns:
            QgsLayerTreeGroup for group_name, or None on failure
        """
        return self._ensure_tracking_group(group_name)

    def _ensure_tracking_layer_placement(self, layer: QgsVectorLayer, group_name: str) -> None:
        """Move layer into the correct tracking subgroup if needed."""
        if not self._is_layer_usable(layer):
            return
        target_group = self._ensure_tracking_subgroup(group_name)
        if not target_group:
            return
        root = QgsProject.instance().layerTreeRoot()
        if not root:
            return
        layer_node = root.findLayer(layer.id())
        if layer_node:
            current_parent = layer_node.parent()
            if current_parent != target_group:
                if current_parent:
                    current_parent.removeChildNode(layer_node)
                target_group.insertChildNode(0, layer_node)
        else:
            self.project.addMapLayer(layer, False)
            target_group.insertLayer(0, layer)

    def _ensure_tracking_layer_name(self, layer: QgsVectorLayer, device_name: str, factory: PerItemLayerFactory) -> None:
        """Ensure layer display name matches device name and registry."""
        if not layer or not device_name or layer.name() == device_name:
            return
        item_id = layer.customProperty(SAR_ITEM_ID)
        if item_id and factory:
            try:
                if factory.rename_item_layer(item_id, device_name):
                    return
            except Exception as exc:
                logger.warning("Failed to rename tracking layer via registry: %s", exc)
        try:
            layer.setName(device_name)
        except Exception as exc:
            logger.warning("Failed to rename tracking layer: %s", exc)

    def _get_tracking_group(self, group_name: str) -> Optional[QgsLayerTreeGroup]:
        """Return the named tracking group if it exists (without creating)."""
        root = QgsProject.instance().layerTreeRoot()
        if not root:
            return None
        sar_root = root.findGroup(GroupNames.ROOT)
        if not sar_root:
            return None
        tracking_root = sar_root.findGroup(GroupNames.TRACKING)
        if not tracking_root:
            return None
        if group_name == GroupNames.TRACKING:
            return tracking_root
        return tracking_root.findGroup(group_name)

    def _remove_device_group_if_empty(self, device_name: Optional[str], group_name: str) -> None:
        """Deprecated: device groups are no longer used in tracking layout."""
        _ = device_name
        _ = group_name
        return

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

            item_type = layer.customProperty(SAR_ITEM_TYPE)
            if item_type == ItemType.DEVICE_POSITION:
                result['position'] = layer
            elif item_type == ItemType.DEVICE_TRAIL:
                result['trail'] = layer

        return result

    def _get_existing_device_position_layer(self, device_id: str) -> Optional[QgsVectorLayer]:
        """Return existing per-device position layer without creating new ones."""
        cached = self._device_position_layers.get(device_id)
        if self._is_cached_layer_usable(cached, device_id=device_id, layer_kind="position"):
            return cached
        self._device_position_layers.pop(device_id, None)

        existing = self._get_device_layers_by_property(device_id)
        layer = existing.get('position')
        if self._is_layer_usable(layer):
            self._device_position_layers[device_id] = layer
            return layer

        return None

    def _get_existing_device_trail_layer(self, device_id: str) -> Optional[QgsVectorLayer]:
        """Return existing per-device trail layer without creating new ones."""
        cached = self._device_trail_layers.get(device_id)
        if self._is_cached_layer_usable(cached, device_id=device_id, layer_kind="trail"):
            return cached
        self._device_trail_layers.pop(device_id, None)

        existing = self._get_device_layers_by_property(device_id)
        layer = existing.get('trail')
        if self._is_layer_usable(layer):
            self._device_trail_layers[device_id] = layer
            return layer

        return None

    def _ensure_device_position_layer(
        self,
        device_id: str,
        sample_position: Dict
    ) -> Optional[QgsVectorLayer]:
        """
        Create or retrieve position layer for a device.

        Each device gets its own position layer under:
            SAR Tracker / Tracking / Current Positions

        Layer display name is the device name (no per-device subgroup).

        Args:
            device_id: Stable device identifier from Traccar
            sample_position: Position dict with 'name' for display name

        Returns:
            QgsVectorLayer for the device position, or None on failure
        """
        # Get device name for display
        device_name = sample_position.get('name') or f"Device {device_id[:8]}"

        # Check cache first
        if device_id in self._device_position_layers:
            layer = self._device_position_layers[device_id]
            if self._is_cached_layer_usable(layer, device_id=device_id, layer_kind="position"):
                factory = self._get_per_device_factory()
                self._ensure_tracking_layer_placement(layer, GroupNames.CURRENT_POSITIONS)
                self._ensure_tracking_layer_name(layer, device_name, factory)
                return layer
            # Stale cache entry
            del self._device_position_layers[device_id]

        # Search by custom property (handles plugin reload)
        existing = self._get_device_layers_by_property(device_id)
        if self._is_layer_usable(existing['position']):
            factory = self._get_per_device_factory()
            self._ensure_tracking_layer_placement(existing['position'], GroupNames.CURRENT_POSITIONS)
            self._ensure_tracking_layer_name(existing['position'], device_name, factory)
            self._device_position_layers[device_id] = existing['position']
            return existing['position']

        # Create new layer via factory
        factory = self._get_per_device_factory()

        # Ensure Current Positions subgroup exists
        positions_group = self._ensure_tracking_subgroup(GroupNames.CURRENT_POSITIONS)
        if not positions_group:
            logger.warning("Failed to create Current Positions group for %s", device_name)
            return None

        legacy_item_id, safe_item_id = self._candidate_device_item_ids("pos", device_id)

        try:
            # Try legacy item id first (existing missions), then safe hash id.
            layer = self._get_or_rebuild_device_layer(factory, legacy_item_id, positions_group)
            if not layer and safe_item_id != legacy_item_id:
                layer = self._get_or_rebuild_device_layer(factory, safe_item_id, positions_group)

            if not layer:
                # Create the layer via PerItemLayerFactory
                item_info = factory.create_item_layer(
                    item_type=ItemType.DEVICE_POSITION,
                    display_name=device_name,
                    item_id=safe_item_id,
                    fields=DEVICE_POSITION_FIELDS,
                    add_to_project=True,
                    target_group=positions_group
                )
                layer = item_info.layer

            if not self._is_layer_usable(layer):
                logger.error("Failed to create position layer for device %s", device_id)
                return None

            self._apply_device_layer_identity(layer, device_id, device_name, is_trail=False)
            self._ensure_tracking_layer_placement(layer, GroupNames.CURRENT_POSITIONS)
            self._ensure_tracking_layer_name(layer, device_name, factory)

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
            refresh_layer_tree_view(self.iface)

        # CRITICAL FIX: If ANY device failed, raise exception to signal data loss risk
        # This ensures no position data is silently lost
        if failed_devices:
            logger.warning(
                "SAR-nh9: %d device(s) failed per-device layer creation: %s",
                len(failed_devices), ", ".join(failed_devices[:5])  # Log first 5
            )
            raise RuntimeError(
                f"Per-device layer creation failed for {len(failed_devices)} device(s)."
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
            SAR Tracker / Tracking / Trail

        Layer display name is the device name (no per-device subgroup).

        Trail layers contain LineString segments for that device's breadcrumbs.

        Args:
            device_id: Stable device identifier from Traccar
            sample_position: Position dict with 'name' for display name

        Returns:
            QgsVectorLayer for the device trail, or None on failure
        """
        # Get device name for display
        device_name = sample_position.get('name') or f"Device {device_id[:8]}"

        # Check cache first
        if device_id in self._device_trail_layers:
            layer = self._device_trail_layers[device_id]
            if self._is_cached_layer_usable(layer, device_id=device_id, layer_kind="trail"):
                factory = self._get_per_device_factory()
                self._ensure_tracking_layer_placement(layer, GroupNames.TRACKING_TRAILS)
                self._ensure_tracking_layer_name(layer, device_name, factory)
                return layer
            # Stale cache entry
            del self._device_trail_layers[device_id]

        # Search by custom property (handles plugin reload)
        existing = self._get_device_layers_by_property(device_id)
        if self._is_layer_usable(existing['trail']):
            factory = self._get_per_device_factory()
            self._ensure_tracking_layer_placement(existing['trail'], GroupNames.TRACKING_TRAILS)
            self._ensure_tracking_layer_name(existing['trail'], device_name, factory)
            self._device_trail_layers[device_id] = existing['trail']
            return existing['trail']

        # Create new layer via factory
        factory = self._get_per_device_factory()

        # Ensure Trail subgroup exists
        trails_group = self._ensure_tracking_subgroup(GroupNames.TRACKING_TRAILS)
        if not trails_group:
            logger.warning("Failed to create Trail group for %s", device_name)
            return None

        legacy_item_id, safe_item_id = self._candidate_device_item_ids("trail", device_id)

        try:
            # Try legacy item id first (existing missions), then safe hash id.
            layer = self._get_or_rebuild_device_layer(factory, legacy_item_id, trails_group)
            if not layer and safe_item_id != legacy_item_id:
                layer = self._get_or_rebuild_device_layer(factory, safe_item_id, trails_group)

            if not layer:
                # Create the layer via PerItemLayerFactory
                item_info = factory.create_item_layer(
                    item_type=ItemType.DEVICE_TRAIL,
                    display_name=device_name,
                    item_id=safe_item_id,
                    fields=DEVICE_TRAIL_FIELDS,
                    add_to_project=True,
                    target_group=trails_group
                )
                layer = item_info.layer

            if not self._is_layer_usable(layer):
                logger.error("Failed to create trail layer for device %s", device_id)
                return None

            self._apply_device_layer_identity(layer, device_id, device_name, is_trail=True)
            self._ensure_tracking_layer_placement(layer, GroupNames.TRACKING_TRAILS)
            self._ensure_tracking_layer_name(layer, device_name, factory)

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
            'line_style': 'dash',
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
            # Robust fallback: preprocessing can yield no segments when points exist but update gaps
            # exceed time_gap_minutes (default 5 minutes). Build locally so trails are still visible.
            if not segments_by_device and by_device:
                for device_id, device_positions in by_device.items():
                    device_segments = build_segments_from_positions(device_positions, gap_minutes)
                    if device_segments:
                        segments_by_device[device_id] = device_segments
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

        failed_devices = []
        try:
            for device_id, device_segments in segments_by_device.items():
                # Get sample position for device name
                sample_pos = by_device.get(device_id, [{}])[0] if by_device else {}
                if not sample_pos and device_segments:
                    # Extract name from segment if no positions
                    sample_pos = {'name': device_segments[0].get('name', device_id)}

                try:
                    layer = self._ensure_device_trail_layer(device_id, sample_pos)
                    if layer:
                        self._update_device_trail(layer, device_segments, device_id)
                    else:
                        failed_devices.append(device_id)
                except Exception as exc:
                    failed_devices.append(device_id)
                    logger.warning(
                        "SAR-nj0: Trail update failed for device %s: %s",
                        device_id,
                        exc
                    )
        finally:
            root.blockSignals(False)
            canvas.freeze(False)
            canvas.refresh()
            refresh_layer_tree_view(self.iface)

        logger.debug(
            "SAR-nj0: Updated per-device trails for %d devices",
            len(segments_by_device)
        )

        if failed_devices:
            raise RuntimeError(
                f"Trail updates failed for {len(failed_devices)} device(s)."
            )

    # =========================================================================
    # Phase SAR-0uy: Migration from Shared to Per-Device Layers
    # =========================================================================

    # Migration constants
    MIGRATION_ID = "tracking_v3_to_v4"
    ARCHIVE_SUFFIX = "_archive_v3"

    def migrate_to_per_device_layers(self) -> bool:
        """
        Migrate existing shared tracking layers to per-device architecture.

        SAR-0uy: This migration is non-destructive - shared layers are archived
        (renamed) not deleted. Migration is idempotent - safe to run multiple times.

        SAFETY FIXES:
        - Acquires global edit lock to prevent concurrent tracking updates
        - Tracks failed devices and reports them
        - Only archives if at least some devices migrated successfully

        Migration Flow:
        1. Check if migration is needed (shared layers exist)
        2. Acquire global edit lock
        3. Extract device list from shared layer features
        4. Create per-device layers for each device
        5. Copy features from shared to per-device layers
        6. Archive shared layers (rename, hide)
        7. Release lock

        Returns:
            True if migration completed successfully (or was not needed)
            False if migration failed
        """
        from ...layers.schema import (
            MigrationStatus,
            migration_tracker,
        )

        # Check if per-device mode is enabled
        if not self.USE_PER_DEVICE_POSITIONS and not self.USE_PER_DEVICE_TRAILS:
            logger.info("SAR-0uy: Per-device mode disabled, skipping migration")
            return True

        # Check if factory is available (requires mission store)
        try:
            self._get_per_device_factory()
        except LayerError as exc:
            logger.error("SAR-0uy: Migration aborted - %s", exc)
            return False

        # Find shared layers
        shared_current = self._find_shared_current_layer()
        shared_breadcrumbs = self._find_shared_breadcrumbs_layer()

        if not shared_current and not shared_breadcrumbs:
            logger.info("SAR-0uy: No shared tracking layers found, migration not needed")
            return True

        # Check for existing archived layers (migration already done)
        if self._has_archived_tracking_layers():
            logger.info("SAR-0uy: Archived layers exist, migration already completed")
            return True

        # SAFETY FIX: Acquire global edit lock to prevent concurrent tracking updates
        lock_acquired = self.acquire_layer_edit_lock(timeout=30.0)
        if not lock_acquired:
            logger.error("SAR-0uy: Cannot migrate - layer edit lock unavailable (concurrent operation in progress)")
            return False

        try:
            # Start migration tracking
            affected_layers = []
            if shared_current:
                affected_layers.append(shared_current.name())
            if shared_breadcrumbs:
                affected_layers.append(shared_breadcrumbs.name())

            migration_record = migration_tracker.start_migration(
                self.MIGRATION_ID,
                from_version=3,
                to_version=4,
                affected_layers=affected_layers
            )

            if migration_record.status == MigrationStatus.COMPLETED:
                logger.info("SAR-0uy: Migration already completed")
                return True

            logger.info(
                "SAR-0uy: Starting migration to per-device layers (current: %s, breadcrumbs: %s)",
                shared_current.name() if shared_current else "none",
                shared_breadcrumbs.name() if shared_breadcrumbs else "none"
            )

            # Extract devices from shared layers
            devices = self._extract_devices_from_shared(shared_current, shared_breadcrumbs)

            if not devices:
                logger.info("SAR-0uy: No devices found in shared layers, archiving empty layers")

            # SAFETY FIX: Track failed devices for proper reporting
            migrated_count = 0
            failed_devices = []

            for device_id, device_info in devices.items():
                try:
                    self._migrate_device_to_per_device(
                        device_id,
                        device_info,
                        shared_current,
                        shared_breadcrumbs
                    )
                    migrated_count += 1
                except Exception as e:
                    logger.error(
                        "SAR-0uy: Failed to migrate device %s: %s",
                        device_id, e
                    )
                    failed_devices.append((device_id, str(e)))

            # SAFETY FIX: Report failed devices prominently
            if failed_devices:
                logger.warning(
                    "SAR-0uy: Migration incomplete - %d/%d devices failed: %s",
                    len(failed_devices),
                    len(devices),
                    ", ".join(d[0] for d in failed_devices[:5])  # Show first 5
                )

            # Archive shared layers (only if at least some devices migrated or no devices existed)
            if migrated_count > 0 or not devices:
                self._archive_shared_tracking_layers(shared_current, shared_breadcrumbs)

                # Complete migration
                migration_tracker.complete_migration(self.MIGRATION_ID, rollback_available=True)

                logger.info(
                    "SAR-0uy: Migration completed - %d devices migrated, %d failed",
                    migrated_count, len(failed_devices)
                )
                return len(failed_devices) == 0  # True only if all succeeded
            else:
                # All devices failed - don't archive, mark as failed
                migration_tracker.fail_migration(
                    self.MIGRATION_ID,
                    f"All {len(devices)} devices failed to migrate"
                )
                return False

        except Exception as e:
            logger.error("SAR-0uy: Migration failed: %s", e)
            migration_tracker.fail_migration(self.MIGRATION_ID, str(e))
            return False

        finally:
            # SAFETY FIX: Always release the lock
            self.release_layer_edit_lock()

    def _find_shared_current_layer(self) -> Optional[QgsVectorLayer]:
        """
        Find the shared Current Positions layer if it exists.

        Looks for layer by:
        1. Custom property sartracker:type = current_position
        2. Layer ID sar_current_positions_active
        3. Layer name "Current – Active" or "Current Positions"

        Returns:
            QgsVectorLayer if found, None otherwise
        """
        for layer in QgsProject.instance().mapLayers().values():
            if not isinstance(layer, QgsVectorLayer):
                continue

            # Skip per-device layers
            if layer.customProperty(self.DEVICE_ID_PROP):
                continue

            # Skip archived layers
            if self.ARCHIVE_SUFFIX in layer.name():
                continue

            # Check by custom property
            layer_type = layer.customProperty("sartracker:type")
            if layer_type == "current_position":
                return layer

            # Check by layer ID
            layer_id_prop = layer.customProperty("sartracker:layer_id")
            if layer_id_prop == LayerIds.CURRENT_ACTIVE:
                return layer

            # Check by name
            if layer.name() in ("Current – Active", "Current Positions"):
                # Verify it has expected fields
                fields = layer.fields()
                if fields.indexFromName("device_id") != -1:
                    return layer

        return None

    def _find_shared_breadcrumbs_layer(self) -> Optional[QgsVectorLayer]:
        """
        Find the shared Breadcrumbs layer if it exists.

        Returns:
            QgsVectorLayer if found, None otherwise
        """
        for layer in QgsProject.instance().mapLayers().values():
            if not isinstance(layer, QgsVectorLayer):
                continue

            # Skip per-device layers
            if layer.customProperty(self.DEVICE_ID_PROP):
                continue

            # Skip archived layers
            if self.ARCHIVE_SUFFIX in layer.name():
                continue

            # Check by custom property
            layer_type = layer.customProperty("sartracker:type")
            if layer_type == "breadcrumb":
                return layer

            # Check by layer ID
            layer_id_prop = layer.customProperty("sartracker:layer_id")
            if layer_id_prop == LayerIds.BREADCRUMBS:
                return layer

            # Check by name
            if layer.name() == "Breadcrumbs":
                # Verify it has expected fields
                fields = layer.fields()
                if fields.indexFromName("device_id") != -1:
                    return layer

        return None

    def _has_archived_tracking_layers(self) -> bool:
        """
        Check if archived tracking layers exist from a previous migration.

        Returns:
            True if archived layers exist
        """
        for layer in QgsProject.instance().mapLayers().values():
            if not isinstance(layer, QgsVectorLayer):
                continue
            if self.ARCHIVE_SUFFIX in layer.name():
                return True
        return False

    def _extract_devices_from_shared(
        self,
        current_layer: Optional[QgsVectorLayer],
        breadcrumbs_layer: Optional[QgsVectorLayer]
    ) -> Dict[str, Dict]:
        """
        Extract device information from shared layers.

        Collects unique device_id values and associated names from both
        Current Positions and Breadcrumbs layers.

        Args:
            current_layer: Shared current positions layer (may be None)
            breadcrumbs_layer: Shared breadcrumbs layer (may be None)

        Returns:
            Dict mapping device_id to device info dict with 'name' key
        """
        devices: Dict[str, Dict] = {}
        skipped_invalid = 0

        def extract_from_layer(layer: QgsVectorLayer):
            nonlocal skipped_invalid
            if not layer or not layer.isValid():
                return

            device_id_idx = layer.fields().indexFromName("device_id")
            name_idx = layer.fields().indexFromName("name")

            if device_id_idx == -1:
                return

            for feature in layer.getFeatures():
                device_id = feature.attribute(device_id_idx)

                # SAFETY FIX: Validate device_id before use
                if not device_id:
                    skipped_invalid += 1
                    continue

                # Validate device_id is a string and reasonable length
                if not isinstance(device_id, str):
                    device_id = str(device_id)

                if len(device_id) > 256:
                    logger.warning(
                        "SAR-0uy: Skipping device with excessively long ID: %s...",
                        device_id[:50]
                    )
                    skipped_invalid += 1
                    continue

                if device_id not in devices:
                    name = None
                    if name_idx != -1:
                        name = feature.attribute(name_idx)
                    # Use full device_id for fallback name, not truncated
                    devices[device_id] = {
                        'name': name or f"Device {device_id}",
                        'device_id': device_id
                    }

        extract_from_layer(current_layer)
        extract_from_layer(breadcrumbs_layer)

        if skipped_invalid > 0:
            logger.warning(
                "SAR-0uy: Skipped %d features with invalid/empty device_id",
                skipped_invalid
            )

        logger.info(
            "SAR-0uy: Extracted %d devices from shared layers",
            len(devices)
        )
        return devices

    def _migrate_device_to_per_device(
        self,
        device_id: str,
        device_info: Dict,
        shared_current: Optional[QgsVectorLayer],
        shared_breadcrumbs: Optional[QgsVectorLayer]
    ):
        """
        Migrate a single device from shared layers to per-device layers.

        Creates per-device position and trail layers, then copies
        features from the shared layers.

        Args:
            device_id: Device identifier
            device_info: Dict with 'name' and other device metadata
            shared_current: Source shared current positions layer
            shared_breadcrumbs: Source shared breadcrumbs layer
        """
        logger.debug("SAR-0uy: Migrating device %s (%s)", device_id, device_info.get('name'))

        # Create per-device position layer if we have position data
        if shared_current and self.USE_PER_DEVICE_POSITIONS:
            try:
                pos_layer = self._ensure_device_position_layer(device_id, device_info)
                if pos_layer:
                    self._copy_device_positions(shared_current, pos_layer, device_id)
            except Exception as e:
                logger.warning(
                    "SAR-0uy: Failed to migrate positions for device %s: %s",
                    device_id, e
                )

        # Create per-device trail layer if we have trail data
        if shared_breadcrumbs and self.USE_PER_DEVICE_TRAILS:
            try:
                trail_layer = self._ensure_device_trail_layer(device_id, device_info)
                if trail_layer:
                    self._copy_device_trails(shared_breadcrumbs, trail_layer, device_id)
            except Exception as e:
                logger.warning(
                    "SAR-0uy: Failed to migrate trails for device %s: %s",
                    device_id, e
                )

    def _copy_device_positions(
        self,
        source_layer: QgsVectorLayer,
        target_layer: QgsVectorLayer,
        device_id: str
    ):
        """
        Copy position features for a device from shared to per-device layer.

        For positions, we only keep the latest position (per-device layers
        store single features representing current position).

        SAFETY FIX: Validates geometry before copy to prevent invalid coordinates.

        Args:
            source_layer: Shared current positions layer
            target_layer: Per-device position layer
            device_id: Device to filter by
        """
        import uuid

        device_id_idx = source_layer.fields().indexFromName("device_id")
        if device_id_idx == -1:
            return

        # Find features for this device, keep the latest one
        latest_feature = None
        latest_ts = None
        ts_idx = source_layer.fields().indexFromName("timestamp")

        for feature in source_layer.getFeatures():
            if feature.attribute(device_id_idx) != device_id:
                continue

            # SAFETY FIX: Skip features with invalid geometry
            geom = feature.geometry()
            if geom.isNull() or geom.isEmpty():
                logger.warning(
                    "SAR-0uy: Skipping position with null/empty geometry for device %s",
                    device_id
                )
                continue

            if ts_idx != -1:
                feature_ts = feature.attribute(ts_idx)
                if latest_ts is None or (feature_ts and feature_ts > latest_ts):
                    latest_feature = feature
                    latest_ts = feature_ts
            else:
                latest_feature = feature  # Just take the last one

        if not latest_feature:
            logger.debug("SAR-0uy: No valid position found for device %s", device_id)
            return

        # SAFETY FIX: Final geometry validation before copy
        src_geom = latest_feature.geometry()
        if src_geom.isNull() or src_geom.isEmpty():
            logger.warning(
                "SAR-0uy: Cannot copy position for device %s - invalid geometry",
                device_id
            )
            return

        # Build the new feature FIRST, then clear and add in transaction
        # This ensures we have valid data before modifying target
        new_feature = QgsFeature(target_layer.fields())
        new_feature.setGeometry(src_geom)

        source_fields = source_layer.fields()
        target_fields = target_layer.fields()

        # Copy common attributes
        for field_name in ['device_id', 'name', 'timestamp', 'altitude', 'speed', 'battery']:
            src_idx = source_fields.indexFromName(field_name)
            tgt_idx = target_fields.indexFromName(field_name)
            if src_idx != -1 and tgt_idx != -1:
                new_feature.setAttribute(tgt_idx, latest_feature.attribute(src_idx))

        # Add UUID if target has id field
        id_idx = target_fields.indexFromName("id")
        if id_idx != -1:
            new_feature.setAttribute(id_idx, str(uuid.uuid4()))

        # Copy to target layer - clear and add in single transaction
        with self._layer_transaction(target_layer, f"Position ({device_id})", "migrate position") as edit_layer:
            # Use deleteFeatures instead of truncate to work with transaction rollback
            existing_ids = [f.id() for f in edit_layer.getFeatures()]
            if existing_ids:
                if not edit_layer.deleteFeatures(existing_ids):
                    raise RuntimeError(f"Failed to clear existing features for device {device_id}")

            if not edit_layer.addFeature(new_feature):
                raise RuntimeError(f"Failed to copy position for device {device_id}")

        logger.debug("SAR-0uy: Copied position for device %s", device_id)

    def _copy_device_trails(
        self,
        source_layer: QgsVectorLayer,
        target_layer: QgsVectorLayer,
        device_id: str
    ):
        """
        Copy trail features for a device from shared to per-device layer.

        SAFETY FIX: Validates geometry and uses transaction-safe deletion.

        Args:
            source_layer: Shared breadcrumbs layer
            target_layer: Per-device trail layer
            device_id: Device to filter by
        """
        import uuid

        device_id_idx = source_layer.fields().indexFromName("device_id")
        if device_id_idx == -1:
            return

        # Collect valid features for this device (with geometry validation)
        device_features = []
        skipped_count = 0
        for feature in source_layer.getFeatures():
            if feature.attribute(device_id_idx) != device_id:
                continue

            # SAFETY FIX: Skip features with invalid geometry
            geom = feature.geometry()
            if geom.isNull() or geom.isEmpty():
                skipped_count += 1
                continue

            device_features.append(feature)

        if skipped_count > 0:
            logger.warning(
                "SAR-0uy: Skipped %d trail segments with invalid geometry for device %s",
                skipped_count, device_id
            )

        if not device_features:
            logger.debug("SAR-0uy: No valid trail segments found for device %s", device_id)
            return

        # Build all new features FIRST before modifying target
        source_fields = source_layer.fields()
        target_fields = target_layer.fields()
        new_features = []

        for idx, feature in enumerate(device_features):
            new_feature = QgsFeature(target_fields)
            new_feature.setGeometry(feature.geometry())

            # Copy common attributes
            for field_name in ['device_id', 'name', 'timestamp']:
                src_idx = source_fields.indexFromName(field_name)
                tgt_idx = target_fields.indexFromName(field_name)
                if src_idx != -1 and tgt_idx != -1:
                    new_feature.setAttribute(tgt_idx, feature.attribute(src_idx))

            # Set per-device trail specific fields
            id_idx = target_fields.indexFromName("id")
            if id_idx != -1:
                new_feature.setAttribute(id_idx, str(uuid.uuid4()))

            seg_idx = target_fields.indexFromName("segment_index")
            if seg_idx != -1:
                new_feature.setAttribute(seg_idx, idx)

            new_features.append(new_feature)

        # Copy to target layer - clear and add in single transaction
        with self._layer_transaction(target_layer, f"Trail ({device_id})", "migrate trails") as edit_layer:
            # Use deleteFeatures instead of truncate to work with transaction rollback
            existing_ids = [f.id() for f in edit_layer.getFeatures()]
            if existing_ids:
                if not edit_layer.deleteFeatures(existing_ids):
                    raise RuntimeError(f"Failed to clear existing trail features for device {device_id}")

            # Add all features
            failed_count = 0
            for new_feature in new_features:
                if not edit_layer.addFeature(new_feature):
                    failed_count += 1

            if failed_count > 0:
                raise RuntimeError(
                    f"Failed to copy {failed_count}/{len(new_features)} trail segments for device {device_id}"
                )

        logger.debug("SAR-0uy: Copied %d trail segments for device %s", len(new_features), device_id)

    def _archive_shared_tracking_layers(
        self,
        current_layer: Optional[QgsVectorLayer],
        breadcrumbs_layer: Optional[QgsVectorLayer]
    ):
        """
        Archive (rename and hide) shared tracking layers.

        Non-destructive: Layers are renamed with suffix and hidden,
        not deleted. This allows rollback if needed.

        SAFETY FIX: Stores original name in custom property for proper rollback.

        Args:
            current_layer: Shared current positions layer
            breadcrumbs_layer: Shared breadcrumbs layer
        """
        def archive_layer(layer: QgsVectorLayer):
            if not layer or not layer.isValid():
                return

            # SAFETY FIX: Check layer is not being edited
            if layer.isEditable():
                logger.warning(
                    "SAR-0uy: Cannot archive layer %s - currently being edited",
                    layer.name()
                )
                return

            old_name = layer.name()
            new_name = f"{old_name}{self.ARCHIVE_SUFFIX}"

            # SAFETY FIX: Store original name for proper rollback
            layer.setCustomProperty("sartracker:original_name", old_name)

            # Rename the layer
            layer.setName(new_name)

            # Verify rename worked
            if layer.name() != new_name:
                logger.error("SAR-0uy: Failed to rename layer %s -> %s", old_name, new_name)
                return

            # Mark as archived
            layer.setCustomProperty("sartracker:archived", True)
            layer.setCustomProperty("sartracker:archived_at", datetime.now(timezone.utc).isoformat())

            # Hide in layer tree
            root = QgsProject.instance().layerTreeRoot()
            tree_layer = root.findLayer(layer.id())
            if tree_layer:
                tree_layer.setItemVisibilityChecked(False)

            logger.info("SAR-0uy: Archived layer %s -> %s", old_name, new_name)

        archive_layer(current_layer)
        archive_layer(breadcrumbs_layer)

    def rollback_per_device_migration(self) -> bool:
        """
        Rollback per-device migration by restoring archived shared layers.

        This method:
        1. Finds archived shared layers
        2. Restores their original names (from stored custom property)
        3. Makes them visible again
        4. Optionally removes per-device layers

        Note: Does NOT delete per-device layers by default for safety.

        Returns:
            True if rollback successful, False otherwise
        """
        logger.info("SAR-0uy: Starting migration rollback")

        archived_current = None
        archived_breadcrumbs = None

        # Find archived layers
        for layer in QgsProject.instance().mapLayers().values():
            if not isinstance(layer, QgsVectorLayer):
                continue

            if layer.customProperty("sartracker:archived") and self.ARCHIVE_SUFFIX in layer.name():
                layer_type = layer.customProperty("sartracker:type")
                if layer_type == "current_position":
                    archived_current = layer
                elif layer_type == "breadcrumb":
                    archived_breadcrumbs = layer

        if not archived_current and not archived_breadcrumbs:
            logger.warning("SAR-0uy: No archived layers found for rollback")
            return False

        def restore_layer(layer: QgsVectorLayer, fallback_name: str):
            if not layer:
                return

            # SAFETY FIX: Get original name from stored property, with fallback
            original_name = layer.customProperty("sartracker:original_name") or fallback_name

            layer.setName(original_name)
            layer.removeCustomProperty("sartracker:archived")
            layer.removeCustomProperty("sartracker:archived_at")
            layer.removeCustomProperty("sartracker:original_name")

            root = QgsProject.instance().layerTreeRoot()
            tree_layer = root.findLayer(layer.id())
            if tree_layer:
                tree_layer.setItemVisibilityChecked(True)

            logger.info("SAR-0uy: Restored layer %s", original_name)

        if archived_current:
            restore_layer(archived_current, "Current – Active")

        if archived_breadcrumbs:
            restore_layer(archived_breadcrumbs, "Breadcrumbs")

        logger.info("SAR-0uy: Migration rollback completed")
        return True

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

        if not self.USE_PER_DEVICE_TRAILS:
            raise LayerError("Per-device tracking is disabled for breadcrumbs.", title="Tracking Disabled")

        self._ensure_per_device_ready()

        total_inputs = len(positions) if isinstance(positions, list) else 0
        if self._maybe_schedule_breadcrumb_task(positions, gap_minutes, total_inputs, processed_segments):
            return

        validated_segments = validate_processed_segments(processed_segments, gap_minutes)
        sanitized_positions = sanitize_breadcrumb_positions(positions)
        self._report_validation_warning(
            "Breadcrumbs",
            total_inputs,
            sanitized_positions.invalid_count,
            sanitized_positions.last_error
        )

        processed_payload = None
        if validated_segments is not None:
            processed_payload = {
                "segments": validated_segments,
                "time_gap_minutes": gap_minutes,
            }

        self._update_breadcrumbs_per_device(
            sanitized_positions.valid,
            gap_minutes,
            processed_segments=processed_payload
        )

        self._log_tracking_event(
            None,  # No single layer
            "BREADCRUMBS_PER_DEVICE",
            "update",
            payload_items=total_inputs,
            device_count=len(set(p.get('device_id') for p in (positions or []) if p.get('device_id')))
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
                    'line_style': 'dash',
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
                    'line_style': 'dash',
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
        Delete all current positions for given device IDs and remove position layers.

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

        self._ensure_per_device_ready()
        factory = self._get_per_device_factory()

        deleted = 0
        for device_id in device_ids:
            layer = self._get_existing_device_position_layer(device_id)
            if not layer or not layer.isValid():
                continue

            device_name = layer.customProperty(self.DEVICE_NAME_PROP)
            if not device_name:
                root = QgsProject.instance().layerTreeRoot()
                node = root.findLayer(layer.id()) if root else None
                parent = node.parent() if node else None
                if isinstance(parent, QgsLayerTreeGroup):
                    device_name = parent.name()

            count = layer.featureCount()
            if count:
                with self._layer_transaction(layer, layer.name(), "delete device positions") as edit_layer:
                    self._clear_layer_features(edit_layer, layer.name())
                layer.triggerRepaint()
                deleted += count

            item_id = layer.customProperty(SAR_ITEM_ID)
            if item_id:
                if not factory.delete_item_layer(item_id, remove_table=True, hard_delete=True):
                    raise RuntimeError(f"Failed to delete position layer for device {device_id}")
            else:
                QgsProject.instance().removeMapLayer(layer.id())

            self._device_position_layers.pop(device_id, None)
            self._remove_device_group_if_empty(device_name, GroupNames.CURRENT_POSITIONS)

        logger.info(
            "[TrackingManager] Deleted %s position(s) across %s device(s)",
            deleted,
            len(device_ids)
        )
        return deleted

    def delete_device_breadcrumbs(
        self,
        device_ids: List[str],
        updated_by: Optional[str] = None
    ) -> int:
        """
        Delete breadcrumbs for given device IDs and remove trail layers.

        Args:
            device_ids: List of device IDs to remove
            updated_by: Coordinator name for audit trail

        Returns:
            Number of breadcrumb segments deleted
        """
        if not isinstance(device_ids, list) or not device_ids:
            raise ValueError("device_ids must be a non-empty list")

        self._ensure_per_device_ready()
        factory = self._get_per_device_factory()

        deleted = 0
        for device_id in device_ids:
            layer = self._get_existing_device_trail_layer(device_id)
            if not layer or not layer.isValid():
                continue

            device_name = layer.customProperty(self.DEVICE_NAME_PROP)
            if not device_name:
                root = QgsProject.instance().layerTreeRoot()
                node = root.findLayer(layer.id()) if root else None
                parent = node.parent() if node else None
                if isinstance(parent, QgsLayerTreeGroup):
                    device_name = parent.name()

            count = layer.featureCount()
            if count:
                with self._layer_transaction(layer, layer.name(), "delete device breadcrumbs") as edit_layer:
                    self._clear_layer_features(edit_layer, layer.name())
                layer.triggerRepaint()
                deleted += count

            item_id = layer.customProperty(SAR_ITEM_ID)
            if item_id:
                if not factory.delete_item_layer(item_id, remove_table=True, hard_delete=True):
                    raise RuntimeError(f"Failed to delete trail layer for device {device_id}")
            else:
                QgsProject.instance().removeMapLayer(layer.id())

            self._device_trail_layers.pop(device_id, None)
            self._remove_device_group_if_empty(device_name, GroupNames.TRACKING)

        logger.info(
            "[TrackingManager] Deleted %s breadcrumb segment(s) across %s device(s)",
            deleted,
            len(device_ids)
        )
        return deleted

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

        self._ensure_per_device_ready()

        trail_layers: Dict[str, QgsVectorLayer] = {}
        for layer in QgsProject.instance().mapLayers().values():
            if not isinstance(layer, QgsVectorLayer):
                continue
            if layer.customProperty(SAR_ITEM_TYPE) != ItemType.DEVICE_TRAIL:
                continue
            if layer.isValid():
                trail_layers[layer.id()] = layer

        if not trail_layers:
            return 0

        # Use timezone-aware datetime to prevent Python 3.9+ comparison crashes
        threshold = datetime.now(timezone.utc) - timedelta(hours=float(older_than_hours))
        total_deleted = 0

        for layer in trail_layers.values():
            end_idx = layer.fields().indexFromName("end_time")
            start_idx = layer.fields().indexFromName("start_time")
            if end_idx == -1 and start_idx == -1:
                logger.warning("Trail layer %s missing time fields; cannot prune", layer.name())
                continue

            feature_ids = []
            for feature in layer.getFeatures(QgsFeatureRequest()):
                ts_val = feature.attribute(end_idx) if end_idx != -1 else feature.attribute(start_idx)
                if not ts_val:
                    continue
                try:
                    ts = parse_iso_timestamp(str(ts_val))
                    if ts.tzinfo is None:
                        ts = ts.replace(tzinfo=timezone.utc)
                except Exception:
                    continue
                if ts < threshold:
                    feature_ids.append(feature.id())

            if not feature_ids:
                continue

            with self._layer_transaction(layer, layer.name(), "prune breadcrumbs") as edit_layer:
                if not edit_layer.deleteFeatures(feature_ids):
                    raise RuntimeError("Failed to delete old breadcrumbs")

            layer.triggerRepaint()
            total_deleted += len(feature_ids)

        if total_deleted:
            logger.info(
                "[TrackingManager] Pruned %s breadcrumb segment(s) older than %sh",
                total_deleted,
                older_than_hours
            )

        return total_deleted

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

        self._ensure_per_device_ready()
        layer = self._get_existing_device_trail_layer(device_id)
        if not layer or not layer.isValid():
            raise RuntimeError("Device trail layer not available")

        if layer.featureCount() == 0:
            raise ValueError(f"No breadcrumbs found for device {device_id}")

        temp_dir = tempfile.mkdtemp(prefix="sartracker_export_")
        # BUG-060 fix: Track temp directory for cleanup
        self._temp_export_dirs.append(temp_dir)
        path = os.path.join(temp_dir, f"{device_id}_track.geojson")

        try:
            options = QgsVectorFileWriter.SaveVectorOptions()
            options.driverName = "GeoJSON"
            result, error_message = QgsVectorFileWriter.writeAsVectorFormatV2(
                layer,
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
