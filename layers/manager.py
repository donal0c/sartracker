# -*- coding: utf-8 -*-
"""
SAR Tracker Layer Manager

Provides idempotent creation and retrieval of layer groups and layers according
to the canonical schema. Manages layer cache, project signals, and ensures
persistent layer structure across plugin sessions.

Qt5/Qt6 Compatible: Uses qgis.PyQt and qt_compat for all Qt imports.
"""

from pathlib import Path
from typing import Dict, List, Optional, Callable
from qgis.PyQt.QtCore import QVariant
from qgis.core import (
    QgsProject,
    QgsVectorLayer,
    QgsField,
    QgsLayerTreeGroup,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransformContext,
    QgsMarkerSymbol,
    QgsLineSymbol,
    QgsFillSymbol,
    QgsWkbTypes,
    QgsMapLayerStyle,
    QgsVectorLayerExporter,
    QgsVectorFileWriter
)

from .schema import (
    SAR_LAYER_SCHEMA_VERSION,
    GroupNames,
    LayerIds,
    LayerDefinition,
    GroupDefinition,
    get_expected_structure,
    get_group_path,
    get_layer_by_id,
    LAYER_GROUP_PATHS,
    LAYER_NAME_TO_ID,
    LAYER_FIELD_CHECKS
)
from ..utils.notify import info, warning, error


# Qt type mapping for field creation
# Use QVariant constants directly for Qt5/Qt6 compatibility
QT_TYPE_MAP = {
    "String": QVariant.String,
    "Int": QVariant.Int,
    "Double": QVariant.Double,
    "DateTime": QVariant.DateTime,
    "Bool": QVariant.Bool
}

GEOMETRY_WKB_MAP = {
    "Point": QgsWkbTypes.Point,
    "LineString": QgsWkbTypes.LineString,
    "Polygon": QgsWkbTypes.Polygon
}

_HAS_EXPORTER_SAVE_OPTIONS = hasattr(QgsVectorLayerExporter, "SaveVectorOptions")


def _create_save_vector_options():
    """Return a SaveVectorOptions instance compatible with the running QGIS version."""
    if _HAS_EXPORTER_SAVE_OPTIONS:
        return QgsVectorLayerExporter.SaveVectorOptions()
    return QgsVectorFileWriter.SaveVectorOptions()


def _export_layer(layer, path, options, transform_context):
    """Export a layer using the best available writer API."""
    if _HAS_EXPORTER_SAVE_OPTIONS:
        return QgsVectorLayerExporter.exportLayer(layer, path, options, transform_context)
    return QgsVectorFileWriter.writeAsVectorFormatV3(layer, path, transform_context, options)


_EXPORT_CREATE_OR_OVERWRITE = (
    QgsVectorLayerExporter.CreateOrOverwriteLayer
    if _HAS_EXPORTER_SAVE_OPTIONS
    else QgsVectorFileWriter.CreateOrOverwriteLayer
)

_EXPORT_NO_ERROR = (
    QgsVectorLayerExporter.NoError
    if _HAS_EXPORTER_SAVE_OPTIONS
    else QgsVectorFileWriter.NoError
)


def _set_option_if_available(options, attr_name, value):
    """Safely set advanced exporter options that may not exist on older QGIS releases."""
    if hasattr(options, attr_name):
        setattr(options, attr_name, value)


class LayerManager:
    """
    Manages the SAR Tracker layer hierarchy with idempotent operations.

    This class ensures that all mission artifacts are stored in a predictable,
    persistent layer structure. It provides methods to create groups and layers
    according to the canonical schema, with automatic migration and repair.

    Attributes:
        project: The current QGIS project
        iface: QGIS interface
        _layer_cache: Cache of layer IDs to layer objects
        _group_cache: Cache of group paths to group objects
        _signals_connected: Whether project signals are connected
    """

    MISSION_STORE_VAR = "sartracker:mission_store_path"
    MISSION_STORE_DRIVER = "GPKG"
    MISSION_STORE_PROVIDER = "ogr"

    def __init__(self, iface):
        """
        Initialize the LayerManager.

        Args:
            iface: QGIS interface instance
        """
        self.iface = iface
        self.project = QgsProject.instance()
        self._layer_cache: Dict[str, QgsVectorLayer] = {}
        self._group_cache: Dict[str, QgsLayerTreeGroup] = {}
        self._signals_connected = False
        self._mission_store_path: Optional[str] = self._load_mission_store_path()
        self._layer_provider_uris: Dict[str, str] = {}

        # Connect to project signals for cache management
        self._connect_signals()

    def _connect_signals(self):
        """Connect to project signals to manage cache lifecycle."""
        if not self._signals_connected:
            try:
                self.project.layersWillBeRemoved.connect(self._on_layers_removed)
                self._signals_connected = True
            except Exception as e:
                print(f"[LayerManager] Warning: Could not connect signals: {e}")

    def _load_mission_store_path(self) -> Optional[str]:
        """Read mission store path from project custom variables."""
        try:
            value = self.project.customVariables().get(self.MISSION_STORE_VAR)
            if value:
                return str(Path(value).expanduser())
        except Exception as exc:
            print(f"[LayerManager] Warning: Could not load mission store path: {exc}")
        return None

    def set_mission_store(self, path: str):
        """
        Configure the mission store GeoPackage path.

        Args:
            path: Absolute path to the mission GeoPackage file.
        """
        if not path or not isinstance(path, str):
            raise ValueError("Mission store path must be a non-empty string")

        normalized = str(Path(path).expanduser())
        target_dir = Path(normalized).parent
        target_dir.mkdir(parents=True, exist_ok=True)

        try:
            self.project.setCustomVariable(self.MISSION_STORE_VAR, normalized)
        except Exception as exc:
            print(f"[LayerManager] Warning: Failed to persist mission store path: {exc}")

        self._mission_store_path = normalized
        self._layer_provider_uris.clear()
        self._layer_cache.clear()

    def get_mission_store(self) -> Optional[str]:
        """Return the configured mission store path, if any."""
        return self._mission_store_path

    def clear_mission_store(self):
        """Remove the mission store association from the project."""
        try:
            self.project.setCustomVariable(self.MISSION_STORE_VAR, "")
        except Exception as exc:
            print(f"[LayerManager] Warning: Failed to clear mission store variable: {exc}")

        self._mission_store_path = None
        self._layer_provider_uris.clear()
        self._layer_cache.clear()

    def _mission_store_enabled(self) -> bool:
        return bool(self._mission_store_path)

    def disconnect_signals(self):
        """Disconnect from project signals on cleanup."""
        if self._signals_connected:
            try:
                self.project.layersWillBeRemoved.disconnect(self._on_layers_removed)
                self._signals_connected = False
            except Exception as e:
                print(f"[LayerManager] Warning: Could not disconnect signals: {e}")

    def _on_layers_removed(self, layer_ids: List[str]):
        """
        Handle layer removal by clearing cache entries.

        Args:
            layer_ids: List of layer IDs being removed
        """
        for layer_id in layer_ids:
            # Remove from cache if present
            cache_keys_to_remove = [k for k, v in self._layer_cache.items() if v.id() == layer_id]
            for key in cache_keys_to_remove:
                del self._layer_cache[key]
                print(f"[LayerManager] Removed {key} from cache")

    def ensure_structure(self, auto_migrate: bool = True) -> bool:
        """
        Ensure the complete SAR Tracker layer structure exists.

        Creates the root group and all nested groups/layers according to the
        schema. If the structure already exists, verifies and updates as needed.
        Handles migration from older schema versions.

        Args:
            auto_migrate: If True, automatically migrate older projects

        Returns:
            True if structure created/verified successfully, False otherwise
        """
        try:
            self._rename_legacy_root_group()

            # Check current schema version
            current_version = self._get_schema_version()

            if current_version is None:
                # New project or pre-schema project
                info(self.iface.messageBar(),
                     "Layer Setup",
                     "Creating SAR Tracker layer structure...")
                created = self._create_structure()
                if created:
                    self._set_schema_version(SAR_LAYER_SCHEMA_VERSION)
                self._organize_existing_layers()
                return created

            elif current_version != SAR_LAYER_SCHEMA_VERSION:
                # Schema version mismatch
                if auto_migrate:
                    warning(self.iface.messageBar(),
                           "Layer Migration",
                           f"Migrating layer structure from v{current_version} to v{SAR_LAYER_SCHEMA_VERSION}")
                    migrated = self._migrate_structure(current_version)
                    if migrated:
                        self._set_schema_version(SAR_LAYER_SCHEMA_VERSION)
                    self._organize_existing_layers()
                    return migrated
                else:
                    warning(self.iface.messageBar(),
                           "Schema Version",
                           f"Layer schema version mismatch (project: v{current_version}, plugin: v{SAR_LAYER_SCHEMA_VERSION})")
                    return False

            else:
                # Schema version matches - verify structure
                valid = self._verify_structure()
                self._organize_existing_layers()
                return valid

        except Exception as e:
            error(self.iface.messageBar(),
                  "Layer Setup Error",
                  f"Failed to ensure layer structure: {str(e)}")
            print(f"[LayerManager] Error in ensure_structure: {e}")
            import traceback
            traceback.print_exc()
            return False

    def _get_schema_version(self) -> Optional[int]:
        """
        Get the current schema version from project variables.

        Returns:
            Schema version number, or None if not set
        """
        try:
            custom_vars = self.project.customVariables()
            if 'sar_layer_schema' in custom_vars:
                return int(custom_vars['sar_layer_schema'])
            return None
        except (ValueError, KeyError):
            return None

    def _set_schema_version(self, version: int):
        """
        Set the schema version in project variables.

        Args:
            version: Schema version number to set
        """
        try:
            self.project.setCustomVariable('sar_layer_schema', version)
            print(f"[LayerManager] Set schema version to {version}")
        except Exception as e:
            print(f"[LayerManager] Warning: Could not set schema version: {e}")

    def _create_structure(self) -> bool:
        """
        Create the complete layer structure from scratch.

        Returns:
            True if successful, False otherwise
        """
        try:
            structure = get_expected_structure()
            self._create_group_recursive(structure)
            print("[LayerManager] Created complete layer structure")
            return True
        except Exception as e:
            print(f"[LayerManager] Error creating structure: {e}")
            import traceback
            traceback.print_exc()
            return False

    def _create_group_recursive(self, group_def: GroupDefinition, parent: Optional[QgsLayerTreeGroup] = None):
        """
        Recursively create groups and layers from a group definition.

        Args:
            group_def: Group definition to create
            parent: Parent group (None = root)
        """
        # Create the group
        group = self.ensure_group(get_group_path(group_def.name), position=group_def.position)

        # Set group metadata
        if group_def.metadata:
            for key, value in group_def.metadata.items():
                group.setCustomProperty(key, value)

        # Create layers in this group
        if group_def.layers:
            for layer_def in group_def.layers:
                if layer_def.auto_create:
                    self.ensure_vector_layer(
                        layer_def=layer_def,
                        group_path=get_group_path(group_def.name)
                    )

        # Create subgroups recursively
        if group_def.subgroups:
            for subgroup_def in group_def.subgroups:
                self._create_group_recursive(subgroup_def, group)

    def _verify_structure(self) -> bool:
        """
        Verify that the layer structure matches the schema.

        Returns:
            True if structure is valid, False otherwise
        """
        try:
            # Check root group exists
            root = self.project.layerTreeRoot()
            sar_group = root.findGroup(GroupNames.ROOT)
            if not sar_group:
                warning(self.iface.messageBar(),
                       "Layer Verification",
                       "Root group missing - use 'Repair Layers' in Settings")
                return False

            # Structure exists - could add more detailed verification here
            return True

        except Exception as e:
            print(f"[LayerManager] Error verifying structure: {e}")
            return False

    def _migrate_structure(self, from_version: int) -> bool:
        """
        Migrate layer structure from an older version.

        Args:
            from_version: Source schema version

        Returns:
            True if migration successful, False otherwise
        """
        try:
            print(f"[LayerManager] Migrating from schema version {from_version}")

            # Create any missing groups/layers
            structure = get_expected_structure()
            self._create_group_recursive(structure)

            # Could add version-specific migration logic here
            # For now, just ensure structure exists

            return True

        except Exception as e:
            print(f"[LayerManager] Error during migration: {e}")
            import traceback
            traceback.print_exc()
            return False

    def ensure_group(self, path: List[str], position: int = 0) -> QgsLayerTreeGroup:
        """
        Ensure a group exists in the layer tree, creating it if necessary.

        This method is idempotent - safe to call multiple times.

        Args:
            path: List of group names from root to target (e.g., ['SAR Tracker', 'Helicopters'])
            position: Position within parent group (0 = top)

        Returns:
            QgsLayerTreeGroup object

        Raises:
            RuntimeError: If group creation fails
        """
        # Check cache first
        cache_key = "/".join(path)
        if cache_key in self._group_cache:
            cached_group = self._group_cache[cache_key]
            # Verify cached group still exists
            if self._group_exists(cached_group):
                return cached_group
            else:
                del self._group_cache[cache_key]

        # Navigate/create group hierarchy
        root = self.project.layerTreeRoot()
        current_parent = root
        current_path = []

        for group_name in path:
            current_path.append(group_name)
            path_key = "/".join(current_path)

            # Check if group exists
            group = current_parent.findGroup(group_name)

            if not group:
                # Create group
                group = current_parent.insertGroup(position, group_name)
                if not group:
                    raise RuntimeError(f"Failed to create group: {group_name}")
                print(f"[LayerManager] Created group: {path_key}")

            # Cache the group
            self._group_cache[path_key] = group
            current_parent = group

        return current_parent

    def _group_exists(self, group: QgsLayerTreeGroup) -> bool:
        """
        Check if a group still exists in the layer tree.

        Args:
            group: Group to check

        Returns:
            True if group exists, False otherwise
        """
        try:
            # Try to access a property - will fail if group deleted
            _ = group.name()
            return True
        except:
            return False

    def ensure_vector_layer(
        self,
        layer_def: LayerDefinition,
        group_path: List[str],
        style_factory: Optional[Callable[[QgsVectorLayer], None]] = None
    ) -> QgsVectorLayer:
        """
        Ensure a vector layer exists, creating it if necessary.

        This method is idempotent - safe to call multiple times.

        Args:
            layer_def: Layer definition from schema
            group_path: Path to parent group
            style_factory: Optional function to apply custom styling

        Returns:
            QgsVectorLayer object

        Raises:
            RuntimeError: If layer creation fails
        """
        # Check cache first
        if layer_def.layer_id in self._layer_cache:
            cached_layer = self._layer_cache[layer_def.layer_id]
            # Verify cached layer still exists
            if self._layer_exists(cached_layer):
                return cached_layer
            else:
                del self._layer_cache[layer_def.layer_id]

        # Check if layer already exists in project
        existing_layer = self._find_layer_by_id(layer_def.layer_id)
        if existing_layer:
            self._layer_cache[layer_def.layer_id] = existing_layer
            return existing_layer

        # Create new layer
        layer = self._create_vector_layer(layer_def)

        # Apply custom styling if provided
        if style_factory:
            try:
                style_factory(layer)
            except Exception as e:
                print(f"[LayerManager] Warning: Style factory failed: {e}")

        # Add layer to project and group
        group = self.ensure_group(group_path)
        self.project.addMapLayer(layer, False)  # Don't add to root
        group.insertLayer(layer_def.position, layer)

        # Set layer metadata
        if layer_def.metadata:
            for key, value in layer_def.metadata.items():
                layer.setCustomProperty(key, value)

        # Store layer ID for retrieval
        layer.setCustomProperty('sartracker:layer_id', layer_def.layer_id)

        # Cache the layer
        self._layer_cache[layer_def.layer_id] = layer

        print(f"[LayerManager] Created layer: {layer_def.name} ({layer_def.layer_id})")

        return layer

    def _create_vector_layer(self, layer_def: LayerDefinition) -> QgsVectorLayer:
        """Create a layer backed by memory or the mission store."""
        if self._mission_store_enabled():
            return self._ensure_persistent_layer(layer_def)
        return self._create_memory_layer(layer_def)

    def _create_memory_layer(self, layer_def: LayerDefinition) -> QgsVectorLayer:
        """
        Create a QgsVectorLayer from a layer definition.

        Args:
            layer_def: Layer definition

        Returns:
            QgsVectorLayer object

        Raises:
            RuntimeError: If layer creation fails
        """
        # Create CRS
        crs = QgsCoordinateReferenceSystem(f"EPSG:{layer_def.crs_epsg}")
        if not crs.isValid():
            raise RuntimeError(f"Invalid CRS: EPSG:{layer_def.crs_epsg}")

        # Create layer URI
        uri = f"{layer_def.geometry_type}?crs=EPSG:{layer_def.crs_epsg}"

        # Create layer
        layer = QgsVectorLayer(uri, layer_def.name, "memory")
        if not layer.isValid():
            raise RuntimeError(f"Failed to create layer: {layer_def.name}")

        # Add fields
        if layer_def.fields:
            layer.startEditing()
            try:
                for field_def in layer_def.fields:
                    field = self._create_field(field_def)
                    if not layer.addAttribute(field):
                        raise RuntimeError(f"Failed to add field: {field_def['name']}")

                if not layer.commitChanges():
                    errors = layer.commitErrors()
                    raise RuntimeError(f"Failed to commit field changes: {errors}")

            except Exception as e:
                layer.rollBack()
                raise RuntimeError(f"Error adding fields: {e}")

            finally:
                # Safety net: Ensure layer is NEVER left in edit mode (Issue #3 critical fix)
                if layer.isEditable():
                    layer.rollBack()

        return layer

    def _ensure_mission_store_directory(self):
        """Ensure the directory containing the mission store exists."""
        if not self._mission_store_path:
            raise RuntimeError("Mission store path is not configured")
        Path(self._mission_store_path).parent.mkdir(parents=True, exist_ok=True)

    def _build_mission_store_uri(self, layer_def: LayerDefinition) -> str:
        """Construct and cache the provider URI for a mission-store layer."""
        if layer_def.layer_id in self._layer_provider_uris:
            return self._layer_provider_uris[layer_def.layer_id]

        if not self._mission_store_path:
            raise RuntimeError("Mission store path is not configured")

        uri = f"{self._mission_store_path}|layername={layer_def.layer_id}"
        self._layer_provider_uris[layer_def.layer_id] = uri
        return uri

    def _load_persistent_layer(self, layer_def: LayerDefinition) -> Optional[QgsVectorLayer]:
        """Try to load an existing GeoPackage layer."""
        if not self._mission_store_path:
            return None

        uri = self._build_mission_store_uri(layer_def)
        layer = QgsVectorLayer(uri, layer_def.name, self.MISSION_STORE_PROVIDER)
        if layer.isValid():
            layer.setCustomProperty('sartracker:layer_id', layer_def.layer_id)
            return layer

        return None

    def _create_persistent_table(self, layer_def: LayerDefinition):
        """Create an empty GeoPackage table for the layer definition."""
        self._ensure_mission_store_directory()
        template_layer = self._create_memory_layer(layer_def)

        options = _create_save_vector_options()
        options.driverName = self.MISSION_STORE_DRIVER
        options.layerName = layer_def.layer_id
        options.actionOnExistingFile = _EXPORT_CREATE_OR_OVERWRITE
        options.fileEncoding = "UTF-8"
        options.onlySelectedFeatures = False
        _set_option_if_available(options, "includeMetadata", True)
        _set_option_if_available(options, "overwriteWithEmptyLayer", True)

        result, error_message = _export_layer(
            template_layer,
            self._mission_store_path,
            options,
            QgsCoordinateTransformContext()
        )

        if result != _EXPORT_NO_ERROR:
            raise RuntimeError(
                f"Failed to create persistent layer '{layer_def.layer_id}': {error_message}"
            )

    def _ensure_persistent_layer(self, layer_def: LayerDefinition) -> QgsVectorLayer:
        """Ensure a GeoPackage-backed layer exists and return it."""
        layer = self._load_persistent_layer(layer_def)
        if layer:
            return layer

        self._create_persistent_table(layer_def)
        layer = self._load_persistent_layer(layer_def)
        if not layer or not layer.isValid():
            raise RuntimeError(f"Persistent layer '{layer_def.layer_id}' could not be loaded")
        return layer

    def _create_field(self, field_def: Dict) -> QgsField:
        """
        Create a QgsField from a field definition.

        Args:
            field_def: Field definition dictionary

        Returns:
            QgsField object
        """
        field_name = field_def["name"]
        field_type_str = field_def["type"]
        field_length = field_def.get("length", 0)

        # Map type string to QVariant type code
        qt_type = QT_TYPE_MAP.get(field_type_str, 10)  # Default to String

        return QgsField(field_name, qt_type, field_type_str, field_length)

    def _find_layer_by_id(self, layer_id: str) -> Optional[QgsVectorLayer]:
        """
        Find a layer in the project by its SAR Tracker layer ID.

        Args:
            layer_id: SAR Tracker layer ID

        Returns:
            QgsVectorLayer if found, None otherwise
        """
        for layer in self.project.mapLayers().values():
            if isinstance(layer, QgsVectorLayer):
                stored_id = layer.customProperty('sartracker:layer_id')
                if stored_id == layer_id:
                    return layer
        return None

    def _layer_exists(self, layer: QgsVectorLayer) -> bool:
        """
        Check if a layer still exists in the project.

        Args:
            layer: Layer to check

        Returns:
            True if layer exists, False otherwise
        """
        try:
            return layer.id() in self.project.mapLayers()
        except:
            return False

    def get_layer(self, layer_id: str) -> Optional[QgsVectorLayer]:
        """
        Get a layer by its SAR Tracker layer ID.

        Args:
            layer_id: SAR Tracker layer ID from LayerIds

        Returns:
            QgsVectorLayer if found, None otherwise
        """
        # Check cache first
        if layer_id in self._layer_cache:
            cached_layer = self._layer_cache[layer_id]
            if self._layer_exists(cached_layer):
                return cached_layer
            else:
                del self._layer_cache[layer_id]

        # Search project
        layer = self._find_layer_by_id(layer_id)
        if layer:
            self._layer_cache[layer_id] = layer

        return layer

    def ensure_persistent_layer(self, layer_id: str) -> QgsVectorLayer:
        """
        Ensure a mission-store backed layer exists and return it.

        Args:
            layer_id: SAR Tracker layer ID

        Returns:
            QgsVectorLayer backed by the mission store
        """
        layer_def = get_layer_by_id(layer_id)
        if not layer_def:
            raise ValueError(f"Unknown layer id: {layer_id}")
        if not self._mission_store_enabled():
            raise RuntimeError("Mission store is not configured")
        return self._ensure_persistent_layer(layer_def)

    def get_helicopter_layer(self, slot: int) -> Optional[QgsVectorLayer]:
        """
        Get a helicopter layer by slot number (1-4).

        Args:
            slot: Helicopter slot number (1-4)

        Returns:
            QgsVectorLayer if found, None otherwise

        Raises:
            ValueError: If slot number invalid
        """
        if not 1 <= slot <= 4:
            raise ValueError(f"Invalid helicopter slot: {slot}. Must be 1-4.")

        layer_id = getattr(LayerIds, f"HELICOPTER_{slot}")
        return self.get_layer(layer_id)

    def repair_structure(self) -> bool:
        """
        Repair the layer structure by recreating missing groups/layers.

        Returns:
            True if repair successful, False otherwise
        """
        try:
            info(self.iface.messageBar(),
                 "Layer Repair",
                 "Repairing SAR Tracker layer structure...")

            # Clear caches
            self._layer_cache.clear()
            self._group_cache.clear()

            # Recreate structure (rebuild groups + auto-created layers)
            success = self._create_structure()

            if success:
                self._set_schema_version(SAR_LAYER_SCHEMA_VERSION)
                self._organize_existing_layers()
                info(self.iface.messageBar(),
                     "Layer Repair",
                     "Layer structure repaired successfully")
            else:
                error(self.iface.messageBar(),
                      "Layer Repair",
                      "Failed to repair layer structure")

            return success

        except Exception as e:
            error(self.iface.messageBar(),
                  "Layer Repair Error",
                  f"Error repairing structure: {str(e)}")
            print(f"[LayerManager] Error in repair_structure: {e}")
            import traceback
            traceback.print_exc()
            return False

    def migrate_memory_layer_to_store(self, layer: QgsVectorLayer, layer_def: LayerDefinition) -> QgsVectorLayer:
        """
        Export an existing memory layer into the mission store.

        Args:
            layer: Source memory-backed layer
            layer_def: Target schema definition

        Returns:
            The newly created persistent layer
        """
        if not self._mission_store_enabled():
            raise RuntimeError("Mission store is not configured")

        if not layer or layer.providerType() != "memory":
            raise ValueError("Only memory layers can be migrated")

        options = _create_save_vector_options()
        options.driverName = self.MISSION_STORE_DRIVER
        options.layerName = layer_def.layer_id
        options.actionOnExistingFile = _EXPORT_CREATE_OR_OVERWRITE
        options.fileEncoding = "UTF-8"
        _set_option_if_available(options, "includeMetadata", True)

        result, error_message = _export_layer(
            layer,
            self._mission_store_path,
            options,
            self.project.transformContext()
        )

        if result != _EXPORT_NO_ERROR:
            raise RuntimeError(
                f"Failed to migrate layer '{layer_def.layer_id}' to mission store: {error_message}"
            )

        persistent_layer = self._load_persistent_layer(layer_def)
        if not persistent_layer:
            raise RuntimeError(f"Persistent layer '{layer_def.layer_id}' could not be loaded after migration")

        style = QgsMapLayerStyle()
        if style.readFromLayer(layer):
            style.writeToLayer(persistent_layer)

        persistent_layer.setCustomProperty('sartracker:layer_id', layer_def.layer_id)
        persistent_layer.triggerRepaint()
        return persistent_layer

    def route_feature(self, category: str, feature):
        """
        Route a feature to the appropriate layer based on category.

        Args:
            category: Artifact category (e.g., 'clue', 'marker_ipp_lkp')
            feature: QgsFeature to add

        Raises:
            ValueError: If category is invalid
            RuntimeError: If feature addition fails
        """
        from .schema import ARTIFACT_LAYER_MAP

        if category not in ARTIFACT_LAYER_MAP:
            raise ValueError(f"Unknown artifact category: {category}")

        layer_id = ARTIFACT_LAYER_MAP[category]
        layer = self.get_layer(layer_id)

        if not layer:
            raise RuntimeError(f"Layer not found for category: {category}")

        # Add feature to layer
        layer.startEditing()
        try:
            if not layer.addFeature(feature):
                raise RuntimeError(f"Failed to add feature to layer: {layer.name()}")

            if not layer.commitChanges():
                errors = layer.commitErrors()
                raise RuntimeError(f"Failed to commit changes: {errors}")

        except Exception as e:
            layer.rollBack()
            raise

        finally:
            # Safety net: Ensure layer is NEVER left in edit mode (Issue #3 critical fix)
            if layer.isEditable():
                layer.rollBack()

    def validate_persistence(self, quiet: bool = False) -> Dict[str, str]:
        """
        Validate that managed layers are backed by non-memory providers.

        Returns:
            Dict mapping layer_ids to issue description (empty if healthy)
        """
        issues: Dict[str, str] = {}
        if not self._mission_store_enabled():
            if not quiet:
                warning(self.iface.messageBar(),
                        "Mission Store",
                        "Mission store is not configured; layers remain in memory.")
            issues["mission_store"] = "not_configured"
            return issues

        for layer_def in self._collect_layer_definitions():
            layer = self.get_layer(layer_def.layer_id)
            if not layer:
                issues[layer_def.layer_id] = "missing"
                continue

            provider = (layer.providerType() or "").lower()
            if provider == "memory":
                issues[layer_def.layer_id] = "memory"

        if issues:
            if not quiet:
                warning(self.iface.messageBar(),
                        "Persistence Diagnostics",
                        f"{len(issues)} layer(s) still use memory providers.")
        else:
            if not quiet:
                info(self.iface.messageBar(),
                     "Persistence Diagnostics",
                     "All managed layers use persistent providers.")

        return issues

    def clear_cache(self):
        """Clear all cached layer and group references."""
        self._layer_cache.clear()
        self._group_cache.clear()
        print("[LayerManager] Cleared layer cache")

    # ------------------------------------------------------------------
    # Legacy structure helpers
    # ------------------------------------------------------------------

    def _rename_legacy_root_group(self):
        """Rename or merge the legacy SAR Tracking root group."""
        root = self.project.layerTreeRoot()
        if not root:
            return

        legacy_group = root.findGroup("SAR Tracking")
        modern_group = root.findGroup(GroupNames.ROOT)

        if legacy_group and legacy_group == modern_group:
            # Already renamed
            legacy_group.setName(GroupNames.ROOT)
            return

        if legacy_group and not modern_group:
            legacy_group.setName(GroupNames.ROOT)
            return

        if legacy_group and modern_group and legacy_group != modern_group:
            # Move children then remove legacy group
            children = list(legacy_group.children())
            for child in children:
                legacy_group.removeChildNode(child)
                modern_group.insertChildNode(0, child)
            parent = legacy_group.parent()
            if parent:
                parent.removeChildNode(legacy_group)

    def _organize_existing_layers(self):
        """Move existing layers into the canonical SAR Tracker groups."""
        root = self.project.layerTreeRoot()
        if not root:
            return

        for layer_name, group_path in LAYER_GROUP_PATHS.items():
            layers = self.project.mapLayersByName(layer_name)
            if not layers:
                continue

            for layer in layers:
                if not self._layer_matches_fields(layer, layer_name):
                    continue

                self._move_layer_to_group(layer, group_path)

                layer_id = LAYER_NAME_TO_ID.get(layer_name)
                if layer_id:
                    layer.setCustomProperty('sartracker:layer_id', layer_id)

    def _move_layer_to_group(self, layer: QgsVectorLayer, group_path: List[str], position: int = 0):
        """Move an existing layer into the specified group path."""
        try:
            target_group = self.ensure_group(group_path, position=position)
        except Exception as e:
            print(f"[LayerManager] Warning: Failed to ensure group for path {group_path}: {e}")
            return

        root = self.project.layerTreeRoot()
        if not root:
            return

        layer_node = root.findLayer(layer.id())
        if layer_node:
            current_parent = layer_node.parent()
            if current_parent == target_group:
                return
            if current_parent:
                current_parent.removeChildNode(layer_node)
            target_group.insertChildNode(position, layer_node)
        else:
            # Layer not in tree yet
            self.project.addMapLayer(layer, False)
            target_group.insertLayer(position, layer)

    def _layer_matches_fields(self, layer: QgsVectorLayer, layer_name: str) -> bool:
        """Check whether a layer matches expected field structure."""
        required_fields = LAYER_FIELD_CHECKS.get(layer_name)
        if not required_fields:
            return True

        existing = {field.name() for field in layer.fields()}
        return all(field in existing for field in required_fields)

    def _collect_layer_definitions(self) -> List[LayerDefinition]:
        """Return a flat list of all layer definitions in the schema."""
        structure = get_expected_structure()
        collected: List[LayerDefinition] = []

        def _walk(group: GroupDefinition):
            if group.layers:
                collected.extend(group.layers)
            if group.subgroups:
                for subgroup in group.subgroups:
                    _walk(subgroup)

        _walk(structure)
        return collected
