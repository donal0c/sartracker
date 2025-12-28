# -*- coding: utf-8 -*-
"""
Task Manager

Centralized management of background QgsTask objects with proper lifecycle handling.
Ensures tasks are cancelled and disconnected during plugin teardown.

This module addresses Issue #6: Background tasks outliving torn-down components.
It provides a single point of control for all async task operations, ensuring
proper signal disconnection and cleanup.

Qt5/Qt6 Compatible: Uses QGIS QgsTask API.
"""

from functools import partial
from typing import Optional, Callable, Dict, Set, Any
from qgis.core import QgsTask, QgsApplication
from qgis.PyQt.QtCore import QObject, QEventLoop, QTimer
import logging
import time
import traceback

logger = logging.getLogger(__name__)


class TaskManager(QObject):
    """
    Manages background task lifecycle with automatic cleanup.

    Features:
    - Automatic signal disconnection on cancellation
    - Prevents dangling task references
    - Centralized task tracking
    - Safe shutdown handling

    LIFE-SAFETY CRITICAL: This class prevents race conditions where task
    completion handlers fire after plugin teardown, which could cause
    crashes during active rescue operations.

    Usage:
        manager = TaskManager()
        manager.start_task(
            task=my_task,
            on_complete=self._handle_complete,
            on_error=self._handle_error
        )
        # Later, during cleanup:
        manager.cancel_all()
    """

    def __init__(self):
        """Initialize task manager."""
        super().__init__()
        self._active_tasks: Dict[str, QgsTask] = {}
        self._task_connections: Dict[str, Dict[str, Callable]] = {}
        self._cancelled_tasks: Set[str] = set()
        # BUG-015 FIX: Track error states for comprehensive error handling
        self._task_errors: Dict[str, Dict[str, Any]] = {}
        self._shutting_down: bool = False

    def start_task(
        self,
        task: QgsTask,
        on_complete: Optional[Callable[[QgsTask], None]] = None,
        on_error: Optional[Callable[[QgsTask], None]] = None,
        task_id: Optional[str] = None
    ) -> str:
        """
        Start a background task with managed lifecycle.

        Args:
            task: QgsTask instance to run
            on_complete: Callback for successful completion (receives task)
            on_error: Callback for error/termination (receives task)
            task_id: Optional identifier (auto-generated if not provided)

        Returns:
            Task ID for cancellation/tracking

        Note:
            Callbacks are wrapped with automatic cleanup. Even if the callback
            crashes, the task will be removed from the active tasks dictionary
            and signals will be disconnected.
        """
        # Do not start new tasks during shutdown.
        if self._shutting_down:
            if not task_id:
                task_id = f"task_{id(task)}"
            logger.warning("Refusing to start task %s during shutdown", task_id)
            return task_id

        # Generate task ID if not provided
        if not task_id:
            task_id = f"task_{id(task)}"

        # Store task reference
        self._active_tasks[task_id] = task

        # Connect signals with automatic cleanup
        complete_slot = partial(self._handle_complete, task_id, task, on_complete)
        error_slot = partial(self._handle_error, task_id, task, on_error)
        task.taskCompleted.connect(complete_slot)
        task.taskTerminated.connect(error_slot)

        self._task_connections[task_id] = {
            "complete": complete_slot,
            "error": error_slot
        }

        # Start task via QGIS task manager
        QgsApplication.taskManager().addTask(task)

        return task_id

    def begin_shutdown(self):
        """Prevent new tasks from being queued during shutdown."""
        self._shutting_down = True

    def _handle_complete(self, task_id: str, task: QgsTask, callback: Optional[Callable]):
        """
        Internal completion handler with cleanup.

        BUG-015 FIX: Enhanced error handling to prevent silent failures.

        Args:
            task_id: Task identifier
            task: QgsTask that completed
            callback: User callback to invoke

        Note:
            Cleanup happens in finally block to ensure it runs even if
            callback raises an exception.
        """
        try:
            # BUG-015 FIX: Check if we're shutting down or task was cancelled
            if self._shutting_down:
                logger.debug("Task %s completed but manager is shutting down - skipping callback", task_id)
                return
            if task_id in self._cancelled_tasks:
                logger.debug("Task %s completed but was already cancelled - skipping callback", task_id)
                return

            if callback:
                try:
                    # BUG-057 FIX: Track callback execution time for diagnostics
                    callback_start = time.monotonic()
                    callback(task)
                    callback_duration = time.monotonic() - callback_start

                    # BUG-057 FIX: Warn about slow callbacks that may block UI
                    if callback_duration > 0.5:  # 500ms threshold
                        logger.warning(
                            "BUG-057: Task %s completion callback took %.2fs (slow callback may block UI)",
                            task_id,
                            callback_duration
                        )
                except Exception as callback_exc:
                    # BUG-015 FIX: Log callback exceptions instead of letting them escape
                    logger.error(
                        "Task %s completion callback raised exception: %s\n%s",
                        task_id,
                        callback_exc,
                        traceback.format_exc()
                    )
                    # Store error for potential retrieval
                    self._task_errors[task_id] = {
                        "type": "callback_error",
                        "exception": callback_exc,
                        "traceback": traceback.format_exc(),
                        "phase": "complete"
                    }
        except Exception as handler_exc:
            # BUG-015 FIX: Catch any unexpected errors in the handler itself
            logger.error(
                "Task %s completion handler failed unexpectedly: %s",
                task_id,
                handler_exc
            )
        finally:
            self._cleanup_task(task_id, task)

    def _handle_error(self, task_id: str, task: QgsTask, callback: Optional[Callable]):
        """
        Internal error handler with cleanup.

        BUG-015 FIX: Enhanced error handling with comprehensive state tracking.

        Args:
            task_id: Task identifier
            task: QgsTask that failed
            callback: User callback to invoke

        Note:
            Cleanup happens in finally block to ensure it runs even if
            callback raises an exception.
        """
        try:
            # BUG-015 FIX: Check if we're shutting down or task was cancelled
            if self._shutting_down:
                logger.debug("Task %s errored but manager is shutting down - skipping callback", task_id)
                return
            if task_id in self._cancelled_tasks:
                logger.debug("Task %s errored but was already cancelled - skipping callback", task_id)
                return

            # BUG-015 FIX: Log the task error for diagnostics
            logger.warning("Task %s terminated/errored", task_id)

            if callback:
                try:
                    # BUG-057 FIX: Track callback execution time for diagnostics
                    callback_start = time.monotonic()
                    callback(task)
                    callback_duration = time.monotonic() - callback_start

                    # BUG-057 FIX: Warn about slow callbacks that may block UI
                    if callback_duration > 0.5:  # 500ms threshold
                        logger.warning(
                            "BUG-057: Task %s error callback took %.2fs (slow callback may block UI)",
                            task_id,
                            callback_duration
                        )
                except Exception as callback_exc:
                    # BUG-015 FIX: Log callback exceptions instead of letting them escape
                    logger.error(
                        "Task %s error callback raised exception: %s\n%s",
                        task_id,
                        callback_exc,
                        traceback.format_exc()
                    )
                    # Store error for potential retrieval
                    self._task_errors[task_id] = {
                        "type": "callback_error",
                        "exception": callback_exc,
                        "traceback": traceback.format_exc(),
                        "phase": "error"
                    }
        except Exception as handler_exc:
            # BUG-015 FIX: Catch any unexpected errors in the handler itself
            logger.error(
                "Task %s error handler failed unexpectedly: %s",
                task_id,
                handler_exc
            )
        finally:
            self._cleanup_task(task_id, task)

    def _cleanup_task(self, task_id: str, task: QgsTask):
        """
        Clean up task after completion.

        Args:
            task_id: Task identifier
            task: QgsTask to clean up

        Note:
            Disconnects all signals to prevent future accidental firing,
            which could occur if the task object is still referenced elsewhere.
        """
        self._disconnect_task_signals(task_id, task)

        # Remove bookkeeping for this task
        self._active_tasks.pop(task_id, None)
        self._cancelled_tasks.discard(task_id)

    def cancel_task(self, task_id: str) -> bool:
        """
        Cancel a specific task.

        Args:
            task_id: Task identifier returned from start_task()

        Returns:
            True if task was found and cancelled, False otherwise

        Note:
            Signals are disconnected BEFORE cancellation to prevent
            handlers from firing during/after the cancel operation.
        """
        task = self._active_tasks.get(task_id)
        if not task:
            return False

        # Disconnect signals first (Issue #6: prevents handlers during cancel)
        self._disconnect_task_signals(task_id, task)

        try:
            task.cancel()
            self._cancelled_tasks.add(task_id)
        except (RuntimeError, TypeError):
            pass

        # Remove from tracking
        self._active_tasks.pop(task_id, None)
        return True

    def cancel_all(self, wait_timeout_ms: int = 5000):
        """
        Cancel all active tasks (call during shutdown).

        BUG-015 FIX: Sets shutdown flag to prevent callbacks during teardown.
        CRASH FIX: Now waits synchronously for tasks to finish to prevent
        race conditions during plugin unload.

        Args:
            wait_timeout_ms: Maximum time to wait for tasks to finish (milliseconds)

        Note:
            This is the primary method called during plugin unload().
            It ensures NO task handlers will fire after unload completes.

            LIFE-SAFETY CRITICAL: This method now includes a synchronous wait
            to ensure all background threads have fully stopped before returning.
            This prevents segmentation faults when QGIS tries to clean up the
            task manager while threads are still accessing Qt objects.
        """
        # BUG-015 FIX: Set shutdown flag to prevent callbacks from firing
        self._shutting_down = True

        # Get list of task IDs (avoid modifying dict during iteration)
        task_ids = list(self._active_tasks.keys())

        if not task_ids:
            logger.debug("No active tasks to cancel")
            self._task_errors.clear()
            return

        logger.info("Cancelling %d active task(s) and waiting for completion...", len(task_ids))

        for task_id in task_ids:
            self.cancel_task(task_id)

        # CRASH FIX: Wait synchronously for QGIS task manager to finish all tasks
        # This prevents the race condition where threads are still running when
        # the plugin is destroyed
        self._wait_for_tasks_to_finish(wait_timeout_ms)

        # BUG-015 FIX: Clear error tracking on shutdown
        self._task_errors.clear()

        logger.info("All tasks cancelled and cleanup complete")

    def _wait_for_tasks_to_finish(self, timeout_ms: int):
        """
        Wait for QGIS task manager to finish processing all tasks.

        CRASH FIX: This method provides a synchronization barrier to ensure
        background threads have fully stopped before plugin unload continues.

        Args:
            timeout_ms: Maximum time to wait in milliseconds

        Note:
            Uses an event loop to process Qt events while waiting, allowing
            tasks to complete their cleanup. If timeout is reached, logs a
            warning but continues (to prevent hanging indefinitely).
        """
        task_manager = QgsApplication.taskManager()
        start_time = time.monotonic()
        timeout_seconds = timeout_ms / 1000.0

        # Poll until all tasks are done or timeout
        while True:
            # Check if QGIS task manager has any active tasks
            active_count = task_manager.countActiveTasks()

            if active_count == 0:
                elapsed = time.monotonic() - start_time
                logger.debug("All tasks finished in %.2f seconds", elapsed)
                return

            # Check timeout
            elapsed = time.monotonic() - start_time
            if elapsed >= timeout_seconds:
                logger.warning(
                    "Timeout waiting for tasks to finish after %.2f seconds. "
                    "%d task(s) still active. Continuing anyway to prevent hang.",
                    elapsed, active_count
                )
                return

            # Process events to allow tasks to complete
            # Use a short wait to avoid busy-waiting
            QEventLoop().processEvents()
            time.sleep(0.05)  # 50ms between checks

    def get_active_count(self) -> int:
        """
        Get number of active tasks.

        Returns:
            Number of tasks currently tracked by this manager
        """
        return len(self._active_tasks)

    def get_active_task_ids(self) -> list:
        """
        Get list of active task IDs.

        Returns:
            List of task identifiers for all active tasks
        """
        return list(self._active_tasks.keys())

    def _disconnect_task_signals(self, task_id: str, task: QgsTask):
        """
        Disconnect stored signal handlers for a task without affecting other listeners.
        """
        handlers = self._task_connections.pop(task_id, {})
        complete_handler = handlers.get("complete")
        error_handler = handlers.get("error")

        if complete_handler:
            try:
                task.taskCompleted.disconnect(complete_handler)
            except (RuntimeError, TypeError):
                pass

        if error_handler:
            try:
                task.taskTerminated.disconnect(error_handler)
            except (RuntimeError, TypeError):
                pass

    # ------------------------------------------------------------------
    # BUG-015 FIX: Error state retrieval methods
    # ------------------------------------------------------------------

    def get_task_error(self, task_id: str) -> Optional[Dict[str, Any]]:
        """
        Get error information for a task if any occurred.

        BUG-015 FIX: Allows callers to check for errors that occurred
        during callback execution.

        Args:
            task_id: Task identifier

        Returns:
            Dict with error details or None if no error recorded
        """
        return self._task_errors.get(task_id)

    def clear_task_error(self, task_id: str):
        """
        Clear error information for a task.

        BUG-015 FIX: Call after handling or acknowledging an error.

        Args:
            task_id: Task identifier
        """
        self._task_errors.pop(task_id, None)

    def has_errors(self) -> bool:
        """
        Check if any tasks have recorded errors.

        BUG-015 FIX: Quick check for error conditions.

        Returns:
            True if any task errors are recorded
        """
        return len(self._task_errors) > 0

    def is_shutting_down(self) -> bool:
        """
        Check if manager is in shutdown state.

        BUG-015 FIX: Allows callbacks to check shutdown state.

        Returns:
            True if cancel_all() has been called
        """
        return self._shutting_down
