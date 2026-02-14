# -*- coding: utf-8 -*-
"""Regression tests for cursor AttributeError and tracking layer ID lookup.

Bug 1: MarkerMapTool.activate() called self.cursor() which does not exist
       on all QGIS/Qt binding combinations, raising AttributeError.
       Fixed by using the stored self._default_cursor reference instead.

Bug 2: get_layer_by_id() returned None for LayerIds.CURRENT_ACTIVE and
       LayerIds.BREADCRUMBS because their LayerDefinition entries were
       removed from get_expected_structure() during the per-device migration,
       while the fallback code in tracking_manager still relied on them.
       Fixed by restoring LayerDefinition entries with auto_create=False.
"""

import ast
import os


# =========================================================================
# Bug 1: MarkerMapTool cursor regression (source-level verification)
#
# MarkerMapTool requires qgis.gui which is unavailable outside QGIS,
# so we verify the fix by inspecting the source AST directly.
# =========================================================================

_MARKER_TOOL_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    "maptools", "marker_tool.py",
)


def _get_marker_tool_ast():
    """Parse marker_tool.py into an AST."""
    with open(_MARKER_TOOL_PATH, "r", encoding="utf-8") as f:
        return ast.parse(f.read(), filename=_MARKER_TOOL_PATH)


def _find_class(tree, class_name):
    """Find a class definition by name in an AST."""
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            return node
    return None


def _find_method(class_node, method_name):
    """Find a method definition by name in a class AST node."""
    for node in class_node.body:
        if isinstance(node, ast.FunctionDef) and node.name == method_name:
            return node
    return None


def _method_calls_self_cursor(method_node):
    """Check whether a method body contains any call to self.cursor()."""
    for node in ast.walk(method_node):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        # Match self.cursor()
        if (isinstance(func, ast.Attribute)
                and func.attr == "cursor"
                and isinstance(func.value, ast.Name)
                and func.value.id == "self"):
            return True
    return False


def test_activate_does_not_call_self_cursor():
    """activate() must not call self.cursor() — it fails on some Qt bindings."""
    tree = _get_marker_tool_ast()
    cls = _find_class(tree, "MarkerMapTool")
    assert cls is not None, "MarkerMapTool class not found"

    activate = _find_method(cls, "activate")
    assert activate is not None, "activate method not found"

    assert not _method_calls_self_cursor(activate), (
        "activate() still calls self.cursor() — this raises AttributeError "
        "on QGIS builds where QgsMapTool does not expose cursor()"
    )


def test_activate_uses_active_cursor():
    """activate() should use self._active_cursor to preserve context-specific cursors.

    When set_marker_context('clue') is called before setMapTool(), the colored
    cursor is stored in _active_cursor.  activate() must apply _active_cursor
    (not _default_cursor) so the colored cursor survives tool activation.
    """
    tree = _get_marker_tool_ast()
    cls = _find_class(tree, "MarkerMapTool")
    activate = _find_method(cls, "activate")
    assert activate is not None

    # Check that _active_cursor appears in the activate method body
    found = False
    for node in ast.walk(activate):
        if (isinstance(node, ast.Attribute)
                and node.attr == "_active_cursor"
                and isinstance(node.value, ast.Name)
                and node.value.id == "self"):
            found = True
            break

    assert found, (
        "activate() does not reference self._active_cursor — "
        "context-specific cursors (clue/casualty colors) will be lost on activation"
    )


def test_active_cursor_initialized_in_init():
    """__init__ must set _active_cursor so activate() never reads an unset attribute."""
    tree = _get_marker_tool_ast()
    cls = _find_class(tree, "MarkerMapTool")
    init = _find_method(cls, "__init__")
    assert init is not None

    found = False
    for node in ast.walk(init):
        if (isinstance(node, ast.Attribute)
                and node.attr == "_active_cursor"
                and isinstance(node.value, ast.Name)
                and node.value.id == "self"):
            found = True
            break

    assert found, (
        "__init__() does not set self._active_cursor — "
        "activate() will raise AttributeError on first tool activation"
    )


def test_set_cursor_with_fallback_updates_active_cursor_both_paths():
    """_set_cursor_with_fallback must update _active_cursor in BOTH try and except paths.

    The except path runs on Qt builds where cursor creation fails — exactly
    the platforms where this bug was reported.  If _active_cursor is only
    assigned in the try block, a cursor construction failure would leave
    _active_cursor stale, and the next activate() would apply the wrong cursor.
    """
    tree = _get_marker_tool_ast()
    cls = _find_class(tree, "MarkerMapTool")
    method = _find_method(cls, "_set_cursor_with_fallback")
    assert method is not None

    # Find the Try node inside the method
    try_node = None
    for node in ast.walk(method):
        if isinstance(node, ast.Try):
            try_node = node
            break

    assert try_node is not None, (
        "_set_cursor_with_fallback has no try/except — exception safety removed"
    )

    def _has_active_cursor_assign(stmts):
        """Check if a list of AST statements assigns self._active_cursor."""
        for stmt in stmts:
            for node in ast.walk(stmt):
                if isinstance(node, ast.Assign):
                    for target in node.targets:
                        if (isinstance(target, ast.Attribute)
                                and target.attr == "_active_cursor"
                                and isinstance(target.value, ast.Name)
                                and target.value.id == "self"):
                            return True
        return False

    assert _has_active_cursor_assign(try_node.body), (
        "_set_cursor_with_fallback() try block does not assign self._active_cursor — "
        "activate() will use a stale cursor after context changes"
    )

    assert len(try_node.handlers) >= 1, "No except handler found"
    assert _has_active_cursor_assign(try_node.handlers[0].body), (
        "_set_cursor_with_fallback() except block does not assign self._active_cursor — "
        "on Qt builds where cursor creation fails, activate() will apply a stale cursor"
    )


def test_set_cursor_with_fallback_does_not_call_self_cursor():
    """_set_cursor_with_fallback must not rely on self.cursor()."""
    tree = _get_marker_tool_ast()
    cls = _find_class(tree, "MarkerMapTool")
    assert cls is not None

    method = _find_method(cls, "_set_cursor_with_fallback")
    assert method is not None, "_set_cursor_with_fallback method not found"

    assert not _method_calls_self_cursor(method), (
        "_set_cursor_with_fallback() still calls self.cursor() — "
        "this silently fails on Qt bindings without cursor() getter"
    )


# =========================================================================
# Bug 2: Tracking layer ID schema lookup regression
# =========================================================================

def test_get_layer_by_id_resolves_current_active():
    """get_layer_by_id must return a definition for CURRENT_ACTIVE (fallback path)."""
    from sartracker.layers.schema import get_layer_by_id, LayerIds

    layer_def = get_layer_by_id(LayerIds.CURRENT_ACTIVE)
    assert layer_def is not None, (
        f"get_layer_by_id('{LayerIds.CURRENT_ACTIVE}') returned None — "
        "tracking fallback will raise 'Unknown layer id'"
    )
    assert layer_def.layer_id == LayerIds.CURRENT_ACTIVE
    assert layer_def.auto_create is False


def test_get_layer_by_id_resolves_breadcrumbs():
    """get_layer_by_id must return a definition for BREADCRUMBS (fallback path)."""
    from sartracker.layers.schema import get_layer_by_id, LayerIds

    layer_def = get_layer_by_id(LayerIds.BREADCRUMBS)
    assert layer_def is not None, (
        f"get_layer_by_id('{LayerIds.BREADCRUMBS}') returned None — "
        "tracking fallback will raise 'Unknown layer id'"
    )
    assert layer_def.layer_id == LayerIds.BREADCRUMBS
    assert layer_def.auto_create is False


def test_tracking_layer_geometry_types():
    """CURRENT_ACTIVE must be Point, BREADCRUMBS must be LineString.

    Breadcrumbs are polyline trail segments (QgsGeometry.fromPolylineXY).
    A Point geometry type causes 'geometry type is not compatible' on commit.
    """
    from sartracker.layers.schema import get_layer_by_id, LayerIds

    current = get_layer_by_id(LayerIds.CURRENT_ACTIVE)
    assert current is not None
    assert current.geometry_type == "Point", (
        f"CURRENT_ACTIVE geometry_type is '{current.geometry_type}' — must be 'Point'"
    )

    breadcrumbs = get_layer_by_id(LayerIds.BREADCRUMBS)
    assert breadcrumbs is not None
    assert breadcrumbs.geometry_type == "LineString", (
        f"BREADCRUMBS geometry_type is '{breadcrumbs.geometry_type}' — "
        "must be 'LineString' (trails are polyline segments)"
    )


def test_current_active_has_correct_fields():
    """CURRENT_ACTIVE definition should carry the expected tracking fields."""
    from sartracker.layers.schema import get_layer_by_id, LayerIds

    layer_def = get_layer_by_id(LayerIds.CURRENT_ACTIVE)
    assert layer_def is not None
    field_names = [f["name"] for f in layer_def.fields]
    for required in ("device_id", "name", "timestamp"):
        assert required in field_names, f"Missing field '{required}' in CURRENT_ACTIVE"


def test_breadcrumbs_has_correct_fields():
    """BREADCRUMBS definition should carry the expected breadcrumb fields."""
    from sartracker.layers.schema import get_layer_by_id, LayerIds

    layer_def = get_layer_by_id(LayerIds.BREADCRUMBS)
    assert layer_def is not None
    field_names = [f["name"] for f in layer_def.fields]
    for required in ("device_id", "name", "timestamp"):
        assert required in field_names, f"Missing field '{required}' in BREADCRUMBS"


def test_layer_group_paths_include_tracking_layers():
    """LAYER_GROUP_PATHS must have entries for Current Positions and Breadcrumbs."""
    from sartracker.layers.schema import LAYER_GROUP_PATHS, GroupNames

    assert "Current Positions" in LAYER_GROUP_PATHS, (
        "LAYER_GROUP_PATHS missing 'Current Positions' — "
        "_ensure_schema_layer will fall back to ROOT group"
    )
    assert "Breadcrumbs" in LAYER_GROUP_PATHS, (
        "LAYER_GROUP_PATHS missing 'Breadcrumbs' — "
        "_ensure_schema_layer will fall back to ROOT group"
    )

    # Verify paths point into the Tracking group
    cp_path = LAYER_GROUP_PATHS["Current Positions"]
    assert GroupNames.TRACKING in cp_path

    bc_path = LAYER_GROUP_PATHS["Breadcrumbs"]
    assert GroupNames.TRACKING in bc_path


def test_tracking_definitions_in_structure_tree():
    """Tracking group in get_expected_structure() must contain the fallback layers."""
    from sartracker.layers.schema import get_expected_structure, GroupNames, LayerIds

    structure = get_expected_structure()

    # Find Tracking group
    tracking = None
    for group in structure.subgroups:
        if group.name == GroupNames.TRACKING:
            tracking = group
            break

    assert tracking is not None, "Tracking group not found in structure"
    assert tracking.subgroups, "Tracking group has no subgroups"

    # Collect all layer IDs under Tracking (in subgroups)
    layer_ids_in_tracking = []
    for subgroup in tracking.subgroups:
        if subgroup.layers:
            layer_ids_in_tracking.extend(l.layer_id for l in subgroup.layers)

    assert LayerIds.CURRENT_ACTIVE in layer_ids_in_tracking, (
        "CURRENT_ACTIVE not found in Tracking subgroups"
    )
    assert LayerIds.BREADCRUMBS in layer_ids_in_tracking, (
        "BREADCRUMBS not found in Tracking subgroups"
    )
