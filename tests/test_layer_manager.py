# -*- coding: utf-8 -*-
"""
Tests for SAR Tracker Layer Manager

Basic smoke tests to verify layer schema and manager functionality.
These tests can run without a full QGIS environment.

Qt5/Qt6 Compatible: Uses qgis.PyQt for all Qt imports.
"""

import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))


def test_schema_import():
    """Test that schema module can be imported."""
    try:
        from layers import schema
        assert schema.SAR_LAYER_SCHEMA_VERSION == 4
        assert schema.ROOT_GROUP_NAME == "SAR Tracker"
        print("✓ Schema module imported successfully")
        return True
    except ImportError as e:
        if 'qgis' in str(e):
            print("⊘ Schema import skipped (requires QGIS environment)")
            return True  # Skip test if QGIS not available
        print(f"✗ Schema import failed: {e}")
        return False
    except Exception as e:
        print(f"✗ Schema import failed: {e}")
        return False


def test_layer_ids_constants():
    """Test that LayerIds constants are defined."""
    try:
        from layers.schema import LayerIds

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

        print(f"✓ All {len(required_ids)} required layer IDs present")
        return True
    except Exception as e:
        print(f"✗ Layer IDs test failed: {e}")
        return False


def test_group_names_constants():
    """Test that GroupNames constants are defined."""
    try:
        from layers.schema import GroupNames

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

        print(f"✓ All {len(required_groups)} required group names present")
        return True
    except Exception as e:
        print(f"✗ Group names test failed: {e}")
        return False


def test_expected_structure():
    """Test that expected structure can be generated."""
    try:
        from layers.schema import get_expected_structure, GroupNames

        structure = get_expected_structure()

        assert structure is not None
        assert structure.name == GroupNames.ROOT
        assert structure.subgroups is not None
        assert len(structure.subgroups) >= 3, f"Expected at least 3 subgroups, got {len(structure.subgroups)}"

        # Verify key groups exist
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

        print(f"✓ Expected structure generated with {len(structure.subgroups)} groups")
        return True
    except Exception as e:
        print(f"✗ Expected structure test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_helicopter_fields():
    """Test that helicopter layers have correct fields."""
    try:
        from layers.schema import get_expected_structure, GroupNames

        structure = get_expected_structure()

        # Find helicopters group
        helicopters_group = None
        for group in structure.subgroups:
            if group.name == GroupNames.HELICOPTERS:
                helicopters_group = group
                break

        assert helicopters_group is not None, "Helicopters group not found"
        assert helicopters_group.layers is not None
        assert len(helicopters_group.layers) == 4, f"Expected 4 helicopter layers, got {len(helicopters_group.layers)}"

        # Verify first helicopter layer has required fields
        heli_layer = helicopters_group.layers[0]
        required_fields = ['call_sign', 'hex_id', 'last_update', 'speed', 'heading', 'altitude']
        field_names = [f['name'] for f in heli_layer.fields]

        for field_name in required_fields:
            assert field_name in field_names, f"Missing field: {field_name}"

        print(f"✓ Helicopter layers configured correctly with {len(required_fields)} required fields")
        return True
    except Exception as e:
        print(f"✗ Helicopter fields test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_marker_layer_fields_match_manager():
    """Ensure marker layer schema matches MarkerLayerManager expectations."""
    try:
        from layers.schema import get_layer_by_id, LayerIds

        expected_fields = {
            LayerIds.MARKERS_IPP_LKP: [
                "id", "name", "subject_category", "description",
                "lat", "lon", "irish_grid_e", "irish_grid_n", "created",
                "created_at", "updated_at", "updated_by", "coordinator_ids", "attachment_path"
            ],
            LayerIds.MARKERS_CLUES: [
                "id", "name", "clue_type", "confidence",
                "description", "lat", "lon", "irish_grid_e", "irish_grid_n", "created",
                "created_at", "updated_at", "updated_by", "coordinator_ids", "attachment_path"
            ],
            LayerIds.MARKERS_HAZARDS: [
                "id", "name", "hazard_type", "severity",
                "description", "lat", "lon", "irish_grid_e", "irish_grid_n", "created",
                "created_at", "updated_at", "updated_by", "coordinator_ids", "attachment_path"
            ],
            LayerIds.MARKERS_CASUALTIES: [
                "id", "name", "condition", "treatment", "evacuation_priority",
                "description", "found_by", "lat", "lon", "irish_grid_e", "irish_grid_n", "created",
                "created_at", "updated_at", "updated_by", "coordinator_ids", "attachment_path"
            ]
        }

        for layer_id, field_names in expected_fields.items():
            layer_def = get_layer_by_id(layer_id)
            assert layer_def is not None, f"Layer definition missing for {layer_id}"
            assert layer_def.fields is not None, f"No fields defined for {layer_id}"
            actual_fields = [field['name'] for field in layer_def.fields]
            assert actual_fields == field_names, f"{layer_id} fields mismatch: {actual_fields}"

        print("✓ Marker layer schemas align with MarkerLayerManager")
        return True
    except Exception as e:
        print(f"✗ Marker layer schema alignment test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_tracking_and_drawing_layer_fields():
    """Ensure tracking and drawing schemas match manager expectations."""
    try:
        from layers.schema import get_layer_by_id, LayerIds

        expectations = {
            LayerIds.LINES: [
                "id", "name", "description", "color", "width",
                "distance_m", "created", "temporary_measure"
            ],
            LayerIds.RANGE_RINGS: [
                "id", "name", "center_lat", "center_lon", "radius_m",
                "label", "color", "lpb_category", "percentile", "created"
            ],
            LayerIds.SEARCH_AREAS: [
                "id", "name", "team", "status", "priority", "area_sqkm", "POA",
                "POD", "terrain", "search_method", "color", "start_time",
                "end_time", "notes", "created"
            ],
            LayerIds.SEARCH_SECTORS: [
                "id", "name", "center_lat", "center_lon",
                "start_bearing", "end_bearing", "radius_m", "arc_length_deg",
                "area_sqkm", "priority", "color", "created"
            ],
            LayerIds.TEXT_LABELS: [
                "id", "text", "lat", "lon", "font_size", "color", "rotation", "created"
            ],
            LayerIds.BEARING_LINES: [
                "id", "name", "origin_lat", "origin_lon",
                "bearing", "distance_m", "label", "color", "created"
            ],
        }

        for layer_id, field_names in expectations.items():
            layer_def = get_layer_by_id(layer_id)
            assert layer_def is not None, f"Missing definition for {layer_id}"
            assert layer_def.fields is not None, f"No fields defined for {layer_id}"
            actual = [field['name'] for field in layer_def.fields]
            assert actual == field_names, f"{layer_id} schema mismatch: {actual}"

        print("✓ Tracking and drawing layer schemas align with managers")
        return True
    except Exception as e:
        print(f"✗ Tracking/drawing schema alignment test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_layer_by_id_lookup():
    """Test that layers can be looked up by ID."""
    try:
        from layers.schema import get_layer_by_id, LayerIds

        # Test valid layer
        layer = get_layer_by_id(LayerIds.HELICOPTER_1)
        assert layer is not None
        assert layer.name == "Helicopter 1"
        assert layer.geometry_type == "Point"

        # Test another layer
        layer = get_layer_by_id(LayerIds.MARKERS_CLUES)
        assert layer is not None
        assert layer.name == "Clues"

        # Test invalid layer
        layer = get_layer_by_id("nonexistent_layer")
        assert layer is None

        print("✓ Layer lookup by ID working correctly")
        return True
    except Exception as e:
        print(f"✗ Layer lookup test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_artifact_layer_map():
    """Test that artifact types map to correct layer IDs."""
    try:
        from layers.schema import ARTIFACT_LAYER_MAP, LayerIds

        assert 'marker_clue' in ARTIFACT_LAYER_MAP
        assert ARTIFACT_LAYER_MAP['marker_clue'] == LayerIds.MARKERS_CLUES

        assert 'helicopter_1' in ARTIFACT_LAYER_MAP
        assert ARTIFACT_LAYER_MAP['helicopter_1'] == LayerIds.HELICOPTER_1

        print(f"✓ Artifact layer map contains {len(ARTIFACT_LAYER_MAP)} mappings")
        return True
    except Exception as e:
        print(f"✗ Artifact layer map test failed: {e}")
        return False


def test_helicopter_manager_colors():
    """Test that helicopter colors are defined."""
    try:
        from layers.helicopter_manager import HELICOPTER_COLORS

        assert len(HELICOPTER_COLORS) == 4
        assert 1 in HELICOPTER_COLORS
        assert 2 in HELICOPTER_COLORS
        assert 3 in HELICOPTER_COLORS
        assert 4 in HELICOPTER_COLORS

        # Verify color format
        for slot, color in HELICOPTER_COLORS.items():
            assert color.startswith('#')
            assert len(color) == 7  # #RRGGBB format

        print("✓ Helicopter colors defined for all 4 slots")
        return True
    except ImportError as e:
        if 'qgis' in str(e):
            print("⊘ Helicopter colors test skipped (requires QGIS environment)")
            return True  # Skip test if QGIS not available
        print(f"✗ Helicopter colors test failed: {e}")
        return False
    except Exception as e:
        print(f"✗ Helicopter colors test failed: {e}")
        return False


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
