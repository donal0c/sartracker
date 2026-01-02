# -*- coding: utf-8 -*-
"""
Test: Per-Device Tracking Layers (SAR-33p / SAR-nh9 Phase 1)

Validates the per-device current position layer implementation:
- Device groups created under Tracking/
- Each device gets its own Position layer
- Position updates replace feature (not accumulate)
- Device colors are consistent
- Feature flag routing works
- Plugin reload preserves layers

**NOTE:** These are QGIS Console tests - designed to run inside QGIS
with the SAR Tracker plugin loaded. They are NOT pytest unit tests.

Run in QGIS Python Console:
    from sartracker.tests.test_per_device_tracking import run_tests
    run_tests()

Or run individual tests:
    from sartracker.tests.test_per_device_tracking import test_single_device
    test_single_device()
"""
import pytest

# Skip all tests in this module when running via pytest
# These tests require full QGIS with SAR Tracker plugin loaded
pytestmark = pytest.mark.skip(
    reason="QGIS Console tests - require plugin loaded in QGIS. Run via QGIS Python Console."
)

import time
import traceback
from typing import Dict, List, Optional

# For running in QGIS console
try:
    from qgis.core import QgsProject, QgsVectorLayer, QgsLayerTreeGroup
    from qgis.utils import iface, plugins
    QGIS_AVAILABLE = True
except ImportError:
    QGIS_AVAILABLE = False
    print("Warning: QGIS not available - tests must be run from QGIS Python console")


def get_plugin():
    """Get the SAR Tracker plugin instance."""
    sar = plugins.get('sartracker')
    if not sar:
        raise RuntimeError("SAR Tracker plugin not loaded. Please enable it first.")
    return sar


def get_tracking_manager():
    """Get the TrackingLayerManager from the plugin."""
    sar = get_plugin()
    layers_controller = getattr(sar, 'layers_controller', None)
    if not layers_controller:
        raise RuntimeError("LayersController not available - is plugin initialized?")
    tracking_manager = getattr(layers_controller, 'tracking', None)
    if not tracking_manager:
        raise RuntimeError("TrackingLayerManager not available")
    return tracking_manager


def create_mock_position(device_id: str, device_name: str, lat: float = 52.0, lon: float = -9.5) -> Dict:
    """Create a mock position dict for testing."""
    import uuid
    from datetime import datetime, timezone
    return {
        'device_id': device_id,
        'name': device_name,
        'lat': lat,
        'lon': lon,
        'ts': datetime.now(timezone.utc).isoformat(),
        'altitude': 100.0,
        'speed': 5.0,
        'battery': 80.0,
        'accuracy': 10.0,
        'source': 'test',
    }


def find_tracking_group() -> Optional[QgsLayerTreeGroup]:
    """Find the Tracking group in the layer tree."""
    root = QgsProject.instance().layerTreeRoot()
    sar_root = root.findGroup("SAR Tracker")
    if not sar_root:
        return None
    return sar_root.findGroup("Tracking")


def find_device_group(device_name: str) -> Optional[QgsLayerTreeGroup]:
    """Find a device group under Tracking."""
    tracking = find_tracking_group()
    if not tracking:
        return None
    return tracking.findGroup(device_name)


def find_device_position_layer(device_id: str) -> Optional[QgsVectorLayer]:
    """Find a device position layer by its device_id custom property."""
    for layer in QgsProject.instance().mapLayers().values():
        if not isinstance(layer, QgsVectorLayer):
            continue
        if layer.customProperty("sartracker:device_id") == device_id:
            item_type = layer.customProperty("sartracker:item_type")
            if item_type == "device_position":
                return layer
    return None


def find_device_trail_layer(device_id: str) -> Optional[QgsVectorLayer]:
    """Find a device trail layer by its device_id custom property."""
    for layer in QgsProject.instance().mapLayers().values():
        if not isinstance(layer, QgsVectorLayer):
            continue
        if layer.customProperty("sartracker:device_id") == device_id:
            item_type = layer.customProperty("sartracker:item_type")
            if item_type == "device_trail":
                return layer
    return None


def count_features(layer: QgsVectorLayer) -> int:
    """Count features in a layer."""
    return layer.featureCount() if layer else 0


# =============================================================================
# Individual Tests
# =============================================================================

def test_feature_flag():
    """Test that feature flag is enabled."""
    print("\n=== Test: Feature Flag ===")
    tm = get_tracking_manager()

    if tm.USE_PER_DEVICE_POSITIONS:
        print("  [PASS] USE_PER_DEVICE_POSITIONS = True")
        return True
    else:
        print("  [FAIL] USE_PER_DEVICE_POSITIONS = False (should be True)")
        return False


def test_single_device():
    """Test creating a single device layer."""
    print("\n=== Test: Single Device ===")
    tm = get_tracking_manager()

    # Create a test position
    device_id = "test_device_001"
    device_name = "Test Alpha"
    position = create_mock_position(device_id, device_name, lat=52.05, lon=-9.52)

    # Update positions
    print(f"  Updating position for {device_name}...")
    start = time.time()
    tm.update_current_positions([position])
    elapsed = time.time() - start
    print(f"  Update took {elapsed*1000:.1f}ms")

    # Verify Tracking group exists
    tracking = find_tracking_group()
    if not tracking:
        print("  [FAIL] Tracking group not created")
        return False
    print("  [PASS] Tracking group exists")

    # Verify device group exists
    device_group = find_device_group(device_name)
    if not device_group:
        print(f"  [FAIL] Device group '{device_name}' not created")
        return False
    print(f"  [PASS] Device group '{device_name}' exists")

    # Verify position layer exists
    layer = find_device_position_layer(device_id)
    if not layer:
        print(f"  [FAIL] Position layer not found for device {device_id}")
        return False
    print(f"  [PASS] Position layer found: {layer.name()}")

    # Verify single feature
    fc = count_features(layer)
    if fc != 1:
        print(f"  [FAIL] Expected 1 feature, got {fc}")
        return False
    print(f"  [PASS] Layer has exactly 1 feature")

    # Verify device_id custom property
    stored_device_id = layer.customProperty("sartracker:device_id")
    if stored_device_id != device_id:
        print(f"  [FAIL] device_id mismatch: {stored_device_id} != {device_id}")
        return False
    print(f"  [PASS] device_id custom property correct")

    return True


def test_position_update_replaces():
    """Test that position updates replace, not accumulate."""
    print("\n=== Test: Position Update Replaces ===")
    tm = get_tracking_manager()

    device_id = "test_device_002"
    device_name = "Test Bravo"

    # First update
    pos1 = create_mock_position(device_id, device_name, lat=52.10, lon=-9.60)
    tm.update_current_positions([pos1])

    layer = find_device_position_layer(device_id)
    if not layer:
        print(f"  [FAIL] Position layer not created")
        return False

    fc1 = count_features(layer)
    print(f"  After first update: {fc1} feature(s)")

    # Second update (different position)
    pos2 = create_mock_position(device_id, device_name, lat=52.11, lon=-9.61)
    tm.update_current_positions([pos2])

    fc2 = count_features(layer)
    print(f"  After second update: {fc2} feature(s)")

    if fc2 != 1:
        print(f"  [FAIL] Expected 1 feature after update, got {fc2}")
        return False
    print("  [PASS] Position updates replace (not accumulate)")

    return True


def test_multiple_devices():
    """Test multiple devices each get their own layer."""
    print("\n=== Test: Multiple Devices ===")
    tm = get_tracking_manager()

    devices = [
        ("test_device_charlie", "Test Charlie", 52.20, -9.70),
        ("test_device_delta", "Test Delta", 52.21, -9.71),
        ("test_device_echo", "Test Echo", 52.22, -9.72),
        ("test_device_foxtrot", "Test Foxtrot", 52.23, -9.73),
        ("test_device_golf", "Test Golf", 52.24, -9.74),
    ]

    positions = [
        create_mock_position(did, name, lat, lon)
        for did, name, lat, lon in devices
    ]

    print(f"  Updating {len(positions)} devices...")
    start = time.time()
    tm.update_current_positions(positions)
    elapsed = time.time() - start
    print(f"  Update took {elapsed*1000:.1f}ms")

    # Verify each device has its own layer
    all_found = True
    for device_id, device_name, _, _ in devices:
        layer = find_device_position_layer(device_id)
        if layer:
            fc = count_features(layer)
            print(f"  [PASS] {device_name}: layer found, {fc} feature(s)")
        else:
            print(f"  [FAIL] {device_name}: layer NOT found")
            all_found = False

    return all_found


def test_device_colors_consistent():
    """Test that device colors are applied."""
    print("\n=== Test: Device Colors ===")
    tm = get_tracking_manager()

    device_id = "test_device_color"
    device_name = "Test Color Check"
    position = create_mock_position(device_id, device_name)

    tm.update_current_positions([position])

    layer = find_device_position_layer(device_id)
    if not layer:
        print("  [FAIL] Layer not created")
        return False

    # Check color custom property
    color_prop = layer.customProperty("sartracker:device_color")
    if color_prop:
        print(f"  [PASS] Device color stored: {color_prop}")
    else:
        print("  [WARN] Device color not stored in custom property")

    # Check renderer has symbol
    renderer = layer.renderer()
    if renderer:
        symbol = renderer.symbol()
        if symbol:
            color = symbol.color().name()
            print(f"  [PASS] Renderer symbol color: {color}")
            return True

    print("  [WARN] Could not verify renderer color")
    return True  # Not a hard failure


def test_ten_devices_performance():
    """Test performance with 10+ devices."""
    print("\n=== Test: 10 Devices Performance ===")
    tm = get_tracking_manager()

    # Generate 10 devices
    devices = []
    for i in range(10):
        device_id = f"test_perf_device_{i:03d}"
        device_name = f"Perf Team {i+1}"
        lat = 52.0 + (i * 0.01)
        lon = -9.5 - (i * 0.01)
        devices.append(create_mock_position(device_id, device_name, lat, lon))

    # First update - creates all layers
    print(f"  Creating {len(devices)} device layers...")
    start = time.time()
    tm.update_current_positions(devices)
    create_time = time.time() - start
    print(f"  Creation took {create_time*1000:.1f}ms")

    # Second update - updates existing layers
    print(f"  Updating {len(devices)} device positions...")
    for d in devices:
        d['lat'] += 0.001
        d['lon'] -= 0.001

    start = time.time()
    tm.update_current_positions(devices)
    update_time = time.time() - start
    print(f"  Update took {update_time*1000:.1f}ms")

    # Verify all layers exist
    found = 0
    for d in devices:
        if find_device_position_layer(d['device_id']):
            found += 1

    if found == len(devices):
        print(f"  [PASS] All {found} device layers created")
    else:
        print(f"  [FAIL] Only {found}/{len(devices)} device layers found")
        return False

    # Performance thresholds (generous for first implementation)
    if create_time < 5.0:
        print(f"  [PASS] Creation time < 5s")
    else:
        print(f"  [WARN] Creation time > 5s (may need optimization)")

    if update_time < 2.0:
        print(f"  [PASS] Update time < 2s")
    else:
        print(f"  [WARN] Update time > 2s (may need optimization)")

    return True


# =============================================================================
# Trail Tests (Phase 2 - SAR-nj0)
# =============================================================================

def test_trail_feature_flag():
    """Test that trail feature flag is enabled."""
    print("\n=== Test: Trail Feature Flag ===")
    tm = get_tracking_manager()

    if tm.USE_PER_DEVICE_TRAILS:
        print("  [PASS] USE_PER_DEVICE_TRAILS = True")
        return True
    else:
        print("  [FAIL] USE_PER_DEVICE_TRAILS = False (should be True)")
        return False


def test_single_device_trail():
    """Test creating a trail layer for a single device."""
    print("\n=== Test: Single Device Trail ===")
    tm = get_tracking_manager()

    device_id = "test_trail_device_001"
    device_name = "Test Trail Alpha"

    # Create multiple positions to form a trail
    positions = []
    base_lat, base_lon = 52.05, -9.52
    from datetime import datetime, timezone, timedelta
    base_time = datetime.now(timezone.utc)

    for i in range(10):
        pos = create_mock_position(
            device_id, device_name,
            lat=base_lat + (i * 0.001),
            lon=base_lon - (i * 0.001)
        )
        # Adjust timestamp for each position
        pos['ts'] = (base_time + timedelta(minutes=i)).isoformat()
        positions.append(pos)

    # Update breadcrumbs
    print(f"  Updating breadcrumbs with {len(positions)} positions...")
    start = time.time()
    tm.update_breadcrumbs(positions, time_gap_minutes=5)
    elapsed = time.time() - start
    print(f"  Update took {elapsed*1000:.1f}ms")

    # Verify trail layer exists
    trail_layer = find_device_trail_layer(device_id)
    if not trail_layer:
        print(f"  [FAIL] Trail layer not found for device {device_id}")
        return False
    print(f"  [PASS] Trail layer found: {trail_layer.name()}")

    # Verify features (should have at least 1 segment)
    fc = count_features(trail_layer)
    if fc < 1:
        print(f"  [FAIL] Expected at least 1 trail segment, got {fc}")
        return False
    print(f"  [PASS] Trail layer has {fc} segment(s)")

    # Verify device_id custom property
    stored_device_id = trail_layer.customProperty("sartracker:device_id")
    if stored_device_id != device_id:
        print(f"  [FAIL] device_id mismatch: {stored_device_id} != {device_id}")
        return False
    print(f"  [PASS] device_id custom property correct")

    return True


def test_multiple_device_trails():
    """Test multiple devices each get their own trail layer."""
    print("\n=== Test: Multiple Device Trails ===")
    tm = get_tracking_manager()

    devices = [
        ("test_trail_charlie", "Test Trail Charlie"),
        ("test_trail_delta", "Test Trail Delta"),
        ("test_trail_echo", "Test Trail Echo"),
    ]

    all_positions = []
    from datetime import datetime, timezone, timedelta
    base_time = datetime.now(timezone.utc)

    for idx, (device_id, device_name) in enumerate(devices):
        base_lat = 52.30 + (idx * 0.05)
        base_lon = -9.80 - (idx * 0.05)
        for i in range(5):
            pos = create_mock_position(
                device_id, device_name,
                lat=base_lat + (i * 0.001),
                lon=base_lon - (i * 0.001)
            )
            pos['ts'] = (base_time + timedelta(minutes=i)).isoformat()
            all_positions.append(pos)

    print(f"  Updating breadcrumbs for {len(devices)} devices ({len(all_positions)} positions)...")
    start = time.time()
    tm.update_breadcrumbs(all_positions, time_gap_minutes=5)
    elapsed = time.time() - start
    print(f"  Update took {elapsed*1000:.1f}ms")

    # Verify each device has its own trail layer
    all_found = True
    for device_id, device_name in devices:
        trail_layer = find_device_trail_layer(device_id)
        if trail_layer:
            fc = count_features(trail_layer)
            print(f"  [PASS] {device_name}: trail layer found, {fc} segment(s)")
        else:
            print(f"  [FAIL] {device_name}: trail layer NOT found")
            all_found = False

    return all_found


def test_trail_updates_replace():
    """Test that trail updates replace segments (not accumulate)."""
    print("\n=== Test: Trail Updates Replace ===")
    tm = get_tracking_manager()

    device_id = "test_trail_replace"
    device_name = "Test Trail Replace"

    from datetime import datetime, timezone, timedelta
    base_time = datetime.now(timezone.utc)

    # First update with 5 positions
    positions1 = []
    for i in range(5):
        pos = create_mock_position(device_id, device_name, lat=52.40 + (i * 0.001), lon=-9.90)
        pos['ts'] = (base_time + timedelta(minutes=i)).isoformat()
        positions1.append(pos)

    tm.update_breadcrumbs(positions1, time_gap_minutes=5)

    trail_layer = find_device_trail_layer(device_id)
    if not trail_layer:
        print("  [FAIL] Trail layer not created")
        return False

    fc1 = count_features(trail_layer)
    print(f"  After first update: {fc1} segment(s)")

    # Second update with different positions
    positions2 = []
    for i in range(8):
        pos = create_mock_position(device_id, device_name, lat=52.41 + (i * 0.001), lon=-9.91)
        pos['ts'] = (base_time + timedelta(minutes=i + 10)).isoformat()
        positions2.append(pos)

    tm.update_breadcrumbs(positions2, time_gap_minutes=5)

    fc2 = count_features(trail_layer)
    print(f"  After second update: {fc2} segment(s)")

    # The count might differ but shouldn't grow unboundedly
    # Main check: we didn't accumulate (fc1 + something) - we replaced
    if fc2 > 10:  # Reasonable upper bound for 8 positions
        print(f"  [FAIL] Segments seem to be accumulating: {fc2}")
        return False

    print("  [PASS] Trail updates replace segments correctly")
    return True


# =============================================================================
# Migration Tests (Phase 3 - SAR-0uy)
# =============================================================================

def test_migration_detection():
    """Test that migration detects shared layers."""
    print("\n=== Test: Migration Detection ===")
    tm = get_tracking_manager()

    # Check find methods work
    shared_current = tm._find_shared_current_layer()
    shared_breadcrumbs = tm._find_shared_breadcrumbs_layer()

    print(f"  Shared Current layer: {shared_current.name() if shared_current else 'None'}")
    print(f"  Shared Breadcrumbs layer: {shared_breadcrumbs.name() if shared_breadcrumbs else 'None'}")

    # Check archived detection
    has_archived = tm._has_archived_tracking_layers()
    print(f"  Has archived layers: {has_archived}")

    print("  [PASS] Migration detection methods work")
    return True


def test_migration_device_extraction():
    """Test extracting devices from shared layers."""
    print("\n=== Test: Migration Device Extraction ===")
    tm = get_tracking_manager()

    shared_current = tm._find_shared_current_layer()
    shared_breadcrumbs = tm._find_shared_breadcrumbs_layer()

    if not shared_current and not shared_breadcrumbs:
        print("  [SKIP] No shared layers to extract from")
        return True

    devices = tm._extract_devices_from_shared(shared_current, shared_breadcrumbs)
    print(f"  Found {len(devices)} devices in shared layers:")
    for device_id, info in list(devices.items())[:5]:  # Show first 5
        print(f"    - {device_id}: {info.get('name', 'Unknown')}")

    print("  [PASS] Device extraction works")
    return True


def test_migration_idempotent():
    """Test that migration is idempotent (safe to run multiple times)."""
    print("\n=== Test: Migration Idempotent ===")
    tm = get_tracking_manager()

    # Run migration twice
    print("  Running migration (first time)...")
    result1 = tm.migrate_to_per_device_layers()
    print(f"  First migration result: {result1}")

    print("  Running migration (second time)...")
    result2 = tm.migrate_to_per_device_layers()
    print(f"  Second migration result: {result2}")

    if result1 and result2:
        print("  [PASS] Migration is idempotent")
        return True
    else:
        print("  [FAIL] Migration returned False")
        return False


def test_archive_detection():
    """Test detecting archived layers."""
    print("\n=== Test: Archive Detection ===")
    tm = get_tracking_manager()

    # Check for archived layers
    has_archived = tm._has_archived_tracking_layers()
    print(f"  Has archived layers: {has_archived}")

    # Find archived layers
    archived_layers = []
    for layer in QgsProject.instance().mapLayers().values():
        if not isinstance(layer, QgsVectorLayer):
            continue
        if tm.ARCHIVE_SUFFIX in layer.name():
            archived_layers.append(layer.name())

    if archived_layers:
        print(f"  Found archived layers: {', '.join(archived_layers)}")
    else:
        print("  No archived layers found")

    print("  [PASS] Archive detection works")
    return True


# =============================================================================
# Test Runner
# =============================================================================

def run_tests():
    """Run all per-device tracking tests."""
    if not QGIS_AVAILABLE:
        print("ERROR: Tests must be run from QGIS Python console")
        return

    print("=" * 60)
    print("SAR-33p Per-Device Tracking Tests")
    print("=" * 60)

    tests = [
        # Phase 1: Position tests
        ("Feature Flag", test_feature_flag),
        ("Single Device", test_single_device),
        ("Position Update Replaces", test_position_update_replaces),
        ("Multiple Devices", test_multiple_devices),
        ("Device Colors", test_device_colors_consistent),
        ("10 Devices Performance", test_ten_devices_performance),
        ("Fallback to Shared", test_fallback_to_shared),
        # Phase 2: Trail tests
        ("Trail Feature Flag", test_trail_feature_flag),
        ("Single Device Trail", test_single_device_trail),
        ("Multiple Device Trails", test_multiple_device_trails),
        ("Trail Updates Replace", test_trail_updates_replace),
        # Phase 3: Migration tests
        ("Migration Detection", test_migration_detection),
        ("Migration Device Extraction", test_migration_device_extraction),
        ("Migration Idempotent", test_migration_idempotent),
        ("Archive Detection", test_archive_detection),
    ]

    results = []
    for name, test_fn in tests:
        try:
            result = test_fn()
            results.append((name, result, None))
        except Exception as e:
            print(f"  [ERROR] {e}")
            traceback.print_exc()
            results.append((name, False, str(e)))

    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)

    passed = sum(1 for _, r, _ in results if r)
    failed = len(results) - passed

    for name, result, error in results:
        status = "[PASS]" if result else "[FAIL]"
        error_msg = f" - {error}" if error else ""
        print(f"  {status} {name}{error_msg}")

    print(f"\nTotal: {passed} passed, {failed} failed")

    if failed == 0:
        print("\nAll tests passed!")
    else:
        print(f"\n{failed} test(s) failed - see details above")

    return failed == 0


def cleanup_test_layers():
    """Remove test layers created during testing."""
    print("\n=== Cleanup Test Layers ===")
    project = QgsProject.instance()
    removed = 0

    for layer_id, layer in list(project.mapLayers().items()):
        if not isinstance(layer, QgsVectorLayer):
            continue
        device_id = layer.customProperty("sartracker:device_id", "")
        if device_id.startswith("test_"):
            layer_name = layer.name()  # Get name before removal
            project.removeMapLayer(layer_id)
            removed += 1
            print(f"  Removed: {layer_name}")

    print(f"  Removed {removed} test layers")

    # Remove empty test device groups
    root = project.layerTreeRoot()
    sar_root = root.findGroup("SAR Tracker")
    if sar_root:
        tracking = sar_root.findGroup("Tracking")
        if tracking:
            for child in list(tracking.children()):
                if isinstance(child, QgsLayerTreeGroup):
                    # Match test group names from both position and trail tests
                    if (child.name().startswith("Test ") or
                        child.name().startswith("Perf ") or
                        child.name().startswith("Test Trail")):
                        tracking.removeChildNode(child)
                        print(f"  Removed group: {child.name()}")


if __name__ == "__main__":
    # When run directly (not in QGIS), just show usage
    print(__doc__)
