# -*- coding: utf-8 -*-
"""Unit tests for breadcrumb preprocessing helpers."""

from sartracker.providers import tasks as breadcrumb_tasks
from sartracker.providers.tasks import prepare_breadcrumb_segments


def _pos(ts, lat, lon, device_id="team1", name="Team 1"):
    return {
        "device_id": device_id,
        "name": name,
        "ts": ts,
        "lat": lat,
        "lon": lon,
    }


def test_prepare_breadcrumb_segments_rejects_null_island():
    positions = [
        _pos("2024-01-01T00:00:00Z", 51.0, -9.0),
        _pos("2024-01-01T00:01:00Z", 0.0, 0.0),
        _pos("2024-01-01T00:02:00Z", 51.1, -9.1),
    ]

    payload = prepare_breadcrumb_segments(positions, time_gap_minutes=5)

    assert payload is not None
    segments = payload["segments"]
    assert len(segments) == 1
    points = segments[0]["points"]
    assert len(points) == 2
    assert all(
        not (abs(point["lat"]) < 0.0001 and abs(point["lon"]) < 0.0001)
        for point in points
    )


def test_prepare_breadcrumb_segments_sparse_updates_create_pairs():
    positions = [
        _pos("2024-01-01T00:00:00Z", 51.0, -9.0),
        _pos("2024-01-01T00:10:00Z", 51.1, -9.1),
    ]

    payload = prepare_breadcrumb_segments(positions, time_gap_minutes=5)

    assert payload is not None
    segments = payload["segments"]
    assert len(segments) == 1
    assert len(segments[0]["points"]) == 2


def test_prepare_breadcrumb_segments_truncates_input(monkeypatch):
    monkeypatch.setattr(breadcrumb_tasks, "MAX_BREADCRUMB_POSITIONS", 2, raising=False)

    positions = [
        _pos("2024-01-01T00:00:00Z", 51.0, -9.0),
        _pos("2024-01-01T00:01:00Z", 51.01, -9.01),
        _pos("2024-01-01T00:02:00Z", 51.02, -9.02),
    ]

    payload = prepare_breadcrumb_segments(positions, time_gap_minutes=5)

    assert payload is not None
    segments = payload["segments"]
    assert len(segments) == 1
    points = segments[0]["points"]
    assert [point["ts"] for point in points] == [
        "2024-01-01T00:01:00Z",
        "2024-01-01T00:02:00Z",
    ]
