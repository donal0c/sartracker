# -*- coding: utf-8 -*-
"""
Coordinates Controller for SAR Tracker.

Manages the status bar coordinate display, including:
- WGS84 (lat/lon) coordinates
- Irish Grid (ITM / EPSG:2157) eastings/northings
- Timer-based throttled updates
- Safe signal disconnection on cleanup

Phase 5 - Coordinates Controller Extraction:
Consolidates coordinate status bar functionality from sartracker.py into
a single controller with proper lifecycle management.

Qt5/Qt6 Compatible: Uses qgis.PyQt and qt_compat for all Qt imports.

LIFE-SAFETY CRITICAL: Coordinate display must remain accurate and must not
crash during plugin reload cycles. All defensive guards from the original
implementation are preserved.
"""

import math
from typing import Optional, Callable, TYPE_CHECKING

from qgis.PyQt.QtCore import QObject, QTimer
from qgis.PyQt.QtGui import QFont
from qgis.PyQt.QtWidgets import QLabel

from qgis.core import (
    QgsPointXY,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsProject,
)

from ..utils.notify import warning

# sip.isdeleted import pattern (Qt5/Qt6 compatible)
try:
    from qgis.PyQt.sip import isdeleted as sip_isdeleted
except ImportError:
    try:
        import sip
        sip_isdeleted = sip.isdeleted
    except Exception:
        def sip_isdeleted(_obj):
            return False

if TYPE_CHECKING:
    from qgis.gui import QgisInterface


class CoordinatesController(QObject):
    """
    Controller for status bar coordinate display.

    Responsibilities:
    - Create and manage coordinate display label in status bar
    - Handle mouse movement over map canvas (throttled)
    - Transform coordinates to WGS84 and Irish Grid (ITM)
    - Clean up safely on unload (no crashes during plugin reload)

    Dependencies are injected via __init__ to avoid plugin globals.

    CRITICAL: This controller manages Qt signal connections and timers that
    historically caused crashes during plugin reload. All defensive patterns
    from the original implementation are preserved.
    """

    def __init__(
        self,
        iface: "QgisInterface",
        is_unloading: Optional[Callable[[], bool]] = None,
        is_app_quitting: Optional[Callable[[], bool]] = None,
        log_exception: Optional[Callable[[str, Exception], None]] = None,
        parent: Optional[QObject] = None
    ):
        """
        Initialize coordinates controller.

        Args:
            iface: QGIS interface
            is_unloading: Callback to check if plugin is unloading
            is_app_quitting: Callback to check if app is quitting
            log_exception: Callback to log exceptions
            parent: Optional QObject parent
        """
        super().__init__(parent)

        self.iface = iface
        self._is_unloading = is_unloading or (lambda: False)
        self._is_app_quitting = is_app_quitting or (lambda: False)
        self._log_exception = log_exception

        # State variables - verbatim from sartracker.py
        self.coords_label: Optional[QLabel] = None
        self.last_coords_point: Optional[QgsPointXY] = None
        self.coords_update_timer: Optional[QTimer] = None
        self._map_canvas_connected: bool = False
        self._coords_updates_enabled: bool = False
        # BUG-058 FIX: Prevent overlapping timer callbacks and unnecessary updates
        self._coords_update_in_progress: bool = False
        self._coords_point_changed: bool = False
        self._coords_error_logged: bool = False

        # Coordinate systems - Irish Grid (ITM) is EPSG:2157
        self.wgs84 = QgsCoordinateReferenceSystem("EPSG:4326")
        # Use EPSG:2157 (Irish Transverse Mercator / ITM) - the modern Irish Grid
        # Note: EPSG:29903 is the older TM65 Irish Grid which has 1-3m accuracy issues
        self.itm = QgsCoordinateReferenceSystem("EPSG:2157")

    def init(self) -> bool:
        """
        Initialize coordinate label, timer, and map canvas listener.

        Returns:
            True if initialization succeeded, False otherwise.

        SAFETY: All setup is wrapped in try/except. If setup fails,
        cleanup is called to ensure no partial state remains.
        """
        try:
            if self._coords_updates_enabled:
                return True  # Already initialized

            self.coords_label = QLabel()
            self.coords_label.setMinimumWidth(550)
            self.coords_label.setMaximumWidth(550)  # Fixed width prevents jitter

            # Use monospace font for stable width
            font = QFont("Courier New", 10)
            if not font.exactMatch():
                font = QFont("Monospace", 10)
            self.coords_label.setFont(font)

            self.coords_label.setStyleSheet("QLabel { padding: 2px 8px; background-color: #f0f0f0; }")
            self.iface.statusBarIface().addPermanentWidget(self.coords_label)

            # Set up timer to throttle coordinate updates (50ms = 20 updates/sec max)
            # Phase 0 fix: Add parent for proper Qt lifecycle (AI_CODE_REFERENCE.md Pattern 7)
            self.coords_update_timer = QTimer(self.iface.mainWindow())
            self.coords_update_timer.timeout.connect(self._update_coords_display)
            self.coords_update_timer.start(50)
            self._coords_updates_enabled = True

            # Connect to map canvas mouse movement (stores point, actual update happens on timer)
            # Store connection reference for proper cleanup in unload() (Issue #4)
            self.iface.mapCanvas().xyCoordinates.connect(self._on_mouse_move)
            self._map_canvas_connected = True
            return True

        except Exception as exc:
            if self._log_exception:
                self._log_exception("CoordinatesController.init", exc)
            warning(
                self.iface.messageBar(),
                "SAR Tracker",
                "Coordinate status display failed to initialize.",
                duration=5
            )
            self._disable_coords_updates("coordinate status bar setup failed")
            self._map_canvas_connected = False
            self.coords_update_timer = None
            self.coords_label = None
            return False

    def _disable_coords_updates(self, reason: Optional[str] = None):
        """
        Stop coordinate update timers and disconnect their signals safely.

        Args:
            reason: Optional diagnostic string logged once to help trace lifecycle issues.
        """
        if reason:
            print(f"[SARTRACKER] Disabling coordinate updates: {reason}")

        self._coords_updates_enabled = False
        timer = self.coords_update_timer
        if timer:
            try:
                timer.timeout.disconnect(self._update_coords_display)
            except (TypeError, RuntimeError):
                pass
            try:
                # Phase 5 FIX: Add sip_isdeleted check before isActive()
                timer_deleted = False
                try:
                    timer_deleted = sip_isdeleted(timer)
                except Exception:
                    pass  # sip unavailable
                if not timer_deleted and timer.isActive():
                    timer.stop()
            except Exception:
                pass
            try:
                # Only call deleteLater if not already deleted
                try:
                    if not sip_isdeleted(timer):
                        timer.deleteLater()
                except Exception:
                    timer.deleteLater()  # sip unavailable, try anyway
            except Exception:
                pass
            self.coords_update_timer = None

        self.last_coords_point = None

    def _on_mouse_move(self, point: QgsPointXY):
        """
        Handle mouse movement over map canvas.
        Just store the point - actual display update happens on timer.

        Args:
            point: QgsPointXY in map canvas CRS

        SAFETY: This handler may be called after plugin unload if signal
        disconnect failed. Check widget existence before processing.
        """
        # Defensive check: Ensure our widgets haven't been destroyed
        # This prevents crashes if disconnect failed or event arrived during unload
        if not self._coords_updates_enabled or not self.coords_label or not self.coords_update_timer:
            # Plugin is being/has been unloaded, ignore event silently
            # (This is normal during unload, not an error condition)
            return
        try:
            if sip_isdeleted(self.coords_label):
                self._disable_coords_updates("coordinate label deleted during mouse move")
                return
        except Exception:
            # sip.isdeleted can throw if sip unavailable; fail closed
            return

        # Safe to proceed - store point for timer-based update
        self.last_coords_point = point
        # BUG-058 FIX: Mark that we have a new point to process
        self._coords_point_changed = True

    def _update_coords_display(self):
        """
        Update coordinate display in status bar.
        Called by timer to throttle updates.

        SAFETY: Timer may fire during unload or after widgets destroyed.
        Check existence before accessing Qt objects.

        BUG-049 FIX: Added early exit checks for unload/quit states.
        BUG-058 FIX: Prevents overlapping callbacks and skips if no mouse movement.
        """
        # BUG-049 FIX: Early exit if plugin is being unloaded or app is quitting
        if self._is_unloading() or self._is_app_quitting():
            return

        if not self._coords_updates_enabled:
            return

        # BUG-058 FIX: Prevent overlapping timer callbacks
        if self._coords_update_in_progress:
            return

        # BUG-058 FIX: Skip if no new mouse movement since last update
        if not self._coords_point_changed:
            return

        # BUG-058 FIX: Mark callback as in progress and reset changed flag
        self._coords_update_in_progress = True
        self._coords_point_changed = False

        try:
            label = self.coords_label
            if not label:
                self._disable_coords_updates("coordinate label missing before update")
                return

            try:
                if sip_isdeleted(label):
                    self.coords_label = None
                    self._disable_coords_updates("coordinate label deleted before update")
                    return
            except Exception:
                # If sip is unavailable fall back to defensive disable
                self.coords_label = None
                self._disable_coords_updates("unable to verify coordinate label state")
                return

            if not self.last_coords_point:
                return

            try:
                canvas = self.iface.mapCanvas()
            except RuntimeError as exc:
                self._disable_coords_updates(f"map canvas unavailable: {exc}")
                return

            if not canvas:
                self._disable_coords_updates("map canvas not available")
                return

            try:
                if sip_isdeleted(canvas):
                    self._disable_coords_updates("map canvas deleted")
                    return
            except Exception:
                # If sip isn't available just stop the timer to avoid crashes
                self._disable_coords_updates("unable to verify map canvas state")
                return

            try:
                map_settings = canvas.mapSettings()
                canvas_crs = map_settings.destinationCrs()
            except RuntimeError as exc:
                self._disable_coords_updates(f"map settings destroyed: {exc}")
                return

            if not canvas_crs.isValid() or not self.wgs84.isValid() or not self.itm.isValid():
                # CRS stack is not ready yet (project loading/unloading)
                return

            try:
                # Transform to WGS84
                transform_to_wgs84 = QgsCoordinateTransform(
                    canvas_crs,
                    self.wgs84,
                    QgsProject.instance()
                )
                wgs84_point = transform_to_wgs84.transform(self.last_coords_point)

                # Transform to Irish Grid (ITM)
                transform_to_itm = QgsCoordinateTransform(
                    canvas_crs,
                    self.itm,
                    QgsProject.instance()
                )
                itm_point = transform_to_itm.transform(self.last_coords_point)

                # BUG-FIX: Validate transformed coordinates before display
                # int(NaN) raises ValueError, and displaying invalid coords is dangerous
                if (math.isnan(wgs84_point.x()) or math.isnan(wgs84_point.y()) or
                    math.isnan(itm_point.x()) or math.isnan(itm_point.y()) or
                    math.isinf(wgs84_point.x()) or math.isinf(wgs84_point.y()) or
                    math.isinf(itm_point.x()) or math.isinf(itm_point.y())):
                    return  # Skip update, keep last valid display

                # Format display text with fixed-width formatting
                # BUG-FIX: Use round() instead of int() for consistency (BUG-029)
                coords_text = (
                    f"WGS84: {wgs84_point.y():9.6f}°N, {wgs84_point.x():10.6f}°E  |  "
                    f"Irish Grid: E:{round(itm_point.x()):7d}  N:{round(itm_point.y()):7d}"
                )

                # Update label (may raise RuntimeError if widget C++ object destroyed)
                self.coords_label.setText(coords_text)

            except RuntimeError as e:
                # Qt C++ object has been deleted but Python wrapper still exists
                # This is expected during cleanup - mark widget as invalid
                print(f"[SARTRACKER] Coordinate label destroyed, stopping updates")
                self.coords_label = None
                self._disable_coords_updates("coordinate label destroyed during update")
                return

            except Exception as e:
                # Log unexpected errors instead of silent pass
                # This helps diagnose real bugs vs normal cleanup issues
                print(f"[SARTRACKER] Warning: Error updating coordinates display: {e}")
                # Don't spam console - only log first occurrence
                if not self._coords_error_logged:
                    import traceback
                    print(traceback.format_exc())
                    self._coords_error_logged = True

        finally:
            # BUG-058 FIX: Always reset in-progress flag
            self._coords_update_in_progress = False

    def cleanup(self, reason: Optional[str] = None):
        """
        Clean up coordinate display resources.

        This method should be called during plugin unload to:
        1. Stop the update timer
        2. Disconnect map canvas signal
        3. Remove label from status bar

        Args:
            reason: Optional string describing why cleanup is happening

        SAFETY: All cleanup is wrapped in try/except to ensure
        cleanup continues even if individual steps fail.
        Idempotent: Safe to call multiple times.
        """
        # Guard against double cleanup (can happen if both _on_app_about_to_quit and unload are called)
        if hasattr(self, '_cleanup_called') and self._cleanup_called:
            return
        self._cleanup_called = True

        cleanup_reason = reason or "controller cleanup"

        # Step 1: Disable timer and updates
        if self.coords_update_timer or self._coords_updates_enabled:
            self._disable_coords_updates(cleanup_reason)

        # Step 2: Disconnect map canvas signal
        # BUG-045 FIX: Always attempt disconnection regardless of flag state
        # Flag may be out of sync due to exceptions during setup
        # Phase 5 FIX: Add sip_isdeleted checks to prevent crashes on destroyed Qt objects
        try:
            if self.iface:
                try:
                    if sip_isdeleted(self.iface):
                        print("[SARTRACKER] iface already deleted, skipping signal disconnect")
                    else:
                        canvas = self.iface.mapCanvas()
                        if canvas:
                            try:
                                if sip_isdeleted(canvas):
                                    print("[SARTRACKER] mapCanvas already deleted, skipping signal disconnect")
                                else:
                                    canvas.xyCoordinates.disconnect(self._on_mouse_move)
                                    print("[SARTRACKER] xyCoordinates signal disconnected successfully")
                            except Exception:
                                # sip_isdeleted may fail if sip unavailable
                                canvas.xyCoordinates.disconnect(self._on_mouse_move)
                                print("[SARTRACKER] xyCoordinates signal disconnected successfully")
                except Exception:
                    # sip_isdeleted may fail - try direct disconnect
                    if self.iface.mapCanvas():
                        self.iface.mapCanvas().xyCoordinates.disconnect(self._on_mouse_move)
                        print("[SARTRACKER] xyCoordinates signal disconnected successfully (no sip check)")
        except (TypeError, RuntimeError) as e:
            # TypeError: Signal not connected (init never completed)
            # RuntimeError: C++ object already deleted
            if self._map_canvas_connected:
                # Only warn if we expected to be connected
                print(f"[SARTRACKER] BUG-045: Could not disconnect xyCoordinates: {e}")
        except Exception as e:
            # BUG-045 FIX: Catch any other exceptions to ensure cleanup continues
            print(f"[SARTRACKER] BUG-045: Unexpected error disconnecting xyCoordinates: {e}")
        finally:
            self._map_canvas_connected = False

        # Step 3: Remove coordinate label from status bar
        # Phase 5 FIX: Add sip_isdeleted checks
        if self.coords_label:
            try:
                label_deleted = False
                try:
                    label_deleted = sip_isdeleted(self.coords_label)
                except Exception:
                    pass  # sip unavailable, assume not deleted

                if not label_deleted:
                    # Check if status bar is accessible
                    try:
                        if self.iface and not sip_isdeleted(self.iface):
                            status_bar = self.iface.statusBarIface()
                            if status_bar and not sip_isdeleted(status_bar):
                                status_bar.removeWidget(self.coords_label)
                    except Exception:
                        pass  # Status bar inaccessible, skip removal
                    self.coords_label.deleteLater()
            except Exception:
                pass
            self.coords_label = None

    def status_snapshot(self) -> dict:
        """
        Return current status for diagnostics.

        Returns:
            dict with current state information

        SAFETY: Uses sip_isdeleted guards to safely check Qt object state
        even during plugin shutdown.
        """
        # Safely check timer state
        timer_active = False
        if self.coords_update_timer:
            try:
                if not sip_isdeleted(self.coords_update_timer):
                    timer_active = self.coords_update_timer.isActive()
            except Exception:
                pass  # sip unavailable or other error

        # Safely check label state
        label_exists = False
        if self.coords_label:
            try:
                label_exists = not sip_isdeleted(self.coords_label)
            except Exception:
                label_exists = True  # Assume exists if we can't check

        return {
            "coords_updates_enabled": self._coords_updates_enabled,
            "map_canvas_connected": self._map_canvas_connected,
            "timer_active": timer_active,
            "label_exists": label_exists,
            "wgs84_valid": self.wgs84.isValid(),
            "itm_valid": self.itm.isValid(),
        }
