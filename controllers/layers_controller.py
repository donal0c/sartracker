# -*- coding: utf-8 -*-
"""
Layers Controller

Manages QGIS map layers for SAR tracking visualization.
Creates and updates breadcrumb trails and current position layers.
"""

from qgis.core import (
    QgsVectorLayer, QgsProject, QgsFeature, QgsGeometry,
    QgsPointXY, QgsField, QgsCategorizedSymbolRenderer,
    QgsRendererCategory, QgsMarkerSymbol, QgsLineSymbol,
    QgsPalLayerSettings, QgsVectorLayerSimpleLabeling,
    QgsTextFormat, QgsTextBufferSettings
)
from qgis.PyQt.QtGui import QColor
from typing import List, Dict
from collections import defaultdict
from datetime import datetime, timedelta
import random


class LayersController:
    """
    Controller for managing SAR tracking layers.
    
    Creates and updates:
    - Breadcrumb trails (colored lines per device)
    - Current positions (labeled points per device)
    """

    LAYER_GROUP_NAME = "SAR Tracking"
    CURRENT_LAYER_NAME = "Current Positions"
    BREADCRUMBS_LAYER_NAME = "Breadcrumbs"
    POI_LAYER_NAME = "Points of Interest"
    CASUALTY_LAYER_NAME = "Casualties"

    def __init__(self, iface):
        """
        Initialize layers controller.

        Args:
            iface: QGIS interface object
        """
        self.iface = iface
        self.project = QgsProject.instance()
        self.device_colors = {}  # Cache device colors for consistency
        self.first_load = True  # Track if this is first data load

    def get_or_create_layer_group(self):
        """
        Get or create SAR Tracking layer group.
        
        Returns:
            QgsLayerTreeGroup
        """
        root = self.project.layerTreeRoot()
        group = root.findGroup(self.LAYER_GROUP_NAME)
        if not group:
            group = root.insertGroup(0, self.LAYER_GROUP_NAME)
        return group

    def _get_device_color(self, device_id: str) -> QColor:
        """
        Get consistent color for a device.
        
        Args:
            device_id: Device identifier
            
        Returns:
            QColor for this device
        """
        if device_id not in self.device_colors:
            # Generate a distinct color (avoid very dark colors)
            self.device_colors[device_id] = QColor(
                random.randint(50, 255),
                random.randint(50, 255),
                random.randint(50, 255)
            )
        return self.device_colors[device_id]

    def update_current_positions(self, positions: List[Dict]):
        """
        Update current positions layer.
        
        Args:
            positions: List of position dicts from provider
        """
        # Get or create layer
        layer = self._get_or_create_current_layer()

        # Clear existing features
        layer.startEditing()
        layer.deleteFeatures([f.id() for f in layer.getFeatures()])

        # Add new features
        for pos in positions:
            feature = QgsFeature(layer.fields())
            feature.setGeometry(
                QgsGeometry.fromPointXY(
                    QgsPointXY(pos['lon'], pos['lat'])
                )
            )
            feature.setAttributes([
                pos['device_id'],
                pos['name'],
                pos['ts'],
                pos.get('altitude'),
                pos.get('speed'),
                pos.get('battery')
            ])
            layer.addFeature(feature)

        layer.commitChanges()

        # Apply styling
        self._apply_current_positions_style(layer)

        # Zoom to extent ONLY on first load
        if self.first_load and positions:
            self.iface.mapCanvas().setExtent(layer.extent())
            self.iface.mapCanvas().refresh()
            self.first_load = False
        else:
            # Just repaint the layer, not the whole canvas
            layer.triggerRepaint()

    def _get_or_create_current_layer(self) -> QgsVectorLayer:
        """
        Get or create current positions layer.
        
        Returns:
            QgsVectorLayer
        """
        # Check if exists
        layers = self.project.mapLayersByName(self.CURRENT_LAYER_NAME)
        if layers:
            return layers[0]

        # Create new memory layer
        layer = QgsVectorLayer(
            "Point?crs=EPSG:4326",
            self.CURRENT_LAYER_NAME,
            "memory"
        )

        # Add fields
        provider = layer.dataProvider()
        provider.addAttributes([
            QgsField("device_id", 10),  # String
            QgsField("name", 10),  # String
            QgsField("timestamp", 10),  # String
            QgsField("altitude", 6),  # Double
            QgsField("speed", 6),  # Double
            QgsField("battery", 6)  # Double
        ])
        layer.updateFields()

        # Add to project in SAR group (position 2 - below POIs and Casualties)
        group = self.get_or_create_layer_group()
        self.project.addMapLayer(layer, False)
        group.insertLayer(2, layer)

        return layer

    def _apply_current_positions_style(self, layer: QgsVectorLayer):
        """
        Apply categorized style to current positions.
        
        Args:
            layer: Current positions layer
        """
        # Get unique device IDs
        device_ids = layer.uniqueValues(
            layer.fields().indexOf('device_id')
        )

        # Create categories with consistent colors
        categories = []
        for device_id in device_ids:
            color = self._get_device_color(str(device_id))
            symbol = QgsMarkerSymbol.createSimple({
                'name': 'circle',
                'color': color.name(),
                'size': '5',
                'outline_color': 'black',
                'outline_width': '0.5'
            })
            category = QgsRendererCategory(device_id, symbol, str(device_id))
            categories.append(category)

        renderer = QgsCategorizedSymbolRenderer('device_id', categories)
        layer.setRenderer(renderer)

        # Apply labels
        label_settings = QgsPalLayerSettings()
        label_settings.fieldName = 'name'
        label_settings.enabled = True

        # Handle QGIS version differences in placement enum
        try:
            # QGIS 3.26+ uses Placement enum
            label_settings.placement = QgsPalLayerSettings.Placement.OverPoint
        except AttributeError:
            # Older QGIS versions
            label_settings.placement = QgsPalLayerSettings.OverPoint

        text_format = QgsTextFormat()
        text_format.setSize(10)
        text_format.setColor(QColor('black'))

        # Text buffer (white halo)
        buffer = QgsTextBufferSettings()
        buffer.setEnabled(True)
        buffer.setColor(QColor('white'))
        buffer.setSize(1)
        text_format.setBuffer(buffer)

        label_settings.setFormat(text_format)

        labeling = QgsVectorLayerSimpleLabeling(label_settings)
        layer.setLabeling(labeling)
        layer.setLabelsEnabled(True)

    def update_breadcrumbs(self, positions: List[Dict], time_gap_minutes: int = 5):
        """
        Update breadcrumb trails layer.
        
        Args:
            positions: List of position dicts from provider
            time_gap_minutes: Minutes gap to break trail into segments
        """
        # Get or create layer
        layer = self._get_or_create_breadcrumbs_layer()

        # Clear existing features
        layer.startEditing()
        layer.deleteFeatures([f.id() for f in layer.getFeatures()])

        # Group positions by device_id
        device_positions = defaultdict(list)
        for pos in positions:
            device_positions[pos['device_id']].append(pos)

        # Create line segments per device
        for device_id, device_pts in device_positions.items():
            # Sort by timestamp
            device_pts.sort(key=lambda p: p['ts'])

            # Break into segments on time gaps
            segments = []
            current_segment = []

            for i, pos in enumerate(device_pts):
                if i == 0:
                    current_segment.append(pos)
                else:
                    prev_time = datetime.fromisoformat(
                        device_pts[i-1]['ts'].replace('Z', '+00:00')
                    )
                    curr_time = datetime.fromisoformat(
                        pos['ts'].replace('Z', '+00:00')
                    )
                    time_diff = (curr_time - prev_time).total_seconds() / 60

                    if time_diff > time_gap_minutes:
                        # Save current segment, start new
                        if len(current_segment) > 1:
                            segments.append(current_segment)
                        current_segment = [pos]
                    else:
                        current_segment.append(pos)

            # Add final segment
            if len(current_segment) > 1:
                segments.append(current_segment)

            # Create features for each segment
            device_name = device_pts[0]['name']
            for segment in segments:
                points = [
                    QgsPointXY(p['lon'], p['lat']) for p in segment
                ]
                geom = QgsGeometry.fromPolylineXY(points)

                feature = QgsFeature(layer.fields())
                feature.setGeometry(geom)
                feature.setAttributes([device_id, device_name])
                layer.addFeature(feature)

        layer.commitChanges()

        # Apply styling
        self._apply_breadcrumbs_style(layer)

        # Refresh only this layer
        layer.triggerRepaint()

    def _get_or_create_breadcrumbs_layer(self) -> QgsVectorLayer:
        """
        Get or create breadcrumbs layer.
        
        Returns:
            QgsVectorLayer
        """
        layers = self.project.mapLayersByName(self.BREADCRUMBS_LAYER_NAME)
        if layers:
            return layers[0]

        layer = QgsVectorLayer(
            "LineString?crs=EPSG:4326",
            self.BREADCRUMBS_LAYER_NAME,
            "memory"
        )

        provider = layer.dataProvider()
        provider.addAttributes([
            QgsField("device_id", 10),  # String
            QgsField("name", 10)  # String
        ])
        layer.updateFields()

        group = self.get_or_create_layer_group()
        self.project.addMapLayer(layer, False)
        group.insertLayer(3, layer)

        return layer

    def _apply_breadcrumbs_style(self, layer: QgsVectorLayer):
        """
        Apply categorized style to breadcrumbs.
        
        Args:
            layer: Breadcrumbs layer
        """
        device_ids = layer.uniqueValues(
            layer.fields().indexOf('device_id')
        )

        categories = []
        for device_id in device_ids:
            color = self._get_device_color(str(device_id))
            symbol = QgsLineSymbol.createSimple({
                'color': color.name(),
                'width': '2',
                'line_style': 'solid',
                'joinstyle': 'round',
                'capstyle': 'round'
            })
            category = QgsRendererCategory(device_id, symbol, str(device_id))
            categories.append(category)

        renderer = QgsCategorizedSymbolRenderer('device_id', categories)
        layer.setRenderer(renderer)

    def get_poi_layer(self) -> QgsVectorLayer:
        """
        Get or create POI layer.

        Returns:
            QgsVectorLayer for POIs
        """
        layers = self.project.mapLayersByName(self.POI_LAYER_NAME)
        if layers:
            return layers[0]

        # Create new memory layer
        layer = QgsVectorLayer(
            "Point?crs=EPSG:4326",
            self.POI_LAYER_NAME,
            "memory"
        )

        # Add fields
        provider = layer.dataProvider()
        provider.addAttributes([
            QgsField("id", 2),  # Int
            QgsField("name", 10),  # String
            QgsField("poi_type", 10),  # String
            QgsField("description", 10),  # String
            QgsField("lat", 6),  # Double
            QgsField("lon", 6),  # Double
            QgsField("irish_grid_e", 6),  # Double
            QgsField("irish_grid_n", 6),  # Double
            QgsField("color", 10),  # String
            QgsField("created", 10)  # String
        ])
        layer.updateFields()

        # Add to project in SAR group (position 0 - on top)
        group = self.get_or_create_layer_group()
        self.project.addMapLayer(layer, False)
        group.insertLayer(0, layer)

        return layer

    def get_casualty_layer(self) -> QgsVectorLayer:
        """
        Get or create Casualty layer.

        Returns:
            QgsVectorLayer for casualties
        """
        layers = self.project.mapLayersByName(self.CASUALTY_LAYER_NAME)
        if layers:
            return layers[0]

        # Create new memory layer
        layer = QgsVectorLayer(
            "Point?crs=EPSG:4326",
            self.CASUALTY_LAYER_NAME,
            "memory"
        )

        # Add fields
        provider = layer.dataProvider()
        provider.addAttributes([
            QgsField("id", 2),  # Int
            QgsField("name", 10),  # String
            QgsField("description", 10),  # String
            QgsField("lat", 6),  # Double
            QgsField("lon", 6),  # Double
            QgsField("irish_grid_e", 6),  # Double
            QgsField("irish_grid_n", 6),  # Double
            QgsField("condition", 10),  # String
            QgsField("created", 10)  # String
        ])
        layer.updateFields()

        # Add to project in SAR group (position 1 - second from top)
        group = self.get_or_create_layer_group()
        self.project.addMapLayer(layer, False)
        group.insertLayer(1, layer)

        # Apply red star styling for casualties
        symbol = QgsMarkerSymbol.createSimple({
            'name': 'star',
            'color': 'red',
            'size': '6',
            'outline_color': 'black',
            'outline_width': '0.5'
        })
        layer.renderer().setSymbol(symbol)

        # Add labels
        label_settings = QgsPalLayerSettings()
        label_settings.fieldName = 'name'
        label_settings.enabled = True

        # Handle QGIS version differences
        try:
            label_settings.placement = QgsPalLayerSettings.Placement.OverPoint
        except AttributeError:
            label_settings.placement = QgsPalLayerSettings.OverPoint

        text_format = QgsTextFormat()
        text_format.setSize(10)
        text_format.setColor(QColor('darkred'))

        buffer = QgsTextBufferSettings()
        buffer.setEnabled(True)
        buffer.setColor(QColor('white'))
        buffer.setSize(1)
        text_format.setBuffer(buffer)

        label_settings.setFormat(text_format)

        labeling = QgsVectorLayerSimpleLabeling(label_settings)
        layer.setLabeling(labeling)
        layer.setLabelsEnabled(True)

        return layer

    def add_poi(self, name: str, lat: float, lon: float, poi_type: str = "",
                irish_grid_e: float = None, irish_grid_n: float = None,
                description: str = "", color: str = "#007BFF") -> int:
        """
        Add a POI marker to the map.

        Args:
            name: POI name
            lat: Latitude (WGS84)
            lon: Longitude (WGS84)
            poi_type: Type (base, vehicle, landmark, hazard, etc.)
            irish_grid_e: Easting (ITM)
            irish_grid_n: Northing (ITM)
            description: Additional notes
            color: Hex color for marker

        Returns:
            Feature ID of added POI
        """
        layer = self.get_poi_layer()

        layer.startEditing()

        feature = QgsFeature(layer.fields())
        feature.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(lon, lat)))

        # Get next ID
        max_id = 0
        for f in layer.getFeatures():
            if f['id'] and f['id'] > max_id:
                max_id = f['id']
        next_id = max_id + 1

        feature.setAttributes([
            next_id,
            name,
            poi_type,
            description,
            lat,
            lon,
            irish_grid_e,
            irish_grid_n,
            color,
            datetime.now().isoformat()
        ])

        layer.addFeature(feature)
        layer.commitChanges()
        # Layer will auto-update, no need to force repaint

        return next_id

    def add_casualty(self, name: str, lat: float, lon: float,
                     irish_grid_e: float = None, irish_grid_n: float = None,
                     description: str = "", condition: str = "") -> int:
        """
        Add a casualty marker to the map.

        Args:
            name: Casualty name/identifier
            lat: Latitude (WGS84)
            lon: Longitude (WGS84)
            irish_grid_e: Easting (ITM)
            irish_grid_n: Northing (ITM)
            description: Additional notes
            condition: Medical condition/status

        Returns:
            Feature ID of added casualty
        """
        layer = self.get_casualty_layer()

        layer.startEditing()

        feature = QgsFeature(layer.fields())
        feature.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(lon, lat)))

        # Get next ID
        max_id = 0
        for f in layer.getFeatures():
            if f['id'] and f['id'] > max_id:
                max_id = f['id']
        next_id = max_id + 1

        feature.setAttributes([
            next_id,
            name,
            description,
            lat,
            lon,
            irish_grid_e,
            irish_grid_n,
            condition,
            datetime.now().isoformat()
        ])

        layer.addFeature(feature)
        layer.commitChanges()
        # Layer will auto-update, no need to force repaint

        return next_id

    def clear_layers(self):
        """Remove all SAR tracking layers."""
        group = self.project.layerTreeRoot().findGroup(self.LAYER_GROUP_NAME)
        if group:
            self.project.layerTreeRoot().removeChildNode(group)
        self.device_colors.clear()
