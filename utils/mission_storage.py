# -*- coding: utf-8 -*-
"""
Mission storage helpers (filesystem and validation).

This module avoids QGIS/UI dependencies so it can be tested headlessly.

DATA INTEGRITY: This module uses SQLite-native backup mechanisms (VACUUM INTO
or connection.backup()) to create consistent GeoPackage snapshots, preventing
data loss during active tracking sessions.
"""
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Callable
import shutil
import re
import zipfile
import sqlite3
import tempfile
import logging
from datetime import datetime


logger = logging.getLogger(__name__)

WarnFunc = Callable[[str, str, int], None]

# Minimum SQLite version for VACUUM INTO support
VACUUM_INTO_MIN_VERSION = (3, 27, 0)


@dataclass
class MissionPaths:
    """Resolved mission storage paths."""
    name: str
    mission_dir: Path
    attachments_dir: Path
    backup_dir: Optional[Path]
    gpkg_path: Path


@dataclass
class MissionSessionState:
    """
    Runtime mission session state for controllers and UI coordination.

    This dataclass consolidates mission state that was previously scattered
    across sartracker.py instance variables. It provides a clean interface
    for passing mission context between controllers and the UI.

    Differences from MissionPaths:
    - MissionPaths: Filesystem paths only (for storage operations)
    - MissionSessionState: Runtime session context (for controllers/UI)

    Phase 2 Refactor: This enables clean dependency injection and reduces
    coupling between sartracker.py and controllers.

    LIFE-SAFETY CRITICAL: Mission state transitions must be handled carefully.
    Prefer immutable snapshots when passing state across boundaries.
    """
    # Filesystem paths (mirrors MissionPaths for convenience)
    mission_name: str
    mission_dir: Optional[Path]
    attachments_dir: Optional[Path]
    backup_dir: Optional[Path]
    gpkg_path: Optional[Path]

    # Project context
    project_path: Optional[Path] = None

    # Finalization state
    is_finalized: bool = False

    # Active session tracking
    is_active: bool = False
    start_time: Optional[datetime] = None

    # Coordinator metadata
    coordinators: str = ""
    metadata_collected: bool = False

    @classmethod
    def from_paths(
        cls,
        paths: MissionPaths,
        *,
        project_path: Optional[Path] = None,
        is_finalized: bool = False,
        is_active: bool = False,
        start_time: Optional[datetime] = None,
        coordinators: str = "",
        metadata_collected: bool = False,
    ) -> "MissionSessionState":
        """
        Create MissionSessionState from MissionPaths with additional context.

        Args:
            paths: MissionPaths with filesystem locations
            project_path: Optional QGIS project file path
            is_finalized: Whether mission is marked as finalized
            is_active: Whether mission is actively being tracked
            start_time: Mission start timestamp (UTC)
            coordinators: Comma-separated coordinator names
            metadata_collected: Whether coordinator metadata has been collected

        Returns:
            MissionSessionState with combined filesystem and runtime state
        """
        return cls(
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

    @classmethod
    def empty(cls) -> "MissionSessionState":
        """
        Create an empty/idle MissionSessionState.

        Use when no mission is loaded or mission has been cleared.
        """
        return cls(
            mission_name="",
            mission_dir=None,
            attachments_dir=None,
            backup_dir=None,
            gpkg_path=None,
            project_path=None,
            is_finalized=False,
            is_active=False,
            start_time=None,
            coordinators="",
            metadata_collected=False,
        )

    def to_paths(self) -> Optional[MissionPaths]:
        """
        Convert to MissionPaths if all required filesystem paths are set.

        Returns:
            MissionPaths if valid, None if any required path is missing

        Use for passing to MissionStorageHelper operations that expect MissionPaths.
        """
        if not self.mission_name or not self.mission_dir or not self.gpkg_path:
            return None
        if not self.attachments_dir:
            return None
        return MissionPaths(
            name=self.mission_name,
            mission_dir=self.mission_dir,
            attachments_dir=self.attachments_dir,
            backup_dir=self.backup_dir,
            gpkg_path=self.gpkg_path,
        )

    def has_storage(self) -> bool:
        """Check if mission storage is configured (gpkg_path is set and exists)."""
        return bool(self.gpkg_path and self.gpkg_path.exists())

    def has_coordinators(self) -> bool:
        """Check if coordinators have been recorded for this mission."""
        return bool(self.coordinators and self.coordinators.strip())

    def snapshot(self) -> "MissionSessionState":
        """
        Create an immutable snapshot of current state.

        Use when passing state to background tasks or across thread boundaries
        to prevent race conditions from state mutations.

        Returns:
            New MissionSessionState instance with same values
        """
        return MissionSessionState(
            mission_name=self.mission_name,
            mission_dir=self.mission_dir,
            attachments_dir=self.attachments_dir,
            backup_dir=self.backup_dir,
            gpkg_path=self.gpkg_path,
            project_path=self.project_path,
            is_finalized=self.is_finalized,
            is_active=self.is_active,
            start_time=self.start_time,
            coordinators=self.coordinators,
            metadata_collected=self.metadata_collected,
        )

    def status_dict(self) -> dict:
        """
        Return state as dictionary for diagnostics and logging.

        Returns:
            Dict with string-serializable values for status display.
            Empty/whitespace-only strings are normalized to None.
        """
        # Normalize strings: empty or whitespace-only becomes None
        mission_name = self.mission_name.strip() if self.mission_name else None
        mission_name = mission_name if mission_name else None
        coordinators = self.coordinators.strip() if self.coordinators else None
        coordinators = coordinators if coordinators else None

        return {
            "mission_name": mission_name,
            "mission_dir": str(self.mission_dir) if self.mission_dir else None,
            "gpkg_path": str(self.gpkg_path) if self.gpkg_path else None,
            "backup_dir": str(self.backup_dir) if self.backup_dir else None,
            "project_path": str(self.project_path) if self.project_path else None,
            "is_finalized": self.is_finalized,
            "is_active": self.is_active,
            "start_time": self.start_time.isoformat() if self.start_time else None,
            "coordinators": coordinators,
            "metadata_collected": self.metadata_collected,
            "has_storage": self.has_storage(),
        }


# =============================================================================
# Safe GeoPackage Backup Functions
# =============================================================================

def _sqlite_version_tuple() -> tuple:
    """Return SQLite version as tuple of integers."""
    return tuple(int(x) for x in sqlite3.sqlite_version.split('.'))


def _supports_vacuum_into() -> bool:
    """Check if SQLite supports VACUUM INTO command (SQLite 3.27+)."""
    return _sqlite_version_tuple() >= VACUUM_INTO_MIN_VERSION


def _backup_with_vacuum_into(source_path: Path, dest_path: Path) -> bool:
    """
    Create backup using VACUUM INTO (SQLite 3.27+).

    This creates an optimized, consistent snapshot in a single operation.
    Works even during active read/write operations.

    Args:
        source_path: Path to source GeoPackage file
        dest_path: Path for backup file

    Returns:
        True if backup succeeded

    Raises:
        RuntimeError: If backup operation fails
    """
    conn = None
    try:
        conn = sqlite3.connect(str(source_path))
        # Use proper escaping for the path
        dest_str = str(dest_path).replace("'", "''")
        conn.execute(f"VACUUM INTO '{dest_str}'")
        logger.info(
            "Created safe GeoPackage snapshot via VACUUM INTO: %s -> %s",
            source_path.name, dest_path.name
        )
        return True
    except sqlite3.Error as exc:
        logger.error(
            "VACUUM INTO backup failed for %s: %s",
            source_path, exc
        )
        # Clean up partial backup if it exists
        if dest_path.exists():
            try:
                dest_path.unlink()
            except Exception:
                pass
        raise RuntimeError(f"GeoPackage backup failed: {exc}") from exc
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


def _backup_with_connection_api(source_path: Path, dest_path: Path) -> bool:
    """
    Create backup using connection.backup() API (Python 3.7+).

    Fallback for SQLite versions that don't support VACUUM INTO.
    Uses incremental backup with small page count to minimize lock time.

    Args:
        source_path: Path to source GeoPackage file
        dest_path: Path for backup file

    Returns:
        True if backup succeeded

    Raises:
        RuntimeError: If backup operation fails
    """
    source_conn = None
    dest_conn = None
    try:
        source_conn = sqlite3.connect(str(source_path))
        dest_conn = sqlite3.connect(str(dest_path))

        # Use incremental backup with small page count to minimize lock time
        source_conn.backup(dest_conn, pages=100, sleep=0.01)

        logger.info(
            "Created safe GeoPackage snapshot via backup API: %s -> %s",
            source_path.name, dest_path.name
        )
        return True
    except sqlite3.Error as exc:
        logger.error(
            "Connection backup failed for %s: %s",
            source_path, exc
        )
        # Clean up partial backup
        if dest_path.exists():
            try:
                dest_path.unlink()
            except Exception:
                pass
        raise RuntimeError(f"GeoPackage backup failed: {exc}") from exc
    finally:
        for conn in (dest_conn, source_conn):
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass


def format_uncommitted_edits(uncommitted: list, operation: str) -> Optional[str]:
    """
    Format a warning message for layers with uncommitted edits.

    Args:
        uncommitted: List of layer names with uncommitted edits
        operation: Operation name (e.g., "backup", "archive")

    Returns:
        Warning message string or None if no edits
    """
    if not uncommitted:
        return None
    layer_list = ", ".join(uncommitted[:3])
    if len(uncommitted) > 3:
        layer_list += f" (+{len(uncommitted) - 3} more)"
    return (
        f"Layers with unsaved changes: {layer_list}. "
        f"These changes may not be included in {operation}."
    )


def check_uncommitted_edits(project=None) -> list:
    """
    Check for layers with uncommitted edits in the current project.

    DATA INTEGRITY: Identifies layers with unsaved changes that may not be
    included in backups. Call before backup operations to warn users.

    Args:
        project: QgsProject instance (defaults to QgsProject.instance())

    Returns:
        List of layer names with uncommitted edits, empty if none found
        or if QGIS is not available.
    """
    try:
        from qgis.core import QgsProject
        proj = project or QgsProject.instance()
        if not proj:
            return []

        uncommitted = []
        # THREAD-SAFETY: Create snapshot of layers to avoid dictionary mutation
        # during iteration if layers are added/removed by another thread
        layers = list(proj.mapLayers().values())
        for layer in layers:
            try:
                # Check if layer is editable and has uncommitted changes
                if hasattr(layer, 'isEditable') and hasattr(layer, 'isModified'):
                    if layer.isEditable() and layer.isModified():
                        name = layer.name()
                        if name:  # Guard against None names
                            uncommitted.append(name)
            except (RuntimeError, AttributeError):
                # Layer may be invalid or deleted
                continue

        return uncommitted
    except ImportError:
        # QGIS not available (headless testing)
        return []
    except Exception as e:
        logger.warning(f"Error checking uncommitted edits: {e}")
        return []


def create_safe_snapshot(source_path: Path, dest_path: Path) -> bool:
    """
    Create a consistent snapshot of a GeoPackage database.

    DATA INTEGRITY: Uses VACUUM INTO when available (SQLite 3.27+), falls back
    to connection.backup() API for older SQLite versions. Both methods create
    transactionally consistent snapshots that work even during active
    read/write operations.

    Args:
        source_path: Path to source GeoPackage file
        dest_path: Path for backup file (must not exist)

    Returns:
        True if backup succeeded

    Raises:
        FileNotFoundError: If source file does not exist
        FileExistsError: If destination file already exists
        RuntimeError: If backup operation fails
    """
    if not source_path.exists():
        raise FileNotFoundError(f"Source GeoPackage not found: {source_path}")

    if dest_path.exists():
        raise FileExistsError(f"Backup destination already exists: {dest_path}")

    # Ensure parent directory exists
    dest_path.parent.mkdir(parents=True, exist_ok=True)

    if _supports_vacuum_into():
        return _backup_with_vacuum_into(source_path, dest_path)
    else:
        return _backup_with_connection_api(source_path, dest_path)


def validate_archive(archive_path: Path, mission_paths: MissionPaths) -> Optional[str]:
    """
    Validate that an archive exists and contains the mission GeoPackage entry.

    Args:
        archive_path: Path to archive zip file
        mission_paths: MissionPaths for expected entry names

    Returns:
        None if valid, otherwise error message string
    """
    if not archive_path:
        return "Archive path is missing"
    if not archive_path.exists():
        return f"Archive file not found: {archive_path}"
    try:
        if archive_path.stat().st_size <= 0:
            return "Archive file is empty"
    except Exception as exc:
        return f"Archive file not accessible: {exc}"

    if not zipfile.is_zipfile(str(archive_path)):
        return "Archive file is not a valid zip"

    expected_entry = f"{mission_paths.name}/{mission_paths.gpkg_path.name}"
    try:
        with zipfile.ZipFile(archive_path, "r") as zipf:
            names = set(zipf.namelist())
            if expected_entry not in names:
                return f"Archive is missing GeoPackage entry: {expected_entry}"
    except Exception as exc:
        return f"Archive validation failed: {exc}"

    return None


# =============================================================================
# Mission Storage Helper Class
# =============================================================================

class MissionStorageHelper:
    """Encapsulates mission storage and backup filesystem operations."""

    def __init__(self, layer_manager, config_store, warn: Optional[WarnFunc] = None):
        self.layer_manager = layer_manager
        self.config_store = config_store
        self.warn = warn or (lambda title, msg, duration=5: None)

    # ------------------------------------------------------------------ #
    # Paths and sanitization
    # ------------------------------------------------------------------ #
    @staticmethod
    def sanitize_mission_name(name: str) -> str:
        """Generate filesystem-safe mission folder name."""
        sanitized = re.sub(r'[^A-Za-z0-9 _-]+', '', name or '').strip()
        sanitized = re.sub(r'\s+', '_', sanitized)
        if not sanitized:
            from datetime import datetime
            sanitized = f"mission_{datetime.now():%Y%m%d_%H%M%S}"
        return sanitized

    def mission_roots(self):
        """Return primary and backup mission roots as Path objects."""
        primary_root = Path(self.config_store.get_mission_primary_root()).expanduser()
        backup_root_str = self.config_store.get_mission_backup_root()
        backup_root = Path(backup_root_str).expanduser() if backup_root_str else None
        return primary_root, backup_root

    # ------------------------------------------------------------------ #
    # Directory setup
    # ------------------------------------------------------------------ #
    def ensure_backup_directory(self, folder_name: Optional[str], backup_root: Optional[Path], create: bool) -> Optional[Path]:
        """Ensure backup directory exists when configured."""
        backup_root = backup_root or (Path(self.config_store.get_mission_backup_root()).expanduser()
                                      if self.config_store.get_mission_backup_root() else None)
        if not backup_root or not folder_name:
            return None

        target = backup_root / folder_name
        if create:
            try:
                target.mkdir(parents=True, exist_ok=True)
                (target / "attachments").mkdir(parents=True, exist_ok=True)
            except Exception as exc:
                self.warn("Mission Backup", f"Failed to prepare backup directory: {exc}", duration=5)
                return None
        return target

    def prepare_new_mission(self, mission_name: str) -> MissionPaths:
        """Create mission storage directories + GeoPackage for a new mission."""
        if not self.layer_manager:
            raise RuntimeError("Layer manager is not initialized")

        # Clear finalized flag and metadata
        try:
            self.layer_manager.set_mission_finalized(False)
        except Exception:
            pass
        try:
            self.layer_manager.set_mission_coordinators("")
            self.layer_manager.set_resume_timestamp("")
        except Exception:
            pass

        primary_root, backup_root = self.mission_roots()
        sanitized_name = self.sanitize_mission_name(mission_name)
        mission_dir = primary_root / sanitized_name
        attachments_dir = mission_dir / "attachments"
        mission_dir.mkdir(parents=True, exist_ok=True)
        attachments_dir.mkdir(parents=True, exist_ok=True)

        gpkg_path = mission_dir / f"{sanitized_name}.gpkg"
        backup_dir = self.ensure_backup_directory(sanitized_name, backup_root, create=True)

        # Persist to layer manager and ensure schema
        self.layer_manager.set_mission_store(str(gpkg_path))
        self.layer_manager.ensure_structure(auto_migrate=False)

        return MissionPaths(
            name=sanitized_name,
            mission_dir=mission_dir,
            attachments_dir=attachments_dir,
            backup_dir=backup_dir,
            gpkg_path=gpkg_path
        )

    def handle_resume(self, store_path: Path) -> MissionPaths:
        """Restore mission storage metadata when resuming a paused mission."""
        if not self.layer_manager:
            raise RuntimeError("Layer manager is not initialized")

        gpkg_path = Path(store_path)
        if not gpkg_path.exists():
            raise FileNotFoundError(f"Mission GeoPackage not found at {gpkg_path}")
        sanitized_name = gpkg_path.parent.name
        mission_dir = gpkg_path.parent
        attachments_dir = mission_dir / "attachments"
        attachments_dir.mkdir(parents=True, exist_ok=True)
        backup_dir = self.ensure_backup_directory(sanitized_name, None, create=True)

        # Cache coordinators in project
        try:
            existing_coords = self.layer_manager.get_mission_coordinators() if self.layer_manager else ""
            self._mission_coordinators_cache = existing_coords or ""
        except Exception:
            self._mission_coordinators_cache = ""

        return MissionPaths(
            name=sanitized_name,
            mission_dir=mission_dir,
            attachments_dir=attachments_dir,
            backup_dir=backup_dir,
            gpkg_path=gpkg_path
        )

    # ------------------------------------------------------------------ #
    # Attachments and backups
    # ------------------------------------------------------------------ #
    def ingest_attachment(self, mission_paths: MissionPaths, attachment_path: Optional[str]) -> Optional[str]:
        """Copy user-selected attachments into the mission folder and return mission-relative path."""
        if not attachment_path:
            return None

        attachments_dir = mission_paths.attachments_dir
        mission_dir = mission_paths.mission_dir

        raw_path = Path(attachment_path).expanduser()

        # If user entered a mission-relative path (e.g. existing attachment), keep it
        if not raw_path.is_absolute():
            candidate = mission_dir / raw_path
            if candidate.exists():
                try:
                    return str(candidate.relative_to(mission_dir))
                except ValueError:
                    return str(candidate)
        else:
            try:
                mission_resolved = mission_dir.resolve()
                raw_resolved = raw_path.resolve()
                try:
                    rel = raw_resolved.relative_to(mission_resolved)
                    return str(rel)
                except ValueError:
                    pass
            except Exception:
                pass

        destination = attachments_dir / raw_path.name
        counter = 1
        while destination.exists():
            destination = attachments_dir / f"{raw_path.stem}_{counter}{raw_path.suffix}"
            counter += 1

        try:
            shutil.copy2(raw_path, destination)
        except Exception as exc:
            self.warn("Attachments", f"Failed to copy attachment: {exc}", duration=5)
            return attachment_path

        try:
            return str(destination.relative_to(mission_dir))
        except ValueError:
            return str(destination)

    def sync_backup(
        self,
        mission_paths: MissionPaths,
        *,
        uncommitted_layers: Optional[list] = None,
        warn_uncommitted: bool = True,
        warn_on_error: bool = True
    ) -> bool:
        """
        Mirror GeoPackage (and attachments if present) to backup root.

        DATA INTEGRITY: Uses SQLite-native backup mechanism (VACUUM INTO or
        connection.backup()) to create consistent GeoPackage snapshot, preventing
        data loss during active tracking sessions. Warns users if layers have
        uncommitted edits that won't be included in the backup.

        Args:
            mission_paths: Mission paths for backup
            uncommitted_layers: Precomputed uncommitted edit list (optional)
            warn_uncommitted: Whether to warn about uncommitted edits
            warn_on_error: Whether to emit warnings on backup failure
        """
        if not mission_paths or not mission_paths.backup_dir:
            return True  # Backup optional or not configured

        gpkg_path = mission_paths.gpkg_path
        backup_dir = mission_paths.backup_dir
        if not gpkg_path.exists():
            return False

        # DATA INTEGRITY: Check for uncommitted edits before backup
        if uncommitted_layers is None:
            uncommitted_layers = check_uncommitted_edits()
        if uncommitted_layers:
            msg = format_uncommitted_edits(uncommitted_layers, "backup")
            if msg and warn_uncommitted:
                self.warn("Uncommitted Edits", msg, duration=8)
            logger.warning(f"Backup proceeding with uncommitted edits in: {uncommitted_layers}")

        try:
            backup_dir.mkdir(parents=True, exist_ok=True)

            # Use safe snapshot into a temp file, then atomically replace
            backup_gpkg = backup_dir / gpkg_path.name
            temp_gpkg = backup_dir / f".{gpkg_path.name}.tmp"
            if temp_gpkg.exists():
                temp_gpkg.unlink()

            create_safe_snapshot(gpkg_path, temp_gpkg)
            temp_gpkg.replace(backup_gpkg)

            # Copy attachments (regular files, safe to copy directly)
            attachments_src = mission_paths.attachments_dir
            if attachments_src and attachments_src.exists():
                attachments_dst = backup_dir / "attachments"
                attachments_tmp = backup_dir / ".attachments_tmp"
                attachments_old = backup_dir / ".attachments_old"

                if attachments_tmp.exists():
                    shutil.rmtree(attachments_tmp, ignore_errors=True)
                attachments_tmp.mkdir(parents=True, exist_ok=True)

                for child in attachments_src.iterdir():
                    target = attachments_tmp / child.name
                    if child.is_file():
                        shutil.copy2(child, target)
                    elif child.is_dir():
                        shutil.copytree(child, target, dirs_exist_ok=True)

                if attachments_dst.exists():
                    if attachments_old.exists():
                        shutil.rmtree(attachments_old, ignore_errors=True)
                    attachments_dst.rename(attachments_old)

                try:
                    attachments_tmp.rename(attachments_dst)
                except Exception:
                    if attachments_old.exists() and not attachments_dst.exists():
                        attachments_old.rename(attachments_dst)
                    raise
                finally:
                    if attachments_old.exists():
                        shutil.rmtree(attachments_old, ignore_errors=True)
            return True
        except Exception as exc:
            try:
                temp_gpkg = backup_dir / f".{gpkg_path.name}.tmp"
                if temp_gpkg.exists():
                    temp_gpkg.unlink()
            except Exception:
                pass
            try:
                attachments_tmp = backup_dir / ".attachments_tmp"
                if attachments_tmp.exists():
                    shutil.rmtree(attachments_tmp, ignore_errors=True)
            except Exception:
                pass
            if warn_on_error:
                self.warn("Mission Backup", f"Failed to sync mission backup: {exc}", duration=5)
            logger.warning("Mission backup failed: %s", exc)
            return False

    def create_archive(
        self,
        mission_paths: MissionPaths,
        project_path: Optional[Path],
        *,
        uncommitted_layers: Optional[list] = None,
        warn_uncommitted: bool = True
    ) -> Path:
        """
        Create a zip archive of the mission GeoPackage, project, and attachments.

        DATA INTEGRITY: Creates a consistent GeoPackage snapshot using SQLite-native
        backup before archiving, preventing data loss during active tracking sessions.
        Warns users if layers have uncommitted edits.

        Args:
            mission_paths: Mission paths for archive
            project_path: Optional QGIS project file path
            uncommitted_layers: Precomputed uncommitted edit list (optional)
            warn_uncommitted: Whether to warn about uncommitted edits

        Returns:
            Path to created archive
        Raises:
            RuntimeError on failure
        """
        if not mission_paths or not mission_paths.gpkg_path:
            raise RuntimeError("Mission paths not set")

        if not mission_paths.gpkg_path.exists():
            raise RuntimeError(f"Mission GeoPackage not found at {mission_paths.gpkg_path}")

        # DATA INTEGRITY: Check for uncommitted edits before archive
        if uncommitted_layers is None:
            uncommitted_layers = check_uncommitted_edits()
        if uncommitted_layers:
            msg = format_uncommitted_edits(uncommitted_layers, "archive")
            if msg and warn_uncommitted:
                self.warn("Uncommitted Edits", msg, duration=8)
            logger.warning(f"Archive proceeding with uncommitted edits in: {uncommitted_layers}")

        # Create temporary snapshot for consistent archive
        temp_dir = Path(tempfile.mkdtemp(prefix="sartracker_archive_"))
        snapshot_path = temp_dir / mission_paths.gpkg_path.name

        try:
            # Create safe snapshot first
            create_safe_snapshot(mission_paths.gpkg_path, snapshot_path)

            # Determine archive directory
            if mission_paths.backup_dir and mission_paths.backup_dir.exists():
                archive_dir = mission_paths.backup_dir
            else:
                archive_dir = mission_paths.mission_dir.parent

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            archive_name = f"{mission_paths.name}_finalized_{timestamp}.zip"
            archive_path = archive_dir / archive_name

            with zipfile.ZipFile(archive_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                # Add the consistent snapshot (not the live file)
                zipf.write(
                    snapshot_path,
                    arcname=f"{mission_paths.name}/{mission_paths.gpkg_path.name}"
                )
                if project_path and project_path.exists():
                    zipf.write(
                        project_path,
                        arcname=f"{mission_paths.name}/{project_path.name}"
                    )
                if mission_paths.attachments_dir and mission_paths.attachments_dir.exists():
                    for attachment_file in mission_paths.attachments_dir.rglob('*'):
                        if attachment_file.is_file():
                            rel_path = attachment_file.relative_to(mission_paths.mission_dir)
                            zipf.write(
                                attachment_file,
                                arcname=f"{mission_paths.name}/{rel_path}"
                            )
            return archive_path
        except Exception as exc:
            # Clean up partial archive if it exists
            if 'archive_path' in locals() and archive_path.exists():
                try:
                    archive_path.unlink()
                except Exception:
                    pass
            raise RuntimeError(f"Failed to create archive: {exc}") from exc
        finally:
            # Clean up temporary snapshot
            shutil.rmtree(temp_dir, ignore_errors=True)

    # ------------------------------------------------------------------ #
    # Temporary Replay Store (Phase 3: SAR-604i)
    # ------------------------------------------------------------------ #
    # These methods manage temporary storage for replay mode.
    # Replay data must be isolated from live mission data.

    @staticmethod
    def _get_replay_cache_root() -> Path:
        """
        Get the root directory for replay temp stores.

        Returns path under QGIS profile: <profile>/sartracker/replay/

        Returns:
            Path to replay cache root directory.

        Raises:
            RuntimeError: If QGIS profile path cannot be determined.
        """
        try:
            from qgis.core import QgsApplication
            profile_dir = QgsApplication.qgisSettingsDirPath()
        except Exception:
            # Fallback to temp directory if QGIS not available
            import tempfile
            profile_dir = tempfile.gettempdir()

        cache_root = Path(profile_dir) / "sartracker" / "replay"
        return cache_root

    @staticmethod
    def prepare_temp_replay_store(token: str) -> Optional[str]:
        """
        Create a temporary mission store for replay mode.

        Creates a unique directory under the replay cache root and returns
        the path to a GeoPackage file within it.

        Args:
            token: Unique identifier for this replay session (e.g., UUID).

        Returns:
            Absolute path to the temp GeoPackage file, or None if creation fails.

        Note:
            The directory structure is:
            <profile>/sartracker/replay/<token>/replay_temp.gpkg
        """
        if not token:
            return None

        try:
            cache_root = MissionStorageHelper._get_replay_cache_root()
            store_dir = cache_root / token
            store_dir.mkdir(parents=True, exist_ok=True)

            gpkg_path = store_dir / "replay_temp.gpkg"
            return str(gpkg_path)

        except Exception as exc:
            print(f"[MissionStorageHelper] Failed to create temp replay store: {exc}")
            return None

    @staticmethod
    def cleanup_temp_replay_store(gpkg_path: Optional[str]) -> None:
        """
        Clean up a temporary replay store.

        Removes the entire directory containing the temp GeoPackage.
        Safe to call with None or non-existent path.

        Args:
            gpkg_path: Path to the temp GeoPackage, or None.
        """
        if not gpkg_path:
            return

        try:
            store_dir = Path(gpkg_path).parent
            if store_dir.exists() and store_dir.is_dir():
                # Safety check: only delete if it's under replay cache
                cache_root = MissionStorageHelper._get_replay_cache_root()
                if str(store_dir).startswith(str(cache_root)):
                    shutil.rmtree(store_dir, ignore_errors=True)
                else:
                    print(f"[MissionStorageHelper] Refusing to delete {store_dir} - not under replay cache")
        except Exception as exc:
            # Best-effort cleanup - don't raise
            print(f"[MissionStorageHelper] Failed to cleanup temp replay store: {exc}")
