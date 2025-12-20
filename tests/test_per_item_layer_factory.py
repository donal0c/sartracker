# -*- coding: utf-8 -*-
"""
Tests for PerItemLayerFactory (Phase 3 Implementation)

These tests validate the ADR-001 architecture and Phase 3 registry:
- Per-item GeoPackage tables
- Layer identification by custom properties (not names)
- Rename, style, and metadata persistence
- Item registry for cross-session discovery
- Lazy loading support

Run in QGIS Python Console:
    from sartracker.tests.test_per_item_layer_factory import run_all_tests
    run_all_tests()

Or run individual tests:
    from sartracker.tests.test_per_item_layer_factory import test_create_and_identify
    test_create_and_identify()

Phase 3 registry tests:
    from sartracker.tests.test_per_item_layer_factory import test_registry_persistence
    test_registry_persistence()
"""

import tempfile
import os
from pathlib import Path

# For running in QGIS console
try:
    from qgis.core import QgsProject, QgsVectorLayer, QgsFeature, QgsGeometry, QgsPointXY
    from qgis.utils import iface
    QGIS_AVAILABLE = True
except ImportError:
    QGIS_AVAILABLE = False
    print("Warning: QGIS not available - tests must be run from QGIS Python console")


def get_test_gpkg_path() -> Path:
    """Get a temporary path for test GeoPackage."""
    temp_dir = tempfile.mkdtemp(prefix="sar_test_")
    return Path(temp_dir) / "test_mission.gpkg"


def cleanup_test_layers():
    """Remove any test layers from the current project."""
    if not QGIS_AVAILABLE:
        return

    project = QgsProject.instance()
    layers_to_remove = []

    for layer_id, layer in project.mapLayers().items():
        if layer.customProperty("sartracker:item_id"):
            layers_to_remove.append(layer_id)

    for layer_id in layers_to_remove:
        project.removeMapLayer(layer_id)


def test_create_and_identify():
    """
    Test 1: Create item layer and identify by custom property.

    Validates:
    - Layer creation with GeoPackage table
    - Custom properties set correctly
    - Layer can be found by item_id (not name)
    """
    print("\n=== Test 1: Create and Identify ===")

    from sartracker.controllers.per_item_layer_factory import (
        PerItemLayerFactory, ItemType
    )

    gpkg_path = get_test_gpkg_path()
    factory = PerItemLayerFactory(gpkg_path)

    # Create a clue layer
    info = factory.create_item_layer(
        item_type=ItemType.MARKER_CLUE,
        display_name="Test Clue - Footprint",
        add_to_project=True
    )

    print(f"  Created: {info.display_name}")
    print(f"  Item ID: {info.item_id}")
    print(f"  Table: {info.table_name}")
    print(f"  Layer valid: {info.layer.isValid()}")

    # Verify custom properties
    assert info.layer.customProperty("sartracker:item_id") == info.item_id, \
        "Item ID property not set"
    assert info.layer.customProperty("sartracker:item_type") == ItemType.MARKER_CLUE, \
        "Item type property not set"
    print("  Custom properties: OK")

    # Verify we can find by item_id
    found_layer = factory.get_layer_by_item_id(info.item_id)
    assert found_layer is not None, "Could not find layer by item_id"
    assert found_layer.id() == info.layer.id(), "Found wrong layer"
    print("  Lookup by item_id: OK")

    # Verify GeoPackage table exists
    from sartracker.controllers.per_item_layer_factory import get_gpkg_tables
    tables = get_gpkg_tables(gpkg_path)
    assert info.table_name in tables, f"Table {info.table_name} not in GeoPackage"
    print(f"  GeoPackage table exists: OK ({info.table_name})")

    print("  PASSED")
    return True


def test_rename_persistence():
    """
    Test 2: Rename layer and verify identification still works.

    Validates:
    - Layer can be renamed
    - item_id lookup still works after rename
    - Table name unchanged
    """
    print("\n=== Test 2: Rename Persistence ===")

    from sartracker.controllers.per_item_layer_factory import (
        PerItemLayerFactory, ItemType
    )

    gpkg_path = get_test_gpkg_path()
    factory = PerItemLayerFactory(gpkg_path)

    # Create a layer
    info = factory.create_item_layer(
        item_type=ItemType.MARKER_HAZARD,
        display_name="Original Name",
        add_to_project=True
    )

    original_item_id = info.item_id
    original_table = info.table_name
    print(f"  Created: '{info.display_name}'")

    # Rename the layer
    new_name = "Renamed - Cliff Edge Hazard"
    success = factory.rename_item_layer(original_item_id, new_name)
    assert success, "Rename failed"
    print(f"  Renamed to: '{new_name}'")

    # Verify identification still works
    found_layer = factory.get_layer_by_item_id(original_item_id)
    assert found_layer is not None, "Could not find layer after rename"
    assert found_layer.name() == new_name, "Layer name not updated"
    print("  Lookup after rename: OK")

    # Verify table name unchanged
    current_table = factory._extract_table_name(found_layer)
    assert current_table == original_table, \
        f"Table name changed: {original_table} -> {current_table}"
    print(f"  Table unchanged: OK ({original_table})")

    print("  PASSED")
    return True


def test_metadata_persistence():
    """
    Test 3: Set and retrieve custom metadata.

    Validates:
    - Custom metadata can be set
    - Metadata persists and can be retrieved
    """
    print("\n=== Test 3: Metadata Persistence ===")

    from sartracker.controllers.per_item_layer_factory import (
        PerItemLayerFactory, ItemType
    )

    gpkg_path = get_test_gpkg_path()
    factory = PerItemLayerFactory(gpkg_path)

    # Create a layer
    info = factory.create_item_layer(
        item_type=ItemType.SEARCH_AREA,
        display_name="Search Area Alpha",
        add_to_project=True
    )
    print(f"  Created: {info.display_name}")

    # Set metadata
    test_metadata = {
        "team": "Team Bravo",
        "priority": "High",
        "notes": "Check along riverbank",
        "assigned_by": "Coordinator 1"
    }
    success = factory.update_item_metadata(info.item_id, test_metadata)
    assert success, "Failed to set metadata"
    print(f"  Set metadata: {len(test_metadata)} properties")

    # Retrieve metadata
    retrieved = factory.get_item_metadata(info.item_id)
    print(f"  Retrieved metadata: {len(retrieved)} properties")

    for key, expected_value in test_metadata.items():
        actual_value = retrieved.get(key)
        assert actual_value == expected_value, \
            f"Metadata mismatch for '{key}': expected '{expected_value}', got '{actual_value}'"

    print("  All metadata values match: OK")
    print("  PASSED")
    return True


def test_delete_layer():
    """
    Test 4: Delete layer and verify cleanup.

    Validates:
    - Layer removed from project
    - GeoPackage table removed
    - Lookup returns None after deletion
    """
    print("\n=== Test 4: Delete Layer ===")

    from sartracker.controllers.per_item_layer_factory import (
        PerItemLayerFactory, ItemType, get_gpkg_tables
    )

    gpkg_path = get_test_gpkg_path()
    factory = PerItemLayerFactory(gpkg_path)

    # Create a layer
    info = factory.create_item_layer(
        item_type=ItemType.RANGE_RING,
        display_name="Range Ring 1km",
        add_to_project=True
    )
    item_id = info.item_id
    table_name = info.table_name
    print(f"  Created: {info.display_name} (table={table_name})")

    # Verify table exists
    tables_before = get_gpkg_tables(gpkg_path)
    assert table_name in tables_before, "Table not created"
    print(f"  Tables before delete: {len(tables_before)}")

    # Delete
    success = factory.delete_item_layer(item_id, remove_table=True)
    assert success, "Delete failed"
    print("  Delete called: OK")

    # Verify layer gone from project
    found = factory.get_layer_by_item_id(item_id)
    assert found is None, "Layer still found after deletion"
    print("  Layer removed from project: OK")

    # Verify table removed from GeoPackage
    tables_after = get_gpkg_tables(gpkg_path)
    assert table_name not in tables_after, "Table still exists in GeoPackage"
    print(f"  Tables after delete: {len(tables_after)}")
    print("  GeoPackage table removed: OK")

    print("  PASSED")
    return True


def test_multiple_items():
    """
    Test 5: Create multiple items and verify isolation.

    Validates:
    - Multiple items can coexist
    - Each has separate table
    - get_all_item_layers returns correct items
    """
    print("\n=== Test 5: Multiple Items ===")

    from sartracker.controllers.per_item_layer_factory import (
        PerItemLayerFactory, ItemType, get_gpkg_tables
    )

    gpkg_path = get_test_gpkg_path()
    factory = PerItemLayerFactory(gpkg_path)

    # Create multiple items
    items_to_create = [
        (ItemType.MARKER_CLUE, "Clue 1 - Backpack"),
        (ItemType.MARKER_CLUE, "Clue 2 - Water Bottle"),
        (ItemType.MARKER_HAZARD, "Hazard - Cliff"),
        (ItemType.SEARCH_AREA, "Search Area North"),
    ]

    created_ids = []
    for item_type, name in items_to_create:
        info = factory.create_item_layer(
            item_type=item_type,
            display_name=name,
            add_to_project=True
        )
        created_ids.append(info.item_id)
        print(f"  Created: {name} ({info.item_id[:8]}...)")

    # Verify all tables exist
    tables = get_gpkg_tables(gpkg_path)
    print(f"  Total tables in GeoPackage: {len(tables)}")
    assert len(tables) >= len(items_to_create), "Not all tables created"

    # Verify get_all_item_layers
    all_items = factory.get_all_item_layers()
    print(f"  get_all_item_layers returned: {len(all_items)}")
    assert len(all_items) >= len(items_to_create), "Not all items returned"

    # Verify filter by type
    clues = factory.get_all_item_layers(item_type=ItemType.MARKER_CLUE)
    print(f"  Clues only: {len(clues)}")
    assert len(clues) == 2, f"Expected 2 clues, got {len(clues)}"

    hazards = factory.get_all_item_layers(item_type=ItemType.MARKER_HAZARD)
    print(f"  Hazards only: {len(hazards)}")
    assert len(hazards) == 1, f"Expected 1 hazard, got {len(hazards)}"

    print("  Type filtering: OK")
    print("  PASSED")
    return True


def test_wal_mode():
    """
    Test 6: Verify WAL mode is enabled.

    Validates:
    - WAL mode enabled on new GeoPackage
    - WAL files created
    """
    print("\n=== Test 6: WAL Mode ===")

    import sqlite3
    from sartracker.controllers.per_item_layer_factory import (
        PerItemLayerFactory, ItemType, enable_wal_mode
    )

    gpkg_path = get_test_gpkg_path()
    factory = PerItemLayerFactory(gpkg_path, auto_wal=True)

    # Create a layer to ensure GeoPackage exists
    info = factory.create_item_layer(
        item_type=ItemType.MARKER_CLUE,
        display_name="WAL Test",
        add_to_project=True
    )
    print(f"  Created: {info.display_name}")

    # Check journal mode
    conn = sqlite3.connect(str(gpkg_path))
    result = conn.execute("PRAGMA journal_mode").fetchone()
    conn.close()

    journal_mode = result[0].upper() if result else "UNKNOWN"
    print(f"  Journal mode: {journal_mode}")

    assert journal_mode == "WAL", f"Expected WAL mode, got {journal_mode}"
    print("  WAL mode: OK")

    print("  PASSED")
    return True


def test_add_feature_to_layer():
    """
    Test 7: Add a feature to a per-item layer.

    Validates:
    - Features can be added to per-item layers
    - Data persists in GeoPackage
    """
    print("\n=== Test 7: Add Feature ===")

    from sartracker.controllers.per_item_layer_factory import (
        PerItemLayerFactory, ItemType
    )

    gpkg_path = get_test_gpkg_path()
    factory = PerItemLayerFactory(gpkg_path)

    # Create a layer
    info = factory.create_item_layer(
        item_type=ItemType.MARKER_CLUE,
        display_name="Feature Test Clue",
        add_to_project=True
    )
    layer = info.layer
    print(f"  Created layer: {info.display_name}")
    print(f"  Initial feature count: {layer.featureCount()}")

    # Add a feature
    feature = QgsFeature(layer.fields())
    feature.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(-9.5, 52.0)))
    feature.setAttribute("id", "test-feature-001")
    feature.setAttribute("name", "Test Clue Feature")
    feature.setAttribute("description", "A test clue for the prototype")

    layer.startEditing()
    success = layer.addFeature(feature)
    assert success, "Failed to add feature"
    layer.commitChanges()

    print(f"  Feature added: {success}")
    print(f"  Final feature count: {layer.featureCount()}")

    assert layer.featureCount() == 1, "Feature count should be 1"
    print("  Feature persisted: OK")

    # Verify feature data
    for feat in layer.getFeatures():
        assert feat["name"] == "Test Clue Feature", "Feature name mismatch"
        print(f"  Feature name verified: '{feat['name']}'")

    print("  PASSED")
    return True


# =============================================================================
# Phase 3 Registry Tests
# =============================================================================

def test_registry_persistence():
    """
    Test 8: Registry persistence across factory instances.

    Validates:
    - Items are recorded in registry on create
    - Registry survives factory recreation
    - Items can be discovered from registry
    """
    print("\n=== Test 8: Registry Persistence ===")

    from sartracker.controllers.per_item_layer_factory import (
        PerItemLayerFactory, ItemType, registry_get_all_items, registry_exists
    )

    gpkg_path = get_test_gpkg_path()
    factory = PerItemLayerFactory(gpkg_path)

    # Create an item
    info = factory.create_item_layer(
        item_type=ItemType.MARKER_CLUE,
        display_name="Registry Test Clue",
        add_to_project=True
    )
    print(f"  Created: {info.display_name} (id={info.item_id[:8]}...)")

    # Verify registry exists
    assert registry_exists(gpkg_path), "Registry table not created"
    print("  Registry table exists: OK")

    # Check registry contains item
    registry_items = registry_get_all_items(gpkg_path)
    assert len(registry_items) >= 1, "Item not in registry"
    found = any(item.item_id == info.item_id for item in registry_items)
    assert found, "Created item not found in registry"
    print("  Item in registry: OK")

    # Create a NEW factory instance (simulating session restart)
    factory2 = PerItemLayerFactory(gpkg_path)

    # Get registry items from new factory
    items = factory2.get_registry_items()
    found2 = any(item.item_id == info.item_id for item in items)
    assert found2, "Item not found in new factory's registry view"
    print("  Item found after factory recreation: OK")

    print("  PASSED")
    return True


def test_discover_existing_items():
    """
    Test 9: Discover items and check layer status.

    Validates:
    - discover_existing_items() finds items
    - Status is ACTIVE for loaded layers
    - Status is ORPHANED when layer removed
    """
    print("\n=== Test 9: Discover Existing Items ===")

    from sartracker.controllers.per_item_layer_factory import (
        PerItemLayerFactory, ItemType, ItemStatus
    )

    gpkg_path = get_test_gpkg_path()
    factory = PerItemLayerFactory(gpkg_path)

    # Create items
    info1 = factory.create_item_layer(
        item_type=ItemType.MARKER_CLUE,
        display_name="Discovery Test 1",
        add_to_project=True
    )
    info2 = factory.create_item_layer(
        item_type=ItemType.MARKER_HAZARD,
        display_name="Discovery Test 2",
        add_to_project=True
    )
    print(f"  Created 2 items")

    # Discover items - should all be ACTIVE
    items = factory.discover_existing_items()
    assert len(items) >= 2, f"Expected 2+ items, got {len(items)}"

    active_items = [i for i in items if i.status == ItemStatus.ACTIVE]
    assert len(active_items) >= 2, "Not all items are ACTIVE"
    print(f"  All items ACTIVE: OK ({len(active_items)})")

    # Remove one layer from project (but keep in registry)
    project = QgsProject.instance()
    project.removeMapLayer(info1.layer.id())
    del factory._layer_cache[info1.item_id]
    print(f"  Removed layer for {info1.item_id[:8]}...")

    # Discover again - should have 1 ORPHANED
    items2 = factory.discover_existing_items()
    orphaned = [i for i in items2 if i.status == ItemStatus.ORPHANED]
    assert len(orphaned) >= 1, "Expected at least 1 ORPHANED item"
    print(f"  Orphaned items found: {len(orphaned)}")

    print("  PASSED")
    return True


def test_rebuild_missing_layer():
    """
    Test 10: Rebuild a layer from registry data.

    Validates:
    - Layer can be removed and rebuilt
    - Rebuilt layer has correct properties
    - Rebuilt layer accesses same data
    """
    print("\n=== Test 10: Rebuild Missing Layer ===")

    from sartracker.controllers.per_item_layer_factory import (
        PerItemLayerFactory, ItemType, SAR_ITEM_ID, SAR_ITEM_TYPE
    )

    gpkg_path = get_test_gpkg_path()
    factory = PerItemLayerFactory(gpkg_path)

    # Create an item with a feature
    info = factory.create_item_layer(
        item_type=ItemType.SEARCH_AREA,
        display_name="Rebuild Test Area",
        add_to_project=True
    )
    layer = info.layer

    # Add a feature to the layer
    feature = QgsFeature(layer.fields())
    from qgis.core import QgsGeometry, QgsPointXY
    # Create a simple polygon
    polygon_wkt = "POLYGON((-9.5 52.0, -9.5 52.1, -9.4 52.1, -9.4 52.0, -9.5 52.0))"
    feature.setGeometry(QgsGeometry.fromWkt(polygon_wkt))
    feature.setAttribute("id", "test-area-001")
    feature.setAttribute("name", "Test Search Area")

    layer.startEditing()
    layer.addFeature(feature)
    layer.commitChanges()

    original_feature_count = layer.featureCount()
    original_item_id = info.item_id
    print(f"  Created layer with {original_feature_count} feature")

    # Remove the layer from project
    project = QgsProject.instance()
    project.removeMapLayer(layer.id())
    del factory._layer_cache[original_item_id]
    print("  Layer removed from project")

    # Verify layer is gone
    found = factory.get_layer_by_item_id(original_item_id)
    assert found is None, "Layer should not be found after removal"
    print("  Layer not found: OK (expected)")

    # Rebuild the layer
    rebuilt_layer = factory.rebuild_missing_layer(original_item_id, add_to_project=True)
    assert rebuilt_layer is not None, "Failed to rebuild layer"
    assert rebuilt_layer.isValid(), "Rebuilt layer is not valid"
    print("  Layer rebuilt: OK")

    # Verify properties
    assert rebuilt_layer.customProperty(SAR_ITEM_ID) == original_item_id, "Item ID mismatch"
    assert rebuilt_layer.customProperty(SAR_ITEM_TYPE) == ItemType.SEARCH_AREA, "Type mismatch"
    print("  Properties match: OK")

    # Verify data is intact
    assert rebuilt_layer.featureCount() == original_feature_count, "Feature count mismatch"
    print(f"  Feature count preserved: {rebuilt_layer.featureCount()}")

    print("  PASSED")
    return True


def test_soft_delete_and_recovery():
    """
    Test 11: Soft delete and item status.

    Validates:
    - Soft delete marks item as deleted
    - Deleted items excluded from normal queries
    - Deleted items can be found with include_deleted=True
    """
    print("\n=== Test 11: Soft Delete and Recovery ===")

    from sartracker.controllers.per_item_layer_factory import (
        PerItemLayerFactory, ItemType, ItemStatus
    )

    gpkg_path = get_test_gpkg_path()
    factory = PerItemLayerFactory(gpkg_path)

    # Create an item
    info = factory.create_item_layer(
        item_type=ItemType.MARKER_CLUE,
        display_name="Delete Test",
        add_to_project=True
    )
    item_id = info.item_id
    print(f"  Created: {info.display_name}")

    # Soft delete (hard_delete=False is default)
    success = factory.delete_item_layer(item_id, remove_table=False, hard_delete=False)
    assert success, "Soft delete failed"
    print("  Soft deleted: OK")

    # Normal query should NOT find it
    items = factory.get_registry_items(include_deleted=False)
    found_normal = any(i.item_id == item_id for i in items)
    assert not found_normal, "Deleted item should not appear in normal query"
    print("  Not in normal query: OK")

    # Query with include_deleted should find it
    items_all = factory.get_registry_items(include_deleted=True)
    found_deleted = any(i.item_id == item_id for i in items_all)
    assert found_deleted, "Deleted item should appear with include_deleted=True"
    print("  Found with include_deleted: OK")

    # Check status is DELETED
    deleted_item = next((i for i in items_all if i.item_id == item_id), None)
    assert deleted_item is not None, "Could not find deleted item"
    assert deleted_item.is_deleted, "Item should be marked as deleted"
    print("  Status is deleted: OK")

    print("  PASSED")
    return True


def test_lazy_loading():
    """
    Test 12: Lazy loading of items on demand.

    Validates:
    - Items can be created but layers not loaded
    - load_items_on_demand() loads orphaned items
    - Batch loading works correctly
    """
    print("\n=== Test 12: Lazy Loading ===")

    from sartracker.controllers.per_item_layer_factory import (
        PerItemLayerFactory, ItemType, ItemStatus
    )

    gpkg_path = get_test_gpkg_path()
    factory = PerItemLayerFactory(gpkg_path)

    # Create multiple items
    created_ids = []
    for i in range(5):
        info = factory.create_item_layer(
            item_type=ItemType.MARKER_CLUE,
            display_name=f"Lazy Test {i+1}",
            add_to_project=True
        )
        created_ids.append(info.item_id)
    print(f"  Created {len(created_ids)} items")

    # Remove all layers from project (simulate new session)
    project = QgsProject.instance()
    for item_id in created_ids:
        layer = factory.get_layer_by_item_id(item_id)
        if layer:
            project.removeMapLayer(layer.id())
    factory._layer_cache.clear()
    print("  All layers removed (simulating new session)")

    # Check orphaned count
    orphaned_count = factory.get_orphaned_count()
    assert orphaned_count >= 5, f"Expected 5+ orphaned, got {orphaned_count}"
    print(f"  Orphaned count: {orphaned_count}")

    # Load 3 items on demand
    result = factory.load_items_on_demand(batch_size=3)
    assert result["loaded"] == 3, f"Expected 3 loaded, got {result['loaded']}"
    print(f"  Loaded: {result['loaded']}, Remaining: {result['remaining']}")

    # Load remaining
    result2 = factory.load_items_on_demand(batch_size=10)
    assert result2["loaded"] >= 2, f"Expected 2+ loaded, got {result2['loaded']}"
    print(f"  Loaded remaining: {result2['loaded']}")

    # All should now be active
    items = factory.discover_existing_items()
    active = [i for i in items if i.status == ItemStatus.ACTIVE]
    assert len(active) >= 5, f"Expected 5+ active, got {len(active)}"
    print(f"  All items now active: {len(active)}")

    print("  PASSED")
    return True


# =============================================================================
# Phase 3 Bulk Operations Tests (SAR-dgj)
# =============================================================================

def test_bulk_visibility():
    """
    Test 13: Bulk show/hide operations.

    Validates:
    - bulk_hide() hides multiple items
    - bulk_show() shows multiple items
    - Locked items are skipped
    """
    print("\n=== Test 13: Bulk Visibility ===")

    from sartracker.controllers.per_item_layer_factory import (
        PerItemLayerFactory, ItemType
    )

    gpkg_path = get_test_gpkg_path()
    factory = PerItemLayerFactory(gpkg_path)

    # Create multiple items
    created_ids = []
    for i in range(3):
        info = factory.create_item_layer(
            item_type=ItemType.MARKER_CLUE,
            display_name=f"Visibility Test {i+1}",
            add_to_project=True
        )
        created_ids.append(info.item_id)
    print(f"  Created {len(created_ids)} items")

    # Hide all
    result = factory.bulk_hide(item_type=ItemType.MARKER_CLUE)
    assert result["changed"] >= 3, f"Expected 3+ changed, got {result['changed']}"
    print(f"  Bulk hide: {result['changed']} changed")

    # Show all
    result = factory.bulk_show(item_type=ItemType.MARKER_CLUE)
    assert result["changed"] >= 3, f"Expected 3+ changed, got {result['changed']}"
    print(f"  Bulk show: {result['changed']} changed")

    print("  PASSED")
    return True


def test_lock_convention():
    """
    Test 14: Lock convention for protecting items.

    Validates:
    - set_item_locked() sets lock state
    - is_item_locked() returns correct state
    - Locked items are skipped in bulk operations
    """
    print("\n=== Test 14: Lock Convention ===")

    from sartracker.controllers.per_item_layer_factory import (
        PerItemLayerFactory, ItemType
    )

    gpkg_path = get_test_gpkg_path()
    factory = PerItemLayerFactory(gpkg_path)

    # Create items
    info1 = factory.create_item_layer(
        item_type=ItemType.MARKER_CLUE,
        display_name="Lock Test 1",
        add_to_project=True
    )
    info2 = factory.create_item_layer(
        item_type=ItemType.MARKER_CLUE,
        display_name="Lock Test 2",
        add_to_project=True
    )
    print("  Created 2 items")

    # Lock one item
    success = factory.set_item_locked(info1.item_id, True)
    assert success, "Failed to lock item"
    print(f"  Locked item 1: OK")

    # Verify lock state
    assert factory.is_item_locked(info1.item_id), "Item 1 should be locked"
    assert not factory.is_item_locked(info2.item_id), "Item 2 should not be locked"
    print("  Lock states verified: OK")

    # Try bulk hide - locked item should be skipped
    result = factory.bulk_hide(item_type=ItemType.MARKER_CLUE)
    assert result["locked"] >= 1, "Expected 1+ locked"
    print(f"  Bulk hide skipped {result['locked']} locked items: OK")

    # Unlock
    factory.set_item_locked(info1.item_id, False)
    assert not factory.is_item_locked(info1.item_id), "Item should be unlocked"
    print("  Unlock: OK")

    print("  PASSED")
    return True


def test_layer_count_guardrails():
    """
    Test 15: Layer count guardrails.

    Validates:
    - get_layer_count_status() returns correct counts
    - check_can_create_item() returns warnings at threshold
    """
    print("\n=== Test 15: Layer Count Guardrails ===")

    from sartracker.controllers.per_item_layer_factory import (
        PerItemLayerFactory, ItemType
    )

    gpkg_path = get_test_gpkg_path()
    factory = PerItemLayerFactory(gpkg_path)

    # Create some items
    for i in range(5):
        factory.create_item_layer(
            item_type=ItemType.MARKER_CLUE,
            display_name=f"Guardrail Test {i+1}",
            add_to_project=True
        )
    print("  Created 5 items")

    # Check status with low threshold
    status = factory.get_layer_count_status(threshold=3)
    assert status["total"] >= 5, f"Expected 5+ total, got {status['total']}"
    assert status["warning"], "Should have warning with threshold=3"
    print(f"  Status: {status['total']} total, warning={status['warning']}")

    # Check with high threshold
    can_create, warning = factory.check_can_create_item(threshold=100)
    assert can_create, "Should allow creation"
    assert warning is None, "Should not have warning with high threshold"
    print("  High threshold: no warning")

    # Check with low threshold
    can_create, warning = factory.check_can_create_item(threshold=3)
    assert can_create, "Should still allow creation (soft guardrail)"
    assert warning is not None, "Should have warning"
    print(f"  Low threshold warning: {warning[:50]}...")

    print("  PASSED")
    return True


def test_bulk_delete():
    """
    Test 16: Bulk delete operations.

    Validates:
    - bulk_delete() removes multiple items
    - Locked items are skipped
    - Soft delete is default
    """
    print("\n=== Test 16: Bulk Delete ===")

    from sartracker.controllers.per_item_layer_factory import (
        PerItemLayerFactory, ItemType
    )

    gpkg_path = get_test_gpkg_path()
    factory = PerItemLayerFactory(gpkg_path)

    # Create items
    created_ids = []
    for i in range(4):
        info = factory.create_item_layer(
            item_type=ItemType.MARKER_HAZARD,
            display_name=f"Delete Test {i+1}",
            add_to_project=True
        )
        created_ids.append(info.item_id)
    print(f"  Created {len(created_ids)} items")

    # Lock one
    factory.set_item_locked(created_ids[0], True)
    print("  Locked first item")

    # Bulk delete (soft, skip locked)
    result = factory.bulk_delete(item_type=ItemType.MARKER_HAZARD)
    assert result["deleted"] >= 3, f"Expected 3+ deleted, got {result['deleted']}"
    assert result["locked"] >= 1, "Expected 1+ locked (skipped)"
    print(f"  Bulk delete: {result['deleted']} deleted, {result['locked']} locked (skipped)")

    # Verify locked item still exists
    locked_layer = factory.get_layer_by_item_id(created_ids[0])
    assert locked_layer is not None, "Locked item should still exist"
    print("  Locked item preserved: OK")

    print("  PASSED")
    return True


def run_all_tests():
    """Run all prototype validation tests."""
    print("\n" + "=" * 60)
    print("SAR Tracker - Per-Item Layer Factory Tests")
    print("Phase 3 Implementation (ADR-001 + Registry + Bulk Ops)")
    print("=" * 60)

    if not QGIS_AVAILABLE:
        print("\nERROR: Tests must be run from QGIS Python console")
        return False

    # Cleanup any previous test layers
    cleanup_test_layers()

    tests = [
        # Phase 2 tests
        ("Create and Identify", test_create_and_identify),
        ("Rename Persistence", test_rename_persistence),
        ("Metadata Persistence", test_metadata_persistence),
        ("Delete Layer", test_delete_layer),
        ("Multiple Items", test_multiple_items),
        ("WAL Mode", test_wal_mode),
        ("Add Feature", test_add_feature_to_layer),
        # Phase 3 registry tests
        ("Registry Persistence", test_registry_persistence),
        ("Discover Existing Items", test_discover_existing_items),
        ("Rebuild Missing Layer", test_rebuild_missing_layer),
        ("Soft Delete and Recovery", test_soft_delete_and_recovery),
        ("Lazy Loading", test_lazy_loading),
        # Phase 3 bulk operations tests (SAR-dgj)
        ("Bulk Visibility", test_bulk_visibility),
        ("Lock Convention", test_lock_convention),
        ("Layer Count Guardrails", test_layer_count_guardrails),
        ("Bulk Delete", test_bulk_delete),
        # Phase 3 performance tests (SAR-49s)
        ("Performance Mode", test_performance_mode),
        ("Performance Status", test_performance_status),
    ]

    passed = 0
    failed = 0

    for name, test_fn in tests:
        try:
            result = test_fn()
            if result:
                passed += 1
            else:
                failed += 1
                print(f"  FAILED (returned False)")
        except Exception as e:
            failed += 1
            print(f"  FAILED with exception: {e}")
            import traceback
            traceback.print_exc()

        # Cleanup after each test
        cleanup_test_layers()

    print("\n" + "=" * 60)
    print(f"Results: {passed} passed, {failed} failed")
    print("=" * 60)

    return failed == 0


# =============================================================================
# Phase 3 Performance Tests (SAR-49s)
# =============================================================================

def test_performance_mode():
    """
    Test 17: Performance mode (scale-based visibility).

    Validates:
    - enable_performance_mode() applies scale visibility
    - Critical items (IPP/LKP) are preserved (no scale visibility)
    - disable_performance_mode() removes scale visibility
    """
    print("\n=== Test 17: Performance Mode ===")

    from sartracker.controllers.per_item_layer_factory import (
        PerItemLayerFactory, ItemType
    )

    gpkg_path = get_test_gpkg_path()
    factory = PerItemLayerFactory(gpkg_path)

    # Create items of different types
    clue = factory.create_item_layer(
        item_type=ItemType.MARKER_CLUE,
        display_name="Perf Test Clue",
        add_to_project=True
    )
    ipp = factory.create_item_layer(
        item_type=ItemType.MARKER_IPP_LKP,
        display_name="Perf Test IPP",
        add_to_project=True
    )
    print("  Created clue and IPP items")

    # Enable performance mode
    result = factory.enable_performance_mode()
    print(f"  Performance mode enabled: {result['applied']} applied, {result['critical_preserved']} critical")

    # Check clue has scale visibility
    assert clue.layer.hasScaleBasedVisibility(), "Clue should have scale visibility"
    print("  Clue has scale visibility: OK")

    # Check IPP does NOT have scale visibility (critical)
    assert not ipp.layer.hasScaleBasedVisibility(), "IPP should NOT have scale visibility"
    print("  IPP preserved (no scale visibility): OK")

    # Disable performance mode
    updated = factory.disable_performance_mode()
    assert updated >= 2, f"Expected 2+ updated, got {updated}"
    assert not clue.layer.hasScaleBasedVisibility(), "Clue scale visibility should be removed"
    print(f"  Performance mode disabled: {updated} layers updated")

    print("  PASSED")
    return True


def test_performance_status():
    """
    Test 18: Performance status reporting.

    Validates:
    - get_performance_status() returns metrics
    - Recommendations are generated appropriately
    """
    print("\n=== Test 18: Performance Status ===")

    from sartracker.controllers.per_item_layer_factory import (
        PerItemLayerFactory, ItemType
    )

    gpkg_path = get_test_gpkg_path()
    factory = PerItemLayerFactory(gpkg_path)

    # Create some items
    for i in range(3):
        factory.create_item_layer(
            item_type=ItemType.MARKER_CLUE,
            display_name=f"Status Test {i+1}",
            add_to_project=True
        )
    print("  Created 3 items")

    # Get status
    status = factory.get_performance_status()
    print(f"  Status: {status['total_items']} total, {status['active_items']} active")
    print(f"  Scale visibility enabled: {status['scale_visibility_enabled']}")

    assert status["total_items"] >= 3, f"Expected 3+ total, got {status['total_items']}"
    assert "spatial_indexes" in status, "Should have spatial_indexes"
    assert "recommendations" in status, "Should have recommendations"
    print("  Status fields present: OK")

    print("  PASSED")
    return True


# Allow running from command line for syntax check
if __name__ == "__main__":
    print("This test must be run from QGIS Python console.")
    print("Use: from sartracker.tests.test_per_item_layer_factory import run_all_tests")
    print("     run_all_tests()")
