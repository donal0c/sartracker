# -*- coding: utf-8 -*-
"""
Devices Controller for SAR Tracker.

Manages the Devices window lifecycle, signal wiring, and data updates
from the ProviderController.

Qt5/Qt6 Compatible: Uses qgis.PyQt and qt_compat for all Qt imports.
"""

import traceback
from typing import Optional, Callable, List, Dict, TYPE_CHECKING

from qgis.PyQt.QtCore import QObject

from ..utils.notify import error

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
    from ..controllers.provider_controller import ProviderController
    from ..ui.devices_window import DevicesWindow


class DevicesController(QObject):
    """
    Controller for the Devices window.

    Responsibilities:
    - Create and manage Devices window lifecycle
    - Connect to ProviderController.refresh_complete signal
    - Update window with device data when received
    - Clean up on unload

    Dependencies are injected via __init__ or setters.
    """

    def __init__(
        self,
        iface: "QgisInterface",
        provider_controller: Optional["ProviderController"] = None,
        is_unloading: Optional[Callable[[], bool]] = None,
        parent: Optional[QObject] = None
    ):
        """
        Initialize Devices controller.

        Args:
            iface: QGIS interface
            provider_controller: ProviderController for device data
            is_unloading: Callback to check if plugin is unloading
            parent: Optional QObject parent
        """
        super().__init__(parent)

        self.iface = iface
        self._provider_controller = provider_controller
        self._is_unloading_cb = is_unloading or (lambda: False)

        # Window instance (created on demand)
        self._window: Optional["DevicesWindow"] = None

        # Safe-mode callback (set by sartracker)
        self._safe_mode_block: Optional[Callable[[str], bool]] = None

        # Shutdown flag
        self._is_shutting_down = False

        # Last received devices (for refresh on show)
        self._last_devices: List[Dict] = []

        # Connect to provider if already set
        if self._provider_controller:
            self._connect_provider_signals()

    # ------------------------------------------------------------------
    # Dependency Setters (for late binding)
    # ------------------------------------------------------------------

    def set_provider_controller(self, provider_controller: "ProviderController"):
        """
        Set/update provider controller reference and connect signals.

        Args:
            provider_controller: ProviderController instance
        """
        # Disconnect from old provider if set
        if self._provider_controller:
            self._disconnect_provider_signals()

        self._provider_controller = provider_controller

        if self._provider_controller:
            self._connect_provider_signals()

    def set_safe_mode_block(self, callback: Callable[[str], bool]):
        """Set safe-mode block callback."""
        self._safe_mode_block = callback

    # ------------------------------------------------------------------
    # Provider Signal Management
    # ------------------------------------------------------------------

    def _connect_provider_signals(self):
        """Connect to provider controller signals."""
        if not self._provider_controller:
            return

        try:
            self._provider_controller.refresh_complete.connect(self._on_refresh_complete)
            print("[DevicesController] Connected to provider refresh_complete signal")
        except Exception as exc:
            print(f"[DevicesController] Warning: Failed to connect provider signals: {exc}")

    def _disconnect_provider_signals(self):
        """Disconnect from provider controller signals."""
        if not self._provider_controller:
            return

        try:
            self._provider_controller.refresh_complete.disconnect(self._on_refresh_complete)
        except (TypeError, RuntimeError):
            pass  # Already disconnected

    def _on_refresh_complete(self, result: dict):
        """
        Handle refresh_complete signal from ProviderController.

        Extracts device list from result and updates window if open.

        Args:
            result: Dict with 'devices' key containing list of device dicts
        """
        if self._is_unloading_cb() or self._is_shutting_down:
            return

        # Extract devices from result
        devices = result.get('devices', [])
        self._last_devices = devices

        # Update window if open
        if self._window and not sip_isdeleted(self._window):
            try:
                self._window.update_devices(devices)
            except RuntimeError:
                self._window = None
            except Exception as exc:
                print(f"[DevicesController] Warning: Failed to update devices window: {exc}")

    # ------------------------------------------------------------------
    # Window Lifecycle
    # ------------------------------------------------------------------

    def toggle_window(self):
        """
        Toggle the Devices window visibility.

        If window is open and visible, close it.
        If window is closed or not visible, show it.
        """
        if self._window:
            try:
                if not sip_isdeleted(self._window) and self._window.isVisible():
                    self.close_window()
                    return
            except RuntimeError:
                self._window = None

        self.show_window()

    def show_window(self):
        """Show the Devices window (create if needed)."""
        if self._safe_mode_block and self._safe_mode_block("Devices"):
            return

        try:
            from ..ui.devices_window import DevicesWindow

            # Reuse existing window if visible
            if self._window:
                try:
                    if sip_isdeleted(self._window):
                        self._window = None
                    elif self._window.isVisible():
                        self._window.raise_()
                        self._window.activateWindow()
                        return
                except RuntimeError:
                    self._window = None

            # Create new window
            self._window = DevicesWindow(self.iface.mainWindow())

            # Wire signals
            self._connect_window_signals()

            # Update with last known devices
            if self._last_devices:
                self._window.update_devices(self._last_devices)

            # Show non-modal
            self._window.show()
            print("[DevicesController] Devices window opened")

        except Exception as e:
            error(
                self.iface.messageBar(),
                "SAR Tracker",
                f"Failed to open Devices window: {e}",
                duration=5
            )
            print(f"[DevicesController] ERROR opening Devices window: {e}")
            traceback.print_exc()

    def _connect_window_signals(self):
        """Connect window signals to handlers."""
        if not self._window:
            return

        self._window.closed.connect(self._on_window_closed)
        self._window.refresh_requested.connect(self._on_refresh_requested)
        self._window.device_selected.connect(self._on_device_selected)

    def _disconnect_window_signals(self):
        """
        Disconnect window signals from handlers.

        CRITICAL: Must be called before window is destroyed to prevent
        callbacks into deleted Qt objects.
        """
        if not self._window:
            return

        try:
            if sip_isdeleted(self._window):
                return

            for signal, handler in [
                (self._window.closed, self._on_window_closed),
                (self._window.refresh_requested, self._on_refresh_requested),
                (self._window.device_selected, self._on_device_selected),
            ]:
                try:
                    signal.disconnect(handler)
                except (TypeError, RuntimeError):
                    pass  # Already disconnected
        except (RuntimeError, AttributeError):
            pass  # Window already deleted

    def refresh_window(self):
        """Refresh the Devices window if open."""
        if self._is_unloading_cb() or self._is_shutting_down:
            return

        if self._window:
            try:
                if sip_isdeleted(self._window):
                    self._window = None
                    return
                # Update with last known devices
                self._window.update_devices(self._last_devices)
            except RuntimeError:
                self._window = None
            except Exception as exc:
                print(f"[DevicesController] Warning: Failed to refresh window: {exc}")

    def close_window(self):
        """Close the window if open."""
        if self._window:
            try:
                if not sip_isdeleted(self._window):
                    self._window.close()
            except Exception:
                pass
            self._window = None

    # ------------------------------------------------------------------
    # Signal Handlers
    # ------------------------------------------------------------------

    def _on_window_closed(self):
        """Handle window closed signal."""
        # CRITICAL: Disconnect signals before clearing reference
        self._disconnect_window_signals()
        self._window = None
        print("[DevicesController] Devices window closed")

    def _on_refresh_requested(self):
        """Handle refresh request from window."""
        if self._is_unloading_cb() or self._is_shutting_down:
            return

        # Trigger a provider refresh if available
        if self._provider_controller and hasattr(self._provider_controller, 'schedule_refresh'):
            try:
                self._provider_controller.schedule_refresh()
                print("[DevicesController] Triggered provider refresh")
            except Exception as exc:
                print(f"[DevicesController] Warning: Failed to trigger refresh: {exc}")

    def _on_device_selected(self, device_id: str):
        """
        Handle device selection from window.

        Future enhancement: Could zoom to device location on map.

        Args:
            device_id: ID of selected device
        """
        if self._is_unloading_cb() or self._is_shutting_down:
            return

        print(f"[DevicesController] Device selected: {device_id}")
        # Future: Could zoom to device location
        # For now, just log the selection

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def cleanup(self):
        """Clean up controller resources."""
        self._is_shutting_down = True

        # Disconnect from provider
        self._disconnect_provider_signals()

        # Close window
        self.close_window()

        # Clear references
        self._provider_controller = None
        self._last_devices = []

        print("[DevicesController] Cleaned up")

    @property
    def window(self) -> Optional["DevicesWindow"]:
        """Get current window instance (may be None)."""
        return self._window

    def status_snapshot(self) -> dict:
        """Return current status for diagnostics."""
        return {
            "window_open": self._window is not None,
            "is_shutting_down": self._is_shutting_down,
            "device_count": len(self._last_devices),
            "provider_connected": self._provider_controller is not None,
        }


__all__ = ['DevicesController']
