# -*- coding: utf-8 -*-
"""
Provider Controller for SAR Tracker.

Manages data provider lifecycle: selection, testing, polling, refresh, and status.
Ensures provider operations follow AI_CODE_REFERENCE.md patterns for
timers, tasks, signals, and defensive guards.

Phase 8 - Provider Workflow Consolidation:
This controller is the SINGLE OWNER of all provider workflows:
- Provider selection + connection testing (two-phase commit)
- Refresh scheduling/polling
- Refresh/load tasks (start/stop/complete/error handling)
- Config save/load/migration helpers

Qt5/Qt6 Compatible: Uses qgis.PyQt and qt_compat for all Qt imports.

LIFE-SAFETY CRITICAL: All async handlers use defensive guards (Pattern 9).
"""

from datetime import datetime, timedelta, timezone
from qgis.PyQt.QtCore import QObject, pyqtSignal, QTimer, QSettings
from typing import Optional, Dict, Any, Callable, List, TYPE_CHECKING

if TYPE_CHECKING:
    from ..utils.breadcrumb_accumulator import BreadcrumbAccumulator

from ..providers.registry import registry as provider_registry
from ..providers.base import Provider
from ..utils.task_manager import TaskManager
from ..utils.notify import (
    info, warning, error, success,
    safe_error, safe_success, safe_warning, safe_info
)
from ..utils.provider_results import sanitize_provider_results
from ..config.keys import ConfigStore, SETTINGS_KEYS
from ..utils.secure_store import SecureStore
from ..utils.device_filtering import should_show_device
from ..config.settings import ACTIVE_DEVICE_STALE_THRESHOLD_SECONDS


def validate_replay_window(start_dt, hours: int, now_dt=None) -> Optional[str]:
    """
    Validate replay window parameters (controller safety net).

    This provides a safety net in case invalid settings reach the controller.
    Primary validation should happen at save time in SettingsPanel.

    Args:
        start_dt: Start datetime (timezone-aware, should be UTC)
        hours: Duration in hours (1-24)
        now_dt: Current datetime for comparison (default: now UTC)

    Returns:
        Error message string if invalid, None if valid.
    """
    if now_dt is None:
        now_dt = datetime.now(timezone.utc)

    # Validate hours range
    if not isinstance(hours, int) or hours < 1 or hours > 24:
        return "Replay hours must be between 1 and 24"

    # Validate start not in future
    if start_dt > now_dt:
        return "Replay start time must be in the past"

    # Validate start within 30 days
    max_lookback = now_dt - timedelta(days=30)
    if start_dt < max_lookback:
        return "Replay start time cannot be more than 30 days ago"

    # Validate end not in future
    end_dt = start_dt + timedelta(hours=hours)
    if end_dt > now_dt:
        return "Replay end time cannot be in the future"

    return None  # Valid


class ProviderController(QObject):
    """
    Controller for provider selection, connection testing, polling, and refresh.

    Phase 8 - Single Owner of Provider Workflows:
    - Manage active provider instance + config
    - Orchestrate connection tests via TaskManager (Pattern 6)
    - Control polling timer with four-layer cleanup (Pattern 7)
    - Own refresh task lifecycle (start/complete/error)
    - Handle config persistence (save/load/migrate)
    - Emit status updates for UI and diagnostics
    - Implement two-phase commit for provider changes (Phase 2 pattern)

    Signals:
        status_changed: Emitted when provider status changes
            Args: dict with keys:
                - provider: str (provider name or None)
                - state: str ('ok', 'error', 'testing', 'connecting', 'refreshing')
                - message: str (status message for UI)
                - last_refresh: str or None (ISO timestamp)
                - devices_count: int (cached device count)
                - poll_interval: int or None (seconds)
                - poll_active: bool
                - data_state: str ('live', 'cached', 'outage', 'unknown')
                - cache_age_seconds: float or None

        config_error: Emitted when provider config validation fails
            Args: str (error message for UI)

        provider_connected: Emitted after successful provider connection
            Args: (provider_name: str, config: dict)

        refresh_started: Emitted when refresh begins
            Args: None

        refresh_complete: Emitted when refresh succeeds with sanitized results
            Args: dict with keys:
                - current: List[dict] - current positions
                - breadcrumbs: List[dict] - breadcrumb points
                - devices: List[dict] - device summaries
                - breadcrumb_processing: dict or None
                - breadcrumb_failures: List[str] - device-specific failures
                - dropped: dict - counts of dropped records
                - was_cached: bool - True if data came from cache
                - cache_age_seconds: float or None
                - outage_recovered: bool - True if this is first success after failures
                - outage_duration_seconds: float or None

        refresh_error: Emitted when refresh fails
            Args: str (error message)

    LIFE-SAFETY CRITICAL: All async handlers use defensive guards (Pattern 9).
    """

    # Status and config signals
    status_changed = pyqtSignal(dict)   # {'provider': str, 'state': 'ok|error|testing', ...}
    config_error = pyqtSignal(str)      # For UI to display via notify.error
    provider_connected = pyqtSignal(str, dict)  # (provider_name, config) - emitted on successful connection

    # Refresh lifecycle signals (Phase 8)
    refresh_started = pyqtSignal()      # Emitted when refresh begins
    refresh_complete = pyqtSignal(dict) # Emitted with sanitized results
    refresh_error = pyqtSignal(str)     # Emitted with error message

    # SAR-f02j: Replay mode visibility signal
    # Emitted when replay mode changes: (enabled, start_iso, end_iso)
    replay_mode_changed = pyqtSignal(bool, str, str)

    # Legacy signal - kept for backwards compatibility during migration
    refresh_requested = pyqtSignal()    # DEPRECATED: Use start_refresh() instead

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
        self._last_data_state = 'unknown'  # live|cached|outage|unknown
        self._last_cache_age_seconds: Optional[float] = None
        self._last_status_dict = self._build_status_dict('ok', 'No provider loaded')

        # ================================================================
        # Phase 8: Refresh state management
        # ================================================================
        self._refresh_in_progress = False
        self._current_refresh_task = None
        self._refresh_started_at: Optional[datetime] = None
        self._current_refresh_incremental = False

        # SAR-la0: Track network failures for recovery notification
        self._consecutive_refresh_failures = 0
        self._first_failure_time: Optional[datetime] = None

        # Dependency injection slots (set via set_*() methods)
        self._layers_controller = None
        self._sar_panel = None
        self._mission_start_getter: Optional[Callable[[], Optional[str]]] = None
        self._mission_active_getter: Optional[Callable[[], bool]] = None

        # SAR-604i: Temp store callbacks for replay mode
        self._temp_store_setter: Optional[Callable[[str], None]] = None  # set_temp_mission_store
        self._temp_store_clearer: Optional[Callable[[], None]] = None    # clear_temp_mission_store
        self._temp_store_getter: Optional[Callable[[], Optional[str]]] = None  # get_temp_mission_store
        self._replay_session_token: Optional[str] = None  # Current replay session ID

        # ================================================================
        # Phase 3 (SAR-4vs): Incremental breadcrumb state (session-scoped)
        # ================================================================
        self._breadcrumb_accumulator: Optional['BreadcrumbAccumulator'] = None
        self._incremental_breadcrumbs_enabled = True  # Feature flag

        # SAR-i1by: Track replay config for change detection
        # Tuple: (enabled, start_iso, hours)
        self._last_replay_config: tuple = (False, None, None)

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
            provider_name: Provider identifier (e.g., 'traccar_http', 'http_traccar')
            config: Provider-specific configuration dict
            test_only: If True, only test connection without committing provider
                      (for "Test Connection" button vs "Connect" button)

        Raises:
            ValueError: If provider_name invalid or config malformed
            KeyError: If provider not registered

        Qt5/Qt6 Compatible: Pure Python + pyqtSignal.
        """
        if self._is_shutting_down or self._task_manager_shutting_down():
            safe_warning(
                self.iface,
                "Provider Controller",
                "Cannot change provider during shutdown.",
                duration=3
            )
            return

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

                # LIFECYCLE SAFETY: Use safe_error for async callback context
                safe_error(
                    self.iface,
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
                # LIFECYCLE SAFETY: Use safe_success for async callback context
                safe_success(
                    self.iface,
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

            # ATOMIC COMMIT: Use tuple assignment for true atomicity
            # BUG-FIX: Prevents inconsistent state if exception occurs between assignments
            self.provider, self.provider_name, self.provider_config = (
                self._pending_provider,
                self._pending_provider_name,
                self._pending_provider_config
            )

            # Store config for signal emission (before clearing shadow state)
            connected_name = self.provider_name
            connected_config = dict(self.provider_config)

            # Clear shadow state (commit complete)
            self._cleanup_shadow_state()
            self._last_data_state = 'unknown'
            self._last_cache_age_seconds = None

            # Phase 3 (SAR-4vs): Reset breadcrumb accumulator on provider change
            print('[PROVIDER_CONTROLLER] Provider changed - resetting breadcrumb accumulator')
            self._init_breadcrumb_accumulator()

            print(f"[PROVIDER_CONTROLLER] Provider commit complete: {self.provider_name}")

            # Show success notification
            # LIFECYCLE SAFETY: Use safe_success for async callback context
            safe_success(
                self.iface,
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
            # Phase 8: Call start_refresh() directly instead of emitting deprecated signal
            print(f"[PROVIDER_CONTROLLER] Triggering initial data load for {self.provider_name}")
            self.start_refresh()

        except Exception as e:
            # DEFENSIVE: Catch all exceptions to prevent error handler crashes
            print(f"[PROVIDER_CONTROLLER] Exception in _on_connection_test_complete: {e}")
            import traceback
            traceback.print_exc()

            # Clean up shadow state (preserve current provider on error)
            self._cleanup_shadow_state()
            self._emit_status('error', f'Unexpected error during provider setup: {str(e)}')

            # LIFECYCLE SAFETY: Use safe_error for async callback context
            safe_error(
                self.iface,
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
            # LIFECYCLE SAFETY: Use safe_error for async callback context
            safe_error(
                self.iface,
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

        # Phase 8: Call start_refresh() directly instead of emitting deprecated signal
        return self.start_refresh()

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
        - data_state: str ('live', 'cached', 'outage', 'unknown')
        - cache_age_seconds: float or None

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
            'last_refresh_duration_ms': self._last_refresh_duration_ms,
            'data_state': self._last_data_state,
            'cache_age_seconds': self._last_cache_age_seconds
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
            self._last_data_state = 'unknown'
            self._last_cache_age_seconds = None

            # Clean up shadow state
            self._cleanup_shadow_state()

            # Phase 8: Cancel any in-progress refresh
            if self._current_refresh_task:
                try:
                    self._current_refresh_task.cancel()
                except Exception:
                    pass
                self._current_refresh_task = None

            # SAR-604i: Clean up replay temp store on shutdown
            self._cleanup_replay_temp_store()

            # Clear dependency references
            self._layers_controller = None
            self._sar_panel = None
            self._mission_start_getter = None
            self._temp_store_setter = None
            self._temp_store_clearer = None
            self._temp_store_getter = None

            # Phase 3 (SAR-4vs): Clear breadcrumb accumulator to release memory
            if self._breadcrumb_accumulator:
                try:
                    self._breadcrumb_accumulator.clear()
                except Exception:
                    pass
                self._breadcrumb_accumulator = None
            self._current_refresh_incremental = False

            print("[PROVIDER_CONTROLLER] Cleanup complete")

        except Exception as e:
            # Don't let cleanup errors propagate - log and continue
            print(f"[PROVIDER_CONTROLLER] Warning: Error during cleanup: {e}")
            import traceback
            traceback.print_exc()

    # ========================================================================
    # Phase 8: Dependency Injection
    # ========================================================================

    def set_layers_controller(self, layers_controller):
        """
        Inject layers controller for refresh result handling.

        Args:
            layers_controller: LayersController instance for updating map layers

        Qt5/Qt6 Compatible: Pure Python reference assignment.
        """
        self._layers_controller = layers_controller

    def set_panel(self, panel):
        """
        Inject SAR panel for UI updates during refresh.

        Args:
            panel: SARPanel instance for device list and loading state

        Qt5/Qt6 Compatible: Pure Python reference assignment.
        """
        self._sar_panel = panel

    def set_mission_start_getter(self, getter: Callable[[], Optional[str]]):
        """
        Inject callback to get mission start time for breadcrumb filtering.

        Args:
            getter: Callable returning ISO8601 timestamp or None

        Qt5/Qt6 Compatible: Pure Python callback.
        """
        self._mission_start_getter = getter

    def set_mission_active_getter(self, getter: Callable[[], bool]):
        """
        Inject callback to determine if a mission is active/paused.

        Args:
            getter: Callable returning True if mission is active/paused
        """
        self._mission_active_getter = getter

    def set_temp_store_handlers(
        self,
        setter: Callable[[str], None],
        clearer: Callable[[], None],
        getter: Callable[[], Optional[str]]
    ):
        """
        SAR-604i: Inject callbacks for temporary mission store management.

        These callbacks are used to manage isolated storage for replay mode.
        When replay is enabled without an active mission, a temp store is
        created. When replay is disabled or a mission starts, the temp
        store is cleaned up.

        Args:
            setter: Callable to set temp store path (layer_manager.set_temp_mission_store)
            clearer: Callable to clear temp store (layer_manager.clear_temp_mission_store)
            getter: Callable to get current temp store path (layer_manager.get_temp_mission_store)
        """
        self._temp_store_setter = setter
        self._temp_store_clearer = clearer
        self._temp_store_getter = getter

    # ========================================================================
    # Phase 3 (SAR-4vs): Incremental Breadcrumb Accumulation
    # ========================================================================

    def _init_breadcrumb_accumulator(self):
        """
        Initialize or reset the breadcrumb accumulator.

        Creates a fresh BreadcrumbAccumulator instance, discarding any
        previously accumulated positions. Called on:
        - First refresh with breadcrumb data
        - New mission start (idle/finished -> active)
        - Provider change commit

        Qt5/Qt6 Compatible: Pure Python.
        """
        from ..utils.breadcrumb_accumulator import BreadcrumbAccumulator
        self._breadcrumb_accumulator = BreadcrumbAccumulator(
            max_positions=100_000  # Match existing limit in tasks.py
        )
        print('[PROVIDER_CONTROLLER] Breadcrumb accumulator initialized')

    def _on_mission_state_changed(self, old_state: str, new_state: str):
        """
        Handle mission state transitions for accumulator lifecycle.

        Called by MissionController when mission state changes. Manages
        breadcrumb accumulator reset/preserve based on transition type.

        Args:
            old_state: Previous mission state ('idle', 'active', 'paused', 'finished')
            new_state: New mission state

        Transition handling:
        - idle/finished -> active: Reset accumulator (new mission)
        - paused -> active: Keep accumulator (resume)
        - Any other: No action

        Qt5/Qt6 Compatible: Pure Python.
        """
        # Reset accumulator on new mission start
        if old_state in ('idle', 'finished') and new_state == 'active':
            print('[PROVIDER_CONTROLLER] New mission - resetting breadcrumb accumulator')
            self._init_breadcrumb_accumulator()
            return

        # Preserve accumulator on resume from pause
        if old_state == 'paused' and new_state == 'active':
            print('[PROVIDER_CONTROLLER] Mission resumed - keeping breadcrumb accumulator')
            # No reset - continue accumulating
            return

    def _check_replay_config_reset(self, replay_enabled: bool, start_iso: Optional[str], hours: Optional[int]):
        """
        Check if replay config changed and reset accumulator if needed.

        SAR-i1by: Prevents stale data from leaking across replay windows or
        into live mode by resetting the accumulator when replay settings change.

        Args:
            replay_enabled: Whether replay mode is currently enabled
            start_iso: Replay start time (ISO8601) or None
            hours: Replay duration in hours or None

        Qt5/Qt6 Compatible: Pure Python.
        """
        last_enabled, last_start, last_hours = self._last_replay_config

        # Determine if there's a meaningful change
        # When replay is disabled, we only care about the enabled flag changing
        # When replay is enabled, we care about all three fields
        needs_reset = False

        if replay_enabled != last_enabled:
            # Enabled/disabled state changed - always reset
            needs_reset = True
        elif replay_enabled:
            # Replay is enabled - check if window changed
            if start_iso != last_start or hours != last_hours:
                needs_reset = True
        # else: replay disabled and was disabled - no reset needed

        if needs_reset:
            # Config changed - reset accumulator
            if self._breadcrumb_accumulator:
                print(f'[PROVIDER_CONTROLLER] Replay config changed: enabled={last_enabled}->{replay_enabled}')
                print('[PROVIDER_CONTROLLER] Resetting breadcrumb accumulator')
                try:
                    self._breadcrumb_accumulator.clear()
                except Exception as e:
                    print(f'[PROVIDER_CONTROLLER] Warning: Error clearing accumulator: {e}')

        # Always update tracked config
        self._last_replay_config = (replay_enabled, start_iso, hours)

    def _manage_replay_temp_store(self, replay_enabled: bool, mission_is_active: bool):
        """
        SAR-604i: Manage temporary mission store for replay mode.

        Creates temp store when replay is enabled without a mission.
        Cleans up temp store when replay is disabled.

        Args:
            replay_enabled: Whether replay mode is enabled
            mission_is_active: Whether a mission is currently active/paused
        """
        if not self._temp_store_setter or not self._temp_store_clearer:
            # Callbacks not wired - skip temp store management
            return

        try:
            current_temp_store = self._temp_store_getter() if self._temp_store_getter else None

            if replay_enabled and not mission_is_active:
                # Replay enabled without mission - ensure temp store exists
                if not current_temp_store:
                    # Create new temp store with unique session token
                    import uuid
                    from ..utils.mission_storage import MissionStorageHelper

                    self._replay_session_token = str(uuid.uuid4())
                    temp_path = MissionStorageHelper.prepare_temp_replay_store(
                        self._replay_session_token
                    )
                    if temp_path:
                        self._temp_store_setter(temp_path)
                        print(f"[PROVIDER_CONTROLLER] Replay temp store created: {temp_path}")
                    else:
                        print("[PROVIDER_CONTROLLER] Warning: Failed to create replay temp store")
            else:
                # Replay disabled or mission active - cleanup temp store if exists
                if current_temp_store:
                    self._cleanup_replay_temp_store()
        except Exception as e:
            print(f"[PROVIDER_CONTROLLER] Warning: Error managing replay temp store: {e}")

    def _cleanup_replay_temp_store(self):
        """
        SAR-604i: Clean up the replay temporary store.

        Clears the temp store from LayerManager and removes the directory.
        Safe to call even if no temp store exists.
        """
        if not self._temp_store_clearer:
            return

        try:
            # Get current temp store path before clearing
            temp_path = self._temp_store_getter() if self._temp_store_getter else None

            # Clear from LayerManager first
            self._temp_store_clearer()

            # Then cleanup filesystem
            if temp_path:
                from ..utils.mission_storage import MissionStorageHelper
                MissionStorageHelper.cleanup_temp_replay_store(temp_path)
                print(f"[PROVIDER_CONTROLLER] Replay temp store cleaned up: {temp_path}")

            self._replay_session_token = None
        except Exception as e:
            print(f"[PROVIDER_CONTROLLER] Warning: Error cleaning up replay temp store: {e}")

    def _get_incremental_timestamps(self, replay_enabled: bool) -> Optional[Dict[str, str]]:
        """
        Get device timestamps for incremental fetch, if applicable.

        SAR-i1by: Incremental fetch is disabled in replay mode to ensure
        complete historical data is fetched for the replay window.

        Args:
            replay_enabled: Whether replay mode is enabled

        Returns:
            Dict of device_id -> ISO timestamp for incremental fetch,
            or None if incremental fetch is disabled.

        Qt5/Qt6 Compatible: Pure Python.
        """
        # Disable incremental fetch in replay mode
        if replay_enabled:
            return None

        # Normal mode - use incremental fetch if enabled
        if self._incremental_breadcrumbs_enabled and self._breadcrumb_accumulator:
            return self._breadcrumb_accumulator.get_latest_timestamps()

        return None

    def get_breadcrumb_stats(self) -> Dict[str, Any]:
        """
        Get breadcrumb accumulator statistics for diagnostics.

        Returns:
            Dict containing:
                - enabled: bool - Whether accumulator is active
                - total_positions: int - Total accumulated positions
                - device_count: int - Number of tracked devices
                - memory_usage_pct: float - Percentage of max capacity used
                - per_device: dict - Per-device position counts

        Qt5/Qt6 Compatible: Pure Python dict.
        Thread Safety: Captures local reference to prevent race condition.
        """
        # Capture local reference to prevent race condition between
        # null check and method call (accumulator could be reset by another thread)
        accumulator = self._breadcrumb_accumulator
        if not accumulator:
            return {'enabled': False}

        try:
            stats = accumulator.stats()
            max_positions = stats.get('max_positions', 100_000)
            return {
                'enabled': True,
                'total_positions': stats['total_positions'],
                'device_count': stats['device_count'],
                'memory_usage_pct': (stats['total_positions'] / max_positions * 100) if max_positions > 0 else 0,
                'per_device': stats.get('positions_per_device', {})
            }
        except Exception as e:
            # Defensive: if accumulator was cleared between capture and use
            print(f'[PROVIDER_CONTROLLER] Warning: get_breadcrumb_stats error: {e}')
            return {'enabled': False, 'error': str(e)}

    # ========================================================================
    # Phase 8: Refresh Workflow (Consolidated)
    # ========================================================================

    def start_refresh(self, since_iso: Optional[str] = None, until_iso: Optional[str] = None) -> bool:
        """
        Start a data refresh using background task.

        This method owns the entire refresh lifecycle:
        - Creates provider-specific refresh task
        - Manages refresh state
        - Emits signals for UI updates

        Args:
            since_iso: Optional ISO8601 timestamp for breadcrumb filtering.
                      If None and mission_start_getter is set, uses mission start time.
            until_iso: Optional ISO8601 timestamp to cap breadcrumb history (replay).

        Returns:
            True if refresh started, False if blocked or no provider

        Qt5/Qt6 Compatible: Uses QgsTask via TaskManager.
        """
        if self._is_shutting_down or self._task_manager_shutting_down():
            return False

        if not self.provider:
            safe_warning(
                self.iface,
                "SAR Tracker",
                "No data source loaded. Please load a data source first.",
                duration=3
            )
            return False

        # Concurrent refresh protection
        if self._refresh_in_progress:
            safe_warning(
                self.iface,
                "SAR Tracker",
                "Refresh already in progress, please wait...",
                duration=2
            )
            return False

        try:
            # Set refresh flag
            self._refresh_in_progress = True
            self._refresh_started_at = datetime.now()

            # Emit started signal for UI
            self.refresh_started.emit()
            self._emit_status('refreshing', 'Refreshing data...')

            # Show loading state in panel if available
            if self._sar_panel:
                try:
                    self._sar_panel.set_loading_state(True)
                except Exception as e:
                    print(f"[PROVIDER_CONTROLLER] Warning: Could not set panel loading state: {e}")

            # Determine replay/test window settings (Traccar HTTP only)
            replay_enabled = False
            replay_start_iso = None
            replay_hours = None
            if self.provider_name == 'traccar_http':
                try:
                    replay_enabled = ConfigStore.get_traccar_test_window_enabled()
                    replay_start_iso = ConfigStore.get_traccar_test_window_start()
                    replay_hours = ConfigStore.get_traccar_test_window_hours()
                except Exception as e:
                    print(f"[PROVIDER_CONTROLLER] Warning: Could not read replay settings: {e}")

            # Replay guard: disable if mission active/paused
            mission_is_active = False
            if replay_enabled and self._mission_active_getter:
                try:
                    mission_is_active = self._mission_active_getter()
                    if mission_is_active:
                        ConfigStore.set_traccar_test_window_enabled(False)
                        replay_enabled = False
                        safe_warning(
                            self.iface,
                            "Replay Disabled",
                            "Replay window disabled while a mission is active.",
                            duration=4
                        )
                        # SAR-604i: Clear temp store when mission becomes active
                        self._cleanup_replay_temp_store()
                except Exception as e:
                    print(f"[PROVIDER_CONTROLLER] Warning: mission active check failed: {e}")

            # SAR-604i: Manage temporary mission store for replay
            self._manage_replay_temp_store(replay_enabled, mission_is_active)

            # SAR-f02j: Emit replay mode signal when disabled
            if not replay_enabled:
                try:
                    self.replay_mode_changed.emit(False, "", "")
                except Exception as sig_err:
                    print(f"[PROVIDER_CONTROLLER] Warning: Could not emit replay_mode_changed: {sig_err}")

            # SAR-i1by: Check if replay config changed and reset accumulator if needed
            self._check_replay_config_reset(replay_enabled, replay_start_iso, replay_hours)

            # Compute replay window if enabled
            effective_since = since_iso
            effective_until = until_iso
            if replay_enabled:
                try:
                    from ..utils.timeparse import parse_iso, format_iso
                    if not replay_start_iso:
                        raise ValueError("Replay start time not set")
                    if not isinstance(replay_hours, int) or replay_hours < 1 or replay_hours > 24:
                        raise ValueError("Replay hours must be between 1 and 24")
                    start_dt = parse_iso(replay_start_iso)
                    now_dt = datetime.now(timezone.utc)

                    # SAR-d39o: Use validation function as safety net
                    validation_error = validate_replay_window(start_dt, replay_hours, now_dt)
                    if validation_error:
                        raise ValueError(validation_error)

                    end_dt = start_dt + timedelta(hours=replay_hours)
                    effective_since = format_iso(start_dt)
                    effective_until = format_iso(end_dt)

                    # SAR-f02j: Emit replay mode signal for UI indicator
                    try:
                        self.replay_mode_changed.emit(True, effective_since, effective_until)
                    except Exception as sig_err:
                        print(f"[PROVIDER_CONTROLLER] Warning: Could not emit replay_mode_changed: {sig_err}")
                except Exception as e:
                    try:
                        ConfigStore.set_traccar_test_window_enabled(False)
                    except Exception as disable_error:
                        print(f"[PROVIDER_CONTROLLER] Warning: Could not disable replay after invalid settings: {disable_error}")
                    safe_warning(
                        self.iface,
                        "Replay Window Invalid",
                        f"Replay window invalid: {e}",
                        duration=4
                    )
                    self._refresh_in_progress = False
                    self._refresh_started_at = None
                    self._clear_loading_state()
                    return False
            else:
                # Get mission start time for breadcrumb filtering.
                if effective_since is None and self._mission_start_getter:
                    try:
                        effective_since = self._mission_start_getter()
                    except Exception as e:
                        print(f"[PROVIDER_CONTROLLER] Warning: Could not get mission start time: {e}")

            # Phase 3 (SAR-4vs): Get device timestamps for incremental fetch
            # SAR-i1by: Disable incremental fetch in replay mode
            device_timestamps = self._get_incremental_timestamps(replay_enabled)
            if device_timestamps:
                print(f'[PROVIDER_CONTROLLER] Incremental fetch for {len(device_timestamps)} devices')
            self._current_refresh_incremental = bool(device_timestamps)

            # Create provider-specific background task
            # SAR-zh9y: Pass replay_enabled to derive current from breadcrumbs
            task = self.provider.create_refresh_task(
                "Refreshing tracking data",
                since_iso=effective_since,
                until_iso=effective_until,
                device_timestamps=device_timestamps,  # Phase 3: incremental fetch
                replay_enabled=replay_enabled  # SAR-zh9y: derive current from breadcrumbs
            )

            # Start task with managed lifecycle
            self.task_manager.start_task(
                task=task,
                on_complete=self._on_refresh_task_complete,
                on_error=self._on_refresh_task_error,
                task_id="provider_refresh"
            )

            # Store task reference for cancellation
            self._current_refresh_task = task

            print(f"[PROVIDER_CONTROLLER] Refresh started for {self.provider_name}")
            return True

        except Exception as e:
            # Reset state on setup error
            self._refresh_in_progress = False
            self._refresh_started_at = None
            self._clear_loading_state()

            print(f"[PROVIDER_CONTROLLER] Error starting refresh: {e}")
            import traceback
            traceback.print_exc()

            safe_error(
                self.iface,
                "Refresh Error",
                f"Failed to start refresh: {str(e)}",
                duration=5
            )
            return False

    def _task_manager_shutting_down(self) -> bool:
        """Check if the task manager is in shutdown mode."""
        if not self.task_manager:
            return False
        if hasattr(self.task_manager, "is_shutting_down"):
            try:
                return bool(self.task_manager.is_shutting_down())
            except Exception:
                return True
        return False

    def _on_refresh_task_complete(self, task):
        """
        Handle successful refresh completion (runs in main thread).

        Processes results, updates layers and panel, emits refresh_complete signal.

        Args:
            task: Completed ProviderRefreshTask with results

        SAFETY: May be called after controller destruction (Pattern 9).
        """
        # BUG-030 FIX: Check shutdown flag FIRST
        if self._is_shutting_down:
            print("[PROVIDER_CONTROLLER] Refresh completed during shutdown - ignoring")
            return

        # CRITICAL GUARD: Check if controller components still exist
        if not self.iface or not self.task_manager:
            print("[PROVIDER_CONTROLLER] Refresh completed after controller destroyed")
            self._refresh_in_progress = False
            return

        try:
            # Reset refresh state
            self._refresh_in_progress = False
            self._current_refresh_task = None
            used_incremental = bool(self._current_refresh_incremental)
            self._current_refresh_incremental = False

            # SAR-la0: Detect network recovery after failures
            was_in_outage = self._consecutive_refresh_failures > 0
            outage_duration = None
            if was_in_outage and self._first_failure_time:
                outage_duration = (datetime.now() - self._first_failure_time).total_seconds()

            # Reset failure tracking on success
            self._consecutive_refresh_failures = 0
            self._first_failure_time = None

            # Hide loading state
            self._clear_loading_state()

            # Check if task was cancelled
            if task.isCanceled():
                safe_info(self.iface, "SAR Tracker", "Refresh cancelled", duration=2)
                return

            # Get and sanitize results from background task
            if not task.results:
                safe_warning(
                    self.iface,
                    "SAR Tracker",
                    "Refresh completed but no data returned",
                    duration=3
                )
                return

            sanitized, dropped = sanitize_provider_results(task.results)
            current = sanitized.get('current', [])
            breadcrumbs = sanitized.get('breadcrumbs', [])
            devices = sanitized.get('devices', [])
            breadcrumb_processing = sanitized.get('breadcrumb_processing')
            breadcrumb_failures = task.results.get('breadcrumb_failures', []) if task.results else []

            print(
                f"[PROVIDER_CONTROLLER] Refresh payload -> "
                f"current:{len(current)} breadcrumbs:{len(breadcrumbs)} devices:{len(devices)}"
            )

            # Update cached stats for diagnostics
            self._cached_device_count = len(devices) if devices else 0
            self._last_refresh_time = datetime.now().isoformat()
            if self._refresh_started_at:
                self._last_refresh_duration_ms = (
                    datetime.now() - self._refresh_started_at
                ).total_seconds() * 1000.0
            else:
                self._last_refresh_duration_ms = None
            self._refresh_started_at = None

            # Surface validation drops (non-fatal)
            dropped_total = sum(dropped.values()) if isinstance(dropped, dict) else 0
            if dropped_total:
                print(
                    f"[PROVIDER_CONTROLLER] Dropped invalid tracking records - "
                    f"current:{dropped.get('current', 0)} breadcrumbs:{dropped.get('breadcrumbs', 0)} "
                    f"devices:{dropped.get('devices', 0)}"
                )
                safe_warning(
                    self.iface,
                    "SAR Tracker",
                    f"Ignored {dropped_total} invalid tracking records (see log for details).",
                    duration=4
                )

            # SAR-nzf: Surface partial breadcrumb failures
            if breadcrumb_failures:
                failed_devices = []
                for failure in breadcrumb_failures[:5]:
                    if ':' in failure:
                        device_name = failure.split(':')[0].strip()
                        failed_devices.append(device_name)
                    else:
                        failed_devices.append(failure[:20])

                if len(breadcrumb_failures) > 5:
                    devices_display = ", ".join(failed_devices) + f" (+{len(breadcrumb_failures) - 5} more)"
                else:
                    devices_display = ", ".join(failed_devices)

                safe_warning(
                    self.iface,
                    "Trail Data Incomplete",
                    f"Failed to fetch trails for: {devices_display}",
                    duration=6
                )
                print(f"[PROVIDER_CONTROLLER] SAR-nzf: Breadcrumb failures: {failed_devices}")

            # =================================================================
            # FR-6 (SAR-5c6): Filter positions to ACTIVE devices only
            # Layer Console (left panel) shows only active tracking layers.
            # SAR Panel devices_list (right panel) shows ALL devices (no filtering).
            #
            # Active device definition (SAR-qvn):
            # - 'online' = always show in layers
            # - 'unknown' within threshold (1 hour) = show (patchy connection grace)
            # - 'unknown' beyond threshold = DO NOT create layer
            # - 'offline' = DO NOT create layer
            # =================================================================
            active_device_ids = set()
            if devices:
                for device in devices:
                    if should_show_device(device, ACTIVE_DEVICE_STALE_THRESHOLD_SECONDS):
                        device_id = device.get('device_id')
                        if device_id:
                            active_device_ids.add(device_id)

            # Filter positions to active devices only
            filtered_current = []
            if current:
                filtered_current = [
                    pos for pos in current
                    if pos.get('device_id') in active_device_ids
                ]
                filtered_out_count = len(current) - len(filtered_current)
                if filtered_out_count > 0:
                    print(f"[PROVIDER_CONTROLLER] FR-6: Filtered {filtered_out_count} position(s) from inactive devices")

            # Filter breadcrumbs to active devices only
            filtered_breadcrumbs = []
            if breadcrumbs:
                filtered_breadcrumbs = [
                    bc for bc in breadcrumbs
                    if bc.get('device_id') in active_device_ids
                ]
                filtered_out_bc = len(breadcrumbs) - len(filtered_breadcrumbs)
                if filtered_out_bc > 0:
                    print(f"[PROVIDER_CONTROLLER] FR-6: Filtered {filtered_out_bc} breadcrumb(s) from inactive devices")

            # =================================================================
            # Phase 3 (SAR-4vs): Accumulate filtered breadcrumbs
            # Initialize accumulator on first refresh with breadcrumb data
            # CRITICAL FIX: Wrap in try/except to prevent refresh failure
            # =================================================================
            all_breadcrumbs = filtered_breadcrumbs  # Default: use filtered directly
            if filtered_breadcrumbs:
                try:
                    # Initialize accumulator if needed (lazy initialization)
                    if self._breadcrumb_accumulator is None:
                        self._init_breadcrumb_accumulator()

                    # Accumulate new breadcrumbs
                    new_count = self._breadcrumb_accumulator.add(filtered_breadcrumbs)
                    print(f'[PROVIDER_CONTROLLER] Added {new_count} new breadcrumb positions')

                    # Use accumulated positions for layer update
                    all_breadcrumbs = self._breadcrumb_accumulator.get_all()

                    # Log stats periodically
                    stats = self._breadcrumb_accumulator.stats()
                    print(f'[PROVIDER_CONTROLLER] Accumulator: {stats["total_positions"]} total, '
                          f'{stats["device_count"]} devices')
                except Exception as accum_err:
                    # CRITICAL FIX (SAR-4vs): Don't let accumulator errors fail entire refresh
                    # Fall back to using filtered_breadcrumbs directly - layers still get data
                    print(f'[PROVIDER_CONTROLLER] WARNING: Accumulator error ({accum_err}), '
                          f'using filtered breadcrumbs directly')
                    all_breadcrumbs = filtered_breadcrumbs
                    import traceback
                    traceback.print_exc()

            # Update layers if controller available
            # BUG-FIX: Only update layers when we have data to prevent clearing
            # existing positions during network glitches. This is LIFE-SAFETY CRITICAL
            # as losing team positions during a rescue could be dangerous.
            if self._layers_controller:
                try:
                    if filtered_current:
                        # Only update when we have active device data
                        self._layers_controller.update_current_positions(filtered_current)
                    elif current:
                        # Had positions but all were filtered (all inactive devices)
                        # SAFETY: Do NOT clear - preserves last known positions
                        print("[PROVIDER_CONTROLLER] All positions filtered (no active devices) - PRESERVING existing layer data")
                    else:
                        # SAFETY: Do NOT clear existing positions on empty response
                        # This preserves last known positions during network issues
                        print("[PROVIDER_CONTROLLER] Current positions empty - PRESERVING existing layer data (network glitch protection)")
                except Exception as layer_err:
                    print(f"[PROVIDER_CONTROLLER] ERROR update_current_positions: {layer_err}")
                    import traceback
                    traceback.print_exc()

                try:
                    if all_breadcrumbs:
                        processed_segments = None if used_incremental else breadcrumb_processing
                        # Phase 3: Send ALL accumulated breadcrumbs to layers
                        # (not just new ones - accumulator holds full session history)
                        self._layers_controller.update_breadcrumbs(
                            all_breadcrumbs,
                            processed_segments=processed_segments
                        )
                    elif breadcrumbs:
                        # Had breadcrumbs but all were filtered (all inactive devices)
                        # SAFETY: Do NOT clear - preserves last known data
                        print("[PROVIDER_CONTROLLER] All breadcrumbs filtered (no active devices) - PRESERVING existing layer data")
                    else:
                        # SAFETY: Do NOT clear existing breadcrumbs on empty response
                        print("[PROVIDER_CONTROLLER] Breadcrumb payload empty - PRESERVING existing layer data (network glitch protection)")
                except Exception as breadcrumb_err:
                    print(f"[PROVIDER_CONTROLLER] ERROR update_breadcrumbs: {breadcrumb_err}")
                    import traceback
                    traceback.print_exc()

            # NOTE: Device list updates now handled by DevicesController
            # which subscribes to the refresh_complete signal directly

            # Detect cached data for warning
            was_cached = False
            cache_age_seconds = None
            cache_positions = []  # Initialize outside if block for scope safety
            if current:
                cache_positions = [p for p in current if p.get('data_origin') == 'cache']
                if cache_positions:
                    was_cached = True
                    cache_age_seconds = max(p.get('cache_age_seconds', 0) for p in cache_positions)
            if was_cached:
                self._last_data_state = 'cached'
                self._last_cache_age_seconds = cache_age_seconds
            else:
                self._last_data_state = 'live'
                self._last_cache_age_seconds = None

            # Build result dict for signal
            result = {
                'current': current,
                'breadcrumbs': breadcrumbs,
                'devices': devices,
                'breadcrumb_processing': breadcrumb_processing,
                'breadcrumb_failures': breadcrumb_failures,
                'dropped': dropped,
                'was_cached': was_cached,
                'cache_age_seconds': cache_age_seconds,
                'outage_recovered': was_in_outage,
                'outage_duration_seconds': outage_duration,
            }

            # Emit refresh_complete signal for any additional handlers
            self.refresh_complete.emit(result)

            # Update status - show active/total devices for clarity
            active_count = len(active_device_ids)
            total_count = len(devices) if devices else 0
            if active_count < total_count:
                self._emit_status('ok', f'Last refresh: {active_count}/{total_count} active devices')
            else:
                self._emit_status('ok', f'Last refresh: {total_count} devices')

            # Show user feedback based on cache/outage state
            if was_cached and cache_age_seconds:
                age_minutes = cache_age_seconds / 60
                if age_minutes >= 60:
                    age_display = f"{age_minutes / 60:.1f} hours"
                else:
                    age_display = f"{age_minutes:.0f} minutes"

                device_cache_stale = any(p.get('device_cache_stale') for p in current)
                roster_warning = " Team roster may have changed!" if device_cache_stale else ""

                safe_error(
                    self.iface,
                    "OFFLINE MODE",
                    f"Showing CACHED positions ({age_display} old) - Network unavailable!{roster_warning}",
                    duration=10
                )
                print(f"[PROVIDER_CONTROLLER] SAR-fhd: Serving {len(cache_positions)} cached positions")

            elif was_in_outage and outage_duration is not None:
                # SAR-la0: Show connection restored notification
                outage_minutes = outage_duration / 60
                if outage_minutes >= 60:
                    outage_display = f"{outage_minutes / 60:.1f} hours"
                elif outage_minutes >= 1:
                    outage_display = f"{outage_minutes:.0f} minutes"
                else:
                    outage_display = f"{outage_duration:.0f} seconds"

                safe_success(
                    self.iface,
                    "CONNECTION RESTORED",
                    f"Network recovered after {outage_display} offline. Positions now live.",
                    duration=8
                )
                print(f"[PROVIDER_CONTROLLER] SAR-la0: Connection restored after {outage_display}")

            elif filtered_current or filtered_breadcrumbs:
                # Show active device count in user notification
                safe_success(
                    self.iface,
                    "SAR Tracker",
                    f"Refreshed: {len(filtered_current)} active devices, {len(filtered_breadcrumbs)} trail points",
                    duration=2
                )
            else:
                safe_info(
                    self.iface,
                    "SAR Tracker",
                    "Refresh completed but no tracking data was returned; preserving existing map data.",
                    duration=3
                )

            print(
                f"[PROVIDER_CONTROLLER] Refresh complete -> "
                f"current:{len(current)} breadcrumbs:{len(breadcrumbs)} devices:{len(devices)}"
            )

        except Exception as e:
            # Reset state on processing error
            self._refresh_in_progress = False
            self._clear_loading_state()

            print(f"[PROVIDER_CONTROLLER] Error in _on_refresh_task_complete: {e}")
            import traceback
            traceback.print_exc()

            safe_error(
                self.iface,
                "Refresh Error",
                f"Error processing refresh results: {str(e)}",
                duration=5
            )

    def _on_refresh_task_error(self, task):
        """
        Handle refresh task error or termination (runs in main thread).

        Args:
            task: Failed or terminated ProviderRefreshTask

        SAFETY: May be called after controller destruction (Pattern 9).
        """
        # BUG-030 FIX: Check shutdown flag FIRST
        if self._is_shutting_down:
            print("[PROVIDER_CONTROLLER] Refresh error during shutdown - ignoring")
            return

        # CRITICAL GUARD: Check if controller components still exist
        if not self.iface:
            print("[PROVIDER_CONTROLLER] Refresh error after controller destroyed")
            self._refresh_in_progress = False
            return

        try:
            # Reset refresh state
            self._refresh_in_progress = False
            self._current_refresh_task = None
            self._refresh_started_at = None
            self._last_refresh_duration_ms = None
            self._current_refresh_incremental = False

            # SAR-la0: Track consecutive failures for recovery notification
            self._consecutive_refresh_failures += 1
            if self._first_failure_time is None:
                self._first_failure_time = datetime.now()
                print(f"[PROVIDER_CONTROLLER] SAR-la0: Network outage started at {self._first_failure_time.isoformat()}")

            # Hide loading state
            self._clear_loading_state()

            # Get error message (defensive hasattr guard)
            error_msg = (
                task.error_message
                if hasattr(task, 'error_message') and task.error_message
                else "Unknown error during refresh"
            )

            # Emit error signal
            self.refresh_error.emit(error_msg)

            # Update status
            self._last_data_state = 'outage'
            self._last_cache_age_seconds = None
            self._emit_status('error', f'Refresh failed: {error_msg}')

            # Show user notification
            safe_error(
                self.iface,
                "Refresh Failed",
                f"Error refreshing data: {error_msg}",
                duration=5
            )

        except Exception as e:
            # DEFENSIVE: Catch ALL exceptions to prevent crashes in error handler
            print(f"[PROVIDER_CONTROLLER] Error in _on_refresh_task_error: {e}")
            import traceback
            traceback.print_exc()

            # Reset state
            self._refresh_in_progress = False
            self._clear_loading_state()

    def _clear_loading_state(self):
        """Clear loading state in panel if available."""
        if self._sar_panel:
            try:
                self._sar_panel.set_loading_state(False)
            except Exception:
                pass

    def cancel_refresh(self):
        """
        Cancel any in-progress refresh task.

        Qt5/Qt6 Compatible: Uses QgsTask.cancel().
        """
        if self._current_refresh_task:
            try:
                self._current_refresh_task.cancel()
                print("[PROVIDER_CONTROLLER] Refresh task cancelled")
            except Exception as e:
                print(f"[PROVIDER_CONTROLLER] Warning: Error cancelling refresh: {e}")
            finally:
                self._current_refresh_task = None
                self._refresh_in_progress = False

    @property
    def refresh_in_progress(self) -> bool:
        """Check if a refresh is currently in progress."""
        return self._refresh_in_progress

    # ========================================================================
    # Phase 8: Config Persistence
    # ========================================================================

    def save_config(self, provider_name: str, config: dict):
        """
        Save provider configuration to QSettings.

        Called when provider successfully connects. Persists config
        for auto-restore on next startup.

        Args:
            provider_name: Provider identifier (e.g., 'traccar_http')
            config: Provider configuration dict

        Qt5/Qt6 Compatible: Uses QSettings.
        """
        try:
            # Save last provider
            ConfigStore.set(SETTINGS_KEYS.PROVIDER_LAST, provider_name)

            # Save provider-specific config
            if provider_name == 'traccar_http':
                self._persist_traccar_http_settings(config)

            print(f"[PROVIDER_CONTROLLER] Saved provider config: {provider_name}")

        except Exception as e:
            print(f"[PROVIDER_CONTROLLER] Warning: Failed to save provider config: {e}")

    def load_config_and_auto_connect(self):
        """
        Load provider configuration from QSettings and auto-connect if enabled.

        This method handles auto-connection functionality on plugin startup.

        Qt5/Qt6 Compatible: Uses QSettings and ConfigStore.
        """
        try:
            # Check if auto-connect is enabled
            auto_connect = ConfigStore.get_provider_auto_connect()
            if not auto_connect:
                print("[PROVIDER_CONTROLLER] Auto-connect disabled, skipping provider restoration")
                return

            # Load last provider
            provider_name = ConfigStore.get(SETTINGS_KEYS.PROVIDER_LAST, None)
            if not provider_name:
                print("[PROVIDER_CONTROLLER] No saved provider config found")
                return

            print(f"[PROVIDER_CONTROLLER] Auto-connecting to saved provider: {provider_name}")

            # Load provider-specific config
            config = self._load_provider_specific_config(provider_name)

            if not config:
                print(f"[PROVIDER_CONTROLLER] Incomplete config for {provider_name}, skipping auto-connect")
                safe_warning(
                    self.iface,
                    "Provider Auto-Connect",
                    f"Auto-connect skipped: saved {provider_name} config is incomplete. "
                    "Open Settings to update credentials.",
                    duration=6
                )
                self._emit_status('error', f'Auto-connect skipped: {provider_name} config incomplete')
                return

            # Auto-connect to provider
            print(f"[PROVIDER_CONTROLLER] Initiating auto-connect to {provider_name}")
            self.set_provider(provider_name, config, test_only=False)

        except Exception as e:
            print(f"[PROVIDER_CONTROLLER] Warning: Failed to auto-connect provider: {e}")

    def _load_provider_specific_config(self, provider_name: str) -> Optional[Dict[str, Any]]:
        """
        Load provider-specific configuration from storage.

        Args:
            provider_name: Provider identifier

        Returns:
            Config dict or None if incomplete
        """
        config = {}

        if provider_name == 'http_traccar':
            # Legacy HTTP provider - migrate to traccar_http
            server_url = ConfigStore.get(SETTINGS_KEYS.PROVIDER_HTTP_SERVER_URL, None)
            username = ConfigStore.get(SETTINGS_KEYS.PROVIDER_HTTP_USERNAME, None)
            password = None
            if username:
                password = SecureStore.get_credential('http_traccar', str(username))
            if not password:
                password = ConfigStore.get(SETTINGS_KEYS.PROVIDER_HTTP_PASSWORD, None)
                if password and username:
                    SecureStore.set_credential('http_traccar', str(username), str(password))
                    ConfigStore.remove(SETTINGS_KEYS.PROVIDER_HTTP_PASSWORD)
            timeout = ConfigStore.get(
                SETTINGS_KEYS.PROVIDER_HTTP_TIMEOUT,
                SETTINGS_KEYS.PROVIDER_HTTP_TIMEOUT_DEFAULT,
                int
            )

            if server_url and username and password:
                legacy_config = {
                    'server_url': str(server_url),
                    'username': str(username),
                    'password': str(password),
                    'timeout': int(timeout)
                }
                converted = self._convert_legacy_http_config(legacy_config)
                if converted:
                    # Update stored provider name for future loads
                    ConfigStore.set(SETTINGS_KEYS.PROVIDER_LAST, 'traccar_http')
                    print("[PROVIDER_CONTROLLER] Migrated legacy HTTP provider settings to Traccar HTTP")
                    return converted

        elif provider_name == 'traccar_http':
            base_url = ConfigStore.get(SETTINGS_KEYS.PROVIDER_TRACCAR_BASE_URL, None)
            auth_type = ConfigStore.get(SETTINGS_KEYS.PROVIDER_TRACCAR_AUTH_TYPE, 'basic')
            timeout = ConfigStore.get(
                SETTINGS_KEYS.PROVIDER_TRACCAR_TIMEOUT,
                SETTINGS_KEYS.PROVIDER_TRACCAR_TIMEOUT_DEFAULT,
                int
            )
            cache_ttl = ConfigStore.get(
                SETTINGS_KEYS.PROVIDER_TRACCAR_CACHE_TTL,
                SETTINGS_KEYS.PROVIDER_TRACCAR_CACHE_TTL_DEFAULT,
                int
            )
            enable_cache = ConfigStore.get(
                SETTINGS_KEYS.PROVIDER_TRACCAR_CACHE_ENABLED,
                SETTINGS_KEYS.PROVIDER_TRACCAR_CACHE_ENABLED_DEFAULT,
                bool
            )

            if base_url and auth_type:
                config = {
                    'base_url': str(base_url),
                    'auth_type': str(auth_type),
                    'timeout_s': int(timeout),
                    'cache_ttl': int(cache_ttl),
                    'enable_last_good_cache': bool(enable_cache)
                }

                if auth_type == 'basic':
                    username = ConfigStore.get(SETTINGS_KEYS.PROVIDER_TRACCAR_USERNAME, None)
                    # Try SecureStore first
                    password = None
                    if username:
                        password = SecureStore.get_credential('traccar_http_basic', str(username))
                    if not password:
                        # Fallback to QSettings
                        password = ConfigStore.get(SETTINGS_KEYS.PROVIDER_TRACCAR_PASSWORD, None)
                        if password and username:
                            SecureStore.set_credential('traccar_http_basic', str(username), str(password))
                            ConfigStore.remove(SETTINGS_KEYS.PROVIDER_TRACCAR_PASSWORD)

                    if username and password:
                        config['username'] = str(username)
                        config['password'] = str(password)
                    else:
                        config = {}  # Incomplete

                elif auth_type == 'bearer':
                    # Try SecureStore first
                    token = SecureStore.get_credential('traccar_http_bearer', 'token')
                    if not token:
                        token = ConfigStore.get(SETTINGS_KEYS.PROVIDER_TRACCAR_TOKEN, None)
                        if token:
                            SecureStore.set_credential('traccar_http_bearer', 'token', str(token))
                            ConfigStore.remove(SETTINGS_KEYS.PROVIDER_TRACCAR_TOKEN)

                    if token:
                        config['token'] = str(token)
                    else:
                        config = {}  # Incomplete

        return config if config else None

    def _convert_legacy_http_config(self, legacy_config: dict) -> Optional[dict]:
        """
        Convert legacy http_traccar config to traccar_http config dict.

        Args:
            legacy_config: Old-style config with server_url, username, password

        Returns:
            Converted config dict or None if invalid
        """
        base_url = str(legacy_config.get('server_url', '')).strip()
        username = str(legacy_config.get('username', '')).strip()
        password = str(legacy_config.get('password', '')).strip()

        if not base_url or not username or not password:
            return None

        timeout = int(legacy_config.get('timeout', SETTINGS_KEYS.PROVIDER_TRACCAR_TIMEOUT_DEFAULT))

        converted = {
            'base_url': base_url,
            'auth_type': 'basic',
            'username': username,
            'password': password,
            'timeout_s': timeout,
            'cache_ttl': SETTINGS_KEYS.PROVIDER_TRACCAR_CACHE_TTL_DEFAULT,
            'enable_last_good_cache': SETTINGS_KEYS.PROVIDER_TRACCAR_CACHE_ENABLED_DEFAULT
        }

        # Persist immediately so next load finds it
        self._persist_traccar_http_settings(converted)
        return converted

    def _persist_traccar_http_settings(self, config: dict):
        """
        Persist Traccar HTTP provider settings to QSettings and SecureStore.

        Args:
            config: Traccar HTTP config dict
        """
        ConfigStore.set(SETTINGS_KEYS.PROVIDER_TRACCAR_BASE_URL, config.get('base_url', ''))
        ConfigStore.set(SETTINGS_KEYS.PROVIDER_TRACCAR_AUTH_TYPE, config.get('auth_type', 'basic'))
        ConfigStore.set(
            SETTINGS_KEYS.PROVIDER_TRACCAR_TIMEOUT,
            config.get('timeout_s', SETTINGS_KEYS.PROVIDER_TRACCAR_TIMEOUT_DEFAULT)
        )
        ConfigStore.set(
            SETTINGS_KEYS.PROVIDER_TRACCAR_CACHE_TTL,
            config.get('cache_ttl', SETTINGS_KEYS.PROVIDER_TRACCAR_CACHE_TTL_DEFAULT)
        )
        ConfigStore.set(
            SETTINGS_KEYS.PROVIDER_TRACCAR_CACHE_ENABLED,
            config.get('enable_last_good_cache', SETTINGS_KEYS.PROVIDER_TRACCAR_CACHE_ENABLED_DEFAULT)
        )

        if config.get('auth_type') == 'basic':
            username = config.get('username', '')
            password = config.get('password', '')
            ConfigStore.set(SETTINGS_KEYS.PROVIDER_TRACCAR_USERNAME, username)
            # Save password to SecureStore
            SecureStore.set_credential('traccar_http_basic', username, password)
        else:
            token = config.get('token', '')
            # Save token to SecureStore
            SecureStore.set_credential('traccar_http_bearer', 'token', token)

        # Remove any plaintext credentials that may exist in QSettings
        ConfigStore.remove(SETTINGS_KEYS.PROVIDER_TRACCAR_PASSWORD)
        ConfigStore.remove(SETTINGS_KEYS.PROVIDER_TRACCAR_TOKEN)
        ConfigStore.remove(SETTINGS_KEYS.PROVIDER_HTTP_PASSWORD)

    # ========================================================================
    # Phase 1.2: Signal Handler Wrappers for Settings Panel
    # ========================================================================
    # These methods match the SettingsPanel signal signatures and wrap
    # set_provider() with the appropriate test_only parameter.

    def handle_test_request(self, provider_name: str, config: dict):
        """
        Handle provider test request from SettingsPanel.

        Wraps set_provider() with test_only=True for the "Test Connection" button.

        Signal signature: provider_test_requested(str, dict)

        Args:
            provider_name: Provider identifier (e.g., 'traccar_http')
            config: Provider configuration dict

        Qt5/Qt6 Compatible: Pure Python slot.
        """
        self.set_provider(provider_name, config, test_only=True)

    def handle_save_request(self, provider_name: str, config: dict):
        """
        Handle provider save/connect request from SettingsPanel.

        Wraps set_provider() with test_only=False for the "Connect" button.
        On successful connection, provider config is persisted for auto-restore.

        Signal signature: provider_save_requested(str, dict)

        Args:
            provider_name: Provider identifier (e.g., 'traccar_http')
            config: Provider configuration dict

        Qt5/Qt6 Compatible: Pure Python slot.
        """
        self.set_provider(provider_name, config, test_only=False)
