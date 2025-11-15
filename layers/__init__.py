# -*- coding: utf-8 -*-
"""
SAR Tracker Layer Management Package

Provides canonical layer hierarchy management with schema versioning,
idempotent layer/group creation, and persistent structure management.

Qt5/Qt6 Compatible: Uses qgis.PyQt for all Qt imports.
"""

from .schema import (
    SAR_LAYER_SCHEMA_VERSION,
    ROOT_GROUP_NAME,
    LayerIds,
    GroupNames,
    LayerDefinition,
    GroupDefinition,
    get_expected_structure,
    get_group_path,
    get_layer_by_id,
    ARTIFACT_LAYER_MAP,
    LEGACY_LAYER_NAMES,
    LAYER_GROUP_PATHS,
    LAYER_NAME_TO_ID,
    LAYER_FIELD_CHECKS
)

from .manager import LayerManager

from .helicopter_manager import (
    HelicopterLayerManager,
    style_helicopter_layer,
    update_helicopter_position,
    clear_helicopter_layer,
    get_helicopter_info,
    HELICOPTER_COLORS
)

from .utilities import (
    select_group_in_layer_panel,
    open_attribute_table,
    set_active_layer,
    zoom_to_layer,
    get_group_by_path,
    count_features_in_layer,
    get_layer_statistics,
    flash_layer_features
)

__all__ = [
    # Schema
    'SAR_LAYER_SCHEMA_VERSION',
    'ROOT_GROUP_NAME',
    'LayerIds',
    'GroupNames',
    'LayerDefinition',
    'GroupDefinition',
    'get_expected_structure',
    'get_group_path',
    'get_layer_by_id',
    'ARTIFACT_LAYER_MAP',
    'LEGACY_LAYER_NAMES',
    'LAYER_GROUP_PATHS',
    'LAYER_NAME_TO_ID',
    'LAYER_FIELD_CHECKS',
    # Manager
    'LayerManager',
    'HelicopterLayerManager',
    # Helicopter Manager
    'style_helicopter_layer',
    'update_helicopter_position',
    'clear_helicopter_layer',
    'get_helicopter_info',
    'HELICOPTER_COLORS',
    # Utilities
    'select_group_in_layer_panel',
    'open_attribute_table',
    'set_active_layer',
    'zoom_to_layer',
    'get_group_by_path',
    'count_features_in_layer',
    'get_layer_statistics',
    'flash_layer_features'
]
