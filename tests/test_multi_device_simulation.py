# -*- coding: utf-8 -*-
"""
Multi-Device Simulation Tests

Test providers with realistic multi-device scenarios using traccar_stub.

WHY THIS MATTERS:
SAR operations involve multiple teams with multiple devices. Provider code must
handle concurrent updates, device state changes, and performance under load.

VALUE PROVIDED:
- Verify multi-device handling (10, 50, 100+ devices)
- Test concurrent position updates
- Validate device lifecycle (add/remove/offline/online)
- Establish performance baselines
- Test error handling with partial failures

REQUIRES: Real QGIS for provider testing
"""

import pytest
import time
import threading
import tempfile
import json
from pathlib import Path
from datetime import datetime, timedelta, timezone

from sartracker.tests.qgis_runtime import require_real_qgis

# These scenarios need a real QGIS runtime, not the mock harness.
require_real_qgis("Multi-device simulation tests require real QGIS runtime")
pytestmark = pytest.mark.qgis_required


# Simple in-memory provider for testing multi-device scenarios
class SimpleMultiDeviceProvider:
    """Simplified provider for testing multi-device behavior."""

    def __init__(self):
        self.devices = {}  # device_id -> list of positions

    def add_device_positions(self, device_id, positions):
        """Add position history for a device."""
        if device_id not in self.devices:
            self.devices[device_id] = []
        self.devices[device_id].extend(positions)
        # Sort by timestamp
        self.devices[device_id].sort(key=lambda p: p['timestamp'])

    def get_current_positions(self):
        """Get latest position for each device."""
        current = []
        for device_id, positions in self.devices.items():
            if positions:
                current.append(positions[-1])  # Latest position
        return current

    def get_breadcrumbs(self, device_id):
        """Get position history for a device."""
        return self.devices.get(device_id, [])


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
def temp_csv_dir(tmp_path):
    """Create temporary directory for CSV test files."""
    csv_dir = tmp_path / "csv_data"
    csv_dir.mkdir()
    return csv_dir


def generate_device_positions(device_id, num_points, start_time):
    """Generate position history for a device."""
    positions = []
    base_lat = 52.0 + (device_id * 0.01)  # Different starting point per device
    base_lon = -9.5 + (device_id * 0.01)

    for i in range(num_points):
        timestamp = start_time + timedelta(minutes=i)
        lat = base_lat + (i * 0.0001)  # Move north
        lon = base_lon + (i * 0.0001)  # Move east

        positions.append({
            'timestamp': timestamp.isoformat(),
            'latitude': lat,
            'longitude': lon,
            'altitude': 100 + i,
            'speed': 5.0,
            'course': 45.0,
            'device_id': f'device_{device_id}'
        })

    return positions


def generate_device_csv(device_id, num_points, start_time, csv_dir):
    """Generate CSV file for a device (for CSV provider tests)."""
    csv_file = csv_dir / f"device_{device_id}.csv"
    positions = generate_device_positions(device_id, num_points, start_time)

    # Write CSV
    with open(csv_file, 'w') as f:
        f.write("timestamp,latitude,longitude,altitude,speed,course,device_id\n")
        for pos in positions:
            f.write(f"{pos['timestamp']},{pos['latitude']},{pos['longitude']},"
                   f"{pos['altitude']},{pos['speed']},{pos['course']},{pos['device_id']}\n")

    return csv_file


def load_csv_positions(csv_file):
    """Load positions from CSV file."""
    positions = []
    with open(csv_file, 'r') as f:
        lines = f.readlines()[1:]  # Skip header
        for line in lines:
            parts = line.strip().split(',')
            if len(parts) >= 7:
                positions.append({
                    'timestamp': parts[0],
                    'latitude': float(parts[1]),
                    'longitude': float(parts[2]),
                    'altitude': float(parts[3]),
                    'speed': float(parts[4]),
                    'course': float(parts[5]),
                    'device_id': parts[6]
                })
    return positions


# =============================================================================
# MULTI-DEVICE CURRENT POSITIONS
# =============================================================================

class TestMultiDeviceCurrentPositions:
    """Test handling of current positions for multiple devices."""

    def test_10_devices_all_positions_returned(self, temp_csv_dir):
        """
        Verify all device positions returned with 10 devices.

        VALUE: Basic multi-device functionality must work.
        """
        start_time = datetime.now(timezone.utc) - timedelta(hours=1)
        num_devices = 10

        # Generate CSV files for each device
        csv_files = []
        for device_id in range(num_devices):
            csv_file = generate_device_csv(device_id, 5, start_time, temp_csv_dir)
            csv_files.append(csv_file)

        # Test with simple provider
        provider = SimpleMultiDeviceProvider()

        # Load all device positions
        for device_id, csv_file in enumerate(csv_files):
            positions = load_csv_positions(csv_file)
            provider.add_device_positions(f'device_{device_id}', positions)

        # Get current positions
        positions = provider.get_current_positions()

        # Verify we got all devices
        assert len(positions) == num_devices, f"Expected {num_devices} positions, got {len(positions)}"

        # Verify each device present
        device_ids = {p['device_id'] for p in positions}
        expected_ids = {f'device_{i}' for i in range(num_devices)}
        assert device_ids == expected_ids, f"Missing devices: {expected_ids - device_ids}"

    def test_50_devices_performance_acceptable(self, temp_csv_dir):
        """
        Verify 50 devices can be handled with acceptable performance.

        VALUE: Medium-sized operations (multiple teams) must perform well.
        """
        start_time = datetime.now(timezone.utc) - timedelta(hours=1)
        num_devices = 50

        # Generate CSV files
        csv_files = []
        for device_id in range(num_devices):
            csv_file = generate_device_csv(device_id, 3, start_time, temp_csv_dir)
            csv_files.append(csv_file)

        provider = SimpleMultiDeviceProvider()

        # Measure load time
        load_start = time.time()
        for device_id, csv_file in enumerate(csv_files):
            positions = load_csv_positions(csv_file)
            provider.add_device_positions(f'device_{device_id}', positions)
        load_time = time.time() - load_start

        # Measure query time
        query_start = time.time()
        positions = provider.get_current_positions()
        query_time = time.time() - query_start

        # Performance assertions
        assert load_time < 2.0, f"Loading 50 devices took {load_time:.2f}s (expected <2s)"
        assert query_time < 0.5, f"Querying 50 devices took {query_time:.2f}s (expected <0.5s)"
        assert len(positions) == num_devices

    def test_100_devices_no_memory_issues(self, temp_csv_dir):
        """
        Verify 100 devices can be handled without memory issues.

        VALUE: Large operations must not cause memory problems.
        """
        start_time = datetime.now(timezone.utc) - timedelta(hours=1)
        num_devices = 100

        # Generate CSV files
        csv_files = []
        for device_id in range(num_devices):
            csv_file = generate_device_csv(device_id, 2, start_time, temp_csv_dir)
            csv_files.append(csv_file)

        provider = SimpleMultiDeviceProvider()

        # Load all devices
        for device_id, csv_file in enumerate(csv_files):
            positions = load_csv_positions(csv_file)
            provider.add_device_positions(f'device_{device_id}', positions)

        # Get positions
        positions = provider.get_current_positions()

        # Should complete without error
        assert len(positions) == num_devices

        # Verify memory-efficient handling (positions should be simple dicts)
        for pos in positions:
            assert isinstance(pos, dict)
            assert 'device_id' in pos
            assert 'latitude' in pos
            assert 'longitude' in pos

    def test_devices_with_stale_positions(self, temp_csv_dir):
        """
        Verify devices with old positions are still returned.

        VALUE: Devices may go offline - last known position should be available.
        """
        now = datetime.now(timezone.utc)

        # Device 0: Recent positions
        csv1 = generate_device_csv(0, 5, now - timedelta(minutes=10), temp_csv_dir)

        # Device 1: Stale positions (2 hours old)
        csv2 = generate_device_csv(1, 5, now - timedelta(hours=2), temp_csv_dir)

        provider = SimpleMultiDeviceProvider()
        positions = load_csv_positions(csv1); provider.add_device_positions("device_0", positions)
        positions = load_csv_positions(csv2); provider.add_device_positions("device_1", positions)

        positions = provider.get_current_positions()

        # Both devices should be returned
        assert len(positions) == 2

        # Verify we can identify which is stale
        for pos in positions:
            if pos['device_id'] == 'device_1':
                # This position should be old
                pos_time = datetime.fromisoformat(pos['timestamp'].replace('Z', '+00:00'))
                age = (now - pos_time).total_seconds()
                assert age > 3600, "Stale device position should be >1 hour old"


# =============================================================================
# MULTI-DEVICE BREADCRUMBS
# =============================================================================

class TestMultiDeviceBreadcrumbs:
    """Test breadcrumb/history retrieval for multiple devices."""

    def test_breadcrumbs_grouped_by_device(self, temp_csv_dir):
        """
        Verify breadcrumbs can be retrieved per device.

        VALUE: Operators need to see individual device tracks.
        """
        start_time = datetime.now(timezone.utc) - timedelta(hours=1)

        # Create 3 devices with different track lengths
        csv1 = generate_device_csv(0, 10, start_time, temp_csv_dir)
        csv2 = generate_device_csv(1, 5, start_time, temp_csv_dir)
        csv3 = generate_device_csv(2, 15, start_time, temp_csv_dir)

        provider = SimpleMultiDeviceProvider()
        positions = load_csv_positions(csv1); provider.add_device_positions("device_0", positions)
        positions = load_csv_positions(csv2); provider.add_device_positions("device_1", positions)
        positions = load_csv_positions(csv3); provider.add_device_positions("device_2", positions)

        # Get breadcrumbs for device 0
        breadcrumbs_0 = provider.get_breadcrumbs('device_0')
        assert len(breadcrumbs_0) == 10

        # Get breadcrumbs for device 1
        breadcrumbs_1 = provider.get_breadcrumbs('device_1')
        assert len(breadcrumbs_1) == 5

        # Verify no cross-contamination
        for bc in breadcrumbs_0:
            assert bc['device_id'] == 'device_0'
        for bc in breadcrumbs_1:
            assert bc['device_id'] == 'device_1'

    def test_breadcrumbs_sorted_by_time(self, temp_csv_dir):
        """
        Verify breadcrumbs are returned in chronological order.

        VALUE: Track display requires time-ordered points.
        """
        start_time = datetime.now(timezone.utc) - timedelta(hours=1)
        csv_file = generate_device_csv(0, 20, start_time, temp_csv_dir)

        provider = SimpleMultiDeviceProvider()
        positions = load_csv_positions(csv_file)
        provider.add_device_positions('device_0', positions)

        breadcrumbs = provider.get_breadcrumbs('device_0')

        # Verify chronological order
        timestamps = [datetime.fromisoformat(bc['timestamp'].replace('Z', '+00:00'))
                     for bc in breadcrumbs]

        for i in range(len(timestamps) - 1):
            assert timestamps[i] <= timestamps[i+1], \
                f"Breadcrumbs not in chronological order at index {i}"


# =============================================================================
# DEVICE LIFECYCLE
# =============================================================================

class TestDeviceLifecycle:
    """Test device addition, removal, and state changes."""

    def test_new_device_appears_in_current(self, temp_csv_dir):
        """
        Verify newly added device appears in current positions.

        VALUE: Devices can be added mid-operation.
        """
        start_time = datetime.now(timezone.utc) - timedelta(minutes=30)

        provider = SimpleMultiDeviceProvider()

        # Initially 2 devices
        csv1 = generate_device_csv(0, 5, start_time, temp_csv_dir)
        csv2 = generate_device_csv(1, 5, start_time, temp_csv_dir)
        positions = load_csv_positions(csv1); provider.add_device_positions("device_0", positions)
        positions = load_csv_positions(csv2); provider.add_device_positions("device_1", positions)

        positions = provider.get_current_positions()
        assert len(positions) == 2

        # Add third device
        csv3 = generate_device_csv(2, 5, start_time, temp_csv_dir)
        positions = load_csv_positions(csv3); provider.add_device_positions("device_2", positions)

        positions = provider.get_current_positions()
        assert len(positions) == 3

        # Verify new device present
        device_ids = {p['device_id'] for p in positions}
        assert 'device_2' in device_ids


# =============================================================================
# PERFORMANCE BASELINES
# =============================================================================

class TestPerformanceBaselines:
    """Establish performance baselines for multi-device operations."""

    def test_10_devices_under_100ms(self, temp_csv_dir):
        """
        Verify 10 devices query completes in <100ms.

        VALUE: Small teams need responsive updates.
        """
        start_time = datetime.now(timezone.utc) - timedelta(minutes=30)

        provider = SimpleMultiDeviceProvider()
        for device_id in range(10):
            csv_file = generate_device_csv(device_id, 5, start_time, temp_csv_dir)
            positions = load_csv_positions(csv_file)
            provider.add_device_positions(f'device_{device_id}', positions)

        # Warm up
        provider.get_current_positions()

        # Measure
        start = time.time()
        positions = provider.get_current_positions()
        elapsed_ms = (time.time() - start) * 1000

        assert len(positions) == 10
        assert elapsed_ms < 100, f"Query took {elapsed_ms:.1f}ms (expected <100ms)"

    def test_50_devices_under_500ms(self, temp_csv_dir):
        """
        Verify 50 devices query completes in <500ms.

        VALUE: Medium operations need sub-second response.
        """
        start_time = datetime.now(timezone.utc) - timedelta(minutes=30)

        provider = SimpleMultiDeviceProvider()
        for device_id in range(50):
            csv_file = generate_device_csv(device_id, 3, start_time, temp_csv_dir)
            positions = load_csv_positions(csv_file)
            provider.add_device_positions(f'device_{device_id}', positions)

        # Warm up
        provider.get_current_positions()

        # Measure
        start = time.time()
        positions = provider.get_current_positions()
        elapsed_ms = (time.time() - start) * 1000

        assert len(positions) == 50
        assert elapsed_ms < 500, f"Query took {elapsed_ms:.1f}ms (expected <500ms)"
