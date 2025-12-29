# -*- coding: utf-8 -*-
"""
Tests for MissionStorageHelper (filesystem operations, no QGIS).
"""
from pathlib import Path
import tempfile

import pytest

from sartracker.utils.mission_storage import MissionStorageHelper, MissionPaths, validate_archive


class FakeLayerManager:
    def __init__(self):
        self.mission_store = None
        self.finalized = None
        self.coordinators = ""
        self.resume_ts = ""
        self.ensure_structure_called = False

    def set_mission_finalized(self, value):
        self.finalized = value

    def set_mission_coordinators(self, coords):
        self.coordinators = coords

    def set_resume_timestamp(self, ts):
        self.resume_ts = ts

    def set_mission_store(self, store):
        self.mission_store = store

    def ensure_structure(self, auto_migrate=False):
        self.ensure_structure_called = True

    def get_mission_coordinators(self):
        return self.coordinators


class FakeConfigStore:
    def __init__(self, primary_root: Path, backup_root: Path):
        self._primary = primary_root
        self._backup = backup_root

    def get_mission_primary_root(self):
        return str(self._primary)

    def get_mission_backup_root(self):
        return str(self._backup)


def test_prepare_new_mission_creates_paths_and_sets_store():
    with tempfile.TemporaryDirectory() as tmpdir:
        primary = Path(tmpdir) / "primary"
        backup = Path(tmpdir) / "backup"
        config = FakeConfigStore(primary, backup)
        lm = FakeLayerManager()

        helper = MissionStorageHelper(layer_manager=lm, config_store=config)
        paths = helper.prepare_new_mission("Test Mission")

        assert paths.mission_dir.exists()
        assert paths.attachments_dir.exists()
        assert paths.gpkg_path.parent == paths.mission_dir
        assert paths.backup_dir.exists()
        assert lm.mission_store == str(paths.gpkg_path)
        assert lm.ensure_structure_called is True


def test_handle_resume_uses_existing_store_and_creates_backup():
    with tempfile.TemporaryDirectory() as tmpdir:
        primary = Path(tmpdir) / "primary"
        backup = Path(tmpdir) / "backup"
        mission_dir = primary / "missionA"
        mission_dir.mkdir(parents=True, exist_ok=True)
        gpkg = mission_dir / "missionA.gpkg"
        gpkg.touch()

        config = FakeConfigStore(primary, backup)
        lm = FakeLayerManager()
        helper = MissionStorageHelper(layer_manager=lm, config_store=config)

        paths = helper.handle_resume(gpkg)

        assert paths.gpkg_path == gpkg
        assert paths.attachments_dir.exists()
        assert paths.backup_dir.exists()


def test_handle_resume_missing_store_raises():
    with tempfile.TemporaryDirectory() as tmpdir:
        primary = Path(tmpdir) / "primary"
        backup = Path(tmpdir) / "backup"
        mission_dir = primary / "missionA"
        mission_dir.mkdir(parents=True, exist_ok=True)
        gpkg = mission_dir / "missionA.gpkg"

        config = FakeConfigStore(primary, backup)
        lm = FakeLayerManager()
        helper = MissionStorageHelper(layer_manager=lm, config_store=config)

        with pytest.raises(FileNotFoundError):
            helper.handle_resume(gpkg)


def test_ingest_attachment_copies_file_and_returns_relative():
    with tempfile.TemporaryDirectory() as tmpdir:
        primary = Path(tmpdir) / "primary"
        backup = Path(tmpdir) / "backup"
        config = FakeConfigStore(primary, backup)
        lm = FakeLayerManager()
        helper = MissionStorageHelper(layer_manager=lm, config_store=config)
        paths = helper.prepare_new_mission("AttachTest")

        src_file = Path(tmpdir) / "note.txt"
        src_file.write_text("hello")

        rel = helper.ingest_attachment(paths, str(src_file))
        stored = paths.mission_dir / Path(rel)

        assert stored.exists()
        assert stored.read_text() == "hello"


def test_sync_backup_copies_gpkg_and_attachments():
    with tempfile.TemporaryDirectory() as tmpdir:
        primary = Path(tmpdir) / "primary"
        backup = Path(tmpdir) / "backup"
        config = FakeConfigStore(primary, backup)
        lm = FakeLayerManager()
        helper = MissionStorageHelper(layer_manager=lm, config_store=config)
        paths = helper.prepare_new_mission("BackupTest")

        # create gpkg and attachment content
        paths.gpkg_path.touch()
        attachment = paths.attachments_dir / "a.txt"
        attachment.write_text("data")

        ok = helper.sync_backup(paths)
        assert ok is True

        backup_gpkg = paths.backup_dir / paths.gpkg_path.name
        backup_attachment = paths.backup_dir / "attachments" / "a.txt"
        assert backup_gpkg.exists()
        assert backup_attachment.exists()


def test_create_archive_includes_gpkg_project_and_attachments():
    with tempfile.TemporaryDirectory() as tmpdir:
        primary = Path(tmpdir) / "primary"
        backup = Path(tmpdir) / "backup"
        config = FakeConfigStore(primary, backup)
        lm = FakeLayerManager()
        helper = MissionStorageHelper(layer_manager=lm, config_store=config)
        paths = helper.prepare_new_mission("ArchiveTest")

        # Create gpkg, project, attachment
        paths.gpkg_path.touch()
        project_file = paths.mission_dir / "project.qgz"
        project_file.write_text("dummy")
        attachment = paths.attachments_dir / "note.txt"
        attachment.write_text("hello")

        archive_path = helper.create_archive(paths, project_file)
        assert archive_path.exists()
        assert validate_archive(archive_path, paths) is None

        import zipfile
        with zipfile.ZipFile(archive_path, 'r') as zipf:
            names = zipf.namelist()
            assert f"{paths.name}/{paths.gpkg_path.name}" in names
            assert f"{paths.name}/{project_file.name}" in names
            assert any(n.endswith("note.txt") for n in names)
