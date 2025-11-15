# -*- coding: utf-8 -*-
"""
SAR Tracker Layer Schema Definition

Defines the canonical layer hierarchy structure, constants, and versioning
for the SAR Tracker QGIS plugin. This module provides the schema that ensures
all mission artifacts are stored in a predictable, persistent structure.

Qt5/Qt6 Compatible: Uses qgis.PyQt for all Qt imports.
"""

from typing import Dict, List, Optional, Any
from dataclasses import dataclass


# Schema version - increment when structure changes
SAR_LAYER_SCHEMA_VERSION = 1

# Root group name
ROOT_GROUP_NAME = "SAR Tracker"

# Layer IDs (unique identifiers for each layer)
class LayerIds:
    """Unique identifiers for all SAR Tracker layers."""
    # Current Positions
    CURRENT_ACTIVE = "sar_current_positions_active"

    # Breadcrumbs
    BREADCRUMBS = "sar_breadcrumbs"

    # Lines
    LINES = "sar_lines"

    # Rings
    RANGE_RINGS = "sar_range_rings"

    # Markers
    MARKERS_IPP_LKP = "sar_markers_ipp_lkp"
    MARKERS_CLUES = "sar_markers_clues"
    MARKERS_HAZARDS = "sar_markers_hazards"
    MARKERS_CASUALTIES = "sar_markers_casualties"

    # Clues (legacy compatibility)
    CLUES = "sar_clues"

    # Helicopters
    HELICOPTER_1 = "sar_helicopter_1"
    HELICOPTER_2 = "sar_helicopter_2"
    HELICOPTER_3 = "sar_helicopter_3"
    HELICOPTER_4 = "sar_helicopter_4"

    # Mission Overlays
    MISSION_OVERLAYS = "sar_mission_overlays"

    # Drawing layers
    BEARING_LINES = "sar_bearing_lines"
    SEARCH_AREAS = "sar_search_areas"
    SEARCH_SECTORS = "sar_search_sectors"
    TEXT_LABELS = "sar_text_labels"


# Group Names
class GroupNames:
    """Names for all layer tree groups."""
    ROOT = ROOT_GROUP_NAME
    CURRENT_POSITIONS = "Current Positions"
    BREADCRUMBS = "Breadcrumbs"
    LINES = "Lines"
    RINGS = "Rings"
    MARKERS = "Markers"
    CLUES = "Clues"
    HELICOPTERS = "Helicopters"
    MISSION_OVERLAYS = "Mission Overlays"


@dataclass
class LayerDefinition:
    """Definition of a single layer in the schema."""
    layer_id: str
    name: str
    geometry_type: str  # 'Point', 'LineString', 'Polygon'
    crs_epsg: int = 4326  # Default WGS84
    fields: Optional[List[Dict[str, Any]]] = None
    metadata: Optional[Dict[str, str]] = None
    position: int = 0  # Position within group (0 = top)
    auto_create: bool = False  # Whether to auto-create the layer during structure ensure


@dataclass
class GroupDefinition:
    """Definition of a layer tree group in the schema."""
    name: str
    parent_path: Optional[List[str]] = None  # Path to parent (None = root)
    layers: Optional[List[LayerDefinition]] = None
    subgroups: Optional[List['GroupDefinition']] = None
    metadata: Optional[Dict[str, str]] = None
    position: int = 0  # Position within parent


# ---------------------------------------------------------------------------
# Marker layer field definitions
# ---------------------------------------------------------------------------

MARKER_COMMON_GEO_FIELDS = [
    {"name": "lat", "type": "Double"},
    {"name": "lon", "type": "Double"},
    {"name": "irish_grid_e", "type": "Double"},
    {"name": "irish_grid_n", "type": "Double"},
    {"name": "created", "type": "DateTime"}
]

IPP_LKP_FIELDS = [
    {"name": "id", "type": "String", "length": 36},
    {"name": "name", "type": "String", "length": 120},
    {"name": "subject_category", "type": "String", "length": 60},
    {"name": "description", "type": "String", "length": 255},
    *MARKER_COMMON_GEO_FIELDS
]

CLUE_FIELDS = [
    {"name": "id", "type": "String", "length": 36},
    {"name": "name", "type": "String", "length": 120},
    {"name": "clue_type", "type": "String", "length": 60},
    {"name": "confidence", "type": "String", "length": 20},
    {"name": "description", "type": "String", "length": 255},
    *MARKER_COMMON_GEO_FIELDS
]

HAZARD_FIELDS = [
    {"name": "id", "type": "String", "length": 36},
    {"name": "name", "type": "String", "length": 120},
    {"name": "hazard_type", "type": "String", "length": 60},
    {"name": "severity", "type": "String", "length": 20},
    {"name": "description", "type": "String", "length": 255},
    *MARKER_COMMON_GEO_FIELDS
]

CASUALTY_FIELDS = [
    {"name": "id", "type": "String", "length": 36},
    {"name": "name", "type": "String", "length": 120},
    {"name": "condition", "type": "String", "length": 60},
    {"name": "treatment", "type": "String", "length": 120},
    {"name": "evacuation_priority", "type": "String", "length": 30},
    {"name": "description", "type": "String", "length": 255},
    {"name": "found_by", "type": "String", "length": 120},
    *MARKER_COMMON_GEO_FIELDS
]


def get_expected_structure() -> GroupDefinition:
    """
    Get the complete expected layer structure for SAR Tracker.

    Returns:
        GroupDefinition: Root group with nested structure
    """
    # Define layer fields for helicopters
    helicopter_fields = [
        {"name": "call_sign", "type": "String", "length": 50},
        {"name": "hex_id", "type": "String", "length": 20},
        {"name": "last_update", "type": "DateTime"},
        {"name": "speed", "type": "Double"},
        {"name": "heading", "type": "Double"},
        {"name": "altitude", "type": "Double"},
        {"name": "timestamp", "type": "DateTime"}
    ]

    # Define the complete structure
    root = GroupDefinition(
        name=GroupNames.ROOT,
        parent_path=None,
        metadata={"schema_version": str(SAR_LAYER_SCHEMA_VERSION)},
        subgroups=[
            # Current Positions group
            GroupDefinition(
                name=GroupNames.CURRENT_POSITIONS,
                parent_path=[GroupNames.ROOT],
                position=0,
                layers=[
                    LayerDefinition(
                        layer_id=LayerIds.CURRENT_ACTIVE,
                        name="Current – Active",
                        geometry_type="Point",
                        fields=[
                            {"name": "device_id", "type": "String", "length": 50},
                            {"name": "name", "type": "String", "length": 100},
                            {"name": "timestamp", "type": "DateTime"},
                            {"name": "altitude", "type": "Double"},
                            {"name": "speed", "type": "Double"},
                            {"name": "battery", "type": "Double"}
                        ],
                        metadata={"sartracker:type": "current_position"}
                    )
                ]
            ),

            # Breadcrumbs group
            GroupDefinition(
                name=GroupNames.BREADCRUMBS,
                parent_path=[GroupNames.ROOT],
                position=1,
                layers=[
                    LayerDefinition(
                        layer_id=LayerIds.BREADCRUMBS,
                        name="Breadcrumbs",
                        geometry_type="LineString",
                        fields=[
                            {"name": "device_id", "type": "String", "length": 50},
                            {"name": "device_name", "type": "String", "length": 100},
                            {"name": "start_time", "type": "DateTime"},
                            {"name": "end_time", "type": "DateTime"}
                        ],
                        metadata={"sartracker:type": "breadcrumb"}
                    )
                ]
            ),

            # Lines group
            GroupDefinition(
                name=GroupNames.LINES,
                parent_path=[GroupNames.ROOT],
                position=2,
                layers=[
                    LayerDefinition(
                        layer_id=LayerIds.LINES,
                        name="Lines",
                        geometry_type="LineString",
                        fields=[
                            {"name": "name", "type": "String", "length": 100},
                            {"name": "description", "type": "String", "length": 255},
                            {"name": "created", "type": "DateTime"}
                        ],
                        metadata={"sartracker:type": "line"}
                    ),
                    LayerDefinition(
                        layer_id=LayerIds.BEARING_LINES,
                        name="Bearing Lines",
                        geometry_type="LineString",
                        fields=[
                            {"name": "name", "type": "String", "length": 100},
                            {"name": "bearing", "type": "Double"},
                            {"name": "distance", "type": "Double"},
                            {"name": "created", "type": "DateTime"}
                        ],
                        metadata={"sartracker:type": "bearing_line"}
                    )
                ]
            ),

            # Rings group
            GroupDefinition(
                name=GroupNames.RINGS,
                parent_path=[GroupNames.ROOT],
                position=3,
                layers=[
                    LayerDefinition(
                        layer_id=LayerIds.RANGE_RINGS,
                        name="Range Rings",
                        geometry_type="Polygon",
                        fields=[
                            {"name": "name", "type": "String", "length": 100},
                            {"name": "radius", "type": "Double"},
                            {"name": "created", "type": "DateTime"}
                        ],
                        metadata={"sartracker:type": "range_ring"}
                    )
                ]
            ),

            # Markers group
            GroupDefinition(
                name=GroupNames.MARKERS,
                parent_path=[GroupNames.ROOT],
                position=4,
                layers=[
                    LayerDefinition(
                        layer_id=LayerIds.MARKERS_IPP_LKP,
                        name="IPP/LKP",
                        geometry_type="Point",
                        fields=IPP_LKP_FIELDS,
                        metadata={"sartracker:type": "marker_ipp_lkp"}
                    ),
                    LayerDefinition(
                        layer_id=LayerIds.MARKERS_HAZARDS,
                        name="Hazards",
                        geometry_type="Point",
                        fields=HAZARD_FIELDS,
                        metadata={"sartracker:type": "marker_hazard"}
                    ),
                    LayerDefinition(
                        layer_id=LayerIds.MARKERS_CASUALTIES,
                        name="Casualties",
                        geometry_type="Point",
                        fields=CASUALTY_FIELDS,
                        metadata={"sartracker:type": "marker_casualty"}
                    )
                ]
            ),

            # Clues group
            GroupDefinition(
                name=GroupNames.CLUES,
                parent_path=[GroupNames.ROOT],
                position=5,
                layers=[
                    LayerDefinition(
                        layer_id=LayerIds.MARKERS_CLUES,
                        name="Clues",
                        geometry_type="Point",
                        fields=CLUE_FIELDS,
                        metadata={"sartracker:type": "marker_clue"}
                    )
                ]
            ),

            # Helicopters group
            GroupDefinition(
                name=GroupNames.HELICOPTERS,
                parent_path=[GroupNames.ROOT],
                position=6,
                layers=[
                    LayerDefinition(
                        layer_id=LayerIds.HELICOPTER_1,
                        name="Helicopter 1",
                        geometry_type="Point",
                        fields=helicopter_fields,
                        metadata={"sartracker:type": "helicopter", "sartracker:slot_index": "1"},
                        auto_create=True
                    ),
                    LayerDefinition(
                        layer_id=LayerIds.HELICOPTER_2,
                        name="Helicopter 2",
                        geometry_type="Point",
                        fields=helicopter_fields,
                        metadata={"sartracker:type": "helicopter", "sartracker:slot_index": "2"},
                        auto_create=True
                    ),
                    LayerDefinition(
                        layer_id=LayerIds.HELICOPTER_3,
                        name="Helicopter 3",
                        geometry_type="Point",
                        fields=helicopter_fields,
                        metadata={"sartracker:type": "helicopter", "sartracker:slot_index": "3"},
                        auto_create=True
                    ),
                    LayerDefinition(
                        layer_id=LayerIds.HELICOPTER_4,
                        name="Helicopter 4",
                        geometry_type="Point",
                        fields=helicopter_fields,
                        metadata={"sartracker:type": "helicopter", "sartracker:slot_index": "4"},
                        auto_create=True
                    )
                ]
            ),

            # Mission Overlays group
            GroupDefinition(
                name=GroupNames.MISSION_OVERLAYS,
                parent_path=[GroupNames.ROOT],
                position=7,
                layers=[
                    LayerDefinition(
                        layer_id=LayerIds.SEARCH_AREAS,
                        name="Search Areas",
                        geometry_type="Polygon",
                        fields=[
                            {"name": "name", "type": "String", "length": 100},
                            {"name": "area_type", "type": "String", "length": 50},
                            {"name": "description", "type": "String", "length": 255},
                            {"name": "created", "type": "DateTime"}
                        ],
                        metadata={"sartracker:type": "search_area"}
                    ),
                    LayerDefinition(
                        layer_id=LayerIds.SEARCH_SECTORS,
                        name="Search Sectors",
                        geometry_type="Polygon",
                        fields=[
                            {"name": "name", "type": "String", "length": 100},
                            {"name": "sector_id", "type": "String", "length": 50},
                            {"name": "created", "type": "DateTime"}
                        ],
                        metadata={"sartracker:type": "search_sector"}
                    ),
                    LayerDefinition(
                        layer_id=LayerIds.TEXT_LABELS,
                        name="Text Labels",
                        geometry_type="Point",
                        fields=[
                            {"name": "text", "type": "String", "length": 255},
                            {"name": "created", "type": "DateTime"}
                        ],
                        metadata={"sartracker:type": "text_label"}
                    )
                ]
            )
        ]
    )

    return root


def get_group_path(group_name: str) -> List[str]:
    """
    Get the full path to a group in the layer tree.

    Args:
        group_name: Name of the group

    Returns:
        List of group names from root to target group
    """
    if group_name == GroupNames.ROOT:
        return [GroupNames.ROOT]
    else:
        return [GroupNames.ROOT, group_name]


def get_layer_by_id(layer_id: str) -> Optional[LayerDefinition]:
    """
    Find a layer definition by its ID.

    Args:
        layer_id: Unique layer identifier

    Returns:
        LayerDefinition if found, None otherwise
    """
    structure = get_expected_structure()

    def search_group(group: GroupDefinition) -> Optional[LayerDefinition]:
        # Search layers in this group
        if group.layers:
            for layer in group.layers:
                if layer.layer_id == layer_id:
                    return layer

        # Search subgroups recursively
        if group.subgroups:
            for subgroup in group.subgroups:
                result = search_group(subgroup)
                if result:
                    return result

        return None

    return search_group(structure)


# Artifact type to layer ID mapping
ARTIFACT_LAYER_MAP = {
    "current_position": LayerIds.CURRENT_ACTIVE,
    "breadcrumb": LayerIds.BREADCRUMBS,
    "line": LayerIds.LINES,
    "bearing_line": LayerIds.BEARING_LINES,
    "range_ring": LayerIds.RANGE_RINGS,
    "marker_ipp_lkp": LayerIds.MARKERS_IPP_LKP,
    "marker_clue": LayerIds.MARKERS_CLUES,
    "marker_hazard": LayerIds.MARKERS_HAZARDS,
    "marker_casualty": LayerIds.MARKERS_CASUALTIES,
    "helicopter_1": LayerIds.HELICOPTER_1,
    "helicopter_2": LayerIds.HELICOPTER_2,
    "helicopter_3": LayerIds.HELICOPTER_3,
    "helicopter_4": LayerIds.HELICOPTER_4,
    "search_area": LayerIds.SEARCH_AREAS,
    "search_sector": LayerIds.SEARCH_SECTORS,
    "text_label": LayerIds.TEXT_LABELS
}


# Legacy layer name mapping (for migration)
LEGACY_LAYER_NAMES = {
    "Current Positions": LayerIds.CURRENT_ACTIVE,
    "Breadcrumbs": LayerIds.BREADCRUMBS,
    "Lines": LayerIds.LINES,
    "Range Rings": LayerIds.RANGE_RINGS,
    "IPP / LKP": LayerIds.MARKERS_IPP_LKP,
    "Clues": LayerIds.MARKERS_CLUES,
    "Hazards": LayerIds.MARKERS_HAZARDS,
    "Casualties": LayerIds.MARKERS_CASUALTIES
}


# Layer tree placement mapping (used during migrations and when inserting layers)
LAYER_GROUP_PATHS = {
    "Current Positions": [GroupNames.ROOT, GroupNames.CURRENT_POSITIONS],
    "Breadcrumbs": [GroupNames.ROOT, GroupNames.BREADCRUMBS],
    "Lines": [GroupNames.ROOT, GroupNames.LINES],
    "Bearing Lines": [GroupNames.ROOT, GroupNames.LINES],
    "Range Rings": [GroupNames.ROOT, GroupNames.RINGS],
    "IPP/LKP": [GroupNames.ROOT, GroupNames.MARKERS],
    "IPP / LKP": [GroupNames.ROOT, GroupNames.MARKERS],
    "Clues": [GroupNames.ROOT, GroupNames.CLUES],
    "Hazards": [GroupNames.ROOT, GroupNames.MARKERS],
    "Casualties": [GroupNames.ROOT, GroupNames.MARKERS],
    "Search Areas": [GroupNames.ROOT, GroupNames.MISSION_OVERLAYS],
    "Search Sectors": [GroupNames.ROOT, GroupNames.MISSION_OVERLAYS],
    "Text Labels": [GroupNames.ROOT, GroupNames.MISSION_OVERLAYS],
    "Helicopter 1": [GroupNames.ROOT, GroupNames.HELICOPTERS],
    "Helicopter 2": [GroupNames.ROOT, GroupNames.HELICOPTERS],
    "Helicopter 3": [GroupNames.ROOT, GroupNames.HELICOPTERS],
    "Helicopter 4": [GroupNames.ROOT, GroupNames.HELICOPTERS],
}


# Mapping of canonical layer names to LayerIds for metadata tagging
LAYER_NAME_TO_ID = {
    "Current Positions": LayerIds.CURRENT_ACTIVE,
    "Breadcrumbs": LayerIds.BREADCRUMBS,
    "Lines": LayerIds.LINES,
    "Bearing Lines": LayerIds.BEARING_LINES,
    "Range Rings": LayerIds.RANGE_RINGS,
    "IPP/LKP": LayerIds.MARKERS_IPP_LKP,
    "IPP / LKP": LayerIds.MARKERS_IPP_LKP,
    "Clues": LayerIds.MARKERS_CLUES,
    "Hazards": LayerIds.MARKERS_HAZARDS,
    "Casualties": LayerIds.MARKERS_CASUALTIES,
    "Search Areas": LayerIds.SEARCH_AREAS,
    "Search Sectors": LayerIds.SEARCH_SECTORS,
    "Text Labels": LayerIds.TEXT_LABELS,
    "Helicopter 1": LayerIds.HELICOPTER_1,
    "Helicopter 2": LayerIds.HELICOPTER_2,
    "Helicopter 3": LayerIds.HELICOPTER_3,
    "Helicopter 4": LayerIds.HELICOPTER_4,
}


# Minimal field checks to identify plugin-managed layers when reorganizing
LAYER_FIELD_CHECKS = {
    "Current Positions": ["device_id", "name"],
    "Breadcrumbs": ["device_id", "name"],
    "Lines": ["id", "name", "distance_m"],
    "Range Rings": ["radius_m", "label"],
    "IPP/LKP": ["subject_category", "irish_grid_e"],
    "IPP / LKP": ["subject_category", "irish_grid_e"],
    "Clues": ["clue_type", "confidence"],
    "Hazards": ["hazard_type", "severity"],
    "Casualties": ["condition", "evacuation_priority"],
    "Search Areas": ["team", "status", "priority"],
    "Search Sectors": ["start_bearing", "end_bearing"],
    "Text Labels": ["text", "font_size"],
}
