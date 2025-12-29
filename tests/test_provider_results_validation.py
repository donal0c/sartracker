# -*- coding: utf-8 -*-
"""
Tests for provider result sanitization helpers.

These run headless (no QGIS) and exercise validation of provider payloads
before they reach QGIS layer update code.
"""

try:
    import pytest
except ImportError:  # pragma: no cover - fallback minimal harness
    class pytest:  # type: ignore
        @staticmethod
        def raises(exc):
            raise RuntimeError("pytest required for these tests")

from sartracker.utils.provider_results import sanitize_provider_results, filter_positions, filter_devices


def test_filter_positions_keeps_valid_and_coerces_lat_lon():
    positions = [
        {"device_id": "dev1", "name": "alpha", "ts": "2025-01-01T00:00:00Z", "lat": "52.0", "lon": "-9.5"},
        {"device_id": "dev2", "name": "beta", "ts": "2025-01-01T00:01:00Z", "lat": 53.1, "lon": -8.2},
    ]
    cleaned, dropped = filter_positions(positions)
    assert dropped == 0
    assert len(cleaned) == 2
    assert isinstance(cleaned[0]["lat"], float)
    assert isinstance(cleaned[0]["lon"], float)


def test_filter_positions_drops_invalid_records():
    positions = [
        {"device_id": "dev1", "name": "alpha", "ts": "2025-01-01T00:00:00Z", "lat": 95.0, "lon": 10.0},  # bad lat
        {"device_id": "", "name": "beta", "ts": "2025-01-01T00:01:00Z", "lat": 50.0, "lon": 10.0},       # missing id
        {"device_id": "dev2", "name": "gamma", "ts": "not-a-ts", "lat": 50.0, "lon": 10.0},              # bad ts
        "not-a-dict",
    ]
    cleaned, dropped = filter_positions(positions)
    assert cleaned == []
    assert dropped == 4


def test_filter_devices_drops_missing_ids():
    devices = [
        {"device_id": "dev1", "name": "alpha"},
        {"name": "beta"},  # missing id
        "not-a-dict",
    ]
    cleaned, dropped = filter_devices(devices)
    assert len(cleaned) == 1
    assert cleaned[0]["device_id"] == "dev1"
    assert dropped == 2


def test_filter_positions_rejects_null_island():
    positions = [
        {"device_id": "dev1", "name": "alpha", "ts": "2025-01-01T00:00:00Z", "lat": 0.0, "lon": 0.0},
    ]
    cleaned, dropped = filter_positions(positions)
    assert cleaned == []
    assert dropped == 1


def test_sanitize_provider_results_applies_filters_and_counts():
    results = {
        "current": [
            {"device_id": "dev1", "name": "a", "ts": "2025-01-01T00:00:00Z", "lat": 10.0, "lon": 20.0},
            {"device_id": "dev2", "name": "b", "ts": "t", "lat": 999, "lon": 20.0},  # invalid
        ],
        "breadcrumbs": [
            {"device_id": "dev1", "name": "a", "ts": "2025-01-01T00:00:00Z", "lat": 11.0, "lon": 21.0},
            {"device_id": "dev1", "name": "a", "ts": "t", "lat": None, "lon": 21.0},  # invalid
        ],
        "devices": [{"device_id": "dev1"}, {"name": "missing"}],
        "breadcrumb_processing": {"segments": 1},
    }

    sanitized, dropped = sanitize_provider_results(results)

    assert len(sanitized["current"]) == 1
    assert len(sanitized["breadcrumbs"]) == 1
    assert len(sanitized["devices"]) == 1
    assert sanitized["breadcrumb_processing"] == {"segments": 1}

    assert dropped["current"] == 1
    assert dropped["breadcrumbs"] == 1
    assert dropped["devices"] == 1


def test_sanitize_provider_results_handles_none():
    sanitized, dropped = sanitize_provider_results(None)
    assert sanitized["current"] == []
    assert sanitized["breadcrumbs"] == []
    assert sanitized["devices"] == []
    assert dropped["current"] == 0
    assert dropped["breadcrumbs"] == 0
    assert dropped["devices"] == 0


if __name__ == "__main__":
    # Minimal self-test runner to avoid pytest dependency in constrained envs
    test_filter_positions_keeps_valid_and_coerces_lat_lon()
    test_filter_positions_drops_invalid_records()
    test_filter_devices_drops_missing_ids()
    test_filter_positions_rejects_null_island()
    test_sanitize_provider_results_applies_filters_and_counts()
    test_sanitize_provider_results_handles_none()
    print("test_provider_results_validation: PASS")
