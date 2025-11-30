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
from typing import Optional, Callable, Dict
from qgis.core import QgsTask, QgsApplication
from qgis.PyQt.QtCore import QObject


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

    def _handle_complete(self, task_id: str, task: QgsTask, callback: Optional[Callable]):
        """
        Internal completion handler with cleanup.

        Args:
            task_id: Task identifier
            task: QgsTask that completed
            callback: User callback to invoke

        Note:
            Cleanup happens in finally block to ensure it runs even if
            callback raises an exception.
        """
        try:
            # Call user callback
            if callback:
                callback(task)
        finally:
            # Always clean up, even if callback crashes
            self._cleanup_task(task_id, task)

    def _handle_error(self, task_id: str, task: QgsTask, callback: Optional[Callable]):
        """
        Internal error handler with cleanup.

        Args:
            task_id: Task identifier
            task: QgsTask that failed
            callback: User callback to invoke

        Note:
            Cleanup happens in finally block to ensure it runs even if
            callback raises an exception.
        """
        try:
            # Call user callback
            if callback:
                callback(task)
        finally:
            # Always clean up, even if callback crashes
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

        # Remove from active tasks
        self._active_tasks.pop(task_id, None)

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
            # Cancel task
            task.cancel()
        except (RuntimeError, TypeError):
            # Task might have completed or been destroyed
            pass

        # Remove from tracking
        self._active_tasks.pop(task_id, None)
        return True

    def cancel_all(self):
        """
        Cancel all active tasks (call during shutdown).

        Note:
            This is the primary method called during plugin unload().
            It ensures NO task handlers will fire after unload completes.
        """
        # Get list of task IDs (avoid modifying dict during iteration)
        task_ids = list(self._active_tasks.keys())

        for task_id in task_ids:
            self.cancel_task(task_id)

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
