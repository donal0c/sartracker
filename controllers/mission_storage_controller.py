# -*- coding: utf-8 -*-
"""
Mission Storage Controller for SAR Tracker.

Manages mission storage lifecycle: archiving, backup sync, and finalization state.
This controller centralizes mission filesystem operations that were previously
scattered across sartracker.py.

Phase 6 - Mission Storage Extraction:
- Fixes missing _start_archive_task() bug (called but never defined)
- Uses MissionStorageHelper.create_archive() for consistent SQLite snapshots
- Runs archive operations in background via TaskManager

Qt5/Qt6 Compatible: Uses qgis.PyQt and qt_compat for all Qt imports.

LIFE-SAFETY CRITICAL: Archive and backup operations preserve mission data
that may be needed for incident review or legal purposes.
"""

from pathlib import Path
from typing import Optional, TYPE_CHECKING

from qgis.PyQt.QtCore import QObject, pyqtSignal
from qgis.core import QgsTask

from ..utils.mission_storage import (
    MissionPaths,
    MissionStorageHelper,
    check_uncommitted_edits,
    format_uncommitted_edits,
    validate_archive,
)
from ..utils.task_manager import TaskManager

if TYPE_CHECKING:
    from qgis.gui import QgisInterface
    from ..layer_manager import LayerManager


class MissionStorageController(QObject):
    """
    Controller for mission storage operations: archive, backup, finalization.

    Responsibilities:
    - Create mission archives in background (fixes missing _start_archive_task bug)
    - Manage backup sync operations
    - Track and update finalization state
    - Emit status updates for UI feedback

    Signals:
        archive_started: Emitted when archive task begins
        archive_completed: Emitted on successful archive
            Args: str (path to created archive)
        archive_failed: Emitted on archive failure
            Args: str (error message)
        backup_completed: Emitted on successful backup sync
        backup_failed: Emitted on backup failure
            Args: str (error message)

    LIFE-SAFETY CRITICAL: All async handlers use defensive guards (Pattern 9).
    Archive operations use SQLite-safe snapshots to prevent data corruption.
    """

    archive_started = pyqtSignal()
    archive_completed = pyqtSignal(str)  # archive_path
    archive_failed = pyqtSignal(str)     # error_message
    backup_completed = pyqtSignal()
    backup_failed = pyqtSignal(str)      # error_message

    def __init__(
        self,
        iface: "QgisInterface",
        task_manager: TaskManager,
        mission_storage: MissionStorageHelper,
        layer_manager: "LayerManager",
        parent: Optional[QObject] = None
    ):
        """
        Initialize mission storage controller.

        Args:
            iface: QGIS interface (for messageBar notifications)
            task_manager: TaskManager instance for background operations
            mission_storage: MissionStorageHelper for filesystem operations
            layer_manager: LayerManager for finalization state persistence
            parent: Optional QObject parent (for Qt lifecycle)
        """
        super().__init__(parent)

        self.iface = iface
        self.task_manager = task_manager
        self.mission_storage = mission_storage
        self.layer_manager = layer_manager

        # Shutdown flag for thread-safe callback guards (Pattern 9)
        self._is_shutting_down = False

        # Track active archive operation to prevent duplicates
        self._archive_in_progress = False

    # ------------------------------------------------------------------
    # Archive Operations (BUG FIX: implements missing _start_archive_task)
    # ------------------------------------------------------------------

    def start_archive_task(
        self,
        paths: MissionPaths,
        project_path: Optional[Path],
        mark_finalized: bool = True,
        *,
        uncommitted_layers: Optional[list] = None
    ) -> bool:
        """
        Start background task to create mission archive.

        This method fixes the missing _start_archive_task() bug in sartracker.py.
        Uses MissionStorageHelper.create_archive() which creates SQLite-safe
        snapshots to prevent data corruption during active tracking.

        Args:
            paths: MissionPaths with current mission directories
            project_path: Optional path to QGIS project file to include
            mark_finalized: Whether to mark mission as finalized on success
            uncommitted_layers: Precomputed uncommitted edit list (optional)

        Returns:
            True if task was started, False if archive already in progress
        """
        if self._is_shutting_down:
            print("[MissionStorageController] Archive requested during shutdown, ignoring")
            return False

        if self._archive_in_progress:
            print("[MissionStorageController] Archive already in progress, ignoring duplicate request")
            return False

        if not paths or not paths.gpkg_path:
            print("[MissionStorageController] Cannot archive: mission paths not set")
            self.archive_failed.emit("Mission paths not configured")
            return False

        if uncommitted_layers is None:
            uncommitted_layers = self._warn_uncommitted_edits("archive")

        self._archive_in_progress = True
        self.archive_started.emit()

        # Create the background task
        task = ArchiveTask(
            paths=paths,
            project_path=project_path,
            storage=self.mission_storage,
            mark_finalized=mark_finalized,
            uncommitted_layers=uncommitted_layers
        )

        # Start via TaskManager with callbacks
        self.task_manager.start_task(
            task=task,
            on_complete=lambda t: self._on_archive_complete(t),
            on_error=lambda t: self._on_archive_error(t),
            task_id="mission_archive"
        )

        return True

    def _on_archive_complete(self, task: "ArchiveTask"):
        """Handle successful archive completion on main thread."""
        self._archive_in_progress = False

        # Defensive guard: check shutdown state (Pattern 9)
        if self._is_shutting_down:
            print("[MissionStorageController] Archive completed but controller shutting down")
            return

        archive_path = getattr(task, "archive_path", None)
        mark_finalized = getattr(task, "mark_finalized", True)
        task_paths = getattr(task, "paths", None)

        if archive_path and task_paths:
            validation_error = validate_archive(Path(archive_path), task_paths)
            if validation_error:
                error_msg = f"Archive validation failed: {validation_error}"
                print(f"[MissionStorageController] Archive error: {error_msg}")
                self.archive_failed.emit(error_msg)
                return
        elif archive_path and not task_paths:
            error_msg = "Archive completed but mission paths were unavailable for validation"
            print(f"[MissionStorageController] Archive error: {error_msg}")
            self.archive_failed.emit(error_msg)
            return

        if archive_path:
            print(f"[MissionStorageController] Archive created: {archive_path}")

            # Mark mission as finalized if requested
            if mark_finalized and self.layer_manager:
                try:
                    self.layer_manager.set_mission_finalized(True)
                    if not self.layer_manager.is_mission_finalized():
                        raise RuntimeError("Finalization flag did not persist")
                    print("[MissionStorageController] Mission marked as finalized")
                except Exception as exc:
                    error_msg = f"Failed to mark mission as finalized: {exc}"
                    print(f"[MissionStorageController] {error_msg}")
                    self.archive_failed.emit(error_msg)
                    return

            self.archive_completed.emit(str(archive_path))
        else:
            # Task completed but no archive path - treat as error
            error_msg = getattr(task, "error_message", "Archive completed but no file created")
            print(f"[MissionStorageController] Archive error: {error_msg}")
            self.archive_failed.emit(error_msg)

    def _on_archive_error(self, task: "ArchiveTask"):
        """Handle archive task failure on main thread."""
        self._archive_in_progress = False

        # Defensive guard: check shutdown state (Pattern 9)
        if self._is_shutting_down:
            return

        error_msg = getattr(task, "error_message", "Archive task failed")
        print(f"[MissionStorageController] Archive failed: {error_msg}")
        self.archive_failed.emit(error_msg)

    # ------------------------------------------------------------------
    # Backup Operations
    # ------------------------------------------------------------------

    def start_backup_task(
        self,
        paths: MissionPaths,
        *,
        uncommitted_layers: Optional[list] = None
    ) -> bool:
        """
        Start background task to sync mission backup.

        Args:
            paths: MissionPaths with current mission directories
            uncommitted_layers: Precomputed uncommitted edit list (optional)

        Returns:
            True if task was started
        """
        if self._is_shutting_down:
            return False

        if not paths:
            return False
        if uncommitted_layers is None:
            uncommitted_layers = self._warn_uncommitted_edits("backup")
        task = BackupTask(
            paths=paths,
            storage=self.mission_storage,
            uncommitted_layers=uncommitted_layers
        )

        self.task_manager.start_task(
            task=task,
            on_complete=lambda t: self._on_backup_complete(t),
            on_error=lambda t: self._on_backup_error(t),
            task_id="mission_backup"
        )

        return True

    def _warn_uncommitted_edits(self, operation: str) -> list:
        """
        Check for uncommitted edits and warn on the main thread.

        Args:
            operation: Operation name ("backup" or "archive")

        Returns:
            List of uncommitted layer names (may be empty)
        """
        if self._is_shutting_down:
            return []
        uncommitted = check_uncommitted_edits()
        msg = format_uncommitted_edits(uncommitted, operation)
        if msg:
            try:
                from ..utils.notify import warning as notify_warning
                notify_warning(self.iface.messageBar(), "Uncommitted Edits", msg, duration=8)
            except Exception:
                print(f"[MissionStorageController] Warning: {msg}")
        return uncommitted

    def _on_backup_complete(self, task: "BackupTask"):
        """Handle successful backup completion."""
        if self._is_shutting_down:
            return

        error_msg = getattr(task, "error_message", None)
        if error_msg:
            self.backup_failed.emit(error_msg)
        else:
            self.backup_completed.emit()

    def _on_backup_error(self, task: "BackupTask"):
        """Handle backup task failure."""
        if self._is_shutting_down:
            return

        error_msg = getattr(task, "error_message", "Backup task failed")
        self.backup_failed.emit(error_msg)

    # ------------------------------------------------------------------
    # Finalization State
    # ------------------------------------------------------------------

    def is_finalized(self) -> bool:
        """Check if current mission is finalized."""
        if self.layer_manager:
            return self.layer_manager.is_mission_finalized()
        return False

    def set_finalized(self, finalized: bool, finalized_by: Optional[str] = None) -> bool:
        """
        Set mission finalization state.

        Args:
            finalized: True to mark as finalized, False to unlock
            finalized_by: Optional name of person who finalized/unlocked

        Returns:
            True if state was updated successfully
        """
        if not self.layer_manager:
            return False

        try:
            self.layer_manager.set_mission_finalized(finalized, finalized_by=finalized_by)
            return True
        except Exception as exc:
            print(f"[MissionStorageController] Failed to set finalized state: {exc}")
            return False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def cleanup(self):
        """
        Clean up controller resources.

        Called during plugin unload. Sets shutdown flag to prevent
        callbacks from accessing destroyed objects.
        """
        self._is_shutting_down = True
        self._archive_in_progress = False

    def status_snapshot(self) -> dict:
        """
        Return current status for diagnostics.

        Returns:
            Dict with archive_in_progress, is_finalized keys
        """
        return {
            "archive_in_progress": self._archive_in_progress,
            "is_finalized": self.is_finalized(),
            "is_shutting_down": self._is_shutting_down,
        }


# =============================================================================
# Background Tasks
# =============================================================================

class ArchiveTask(QgsTask):
    """
    Background task for creating mission archive.

    Uses MissionStorageHelper.create_archive() which creates SQLite-safe
    snapshots via VACUUM INTO or connection.backup() API.

    DATA INTEGRITY: Archive is created from consistent database snapshot,
    not from live file that may be mid-write.
    """

    def __init__(
        self,
        paths: MissionPaths,
        project_path: Optional[Path],
        storage: MissionStorageHelper,
        mark_finalized: bool = True,
        uncommitted_layers: Optional[list] = None
    ):
        super().__init__("Creating mission archive", QgsTask.CanCancel)
        self.paths = paths
        self.project_path = project_path
        self.storage = storage
        self.mark_finalized = mark_finalized
        self.uncommitted_layers = uncommitted_layers or []

        # Results (set during run())
        self.archive_path: Optional[Path] = None
        self.error_message: Optional[str] = None

    def run(self) -> bool:
        """
        Execute archive creation in background thread.

        Returns:
            True if archive was created successfully
        """
        try:
            if self.isCanceled():
                return False

            self.archive_path = self.storage.create_archive(
                mission_paths=self.paths,
                project_path=self.project_path,
                uncommitted_layers=self.uncommitted_layers,
                warn_uncommitted=False
            )

            return self.archive_path is not None

        except Exception as exc:
            self.error_message = str(exc)
            import traceback
            traceback.print_exc()
            return False


class BackupTask(QgsTask):
    """
    Background task for syncing mission backup.

    Uses MissionStorageHelper.sync_backup() which creates SQLite-safe
    snapshots of the GeoPackage.
    """

    def __init__(
        self,
        paths: MissionPaths,
        storage: MissionStorageHelper,
        uncommitted_layers: Optional[list] = None
    ):
        super().__init__("Sync mission backup", QgsTask.CanCancel)
        self.paths = paths
        self.storage = storage
        self.uncommitted_layers = uncommitted_layers or []
        self.error_message: Optional[str] = None

    def run(self) -> bool:
        """Execute backup sync in background thread."""
        try:
            if self.isCanceled():
                return False

            return bool(
                self.storage.sync_backup(
                    self.paths,
                    uncommitted_layers=self.uncommitted_layers,
                    warn_uncommitted=False,
                    warn_on_error=False
                )
            )

        except Exception as exc:
            self.error_message = str(exc)
            return False
