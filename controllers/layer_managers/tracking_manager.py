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
from qgis.PyQt.QtCore import QVariant
from qgis.PyQt.QtGui import QColor

from .base_manager import BaseLayerManager
from ...utils.exceptions import LayerLockError, LayerTransactionError, LayerError


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

    # Layer names / custom property keys
    CURRENT_LAYER_NAME = "Current Positions"
    BREADCRUMBS_LAYER_NAME = "Breadcrumbs"
    BREADCRUMB_STYLE_MANAGED_PROP = "sartracker:breadcrumbs_style_managed"
    BREADCRUMB_STYLE_INITIALIZED_PROP = "sartracker:breadcrumbs_style_initialized"

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
        # Qt5/Qt6 Compatible: Using QVariant types
        layer = QgsVectorLayer(
            "Point?crs=EPSG:4326",
            self.CURRENT_LAYER_NAME,
            "memory"
        )

        # Add fields
        provider = layer.dataProvider()
        provider.addAttributes([
            QgsField("device_id", QVariant.String),  # String
            QgsField("name", QVariant.String),       # String
            QgsField("timestamp", QVariant.String),  # String
            QgsField("altitude", QVariant.Double),   # Double
            QgsField("speed", QVariant.Double),      # Double
            QgsField("battery", QVariant.Double)     # Double
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

        # Check if layer is already being edited (Issue #3 safety check)
        if layer.isEditable():
            raise LayerLockError(self.CURRENT_LAYER_NAME)

        # Layer update with proper transaction handling (Issue #3 fix)
        # This ensures the layer is NEVER left in edit mode, even in edge cases
        try:
            # Start editing
            if not layer.startEditing():
                raise RuntimeError(f"Failed to start editing {self.CURRENT_LAYER_NAME}")

            # Clear existing features efficiently
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
                    if not layer.deleteFeatures(layer.allFeatureIds()):
                        raise RuntimeError(f"Failed to clear features from {self.CURRENT_LAYER_NAME}")

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
                if not layer.addFeature(feature):
                    raise RuntimeError(f"Failed to add feature for device {pos['device_id']}")

            # Commit changes and check for errors
            if not layer.commitChanges():
                # Get commit errors for better error message
                errors = layer.commitErrors()
                raise RuntimeError(
                    f"Failed to commit changes to {self.CURRENT_LAYER_NAME}: "
                    f"{'; '.join(errors) if errors else 'Unknown error'}"
                )

        except Exception as e:
            # Rollback on any error to prevent edit mode lockup (Issue #3)
            layer.rollBack()

            # Raise typed exception for error handler (Issue #3)
            raise LayerTransactionError(
                self.CURRENT_LAYER_NAME,
                "commit changes",
                details=str(e)
            ) from e

        finally:
            # Safety net: Ensure layer is NEVER left in edit mode (Issue #3 critical fix)
            # This handles edge cases where commitChanges() succeeded but we raised exception anyway
            if layer.isEditable():
                layer.rollBack()

        # Apply styling (outside transaction - failures here don't affect data)
        try:
            self._apply_current_positions_style(layer)
        except Exception as e:
            # Log styling errors but don't fail the update (Issue #3)
            # Non-critical: styling failure doesn't affect core functionality
            print(f"Warning: Failed to apply styling to {self.CURRENT_LAYER_NAME}: {str(e)}")

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
        Apply or update categorized style to current positions.

        Updates existing renderer to:
        1. Prevent crashes (replacing renderer deletes C++ objects UI might be using)
        2. Preserve user manual color changes
        3. Only add categories for new devices
        """
        # Get unique device IDs
        try:
            device_ids = layer.uniqueValues(
                layer.fields().indexOf('device_id')
            )
        except Exception:
            return

        # Check if we already have a categorized renderer
        current_renderer = layer.renderer()

        if isinstance(current_renderer, QgsCategorizedSymbolRenderer):
            # UPDATE EXISTING: Safest approach
            existing_categories = current_renderer.categories()
            existing_ids = {cat.value() for cat in existing_categories}

            new_devices = [d for d in device_ids if d not in existing_ids]

            if not new_devices:
                return

            for device_id in new_devices:
                color = self._get_device_color(str(device_id))
                symbol = QgsMarkerSymbol.createSimple({
                    'name': 'circle',
                    'color': color.name(),
                    'size': '5',
                    'outline_color': 'black',
                    'outline_width': '0.5'
                })
                category = QgsRendererCategory(device_id, symbol, str(device_id))
                current_renderer.addCategory(category)

            layer.triggerRepaint()

        else:
            # FIRST LOAD / RESET: Create new renderer
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

            # Apply labels (only apply defaults on first load/reset to respect user changes)
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
            QgsField("device_id", QVariant.String),  # String
            QgsField("name", QVariant.String)        # String
        ])
        layer.updateFields()

        # Add to project in SAR group (position 3 - below current positions)
        self._add_layer_to_group(layer, position=3)

        # Track that SAR Tracker manages the initial style for this layer
        layer.setCustomProperty(self.BREADCRUMB_STYLE_MANAGED_PROP, True)
        layer.setCustomProperty(self.BREADCRUMB_STYLE_INITIALIZED_PROP, False)

        return layer

    def update_breadcrumbs(
        self,
        positions: List[Dict],
        time_gap_minutes: int = 5,
        processed_segments: Optional[Dict[str, Any]] = None
    ):
        """
        Update breadcrumb trails layer.

        Creates line segments showing device movement history.
        Automatically breaks trails on time gaps (e.g., when device was off).

        Args:
            positions: List of position dicts from tracking provider
            time_gap_minutes: Minutes gap to break trail into segments (default: 5)
            processed_segments: Optional pre-processed segment payload produced
                by provider refresh tasks. When provided (and compatible with
                the requested time gap), sorting and segmentation are skipped.

        Raises:
            ValueError: If position data is invalid
        """
        if not isinstance(time_gap_minutes, (int, float)) or time_gap_minutes <= 0:
            raise ValueError(f"time_gap_minutes must be a positive number, got: {time_gap_minutes}")

        gap_minutes = float(time_gap_minutes)
        layer = self._get_or_create_breadcrumbs_layer()

        if layer.isEditable():
            raise LayerLockError(self.BREADCRUMBS_LAYER_NAME)

        segments = self._validate_processed_segments(processed_segments, gap_minutes)
        if segments is None:
            sanitized_positions = self._sanitize_breadcrumb_positions(positions)
            segments = self._build_segments_from_positions(sanitized_positions, gap_minutes)

        self._replace_breadcrumb_layer_features(layer, segments or [])

        try:
            self._apply_breadcrumbs_style(layer)
        except Exception as e:
            print(f"Warning: Failed to apply styling to {self.BREADCRUMBS_LAYER_NAME}: {str(e)}")

        layer.triggerRepaint()

    def _sanitize_breadcrumb_positions(self, positions: List[Dict]) -> List[Dict[str, Any]]:
        """Validate and normalize raw breadcrumb payloads."""
        if positions is None:
            return []

        if not isinstance(positions, list):
            raise ValueError("positions must be a list")

        sanitized = []
        for i, pos in enumerate(positions):
            if not isinstance(pos, dict):
                raise ValueError(f"Position {i} must be a dictionary")

            required_fields = ['device_id', 'name', 'ts', 'lat', 'lon']
            missing_fields = [field for field in required_fields if field not in pos]
            if missing_fields:
                raise ValueError(f"Position {i} missing required fields: {missing_fields}")

            try:
                lat = float(pos['lat'])
                lon = float(pos['lon'])
            except (TypeError, ValueError) as e:
                raise ValueError(f"Position {i} has invalid lat/lon: {e}")

            if not (-90 <= lat <= 90):
                raise ValueError(f"Position {i} has invalid latitude: {lat} (must be -90 to 90)")

            if not (-180 <= lon <= 180):
                raise ValueError(f"Position {i} has invalid longitude: {lon} (must be -180 to 180)")

            device_id = pos['device_id']
            name = pos['name']

            if not device_id or not isinstance(device_id, str):
                raise ValueError(f"Position {i} has invalid device_id (must be non-empty string)")

            if not name or not isinstance(name, str):
                raise ValueError(f"Position {i} has invalid name (must be non-empty string)")

            ts = pos['ts']
            if not isinstance(ts, str):
                raise ValueError(f"Position {i} has invalid timestamp (must be string)")

            sanitized.append({
                'device_id': device_id,
                'name': name,
                'ts': ts,
                'lat': lat,
                'lon': lon
            })

        return sanitized

    def _build_segments_from_positions(self, positions: List[Dict[str, Any]], time_gap_minutes: float) -> List[Dict[str, Any]]:
        """Reproduce legacy segmentation logic for fallback scenarios."""
        device_positions = defaultdict(list)
        for pos in positions:
            device_positions[pos['device_id']].append(pos)

        segments = []

        for device_id, device_pts in device_positions.items():
            device_pts.sort(key=lambda p: p['ts'])
            if not device_pts:
                continue

            current_segment = [device_pts[0]]

            for idx in range(1, len(device_pts)):
                pos = device_pts[idx]
                prev_pos = device_pts[idx - 1]

                try:
                    prev_time = self._parse_iso_timestamp(prev_pos['ts'])
                    curr_time = self._parse_iso_timestamp(pos['ts'])
                    gap_minutes = (curr_time - prev_time).total_seconds() / 60.0
                except Exception as e:
                    print(f"Warning: Could not parse timestamp for device {device_id}: {e}. Treating as continuous segment.")
                    gap_minutes = 0

                if gap_minutes > time_gap_minutes:
                    if len(current_segment) > 1:
                        segments.append(self._segment_from_points(device_id, current_segment[0]['name'], current_segment))
                    current_segment = [pos]
                else:
                    current_segment.append(pos)

            if len(current_segment) > 1:
                segments.append(self._segment_from_points(device_id, current_segment[0]['name'], current_segment))

        return segments

    def _segment_from_points(self, device_id: str, device_name: str, points: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Convert a list of sanitized points into a standardized segment payload."""
        return {
            'device_id': device_id,
            'name': device_name,
            'points': [
                {
                    'lon': point['lon'],
                    'lat': point['lat'],
                    'ts': point.get('ts')
                }
                for point in points
            ]
        }

    def _validate_processed_segments(
        self,
        processed_payload: Optional[Dict[str, Any]],
        requested_gap_minutes: float
    ) -> Optional[List[Dict[str, Any]]]:
        """
        Validate provider-supplied pre-processed segments.

        Returns:
            List of safe segment payloads, an empty list (meaning no features),
            or None if payload is unusable and we must fallback to raw data.
        """
        if not processed_payload:
            return None

        if isinstance(processed_payload, dict):
            segments = processed_payload.get('segments')
            payload_gap = processed_payload.get('time_gap_minutes', requested_gap_minutes)
        else:
            segments = processed_payload
            payload_gap = requested_gap_minutes

        try:
            gap_value = float(payload_gap)
        except (TypeError, ValueError):
            gap_value = requested_gap_minutes

        if gap_value <= 0 or abs(gap_value - requested_gap_minutes) > 0.001:
            return None

        if segments is None or not isinstance(segments, list):
            return None

        validated = []
        for segment in segments:
            if not isinstance(segment, dict):
                continue

            device_id = segment.get('device_id')
            name = segment.get('name') or device_id
            points = segment.get('points')

            if not device_id or not isinstance(device_id, str):
                continue
            if not name or not isinstance(name, str):
                name = device_id
            if not isinstance(points, list) or len(points) < 2:
                continue

            processed_points = []
            valid_segment = True
            for point in points:
                if not isinstance(point, dict):
                    valid_segment = False
                    break
                try:
                    lat = float(point.get('lat'))
                    lon = float(point.get('lon'))
                except (TypeError, ValueError):
                    valid_segment = False
                    break

                if not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
                    valid_segment = False
                    break

                processed_points.append({
                    'lat': lat,
                    'lon': lon,
                    'ts': point.get('ts')
                })

            if valid_segment and len(processed_points) >= 2:
                validated.append({
                    'device_id': device_id,
                    'name': name,
                    'points': processed_points
                })

        return validated if validated else []

    def _replace_breadcrumb_layer_features(self, layer: QgsVectorLayer, segments: List[Dict[str, Any]]):
        """
        Replace layer features with provided segments using safe transactions.
        """
        segments = segments or []

        try:
            if not layer.startEditing():
                raise RuntimeError(f"Failed to start editing {self.BREADCRUMBS_LAYER_NAME}")

            if layer.featureCount() > 0:
                try:
                    layer.dataProvider().truncate()
                except (AttributeError, NotImplementedError, RuntimeError) as e:
                    print(f"Truncate not available for {self.BREADCRUMBS_LAYER_NAME}, using deleteFeatures: {e}")
                    if not layer.deleteFeatures(layer.allFeatureIds()):
                        raise RuntimeError(f"Failed to clear features from {self.BREADCRUMBS_LAYER_NAME}")

            for segment in segments:
                qgs_points = []
                for point in segment.get('points', []):
                    try:
                        lon = float(point.get('lon'))
                        lat = float(point.get('lat'))
                    except (TypeError, ValueError):
                        qgs_points = []
                        break

                    if not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
                        qgs_points = []
                        break

                    qgs_points.append(QgsPointXY(lon, lat))

                if len(qgs_points) < 2:
                    continue

                geom = QgsGeometry.fromPolylineXY(qgs_points)
                feature = QgsFeature(layer.fields())
                feature.setGeometry(geom)
                device_id = segment.get('device_id', '')
                device_name = segment.get('name') or device_id
                feature.setAttributes([device_id, device_name])
                if not layer.addFeature(feature):
                    raise RuntimeError(f"Failed to add breadcrumb segment for device {device_id}")

            if not layer.commitChanges():
                errors = layer.commitErrors()
                raise RuntimeError(
                    f"Failed to commit changes to {self.BREADCRUMBS_LAYER_NAME}: "
                    f"{'; '.join(errors) if errors else 'Unknown error'}"
                )

        except Exception as e:
            layer.rollBack()
            raise LayerTransactionError(
                self.BREADCRUMBS_LAYER_NAME,
                "commit changes",
                details=str(e)
            ) from e

        finally:
            if layer.isEditable():
                layer.rollBack()

    @staticmethod
    def _parse_iso_timestamp(timestamp: str) -> datetime:
        """Parse ISO timestamp handling 'Z' suffix."""
        if not isinstance(timestamp, str):
            raise ValueError("Timestamp must be a string")

        ts = timestamp.strip()
        if ts.endswith('Z'):
            ts = ts[:-1] + '+00:00'

        return datetime.fromisoformat(ts)

    def _apply_breadcrumbs_style(self, layer: QgsVectorLayer):
        """
        Apply or update categorized style to breadcrumbs safely.

        Updates existing renderer to:
        1. Prevent crashes (replacing renderer deletes C++ objects UI might be using)
        2. Preserve user manual color changes
        3. Only add categories for new devices
        """
        if not bool(layer.customProperty(self.BREADCRUMB_STYLE_MANAGED_PROP, True)):
            return

        # Get unique device IDs from data
        try:
            device_ids = layer.uniqueValues(layer.fields().indexOf('device_id'))
        except Exception:
            # Layer might not be valid yet
            return

        # Check if we already have a categorized renderer
        current_renderer = layer.renderer()
        
        style_initialized = bool(
            layer.customProperty(self.BREADCRUMB_STYLE_INITIALIZED_PROP, False)
        )

        if isinstance(current_renderer, QgsCategorizedSymbolRenderer):
            # UPDATE EXISTING: Safest approach
            # 1. Get existing categories
            existing_categories = current_renderer.categories()
            existing_ids = {cat.value() for cat in existing_categories}
            
            # 2. Find new devices that need categories
            new_devices = [d for d in device_ids if d not in existing_ids]
            
            if not new_devices:
                return  # Nothing to do, renderer is up to date
                
            # 3. Create categories ONLY for new devices
            for device_id in new_devices:
                color = self._get_device_color(str(device_id))
                symbol = QgsLineSymbol.createSimple({
                    'color': color.name(),
                    'width': '2',
                    'line_style': 'solid',
                    'joinstyle': 'round',
                    'capstyle': 'round'
                })
                category = QgsRendererCategory(device_id, symbol, str(device_id))
                current_renderer.addCategory(category)
            
            # Force refresh of the legend/canvas
            layer.triggerRepaint()
            layer.setCustomProperty(self.BREADCRUMB_STYLE_INITIALIZED_PROP, True)
            
        else:
            if style_initialized:
                # User switched renderer manually - stop auto styling so their custom
                # symbology persists across refreshes.
                layer.setCustomProperty(self.BREADCRUMB_STYLE_MANAGED_PROP, False)
                print("[SARTRACKER] Breadcrumb renderer manually overridden; auto styling disabled.")
                return

            # FIRST LOAD / RESET: Create new renderer
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
            layer.setCustomProperty(self.BREADCRUMB_STYLE_INITIALIZED_PROP, True)
