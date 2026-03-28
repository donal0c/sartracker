# -*- coding: utf-8 -*-
"""
Tests for SAR Tracker Layer Manager

Basic smoke tests to verify layer schema and manager functionality.
These tests can run without a full QGIS environment.

Qt5/Qt6 Compatible: Uses qgis.PyQt for all Qt imports.
"""

import sys
import os
import importlib

import pytest

# Add parent directory to path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))


def _import_layers_module(module_name: str):
    sys.modules.pop("layers", None)
    sys.modules.pop(module_name, None)
    return importlib.import_module(module_name)


def test_schema_import():
    """Test that schema module can be imported."""
    try:
        schema = _import_layers_module("sartracker.layers.schema")
    except ImportError as e:
        if 'qgis' in str(e):
            pytest.skip("Schema import requires QGIS environment")
        raise

    assert schema.SAR_LAYER_SCHEMA_VERSION == 4
    assert schema.ROOT_GROUP_NAME == "SAR Tracker"


def test_layer_ids_constants():
    """Test that LayerIds constants are defined."""
    LayerIds = _import_layers_module("sartracker.layers.schema").LayerIds

    required_ids = [
        'CURRENT_ACTIVE',
        'BREADCRUMBS',
        'LINES',
        'RANGE_RINGS',
        'MARKERS_IPP_LKP',
        'MARKERS_CLUES',
        'MARKERS_HAZARDS',
        'MARKERS_CASUALTIES',
        'HELICOPTER_1',
        'HELICOPTER_2',
        'HELICOPTER_3',
        'HELICOPTER_4',
        'SEARCH_AREAS',
        'SEARCH_SECTORS',
        'TEXT_LABELS'
    ]

    for layer_id in required_ids:
        assert hasattr(LayerIds, layer_id), f"Missing layer ID: {layer_id}"


def test_group_names_constants():
    """Test that GroupNames constants are defined."""
    GroupNames = _import_layers_module("sartracker.layers.schema").GroupNames

    required_groups = [
        'ROOT',
        'TRACKING',
        'HELICOPTERS',
        'MAP_TOOLS',
        'MAP_TOOLS_IPP_LKP',
        'MAP_TOOLS_CLUES',
        'MAP_TOOLS_HAZARDS',
        'MAP_TOOLS_CASUALTIES',
        'MAP_TOOLS_SEARCH_AREAS',
        'MAP_TOOLS_SEARCH_SECTORS',
        'MAP_TOOLS_RANGE_RINGS',
        'MAP_TOOLS_BEARING_LINES',
        'MAP_TOOLS_LINES',
        'MAP_TOOLS_TEXT_LABELS'
    ]

    for group_name in required_groups:
        assert hasattr(GroupNames, group_name), f"Missing group name: {group_name}"


def test_expected_structure():
    """Test that expected structure can be generated."""
    schema = _import_layers_module("sartracker.layers.schema")
    get_expected_structure = schema.get_expected_structure
    GroupNames = schema.GroupNames

    structure = get_expected_structure()

    assert structure is not None
    assert structure.name == GroupNames.ROOT
    assert structure.subgroups is not None
    assert len(structure.subgroups) >= 3, f"Expected at least 3 subgroups, got {len(structure.subgroups)}"

    group_names = [g.name for g in structure.subgroups]
    assert GroupNames.TRACKING in group_names
    assert GroupNames.MAP_TOOLS in group_names
    assert GroupNames.HELICOPTERS in group_names

    map_tools_group = None
    for group in structure.subgroups:
        if group.name == GroupNames.MAP_TOOLS:
            map_tools_group = group
            break

    assert map_tools_group is not None, "Map Tools group not found"
    map_tools_subgroups = [g.name for g in map_tools_group.subgroups or []]
    assert GroupNames.MAP_TOOLS_SEARCH_SECTORS in map_tools_subgroups
    assert GroupNames.MAP_TOOLS_TEXT_LABELS in map_tools_subgroups


def test_helicopter_fields():
    """Test that helicopter layers have correct fields."""
    schema = _import_layers_module("sartracker.layers.schema")
    get_expected_structure = schema.get_expected_structure
    GroupNames = schema.GroupNames

    structure = get_expected_structure()

    helicopters_group = None
    for group in structure.subgroups:
        if group.name == GroupNames.HELICOPTERS:
            helicopters_group = group
            break

    assert helicopters_group is not None, "Helicopters group not found"
    assert helicopters_group.layers is not None
    assert len(helicopters_group.layers) == 4, f"Expected 4 helicopter layers, got {len(helicopters_group.layers)}"

    heli_layer = helicopters_group.layers[0]
    required_fields = ['call_sign', 'hex_id', 'last_update', 'speed', 'heading', 'altitude']
    field_names = [f['name'] for f in heli_layer.fields]

    for field_name in required_fields:
        assert field_name in field_names, f"Missing field: {field_name}"


def test_marker_layer_fields_match_manager():
    """Ensure marker layer schema matches MarkerLayerManager expectations."""
    schema = _import_layers_module("sartracker.layers.schema")
    get_layer_by_id = schema.get_layer_by_id
    LayerIds = schema.LayerIds

    expected_fields = {
        LayerIds.MARKERS_IPP_LKP: [
            "id", "name", "subject_category", "description",
            "lat", "lon", "irish_grid_e", "irish_grid_n", "created",
            "created_at", "updated_at", "updated_by", "coordinator_ids", "attachment_path",
            "display_order"
        ],
        LayerIds.MARKERS_CLUES: [
            "id", "name", "clue_type", "confidence", "found_by",
            "description", "lat", "lon", "irish_grid_e", "irish_grid_n", "created",
            "created_at", "updated_at", "updated_by", "coordinator_ids", "attachment_path",
            "display_order"
        ],
        LayerIds.MARKERS_HAZARDS: [
            "id", "name", "hazard_type", "severity",
            "description", "lat", "lon", "irish_grid_e", "irish_grid_n", "created",
            "created_at", "updated_at", "updated_by", "coordinator_ids", "attachment_path",
            "display_order"
        ],
        LayerIds.MARKERS_CASUALTIES: [
            "id", "name", "condition", "treatment", "evacuation_priority",
            "description", "found_by", "lat", "lon", "irish_grid_e", "irish_grid_n", "created",
            "created_at", "updated_at", "updated_by", "coordinator_ids", "attachment_path",
            "display_order"
        ]
    }

    for layer_id, field_names in expected_fields.items():
        layer_def = get_layer_by_id(layer_id)
        assert layer_def is not None, f"Layer definition missing for {layer_id}"
        assert layer_def.fields is not None, f"No fields defined for {layer_id}"
        actual_fields = [field['name'] for field in layer_def.fields]
        assert actual_fields == field_names, f"{layer_id} fields mismatch: {actual_fields}"


def test_tracking_and_drawing_layer_fields():
    """Ensure tracking and drawing schemas match manager expectations."""
    schema = _import_layers_module("sartracker.layers.schema")
    get_layer_by_id = schema.get_layer_by_id
    LayerIds = schema.LayerIds

    expectations = {
        LayerIds.LINES: [
            "id", "name", "description", "color", "width",
            "distance_m", "created", "temporary_measure", "display_order"
        ],
        LayerIds.RANGE_RINGS: [
            "id", "name", "center_lat", "center_lon", "radius_m",
            "label", "color", "lpb_category", "percentile", "created", "display_order"
        ],
        LayerIds.SEARCH_AREAS: [
            "id", "name", "team", "status", "priority", "area_sqkm", "POA",
            "POD", "terrain", "search_method", "color", "start_time",
            "end_time", "notes", "created", "display_order"
        ],
        LayerIds.SEARCH_SECTORS: [
            "id", "name", "center_lat", "center_lon",
            "start_bearing", "end_bearing", "radius_m", "arc_length_deg",
            "area_sqkm", "priority", "color", "created", "display_order"
        ],
        LayerIds.TEXT_LABELS: [
            "id", "text", "lat", "lon", "font_size", "color", "rotation", "created",
            "display_order"
        ],
        LayerIds.BEARING_LINES: [
            "id", "name", "origin_lat", "origin_lon",
            "bearing", "distance_m", "label", "color", "created", "display_order"
        ],
    }

    for layer_id, field_names in expectations.items():
        layer_def = get_layer_by_id(layer_id)
        assert layer_def is not None, f"Missing definition for {layer_id}"
        assert layer_def.fields is not None, f"No fields defined for {layer_id}"
        actual = [field['name'] for field in layer_def.fields]
        assert actual == field_names, f"{layer_id} schema mismatch: {actual}"


def test_layer_by_id_lookup():
    """Test that layers can be looked up by ID."""
    schema = _import_layers_module("sartracker.layers.schema")
    get_layer_by_id = schema.get_layer_by_id
    LayerIds = schema.LayerIds

    layer = get_layer_by_id(LayerIds.HELICOPTER_1)
    assert layer is not None
    assert layer.name == "Helicopter 1"
    assert layer.geometry_type == "Point"

    layer = get_layer_by_id(LayerIds.MARKERS_CLUES)
    assert layer is not None
    assert layer.name == "Clues"

    layer = get_layer_by_id("nonexistent_layer")
    assert layer is None


def test_artifact_layer_map():
    """Test that artifact types map to correct layer IDs."""
    schema = _import_layers_module("sartracker.layers.schema")
    ARTIFACT_LAYER_MAP = schema.ARTIFACT_LAYER_MAP
    LayerIds = schema.LayerIds

    assert 'marker_clue' in ARTIFACT_LAYER_MAP
    assert ARTIFACT_LAYER_MAP['marker_clue'] == LayerIds.MARKERS_CLUES

    assert 'helicopter_1' in ARTIFACT_LAYER_MAP
    assert ARTIFACT_LAYER_MAP['helicopter_1'] == LayerIds.HELICOPTER_1


def test_helicopter_manager_colors():
    """Test that helicopter colors are defined."""
    try:
        HELICOPTER_COLORS = _import_layers_module("sartracker.layers.helicopter_manager").HELICOPTER_COLORS
    except ImportError as e:
        if 'qgis' in str(e):
            pytest.skip("Helicopter colors require QGIS environment")
        raise

    assert len(HELICOPTER_COLORS) == 4
    assert 1 in HELICOPTER_COLORS
    assert 2 in HELICOPTER_COLORS
    assert 3 in HELICOPTER_COLORS
    assert 4 in HELICOPTER_COLORS

    for slot, color in HELICOPTER_COLORS.items():
        assert color.startswith('#')
        assert len(color) == 7


def run_all_tests():
    """Run all layer manager tests."""
    print("=" * 60)
    print("SAR Tracker Layer Manager - Smoke Tests")
    print("=" * 60)
    print()

    tests = [
        ("Schema Import", test_schema_import),
        ("Layer IDs Constants", test_layer_ids_constants),
        ("Group Names Constants", test_group_names_constants),
        ("Expected Structure", test_expected_structure),
        ("Helicopter Fields", test_helicopter_fields),
        ("Marker Layer Fields", test_marker_layer_fields_match_manager),
        ("Tracking & Drawing Layer Fields", test_tracking_and_drawing_layer_fields),
        ("Layer Lookup by ID", test_layer_by_id_lookup),
        ("Artifact Layer Map", test_artifact_layer_map),
        ("Helicopter Colors", test_helicopter_manager_colors)
    ]

    results = []
    for test_name, test_func in tests:
        print(f"Running: {test_name}")
        try:
            result = test_func()
            results.append((test_name, result))
        except Exception as e:
            print(f"✗ {test_name} crashed: {e}")
            import traceback
            traceback.print_exc()
            results.append((test_name, False))
        print()

    print("=" * 60)
    print("Test Summary")
    print("=" * 60)

    passed = sum(1 for _, result in results if result)
    total = len(results)

    for test_name, result in results:
        status = "✓ PASS" if result else "✗ FAIL"
        print(f"{status}: {test_name}")

    print()
    print(f"Results: {passed}/{total} tests passed")

    if passed == total:
        print("✓ ALL TESTS PASSED")
        return 0
    else:
        print(f"✗ {total - passed} TEST(S) FAILED")
        return 1


if __name__ == "__main__":
    sys.exit(run_all_tests())
