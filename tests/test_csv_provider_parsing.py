# -*- coding: utf-8 -*-
import os
import shutil
import tempfile

import pytest

from sartracker.providers.csv import FileCSVProvider


@pytest.fixture
def temp_dir():
    """Create temporary directory for test CSV files."""
    temp_path = tempfile.mkdtemp()
    yield temp_path
    shutil.rmtree(temp_path)


def _write_csv(path, rows, encoding="utf-8"):
    lines = [
        "Device:,test_device,,,,,,",
        "Valid,Time,Latitude,Longitude,Altitude,Speed,Address,Attributes",
    ]
    lines.extend(rows)
    content = "\n".join(lines) + "\n"
    with open(path, "w", encoding=encoding) as handle:
        handle.write(content)


def test_csv_provider_out_of_order_timestamps_current_uses_latest(temp_dir):
    csv_path = os.path.join(temp_dir, "device.csv")
    rows = [
        "true,2025-11-15T14:31:00Z,52.1000,-9.4000,100 m,5.0 kn,,",
        "true,2025-11-15T14:35:00Z,52.2000,-9.5000,101 m,6.0 kn,,",
        "true,2025-11-15T14:30:00Z,52.0000,-9.3000,99 m,4.0 kn,,",
    ]
    _write_csv(csv_path, rows)

    provider = FileCSVProvider(csv_path)
    current = provider.get_current()

    assert len(current) == 1
    assert current[0]["ts"] == "2025-11-15T14:35:00Z"
    assert current[0]["lat"] == 52.2
    assert current[0]["lon"] == -9.5


def test_csv_provider_devices_use_timezone_aware_latest(temp_dir):
    csv_path = os.path.join(temp_dir, "device.csv")
    rows = [
        "true,2025-11-15T14:00:00+01:00,52.1000,-9.4000,100 m,5.0 kn,,",
        "true,2025-11-15T13:30:00Z,52.2000,-9.5000,101 m,6.0 kn,,",
    ]
    _write_csv(csv_path, rows)

    provider = FileCSVProvider(csv_path)
    devices = provider.get_devices()

    assert len(devices) == 1
    assert devices[0]["last_update"] == "2025-11-15T13:30:00Z"


def test_csv_provider_invalid_positions_and_bad_altitude_speed(temp_dir):
    csv_path = os.path.join(temp_dir, "device.csv")
    rows = [
        "true,2025-11-15T14:30:00Z,52.1000,-9.4000,bad m,bad kn,,",
        "true,2025-11-15T14:31:00Z,91.0000,-9.4000,100 m,5.0 kn,,",
        "true,2025-11-15T14:32:00Z,52.1000,181.0000,100 m,5.0 kn,,",
        "true,2025-11-15T14:33:00Z,nan,-9.4000,100 m,5.0 kn,,",
        "true,2025-11-15T14:34:00Z,0.0000,0.0000,100 m,5.0 kn,,",
    ]
    _write_csv(csv_path, rows)

    provider = FileCSVProvider(csv_path)
    breadcrumbs = provider.get_breadcrumbs()

    assert len(breadcrumbs) == 1
    assert breadcrumbs[0]["altitude"] is None
    assert breadcrumbs[0]["speed"] is None


def test_csv_provider_bom_header_parsed(temp_dir):
    csv_path = os.path.join(temp_dir, "device.csv")
    rows = [
        "true,2025-11-15T14:30:00Z,52.1000,-9.4000,100 m,5.0 kn,,",
    ]
    _write_csv(csv_path, rows, encoding="utf-8-sig")

    provider = FileCSVProvider(csv_path)
    current = provider.get_current()

    assert len(current) == 1
    assert current[0]["device_id"] == "test_device"


def test_csv_provider_cancellation_stops_parse(temp_dir):
    csv_path = os.path.join(temp_dir, "device.csv")
    rows = []
    for i in range(50):
        ts = f"2025-11-15T14:{30 + (i // 60):02d}:{i % 60:02d}Z"
        lat = 52.0 + (i * 0.0001)
        lon = -9.0 - (i * 0.0001)
        rows.append(f"true,{ts},{lat:.4f},{lon:.4f},100 m,5.0 kn,,")
    _write_csv(csv_path, rows)

    provider = FileCSVProvider(csv_path)
    calls = {"count": 0}

    def cancel_cb():
        calls["count"] += 1
        return calls["count"] > 10

    breadcrumbs = provider.get_breadcrumbs(cancel_cb=cancel_cb)

    assert breadcrumbs == []
    assert calls["count"] > 0
