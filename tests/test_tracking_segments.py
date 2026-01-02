# -*- coding: utf-8 -*-
"""Unit tests for pure-Python tracking data helpers."""

import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

# Provide lightweight package stubs so importing controllers.* doesn't pull heavy QGIS deps
if "controllers" not in sys.modules:
    controllers_pkg = types.ModuleType("controllers")
    controllers_pkg.__path__ = [str(ROOT / "controllers")]
    sys.modules["controllers"] = controllers_pkg

if "controllers.layer_managers" not in sys.modules:
    lm_pkg = types.ModuleType("controllers.layer_managers")
    lm_pkg.__path__ = [str(ROOT / "controllers" / "layer_managers")]
    sys.modules["controllers.layer_managers"] = lm_pkg

from controllers.layer_managers.tracking_segments import (  # noqa: E402  pylint: disable=wrong-import-position
    build_segments_from_positions,
    parse_iso_timestamp,
    sanitize_breadcrumb_positions,
    sanitize_current_positions,
    validate_processed_segments,
)


def test_sanitize_breadcrumb_positions_valid_payload():
    positions = [
        {"device_id": "alpha", "name": "Alpha", "ts": "2024-01-01T00:00:00Z", "lat": "51.5", "lon": "-9.5"},
        {"device_id": "alpha", "name": "Alpha", "ts": "2024-01-01T00:05:00Z", "lat": 51.5005, "lon": -9.5005},
    ]

    sanitized = sanitize_breadcrumb_positions(positions)

    assert len(sanitized.valid) == 2
    assert sanitized.invalid_count == 0
    assert sanitized.valid[0]["lat"] == pytest.approx(51.5)
    assert sanitized.valid[1]["lon"] == pytest.approx(-9.5005)


def test_sanitize_breadcrumb_positions_skips_bad_latitude():
    positions = [
        {"device_id": "alpha", "name": "Alpha", "ts": "2024-01-01T00:00:00Z", "lat": "120", "lon": "0"},
    ]

    result = sanitize_breadcrumb_positions(positions)

    assert len(result.valid) == 0
    assert result.invalid_count == 1
    assert "latitude" in (result.last_error or "")


def test_sanitize_breadcrumb_positions_type_error():
    with pytest.raises(ValueError):
        sanitize_breadcrumb_positions("not-a-list")


def test_sanitize_current_positions_partial_failure():
    positions = [
        {"device_id": "alpha", "name": "Alpha", "ts": "2024-01-01T00:00:00Z", "lat": "51.5", "lon": "-9.5"},
        {"device_id": "", "name": "bad", "ts": "2024-01-01T00:01:00Z", "lat": "51.6", "lon": "-9.6"},
    ]

    result = sanitize_current_positions(positions)

    assert len(result.valid) == 1
    assert result.invalid_count == 1
    assert result.valid[0]["device_id"] == "alpha"


def test_build_segments_from_positions_honors_time_gap():
    base = "2024-01-01T00:{:02d}:00Z"
    positions = [
        {"device_id": "team1", "name": "Team 1", "ts": base.format(0), "lat": 51.1, "lon": -9.1},
        {"device_id": "team1", "name": "Team 1", "ts": base.format(2), "lat": 51.1005, "lon": -9.1005},
        {"device_id": "team1", "name": "Team 1", "ts": base.format(10), "lat": 51.2, "lon": -9.2},
        {"device_id": "team1", "name": "Team 1", "ts": base.format(12), "lat": 51.2005, "lon": -9.2005},
    ]

    segments = build_segments_from_positions(positions, time_gap_minutes=5)

    assert len(segments) == 2
    assert all(len(seg["points"]) == 2 for seg in segments)
    assert segments[0]["points"][0]["lon"] == pytest.approx(-9.1)
    assert segments[1]["points"][1]["lat"] == pytest.approx(51.2005)


def test_validate_processed_segments_filters_invalid_entries():
    payload = {
        "time_gap_minutes": 5,
        "segments": [
            {
                "device_id": "ok",
                "name": "OK",
                "points": [
                    {"lat": 51.0, "lon": -9.0},
                    {"lat": 51.1, "lon": -9.1},
                ],
            },
            {
                "device_id": "",
                "name": "bad",
                "points": [{"lat": 0, "lon": 0}, {"lat": 0, "lon": 0}],
            },
        ],
    }

    validated = validate_processed_segments(payload, requested_gap_minutes=5)

    assert isinstance(validated, list)
    assert len(validated) == 1
    assert validated[0]["device_id"] == "ok"


def test_validate_processed_segments_rejects_null_island():
    payload = {
        "time_gap_minutes": 5,
        "segments": [
            {
                "device_id": "bad",
                "name": "Bad",
                "points": [
                    {"lat": 0, "lon": 0},
                    {"lat": 0.0, "lon": 0.0},
                ],
            },
            {
                "device_id": "ok",
                "name": "OK",
                "points": [
                    {"lat": 51.0, "lon": -9.0},
                    {"lat": 51.1, "lon": -9.1},
                ],
            },
        ],
    }

    validated = validate_processed_segments(payload, requested_gap_minutes=5)

    assert len(validated) == 1
    assert validated[0]["device_id"] == "ok"


def test_parse_iso_timestamp_handles_z_suffix():
    dt = parse_iso_timestamp("2024-01-01T00:00:00Z")
    assert dt.tzinfo is not None
    assert dt.isoformat().startswith("2024-01-01T00:00:00")
