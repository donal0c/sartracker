# -*- coding: utf-8 -*-
"""Tests for release packaging utilities."""

from pathlib import Path
import zipfile

from tools.make_release import create_release_zip


def test_create_release_zip_creates_missing_output_directory(tmp_path):
    plugin_dir = tmp_path / "plugin"
    plugin_dir.mkdir()
    (plugin_dir / "metadata.txt").write_text(
        "[general]\nname=sartracker\nqgisMinimumVersion=3.28\nqgisMaximumVersion=4.99\nversion=0.6.0\n",
        encoding="utf-8",
    )
    (plugin_dir / "icon.png").write_bytes(b"png")

    output_dir = tmp_path / "dist"

    zip_path = create_release_zip(plugin_dir, "0.6.0", output_dir)

    created_zip = Path(zip_path)
    assert created_zip.exists()
    with zipfile.ZipFile(created_zip) as archive:
        assert "sartracker/metadata.txt" in archive.namelist()
