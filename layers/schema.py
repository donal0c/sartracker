# -*- coding: utf-8 -*-
"""
SAR Tracker Layer Schema Definition

Defines the canonical layer hierarchy structure, constants, and versioning
for the SAR Tracker QGIS plugin. This module provides the schema that ensures
all mission artifacts are stored in a predictable, persistent structure.

Qt5/Qt6 Compatible: Uses qgis.PyQt for all Qt imports.
"""

import json
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
import logging
import threading

logger = logging.getLogger(__name__)


# Schema version - increment when structure changes
# Version 4: Per-device tracking + per-item map tools layers
#   - Each device gets its own Position and Trail layers under Tracking/{DeviceName}/
#   - Each map tool item is stored in its own layer under Map Tools/{Type}/
#   - Migration from shared Current Positions/Breadcrumbs layers
SAR_LAYER_SCHEMA_VERSION = 4


# =============================================================================
# BUG-028 FIX: Migration Status Tracking
# =============================================================================


class MigrationStatus(Enum):
    """Status values for migration tracking."""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"  # For optional migrations that don't apply


@dataclass
class MigrationRecord:
    """
    Record of a single migration attempt.

    BUG-028 FIX: Tracks migration status to detect and recover from
    partial migrations that could leave data in inconsistent states.
    """
    migration_id: str
    from_version: int
    to_version: int
    status: MigrationStatus = MigrationStatus.PENDING
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    error_message: Optional[str] = None
    affected_layers: List[str] = field(default_factory=list)
    rollback_available: bool = False


class MigrationTracker:
    """
    Thread-safe tracker for schema migration status.

    BUG-028 FIX: Provides version tracking for partial migrations to:
    1. Detect incomplete migrations from previous sessions
    2. Prevent repeated migration attempts
    3. Enable recovery from failed migrations
    4. Track which layers were affected by each migration

    LIFE-SAFETY CRITICAL: Incomplete migrations can corrupt layer data
    which could compromise rescue operations.
    """

    _instance: Optional['MigrationTracker'] = None
    _lock = threading.RLock()
    _PROJECT_ENTRY_GROUP = "SARTracker"
    _PROJECT_ENTRY_KEY = "sartracker:migrations"

    def __new__(cls):
        """Singleton pattern for global migration state."""
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self):
        """Initialize migration tracker (only once due to singleton)."""
        if getattr(self, '_initialized', False):
            return

        self._migrations: Dict[str, MigrationRecord] = {}
        self._current_schema_version = SAR_LAYER_SCHEMA_VERSION
        self._initialized = True

    def _serialize_record(self, record: MigrationRecord) -> Dict[str, Any]:
        """Serialize a MigrationRecord for persistence."""
        return {
            "migration_id": record.migration_id,
            "from_version": record.from_version,
            "to_version": record.to_version,
            "status": record.status.value,
            "started_at": record.started_at,
            "completed_at": record.completed_at,
            "error_message": record.error_message,
            "affected_layers": list(record.affected_layers or []),
            "rollback_available": bool(record.rollback_available),
        }

    def _deserialize_record(self, payload: Dict[str, Any]) -> Optional[MigrationRecord]:
        """Rehydrate a MigrationRecord from persisted data."""
        if not isinstance(payload, dict):
            return None
        status_value = payload.get("status", MigrationStatus.PENDING.value)
        try:
            status = MigrationStatus(status_value)
        except Exception:
            status = MigrationStatus.PENDING
        try:
            from_version = int(payload.get("from_version") or 0)
        except (TypeError, ValueError):
            from_version = 0
        try:
            to_version = int(payload.get("to_version") or 0)
        except (TypeError, ValueError):
            to_version = 0
        return MigrationRecord(
            migration_id=str(payload.get("migration_id", "")),
            from_version=from_version,
            to_version=to_version,
            status=status,
            started_at=payload.get("started_at"),
            completed_at=payload.get("completed_at"),
            error_message=payload.get("error_message"),
            affected_layers=list(payload.get("affected_layers", []) or []),
            rollback_available=bool(payload.get("rollback_available", False)),
        )

    def _persist_to_project(self) -> None:
        """Persist migration state to the current QGIS project (best effort)."""
        project = None
        try:
            from qgis.core import QgsProject
            project = QgsProject.instance()
        except Exception:
            project = None

        if not project:
            return

        try:
            data = {
                migration_id: self._serialize_record(record)
                for migration_id, record in self._migrations.items()
            }
            project.writeEntry(
                self._PROJECT_ENTRY_GROUP,
                self._PROJECT_ENTRY_KEY,
                json.dumps(data)
            )
        except Exception as exc:
            logger.warning("Failed to persist migration state: %s", exc)

    def load_from_project(self, project=None) -> None:
        """Load persisted migration state from a QGIS project (best effort)."""
        if project is None:
            try:
                from qgis.core import QgsProject
                project = QgsProject.instance()
            except Exception:
                project = None

        if not project:
            return

        with self._lock:
            try:
                payload = project.readEntry(
                    self._PROJECT_ENTRY_GROUP,
                    self._PROJECT_ENTRY_KEY
                )[0]
            except Exception as exc:
                logger.warning("Failed to read migration state: %s", exc)
                return

            self._migrations.clear()

            if not payload:
                return

            try:
                data = json.loads(payload)
            except Exception as exc:
                logger.warning("Failed to parse migration state: %s", exc)
                return

            if not isinstance(data, dict):
                logger.warning("Unexpected migration state payload type: %s", type(data).__name__)
                return

            for migration_id, record_payload in data.items():
                record = self._deserialize_record(record_payload)
                if record and record.migration_id:
                    self._migrations[migration_id] = record

    def start_migration(
        self,
        migration_id: str,
        from_version: int,
        to_version: int,
        affected_layers: Optional[List[str]] = None
    ) -> MigrationRecord:
        """
        Record the start of a migration.

        Args:
            migration_id: Unique identifier for this migration
            from_version: Schema version before migration
            to_version: Target schema version
            affected_layers: List of layer names that will be modified

        Returns:
            MigrationRecord for tracking this migration
        """
        with self._lock:
            if migration_id in self._migrations:
                existing = self._migrations[migration_id]
                if existing.status == MigrationStatus.IN_PROGRESS:
                    logger.warning(
                        "Migration %s already in progress - possible incomplete "
                        "migration from previous session",
                        migration_id
                    )
                elif existing.status == MigrationStatus.COMPLETED:
                    logger.info("Migration %s already completed, skipping", migration_id)
                    return existing

            record = MigrationRecord(
                migration_id=migration_id,
                from_version=from_version,
                to_version=to_version,
                status=MigrationStatus.IN_PROGRESS,
                started_at=datetime.now(timezone.utc).isoformat(),
                affected_layers=affected_layers or []
            )
            self._migrations[migration_id] = record
            logger.info(
                "Started migration %s: v%d -> v%d (layers: %s)",
                migration_id, from_version, to_version,
                ", ".join(affected_layers or ["none"])
            )
            self._persist_to_project()
            return record

    def complete_migration(self, migration_id: str, rollback_available: bool = False):
        """
        Record successful completion of a migration.

        Args:
            migration_id: Identifier of completed migration
            rollback_available: Whether rollback data was preserved
        """
        with self._lock:
            if migration_id not in self._migrations:
                logger.warning("Completing unknown migration: %s", migration_id)
                return

            record = self._migrations[migration_id]
            record.status = MigrationStatus.COMPLETED
            record.completed_at = datetime.now(timezone.utc).isoformat()
            record.rollback_available = rollback_available
            logger.info(
                "Completed migration %s (rollback %s)",
                migration_id,
                "available" if rollback_available else "not available"
            )
            self._persist_to_project()

    def fail_migration(self, migration_id: str, error_message: str):
        """
        Record a failed migration.

        Args:
            migration_id: Identifier of failed migration
            error_message: Description of what went wrong
        """
        with self._lock:
            if migration_id not in self._migrations:
                logger.warning("Failing unknown migration: %s", migration_id)
                return

            record = self._migrations[migration_id]
            record.status = MigrationStatus.FAILED
            record.completed_at = datetime.now(timezone.utc).isoformat()
            record.error_message = error_message
            logger.error(
                "Migration %s FAILED: %s",
                migration_id, error_message
            )
            self._persist_to_project()

    def get_migration_status(self, migration_id: str) -> Optional[MigrationRecord]:
        """Get the status of a specific migration."""
        with self._lock:
            return self._migrations.get(migration_id)

    def has_incomplete_migrations(self) -> List[MigrationRecord]:
        """
        Check for incomplete migrations that may need recovery.

        Returns:
            List of migrations that are IN_PROGRESS or FAILED
        """
        with self._lock:
            return [
                record for record in self._migrations.values()
                if record.status in (MigrationStatus.IN_PROGRESS, MigrationStatus.FAILED)
            ]

    def is_migration_needed(self, from_version: int, to_version: int) -> bool:
        """
        Check if a migration should be performed.

        Args:
            from_version: Current schema version
            to_version: Target schema version

        Returns:
            True if migration should proceed
        """
        migration_id = f"v{from_version}_to_v{to_version}"
        with self._lock:
            existing = self._migrations.get(migration_id)
            if existing and existing.status == MigrationStatus.COMPLETED:
                return False
            return from_version < to_version

    def clear_all(self):
        """Clear all migration records (for testing)."""
        with self._lock:
            self._migrations.clear()
        self._persist_to_project()


# Global migration tracker instance
migration_tracker = MigrationTracker()

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
    # Tracking groups
    CURRENT_POSITIONS = "Current Positions"
    BREADCRUMBS = "Breadcrumbs"
    TRACKING = "Tracking"  # For future per-device tracking layers
    # Helicopters
    HELICOPTERS = "Helicopters"
    # Mission Overlays (legacy - retained for compatibility)
    MISSION_OVERLAYS = "Mission Overlays"
    # Map Tools - main group for all drawing/marker items (FR-3)
    MAP_TOOLS = "Map Tools"
    # Map Tools subgroups (per-item layers go here)
    MAP_TOOLS_IPP_LKP = "IPP-LKP"
    MAP_TOOLS_CLUES = "Clues"
    MAP_TOOLS_HAZARDS = "Hazards"
    MAP_TOOLS_CASUALTIES = "Casualties"
    MAP_TOOLS_SEARCH_AREAS = "Search Areas"
    MAP_TOOLS_SEARCH_SECTORS = "Search Sectors"
    MAP_TOOLS_RANGE_RINGS = "Range Rings"
    MAP_TOOLS_BEARING_LINES = "Bearing Lines"
    MAP_TOOLS_LINES = "Lines"
    MAP_TOOLS_TEXT_LABELS = "Text Labels"


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
    auto_create: bool = True  # Whether to auto-create the group during structure ensure


# ---------------------------------------------------------------------------
# Marker layer field definitions
# ---------------------------------------------------------------------------

MARKER_COMMON_GEO_FIELDS = [
    {"name": "lat", "type": "Double"},
    {"name": "lon", "type": "Double"},
    {"name": "irish_grid_e", "type": "Double"},
    {"name": "irish_grid_n", "type": "Double"},
    {"name": "created", "type": "String", "length": 40}
]

MARKER_AUDIT_FIELDS = [
    {"name": "created_at", "type": "String", "length": 40},
    {"name": "updated_at", "type": "String", "length": 40},
    {"name": "updated_by", "type": "String", "length": 120},
    {"name": "coordinator_ids", "type": "String", "length": 255},
    {"name": "attachment_path", "type": "String", "length": 255}
]

IPP_LKP_FIELDS = [
    {"name": "id", "type": "String", "length": 36},
    {"name": "name", "type": "String", "length": 120},
    {"name": "subject_category", "type": "String", "length": 60},
    {"name": "description", "type": "String", "length": 255},
    *MARKER_COMMON_GEO_FIELDS,
    *MARKER_AUDIT_FIELDS,
    {"name": "display_order", "type": "Int"}
]

CLUE_FIELDS = [
    {"name": "id", "type": "String", "length": 36},
    {"name": "name", "type": "String", "length": 120},
    {"name": "clue_type", "type": "String", "length": 60},
    {"name": "confidence", "type": "String", "length": 20},
    {"name": "description", "type": "String", "length": 255},
    *MARKER_COMMON_GEO_FIELDS,
    *MARKER_AUDIT_FIELDS,
    {"name": "display_order", "type": "Int"}
]

HAZARD_FIELDS = [
    {"name": "id", "type": "String", "length": 36},
    {"name": "name", "type": "String", "length": 120},
    {"name": "hazard_type", "type": "String", "length": 60},
    {"name": "severity", "type": "String", "length": 20},
    {"name": "description", "type": "String", "length": 255},
    *MARKER_COMMON_GEO_FIELDS,
    *MARKER_AUDIT_FIELDS,
    {"name": "display_order", "type": "Int"}
]

CASUALTY_FIELDS = [
    {"name": "id", "type": "String", "length": 36},
    {"name": "name", "type": "String", "length": 120},
    {"name": "condition", "type": "String", "length": 60},
    {"name": "treatment", "type": "String", "length": 120},
    {"name": "evacuation_priority", "type": "String", "length": 30},
    {"name": "description", "type": "String", "length": 255},
    {"name": "found_by", "type": "String", "length": 120},
    *MARKER_COMMON_GEO_FIELDS,
    *MARKER_AUDIT_FIELDS,
    {"name": "display_order", "type": "Int"}
]

# ---------------------------------------------------------------------------
# Tracking layer field definitions
# ---------------------------------------------------------------------------

CURRENT_POSITION_FIELDS = [
    {"name": "device_id", "type": "String", "length": 50},
    {"name": "name", "type": "String", "length": 100},
    {"name": "timestamp", "type": "String", "length": 40},
    {"name": "altitude", "type": "Double"},
    {"name": "speed", "type": "Double"},
    {"name": "battery", "type": "Double"}
]

BREADCRUMB_FIELDS = [
    {"name": "device_id", "type": "String", "length": 50},
    {"name": "name", "type": "String", "length": 100},
    {"name": "timestamp", "type": "String", "length": 40}
]

# ---------------------------------------------------------------------------
# Per-device tracking layer field definitions (Phase SAR-nh9)
# ---------------------------------------------------------------------------

# Fields for per-device position layers (single feature per layer - latest position)
DEVICE_POSITION_FIELDS = [
    {"name": "id", "type": "String", "length": 36},           # Feature UUID
    {"name": "device_id", "type": "String", "length": 50},    # Stable device ID from Traccar
    {"name": "name", "type": "String", "length": 100},        # Display name
    {"name": "timestamp", "type": "String", "length": 40},    # ISO8601 timestamp
    {"name": "altitude", "type": "Double"},                   # Meters
    {"name": "speed", "type": "Double"},                      # km/h
    {"name": "battery", "type": "Double"},                    # Percentage
    {"name": "accuracy", "type": "Double"},                   # GPS accuracy (m)
    {"name": "source", "type": "String", "length": 50},       # Data source
]

# Fields for per-device trail layers (LineString segments for that device only)
DEVICE_TRAIL_FIELDS = [
    {"name": "id", "type": "String", "length": 36},           # Segment UUID
    {"name": "device_id", "type": "String", "length": 50},    # Stable device ID
    {"name": "name", "type": "String", "length": 100},        # Display name
    {"name": "segment_index", "type": "Int"},                 # Segment order
    {"name": "start_time", "type": "String", "length": 40},   # First point time
    {"name": "end_time", "type": "String", "length": 40},     # Last point time
    {"name": "point_count", "type": "Int"},                   # Points in segment
    {"name": "distance_m", "type": "Double"},                 # Segment length
]

# ---------------------------------------------------------------------------
# Drawing / overlay layer field definitions
# ---------------------------------------------------------------------------

LINES_FIELDS = [
    {"name": "id", "type": "String", "length": 36},
    {"name": "name", "type": "String", "length": 120},
    {"name": "description", "type": "String", "length": 255},
    {"name": "color", "type": "String", "length": 16},
    {"name": "width", "type": "Int"},
    {"name": "distance_m", "type": "Double"},
    {"name": "created", "type": "String", "length": 40},
    {"name": "temporary_measure", "type": "Bool"},
    {"name": "display_order", "type": "Int"}
]

SEARCH_AREA_FIELDS = [
    {"name": "id", "type": "String", "length": 36},
    {"name": "name", "type": "String", "length": 120},
    {"name": "team", "type": "String", "length": 120},
    {"name": "status", "type": "String", "length": 40},
    {"name": "priority", "type": "String", "length": 20},
    {"name": "area_sqkm", "type": "Double"},
    {"name": "POA", "type": "Double"},
    {"name": "POD", "type": "Double"},
    {"name": "terrain", "type": "String", "length": 120},
    {"name": "search_method", "type": "String", "length": 120},
    {"name": "color", "type": "String", "length": 16},
    {"name": "start_time", "type": "String", "length": 40},
    {"name": "end_time", "type": "String", "length": 40},
    {"name": "notes", "type": "String", "length": 255},
    {"name": "created", "type": "String", "length": 40},
    {"name": "display_order", "type": "Int"}
]

RANGE_RING_FIELDS = [
    {"name": "id", "type": "String", "length": 36},
    {"name": "name", "type": "String", "length": 120},
    {"name": "center_lat", "type": "Double"},
    {"name": "center_lon", "type": "Double"},
    {"name": "radius_m", "type": "Double"},
    {"name": "label", "type": "String", "length": 60},
    {"name": "color", "type": "String", "length": 16},
    {"name": "lpb_category", "type": "String", "length": 60},
    {"name": "percentile", "type": "Int"},
    {"name": "created", "type": "String", "length": 40},
    {"name": "display_order", "type": "Int"}
]

BEARING_LINE_FIELDS = [
    {"name": "id", "type": "String", "length": 36},
    {"name": "name", "type": "String", "length": 120},
    {"name": "origin_lat", "type": "Double"},
    {"name": "origin_lon", "type": "Double"},
    {"name": "bearing", "type": "Double"},
    {"name": "distance_m", "type": "Double"},
    {"name": "label", "type": "String", "length": 60},
    {"name": "color", "type": "String", "length": 16},
    {"name": "created", "type": "String", "length": 40},
    {"name": "display_order", "type": "Int"}
]

SEARCH_SECTOR_FIELDS = [
    {"name": "id", "type": "String", "length": 36},
    {"name": "name", "type": "String", "length": 120},
    {"name": "center_lat", "type": "Double"},
    {"name": "center_lon", "type": "Double"},
    {"name": "start_bearing", "type": "Double"},
    {"name": "end_bearing", "type": "Double"},
    {"name": "radius_m", "type": "Double"},
    {"name": "arc_length_deg", "type": "Double"},
    {"name": "area_sqkm", "type": "Double"},
    {"name": "priority", "type": "String", "length": 20},
    {"name": "color", "type": "String", "length": 16},
    {"name": "created", "type": "String", "length": 40},
    {"name": "display_order", "type": "Int"}
]

TEXT_LABEL_FIELDS = [
    {"name": "id", "type": "String", "length": 36},
    {"name": "text", "type": "String", "length": 255},
    {"name": "lat", "type": "Double"},
    {"name": "lon", "type": "Double"},
    {"name": "font_size", "type": "Int"},
    {"name": "color", "type": "String", "length": 16},
    {"name": "rotation", "type": "Double"},
    {"name": "created", "type": "String", "length": 40},
    {"name": "display_order", "type": "Int"}
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

    map_tools_subgroups = [
        GroupDefinition(
            name=GroupNames.MAP_TOOLS_IPP_LKP,
            parent_path=[GroupNames.ROOT, GroupNames.MAP_TOOLS],
            position=0,
            layers=[
                LayerDefinition(
                    layer_id=LayerIds.MARKERS_IPP_LKP,
                    name="IPP/LKP",
                    geometry_type="Point",
                    fields=IPP_LKP_FIELDS,
                    metadata={"sartracker:type": "marker_ipp_lkp", "sartracker:virtual": "true"},
                    auto_create=False
                )
            ]
        ),
        GroupDefinition(
            name=GroupNames.MAP_TOOLS_CLUES,
            parent_path=[GroupNames.ROOT, GroupNames.MAP_TOOLS],
            position=1,
            layers=[
                LayerDefinition(
                    layer_id=LayerIds.MARKERS_CLUES,
                    name="Clues",
                    geometry_type="Point",
                    fields=CLUE_FIELDS,
                    metadata={"sartracker:type": "marker_clue", "sartracker:virtual": "true"},
                    auto_create=False
                )
            ]
        ),
        GroupDefinition(
            name=GroupNames.MAP_TOOLS_HAZARDS,
            parent_path=[GroupNames.ROOT, GroupNames.MAP_TOOLS],
            position=2,
            layers=[
                LayerDefinition(
                    layer_id=LayerIds.MARKERS_HAZARDS,
                    name="Hazards",
                    geometry_type="Point",
                    fields=HAZARD_FIELDS,
                    metadata={"sartracker:type": "marker_hazard", "sartracker:virtual": "true"},
                    auto_create=False
                )
            ]
        ),
        GroupDefinition(
            name=GroupNames.MAP_TOOLS_CASUALTIES,
            parent_path=[GroupNames.ROOT, GroupNames.MAP_TOOLS],
            position=3,
            layers=[
                LayerDefinition(
                    layer_id=LayerIds.MARKERS_CASUALTIES,
                    name="Casualties",
                    geometry_type="Point",
                    fields=CASUALTY_FIELDS,
                    metadata={"sartracker:type": "marker_casualty", "sartracker:virtual": "true"},
                    auto_create=False
                )
            ]
        ),
        GroupDefinition(
            name=GroupNames.MAP_TOOLS_SEARCH_AREAS,
            parent_path=[GroupNames.ROOT, GroupNames.MAP_TOOLS],
            position=4,
            layers=[
                LayerDefinition(
                    layer_id=LayerIds.SEARCH_AREAS,
                    name="Search Areas",
                    geometry_type="Polygon",
                    fields=SEARCH_AREA_FIELDS,
                    metadata={"sartracker:type": "search_area", "sartracker:virtual": "true"},
                    auto_create=False
                )
            ]
        ),
        GroupDefinition(
            name=GroupNames.MAP_TOOLS_SEARCH_SECTORS,
            parent_path=[GroupNames.ROOT, GroupNames.MAP_TOOLS],
            position=5,
            layers=[
                LayerDefinition(
                    layer_id=LayerIds.SEARCH_SECTORS,
                    name="Search Sectors",
                    geometry_type="Polygon",
                    fields=SEARCH_SECTOR_FIELDS,
                    metadata={"sartracker:type": "search_sector", "sartracker:virtual": "true"},
                    auto_create=False
                )
            ]
        ),
        GroupDefinition(
            name=GroupNames.MAP_TOOLS_RANGE_RINGS,
            parent_path=[GroupNames.ROOT, GroupNames.MAP_TOOLS],
            position=6,
            layers=[
                LayerDefinition(
                    layer_id=LayerIds.RANGE_RINGS,
                    name="Range Rings",
                    geometry_type="Polygon",
                    fields=RANGE_RING_FIELDS,
                    metadata={"sartracker:type": "range_ring", "sartracker:virtual": "true"},
                    auto_create=False
                )
            ]
        ),
        GroupDefinition(
            name=GroupNames.MAP_TOOLS_BEARING_LINES,
            parent_path=[GroupNames.ROOT, GroupNames.MAP_TOOLS],
            position=7,
            layers=[
                LayerDefinition(
                    layer_id=LayerIds.BEARING_LINES,
                    name="Bearing Lines",
                    geometry_type="LineString",
                    fields=BEARING_LINE_FIELDS,
                    metadata={"sartracker:type": "bearing_line", "sartracker:virtual": "true"},
                    auto_create=False
                )
            ]
        ),
        GroupDefinition(
            name=GroupNames.MAP_TOOLS_LINES,
            parent_path=[GroupNames.ROOT, GroupNames.MAP_TOOLS],
            position=8,
            layers=[
                LayerDefinition(
                    layer_id=LayerIds.LINES,
                    name="Lines",
                    geometry_type="LineString",
                    fields=LINES_FIELDS,
                    metadata={"sartracker:type": "line", "sartracker:virtual": "true"},
                    auto_create=False
                )
            ]
        ),
        GroupDefinition(
            name=GroupNames.MAP_TOOLS_TEXT_LABELS,
            parent_path=[GroupNames.ROOT, GroupNames.MAP_TOOLS],
            position=9,
            layers=[
                LayerDefinition(
                    layer_id=LayerIds.TEXT_LABELS,
                    name="Text Labels",
                    geometry_type="Point",
                    fields=TEXT_LABEL_FIELDS,
                    metadata={"sartracker:type": "text_label", "sartracker:virtual": "true"},
                    auto_create=False
                )
            ]
        ),
    ]

    # Define the complete structure
    root = GroupDefinition(
        name=GroupNames.ROOT,
        parent_path=None,
        metadata={"schema_version": str(SAR_LAYER_SCHEMA_VERSION)},
        subgroups=[
            # Tracking group (per-device layers created dynamically)
            GroupDefinition(
                name=GroupNames.TRACKING,
                parent_path=[GroupNames.ROOT],
                position=0
            ),

            # Helicopters group
            GroupDefinition(
                name=GroupNames.HELICOPTERS,
                parent_path=[GroupNames.ROOT],
                position=1,
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

            # Map Tools group (per-item layers only)
            GroupDefinition(
                name=GroupNames.MAP_TOOLS,
                parent_path=[GroupNames.ROOT],
                position=2,
                subgroups=map_tools_subgroups
            ),

            # Mission Overlays group removed from canonical schema (legacy only)
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
    "text_label": LayerIds.TEXT_LABELS,
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
    "Casualties": LayerIds.MARKERS_CASUALTIES,
    "Search Areas": LayerIds.SEARCH_AREAS,
    "Search Sectors": LayerIds.SEARCH_SECTORS,
    "Bearing Lines": LayerIds.BEARING_LINES,
    "Text Labels": LayerIds.TEXT_LABELS,
}


# Layer tree placement mapping (used during migrations and when inserting layers)
# Phase 4: All drawing/marker items now use Map Tools hierarchy
LAYER_GROUP_PATHS = {
    # Legacy tracking layers (handled via migration; do not auto-create groups)
    # Map Tools - Drawing items (per-item layers)
    "Lines": [GroupNames.ROOT, GroupNames.MAP_TOOLS, GroupNames.MAP_TOOLS_LINES],
    "Bearing Lines": [GroupNames.ROOT, GroupNames.MAP_TOOLS, GroupNames.MAP_TOOLS_BEARING_LINES],
    "Range Rings": [GroupNames.ROOT, GroupNames.MAP_TOOLS, GroupNames.MAP_TOOLS_RANGE_RINGS],
    "Search Areas": [GroupNames.ROOT, GroupNames.MAP_TOOLS, GroupNames.MAP_TOOLS_SEARCH_AREAS],
    # Map Tools - Marker items (per-item layers)
    "IPP/LKP": [GroupNames.ROOT, GroupNames.MAP_TOOLS, GroupNames.MAP_TOOLS_IPP_LKP],
    "IPP / LKP": [GroupNames.ROOT, GroupNames.MAP_TOOLS, GroupNames.MAP_TOOLS_IPP_LKP],
    "Clues": [GroupNames.ROOT, GroupNames.MAP_TOOLS, GroupNames.MAP_TOOLS_CLUES],
    "Hazards": [GroupNames.ROOT, GroupNames.MAP_TOOLS, GroupNames.MAP_TOOLS_HAZARDS],
    "Casualties": [GroupNames.ROOT, GroupNames.MAP_TOOLS, GroupNames.MAP_TOOLS_CASUALTIES],
    # Map Tools - legacy shared items (sectors, text labels)
    "Search Sectors": [GroupNames.ROOT, GroupNames.MAP_TOOLS, GroupNames.MAP_TOOLS_SEARCH_SECTORS],
    "Text Labels": [GroupNames.ROOT, GroupNames.MAP_TOOLS, GroupNames.MAP_TOOLS_TEXT_LABELS],
    # Helicopters
    "Helicopter 1": [GroupNames.ROOT, GroupNames.HELICOPTERS],
    "Helicopter 2": [GroupNames.ROOT, GroupNames.HELICOPTERS],
    "Helicopter 3": [GroupNames.ROOT, GroupNames.HELICOPTERS],
    "Helicopter 4": [GroupNames.ROOT, GroupNames.HELICOPTERS],
}


# =============================================================================
# Phase 4: Per-Item Layer Group Paths (FR-2/FR-3)
# =============================================================================
# These paths are used by PerItemLayerFactory for placing per-item layers
# in the new "Map Tools" hierarchy.

def get_per_item_group_path(item_type: str) -> List[str]:
    """
    Get the group path for a per-item layer based on its type.

    Args:
        item_type: Item type from PerItemLayerFactory.ItemType

    Returns:
        List of group names forming the path (e.g., ["SAR Tracker", "Map Tools", "Clues"])
    """
    # Map item types to their subgroups under Map Tools
    PER_ITEM_GROUP_MAP = {
        "marker_clue": GroupNames.MAP_TOOLS_CLUES,
        "marker_ipp_lkp": GroupNames.MAP_TOOLS_IPP_LKP,
        "marker_hazard": GroupNames.MAP_TOOLS_HAZARDS,
        "marker_casualty": GroupNames.MAP_TOOLS_CASUALTIES,
        "search_area": GroupNames.MAP_TOOLS_SEARCH_AREAS,
        "search_sector": GroupNames.MAP_TOOLS_SEARCH_SECTORS,
        "range_ring": GroupNames.MAP_TOOLS_RANGE_RINGS,
        "bearing_line": GroupNames.MAP_TOOLS_BEARING_LINES,
        "line": GroupNames.MAP_TOOLS_LINES,
        "text_label": GroupNames.MAP_TOOLS_TEXT_LABELS,
    }

    subgroup = PER_ITEM_GROUP_MAP.get(item_type)
    if subgroup:
        return [GroupNames.ROOT, GroupNames.MAP_TOOLS, subgroup]

    # Fallback to Map Tools root if unknown type
    logger.warning("Unknown item type for per-item grouping: %s", item_type)
    return [GroupNames.ROOT, GroupNames.MAP_TOOLS]


def get_per_device_group_path(device_name: str) -> List[str]:
    """
    Get the group path for a device's tracking layers.

    Phase SAR-nh9: Per-device tracking layers are organized as:
        SAR Tracker / Tracking / {DeviceName} / [Position, Trail]

    This device-centric grouping matches coordinator mental model
    ("show me Alpha Team") and enables one-click device visibility toggle.

    Args:
        device_name: Display name of the device (e.g., "Alpha Team")

    Returns:
        List of group names forming the path
        e.g., ["SAR Tracker", "Tracking", "Alpha Team"]
    """
    return [GroupNames.ROOT, GroupNames.TRACKING, device_name]


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
    "Bearing Lines": ["bearing", "origin_lat", "origin_lon"],
}
