# -*- coding: utf-8 -*-
"""Regression tests for WGS84 direction labels in SAR UI."""

from pathlib import Path

import pytest

from utils import coordinates


def test_format_wgs84_degrees_uses_west_for_negative_longitude():
    """Ireland longitudes must render as W, not E."""
    result = coordinates.format_wgs84_degrees(52.274681, -9.530912, precision=6)
    assert result == "52.274681°N, 9.530912°W"


def test_format_wgs84_degrees_rejects_infinite_longitude():
    """Life-safety: reject non-finite inputs."""
    with pytest.raises(ValueError, match="Infinity"):
        coordinates.format_wgs84_degrees(53.0, float("inf"), precision=6)


def test_ui_files_do_not_hardcode_east_for_longitude():
    """Regression guard for SAR-kvl7 hardcoded °E bug."""
    project_root = Path(__file__).resolve().parent.parent
    files = [
        project_root / "controllers" / "coordinates_controller.py",
        project_root / "ui" / "coordinate_converter_dialog.py",
        project_root / "ui" / "marker_dialog.py",
    ]
    forbidden_patterns = [
        "wgs84_point.x():10.6f}°E",
        "Longitude: {lon:.6f}°E",
        "Longitude: {wgs84_point.x():.6f}°E",
        "{self.lon:.6f}°E",
    ]

    for file_path in files:
        content = file_path.read_text(encoding="utf-8")
        for pattern in forbidden_patterns:
            assert pattern not in content, f"Hardcoded east direction in {file_path}: {pattern}"
