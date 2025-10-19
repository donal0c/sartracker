# -*- coding: utf-8 -*-
"""
Marker Layer Manager

Manages SAR marker point layers: IPP/LKP, Clues, and Hazards.
Each marker type has its own layer with appropriate fields and styling.

Qt5/Qt6 Compatible: Uses qgis.PyQt for all imports.
"""

from datetime import datetime
import uuid

from qgis.core import (
    QgsVectorLayer, QgsField, QgsFeature, QgsGeometry,
    QgsPointXY, QgsMarkerSymbol, QgsPalLayerSettings,
    QgsVectorLayerSimpleLabeling, QgsTextFormat, QgsTextBufferSettings
)
from qgis.PyQt.QtCore import QVariant
from qgis.PyQt.QtGui import QColor

from .base_manager import BaseLayerManager


class MarkerLayerManager(BaseLayerManager):
    """
    Manages marker layers for SAR operations.

    Handles three distinct marker types:
    - IPP/LKP: Initial Planning Point / Last Known Position
    - Clues: Evidence found during search
    - Hazards: Safety-critical warnings

    Each type has its own layer with specific fields and styling.
    """

    # Layer names
    IPP_LKP_LAYER_NAME = "IPP/LKP"
    CLUES_LAYER_NAME = "Clues"
    HAZARDS_LAYER_NAME = "Hazards"

    def __init__(self, iface, shared_device_colors=None):
        """Initialize marker layer manager."""
        super().__init__(iface, shared_device_colors)

    def get_managed_layer_names(self):
        """Return list of layer names this manager handles."""
        return [
            self.IPP_LKP_LAYER_NAME,
            self.CLUES_LAYER_NAME,
            self.HAZARDS_LAYER_NAME
        ]

    # =========================================================================
    # IPP/LKP Layer (Initial Planning Point / Last Known Position)
    # =========================================================================

    def _get_or_create_ipp_lkp_layer(self) -> QgsVectorLayer:
        """
        Get or create IPP/LKP layer.

        IPP (Initial Planning Point) or LKP (Last Known Position) is the
        starting point for search planning - where the subject was last
        reliably seen or located.

        Returns:
            QgsVectorLayer: IPP/LKP layer
        """
        # Check if layer already exists
        layers = self.project.mapLayersByName(self.IPP_LKP_LAYER_NAME)
        if layers:
            return layers[0]

        # Create new memory layer with WGS84 CRS
        # Qt5/Qt6 Compatible: Using QVariant types
        layer = QgsVectorLayer(
            "Point?crs=EPSG:4326",
            self.IPP_LKP_LAYER_NAME,
            "memory"
        )

        # Add fields
        layer.dataProvider().addAttributes([
            QgsField("id", QVariant.String),                # String - UUID
            QgsField("name", QVariant.String),              # String - marker name
            QgsField("subject_category", QVariant.String),  # String - subject type (Child, Hiker, etc.)
            QgsField("description", QVariant.String),       # String - additional notes
            QgsField("lat", QVariant.Double),               # Double - WGS84 latitude
            QgsField("lon", QVariant.Double),               # Double - WGS84 longitude
            QgsField("irish_grid_e", QVariant.Double),      # Double - ITM easting
            QgsField("irish_grid_n", QVariant.Double),      # Double - ITM northing
            QgsField("created", QVariant.String),           # String - ISO timestamp
        ])
        layer.updateFields()

        # Apply styling - Blue star/target symbol
        symbol = QgsMarkerSymbol.createSimple({
            'name': 'star',
            'color': '#0066FF',  # Blue
            'size': '7',
            'outline_color': 'black',
            'outline_width': '0.5'
        })
        layer.renderer().setSymbol(symbol)

        # Apply labels
        self._apply_marker_labels(layer, QColor('#0066FF'))

        # Add to project in SAR group (position 0 - on top)
        self._add_layer_to_group(layer, position=0)

        return layer

    def add_ipp_lkp(self, name: str, lat: float, lon: float,
                    subject_category: str = "", description: str = "",
                    irish_grid_e: float = None, irish_grid_n: float = None) -> str:
        """
        Add an IPP/LKP marker to the map.

        Args:
            name: Marker name/identifier
            lat: Latitude (WGS84 decimal degrees)
            lon: Longitude (WGS84 decimal degrees)
            subject_category: Subject type (e.g., "Child (1-3 years)", "Hiker", "Elderly")
            description: Additional notes
            irish_grid_e: Irish Grid (ITM) Easting (optional)
            irish_grid_n: Irish Grid (ITM) Northing (optional)

        Returns:
            str: UUID of added marker
        """
        # Validate name (required)
        if not name or not name.strip():
            raise ValueError("Marker name cannot be empty")

        # Validate coordinates
        if not (-90 <= lat <= 90):
            raise ValueError(f"Invalid latitude: {lat}. Must be between -90 and 90")

        if not (-180 <= lon <= 180):
            raise ValueError(f"Invalid longitude: {lon}. Must be between -180 and 180")

        # Validate optional Irish Grid coordinates if provided
        if irish_grid_e is not None:
            if not (0 <= irish_grid_e <= 1000000):
                raise ValueError(f"Invalid Irish Grid easting: {irish_grid_e}. Must be between 0 and 1,000,000")

        if irish_grid_n is not None:
            if not (0 <= irish_grid_n <= 1500000):
                raise ValueError(f"Invalid Irish Grid northing: {irish_grid_n}. Must be between 0 and 1,500,000")

        layer = self._get_or_create_ipp_lkp_layer()

        # Create feature
        feature = QgsFeature(layer.fields())
        feature.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(lon, lat)))

        # Generate UUID
        marker_id = str(uuid.uuid4())

        # Set attributes
        feature.setAttributes([
            marker_id,
            name,
            subject_category,
            description,
            lat,
            lon,
            irish_grid_e,
            irish_grid_n,
            datetime.now().isoformat()
        ])

        # Add to layer with error handling
        try:
            layer.startEditing()

            if not layer.addFeature(feature):
                layer.rollBack()
                raise RuntimeError(f"Failed to add feature to {self.IPP_LKP_LAYER_NAME} layer")

            if not layer.commitChanges():
                errors = layer.commitErrors()
                raise RuntimeError(f"Failed to commit changes to {self.IPP_LKP_LAYER_NAME} layer: {', '.join(errors)}")

            # Force immediate visual update
            layer.triggerRepaint()

            return marker_id

        except Exception as e:
            # Ensure layer is not left in editing state
            if layer.isEditable():
                layer.rollBack()
            raise RuntimeError(f"Error adding {self.IPP_LKP_LAYER_NAME} marker '{name}': {str(e)}")

    # =========================================================================
    # Clues Layer (Evidence found during search)
    # =========================================================================

    def _get_or_create_clues_layer(self) -> QgsVectorLayer:
        """
        Get or create Clues layer.

        Clues are evidence or signs found during search operations:
        footprints, clothing, equipment, witness sightings, etc.

        Returns:
            QgsVectorLayer: Clues layer
        """
        # Check if layer already exists
        layers = self.project.mapLayersByName(self.CLUES_LAYER_NAME)
        if layers:
            return layers[0]

        # Create new memory layer with WGS84 CRS
        # Qt5/Qt6 Compatible: Using integer type codes (10=String, 2=Int, 6=Double)
        layer = QgsVectorLayer(
            "Point?crs=EPSG:4326",
            self.CLUES_LAYER_NAME,
            "memory"
        )

        # Add fields
        layer.dataProvider().addAttributes([
            QgsField("id", QVariant.String),           # String - UUID
            QgsField("name", QVariant.String),         # String - clue name
            QgsField("clue_type", QVariant.String),    # String - Footprint, Clothing, Witness Sighting, etc.
            QgsField("confidence", QVariant.String),   # String - Confirmed, Probable, Possible
            QgsField("description", QVariant.String),  # String - additional notes
            QgsField("lat", QVariant.Double),          # Double - WGS84 latitude
            QgsField("lon", QVariant.Double),          # Double - WGS84 longitude
            QgsField("irish_grid_e", QVariant.Double), # Double - ITM easting
            QgsField("irish_grid_n", QVariant.Double), # Double - ITM northing
            QgsField("created", QVariant.String),      # String - ISO timestamp
        ])
        layer.updateFields()

        # Apply styling - Yellow triangle/flag symbol
        symbol = QgsMarkerSymbol.createSimple({
            'name': 'triangle',
            'color': '#FFD700',  # Gold/Yellow
            'size': '6',
            'outline_color': 'black',
            'outline_width': '0.5'
        })
        layer.renderer().setSymbol(symbol)

        # Apply labels
        self._apply_marker_labels(layer, QColor('#806600'))  # Dark yellow-brown for contrast

        # Add to project in SAR group (position 1)
        self._add_layer_to_group(layer, position=1)

        return layer

    def add_clue(self, name: str, lat: float, lon: float,
                 clue_type: str = "", confidence: str = "Possible",
                 description: str = "",
                 irish_grid_e: float = None, irish_grid_n: float = None) -> str:
        """
        Add a clue marker to the map.

        Args:
            name: Clue name/identifier
            lat: Latitude (WGS84 decimal degrees)
            lon: Longitude (WGS84 decimal degrees)
            clue_type: Type (Footprint, Clothing, Equipment, Witness Sighting, etc.)
            confidence: Confidence level (Confirmed, Probable, Possible)
            description: Additional notes
            irish_grid_e: Irish Grid (ITM) Easting (optional)
            irish_grid_n: Irish Grid (ITM) Northing (optional)

        Returns:
            str: UUID of added clue
        """
        # Validate name (required)
        if not name or not name.strip():
            raise ValueError("Marker name cannot be empty")

        # Validate coordinates
        if not (-90 <= lat <= 90):
            raise ValueError(f"Invalid latitude: {lat}. Must be between -90 and 90")

        if not (-180 <= lon <= 180):
            raise ValueError(f"Invalid longitude: {lon}. Must be between -180 and 180")

        # Validate optional Irish Grid coordinates if provided
        if irish_grid_e is not None:
            if not (0 <= irish_grid_e <= 1000000):
                raise ValueError(f"Invalid Irish Grid easting: {irish_grid_e}. Must be between 0 and 1,000,000")

        if irish_grid_n is not None:
            if not (0 <= irish_grid_n <= 1500000):
                raise ValueError(f"Invalid Irish Grid northing: {irish_grid_n}. Must be between 0 and 1,500,000")

        layer = self._get_or_create_clues_layer()

        # Create feature
        feature = QgsFeature(layer.fields())
        feature.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(lon, lat)))

        # Generate UUID
        marker_id = str(uuid.uuid4())

        # Set attributes
        feature.setAttributes([
            marker_id,
            name,
            clue_type,
            confidence,
            description,
            lat,
            lon,
            irish_grid_e,
            irish_grid_n,
            datetime.now().isoformat()
        ])

        # Add to layer with error handling
        try:
            layer.startEditing()

            if not layer.addFeature(feature):
                layer.rollBack()
                raise RuntimeError(f"Failed to add feature to {self.CLUES_LAYER_NAME} layer")

            if not layer.commitChanges():
                errors = layer.commitErrors()
                raise RuntimeError(f"Failed to commit changes to {self.CLUES_LAYER_NAME} layer: {', '.join(errors)}")

            # Force immediate visual update
            layer.triggerRepaint()

            return marker_id

        except Exception as e:
            # Ensure layer is not left in editing state
            if layer.isEditable():
                layer.rollBack()
            raise RuntimeError(f"Error adding {self.CLUES_LAYER_NAME} marker '{name}': {str(e)}")

    # =========================================================================
    # Hazards Layer (Safety warnings)
    # =========================================================================

    def _get_or_create_hazards_layer(self) -> QgsVectorLayer:
        """
        Get or create Hazards layer.

        Hazards are safety-critical warnings for search teams:
        cliffs, water hazards, bogs, dense vegetation, etc.

        Returns:
            QgsVectorLayer: Hazards layer
        """
        # Check if layer already exists
        layers = self.project.mapLayersByName(self.HAZARDS_LAYER_NAME)
        if layers:
            return layers[0]

        # Create new memory layer with WGS84 CRS
        # Qt5/Qt6 Compatible: Using integer type codes (10=String, 2=Int, 6=Double)
        layer = QgsVectorLayer(
            "Point?crs=EPSG:4326",
            self.HAZARDS_LAYER_NAME,
            "memory"
        )

        # Add fields
        layer.dataProvider().addAttributes([
            QgsField("id", QVariant.String),            # String - UUID
            QgsField("name", QVariant.String),          # String - hazard name
            QgsField("hazard_type", QVariant.String),   # String - Cliff, Water, Bog, etc.
            QgsField("severity", QVariant.String),      # String - Critical, High, Medium, Low
            QgsField("description", QVariant.String),   # String - additional notes
            QgsField("lat", QVariant.Double),           # Double - WGS84 latitude
            QgsField("lon", QVariant.Double),           # Double - WGS84 longitude
            QgsField("irish_grid_e", QVariant.Double),  # Double - ITM easting
            QgsField("irish_grid_n", QVariant.Double),  # Double - ITM northing
            QgsField("created", QVariant.String),       # String - ISO timestamp
        ])
        layer.updateFields()

        # Apply styling - Red warning symbol
        symbol = QgsMarkerSymbol.createSimple({
            'name': 'filled_arrowhead',  # Warning/exclamation-like symbol
            'color': '#FF0000',  # Red
            'size': '7',
            'outline_color': 'black',
            'outline_width': '0.5',
            'angle': '180'  # Point upward
        })
        layer.renderer().setSymbol(symbol)

        # Apply labels
        self._apply_marker_labels(layer, QColor('#8B0000'))  # Dark red for labels

        # Add to project in SAR group (position 2)
        self._add_layer_to_group(layer, position=2)

        return layer

    def add_hazard(self, name: str, lat: float, lon: float,
                   hazard_type: str = "", severity: str = "Medium",
                   description: str = "",
                   irish_grid_e: float = None, irish_grid_n: float = None) -> str:
        """
        Add a hazard marker to the map.

        Args:
            name: Hazard name/identifier
            lat: Latitude (WGS84 decimal degrees)
            lon: Longitude (WGS84 decimal degrees)
            hazard_type: Type (Cliff/Drop-off, Water Hazard, Bog, etc.)
            severity: Severity level (Critical, High, Medium, Low)
            description: Additional notes
            irish_grid_e: Irish Grid (ITM) Easting (optional)
            irish_grid_n: Irish Grid (ITM) Northing (optional)

        Returns:
            str: UUID of added hazard
        """
        # Validate name (required)
        if not name or not name.strip():
            raise ValueError("Marker name cannot be empty")

        # Validate coordinates
        if not (-90 <= lat <= 90):
            raise ValueError(f"Invalid latitude: {lat}. Must be between -90 and 90")

        if not (-180 <= lon <= 180):
            raise ValueError(f"Invalid longitude: {lon}. Must be between -180 and 180")

        # Validate optional Irish Grid coordinates if provided
        if irish_grid_e is not None:
            if not (0 <= irish_grid_e <= 1000000):
                raise ValueError(f"Invalid Irish Grid easting: {irish_grid_e}. Must be between 0 and 1,000,000")

        if irish_grid_n is not None:
            if not (0 <= irish_grid_n <= 1500000):
                raise ValueError(f"Invalid Irish Grid northing: {irish_grid_n}. Must be between 0 and 1,500,000")

        layer = self._get_or_create_hazards_layer()

        # Create feature
        feature = QgsFeature(layer.fields())
        feature.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(lon, lat)))

        # Generate UUID
        marker_id = str(uuid.uuid4())

        # Set attributes
        feature.setAttributes([
            marker_id,
            name,
            hazard_type,
            severity,
            description,
            lat,
            lon,
            irish_grid_e,
            irish_grid_n,
            datetime.now().isoformat()
        ])

        # Add to layer with error handling
        try:
            layer.startEditing()

            if not layer.addFeature(feature):
                layer.rollBack()
                raise RuntimeError(f"Failed to add feature to {self.HAZARDS_LAYER_NAME} layer")

            if not layer.commitChanges():
                errors = layer.commitErrors()
                raise RuntimeError(f"Failed to commit changes to {self.HAZARDS_LAYER_NAME} layer: {', '.join(errors)}")

            # Force immediate visual update
            layer.triggerRepaint()

            return marker_id

        except Exception as e:
            # Ensure layer is not left in editing state
            if layer.isEditable():
                layer.rollBack()
            raise RuntimeError(f"Error adding {self.HAZARDS_LAYER_NAME} marker '{name}': {str(e)}")

    # =========================================================================
    # Common Helper Methods
    # =========================================================================

    def _apply_marker_labels(self, layer: QgsVectorLayer, text_color: QColor):
        """
        Apply labeling to a marker layer.

        Args:
            layer: Layer to apply labels to
            text_color: Color for label text
        """
        label_settings = QgsPalLayerSettings()
        label_settings.fieldName = 'name'
        label_settings.enabled = True

        # Handle QGIS version differences in placement enum
        # Qt5/Qt6 Compatible: Try new style first, fallback to old
        try:
            # QGIS 3.26+ uses Placement enum
            label_settings.placement = QgsPalLayerSettings.Placement.OverPoint
        except AttributeError:
            # Older QGIS versions
            label_settings.placement = QgsPalLayerSettings.OverPoint

        # Text format
        text_format = QgsTextFormat()
        text_format.setSize(10)
        text_format.setColor(text_color)

        # Text buffer (white halo for readability)
        buffer = QgsTextBufferSettings()
        buffer.setEnabled(True)
        buffer.setColor(QColor('white'))
        buffer.setSize(1)
        text_format.setBuffer(buffer)

        label_settings.setFormat(text_format)

        # Apply labeling to layer
        labeling = QgsVectorLayerSimpleLabeling(label_settings)
        layer.setLabeling(labeling)
        layer.setLabelsEnabled(True)
