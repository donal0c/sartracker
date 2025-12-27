# -*- coding: utf-8 -*-
"""
Mission Lifecycle Controller for SAR Tracker.

Centralizes mission lifecycle management: storage setup, state transitions,
project hooks, backup/autosave, and finalization workflows.

Phase 2 - Mission Lifecycle/Storage Extraction:
This controller consolidates mission state that was previously scattered
across sartracker.py instance variables. It provides a clean interface
for managing mission sessions from start to finish.

Qt5/Qt6 Compatible: Uses qgis.PyQt and qt_compat for all Qt imports.

LIFE-SAFETY CRITICAL: Mission lifecycle operations affect data integrity
and must handle all error cases gracefully. Backups and archives use
SQLite-safe snapshots to prevent data corruption during active tracking.
"""

import re
import threading
import weakref
from datetime import datetime
from pathlib import Path
from typing import Optional, Callable, List, TYPE_CHECKING

from qgis.PyQt.QtCore import QObject, pyqtSignal
from qgis.PyQt.QtWidgets import QMessageBox, QInputDialog

from qgis.core import QgsProject

from ..utils.mission_storage import MissionPaths, MissionSessionState, MissionStorageHelper
from ..utils.notify import info, warning, error, success
from ..utils.qt_compat import dialog_exec, DialogAccepted, ISODate
from ..config.keys import ConfigStore

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
    from ..layers import LayerManager
    from ..controllers.mission_controller import MissionController
    from ..controllers.mission_storage_controller import MissionStorageController
    from ..utils.task_manager import TaskManager


class MissionLifecycleController(QObject):
    """
    Controller for mission lifecycle operations.

    Responsibilities:
    - Maintain single source of truth for mission session state
    - Handle mission storage setup (new/resume)
    - Coordinate with MissionController for timing state
    - Coordinate with MissionStorageController for archive/backup operations
    - Handle project lifecycle hooks (read/new)
    - Manage coordinator metadata collection
    - Emit signals for UI updates

    Dependencies are injected via __init__ to avoid plugin globals.

    LIFE-SAFETY CRITICAL: Mission state transitions must be handled carefully.
    All defensive patterns from the original implementation are preserved.

    Phase 2 Refactor: This controller is the single point of truth for
    mission session state, replacing scattered sartracker.py instance variables:
    - _mission_folder_name
    - _mission_directory
    - _mission_attachments_dir
    - _mission_backup_directory
    - _mission_gpkg_path
    - _mission_coordinators_cache
    - _metadata_collected

    Signals:
        session_state_changed: Emitted when mission session state changes
            Args: MissionSessionState snapshot
        storage_status_changed: Emitted when storage status needs UI update
            Args: bool (active), str (primary_path), str (backup_path)
        coordinator_metadata_requested: Emitted when coordinator dialog should show
            Args: str (mode: "new" | "resume"), bool (allow_resume_time)
        mission_finalized: Emitted when mission is marked as finalized
        mission_unlocked: Emitted when finalized mission is unlocked
        resume_prompt_requested: Emitted when resume/start-fresh dialog needed
            Args: Path (gpkg_path)
        new_mission_name_requested: Emitted when new mission name dialog needed
    """

    # Session state signals
    session_state_changed = pyqtSignal(object)  # MissionSessionState
    storage_status_changed = pyqtSignal(bool, str, str)  # active, primary, backup

    # Coordinator metadata signals
    coordinator_metadata_requested = pyqtSignal(str, bool)  # mode, allow_resume_time

    # Finalization signals
    mission_finalized = pyqtSignal()
    mission_unlocked = pyqtSignal()

    # Dialog request signals (for orchestrator to handle UI)
    resume_prompt_requested = pyqtSignal(object)  # Path (gpkg_path)
    new_mission_name_requested = pyqtSignal()

    # Post-storage operation signals (orchestrator handles layer/catalog ops)
    # These are emitted after storage is set up, allowing sartracker.py to
    # perform operations that need controllers not available to this class
    storage_prepared = pyqtSignal()  # New mission storage ready - rebuild layers
    storage_resumed = pyqtSignal()  # Mission resumed - recover layers if needed
    storage_loaded = pyqtSignal(bool)  # Existing storage loaded - arg: is_active

    # Project lifecycle signals
    # structure_ensured: Emitted after layer structure is ensured. Orchestrator
    # should call layers_controller.ensure_helicopter_layers() and other post-init ops
    structure_ensured = pyqtSignal()
    # project_sync_complete: Emitted when project state sync is complete
    project_sync_complete = pyqtSignal(str)  # arg: reason

    # Backup/autosave signals
    backup_completed = pyqtSignal(bool)  # arg: success
    autosave_status_changed = pyqtSignal(bool)  # arg: success
    # paused_mission_found: Emitted when a paused mission is detected
    # Args: saved_state dict, or None if no paused mission
    paused_mission_found = pyqtSignal(object)
    # mission_resumed_from_pause: Emitted after successfully resuming a paused mission
    mission_resumed_from_pause = pyqtSignal(str)  # arg: mission_name

    # Finalization signals
    archive_completed = pyqtSignal(str)  # arg: archive_path
    archive_failed = pyqtSignal(str)  # arg: error_message
    finalization_state_changed = pyqtSignal(bool)  # arg: is_finalized

    def __init__(
        self,
        iface: "QgisInterface",
        layer_manager: Optional["LayerManager"] = None,
        mission_storage: Optional[MissionStorageHelper] = None,
        mission_controller: Optional["MissionController"] = None,
        mission_storage_controller: Optional["MissionStorageController"] = None,
        task_manager: Optional["TaskManager"] = None,
        is_unloading: Optional[Callable[[], bool]] = None,
        is_app_quitting: Optional[Callable[[], bool]] = None,
        log_exception: Optional[Callable[[str, Exception], None]] = None,
        parent: Optional[QObject] = None
    ):
        """
        Initialize mission lifecycle controller.

        Args:
            iface: QGIS interface (for messageBar notifications)
            layer_manager: LayerManager for SAR project state and layer operations
            mission_storage: MissionStorageHelper for filesystem operations
            mission_controller: MissionController for timing state (optional)
            mission_storage_controller: MissionStorageController for archive/backup
            task_manager: TaskManager for background operations
            is_unloading: Callback to check if plugin is unloading
            is_app_quitting: Callback to check if app is quitting
            log_exception: Callback to log exceptions
            parent: Optional QObject parent (for Qt lifecycle)
        """
        super().__init__(parent)

        self.iface = iface
        self.layer_manager = layer_manager
        self.mission_storage = mission_storage
        self.mission_controller = mission_controller
        self.mission_storage_controller = mission_storage_controller
        self.task_manager = task_manager

        # Callbacks for lifecycle guards
        self._is_unloading = is_unloading or (lambda: False)
        self._is_app_quitting = is_app_quitting or (lambda: False)
        self._log_exception = log_exception

        # Shutdown flag for thread-safe callback guards (Pattern 9)
        self._is_shutting_down: bool = False

        # Finalization in-progress flag (prevents duplicate finalization)
        self._is_finalizing: bool = False

        # Thread-safe lock for state access (protects _session_state)
        # Required because background task callbacks may access state from worker threads
        self._state_lock = threading.RLock()

        # Session state - single source of truth (protected by _state_lock)
        self._session_state = MissionSessionState.empty()

        # Project signature for change detection
        self._last_project_signature: str = ""

    # ------------------------------------------------------------------
    # Session State Access (Read-Only External Access)
    # ------------------------------------------------------------------
    # NOTE on thread safety:
    # - get_session_state() uses _state_lock for atomic snapshot reads
    # - Individual property accessors do NOT use locks for performance
    # - Properties provide eventually-consistent reads suitable for UI display
    # - For atomic operations, always use get_session_state() or get_current_paths()

    def get_session_state(self) -> MissionSessionState:
        """
        Get current mission session state.

        Returns:
            MissionSessionState snapshot (safe for passing across boundaries)

        THREAD-SAFETY: Uses lock to ensure atomic read of state.
        """
        with self._state_lock:
            return self._session_state.snapshot()

    def get_current_paths(self) -> Optional[MissionPaths]:
        """
        Get current mission paths for storage operations.

        Returns:
            MissionPaths if valid, None otherwise

        Use when calling MissionStorageHelper methods that expect MissionPaths.
        THREAD-SAFETY: Uses lock to ensure atomic read of state.
        """
        with self._state_lock:
            return self._session_state.to_paths()

    @property
    def mission_name(self) -> str:
        """Current mission name."""
        return self._session_state.mission_name

    @property
    def mission_dir(self) -> Optional[Path]:
        """Current mission directory path."""
        return self._session_state.mission_dir

    @property
    def gpkg_path(self) -> Optional[Path]:
        """Current mission GeoPackage path."""
        return self._session_state.gpkg_path

    @property
    def attachments_dir(self) -> Optional[Path]:
        """Current mission attachments directory."""
        return self._session_state.attachments_dir

    @property
    def backup_dir(self) -> Optional[Path]:
        """Current mission backup directory."""
        return self._session_state.backup_dir

    @property
    def coordinators(self) -> str:
        """Current mission coordinators (comma-separated)."""
        return self._session_state.coordinators

    @property
    def is_finalized(self) -> bool:
        """Whether current mission is finalized."""
        return self._session_state.is_finalized

    @property
    def is_active(self) -> bool:
        """Whether mission is actively being tracked."""
        return self._session_state.is_active

    @property
    def metadata_collected(self) -> bool:
        """Whether coordinator metadata has been collected."""
        return self._session_state.metadata_collected

    def has_storage(self) -> bool:
        """Check if mission storage is configured and exists."""
        return self._session_state.has_storage()

    # ------------------------------------------------------------------
    # Session State Updates (Internal Methods)
    # ------------------------------------------------------------------

    def _update_session_state(self, **kwargs) -> None:
        """
        Update session state fields and emit change signal.

        Args:
            **kwargs: Fields to update (must match MissionSessionState attributes)

        SAFETY: Creates new state instance to ensure immutability of emitted signals.
        THREAD-SAFETY: Uses lock for atomic state update.
        """
        if self._is_shutting_down:
            return

        with self._state_lock:
            # Build new state with updated fields
            new_state = MissionSessionState(
                mission_name=kwargs.get('mission_name', self._session_state.mission_name),
                mission_dir=kwargs.get('mission_dir', self._session_state.mission_dir),
                attachments_dir=kwargs.get('attachments_dir', self._session_state.attachments_dir),
                backup_dir=kwargs.get('backup_dir', self._session_state.backup_dir),
                gpkg_path=kwargs.get('gpkg_path', self._session_state.gpkg_path),
                project_path=kwargs.get('project_path', self._session_state.project_path),
                is_finalized=kwargs.get('is_finalized', self._session_state.is_finalized),
                is_active=kwargs.get('is_active', self._session_state.is_active),
                start_time=kwargs.get('start_time', self._session_state.start_time),
                coordinators=kwargs.get('coordinators', self._session_state.coordinators),
                metadata_collected=kwargs.get('metadata_collected', self._session_state.metadata_collected),
            )
            self._session_state = new_state

        # Re-check shutdown before emitting signal (TOCTOU protection)
        if not self._is_shutting_down:
            self.session_state_changed.emit(new_state.snapshot())

    def _clear_session_state(self) -> None:
        """Clear all session state to empty/idle."""
        with self._state_lock:
            self._session_state = MissionSessionState.empty()
            self._last_project_signature = ""
            snapshot = self._session_state.snapshot()

        # Re-check shutdown before emitting signal
        if not self._is_shutting_down:
            self.session_state_changed.emit(snapshot)

    def _update_from_paths(
        self,
        paths: MissionPaths,
        project_path: Optional[Path] = None,
        coordinators: str = "",
        metadata_collected: bool = False
    ) -> None:
        """
        Update session state from MissionPaths result.

        Args:
            paths: MissionPaths from storage operations
            project_path: Optional QGIS project file path
            coordinators: Coordinator names (comma-separated)
            metadata_collected: Whether metadata has been collected
        """
        # Check finalized state from layer manager
        is_finalized = False
        if self.layer_manager:
            try:
                is_finalized = self.layer_manager.is_mission_finalized()
            except Exception as exc:
                # Log but don't fail - finalized state defaults to False
                if self._log_exception:
                    self._log_exception("_update_from_paths.is_finalized", exc)

        # Check active state from mission controller
        is_active = False
        start_time = None
        if self.mission_controller:
            try:
                is_active = self.mission_controller.is_active()
                # Get start time if available
                snapshot = self.mission_controller.status_snapshot()
                if snapshot.get('started_at'):
                    try:
                        start_time = datetime.fromisoformat(snapshot['started_at'])
                    except (TypeError, ValueError) as exc:
                        # Log but don't fail - start_time is optional
                        if self._log_exception:
                            self._log_exception("_update_from_paths.start_time", exc)
            except Exception as exc:
                # Log but don't fail - active state defaults to False
                if self._log_exception:
                    self._log_exception("_update_from_paths.is_active", exc)

        self._update_session_state(
            mission_name=paths.name,
            mission_dir=paths.mission_dir,
            attachments_dir=paths.attachments_dir,
            backup_dir=paths.backup_dir,
            gpkg_path=paths.gpkg_path,
            project_path=project_path,
            is_finalized=is_finalized,
            is_active=is_active,
            start_time=start_time,
            coordinators=coordinators,
            metadata_collected=metadata_collected,
        )

    # ------------------------------------------------------------------
    # Coordinator Metadata
    # ------------------------------------------------------------------

    def set_coordinators(self, coordinators: str, persist: bool = True) -> bool:
        """
        Set mission coordinators.

        Args:
            coordinators: Comma-separated coordinator names
            persist: Whether to persist to layer manager (default True)

        Returns:
            True if successful
        """
        if self._is_shutting_down:
            return False

        if persist and self.layer_manager:
            try:
                self.layer_manager.set_mission_coordinators(coordinators)
            except Exception as exc:
                if self._log_exception:
                    self._log_exception("set_coordinators", exc)
                return False

        self._update_session_state(
            coordinators=coordinators,
            metadata_collected=bool(coordinators and coordinators.strip())
        )
        return True

    def mark_metadata_collected(self, collected: bool = True) -> None:
        """Mark whether coordinator metadata has been collected."""
        self._update_session_state(metadata_collected=collected)

    # ------------------------------------------------------------------
    # Finalization State
    # ------------------------------------------------------------------

    def check_finalized(self) -> bool:
        """
        Check and update finalization state from layer manager.

        Returns:
            True if mission is finalized
        """
        is_finalized = False
        if self.layer_manager:
            try:
                is_finalized = self.layer_manager.is_mission_finalized()
            except Exception as exc:
                # Log but don't fail - finalized state defaults to False
                if self._log_exception:
                    self._log_exception("check_finalized", exc)

        if is_finalized != self._session_state.is_finalized:
            self._update_session_state(is_finalized=is_finalized)

        return is_finalized

    def set_finalized(self, finalized: bool, finalized_by: Optional[str] = None) -> bool:
        """
        Set mission finalization state.

        Args:
            finalized: True to mark as finalized, False to unlock
            finalized_by: Optional name of person who finalized/unlocked

        Returns:
            True if state was updated successfully
        """
        if self._is_shutting_down:
            return False

        if not self.layer_manager:
            return False

        try:
            self.layer_manager.set_mission_finalized(finalized, finalized_by=finalized_by)
        except Exception as exc:
            if self._log_exception:
                self._log_exception("set_finalized", exc)
            warning(
                self.iface.messageBar(),
                "Mission",
                f"Failed to update finalization state: {exc}",
                duration=5
            )
            return False

        self._update_session_state(is_finalized=finalized)

        # Emit signals (guarded by shutdown check)
        if not self._is_shutting_down:
            if finalized:
                self.mission_finalized.emit()
            else:
                self.mission_unlocked.emit()

        return True

    # ------------------------------------------------------------------
    # Active State Sync
    # ------------------------------------------------------------------

    def sync_active_state(self) -> None:
        """
        Synchronize is_active state with MissionController.

        Call when mission controller state may have changed externally.
        """
        is_active = False
        start_time = None

        if self.mission_controller:
            try:
                is_active = self.mission_controller.is_active()
                snapshot = self.mission_controller.status_snapshot()
                if snapshot.get('started_at'):
                    try:
                        start_time = datetime.fromisoformat(snapshot['started_at'])
                    except (TypeError, ValueError) as exc:
                        # Log but don't fail - start_time is optional
                        if self._log_exception:
                            self._log_exception("sync_active_state.start_time", exc)
            except Exception as exc:
                # Log but don't fail - active state defaults to False
                if self._log_exception:
                    self._log_exception("sync_active_state", exc)

        if is_active != self._session_state.is_active or start_time != self._session_state.start_time:
            self._update_session_state(is_active=is_active, start_time=start_time)

    # ------------------------------------------------------------------
    # Storage Status (UI Helper)
    # ------------------------------------------------------------------

    def emit_storage_status(self) -> None:
        """
        Emit storage status for UI updates.

        Emits storage_status_changed signal with current paths.
        """
        if self._is_shutting_down:
            return

        primary = str(self._session_state.gpkg_path) if self._session_state.gpkg_path else ""
        backup = str(self._session_state.backup_dir) if self._session_state.backup_dir else ""

        self.storage_status_changed.emit(
            self._session_state.is_active,
            primary,
            backup
        )

    # ------------------------------------------------------------------
    # Project Path
    # ------------------------------------------------------------------

    def update_project_path(self) -> None:
        """Update project_path from current QGIS project."""
        try:
            project = QgsProject.instance()
            project_file = project.fileName() if project else None
            project_path = Path(project_file) if project_file else None
            if project_path != self._session_state.project_path:
                self._update_session_state(project_path=project_path)
        except Exception as exc:
            # Log but don't fail - project path is not critical for operation
            if self._log_exception:
                self._log_exception("update_project_path", exc)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def cleanup(self) -> None:
        """
        Clean up controller resources.

        Called during plugin unload. Sets shutdown flag to prevent
        callbacks from accessing destroyed objects. Idempotent.
        """
        self._is_shutting_down = True
        # Don't clear state - may be needed for diagnostics during shutdown
        # Just prevent further updates

    def status_snapshot(self) -> dict:
        """
        Return current status for diagnostics.

        Returns:
            Dict with controller state information

        THREAD-SAFETY: Uses lock for atomic read of session state.
        """
        with self._state_lock:
            state_dict = self._session_state.status_dict()
        state_dict["is_shutting_down"] = self._is_shutting_down
        state_dict["is_finalizing"] = self._is_finalizing
        state_dict["has_layer_manager"] = self.layer_manager is not None
        state_dict["has_mission_storage"] = self.mission_storage is not None
        state_dict["has_mission_controller"] = self.mission_controller is not None
        state_dict["has_storage_controller"] = self.mission_storage_controller is not None
        return state_dict


    # ==========================================================================
    # P2.3: Mission Path Creation/Resume/Load (SAR-9dg)
    # ==========================================================================

    @staticmethod
    def sanitize_mission_name(name: str) -> str:
        """
        Generate a filesystem-safe mission folder name.

        Args:
            name: Raw mission name from user input

        Returns:
            Sanitized name safe for use as directory name
        """
        sanitized = re.sub(r'[^A-Za-z0-9 _-]+', '', name or '').strip()
        sanitized = re.sub(r'\s+', '_', sanitized)
        if not sanitized:
            sanitized = f"mission_{datetime.now():%Y%m%d_%H%M%S}"
        return sanitized

    def mission_roots_from_settings(self) -> tuple:
        """
        Return primary and backup mission roots as Path objects.

        Returns:
            Tuple of (primary_root: Path, backup_root: Optional[Path])
        """
        if not self.mission_storage:
            return Path(ConfigStore.get_mission_primary_root()).expanduser(), None
        return self.mission_storage.mission_roots()

    def show_resume_prompt(self, gpkg_path: Path) -> bool:
        """
        Show a dialog asking user whether to resume existing mission or start fresh.

        Args:
            gpkg_path: Path to the existing mission GeoPackage

        Returns:
            True if user chose to resume, False if user chose start fresh
        """
        mission_name = gpkg_path.parent.name

        # Check if mission is finalized directly from layer_manager
        # (Don't use check_finalized() which updates session state before storage is loaded)
        is_finalized = False
        if self.layer_manager:
            try:
                is_finalized = self.layer_manager.is_mission_finalized()
            except Exception as exc:
                if self._log_exception:
                    self._log_exception("show_resume_prompt.finalized_check", exc)

        if is_finalized:
            message = (
                f"Found finalized mission: <b>{mission_name}</b>\n\n"
                f"Location: {gpkg_path.parent}\n\n"
                f"This mission has been archived and is marked as read-only.\n\n"
                f"<b>Resume:</b> View mission data (read-only mode)\n"
                f"<b>Start Fresh:</b> Clear this mission and begin a new one"
            )
        else:
            message = (
                f"Found existing mission: <b>{mission_name}</b>\n\n"
                f"Location: {gpkg_path.parent}\n\n"
                f"<b>Resume:</b> Continue working on this mission\n"
                f"<b>Start Fresh:</b> Clear this mission and begin a new one"
            )

        dialog = QMessageBox(self.iface.mainWindow())
        dialog.setWindowTitle("Resume Mission?")
        dialog.setText(message)
        dialog.setIcon(QMessageBox.Question)

        resume_button = dialog.addButton("Resume", QMessageBox.AcceptRole)
        start_fresh_button = dialog.addButton("Start Fresh", QMessageBox.RejectRole)
        dialog.setDefaultButton(resume_button)

        dialog_exec(dialog)

        clicked_button = dialog.clickedButton()
        return clicked_button == resume_button

    def prompt_new_mission_name(self) -> Optional[str]:
        """
        Prompt user for a new mission name when starting fresh.

        Returns:
            Sanitized mission name, or None if cancelled
        """
        default_name = f"Mission {datetime.now().strftime('%Y-%m-%d %H:%M')}"

        name, ok = QInputDialog.getText(
            self.iface.mainWindow(),
            "Start New Mission",
            "Enter a name for the new mission:",
            text=default_name
        )
        if not ok:
            return None

        sanitized = self.sanitize_mission_name(name)
        if not sanitized:
            sanitized = self.sanitize_mission_name(default_name)
        return sanitized

    def collect_mission_metadata(
        self,
        mode: str,
        allow_resume_time: bool,
        preselected: Optional[List[str]] = None
    ) -> bool:
        """
        Prompt for coordinators (and optional resume time) and persist to project.

        Args:
            mode: "start" or "resume" (affects dialog wording)
            allow_resume_time: Whether to show resume timestamp field
            preselected: Coordinators to pre-select in dialog

        Returns:
            True if metadata was collected, False if cancelled or failed
        """
        if self._is_shutting_down:
            return False

        if not self.layer_manager:
            return False

        # Import dialog here to avoid circular imports at module load
        from ..ui.mission_metadata_dialog import MissionMetadataDialog

        roster = ConfigStore.get_coordinator_list()
        existing_raw = self.layer_manager.get_mission_coordinators()
        existing: List[str] = []
        if existing_raw:
            for token in existing_raw.split(","):
                name = token.strip()
                if name:
                    existing.append(name)
        preselect = preselected or existing

        dialog = MissionMetadataDialog(
            coordinators=roster,
            mode=mode,
            allow_resume_time=allow_resume_time,
            preselected=preselect,
            parent=self.iface.mainWindow()
        )
        result = dialog_exec(dialog)
        if result != DialogAccepted:
            return False

        selected = dialog.selected_coordinators()
        pending_entry = dialog.pending_entry()
        updated_roster = dialog.updated_roster()

        # Preserve existing selections if none were checked
        if not selected and existing:
            selected = existing

        # If user typed but didn't press Add, capture that entry
        if not selected and pending_entry:
            selected = [pending_entry]
            updated_roster = updated_roster or []
            if pending_entry not in updated_roster:
                updated_roster.append(pending_entry)

        # If still empty, fall back to all entries in list (checked or not)
        if not selected:
            all_entries = dialog.all_entries()
            if all_entries:
                selected = all_entries

        # Persist coordinators for mission and settings roster enrichment
        try:
            self.layer_manager.set_mission_coordinators(",".join(selected))
            self._update_session_state(
                coordinators=",".join(selected),
                metadata_collected=bool(selected)
            )
        except Exception as exc:
            warning(
                self.iface.messageBar(),
                "Mission Metadata",
                f"Failed to save coordinators: {exc}",
                duration=6
            )
            if self._log_exception:
                self._log_exception("collect_mission_metadata.persist", exc)

        if updated_roster:
            ConfigStore.set_coordinator_roster("\n".join(updated_roster))

        resume_dt = dialog.resume_timestamp()
        if resume_dt:
            try:
                iso_ts = resume_dt.toUTC().toString(ISODate)
                self.layer_manager.set_resume_timestamp(iso_ts)
            except Exception as exc:
                if self._log_exception:
                    self._log_exception("collect_mission_metadata.resume_ts", exc)

        # If still empty, use cache or global roster so we don't reprompt forever
        if not selected:
            fallback: List[str] = []
            cached = self._session_state.coordinators
            if cached:
                fallback = [name for name in cached.split(",") if name.strip()]
            elif roster:
                fallback = roster
            if fallback:
                selected = fallback
                try:
                    self.layer_manager.set_mission_coordinators(",".join(selected))
                    self._update_session_state(
                        coordinators=",".join(selected),
                        metadata_collected=True
                    )
                except Exception as exc:
                    if self._log_exception:
                        self._log_exception("collect_mission_metadata.fallback", exc)

        # Only treat metadata as collected if we have coordinators recorded
        collected = bool(selected)
        self._update_session_state(metadata_collected=collected)
        return collected

    def prepare_new_mission(self, mission_name: str) -> bool:
        """
        Create mission storage directories + GeoPackage for a new mission.

        Args:
            mission_name: Name for the new mission (will be sanitized)

        Returns:
            True if storage was prepared successfully

        Emits:
            storage_prepared: After successful setup (orchestrator should rebuild layers)
        """
        if self._is_shutting_down:
            return False

        if not self.layer_manager or not self.mission_storage:
            return False

        try:
            paths = self.mission_storage.prepare_new_mission(mission_name)
        except Exception as exc:
            if self._log_exception:
                self._log_exception("prepare_new_mission", exc)
            error(
                self.iface.messageBar(),
                "Mission Storage",
                f"Failed to prepare mission storage: {exc}",
                duration=6
            )
            return False

        # Update session state with new paths
        self._update_session_state(
            mission_name=paths.name,
            mission_dir=paths.mission_dir,
            attachments_dir=paths.attachments_dir,
            backup_dir=paths.backup_dir,
            gpkg_path=paths.gpkg_path,
            coordinators="",
            metadata_collected=False,
            is_active=False,
            is_finalized=False,
        )

        # Emit signal for orchestrator to perform layer rebuild
        # (needs layers_controller which we don't have access to)
        if not self._is_shutting_down:
            self.storage_prepared.emit()
            self.emit_storage_status()

        return True

    def handle_mission_resume(self, mission_name: str) -> bool:
        """
        Restore mission storage metadata when resuming a paused mission.

        Args:
            mission_name: Name of the mission to resume

        Returns:
            True if resume was successful

        Emits:
            storage_resumed: After successful resume (orchestrator may recover layers)
        """
        if self._is_shutting_down:
            return False

        if not self.layer_manager or not self.mission_storage:
            return False

        store_path = self.layer_manager.get_mission_store()
        if not store_path:
            warning(
                self.iface.messageBar(),
                "Mission Storage",
                "Mission store path missing; creating a new mission store.",
                duration=5
            )
            return self.prepare_new_mission(mission_name)

        try:
            paths = self.mission_storage.handle_resume(Path(store_path))
        except Exception as exc:
            if self._log_exception:
                self._log_exception("handle_mission_resume", exc)
            warning(
                self.iface.messageBar(),
                "Mission Storage",
                f"Mission store invalid, starting fresh: {exc}",
                duration=5
            )
            return self.prepare_new_mission(mission_name)

        # Load coordinators from project
        existing_coords = ""
        try:
            existing_coords = self.layer_manager.get_mission_coordinators() or ""
        except Exception as exc:
            if self._log_exception:
                self._log_exception("handle_mission_resume.coords", exc)

        # Update session state
        self._update_session_state(
            mission_name=paths.name,
            mission_dir=paths.mission_dir,
            attachments_dir=paths.attachments_dir,
            backup_dir=paths.backup_dir,
            gpkg_path=paths.gpkg_path,
            coordinators=existing_coords,
            metadata_collected=bool(existing_coords),
        )

        # Emit signals
        if not self._is_shutting_down:
            self.storage_resumed.emit()
            self.emit_storage_status()

        return True

    def load_existing_storage_state(self) -> bool:
        """
        Initialize mission storage from current LayerManager state.

        This is the master orchestration method that:
        1. Checks for existing mission store in project
        2. Shows resume/start-fresh prompt if store exists
        3. Handles user choice (resume vs start fresh)
        4. Loads coordinator metadata
        5. Emits appropriate signals for layer operations

        Returns:
            True if storage was loaded (resumed or new), False if no action taken

        Emits:
            storage_loaded: After storage state is loaded (arg: is_active)
        """
        if self._is_shutting_down:
            return False

        if not self.layer_manager:
            return False

        store_path = self.layer_manager.get_mission_store()
        if not store_path:
            # No store configured - clear state
            self._clear_session_state()
            self.emit_storage_status()
            return False

        gpkg_path = Path(store_path)
        if gpkg_path.exists():
            # Existing store found - ask user what to do
            try:
                should_resume = self.show_resume_prompt(gpkg_path)
            except Exception as prompt_error:
                if self._log_exception:
                    self._log_exception("load_existing_storage_state.prompt", prompt_error)
                error(
                    self.iface.messageBar(),
                    "Mission Resume",
                    "Failed to show resume dialog. Starting fresh.",
                    duration=5
                )
                should_resume = False

            if not should_resume:
                # User chose "Start Fresh"
                mission_name = self.prompt_new_mission_name()
                if not mission_name:
                    info(
                        self.iface.messageBar(),
                        "SAR Tracker",
                        "Start Fresh cancelled; continuing with existing mission store.",
                        duration=4
                    )
                    return False

                if not self.prepare_new_mission(mission_name):
                    return False

                # Clear any saved mission controller state
                if self.mission_controller:
                    try:
                        self.mission_controller.clear_saved_state()
                    except Exception as exc:
                        if self._log_exception:
                            self._log_exception("load_existing_storage_state.clear_state", exc)

                is_active = self.mission_controller.is_active() if self.mission_controller else False
                info(
                    self.iface.messageBar(),
                    "SAR Tracker",
                    f"New mission storage created for '{mission_name}'.",
                    duration=4
                )

                if not self._is_shutting_down:
                    self.storage_loaded.emit(is_active)
                return True

        # User chose resume or no prompt needed - continue loading existing
        if not self._load_resumed_storage(gpkg_path):
            # Storage load failed (e.g., file disappeared)
            return False

        # If no coordinators recorded, prompt for them
        if not self._session_state.metadata_collected:
            try:
                self.collect_mission_metadata(
                    mode="resume",
                    allow_resume_time=True,
                    preselected=None
                )
            except Exception as exc:
                if self._log_exception:
                    self._log_exception("load_existing_storage_state.metadata", exc)

        is_active = self.mission_controller.is_active() if self.mission_controller else False

        if not self._is_shutting_down:
            self.storage_loaded.emit(is_active)

        return True

    def _load_resumed_storage(self, gpkg_path: Path) -> bool:
        """
        Load storage state for a resumed mission (internal helper).

        Args:
            gpkg_path: Path to the mission GeoPackage file

        Returns:
            True if storage was loaded successfully, False on failure

        SAFETY: Re-validates file existence to guard against TOCTOU race conditions
        where the file could be moved/deleted between the existence check in
        load_existing_storage_state() and actual loading here.
        """
        # TOCTOU guard: Re-check file exists before loading
        if not gpkg_path.exists():
            error(
                self.iface.messageBar(),
                "Mission Storage",
                f"Mission file no longer exists: {gpkg_path.name}",
                duration=6
            )
            if self._log_exception:
                self._log_exception(
                    "_load_resumed_storage.toctou",
                    FileNotFoundError(f"Mission file disappeared: {gpkg_path}")
                )
            return False

        mission_dir = gpkg_path.parent
        mission_name = mission_dir.name

        # Setup attachments directory
        attachments_dir = mission_dir / "attachments"
        try:
            if not attachments_dir.exists():
                attachments_dir.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            attachments_dir = None
            if self._log_exception:
                self._log_exception("_load_resumed_storage.attachments", exc)
            warning(
                self.iface.messageBar(),
                "Mission Storage",
                "Attachments folder could not be prepared. Attachments will stay at original paths.",
                duration=6
            )

        # Setup backup directory
        backup_dir = None
        if self.mission_storage:
            try:
                backup_dir = self.mission_storage.ensure_backup_directory(
                    folder_name=mission_name,
                    backup_root=None,
                    create=False
                )
            except Exception as exc:
                if self._log_exception:
                    self._log_exception("_load_resumed_storage.backup", exc)
                warning(
                    self.iface.messageBar(),
                    "Mission Storage",
                    "Backup directory unavailable. Backups are disabled until path is fixed.",
                    duration=6
                )

        # Load coordinators
        existing_coords = ""
        try:
            if self.layer_manager:
                existing_coords = self.layer_manager.get_mission_coordinators() or ""
        except Exception as exc:
            # Log but continue - coordinators are optional for operation
            if self._log_exception:
                self._log_exception("_load_resumed_storage.coordinators", exc)

        # Update session state
        self._update_session_state(
            mission_name=mission_name,
            mission_dir=mission_dir,
            attachments_dir=attachments_dir,
            backup_dir=backup_dir,
            gpkg_path=gpkg_path,
            coordinators=existing_coords,
            metadata_collected=bool(existing_coords),
        )

        # Check finalization state
        self.check_finalized()

        # Emit storage status
        self.emit_storage_status()

        return True

    # ==========================================================================
    # P2.4: Project Hooks (SAR-uay)
    # ==========================================================================

    def on_project_read(self) -> None:
        """
        Handle QGIS project read (open/restore/template load).

        This method should be connected to QgsProject.readProject signal
        by the orchestrator (sartracker.py).
        """
        self.sync_project_state(reason="projectRead")

    def on_new_project_created(self) -> None:
        """
        Handle QGIS new project created.

        This method should be connected to QgsProject.cleared signal
        by the orchestrator (sartracker.py).
        """
        self.sync_project_state(reason="newProjectCreated")

    def sync_project_state(self, reason: str = "unknown") -> bool:
        """
        Synchronize LayerManager + mission UI with the current QGIS project.

        Life-safety: This must not mutate non-SAR projects. We only ensure the
        SAR layer structure when the project already looks like a SAR Tracker
        project (e.g., it contains SAR customVariables / root group).

        Args:
            reason: Reason for sync (for logging)

        Returns:
            True if sync was performed, False if skipped

        Emits:
            structure_ensured: After layer structure is ensured
            project_sync_complete: When sync is complete (arg: reason)
        """
        if self._is_shutting_down or self._is_unloading() or self._is_app_quitting():
            return False

        if not self.layer_manager:
            return False

        project = QgsProject.instance()
        try:
            project_file = project.fileName() or ""
        except Exception:
            project_file = ""

        try:
            store = self.layer_manager.get_mission_store() or ""
        except Exception:
            store = ""

        # Signature check to avoid duplicate syncs
        signature = f"{project_file}|{store}"
        if signature == self._last_project_signature:
            return False
        self._last_project_signature = signature

        # Notify layer manager of project read
        try:
            self.layer_manager.on_project_read()
        except Exception as exc:
            if self._log_exception:
                self._log_exception(f"sync_project_state.layer_manager.{reason}", exc)

        # Only touch the project if it already indicates a SAR mission project.
        # Never create/repair structure on an unsaved startup "Untitled Project"
        # unless a mission store is already configured. This avoids dirtying the
        # transient startup project and triggering QGIS' save prompt.
        should_ensure = False
        try:
            is_sar = bool(self.layer_manager.is_sar_project())
            should_ensure = bool(store) or (bool(project_file) and is_sar)
        except Exception:
            should_ensure = False

        if should_ensure:
            try:
                self.layer_manager.ensure_structure(auto_migrate=True)
            except Exception as exc:
                if self._log_exception:
                    self._log_exception(f"sync_project_state.ensure_structure.{reason}", exc)
                warning(
                    self.iface.messageBar(),
                    "Layer Structure",
                    f"Could not verify SAR layer structure for this project: {exc}",
                    duration=6,
                )

            # Signal orchestrator to perform post-structure operations
            # (e.g., helicopter layer init) that need controllers we don't have
            if not self._is_shutting_down:
                self.structure_ensured.emit()

        # Refresh mission storage state (uses load_existing_storage_state from P2.3)
        try:
            self.load_existing_storage_state()
        except Exception as exc:
            if self._log_exception:
                self._log_exception(f"sync_project_state.load_existing.{reason}", exc)

        # Signal sync complete
        if not self._is_shutting_down:
            self.project_sync_complete.emit(reason)

        return True

    # ==========================================================================
    # P2.5: Backup/Autosave (SAR-vwz)
    # ==========================================================================

    def sync_backup(self, async_run: bool = False) -> bool:
        """
        Mirror GeoPackage (and attachments if present) to backup root.

        Args:
            async_run: If True, run backup in background task

        Returns:
            True if backup initiated/completed successfully, False on error

        Emits:
            backup_completed: After backup finishes (arg: success)
        """
        if self._is_shutting_down:
            return False

        if not self.mission_storage:
            return True  # No storage configured is not an error

        paths = self.get_current_paths()
        if not paths:
            return True  # No paths configured is not an error

        if async_run:
            # Use MissionStorageController if available (preferred path)
            if self.mission_storage_controller:
                self.mission_storage_controller.start_backup_task(paths)
                return True
            # Fallback: use task_manager directly
            elif self.task_manager:
                self._start_backup_task_inline(paths)
                return True
            # No async capability - fall through to sync

        # Synchronous backup
        try:
            result = self.mission_storage.sync_backup(paths)
            if not self._is_shutting_down:
                self.backup_completed.emit(result)
            return result
        except Exception as exc:
            if self._log_exception:
                self._log_exception("sync_backup", exc)
            warning(
                self.iface.messageBar(),
                "Mission Backup",
                f"Backup failed: {exc}",
                duration=6
            )
            if not self._is_shutting_down:
                self.backup_completed.emit(False)
            return False

    def _start_backup_task_inline(self, paths: MissionPaths) -> None:
        """
        Run backup sync in background using inline QgsTask (fallback path).

        This is used when MissionStorageController is not available.
        Prefer using mission_storage_controller.start_backup_task() when available.

        Args:
            paths: Mission paths for backup

        SAFETY: Uses weakref to avoid preventing garbage collection of controller
        during plugin unload. Callbacks check sip_isdeleted before accessing objects.
        """
        # Guard: task_manager must be available
        if not self.task_manager:
            if self._log_exception:
                self._log_exception(
                    "_start_backup_task_inline",
                    RuntimeError("task_manager is None, cannot start backup task")
                )
            return

        from qgis.core import QgsTask

        # Use weakref to avoid preventing GC during plugin unload
        controller_weak = weakref.ref(self)

        class BackupTask(QgsTask):
            def __init__(self, mission_paths: MissionPaths, storage: MissionStorageHelper):
                super().__init__("Sync mission backup", QgsTask.CanCancel)
                self.paths = mission_paths
                self.storage = storage
                self.error_message = None

            def run(self) -> bool:
                try:
                    return bool(self.storage.sync_backup(self.paths))
                except Exception as exc:
                    self.error_message = str(exc)
                    return False

        def on_complete(task):
            controller = controller_weak()
            if controller is None or controller._is_shutting_down:
                return
            # Check if Qt objects are still valid
            if sip_isdeleted(controller) or sip_isdeleted(controller.iface):
                return
            has_error = bool(getattr(task, "error_message", None))
            if has_error:
                warning(
                    controller.iface.messageBar(),
                    "Mission Backup",
                    f"Backup completed with warnings: {task.error_message}",
                    duration=4
                )
            else:
                success(
                    controller.iface.messageBar(),
                    "Mission Backup",
                    "Mission backup completed.",
                    duration=2
                )
            if not controller._is_shutting_down:
                controller.backup_completed.emit(not has_error)

        def on_error(task):
            controller = controller_weak()
            if controller is None or controller._is_shutting_down:
                return
            # Check if Qt objects are still valid
            if sip_isdeleted(controller) or sip_isdeleted(controller.iface):
                return
            msg = getattr(task, "error_message", None) or "Backup task failed."
            warning(
                controller.iface.messageBar(),
                "Mission Backup",
                msg,
                duration=5
            )
            if not controller._is_shutting_down:
                controller.backup_completed.emit(False)

        task = BackupTask(paths, self.mission_storage)
        self.task_manager.start_task(
            task=task,
            on_complete=on_complete,
            on_error=on_error,
            task_id="mission_backup"
        )

    def check_for_paused_mission(self) -> Optional[dict]:
        """
        Check if there's a paused mission and prompt user to resume.

        This should be called during plugin initialization after all
        components are ready.

        Returns:
            Saved state dict if mission was resumed, None otherwise

        Emits:
            paused_mission_found: When a paused mission is detected
            mission_resumed_from_pause: After successful resume (arg: mission_name)
        """
        if self._is_shutting_down or self._is_unloading() or self._is_app_quitting():
            return None

        if not self.mission_controller:
            return None

        try:
            saved_state = self.mission_controller.load_saved_state()

            if not saved_state:
                return None

            # Emit signal so orchestrator can show panel if needed
            if not self._is_shutting_down:
                self.paused_mission_found.emit(saved_state)

            # Import dialog here to avoid circular imports
            from ..ui.mission_resume_dialog import MissionResumeDialog

            dialog = MissionResumeDialog(saved_state, parent=self.iface.mainWindow())
            result = dialog_exec(dialog)

            if result == DialogAccepted:
                try:
                    if self.mission_controller.restore_from_state(saved_state):
                        mission_name = saved_state.get('name', 'Unknown')
                        success(
                            self.iface.messageBar(),
                            "SAR Tracker",
                            f"Mission '{mission_name}' resumed",
                            duration=3
                        )
                        if not self._is_shutting_down:
                            self.mission_resumed_from_pause.emit(mission_name)
                        return saved_state
                except Exception as restore_error:
                    if self._log_exception:
                        self._log_exception("check_for_paused_mission.restore", restore_error)
                    error(
                        self.iface.messageBar(),
                        "Mission Resume Failed",
                        f"Could not restore mission: {restore_error}",
                        duration=5
                    )
                    self.mission_controller.clear_saved_state()
            else:
                # User declined to resume
                self.mission_controller.clear_saved_state()

        except Exception as exc:
            if self._log_exception:
                self._log_exception("check_for_paused_mission", exc)
            error(
                self.iface.messageBar(),
                "SAR Tracker",
                f"Error checking for paused mission: {exc}",
                duration=5
            )

        return None

    # ==========================================================================
    # P2.6: Finalize/Unlock/Archive (SAR-984)
    # ==========================================================================

    def on_finalize_requested(self) -> bool:
        """
        Handle finalize mission request.

        Saves the project and creates a mission archive in the background.

        Returns:
            True if finalization was started, False if skipped/failed

        Emits:
            archive_completed: After successful archive (arg: archive_path)
            archive_failed: On archive failure (arg: error_message)
            finalization_state_changed: When finalization state changes
        """
        if self._is_shutting_down or self._is_unloading() or self._is_app_quitting():
            return False

        # Race condition protection: prevent duplicate finalization
        if self._is_finalizing:
            info(
                self.iface.messageBar(),
                "Finalize Mission",
                "Finalization already in progress, please wait.",
                duration=3
            )
            return False

        paths = self.get_current_paths()
        if not paths:
            error(
                self.iface.messageBar(),
                "Finalize Mission",
                "No active mission store to finalize.",
                duration=5
            )
            return False

        # Check if already finalized
        if self.check_finalized():
            info(
                self.iface.messageBar(),
                "Finalize Mission",
                "Mission is already finalized.",
                duration=3
            )
            return False

        self._is_finalizing = True
        try:
            # Save project before archiving
            project = QgsProject.instance()
            if project.fileName():
                if not project.write():
                    raise RuntimeError("Failed to save QGIS project before finalization")
            else:
                error(
                    self.iface.messageBar(),
                    "Finalize Mission",
                    "Please save the project before finalizing the mission.",
                    duration=5
                )
                self._is_finalizing = False
                return False

            project_path = Path(project.fileName()) if project.fileName() else None

            # Run archive in background
            return self.start_archive_task(paths, project_path)

        except Exception as exc:
            self._is_finalizing = False
            if self._log_exception:
                self._log_exception("on_finalize_requested", exc)
            error(
                self.iface.messageBar(),
                "Finalize Mission",
                f"Failed to finalize mission: {exc}",
                duration=10
            )
            return False

    def start_archive_task(
        self,
        paths: MissionPaths,
        project_path: Optional[Path]
    ) -> bool:
        """
        Start background task to create mission archive.

        Args:
            paths: MissionPaths with current mission directories
            project_path: Optional path to QGIS project file to include

        Returns:
            True if archive task was started, False otherwise

        IMPORTANT: When using mission_storage_controller (async path), the caller
        MUST connect on_archive_complete() and on_archive_failed() to the
        storage controller's archive_succeeded and archive_failed signals.
        Otherwise _is_finalizing will remain True forever, blocking future
        finalization attempts.
        """
        if self.mission_storage_controller:
            started = self.mission_storage_controller.start_archive_task(
                paths=paths,
                project_path=project_path,
                mark_finalized=True
            )
            if not started:
                self._is_finalizing = False
                warning(
                    self.iface.messageBar(),
                    "Mission Archive",
                    "Archive could not be started.",
                    duration=5
                )
                return False
            return True

        # Fallback: no controller available, use synchronous method
        try:
            if self.mission_storage:
                archive_path = self.mission_storage.create_archive(paths, project_path)
            else:
                error(
                    self.iface.messageBar(),
                    "Mission Archive",
                    "No storage helper available for archive.",
                    duration=5
                )
                self._is_finalizing = False
                return False

            # Mark as finalized
            if self.set_finalized(True):
                archive_name = archive_path.name if hasattr(archive_path, 'name') else str(archive_path)
                success(
                    self.iface.messageBar(),
                    "Mission Finalized",
                    f"Archive created: {archive_name}",
                    duration=6
                )
                if not self._is_shutting_down:
                    self.archive_completed.emit(str(archive_path))
                    self.finalization_state_changed.emit(True)
                return True
            else:
                warning(
                    self.iface.messageBar(),
                    "Mission Archive",
                    "Archive created but could not mark mission as finalized.",
                    duration=6
                )
                return False

        except Exception as exc:
            if self._log_exception:
                self._log_exception("start_archive_task.fallback", exc)
            error(
                self.iface.messageBar(),
                "Mission Archive",
                f"Archive failed: {exc}",
                duration=8
            )
            if not self._is_shutting_down:
                self.archive_failed.emit(str(exc))
            return False

        finally:
            self._is_finalizing = False

    def on_archive_complete(self, archive_path: str) -> None:
        """
        Handle successful archive completion from MissionStorageController.

        This should be connected to MissionStorageController.archive_succeeded signal.

        Args:
            archive_path: Path to the created archive file
        """
        self._is_finalizing = False

        # Update state
        self._update_session_state(is_finalized=True)

        # Emit signals
        if not self._is_shutting_down:
            self.archive_completed.emit(archive_path)
            self.finalization_state_changed.emit(True)
            self.mission_finalized.emit()

        # Show success notification
        archive_name = Path(archive_path).name if archive_path else "archive"
        success(
            self.iface.messageBar(),
            "Mission Finalized",
            f"Archive created: {archive_name}",
            duration=6
        )

    def on_archive_failed(self, error_message: str) -> None:
        """
        Handle archive failure from MissionStorageController.

        This should be connected to MissionStorageController.archive_failed signal.

        Args:
            error_message: Error description
        """
        self._is_finalizing = False

        if not self._is_shutting_down:
            self.archive_failed.emit(error_message)

        error(
            self.iface.messageBar(),
            "Mission Archive",
            f"Archive failed: {error_message}",
            duration=8
        )

    def on_unlock_requested(self) -> bool:
        """
        Handle admin unlock request for finalized missions.

        Shows a dialog to enter admin name and unlocks the mission if valid.

        Returns:
            True if mission was unlocked, False otherwise

        Emits:
            finalization_state_changed: When mission is unlocked (arg: False)
            mission_unlocked: After successful unlock
        """
        if self._is_shutting_down:
            return False

        if not self.layer_manager or not self.check_finalized():
            info(
                self.iface.messageBar(),
                "Mission Unlock",
                "Mission is not finalized.",
                duration=4
            )
            return False

        admin_roster = ConfigStore.get_admin_list()
        prompt_text = "Enter admin name to unlock mission:"
        if admin_roster:
            prompt_text += f"\nAllowed: {', '.join(admin_roster)}"

        admin_name, ok = QInputDialog.getText(
            self.iface.mainWindow(),
            "Unlock Finalized Mission",
            prompt_text
        )
        if not ok:
            return False

        admin_name = (admin_name or "").strip()
        if admin_roster and admin_name not in admin_roster:
            warning(
                self.iface.messageBar(),
                "Mission Unlock",
                "Admin not in roster.",
                duration=5
            )
            return False

        if self.set_finalized(False, finalized_by=admin_name):
            info(
                self.iface.messageBar(),
                "Mission Unlock",
                "Mission unlocked. Editing is re-enabled.",
                duration=5
            )
            if not self._is_shutting_down:
                self.finalization_state_changed.emit(False)
            return True
        else:
            error(
                self.iface.messageBar(),
                "Mission Unlock",
                "Failed to unlock mission.",
                duration=6
            )
            return False
