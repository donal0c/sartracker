# -*- coding: utf-8 -*-
"""
Tests for SQLite backup operations in mission_storage.py.

These tests verify the ACTUAL SQLite backup functions that ensure data integrity
during mission operations. Bugs here cause data loss during active tracking.

Value: Tests critical data integrity functions for GeoPackage snapshots.
"""

import sqlite3
import tempfile
from pathlib import Path

import pytest

from utils.mission_storage import (
    _sqlite_version_tuple,
    _supports_vacuum_into,
    create_safe_snapshot,
    validate_archive,
    MissionPaths,
)


class TestSQLiteVersionCheck:
    """Tests for SQLite version detection."""

    def test_version_tuple_returns_integers(self):
        """Version tuple should be integers, not strings."""
        version = _sqlite_version_tuple()

        assert isinstance(version, tuple)
        assert len(version) >= 3
        assert all(isinstance(v, int) for v in version)

    def test_version_matches_sqlite3_module(self):
        """Version tuple should match sqlite3 module version."""
        version = _sqlite_version_tuple()
        expected = tuple(int(x) for x in sqlite3.sqlite_version.split('.'))

        assert version == expected

    def test_supports_vacuum_into_is_boolean(self):
        """VACUUM INTO support check returns boolean."""
        result = _supports_vacuum_into()

        assert isinstance(result, bool)


class TestCreateSafeSnapshot:
    """Tests for SQLite-safe GeoPackage snapshot creation."""

    def test_snapshot_creates_valid_copy(self):
        """Snapshot creates a valid, independent database copy."""
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir) / "source.gpkg"
            dest = Path(tmpdir) / "dest.gpkg"

            # Create minimal valid GeoPackage
            conn = sqlite3.connect(str(source))
            conn.execute("CREATE TABLE test_data (id INTEGER, name TEXT)")
            conn.execute("INSERT INTO test_data VALUES (1, 'mission_alpha')")
            conn.commit()
            conn.close()

            # Create snapshot
            result = create_safe_snapshot(source, dest)

            assert result is True
            assert dest.exists()

            # Verify snapshot is valid and independent
            snap_conn = sqlite3.connect(str(dest))
            row = snap_conn.execute("SELECT * FROM test_data").fetchone()
            snap_conn.close()

            assert row == (1, 'mission_alpha')

    def test_snapshot_source_not_found_raises(self):
        """Missing source file raises FileNotFoundError."""
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir) / "nonexistent.gpkg"
            dest = Path(tmpdir) / "dest.gpkg"

            with pytest.raises(FileNotFoundError):
                create_safe_snapshot(source, dest)

    def test_snapshot_dest_exists_raises(self):
        """Existing destination file raises FileExistsError."""
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir) / "source.gpkg"
            dest = Path(tmpdir) / "dest.gpkg"

            # Create both files
            source.touch()
            dest.touch()

            with pytest.raises(FileExistsError):
                create_safe_snapshot(source, dest)

    def test_snapshot_creates_parent_directory(self):
        """Snapshot creates parent directory if it doesn't exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir) / "source.gpkg"
            dest = Path(tmpdir) / "nested" / "deep" / "dest.gpkg"

            # Create source
            conn = sqlite3.connect(str(source))
            conn.execute("CREATE TABLE t (x INTEGER)")
            conn.close()

            result = create_safe_snapshot(source, dest)

            assert result is True
            assert dest.exists()
            assert dest.parent.exists()

    def test_snapshot_is_consistent_with_uncommitted_writes(self):
        """Snapshot captures data even during active session."""
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir) / "source.gpkg"
            dest = Path(tmpdir) / "dest.gpkg"

            # Create and keep connection open (simulating active session)
            conn = sqlite3.connect(str(source))
            conn.execute("CREATE TABLE positions (device TEXT, lat REAL, lon REAL)")
            conn.execute("INSERT INTO positions VALUES ('DEV001', 52.1, -9.5)")
            conn.commit()

            # Add uncommitted data
            conn.execute("INSERT INTO positions VALUES ('DEV002', 52.2, -9.6)")
            # Note: NOT committing this second insert

            # Snapshot should capture committed data
            result = create_safe_snapshot(source, dest)
            conn.close()

            assert result is True

            # Verify snapshot has committed data
            snap_conn = sqlite3.connect(str(dest))
            count = snap_conn.execute("SELECT COUNT(*) FROM positions").fetchone()[0]
            snap_conn.close()

            # Should have at least the committed row
            assert count >= 1


class TestValidateArchive:
    """Tests for archive validation."""

    def test_missing_path_returns_error(self):
        """None path returns error message."""
        result = validate_archive(None, None)

        assert result is not None
        assert "missing" in result.lower()

    def test_nonexistent_file_returns_error(self):
        """Non-existent file returns error message."""
        with tempfile.TemporaryDirectory() as tmpdir:
            archive = Path(tmpdir) / "nonexistent.zip"
            paths = MissionPaths(
                name="test",
                mission_dir=Path(tmpdir),
                attachments_dir=Path(tmpdir) / "attachments",
                backup_dir=None,
                gpkg_path=Path(tmpdir) / "test.gpkg"
            )

            result = validate_archive(archive, paths)

            assert result is not None
            assert "not found" in result.lower()

    def test_empty_file_returns_error(self):
        """Empty file returns error message."""
        with tempfile.TemporaryDirectory() as tmpdir:
            archive = Path(tmpdir) / "empty.zip"
            archive.touch()  # Create empty file

            paths = MissionPaths(
                name="test",
                mission_dir=Path(tmpdir),
                attachments_dir=Path(tmpdir) / "attachments",
                backup_dir=None,
                gpkg_path=Path(tmpdir) / "test.gpkg"
            )

            result = validate_archive(archive, paths)

            assert result is not None
            assert "empty" in result.lower()

    def test_invalid_zip_returns_error(self):
        """Non-zip file returns error message."""
        with tempfile.TemporaryDirectory() as tmpdir:
            archive = Path(tmpdir) / "fake.zip"
            archive.write_text("not a zip file")

            paths = MissionPaths(
                name="test",
                mission_dir=Path(tmpdir),
                attachments_dir=Path(tmpdir) / "attachments",
                backup_dir=None,
                gpkg_path=Path(tmpdir) / "test.gpkg"
            )

            result = validate_archive(archive, paths)

            assert result is not None
            assert "not a valid zip" in result.lower()

    def test_valid_archive_returns_none(self):
        """Valid archive with expected entry returns None (success)."""
        import zipfile
        with tempfile.TemporaryDirectory() as tmpdir:
            archive = Path(tmpdir) / "valid.zip"
            mission_name = "TestMission"
            gpkg_name = "TestMission.gpkg"

            # Create valid zip with expected structure
            with zipfile.ZipFile(archive, 'w') as zipf:
                zipf.writestr(f"{mission_name}/{gpkg_name}", "dummy content")

            paths = MissionPaths(
                name=mission_name,
                mission_dir=Path(tmpdir) / mission_name,
                attachments_dir=Path(tmpdir) / mission_name / "attachments",
                backup_dir=None,
                gpkg_path=Path(tmpdir) / mission_name / gpkg_name
            )

            result = validate_archive(archive, paths)

            assert result is None  # None means valid

    def test_archive_missing_gpkg_returns_error(self):
        """Archive without expected GeoPackage entry returns error."""
        import zipfile
        with tempfile.TemporaryDirectory() as tmpdir:
            archive = Path(tmpdir) / "incomplete.zip"

            # Create zip without gpkg
            with zipfile.ZipFile(archive, 'w') as zipf:
                zipf.writestr("TestMission/project.qgz", "dummy")

            paths = MissionPaths(
                name="TestMission",
                mission_dir=Path(tmpdir) / "TestMission",
                attachments_dir=Path(tmpdir) / "TestMission" / "attachments",
                backup_dir=None,
                gpkg_path=Path(tmpdir) / "TestMission" / "TestMission.gpkg"
            )

            result = validate_archive(archive, paths)

            assert result is not None
            assert "missing" in result.lower()
