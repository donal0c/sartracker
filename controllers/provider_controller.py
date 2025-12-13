# -*- coding: utf-8 -*-
"""
Provider Controller for SAR Tracker.

Manages data provider lifecycle: selection, testing, polling, and status.
Ensures provider operations follow AI_CODE_REFERENCE.md patterns for
timers, tasks, signals, and defensive guards.

Phase 3 - UI & Controller Preparation:
This controller orchestrates provider changes using the two-phase commit
pattern from Phase 2, exposes status for diagnostics, and manages polling
timers with proper cleanup.

Qt5/Qt6 Compatible: Uses qgis.PyQt and qt_compat for all Qt imports.
"""

from qgis.PyQt.QtCore import QObject, pyqtSignal, QTimer
from typing import Optional, Dict, Any

from ..providers.registry import registry as provider_registry
from ..providers.base import Provider
from ..utils.task_manager import TaskManager
from ..utils.notify import info, warning, error, success


class ProviderController(QObject):
    """
    Controller for provider selection, connection testing, and polling.

    Responsibilities:
    - Manage active provider instance + config
    - Orchestrate connection tests via TaskManager (Pattern 6)
    - Control polling timer with four-layer cleanup (Pattern 7)
    - Emit status updates for UI and diagnostics
    - Implement two-phase commit for provider changes (Phase 2 pattern)

    Signals:
        status_changed: Emitted when provider status changes
            Args: dict with keys:
                - provider: str (provider name or None)
                - state: str ('ok', 'error', 'testing', 'connecting')
                - message: str (status message for UI)
                - last_refresh: str or None (ISO timestamp)
                - devices_count: int (cached device count)
                - poll_interval: int or None (seconds)
                - poll_active: bool

        config_error: Emitted when provider config validation fails
            Args: str (error message for UI)

    LIFE-SAFETY CRITICAL: All async handlers use defensive guards (Pattern 9).
    """

    status_changed = pyqtSignal(dict)   # {'provider': str, 'state': 'ok|error|testing', ...}
    config_error = pyqtSignal(str)      # For UI to display via notify.error
    provider_connected = pyqtSignal(str, dict)  # (provider_name, config) - emitted on successful connection
    refresh_requested = pyqtSignal()  # Trigger data refresh (connected to sartracker._on_refresh_data)

    def __init__(self, iface, task_manager: TaskManager, parent=None):
        """
        Initialize provider controller.

        Args:
            iface: QGIS interface (for messageBar notifications)
            task_manager: TaskManager instance for background operations
            parent: Optional QObject parent (for Qt lifecycle)
        """
        super().__init__(parent)

        # QGIS interface and task manager
        self.iface = iface
        self.task_manager = task_manager

        # BUG-030 FIX: Shutdown flag for thread-safe callback guards
        # This flag is checked atomically in callbacks to prevent accessing
        # destroyed objects during plugin shutdown
        self._is_shutting_down = False

        # Active provider state
        self.provider: Optional[Provider] = None
        self.provider_name: Optional[str] = None
        self.provider_config: Optional[Dict] = None

        # Shadow state for two-phase commit (Phase 2 pattern)
        self._pending_provider: Optional[Provider] = None
        self._pending_provider_name: Optional[str] = None
        self._pending_provider_config: Optional[Dict] = None
        self._pending_test_only: bool = False  # FIX ISSUE #4: Track test-only mode

        # Polling timer (Pattern 7: Layer 1 - Qt parent assignment)
        self.poll_timer = QTimer(self)
        self.poll_timer.timeout.connect(self._on_poll_timer)

        # Status tracking
        self._cached_device_count = 0
        self._last_refresh_time: Optional[str] = None
        self._last_error_message: Optional[str] = None
        self._last_refresh_duration_ms: Optional[float] = None
        self._last_status_dict = self._build_status_dict('ok', 'No provider loaded')

    def set_provider(self, provider_name: str, config: Dict[str, Any], test_only: bool = False):
        """
        Set active provider with connection test (two-phase commit).

        Phase 1: Validation
        - Create provider in shadow state
        - Test connection asynchronously
        - Current provider remains active

        Phase 2: Commit (only if validation succeeds AND test_only=False)
        - Replace active provider with validated shadow provider
        - Update UI and emit status
        - Trigger initial data load

        Rollback (if validation fails OR test_only=True):
        - Discard shadow provider
        - Current provider unchanged

        Args:
            provider_name: Provider identifier (e.g., 'csv', 'http_traccar')
            config: Provider-specific configuration dict
            test_only: If True, only test connection without committing provider
                      (for "Test Connection" button vs "Connect" button)

        Raises:
            ValueError: If provider_name invalid or config malformed
            KeyError: If provider not registered

        Qt5/Qt6 Compatible: Pure Python + pyqtSignal.
        """
        # INPUT VALIDATION (AI_CODE_REFERENCE.md - mandatory pattern)
        if not provider_name or not isinstance(provider_name, str):
            raise ValueError("Provider name must be a non-empty string")

        if config is None or not isinstance(config, dict):
            raise ValueError("Provider config must be a dictionary")

        # DEFENSIVE GUARD: Prevent concurrent provider changes
        if self._pending_provider is not None:
            warning(
                self.iface.messageBar(),
                "Provider Controller",
                "Provider change already in progress, please wait...",
                duration=2
            )
            return

        try:
            # PHASE 1: CREATE PROVIDER IN SHADOW STATE
            print(f"[PROVIDER_CONTROLLER] Starting provider change: {provider_name}")

            # Create provider via registry (may raise KeyError or ProviderDataError)
            new_provider = provider_registry.get_provider(provider_name, config)

            # Store in SHADOW variables (not committed yet)
            self._pending_provider = new_provider
            self._pending_provider_name = provider_name
            self._pending_provider_config = config
            self._pending_test_only = test_only  # FIX ISSUE #4: Remember test-only mode

            # Emit testing status
            self._emit_status('testing', f'Testing connection to {provider_name}...')

            # Show testing notification
            info(
                self.iface.messageBar(),
                "Provider Controller",
                f"Testing connection to {provider_name}...",
                duration=2
            )

            # PHASE 1: TEST CONNECTION IN BACKGROUND
            # Use ConnectionTestTask from providers.tasks (import locally to avoid circular deps)
            from ..providers.tasks import ConnectionTestTask

            test_task = ConnectionTestTask(
                self._pending_provider,
                f"Testing {provider_name} connection"
            )

            # Start task with managed lifecycle (Pattern 6)
            self.task_manager.start_task(
                task=test_task,
                on_complete=self._on_connection_test_complete,
                on_error=self._on_connection_test_error,
                task_id="provider_connection_test"
            )

            print(f"[PROVIDER_CONTROLLER] Connection test task started for: {provider_name}")

        except KeyError as e:
            # Provider not registered
            self._cleanup_shadow_state()
            error_msg = f"Provider '{provider_name}' not found: {e}"
            self.config_error.emit(error_msg)
            error(
                self.iface.messageBar(),
                "Provider Error",
                error_msg,
                duration=5
            )
            print(f"[PROVIDER_CONTROLLER] Provider not found: {e}")

        except Exception as e:
            # Provider creation failed
            self._cleanup_shadow_state()
            error_msg = f"Failed to create {provider_name} provider: {str(e)}"
            self.config_error.emit(error_msg)
            error(
                self.iface.messageBar(),
                "Provider Error",
                error_msg,
                duration=5
            )
            print(f"[PROVIDER_CONTROLLER] Provider creation failed: {e}")

    def _on_connection_test_complete(self, task):
        """
        Handle connection test completion (runs in main thread).

        PHASE 2 COMMIT: Replace active provider with validated shadow provider.
        ROLLBACK: Discard shadow provider if test failed.

        Args:
            task: Completed ConnectionTestTask

        SAFETY: May be called after controller destruction (Pattern 9).
        """
        # BUG-030 FIX: Enhanced thread-safe guard for controller destruction
        # Check shutdown flag FIRST (atomic boolean check), then object references
        if self._is_shutting_down:
            print("[PROVIDER_CONTROLLER] Connection test completed during shutdown - ignoring")
            return

        # CRITICAL GUARD: Check if controller still exists (Pattern 9)
        if not self.iface or not self.task_manager:
            print("[PROVIDER_CONTROLLER] Connection test completed after controller destroyed")
            self._cleanup_shadow_state()
            return

        try:
            # DEFENSIVE CHECK: Ensure we have pending provider state
            if self._pending_provider is None:
                print("[PROVIDER_CONTROLLER] Warning: Connection test completed but no pending provider")
                return

            # Check if connection test succeeded
            if not task.success:
                # ================================================================
                # ROLLBACK: Connection test failed
                # ================================================================
                print(f"[PROVIDER_CONTROLLER] Connection test FAILED for {self._pending_provider_name}")
                print(f"[PROVIDER_CONTROLLER] Rolling back to previous provider: {self.provider_name}")

                error(
                    self.iface.messageBar(),
                    "Connection Failed",
                    f"Could not connect to {self._pending_provider_name}. "
                    + (f"Your current provider ({self.provider_name}) remains active."
                       if self.provider else "No provider loaded."),
                    duration=8
                )

                # ROLLBACK: Discard pending provider
                self._cleanup_shadow_state()
                self._emit_status('error', f'Connection to {self._pending_provider_name} failed')

                return

            # ================================================================
            # FIX ISSUE #4: Check if this is test-only mode
            # ================================================================
            if self._pending_test_only:
                print(f"[PROVIDER_CONTROLLER] Connection test SUCCEEDED for {self._pending_provider_name} (test-only mode)")
                print(f"[PROVIDER_CONTROLLER] NOT committing provider - test-only request")

                # Show success notification but don't commit
                success(
                    self.iface.messageBar(),
                    "Connection Test",
                    f"Connection to {self._pending_provider_name} successful! Click 'Connect' to switch providers.",
                    duration=5
                )

                # ROLLBACK: Discard pending provider (test succeeded, but don't commit)
                pending_name = self._pending_provider_name
                self._cleanup_shadow_state()
                self._emit_status('ok', f'Test successful: {pending_name} (not connected)')

                return

            # ================================================================
            # PHASE 2 COMMIT: Connection test succeeded
            # ================================================================
            print(f"[PROVIDER_CONTROLLER] Connection test SUCCEEDED for {self._pending_provider_name}")
            print(f"[PROVIDER_CONTROLLER] Committing provider change: {self.provider_name} -> {self._pending_provider_name}")

            # Stop polling timer for old provider
            self.stop_polling()

            # ATOMIC COMMIT: Replace current provider with validated pending provider
            self.provider = self._pending_provider
            self.provider_name = self._pending_provider_name
            self.provider_config = self._pending_provider_config

            # Store config for signal emission (before clearing shadow state)
            connected_name = self.provider_name
            connected_config = dict(self.provider_config)

            # Clear shadow state (commit complete)
            self._cleanup_shadow_state()

            print(f"[PROVIDER_CONTROLLER] Provider commit complete: {self.provider_name}")

            # Show success notification
            success(
                self.iface.messageBar(),
                "Provider Controller",
                f"Connected to {self.provider_name} successfully",
                duration=3
            )

            # Emit provider_connected signal for persistence (Phase 3)
            self.provider_connected.emit(connected_name, connected_config)

            # Emit status change
            self._emit_status('ok', f'Connected to {self.provider_name}')

            # FIX ISSUE #1: Auto-load data after successful connection
            # Trigger initial refresh so map isn't empty (regression fix)
            print(f"[PROVIDER_CONTROLLER] Triggering initial data load for {self.provider_name}")
            self.refresh_requested.emit()

        except Exception as e:
            # DEFENSIVE: Catch all exceptions to prevent error handler crashes
            print(f"[PROVIDER_CONTROLLER] Exception in _on_connection_test_complete: {e}")
            import traceback
            traceback.print_exc()

            # Clean up shadow state (preserve current provider on error)
            self._cleanup_shadow_state()
            self._emit_status('error', f'Unexpected error during provider setup: {str(e)}')

            error(
                self.iface.messageBar(),
                "Provider Error",
                f"Unexpected error: {str(e)}",
                duration=5
            )

    def _on_connection_test_error(self, task):
        """
        Handle connection test error or cancellation (runs in main thread).

        ROLLBACK: Discard shadow provider on error/timeout.

        Args:
            task: Failed or cancelled ConnectionTestTask

        SAFETY: May be called after controller destruction (Pattern 9).
        """
        # BUG-030 FIX: Enhanced thread-safe guard for controller destruction
        # Check shutdown flag FIRST (atomic boolean check), then object references
        if self._is_shutting_down:
            print("[PROVIDER_CONTROLLER] Connection test error during shutdown - ignoring")
            return

        # CRITICAL GUARD: Check if controller still exists (Pattern 9)
        if not self.iface or not self.task_manager:
            print("[PROVIDER_CONTROLLER] Connection test error after controller destroyed")
            self._cleanup_shadow_state()
            return

        try:
            # DEFENSIVE CHECK: Ensure we have pending provider state
            if self._pending_provider is None:
                print("[PROVIDER_CONTROLLER] Warning: Connection test error but no pending provider")
                return

            # ================================================================
            # ROLLBACK: Connection test failed/timed out/cancelled
            # ================================================================
            print(f"[PROVIDER_CONTROLLER] Connection test ERROR for {self._pending_provider_name}")
            print(f"[PROVIDER_CONTROLLER] Rolling back to previous provider: {self.provider_name}")

            # Get error message
            error_msg = (
                task.error_message
                if hasattr(task, 'error_message') and task.error_message
                else "Connection test failed or was cancelled"
            )

            # Show user-friendly error with rollback context
            error(
                self.iface.messageBar(),
                "Connection Failed",
                f"{self._pending_provider_name}: {error_msg}. "
                + (f"Your current provider ({self.provider_name}) remains active."
                   if self.provider else "No provider loaded."),
                duration=8
            )

            # ROLLBACK: Discard pending provider
            self._cleanup_shadow_state()
            self._emit_status('error', f'Connection error: {error_msg}')

        except Exception as e:
            # Last resort error handling
            print(f"[PROVIDER_CONTROLLER] Error in connection test error handler: {e}")
            import traceback
            traceback.print_exc()

            # Best effort: clean up shadow state
            self._cleanup_shadow_state()

    def start_polling(self, interval_seconds: int):
        """
        Start auto-refresh polling.

        Args:
            interval_seconds: Polling interval (must be >= 5 seconds)

        Raises:
            ValueError: If interval < 5
            RuntimeError: If no provider is set

        Qt5/Qt6 Compatible: Uses QTimer.
        """
        # INPUT VALIDATION
        if interval_seconds < 5:
            raise ValueError(f"Polling interval must be >= 5 seconds, got {interval_seconds}")

        if not self.provider:
            raise RuntimeError("Cannot start polling without an active provider")

        # Stop existing timer if running
        self.stop_polling()

        # Start timer (interval in milliseconds)
        self.poll_timer.start(interval_seconds * 1000)
        print(f"[PROVIDER_CONTROLLER] Polling started: {interval_seconds}s interval")

        # Emit status update
        self._emit_status('ok', f'Polling every {interval_seconds}s')

    def stop_polling(self):
        """
        Stop auto-refresh polling.

        Qt5/Qt6 Compatible: Uses QTimer.
        """
        if self.poll_timer.isActive():
            self.poll_timer.stop()
            print("[PROVIDER_CONTROLLER] Polling stopped")

        # Emit status update
        self._emit_status('ok', 'Polling stopped')

    def refresh_now(self) -> bool:
        """
        Trigger immediate data refresh.

        Emits refresh_requested signal which sartracker.py connects to
        _on_refresh_data() method for actual refresh execution.

        Returns:
            True if refresh started, False if no provider set

        Qt5/Qt6 Compatible: Uses pyqtSignal.
        """
        if self._is_shutting_down:
            return False

        if not self.provider:
            warning(
                self.iface.messageBar(),
                "Provider Controller",
                "No provider loaded. Please load a provider first.",
                duration=3
            )
            return False

        # Emit refresh signal (sartracker.py will handle actual refresh via _on_refresh_data)
        self.refresh_requested.emit()
        return True

    def _on_poll_timer(self):
        """
        Handle polling timer timeout.

        SAFETY: Timer may fire after controller destruction (Pattern 7).
        """
        if self._is_shutting_down:
            return

        # DEFENSIVE GUARD: Check if controller still valid (Pattern 9)
        if not self.provider or not self.iface:
            return

        # Trigger refresh
        self.refresh_now()

    def status_snapshot(self) -> Dict[str, Any]:
        """
        Get current controller status for diagnostics.

        Returns pure Python data structures (no Qt types) with:
        - provider: str or None
        - state: str ('ok', 'error', 'testing', 'connecting')
        - message: str
        - poll_interval: int or None (seconds)
        - poll_active: bool
        - devices_count: int
        - last_refresh: str or None (ISO timestamp)

        Qt5/Qt6 Compatible: Pure Python dict.
        """
        return dict(self._last_status_dict)

    def _emit_status(self, state: str, message: str):
        """
        Build and emit status change signal.

        Args:
            state: State string ('ok', 'error', 'testing', 'connecting', 'refreshing')
            message: Human-readable status message

        Qt5/Qt6 Compatible: Pure Python dict + pyqtSignal.
        """
        if state == 'error':
            self._last_error_message = message
        elif state == 'ok':
            self._last_error_message = None
        self._last_status_dict = self._build_status_dict(state, message)
        self.status_changed.emit(dict(self._last_status_dict))

    def _build_status_dict(self, state: str, message: str) -> Dict[str, Any]:
        """
        Build status dictionary.

        Args:
            state: State string
            message: Status message

        Returns:
            Status dict for signal emission and diagnostics

        Qt5/Qt6 Compatible: Pure Python dict.
        """
        status_dict = {
            'provider': self.provider_name,
            'state': state,
            'message': message,
            'poll_interval': self.poll_timer.interval() // 1000 if self.poll_timer.isActive() else None,
            'poll_active': self.poll_timer.isActive(),
            'devices_count': self._cached_device_count,
            'last_refresh': self._last_refresh_time,
            'provider_base_url': self._get_provider_base_url(),
            'last_error': self._last_error_message,
            'last_refresh_duration_ms': self._last_refresh_duration_ms
        }
        return status_dict

    def update_refresh_stats(self, devices_count: int, refresh_time: str, refresh_duration_ms: Optional[float] = None):
        """
        Update cached refresh statistics.

        Args:
            devices_count: Number of devices in last refresh
            refresh_time: ISO timestamp of last refresh
            refresh_duration_ms: Optional refresh duration in milliseconds

        Qt5/Qt6 Compatible: Pure Python types.
        """
        self._cached_device_count = devices_count
        self._last_refresh_time = refresh_time
        self._last_refresh_duration_ms = refresh_duration_ms

        # Emit status update
        self._emit_status('ok', f'Last refresh: {devices_count} devices')

    def _get_provider_base_url(self) -> Optional[str]:
        """
        Extract a display-safe base URL for diagnostics.

        Returns:
            str or None: Base URL for HTTP providers, or None if not applicable
        """
        if not self.provider_config:
            return None

        if 'base_url' in self.provider_config:
            return self.provider_config.get('base_url')
        if 'server_url' in self.provider_config:
            return self.provider_config.get('server_url')
        return None

    def _cleanup_shadow_state(self):
        """
        Clear shadow state variables for two-phase commit.

        Preserves current provider state.
        """
        self._pending_provider = None
        self._pending_provider_name = None
        self._pending_provider_config = None
        self._pending_test_only = False  # FIX ISSUE #4: Reset test-only flag

    def cleanup(self):
        """
        Explicit cleanup method for proper resource release (Pattern 7: Layer 2).

        Stops polling timer before controller destruction.
        This method should be called from the plugin's unload() sequence.

        BUG-030 FIX: Sets shutdown flag FIRST to prevent callbacks from
        accessing destroyed objects during cleanup.

        Qt5/Qt6 Compatible: Uses QTimer.isActive(), .stop().
        """
        try:
            # BUG-030 FIX: Set shutdown flag FIRST to prevent in-flight callbacks
            # from accessing destroyed objects. This is atomic (single assignment)
            # and checked at the start of all async callback handlers.
            self._is_shutting_down = True

            # Stop polling timer (Pattern 7: Layer 2)
            if hasattr(self, 'poll_timer') and self.poll_timer:
                if self.poll_timer.isActive():
                    self.poll_timer.stop()
                    print("[PROVIDER_CONTROLLER] Polling timer stopped during cleanup")

            # Clear provider references
            self.provider = None
            self.provider_name = None
            self.provider_config = None

            # Clean up shadow state
            self._cleanup_shadow_state()

            print("[PROVIDER_CONTROLLER] Cleanup complete")

        except Exception as e:
            # Don't let cleanup errors propagate - log and continue
            print(f"[PROVIDER_CONTROLLER] Warning: Error during cleanup: {e}")
            import traceback
            traceback.print_exc()
