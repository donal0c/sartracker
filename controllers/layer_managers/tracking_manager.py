# -*- coding: utf-8 -*-
"""
Tracking Layer Manager

Manages real-time tracking layers: current positions and breadcrumb trails.
Handles device position updates from tracking sources (e.g., Traccar).

Qt5/Qt6 Compatible: Uses qgis.PyQt for all imports.
"""

from typing import List, Dict, Optional, Any
from datetime import datetime
from collections import defaultdict

from qgis.core import (
    QgsVectorLayer, QgsField, QgsFeature, QgsGeometry,
    QgsPointXY, QgsCategorizedSymbolRenderer, QgsRendererCategory,
    QgsMarkerSymbol, QgsLineSymbol, QgsPalLayerSettings,
    QgsVectorLayerSimpleLabeling, QgsTextFormat, QgsTextBufferSettings
)
from qgis.PyQt.QtGui import QColor

from .base_manager import BaseLayerManager


class TrackingLayerManager(BaseLayerManager):
    """
    Manages tracking layers for live device positions and breadcrumb trails.

    Handles:
    - Current Positions: Latest position for each tracked device
    - Breadcrumbs: Historical trail showing device movement

    Features:
    - Categorized styling by device (consistent colors)
    - Automatic trail segmentation on time gaps
    - Efficient layer clearing for live updates
    """

    # Layer names
    CURRENT_LAYER_NAME = "Current Positions"
    BREADCRUMBS_LAYER_NAME = "Breadcrumbs"

    def __init__(self, iface, shared_device_colors=None):
        """Initialize tracking layer manager."""
        super().__init__(iface, shared_device_colors)
        self.first_load = True  # Track if this is first data load for auto-zoom

    def get_managed_layer_names(self):
        """Return list of layer names this manager handles."""
        return [self.CURRENT_LAYER_NAME, self.BREADCRUMBS_LAYER_NAME]

    def reset_state(self):
        """Reset manager state (called after clearing layers)."""
        super().reset_state()
        self.first_load = True  # Reset auto-zoom flag

    # =========================================================================
    # Current Positions Layer
    # =========================================================================

    def _get_or_create_current_layer(self) -> QgsVectorLayer:
        """
        Get or create current positions layer.

        Returns:
            QgsVectorLayer: Current positions layer
        """
        # Check if exists
        layers = self.project.mapLayersByName(self.CURRENT_LAYER_NAME)
        if layers:
            return layers[0]

        # Create new memory layer with WGS84 CRS
        # Qt5/Qt6 Compatible: Using integer type codes (10=String, 2=Int, 6=Double)
        layer = QgsVectorLayer(
            "Point?crs=EPSG:4326",
            self.CURRENT_LAYER_NAME,
            "memory"
        )

        # Add fields
        provider = layer.dataProvider()
        provider.addAttributes([
            QgsField("device_id", 10),  # String
            QgsField("name", 10),       # String
            QgsField("timestamp", 10),  # String
            QgsField("altitude", 6),    # Double
            QgsField("speed", 6),       # Double
            QgsField("battery", 6)      # Double
        ])
        layer.updateFields()

        # Add to project in SAR group (position 2 - below markers)
        self._add_layer_to_group(layer, position=2)

        return layer

    def update_current_positions(self, positions: List[Dict]):
        """
        Update current positions layer.

        Clears existing features and adds new position for each device.
        Uses efficient truncate() method for clearing when available.

        Args:
            positions: List of position dicts from tracking provider
                Expected keys: device_id, name, ts, lat, lon,
                              altitude (optional), speed (optional), battery (optional)

        Raises:
            ValueError: If position data is invalid
        """
        # Validate positions list
        if not isinstance(positions, list):
            raise ValueError("positions must be a list")

        # Validate each position dict
        for i, pos in enumerate(positions):
            if not isinstance(pos, dict):
                raise ValueError(f"Position {i} must be a dictionary")

            # Validate required fields
            required_fields = ['device_id', 'name', 'ts', 'lat', 'lon']
            missing_fields = [field for field in required_fields if field not in pos]
            if missing_fields:
                raise ValueError(f"Position {i} missing required fields: {missing_fields}")

            # Validate coordinates
            try:
                lat = float(pos['lat'])
                lon = float(pos['lon'])
            except (TypeError, ValueError) as e:
                raise ValueError(f"Position {i} has invalid lat/lon: {e}")

            if not (-90 <= lat <= 90):
                raise ValueError(f"Position {i} has invalid latitude: {lat} (must be -90 to 90)")

            if not (-180 <= lon <= 180):
                raise ValueError(f"Position {i} has invalid longitude: {lon} (must be -180 to 180)")

            # Validate device_id and name are non-empty strings
            if not pos['device_id'] or not isinstance(pos['device_id'], str):
                raise ValueError(f"Position {i} has invalid device_id (must be non-empty string)")

            if not pos['name'] or not isinstance(pos['name'], str):
                raise ValueError(f"Position {i} has invalid name (must be non-empty string)")

        # Get or create layer
        layer = self._get_or_create_current_layer()

        # Clear existing features efficiently
        layer.startEditing()

        # Use dataProvider().truncate() for better performance with many features
        # This is faster than iterating through all features to delete them
        if layer.featureCount() > 0:
            try:
                # Truncate is faster for clearing all features
                layer.dataProvider().truncate()
            except (AttributeError, NotImplementedError, RuntimeError) as e:
                # Fallback to deleteFeatures if truncate not supported
                # Use allFeatureIds() to avoid loading feature objects into memory
                print(f"Truncate not available for {self.CURRENT_LAYER_NAME}, using deleteFeatures: {e}")
                layer.deleteFeatures(layer.allFeatureIds())

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

    def _apply_current_positions_style(self, layer: QgsVectorLayer):
        """
        Apply categorized style to current positions.

        Each device gets a unique color for easy identification.

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
        # Qt5/Qt6 Compatible
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

    # =========================================================================
    # Breadcrumbs Layer
    # =========================================================================

    def _get_or_create_breadcrumbs_layer(self) -> QgsVectorLayer:
        """
        Get or create breadcrumbs layer.

        Returns:
            QgsVectorLayer: Breadcrumbs layer
        """
        layers = self.project.mapLayersByName(self.BREADCRUMBS_LAYER_NAME)
        if layers:
            return layers[0]

        # Create new memory layer with WGS84 CRS
        # Qt5/Qt6 Compatible: Using integer type codes
        layer = QgsVectorLayer(
            "LineString?crs=EPSG:4326",
            self.BREADCRUMBS_LAYER_NAME,
            "memory"
        )

        provider = layer.dataProvider()
        provider.addAttributes([
            QgsField("device_id", 10),  # String
            QgsField("name", 10)        # String
        ])
        layer.updateFields()

        # Add to project in SAR group (position 3 - below current positions)
        self._add_layer_to_group(layer, position=3)

        return layer

    def update_breadcrumbs(self, positions: List[Dict], time_gap_minutes: int = 5):
        """
        Update breadcrumb trails layer.

        Creates line segments showing device movement history.
        Automatically breaks trails on time gaps (e.g., when device was off).

        Args:
            positions: List of position dicts from tracking provider
            time_gap_minutes: Minutes gap to break trail into segments (default: 5)

        Raises:
            ValueError: If position data is invalid
        """
        # Validate positions list
        if not isinstance(positions, list):
            raise ValueError("positions must be a list")

        # Validate each position dict (same validation as update_current_positions)
        for i, pos in enumerate(positions):
            if not isinstance(pos, dict):
                raise ValueError(f"Position {i} must be a dictionary")

            # Validate required fields
            required_fields = ['device_id', 'name', 'ts', 'lat', 'lon']
            missing_fields = [field for field in required_fields if field not in pos]
            if missing_fields:
                raise ValueError(f"Position {i} missing required fields: {missing_fields}")

            # Validate coordinates
            try:
                lat = float(pos['lat'])
                lon = float(pos['lon'])
            except (TypeError, ValueError) as e:
                raise ValueError(f"Position {i} has invalid lat/lon: {e}")

            if not (-90 <= lat <= 90):
                raise ValueError(f"Position {i} has invalid latitude: {lat} (must be -90 to 90)")

            if not (-180 <= lon <= 180):
                raise ValueError(f"Position {i} has invalid longitude: {lon} (must be -180 to 180)")

            # Validate device_id and name are non-empty strings
            if not pos['device_id'] or not isinstance(pos['device_id'], str):
                raise ValueError(f"Position {i} has invalid device_id (must be non-empty string)")

            if not pos['name'] or not isinstance(pos['name'], str):
                raise ValueError(f"Position {i} has invalid name (must be non-empty string)")

        # Validate time_gap_minutes
        if not isinstance(time_gap_minutes, (int, float)) or time_gap_minutes <= 0:
            raise ValueError(f"time_gap_minutes must be a positive number, got: {time_gap_minutes}")

        # Get or create layer
        layer = self._get_or_create_breadcrumbs_layer()

        # Clear existing features efficiently
        layer.startEditing()

        # Use dataProvider().truncate() for better performance
        if layer.featureCount() > 0:
            try:
                # Truncate is faster for clearing all features
                layer.dataProvider().truncate()
            except (AttributeError, NotImplementedError, RuntimeError) as e:
                # Fallback to deleteFeatures if truncate not supported
                # Use allFeatureIds() to avoid loading feature objects into memory
                print(f"Truncate not available for {self.BREADCRUMBS_LAYER_NAME}, using deleteFeatures: {e}")
                layer.deleteFeatures(layer.allFeatureIds())

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
                    try:
                        # Parse timestamps with fallback for various formats
                        # This handles both ISO format and 'Z' suffix (UTC indicator)
                        prev_ts = device_pts[i-1]['ts']
                        curr_ts = pos['ts']

                        # Handle 'Z' suffix (UTC indicator)
                        if prev_ts.endswith('Z'):
                            prev_ts = prev_ts[:-1] + '+00:00'
                        if curr_ts.endswith('Z'):
                            curr_ts = curr_ts[:-1] + '+00:00'

                        prev_time = datetime.fromisoformat(prev_ts)
                        curr_time = datetime.fromisoformat(curr_ts)
                        time_diff = (curr_time - prev_time).total_seconds() / 60
                    except (ValueError, AttributeError, TypeError) as e:
                        # If timestamp parsing fails, assume no gap and continue segment
                        # This prevents crashes on malformed timestamps
                        # Warn user via message bar (visible in QGIS UI)
                        self.iface.messageBar().pushWarning(
                            "Timestamp Parsing",
                            f"Could not parse timestamp for device {device_id}: {e}. Treating as continuous segment."
                        )
                        time_diff = 0

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

    def _apply_breadcrumbs_style(self, layer: QgsVectorLayer):
        """
        Apply categorized style to breadcrumbs.

        Each device gets matching color to its position marker.

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
