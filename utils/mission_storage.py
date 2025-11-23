# -*- coding: utf-8 -*-
"""
Mission storage helpers (filesystem and validation).

This module avoids QGIS/UI dependencies so it can be tested headlessly.
"""
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Callable
import shutil
import re
import zipfile
from datetime import datetime


WarnFunc = Callable[[str, str, int], None]


@dataclass
class MissionPaths:
    """Resolved mission storage paths."""
    name: str
    mission_dir: Path
    attachments_dir: Path
    backup_dir: Optional[Path]
    gpkg_path: Path


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

    def sync_backup(self, mission_paths: MissionPaths) -> bool:
        """Mirror GeoPackage (and attachments if present) to backup root."""
        if not mission_paths or not mission_paths.backup_dir:
            return True  # Backup optional or not configured

        gpkg_path = mission_paths.gpkg_path
        backup_dir = mission_paths.backup_dir
        if not gpkg_path.exists():
            return False

        try:
            backup_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(gpkg_path, backup_dir / gpkg_path.name)

            attachments_src = mission_paths.attachments_dir
            if attachments_src and attachments_src.exists():
                attachments_dst = backup_dir / "attachments"
                attachments_dst.mkdir(parents=True, exist_ok=True)
                for child in attachments_src.iterdir():
                    target = attachments_dst / child.name
                    if child.is_file():
                        shutil.copy2(child, target)
                    elif child.is_dir():
                        shutil.copytree(child, target, dirs_exist_ok=True)
            return True
        except Exception as exc:
            self.warn("Mission Backup", f"Failed to sync mission backup: {exc}", duration=5)
            return False

    def create_archive(self, mission_paths: MissionPaths, project_path: Optional[Path]) -> Path:
        """
        Create a zip archive of the mission GeoPackage, project, and attachments.

        Returns:
            Path to created archive
        Raises:
            RuntimeError on failure
        """
        if not mission_paths or not mission_paths.gpkg_path:
            raise RuntimeError("Mission paths not set")

        if not mission_paths.gpkg_path.exists():
            raise RuntimeError(f"Mission GeoPackage not found at {mission_paths.gpkg_path}")

        # Determine archive directory
        if mission_paths.backup_dir and mission_paths.backup_dir.exists():
            archive_dir = mission_paths.backup_dir
        else:
            archive_dir = mission_paths.mission_dir.parent

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        archive_name = f"{mission_paths.name}_finalized_{timestamp}.zip"
        archive_path = archive_dir / archive_name

        try:
            with zipfile.ZipFile(archive_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                zipf.write(
                    mission_paths.gpkg_path,
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
            if archive_path.exists():
                try:
                    archive_path.unlink()
                except Exception:
                    pass
            raise RuntimeError(f"Failed to create archive: {exc}") from exc
