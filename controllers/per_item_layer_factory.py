# -*- coding: utf-8 -*-
"""
Per-Item Layer Factory (Phase 3 Implementation)

Creates and manages individual GeoPackage-backed layers for each map item.
Implements ADR-001 architecture with item registry for session persistence.

Key design decisions:
- Each item (marker, search area, etc.) gets its own GeoPackage table
- Items identified by custom layer properties, NOT layer names
- Layer names can be freely renamed by users
- WAL mode enabled for crash safety
- Item registry table (_sar_item_registry) tracks all items persistently
- Lazy loading support for 100+ layer scalability

Qt5/Qt6 Compatible: Uses qgis.PyQt for all imports.

LIFE-SAFETY CRITICAL: This code handles mission data storage.
"""

import logging
import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple, Set

from qgis.core import (
    QgsProject, QgsVectorLayer, QgsFeature, QgsGeometry,
    QgsPointXY, QgsField, QgsFields, QgsLayerTreeGroup,
    QgsVectorFileWriter, QgsCoordinateReferenceSystem,
    QgsCoordinateTransformContext
)
from qgis.PyQt.QtCore import QVariant

logger = logging.getLogger(__name__)


# =============================================================================
# Constants
# =============================================================================

# Custom property keys for item identification
# These are stored in the QGIS project and survive layer rename
SAR_ITEM_ID = "sartracker:item_id"
SAR_ITEM_TYPE = "sartracker:item_type"
SAR_ITEM_CREATED = "sartracker:item_created"

# Item types supported by this factory
class ItemType:
    """Supported item types for per-item layers."""
    MARKER_CLUE = "marker_clue"
    MARKER_HAZARD = "marker_hazard"
    MARKER_IPP_LKP = "marker_ipp_lkp"
    MARKER_CASUALTY = "marker_casualty"
    SEARCH_AREA = "search_area"
    SEARCH_SECTOR = "search_sector"
    RANGE_RING = "range_ring"
    BEARING_LINE = "bearing_line"
    LINE = "line"
    TEXT_LABEL = "text_label"
    # Phase SAR-nh9: Per-device tracking layers
    DEVICE_POSITION = "device_position"
    DEVICE_TRAIL = "device_trail"


# Geometry types per item type
ITEM_GEOMETRY_TYPES = {
    ItemType.MARKER_CLUE: "Point",
    ItemType.MARKER_HAZARD: "Point",
    ItemType.MARKER_IPP_LKP: "Point",
    ItemType.MARKER_CASUALTY: "Point",
    ItemType.SEARCH_AREA: "Polygon",
    ItemType.SEARCH_SECTOR: "Polygon",
    ItemType.RANGE_RING: "Polygon",
    ItemType.BEARING_LINE: "LineString",
    ItemType.LINE: "LineString",
    ItemType.TEXT_LABEL: "Point",
    # Phase SAR-nh9: Per-device tracking layers
    ItemType.DEVICE_POSITION: "Point",
    ItemType.DEVICE_TRAIL: "LineString",
}


# =============================================================================
# Item Registry Schema (Phase 3)
# =============================================================================

# Registry table name (prefixed with underscore to indicate internal/system table)
REGISTRY_TABLE_NAME = "_sar_item_registry"

# Registry schema version (for future migrations)
REGISTRY_SCHEMA_VERSION = 1

# SQL to create the registry table
REGISTRY_CREATE_SQL = """
CREATE TABLE IF NOT EXISTS _sar_item_registry (
    item_id TEXT PRIMARY KEY,
    item_type TEXT NOT NULL,
    table_name TEXT NOT NULL UNIQUE,
    display_name TEXT,
    geometry_type TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT,
    deleted_at TEXT,
    is_deleted INTEGER DEFAULT 0,
    schema_version INTEGER DEFAULT 1,
    extra_metadata TEXT
);

CREATE INDEX IF NOT EXISTS idx_registry_type ON _sar_item_registry(item_type);
CREATE INDEX IF NOT EXISTS idx_registry_deleted ON _sar_item_registry(is_deleted);
"""


class ItemStatus(Enum):
    """Status of an item in the registry."""
    ACTIVE = "active"           # Item exists with valid layer
    ORPHANED = "orphaned"       # Registry entry exists but layer missing
    DELETED = "deleted"         # Soft-deleted (retained for recovery)

# Default display name prefixes per item type
ITEM_NAME_PREFIXES = {
    ItemType.MARKER_CLUE: "CLU",
    ItemType.MARKER_HAZARD: "HAZ",
    ItemType.MARKER_IPP_LKP: "IPP",
    ItemType.MARKER_CASUALTY: "CAS",
    ItemType.SEARCH_AREA: "SAR",
    ItemType.SEARCH_SECTOR: "SEC",
    ItemType.RANGE_RING: "RNG",
    ItemType.BEARING_LINE: "BRG",
    ItemType.LINE: "LNE",
    ItemType.TEXT_LABEL: "TXT",
}


# =============================================================================
# Data Classes
# =============================================================================

@dataclass
class ItemLayerInfo:
    """
    Information about a per-item layer.

    This represents both in-memory layer state and persistent registry data.
    The registry ensures items are discoverable across sessions even if
    layer names have been changed by users.
    """
    item_id: str
    item_type: str
    display_name: str
    table_name: str
    geometry_type: str = ""
    layer: Optional[QgsVectorLayer] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    is_deleted: bool = False
    status: ItemStatus = ItemStatus.ACTIVE
    extra_metadata: Optional[Dict[str, Any]] = None

    def __post_init__(self):
        """Set geometry_type from item_type if not provided."""
        if not self.geometry_type and self.item_type:
            self.geometry_type = ITEM_GEOMETRY_TYPES.get(self.item_type, "Point")


# =============================================================================
# GeoPackage Utilities
# =============================================================================

def enable_wal_mode(gpkg_path: Path) -> bool:
    """
    Enable WAL mode for better concurrent access and crash recovery.

    ADR-001 requirement: All mission GeoPackages must use WAL mode.

    Args:
        gpkg_path: Path to GeoPackage file

    Returns:
        True if WAL mode enabled successfully
    """
    conn = None
    try:
        conn = sqlite3.connect(str(gpkg_path))
        result = conn.execute("PRAGMA journal_mode=WAL").fetchone()

        success = result and result[0].upper() == "WAL"
        if success:
            logger.debug("WAL mode enabled for %s", gpkg_path.name)
        else:
            logger.warning("Failed to enable WAL mode for %s: %s", gpkg_path.name, result)
        return success

    except sqlite3.Error as e:
        logger.error("SQLite error enabling WAL mode for %s: %s", gpkg_path, e)
        return False
    finally:
        if conn:
            conn.close()


def checkpoint_wal(gpkg_path: Path) -> bool:
    """
    Checkpoint WAL before backup operations.

    ADR-001 requirement: Must checkpoint before creating backups.

    Args:
        gpkg_path: Path to GeoPackage file

    Returns:
        True if checkpoint successful
    """
    conn = None
    try:
        conn = sqlite3.connect(str(gpkg_path))
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        logger.debug("WAL checkpoint completed for %s", gpkg_path.name)
        return True

    except sqlite3.Error as e:
        logger.error("SQLite error during WAL checkpoint for %s: %s", gpkg_path, e)
        return False
    finally:
        if conn:
            conn.close()


def get_gpkg_tables(gpkg_path: Path) -> List[str]:
    """
    Get list of all user tables in a GeoPackage.

    Args:
        gpkg_path: Path to GeoPackage file

    Returns:
        List of table names (excluding gpkg_* system tables)
    """
    conn = None
    try:
        conn = sqlite3.connect(str(gpkg_path))
        cursor = conn.execute(
            "SELECT table_name FROM gpkg_contents WHERE data_type = 'features'"
        )
        tables = [row[0] for row in cursor.fetchall()]
        return tables

    except sqlite3.Error as e:
        logger.error("Error listing GeoPackage tables: %s", e)
        return []
    finally:
        if conn:
            conn.close()


# =============================================================================
# Item Registry Functions (Phase 3)
# =============================================================================

def ensure_registry_table(gpkg_path: Path) -> bool:
    """
    Ensure the item registry table exists in the GeoPackage.

    Creates _sar_item_registry table if it doesn't exist.
    This table tracks all per-item layers for discovery across sessions.

    Args:
        gpkg_path: Path to GeoPackage file

    Returns:
        True if registry table exists or was created successfully
    """
    if not gpkg_path.exists():
        logger.debug("GeoPackage does not exist yet: %s", gpkg_path)
        return False

    conn = None
    try:
        conn = sqlite3.connect(str(gpkg_path))
        # Execute the CREATE statements (safe to run multiple times with IF NOT EXISTS)
        conn.executescript(REGISTRY_CREATE_SQL)
        conn.commit()
        logger.debug("Registry table ensured for %s", gpkg_path.name)
        return True

    except sqlite3.Error as e:
        logger.error("Failed to create registry table in %s: %s", gpkg_path, e)
        return False
    finally:
        if conn:
            conn.close()


def registry_add_item(
    gpkg_path: Path,
    item_id: str,
    item_type: str,
    table_name: str,
    display_name: str,
    geometry_type: str,
    created_at: str,
    extra_metadata: Optional[Dict[str, Any]] = None
) -> bool:
    """
    Add an item to the registry.

    Args:
        gpkg_path: Path to GeoPackage
        item_id: Unique item identifier
        item_type: ItemType value
        table_name: GeoPackage table name
        display_name: User-visible display name
        geometry_type: Point, LineString, or Polygon
        created_at: ISO timestamp of creation
        extra_metadata: Optional JSON-serializable metadata

    Returns:
        True if item was added successfully
    """
    import json

    conn = None
    try:
        conn = sqlite3.connect(str(gpkg_path))
        conn.execute(
            """
            INSERT INTO _sar_item_registry
            (item_id, item_type, table_name, display_name, geometry_type,
             created_at, schema_version, extra_metadata)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                item_id,
                item_type,
                table_name,
                display_name,
                geometry_type,
                created_at,
                REGISTRY_SCHEMA_VERSION,
                json.dumps(extra_metadata) if extra_metadata else None
            )
        )
        conn.commit()
        logger.debug("Added item %s to registry", item_id)
        return True

    except sqlite3.IntegrityError as e:
        logger.warning("Item %s already exists in registry: %s", item_id, e)
        return False
    except sqlite3.Error as e:
        logger.error("Failed to add item %s to registry: %s", item_id, e)
        return False
    finally:
        if conn:
            conn.close()


def registry_update_item(
    gpkg_path: Path,
    item_id: str,
    display_name: Optional[str] = None,
    extra_metadata: Optional[Dict[str, Any]] = None
) -> bool:
    """
    Update an item in the registry.

    Args:
        gpkg_path: Path to GeoPackage
        item_id: Item to update
        display_name: New display name (if provided)
        extra_metadata: New metadata (if provided)

    Returns:
        True if item was updated
    """
    import json

    updates = []
    params = []

    if display_name is not None:
        updates.append("display_name = ?")
        params.append(display_name)

    if extra_metadata is not None:
        updates.append("extra_metadata = ?")
        params.append(json.dumps(extra_metadata))

    if not updates:
        return True  # Nothing to update

    updates.append("updated_at = ?")
    params.append(datetime.now(timezone.utc).isoformat())
    params.append(item_id)

    conn = None
    try:
        conn = sqlite3.connect(str(gpkg_path))
        conn.execute(
            f"UPDATE _sar_item_registry SET {', '.join(updates)} WHERE item_id = ?",
            params
        )
        conn.commit()
        return True

    except sqlite3.Error as e:
        logger.error("Failed to update item %s in registry: %s", item_id, e)
        return False
    finally:
        if conn:
            conn.close()


def registry_soft_delete_item(gpkg_path: Path, item_id: str) -> bool:
    """
    Soft-delete an item in the registry (mark as deleted but retain record).

    Args:
        gpkg_path: Path to GeoPackage
        item_id: Item to mark as deleted

    Returns:
        True if item was marked as deleted
    """
    conn = None
    try:
        conn = sqlite3.connect(str(gpkg_path))
        conn.execute(
            """
            UPDATE _sar_item_registry
            SET is_deleted = 1, deleted_at = ?
            WHERE item_id = ?
            """,
            (datetime.now(timezone.utc).isoformat(), item_id)
        )
        conn.commit()
        logger.debug("Soft-deleted item %s in registry", item_id)
        return True

    except sqlite3.Error as e:
        logger.error("Failed to soft-delete item %s: %s", item_id, e)
        return False
    finally:
        if conn:
            conn.close()


def registry_hard_delete_item(gpkg_path: Path, item_id: str) -> bool:
    """
    Permanently remove an item from the registry.

    Args:
        gpkg_path: Path to GeoPackage
        item_id: Item to remove

    Returns:
        True if item was removed
    """
    conn = None
    try:
        conn = sqlite3.connect(str(gpkg_path))
        conn.execute(
            "DELETE FROM _sar_item_registry WHERE item_id = ?",
            (item_id,)
        )
        conn.commit()
        logger.debug("Hard-deleted item %s from registry", item_id)
        return True

    except sqlite3.Error as e:
        logger.error("Failed to hard-delete item %s: %s", item_id, e)
        return False
    finally:
        if conn:
            conn.close()


def registry_exists(gpkg_path: Path) -> bool:
    """
    Check if the registry table exists in the GeoPackage.

    Args:
        gpkg_path: Path to GeoPackage

    Returns:
        True if registry table exists
    """
    if not gpkg_path.exists():
        return False

    conn = None
    try:
        conn = sqlite3.connect(str(gpkg_path))
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (REGISTRY_TABLE_NAME,)
        )
        exists = cursor.fetchone() is not None
        return exists

    except sqlite3.Error:
        return False
    finally:
        if conn:
            conn.close()


# =============================================================================
# Performance Utilities (Phase 3 - SAR-49s)
# =============================================================================

def ensure_spatial_index(gpkg_path: Path, table_name: str) -> bool:
    """
    Ensure a spatial index exists for a GeoPackage table.

    GeoPackage uses rtree-based spatial indexes. This creates the index
    if it doesn't already exist.

    Args:
        gpkg_path: Path to GeoPackage
        table_name: Table to index

    Returns:
        True if index exists or was created successfully
    """
    if not gpkg_path.exists():
        return False

    conn = None
    try:
        conn = sqlite3.connect(str(gpkg_path))

        # Check if table has geometry column registered
        cursor = conn.execute(
            "SELECT column_name FROM gpkg_geometry_columns WHERE table_name = ?",
            (table_name,)
        )
        row = cursor.fetchone()
        if not row:
            logger.debug("Table %s has no registered geometry column", table_name)
            return False

        geom_column = row[0]

        # Check if spatial index already exists
        index_table = f"rtree_{table_name}_{geom_column}"
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (index_table,)
        )
        if cursor.fetchone():
            logger.debug("Spatial index already exists for %s", table_name)
            return True

        # Create spatial index using gpkg_add_geometry_index if available
        # This is the GeoPackage-compliant way to add indexes
        try:
            conn.execute(
                f"SELECT gpkgAddGeometryIndex('{table_name}', '{geom_column}')"
            )
        except sqlite3.OperationalError:
            # Fallback: Create rtree manually
            logger.debug("gpkgAddGeometryIndex not available, creating rtree manually")
            conn.execute(f"""
                CREATE VIRTUAL TABLE IF NOT EXISTS "{index_table}" USING rtree(
                    id,
                    minx, maxx,
                    miny, maxy
                )
            """)

            # Populate from existing data
            conn.execute(f"""
                INSERT OR REPLACE INTO "{index_table}" (id, minx, maxx, miny, maxy)
                SELECT rowid,
                       ST_MinX("{geom_column}"), ST_MaxX("{geom_column}"),
                       ST_MinY("{geom_column}"), ST_MaxY("{geom_column}")
                FROM "{table_name}"
                WHERE "{geom_column}" IS NOT NULL
            """)

        conn.commit()
        logger.info("Created spatial index for %s.%s", table_name, geom_column)
        return True

    except sqlite3.Error as e:
        logger.error("Failed to create spatial index for %s: %s", table_name, e)
        return False
    finally:
        if conn:
            conn.close()


def get_spatial_index_status(gpkg_path: Path) -> Dict[str, Any]:
    """
    Get spatial index status for all tables in a GeoPackage.

    Returns:
        Dict with 'indexed', 'not_indexed', and 'total' counts
    """
    if not gpkg_path.exists():
        return {"indexed": 0, "not_indexed": 0, "total": 0, "tables": []}

    conn = None
    try:
        conn = sqlite3.connect(str(gpkg_path))

        # Get all geometry tables
        cursor = conn.execute(
            "SELECT table_name, column_name FROM gpkg_geometry_columns"
        )
        geom_tables = cursor.fetchall()

        indexed = []
        not_indexed = []

        for table_name, geom_column in geom_tables:
            index_table = f"rtree_{table_name}_{geom_column}"
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                (index_table,)
            )
            if cursor.fetchone():
                indexed.append(table_name)
            else:
                not_indexed.append(table_name)

        return {
            "indexed": len(indexed),
            "not_indexed": len(not_indexed),
            "total": len(geom_tables),
            "indexed_tables": indexed,
            "not_indexed_tables": not_indexed
        }

    except sqlite3.Error as e:
        logger.error("Failed to get spatial index status: %s", e)
        return {"indexed": 0, "not_indexed": 0, "total": 0, "error": str(e)}
    finally:
        if conn:
            conn.close()


# Performance mode presets
class PerformanceMode:
    """Performance mode presets for large missions."""

    # Scale thresholds for visibility (1:X)
    # At scales smaller than this, items are hidden to reduce rendering load
    SCALE_THRESHOLDS = {
        ItemType.MARKER_CLUE: 50000,      # Hide clues at 1:50000 and smaller
        ItemType.MARKER_HAZARD: 100000,   # Hazards visible longer
        ItemType.MARKER_IPP_LKP: 0,       # Always visible (critical)
        ItemType.MARKER_CASUALTY: 0,      # Always visible (critical)
        ItemType.TEXT_LABEL: 25000,       # Labels hidden early
        ItemType.SEARCH_AREA: 500000,     # Areas visible at regional scale
        ItemType.SEARCH_SECTOR: 500000,   # Sectors visible at regional scale
        ItemType.RANGE_RING: 250000,
        ItemType.BEARING_LINE: 100000,
        ItemType.LINE: 100000,
        # Phase SAR-nh9: Device tracking always visible (critical for SAR)
        ItemType.DEVICE_POSITION: 0,      # Always visible (life-safety critical)
        ItemType.DEVICE_TRAIL: 0,         # Always visible (life-safety critical)
    }

    @staticmethod
    def apply_scale_visibility(layer: 'QgsVectorLayer', item_type: str) -> bool:
        """
        Apply scale-based visibility to a layer based on its type.

        Args:
            layer: The layer to configure
            item_type: ItemType value

        Returns:
            True if scale visibility was applied
        """
        threshold = PerformanceMode.SCALE_THRESHOLDS.get(item_type, 0)

        if threshold > 0:
            layer.setScaleBasedVisibility(True)
            layer.setMinimumScale(threshold)
            layer.setMaximumScale(0)  # No max (visible at any zoom in)
            return True
        else:
            layer.setScaleBasedVisibility(False)
            return False

    @staticmethod
    def remove_scale_visibility(layer: 'QgsVectorLayer') -> None:
        """Remove scale-based visibility from a layer."""
        layer.setScaleBasedVisibility(False)


def registry_get_all_items(
    gpkg_path: Path,
    include_deleted: bool = False,
    item_type: Optional[str] = None
) -> List[ItemLayerInfo]:
    """
    Get all items from the registry.

    Args:
        gpkg_path: Path to GeoPackage
        include_deleted: Include soft-deleted items
        item_type: Filter by item type (optional)

    Returns:
        List of ItemLayerInfo objects from registry
    """
    import json

    if not gpkg_path.exists():
        return []

    # Check if registry table exists before querying
    if not registry_exists(gpkg_path):
        return []

    conn = None
    try:
        conn = sqlite3.connect(str(gpkg_path))
        conn.row_factory = sqlite3.Row

        query = "SELECT * FROM _sar_item_registry WHERE 1=1"
        params = []

        if not include_deleted:
            query += " AND is_deleted = 0"

        if item_type:
            query += " AND item_type = ?"
            params.append(item_type)

        query += " ORDER BY created_at"

        cursor = conn.execute(query, params)
        rows = cursor.fetchall()

        items = []
        for row in rows:
            extra = None
            if row["extra_metadata"]:
                try:
                    extra = json.loads(row["extra_metadata"])
                except json.JSONDecodeError:
                    pass

            items.append(ItemLayerInfo(
                item_id=row["item_id"],
                item_type=row["item_type"],
                display_name=row["display_name"] or "",
                table_name=row["table_name"],
                geometry_type=row["geometry_type"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
                is_deleted=bool(row["is_deleted"]),
                status=ItemStatus.DELETED if row["is_deleted"] else ItemStatus.ORPHANED,
                extra_metadata=extra
            ))

        return items

    except sqlite3.Error as e:
        logger.error("Failed to read registry from %s: %s", gpkg_path, e)
        return []
    finally:
        if conn:
            conn.close()


def registry_get_item(gpkg_path: Path, item_id: str) -> Optional[ItemLayerInfo]:
    """
    Get a specific item from the registry.

    Args:
        gpkg_path: Path to GeoPackage
        item_id: Item to retrieve

    Returns:
        ItemLayerInfo or None if not found
    """
    import json

    if not gpkg_path.exists():
        return None

    # Check if registry table exists before querying
    if not registry_exists(gpkg_path):
        return None

    conn = None
    try:
        conn = sqlite3.connect(str(gpkg_path))
        conn.row_factory = sqlite3.Row
        cursor = conn.execute(
            "SELECT * FROM _sar_item_registry WHERE item_id = ?",
            (item_id,)
        )
        row = cursor.fetchone()

        if not row:
            return None

        extra = None
        if row["extra_metadata"]:
            try:
                extra = json.loads(row["extra_metadata"])
            except json.JSONDecodeError:
                pass

        return ItemLayerInfo(
            item_id=row["item_id"],
            item_type=row["item_type"],
            display_name=row["display_name"] or "",
            table_name=row["table_name"],
            geometry_type=row["geometry_type"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            is_deleted=bool(row["is_deleted"]),
            status=ItemStatus.DELETED if row["is_deleted"] else ItemStatus.ORPHANED,
            extra_metadata=extra
        )

    except sqlite3.Error as e:
        logger.error("Failed to get item %s from registry: %s", item_id, e)
        return None
    finally:
        if conn:
            conn.close()


# =============================================================================
# Per-Item Layer Factory
# =============================================================================

class PerItemLayerFactory:
    """
    Factory for creating and managing per-item GeoPackage layers.

    This is the core component of the ADR-001 architecture. Each map item
    (marker, search area, etc.) gets its own:
    - GeoPackage table (named by item_id, not display name)
    - QGIS layer (can be renamed freely)
    - Registry entry for cross-session discovery

    Item identification uses custom layer properties that persist across
    project save/load and are independent of layer names.

    The item registry (_sar_item_registry table) tracks all items persistently,
    enabling:
    - Discovery of existing items even if layers have been renamed
    - Rebuild of missing layers from registry data
    - Lazy loading for 100+ layer scalability

    LIFE-SAFETY CRITICAL: This handles mission data persistence.
    """

    def __init__(self, gpkg_path: Path, auto_wal: bool = True, auto_registry: bool = True):
        """
        Initialize the factory.

        Args:
            gpkg_path: Path to mission GeoPackage file
            auto_wal: Enable WAL mode automatically (default True)
            auto_registry: Create registry table if missing (default True)
        """
        self.gpkg_path = Path(gpkg_path)
        self._layer_cache: Dict[str, QgsVectorLayer] = {}
        self._registry_synced: bool = False

        # Ensure GeoPackage exists with WAL mode
        if self.gpkg_path.exists():
            if auto_wal:
                enable_wal_mode(self.gpkg_path)
            if auto_registry:
                ensure_registry_table(self.gpkg_path)
                self._registry_synced = True

    def create_item_layer(
        self,
        item_type: str,
        display_name: str,
        item_id: Optional[str] = None,
        fields: Optional[List[Dict[str, Any]]] = None,
        add_to_project: bool = True,
        target_group: Optional[QgsLayerTreeGroup] = None
    ) -> ItemLayerInfo:
        """
        Create a new per-item layer with its own GeoPackage table.

        Args:
            item_type: Type from ItemType class
            display_name: User-visible layer name (can be changed later)
            item_id: Optional specific ID (generated if not provided)
            fields: Optional field definitions for the layer
            add_to_project: Whether to add to current QGIS project
            target_group: Optional group to add layer to

        Returns:
            ItemLayerInfo with the created layer

        Raises:
            ValueError: If item_type is invalid
            RuntimeError: If layer creation fails
        """
        # Validate item type
        if item_type not in ITEM_GEOMETRY_TYPES:
            raise ValueError(f"Invalid item type: {item_type}")

        # Generate or validate item_id
        if item_id is None:
            item_id = str(uuid.uuid4())

        # Create table name from item_id (stable, not based on display name)
        # Format: {type_prefix}_{uuid_hex} e.g., "clue_a1b2c3d4e5f6..."
        prefix = item_type.replace("marker_", "").replace("_", "")
        uuid_hex = item_id.replace("-", "")
        table_name = f"{prefix}_{uuid_hex}"

        if self.gpkg_path.exists():
            existing_tables = set(get_gpkg_tables(self.gpkg_path))
            if table_name in existing_tables:
                raise RuntimeError(
                    f"Table name collision for item {item_id}: {table_name} already exists"
                )

        geometry_type = ITEM_GEOMETRY_TYPES[item_type]
        created_at = datetime.now(timezone.utc).isoformat()

        # Create the GeoPackage table and layer
        layer = self._create_gpkg_layer(
            table_name=table_name,
            geometry_type=geometry_type,
            display_name=display_name,
            fields=fields
        )

        if not layer or not layer.isValid():
            raise RuntimeError(f"Failed to create layer for item {item_id}")

        # Set custom properties for identification (survives rename)
        layer.setCustomProperty(SAR_ITEM_ID, item_id)
        layer.setCustomProperty(SAR_ITEM_TYPE, item_type)
        layer.setCustomProperty(SAR_ITEM_CREATED, created_at)

        # Add to project if requested
        if add_to_project:
            self._add_layer_to_project(layer, target_group)

        # Cache the layer
        self._layer_cache[item_id] = layer

        # Sync to registry (Phase 3)
        self._ensure_registry()
        registry_success = registry_add_item(
            gpkg_path=self.gpkg_path,
            item_id=item_id,
            item_type=item_type,
            table_name=table_name,
            display_name=display_name,
            geometry_type=geometry_type,
            created_at=created_at
        )

        if not registry_success:
            # Rollback: registry failed, so remove layer from project and GeoPackage
            # Each rollback step is wrapped to ensure all steps are attempted
            logger.error(
                "Registry add failed for item %s - rolling back layer creation",
                item_id
            )
            rollback_complete = True

            # Step 1: Remove from project (if added)
            # Note: Don't gate on layer.isValid() - layer was added regardless of
            # current validity state, and QGIS can have invalid layers in project
            try:
                if add_to_project and layer:
                    project = QgsProject.instance()
                    project.removeMapLayer(layer.id())
            except Exception as exc:
                logger.warning(
                    "Rollback: failed to remove layer from project for item %s: %s",
                    item_id, exc
                )
                rollback_complete = False

            # Step 2: Remove from cache (safe - never raises)
            self._layer_cache.pop(item_id, None)

            # Step 3: Drop GeoPackage table
            try:
                if not self._drop_gpkg_table(table_name):
                    logger.warning(
                        "Rollback incomplete: failed to drop GeoPackage table '%s' for item %s",
                        table_name, item_id
                    )
                    rollback_complete = False
            except Exception as exc:
                logger.warning(
                    "Rollback: exception dropping GeoPackage table '%s' for item %s: %s",
                    table_name, item_id, exc
                )
                rollback_complete = False

            rollback_status = "rolled back" if rollback_complete else "rollback incomplete"
            raise RuntimeError(
                f"Failed to register item {item_id} in registry - {rollback_status}"
            )

        logger.info(
            "Created per-item layer: %s (type=%s, table=%s)",
            display_name, item_type, table_name
        )

        return ItemLayerInfo(
            item_id=item_id,
            item_type=item_type,
            display_name=display_name,
            table_name=table_name,
            geometry_type=geometry_type,
            layer=layer,
            created_at=created_at,
            status=ItemStatus.ACTIVE
        )

    def get_layer_by_item_id(self, item_id: str) -> Optional[QgsVectorLayer]:
        """
        Find a layer by its item_id custom property.

        This is the primary lookup method - it searches by stable ID,
        not by layer name (which users can change).

        Args:
            item_id: The stable item identifier

        Returns:
            QgsVectorLayer if found, None otherwise
        """
        # Check cache first
        if item_id in self._layer_cache:
            layer = self._layer_cache[item_id]
            if layer and layer.isValid():
                return layer
            else:
                # Stale cache entry
                del self._layer_cache[item_id]

        # Search project layers by custom property
        project = QgsProject.instance()
        for layer in project.mapLayers().values():
            if isinstance(layer, QgsVectorLayer):
                if layer.customProperty(SAR_ITEM_ID) == item_id:
                    self._layer_cache[item_id] = layer
                    return layer

        return None

    def get_all_item_layers(self, item_type: Optional[str] = None) -> List[ItemLayerInfo]:
        """
        Get all per-item layers, optionally filtered by type.

        Args:
            item_type: Optional filter by ItemType

        Returns:
            List of ItemLayerInfo for matching layers
        """
        result = []
        project = QgsProject.instance()

        for layer in project.mapLayers().values():
            if not isinstance(layer, QgsVectorLayer):
                continue

            layer_item_id = layer.customProperty(SAR_ITEM_ID)
            layer_item_type = layer.customProperty(SAR_ITEM_TYPE)

            if not layer_item_id:
                continue  # Not a per-item layer

            if item_type and layer_item_type != item_type:
                continue  # Type filter doesn't match

            result.append(ItemLayerInfo(
                item_id=layer_item_id,
                item_type=layer_item_type or "",
                display_name=layer.name(),
                table_name=self._extract_table_name(layer),
                layer=layer,
                created_at=layer.customProperty(SAR_ITEM_CREATED)
            ))

        return result

    def delete_item_layer(
        self,
        item_id: str,
        remove_table: bool = True,
        hard_delete: bool = False
    ) -> bool:
        """
        Delete a per-item layer and optionally its GeoPackage table.

        Args:
            item_id: The stable item identifier
            remove_table: Also remove the GeoPackage table (default True)
            hard_delete: Permanently remove from registry (default False = soft delete)

        Returns:
            True if deletion successful
        """
        layer = self.get_layer_by_item_id(item_id)
        if not layer:
            logger.warning("Cannot delete item %s: layer not found", item_id)
            return False

        table_name = self._extract_table_name(layer)
        layer_id = layer.id()

        # Remove from project
        project = QgsProject.instance()
        project.removeMapLayer(layer_id)

        # Remove from cache
        if item_id in self._layer_cache:
            del self._layer_cache[item_id]

        # Remove GeoPackage table if requested
        if remove_table and table_name:
            self._drop_gpkg_table(table_name)

        # Update registry (Phase 3)
        if hard_delete:
            registry_hard_delete_item(self.gpkg_path, item_id)
        else:
            registry_soft_delete_item(self.gpkg_path, item_id)

        logger.info("Deleted per-item layer: %s (table=%s, hard=%s)", item_id, table_name, hard_delete)
        return True

    def rename_item_layer(self, item_id: str, new_name: str) -> bool:
        """
        Rename a per-item layer (display name only, table unchanged).

        This demonstrates that layer names can change freely while
        item_id remains stable for identification.

        Args:
            item_id: The stable item identifier
            new_name: New display name for the layer

        Returns:
            True if rename successful
        """
        layer = self.get_layer_by_item_id(item_id)
        if not layer:
            logger.warning("Cannot rename item %s: layer not found", item_id)
            return False

        old_name = layer.name()
        layer.setName(new_name)

        # Update registry (Phase 3)
        registry_update_item(self.gpkg_path, item_id, display_name=new_name)

        logger.info("Renamed item layer: '%s' -> '%s' (id=%s)", old_name, new_name, item_id)
        return True

    def update_item_metadata(
        self,
        item_id: str,
        metadata: Dict[str, str]
    ) -> bool:
        """
        Update custom metadata properties on a per-item layer.

        Args:
            item_id: The stable item identifier
            metadata: Dict of property_name -> value to set

        Returns:
            True if update successful
        """
        layer = self.get_layer_by_item_id(item_id)
        if not layer:
            logger.warning("Cannot update metadata for %s: layer not found", item_id)
            return False

        for key, value in metadata.items():
            # Prefix custom metadata to avoid conflicts
            prop_key = f"sartracker:meta:{key}"
            layer.setCustomProperty(prop_key, value)

        return True

    def get_item_metadata(self, item_id: str) -> Dict[str, str]:
        """
        Get all custom metadata properties from a per-item layer.

        Args:
            item_id: The stable item identifier

        Returns:
            Dict of property_name -> value (empty if not found)
        """
        layer = self.get_layer_by_item_id(item_id)
        if not layer:
            return {}

        result = {}
        prefix = "sartracker:meta:"

        for key in layer.customPropertyKeys():
            if key.startswith(prefix):
                prop_name = key[len(prefix):]
                result[prop_name] = layer.customProperty(key)

        return result

    # =========================================================================
    # Registry and Discovery Methods (Phase 3)
    # =========================================================================

    def _ensure_registry(self) -> bool:
        """
        Ensure the registry table exists in the GeoPackage.

        Called automatically before registry operations.

        Returns:
            True if registry is available
        """
        if self._registry_synced:
            return True

        if not self.gpkg_path.exists():
            return False

        if ensure_registry_table(self.gpkg_path):
            self._registry_synced = True
            return True

        return False

    def discover_existing_items(
        self,
        include_deleted: bool = False,
        item_type: Optional[str] = None
    ) -> List[ItemLayerInfo]:
        """
        Discover all items from the registry and update their status.

        This method reads all items from the registry table and checks
        whether each item has a corresponding layer loaded in the project.
        Items without loaded layers are marked as ORPHANED.

        This is the key method for session resumption - it finds all
        items that existed in a previous session even if layers haven't
        been loaded yet.

        Args:
            include_deleted: Include soft-deleted items
            item_type: Filter by item type (optional)

        Returns:
            List of ItemLayerInfo with current status
        """
        if not self._ensure_registry():
            return []

        # Get all items from registry
        registry_items = registry_get_all_items(
            self.gpkg_path,
            include_deleted=include_deleted,
            item_type=item_type
        )

        # Check which items have loaded layers
        project = QgsProject.instance()
        result = []

        for item in registry_items:
            # Try to find the layer in the project
            layer = self.get_layer_by_item_id(item.item_id)

            if layer and layer.isValid():
                # Layer is loaded - update display name from layer (may have been renamed)
                item.layer = layer
                item.display_name = layer.name()
                item.status = ItemStatus.ACTIVE
            else:
                # Layer not loaded - item is orphaned (can be rebuilt)
                item.layer = None
                item.status = ItemStatus.ORPHANED if not item.is_deleted else ItemStatus.DELETED

            result.append(item)

        return result

    def rebuild_missing_layer(
        self,
        item_id: str,
        add_to_project: bool = True,
        target_group: Optional[QgsLayerTreeGroup] = None
    ) -> Optional[QgsVectorLayer]:
        """
        Rebuild a layer from registry data for an orphaned item.

        This is used when:
        - Resuming a mission where layers haven't been loaded yet
        - A layer was accidentally removed from the project
        - Lazy loading is triggered for an item

        Args:
            item_id: The item to rebuild a layer for
            add_to_project: Add the rebuilt layer to the project
            target_group: Optional group to add layer to

        Returns:
            The rebuilt QgsVectorLayer, or None if rebuild failed
        """
        # Get item info from registry
        item_info = registry_get_item(self.gpkg_path, item_id)
        if not item_info:
            logger.warning("Cannot rebuild layer for %s: not found in registry", item_id)
            return None

        if item_info.is_deleted:
            logger.warning("Cannot rebuild layer for %s: item is deleted", item_id)
            return None

        # Check if table still exists in GeoPackage
        tables = get_gpkg_tables(self.gpkg_path)
        if item_info.table_name not in tables:
            logger.error(
                "Cannot rebuild layer for %s: table %s not found in GeoPackage",
                item_id, item_info.table_name
            )
            return None

        # Open the layer from the existing GeoPackage table
        uri = f"{self.gpkg_path}|layername={item_info.table_name}"
        layer = QgsVectorLayer(uri, item_info.display_name, "ogr")

        if not layer.isValid():
            logger.error("Failed to open layer from %s", uri)
            return None

        # Set custom properties for identification
        layer.setCustomProperty(SAR_ITEM_ID, item_id)
        layer.setCustomProperty(SAR_ITEM_TYPE, item_info.item_type)
        layer.setCustomProperty(SAR_ITEM_CREATED, item_info.created_at or "")

        # Add to project if requested
        if add_to_project:
            self._add_layer_to_project(layer, target_group)

        # Update cache
        self._layer_cache[item_id] = layer

        logger.info(
            "Rebuilt layer for item %s: %s (table=%s)",
            item_id, item_info.display_name, item_info.table_name
        )

        return layer

    def get_registry_items(
        self,
        include_deleted: bool = False,
        item_type: Optional[str] = None
    ) -> List[ItemLayerInfo]:
        """
        Get items directly from the registry without checking layer status.

        This is a lightweight method for getting registry data without
        querying the QGIS project. Use discover_existing_items() when
        you need current layer status.

        Args:
            include_deleted: Include soft-deleted items
            item_type: Filter by item type

        Returns:
            List of ItemLayerInfo from registry
        """
        if not self._ensure_registry():
            return []

        return registry_get_all_items(
            self.gpkg_path,
            include_deleted=include_deleted,
            item_type=item_type
        )

    def sync_registry_with_project(self) -> Dict[str, Any]:
        """
        Synchronize the registry with the current project state.

        This method:
        1. Finds items in registry that don't have loaded layers (orphaned)
        2. Finds layers in project that aren't in registry (unregistered)
        3. Returns a summary of the sync status

        Use this after opening an existing mission to verify consistency.

        Returns:
            Dict with 'orphaned', 'unregistered', and 'synced' counts
        """
        if not self._ensure_registry():
            return {"orphaned": 0, "unregistered": 0, "synced": 0, "error": "No registry"}

        # Get all registry items
        registry_items = registry_get_all_items(self.gpkg_path, include_deleted=False)
        registry_ids = {item.item_id for item in registry_items}

        # Get all project layers with SAR item IDs
        project = QgsProject.instance()
        project_item_ids: Set[str] = set()

        for layer in project.mapLayers().values():
            if isinstance(layer, QgsVectorLayer):
                item_id = layer.customProperty(SAR_ITEM_ID)
                if item_id:
                    project_item_ids.add(item_id)

        # Calculate differences
        orphaned_ids = registry_ids - project_item_ids  # In registry but not project
        unregistered_ids = project_item_ids - registry_ids  # In project but not registry

        # Synced items
        synced_ids = registry_ids & project_item_ids

        # Register any unregistered items found in project
        for item_id in unregistered_ids:
            layer = None
            for lyr in project.mapLayers().values():
                if isinstance(lyr, QgsVectorLayer) and lyr.customProperty(SAR_ITEM_ID) == item_id:
                    layer = lyr
                    break

            if layer:
                item_type = layer.customProperty(SAR_ITEM_TYPE) or ""
                created_at = layer.customProperty(SAR_ITEM_CREATED) or datetime.now(timezone.utc).isoformat()
                table_name = self._extract_table_name(layer)

                registry_add_item(
                    gpkg_path=self.gpkg_path,
                    item_id=item_id,
                    item_type=item_type,
                    table_name=table_name,
                    display_name=layer.name(),
                    geometry_type=ITEM_GEOMETRY_TYPES.get(item_type, "Point"),
                    created_at=created_at
                )
                logger.info("Registered untracked item %s in registry", item_id)

        return {
            "orphaned": len(orphaned_ids),
            "unregistered": len(unregistered_ids),
            "synced": len(synced_ids),
            "orphaned_ids": list(orphaned_ids),
            "unregistered_ids": list(unregistered_ids)
        }

    def load_items_on_demand(
        self,
        item_ids: Optional[List[str]] = None,
        item_type: Optional[str] = None,
        target_group: Optional[QgsLayerTreeGroup] = None,
        batch_size: int = 10
    ) -> Dict[str, Any]:
        """
        Load orphaned items on demand (lazy loading).

        This is the key method for 100+ layer scalability. Instead of
        loading all layers at mission open, items can be loaded on demand
        when they are needed (e.g., when a group is expanded or an item
        is selected).

        Args:
            item_ids: Specific items to load (if None, loads all orphaned)
            item_type: Filter by type (if item_ids not provided)
            target_group: Optional group to add layers to
            batch_size: Maximum items to load in one call (for responsiveness)

        Returns:
            Dict with 'loaded', 'failed', and 'remaining' counts
        """
        if not self._ensure_registry():
            return {"loaded": 0, "failed": 0, "remaining": 0, "error": "No registry"}

        # Get items to load
        if item_ids:
            # Load specific items
            items_to_load = []
            for item_id in item_ids[:batch_size]:
                info = registry_get_item(self.gpkg_path, item_id)
                if info and not info.is_deleted:
                    # Check if already loaded
                    existing = self.get_layer_by_item_id(item_id)
                    if not existing or not existing.isValid():
                        items_to_load.append(info)
        else:
            # Load orphaned items of the specified type
            all_items = self.discover_existing_items(include_deleted=False, item_type=item_type)
            items_to_load = [
                item for item in all_items
                if item.status == ItemStatus.ORPHANED
            ][:batch_size]

        # Load the items
        loaded = 0
        failed = 0

        # Use batch operations for performance (ADR-001 pattern)
        if items_to_load and target_group:
            project = QgsProject.instance()
            root = project.layerTreeRoot()

            # Block signals during batch operation
            root.blockSignals(True)
            try:
                for item in items_to_load:
                    layer = self.rebuild_missing_layer(
                        item.item_id,
                        add_to_project=True,
                        target_group=target_group
                    )
                    if layer:
                        loaded += 1
                    else:
                        failed += 1
            finally:
                root.blockSignals(False)
                # Single update after batch
                if hasattr(root, 'updateVisibility'):
                    root.updateVisibility()
        else:
            # No target group - load individually
            for item in items_to_load:
                layer = self.rebuild_missing_layer(
                    item.item_id,
                    add_to_project=True,
                    target_group=None
                )
                if layer:
                    loaded += 1
                else:
                    failed += 1

        # Calculate remaining
        if item_ids:
            remaining = max(0, len(item_ids) - batch_size)
        else:
            all_orphaned = len([
                item for item in self.discover_existing_items(include_deleted=False, item_type=item_type)
                if item.status == ItemStatus.ORPHANED
            ])
            remaining = all_orphaned

        logger.info(
            "Lazy loaded %d items (failed: %d, remaining: %d)",
            loaded, failed, remaining
        )

        return {
            "loaded": loaded,
            "failed": failed,
            "remaining": remaining
        }

    def get_item_count(self, item_type: Optional[str] = None, include_deleted: bool = False) -> int:
        """
        Get count of items in the registry without loading layer data.

        This is a lightweight method for UI display (e.g., "50 clues")
        without loading all the layers.

        Args:
            item_type: Filter by type (optional)
            include_deleted: Include soft-deleted items

        Returns:
            Number of items matching criteria
        """
        items = self.get_registry_items(include_deleted=include_deleted, item_type=item_type)
        return len(items)

    def get_orphaned_count(self, item_type: Optional[str] = None) -> int:
        """
        Get count of orphaned (unloaded) items.

        Args:
            item_type: Filter by type (optional)

        Returns:
            Number of orphaned items
        """
        items = self.discover_existing_items(include_deleted=False, item_type=item_type)
        return len([item for item in items if item.status == ItemStatus.ORPHANED])

    # =========================================================================
    # Bulk Operations (Phase 3 - SAR-dgj)
    # =========================================================================

    # Default threshold for layer count warnings
    DEFAULT_LAYER_WARNING_THRESHOLD = 100

    def bulk_set_visibility(
        self,
        visible: bool,
        item_type: Optional[str] = None,
        item_ids: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        Set visibility for multiple item layers at once.

        Uses blockSignals for performance when changing many layers.

        Args:
            visible: True to show, False to hide
            item_type: Filter by item type (optional)
            item_ids: Specific item IDs to change (optional, overrides item_type)

        Returns:
            Dict with 'changed', 'skipped', and 'locked' counts
        """
        project = QgsProject.instance()
        root = project.layerTreeRoot()

        changed = 0
        skipped = 0
        locked = 0

        # Get items to process
        if item_ids:
            items = [self.get_layer_by_item_id(item_id) for item_id in item_ids]
            items = [layer for layer in items if layer is not None]
        else:
            item_infos = self.discover_existing_items(include_deleted=False, item_type=item_type)
            items = [info.layer for info in item_infos if info.layer is not None]

        if not items:
            return {"changed": 0, "skipped": 0, "locked": 0}

        # Block signals for bulk operation
        root.blockSignals(True)
        try:
            for layer in items:
                # Check if locked
                if layer.customProperty("sartracker:locked"):
                    locked += 1
                    continue

                layer_node = root.findLayer(layer.id())
                if layer_node:
                    if layer_node.isVisible() != visible:
                        layer_node.setItemVisibilityChecked(visible)
                        changed += 1
                    else:
                        skipped += 1
                else:
                    skipped += 1
        finally:
            root.blockSignals(False)

        action = "shown" if visible else "hidden"
        logger.info("Bulk %s: %d changed, %d skipped, %d locked", action, changed, skipped, locked)

        return {"changed": changed, "skipped": skipped, "locked": locked}

    def bulk_show(self, item_type: Optional[str] = None, item_ids: Optional[List[str]] = None) -> Dict[str, Any]:
        """Show multiple item layers. See bulk_set_visibility for details."""
        return self.bulk_set_visibility(visible=True, item_type=item_type, item_ids=item_ids)

    def bulk_hide(self, item_type: Optional[str] = None, item_ids: Optional[List[str]] = None) -> Dict[str, Any]:
        """Hide multiple item layers. See bulk_set_visibility for details."""
        return self.bulk_set_visibility(visible=False, item_type=item_type, item_ids=item_ids)

    def set_item_locked(self, item_id: str, locked: bool) -> bool:
        """
        Set the lock state for an item.

        Locked items are protected from bulk operations (show/hide/delete).
        This is a convention - individual operations still work if called directly.

        Args:
            item_id: Item to lock/unlock
            locked: True to lock, False to unlock

        Returns:
            True if lock state was changed
        """
        layer = self.get_layer_by_item_id(item_id)
        if not layer:
            return False

        if locked:
            layer.setCustomProperty("sartracker:locked", "true")
        else:
            layer.removeCustomProperty("sartracker:locked")

        # Update registry metadata
        registry_update_item(
            self.gpkg_path,
            item_id,
            extra_metadata={"locked": locked}
        )

        logger.debug("Item %s lock state: %s", item_id, locked)
        return True

    def is_item_locked(self, item_id: str) -> bool:
        """
        Check if an item is locked.

        Args:
            item_id: Item to check

        Returns:
            True if locked
        """
        layer = self.get_layer_by_item_id(item_id)
        if not layer:
            return False

        return bool(layer.customProperty("sartracker:locked"))

    def get_layer_count_status(self, threshold: Optional[int] = None) -> Dict[str, Any]:
        """
        Get current layer count and warning status.

        Used to warn coordinators before creating too many layers.

        Args:
            threshold: Warning threshold (default: DEFAULT_LAYER_WARNING_THRESHOLD)

        Returns:
            Dict with 'total', 'active', 'orphaned', 'threshold', 'warning'
        """
        if threshold is None:
            threshold = self.DEFAULT_LAYER_WARNING_THRESHOLD

        items = self.discover_existing_items(include_deleted=False)
        total = len(items)
        active = len([i for i in items if i.status == ItemStatus.ACTIVE])
        orphaned = len([i for i in items if i.status == ItemStatus.ORPHANED])

        return {
            "total": total,
            "active": active,
            "orphaned": orphaned,
            "threshold": threshold,
            "warning": total >= threshold,
            "message": f"Layer count ({total}) exceeds threshold ({threshold})" if total >= threshold else None
        }

    def check_can_create_item(self, threshold: Optional[int] = None) -> Tuple[bool, Optional[str]]:
        """
        Check if a new item can be created without exceeding thresholds.

        This is a soft guardrail - returns a warning but doesn't prevent creation.

        Args:
            threshold: Warning threshold (default: DEFAULT_LAYER_WARNING_THRESHOLD)

        Returns:
            Tuple of (can_create: bool, warning_message: Optional[str])
        """
        status = self.get_layer_count_status(threshold)

        if status["warning"]:
            return (True, status["message"])  # Can create, but warn

        return (True, None)

    def bulk_delete(
        self,
        item_type: Optional[str] = None,
        item_ids: Optional[List[str]] = None,
        skip_locked: bool = True,
        hard_delete: bool = False
    ) -> Dict[str, Any]:
        """
        Delete multiple items at once.

        SAFETY: By default skips locked items and uses soft delete.

        Args:
            item_type: Filter by item type (optional)
            item_ids: Specific item IDs to delete (optional)
            skip_locked: Skip locked items (default True)
            hard_delete: Permanently remove (default False = soft delete)

        Returns:
            Dict with 'deleted', 'skipped', 'locked', 'failed' counts
        """
        deleted = 0
        skipped = 0
        locked_count = 0
        failed = 0

        # Get items to process
        if item_ids:
            ids_to_delete = item_ids
        else:
            items = self.discover_existing_items(include_deleted=False, item_type=item_type)
            ids_to_delete = [info.item_id for info in items]

        for item_id in ids_to_delete:
            # Check lock
            if skip_locked and self.is_item_locked(item_id):
                locked_count += 1
                continue

            try:
                success = self.delete_item_layer(
                    item_id,
                    remove_table=hard_delete,
                    hard_delete=hard_delete
                )
                if success:
                    deleted += 1
                else:
                    failed += 1
            except Exception as e:
                logger.error("Failed to delete item %s: %s", item_id, e)
                failed += 1

        logger.info(
            "Bulk delete: %d deleted, %d locked, %d failed",
            deleted, locked_count, failed
        )

        return {
            "deleted": deleted,
            "skipped": skipped,
            "locked": locked_count,
            "failed": failed
        }

    def collapse_all_groups(self) -> int:
        """
        Collapse all SAR Tracker layer groups in the layer tree.

        Useful for cleaning up the view when there are many items.

        Returns:
            Number of groups collapsed
        """
        project = QgsProject.instance()
        root = project.layerTreeRoot()

        collapsed = 0

        def collapse_recursive(group: QgsLayerTreeGroup):
            nonlocal collapsed
            group.setExpanded(False)
            collapsed += 1

            for child in group.children():
                if isinstance(child, QgsLayerTreeGroup):
                    collapse_recursive(child)

        # Find SAR Tracker root group
        sar_root = root.findGroup("SAR Tracker")
        if sar_root:
            collapse_recursive(sar_root)

        logger.info("Collapsed %d groups", collapsed)
        return collapsed

    def expand_all_groups(self) -> int:
        """
        Expand all SAR Tracker layer groups in the layer tree.

        Returns:
            Number of groups expanded
        """
        project = QgsProject.instance()
        root = project.layerTreeRoot()

        expanded = 0

        def expand_recursive(group: QgsLayerTreeGroup):
            nonlocal expanded
            group.setExpanded(True)
            expanded += 1

            for child in group.children():
                if isinstance(child, QgsLayerTreeGroup):
                    expand_recursive(child)

        # Find SAR Tracker root group
        sar_root = root.findGroup("SAR Tracker")
        if sar_root:
            expand_recursive(sar_root)

        logger.info("Expanded %d groups", expanded)
        return expanded

    def set_group_expanded(self, group_name: str, expanded: bool) -> bool:
        """
        Set the expanded state of a specific group.

        Args:
            group_name: Name of the group (e.g., "Clues", "Markers", "Search Areas")
            expanded: True to expand, False to collapse

        Returns:
            True if group was found and state changed
        """
        project = QgsProject.instance()
        root = project.layerTreeRoot()

        # Try to find the group under SAR Tracker
        sar_root = root.findGroup("SAR Tracker")
        if not sar_root:
            return False

        target_group = sar_root.findGroup(group_name)
        if not target_group:
            # Try direct child search
            for child in sar_root.children():
                if isinstance(child, QgsLayerTreeGroup) and child.name() == group_name:
                    target_group = child
                    break

        if target_group:
            target_group.setExpanded(expanded)
            action = "expanded" if expanded else "collapsed"
            logger.debug("Group '%s' %s", group_name, action)
            return True

        return False

    # =========================================================================
    # Performance Mode Methods (Phase 3 - SAR-49s)
    # =========================================================================

    def enable_performance_mode(self, item_type: Optional[str] = None) -> Dict[str, Any]:
        """
        Enable performance mode for items.

        Applies scale-based visibility to reduce rendering load at small scales.
        Critical items (IPP/LKP, casualties) are never hidden.

        Args:
            item_type: Apply only to this type (optional, default all)

        Returns:
            Dict with 'applied', 'skipped', and 'critical_preserved' counts
        """
        items = self.discover_existing_items(include_deleted=False, item_type=item_type)

        applied = 0
        skipped = 0
        critical_preserved = 0

        for item in items:
            if not item.layer:
                skipped += 1
                continue

            if PerformanceMode.apply_scale_visibility(item.layer, item.item_type):
                applied += 1
            else:
                # Item type has threshold=0 (critical, always visible)
                critical_preserved += 1

        logger.info(
            "Performance mode enabled: %d applied, %d critical preserved, %d skipped",
            applied, critical_preserved, skipped
        )

        return {
            "applied": applied,
            "skipped": skipped,
            "critical_preserved": critical_preserved
        }

    def disable_performance_mode(self, item_type: Optional[str] = None) -> int:
        """
        Disable performance mode (remove scale-based visibility).

        Args:
            item_type: Apply only to this type (optional, default all)

        Returns:
            Number of layers updated
        """
        items = self.discover_existing_items(include_deleted=False, item_type=item_type)

        updated = 0
        for item in items:
            if item.layer:
                PerformanceMode.remove_scale_visibility(item.layer)
                updated += 1

        logger.info("Performance mode disabled: %d layers updated", updated)
        return updated

    def ensure_all_spatial_indexes(self) -> Dict[str, Any]:
        """
        Ensure spatial indexes exist for all item tables.

        Should be called after mission load or periodically for large missions.

        Returns:
            Dict with 'created', 'existing', and 'failed' counts
        """
        items = self.get_registry_items(include_deleted=False)

        created = 0
        existing = 0
        failed = 0

        processed_tables: Set[str] = set()

        for item in items:
            if item.table_name in processed_tables:
                continue

            processed_tables.add(item.table_name)

            # Check current status
            status = get_spatial_index_status(self.gpkg_path)
            if item.table_name in status.get("indexed_tables", []):
                existing += 1
            elif ensure_spatial_index(self.gpkg_path, item.table_name):
                created += 1
            else:
                failed += 1

        logger.info(
            "Spatial index check: %d created, %d existing, %d failed",
            created, existing, failed
        )

        return {
            "created": created,
            "existing": existing,
            "failed": failed,
            "total_tables": len(processed_tables)
        }

    def get_performance_status(self) -> Dict[str, Any]:
        """
        Get current performance mode status.

        Returns:
            Dict with performance metrics and recommendations
        """
        items = self.discover_existing_items(include_deleted=False)

        total = len(items)
        active = len([i for i in items if i.status == ItemStatus.ACTIVE])
        scale_visibility_enabled = 0
        critical_items = 0

        for item in items:
            if item.layer and item.layer.hasScaleBasedVisibility():
                scale_visibility_enabled += 1
            if item.item_type in (ItemType.MARKER_IPP_LKP, ItemType.MARKER_CASUALTY):
                critical_items += 1

        # Get spatial index status
        index_status = get_spatial_index_status(self.gpkg_path)

        # Recommendations
        recommendations = []
        if total > 50 and scale_visibility_enabled == 0:
            recommendations.append("Consider enabling performance mode for better responsiveness")
        if index_status.get("not_indexed", 0) > 0:
            recommendations.append(
                f"Run ensure_all_spatial_indexes() to index {index_status['not_indexed']} tables"
            )

        return {
            "total_items": total,
            "active_items": active,
            "scale_visibility_enabled": scale_visibility_enabled,
            "critical_items": critical_items,
            "spatial_indexes": index_status,
            "recommendations": recommendations
        }

    # =========================================================================
    # Private Methods
    # =========================================================================

    def _create_gpkg_layer(
        self,
        table_name: str,
        geometry_type: str,
        display_name: str,
        fields: Optional[List[Dict[str, Any]]] = None
    ) -> Optional[QgsVectorLayer]:
        """
        Create a new table in the GeoPackage and return a layer for it.

        Args:
            table_name: Name for the GeoPackage table
            geometry_type: 'Point', 'LineString', or 'Polygon'
            display_name: User-visible layer name
            fields: Optional field definitions

        Returns:
            QgsVectorLayer connected to the new table, or None on failure
        """
        # Build field list
        qgs_fields = QgsFields()

        # Add standard fields
        qgs_fields.append(QgsField("id", QVariant.String, len=36))
        qgs_fields.append(QgsField("name", QVariant.String, len=120))
        qgs_fields.append(QgsField("description", QVariant.String, len=255))
        qgs_fields.append(QgsField("created_at", QVariant.String, len=40))
        qgs_fields.append(QgsField("updated_at", QVariant.String, len=40))

        # Add custom fields if provided
        if fields:
            for field_def in fields:
                field_name = field_def.get("name", "")
                field_type_str = field_def.get("type", "String")
                field_len = field_def.get("length", 255)

                # Map string type names to QVariant types
                type_map = {
                    "String": QVariant.String,
                    "Int": QVariant.Int,
                    "Double": QVariant.Double,
                    "Bool": QVariant.Bool,
                }
                field_type = type_map.get(field_type_str, QVariant.String)

                if field_name and field_name not in [f.name() for f in qgs_fields]:
                    qgs_fields.append(QgsField(field_name, field_type, len=field_len))

        # Determine geometry type for OGR
        geom_type_map = {
            "Point": 1,  # wkbPoint
            "LineString": 2,  # wkbLineString
            "Polygon": 3,  # wkbPolygon
        }
        ogr_geom_type = geom_type_map.get(geometry_type, 1)

        # CRS - WGS84
        crs = QgsCoordinateReferenceSystem("EPSG:4326")

        # Create or append to GeoPackage
        gpkg_exists = self.gpkg_path.exists()

        options = QgsVectorFileWriter.SaveVectorOptions()
        options.driverName = "GPKG"
        options.layerName = table_name
        options.fileEncoding = "UTF-8"

        if gpkg_exists:
            options.actionOnExistingFile = QgsVectorFileWriter.CreateOrOverwriteLayer
        else:
            options.actionOnExistingFile = QgsVectorFileWriter.CreateOrOverwriteFile

        # Create a temporary memory layer to write from
        mem_uri = f"{geometry_type}?crs=EPSG:4326"
        mem_layer = QgsVectorLayer(mem_uri, "temp", "memory")

        if not mem_layer.isValid():
            logger.error("Failed to create temp memory layer")
            return None

        # Add fields to memory layer
        mem_layer.dataProvider().addAttributes(qgs_fields.toList())
        mem_layer.updateFields()

        # Write to GeoPackage
        transform_context = QgsProject.instance().transformContext()

        error = QgsVectorFileWriter.writeAsVectorFormatV3(
            mem_layer,
            str(self.gpkg_path),
            transform_context,
            options
        )

        if error[0] != QgsVectorFileWriter.NoError:
            logger.error("Failed to create GeoPackage table %s: %s", table_name, error[1])
            return None

        # Enable WAL mode if this is a new GeoPackage
        if not gpkg_exists:
            enable_wal_mode(self.gpkg_path)

        # Open the layer from the GeoPackage
        uri = f"{self.gpkg_path}|layername={table_name}"
        layer = QgsVectorLayer(uri, display_name, "ogr")

        if not layer.isValid():
            logger.error("Failed to open GeoPackage layer: %s", uri)
            return None

        return layer

    def _add_layer_to_project(
        self,
        layer: QgsVectorLayer,
        target_group: Optional[QgsLayerTreeGroup] = None
    ):
        """
        Add a layer to the current QGIS project.

        Args:
            layer: Layer to add
            target_group: Optional group to add to (default: root)
        """
        project = QgsProject.instance()

        # Add without legend first
        project.addMapLayer(layer, False)

        # Then add to tree
        root = project.layerTreeRoot()

        if target_group:
            target_group.addLayer(layer)
        else:
            root.addLayer(layer)

    def _extract_table_name(self, layer: QgsVectorLayer) -> str:
        """
        Extract the GeoPackage table name from a layer's data source.

        Args:
            layer: The layer to examine

        Returns:
            Table name, or empty string if not a GeoPackage layer
        """
        source = layer.source()
        for part in source.split("|"):
            if part.startswith("layername="):
                return part.split("=", 1)[1]
        return ""

    def _drop_gpkg_table(self, table_name: str) -> bool:
        """
        Remove a table from the GeoPackage.

        Args:
            table_name: Name of table to remove

        Returns:
            True if removal successful
        """
        conn = None
        try:
            conn = sqlite3.connect(str(self.gpkg_path))

            # Remove from gpkg_contents
            conn.execute(
                "DELETE FROM gpkg_contents WHERE table_name = ?",
                (table_name,)
            )

            # Remove from gpkg_geometry_columns
            conn.execute(
                "DELETE FROM gpkg_geometry_columns WHERE table_name = ?",
                (table_name,)
            )

            # Drop the table itself
            conn.execute(f'DROP TABLE IF EXISTS "{table_name}"')

            # Drop spatial index if exists
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE ?",
                (f"rtree_{table_name}_%",)
            )
            for row in cursor.fetchall():
                conn.execute(f'DROP TABLE IF EXISTS "{row[0]}"')

            conn.commit()

            logger.debug("Dropped GeoPackage table: %s", table_name)
            return True

        except sqlite3.Error as e:
            logger.error("Error dropping GeoPackage table %s: %s", table_name, e)
            return False
        finally:
            if conn:
                conn.close()


# =============================================================================
# Convenience Functions
# =============================================================================

def create_per_item_clue(
    factory: PerItemLayerFactory,
    name: str,
    **kwargs
) -> ItemLayerInfo:
    """
    Convenience function to create a clue marker layer.

    Args:
        factory: PerItemLayerFactory instance
        name: Display name for the clue
        **kwargs: Additional arguments passed to create_item_layer

    Returns:
        ItemLayerInfo for the created layer
    """
    from ..layers.schema import CLUE_FIELDS

    return factory.create_item_layer(
        item_type=ItemType.MARKER_CLUE,
        display_name=name,
        fields=CLUE_FIELDS,
        **kwargs
    )


def create_per_item_search_area(
    factory: PerItemLayerFactory,
    name: str,
    **kwargs
) -> ItemLayerInfo:
    """
    Convenience function to create a search area layer.

    Args:
        factory: PerItemLayerFactory instance
        name: Display name for the search area
        **kwargs: Additional arguments passed to create_item_layer

    Returns:
        ItemLayerInfo for the created layer
    """
    from ..layers.schema import SEARCH_AREA_FIELDS

    return factory.create_item_layer(
        item_type=ItemType.SEARCH_AREA,
        display_name=name,
        fields=SEARCH_AREA_FIELDS,
        **kwargs
    )
