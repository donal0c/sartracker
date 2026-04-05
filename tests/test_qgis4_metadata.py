# -*- coding: utf-8 -*-
"""Tests for QGIS 4 compatibility metadata validation."""

from pathlib import Path

from tools.make_release import validate_plugin_metadata


def _write_metadata(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8")


def test_validate_plugin_metadata_rejects_missing_qgis4_max_version(tmp_path):
    plugin_dir = tmp_path / "plugin"
    plugin_dir.mkdir()
    _write_metadata(
        plugin_dir / "metadata.txt",
        """[general]
name=sartracker
qgisMinimumVersion=3.28
version=0.6.0
supportsQt6=yes
""",
    )

    is_valid, errors = validate_plugin_metadata(plugin_dir)

    assert not is_valid
    assert any("qgisMaximumVersion=4.99" in error for error in errors)
    assert any("supportsQt6" in error for error in errors)


def test_validate_plugin_metadata_accepts_explicit_qgis4_range(tmp_path):
    plugin_dir = tmp_path / "plugin"
    plugin_dir.mkdir()
    _write_metadata(
        plugin_dir / "metadata.txt",
        """[general]
name=sartracker
qgisMinimumVersion=3.28
qgisMaximumVersion=4.99
version=0.6.0
""",
    )

    is_valid, errors = validate_plugin_metadata(plugin_dir)

    assert is_valid
    assert errors == []
