# -*- coding: utf-8 -*-
"""
Tests for SAR-drpu: Initial zoom buffering to prevent extreme zoom on first load.

TDD Red Phase: These tests define the expected behavior for the fix.
The tests verify that:
1. Single device positions get buffered to reasonable extent
2. Multiple clustered devices get buffered
3. Multiple spread-out devices use combined extent (may not need extra buffer)
4. Settings from config/settings.py are respected
"""
import pytest
from unittest.mock import MagicMock, patch, PropertyMock


class MockQgsRectangle:
    """Mock QgsRectangle for testing extent calculations."""

    def __init__(self, xmin=0, ymin=0, xmax=0, ymax=0):
        # Support copy constructor: QgsRectangle(other_rectangle)
        if isinstance(xmin, MockQgsRectangle):
            other = xmin
            self._xmin = other._xmin
            self._ymin = other._ymin
            self._xmax = other._xmax
            self._ymax = other._ymax
        else:
            self._xmin = xmin
            self._ymin = ymin
            self._xmax = xmax
            self._ymax = ymax

    def width(self):
        return self._xmax - self._xmin

    def height(self):
        return self._ymax - self._ymin

    def isEmpty(self):
        # QGIS isEmpty() returns True for inverted/uninitialized rectangles,
        # NOT for zero-width points. A point at (x,y) is NOT empty.
        return self._xmax < self._xmin or self._ymax < self._ymin

    def isNull(self):
        return self._xmin == 0 and self._ymin == 0 and self._xmax == 0 and self._ymax == 0

    def combineExtentWith(self, other):
        """Expand this extent to include another extent."""
        if self.isNull():
            self._xmin = other._xmin
            self._ymin = other._ymin
            self._xmax = other._xmax
            self._ymax = other._ymax
        else:
            self._xmin = min(self._xmin, other._xmin)
            self._ymin = min(self._ymin, other._ymin)
            self._xmax = max(self._xmax, other._xmax)
            self._ymax = max(self._ymax, other._ymax)

    def buffered(self, distance):
        """Return a new rectangle expanded by distance on all sides."""
        return MockQgsRectangle(
            self._xmin - distance,
            self._ymin - distance,
            self._xmax + distance,
            self._ymax + distance
        )

    def __repr__(self):
        return f"MockQgsRectangle({self._xmin}, {self._ymin}, {self._xmax}, {self._ymax})"


def create_mock_layer(extent_xmin, extent_ymin, extent_xmax, extent_ymax, feature_count=1):
    """Create a mock layer with specified extent."""
    layer = MagicMock()
    layer.isValid.return_value = True
    layer.featureCount.return_value = feature_count
    layer.extent.return_value = MockQgsRectangle(extent_xmin, extent_ymin, extent_xmax, extent_ymax)
    return layer


class TestInitialZoomBuffering:
    """Test cases for initial zoom buffering behavior."""

    def test_single_point_extent_is_buffered(self):
        """
        SAR-drpu: A single device position (point) should be buffered to ~1km.

        A point has zero extent, so without buffering, QGIS zooms to street level.
        The fix should apply INITIAL_ZOOM_BUFFER_DEGREES (~0.01 = ~1km).
        """
        from sartracker.controllers.layer_managers.tracking_manager import TrackingLayerManager
        from sartracker.config.settings import INITIAL_ZOOM_BUFFER_DEGREES, INITIAL_ZOOM_MIN_EXTENT_DEGREES

        # Create manager with mocked dependencies
        mock_iface = MagicMock()
        mock_canvas = MagicMock()
        mock_iface.mapCanvas.return_value = mock_canvas

        manager = TrackingLayerManager(mock_iface)
        manager.first_load = True
        manager.USE_PER_DEVICE_POSITIONS = True

        # Single device at a point (zero extent) - will be returned by mocked helper
        point_extent = MockQgsRectangle(-9.5, 52.0, -9.5, 52.0)

        # Mock the helper to return the point extent, and mock per-device checks
        with patch.object(manager, '_ensure_per_device_ready'):
            with patch.object(manager, '_update_positions_per_device'):
                with patch.object(manager, '_log_tracking_event'):
                    with patch.object(manager, '_calculate_combined_device_extent', return_value=point_extent):
                        # Trigger the zoom logic
                        manager.update_current_positions([{
                            'device_id': 'device1',
                            'name': 'Test Device',
                            'lat': 52.0,
                            'lon': -9.5,
                            'ts': '2026-01-05T12:00:00Z'
                        }])

        # Verify setExtent was called with a BUFFERED extent
        mock_canvas.setExtent.assert_called_once()
        extent_arg = mock_canvas.setExtent.call_args[0][0]

        # The extent should be significantly larger than zero (buffered)
        # Allow small floating point tolerance (0.1% of expected value)
        expected_min_size = INITIAL_ZOOM_BUFFER_DEGREES * 2
        tolerance = expected_min_size * 0.01
        assert extent_arg.width() >= expected_min_size - tolerance, \
            f"Expected buffered width >= {expected_min_size}, got {extent_arg.width()}"
        assert extent_arg.height() >= expected_min_size - tolerance, \
            f"Expected buffered height >= {expected_min_size}, got {extent_arg.height()}"

    def test_multiple_clustered_devices_are_buffered(self):
        """
        SAR-drpu: Multiple devices clustered together should still be buffered.

        If 5 devices are within 100m of each other, the combined extent is still
        too small for a useful SAR overview. Buffer should be applied.
        """
        from sartracker.controllers.layer_managers.tracking_manager import TrackingLayerManager
        from sartracker.config.settings import INITIAL_ZOOM_MIN_EXTENT_DEGREES

        mock_iface = MagicMock()
        mock_canvas = MagicMock()
        mock_iface.mapCanvas.return_value = mock_canvas

        manager = TrackingLayerManager(mock_iface)
        manager.first_load = True
        manager.USE_PER_DEVICE_POSITIONS = True

        # Combined extent of clustered devices (~0.002 degrees = ~200m)
        clustered_extent = MockQgsRectangle(-9.501, 51.999, -9.499, 52.001)

        with patch.object(manager, '_ensure_per_device_ready'):
            with patch.object(manager, '_update_positions_per_device'):
                with patch.object(manager, '_log_tracking_event'):
                    with patch.object(manager, '_calculate_combined_device_extent', return_value=clustered_extent):
                        manager.update_current_positions([
                            {'device_id': 'device1', 'name': 'D1', 'lat': 52.0, 'lon': -9.5, 'ts': '2026-01-05T12:00:00Z'},
                        ])

        mock_canvas.setExtent.assert_called_once()
        extent_arg = mock_canvas.setExtent.call_args[0][0]

        # Even with 3 devices, combined extent is ~0.002 degrees which is < MIN threshold
        # So buffering should be applied, resulting in extent >= MIN threshold
        assert extent_arg.width() >= INITIAL_ZOOM_MIN_EXTENT_DEGREES, \
            f"Expected width >= {INITIAL_ZOOM_MIN_EXTENT_DEGREES}, got {extent_arg.width()}"

    def test_spread_out_devices_use_combined_extent(self):
        """
        SAR-drpu: Devices spread across a large area should use combined extent.

        If devices are spread across 5km, the combined extent is already useful
        and may not need additional buffering (or minimal buffering).
        """
        from sartracker.controllers.layer_managers.tracking_manager import TrackingLayerManager
        from sartracker.config.settings import INITIAL_ZOOM_MIN_EXTENT_DEGREES

        mock_iface = MagicMock()
        mock_canvas = MagicMock()
        mock_iface.mapCanvas.return_value = mock_canvas

        manager = TrackingLayerManager(mock_iface)
        manager.first_load = True
        manager.USE_PER_DEVICE_POSITIONS = True

        # Combined extent of spread devices (~0.05 degrees = ~5km)
        spread_extent = MockQgsRectangle(-9.55, 52.00, -9.50, 52.05)

        with patch.object(manager, '_ensure_per_device_ready'):
            with patch.object(manager, '_update_positions_per_device'):
                with patch.object(manager, '_log_tracking_event'):
                    with patch.object(manager, '_calculate_combined_device_extent', return_value=spread_extent):
                        manager.update_current_positions([
                            {'device_id': 'device1', 'name': 'D1', 'lat': 52.0, 'lon': -9.5, 'ts': '2026-01-05T12:00:00Z'},
                        ])

        mock_canvas.setExtent.assert_called_once()
        extent_arg = mock_canvas.setExtent.call_args[0][0]

        # Combined extent is already ~0.05 degrees which is > MIN threshold (0.02)
        # So no buffering needed - extent should be roughly the original
        assert extent_arg.width() >= 0.04, \
            f"Expected combined extent width >= 0.04, got {extent_arg.width()}"
        assert extent_arg.height() >= 0.04, \
            f"Expected combined extent height >= 0.04, got {extent_arg.height()}"

    def test_first_load_flag_prevents_repeated_zoom(self):
        """
        SAR-drpu: Auto-zoom should only happen on first load, not every update.
        """
        from sartracker.controllers.layer_managers.tracking_manager import TrackingLayerManager

        mock_iface = MagicMock()
        mock_canvas = MagicMock()
        mock_iface.mapCanvas.return_value = mock_canvas

        manager = TrackingLayerManager(mock_iface)
        manager.first_load = False  # Not first load
        manager.USE_PER_DEVICE_POSITIONS = True

        with patch.object(manager, '_ensure_per_device_ready'):
            with patch.object(manager, '_update_positions_per_device'):
                with patch.object(manager, '_log_tracking_event'):
                    manager.update_current_positions([{
                        'device_id': 'device1', 'name': 'D1', 'lat': 52.0, 'lon': -9.5, 'ts': '2026-01-05T12:00:00Z'
                    }])

        # setExtent should NOT be called when first_load is False
        mock_canvas.setExtent.assert_not_called()

    def test_settings_are_imported_from_config(self):
        """
        SAR-drpu: Verify that zoom settings exist in config/settings.py.
        """
        from sartracker.config.settings import (
            INITIAL_ZOOM_BUFFER_DEGREES,
            INITIAL_ZOOM_MIN_EXTENT_DEGREES
        )

        # Settings should have reasonable values
        assert INITIAL_ZOOM_BUFFER_DEGREES > 0, "Buffer should be positive"
        assert INITIAL_ZOOM_BUFFER_DEGREES <= 0.1, "Buffer should be reasonable (< ~10km)"

        assert INITIAL_ZOOM_MIN_EXTENT_DEGREES > 0, "Min extent should be positive"
        assert INITIAL_ZOOM_MIN_EXTENT_DEGREES <= 0.2, "Min extent should be reasonable (< ~20km)"

        # Buffer should be less than or equal to min extent threshold
        assert INITIAL_ZOOM_BUFFER_DEGREES <= INITIAL_ZOOM_MIN_EXTENT_DEGREES, \
            "Buffer should be <= min extent threshold"


class TestCalculateCombinedDeviceExtent:
    """Test the _calculate_combined_device_extent helper method directly."""

    def test_single_layer_returns_its_extent(self):
        """Single device layer should return that layer's extent."""
        from sartracker.controllers.layer_managers.tracking_manager import TrackingLayerManager

        mock_iface = MagicMock()
        manager = TrackingLayerManager(mock_iface)

        # Create mock layer with known extent
        mock_layer = create_mock_layer(-9.5, 52.0, -9.5, 52.0)
        manager._device_position_layers = {'device1': mock_layer}

        # Patch QgsRectangle to use our mock
        with patch('sartracker.controllers.layer_managers.tracking_manager.QgsRectangle', MockQgsRectangle):
            result = manager._calculate_combined_device_extent()

        assert result is not None
        # Should be the same as the single layer's extent
        assert result._xmin == -9.5
        assert result._ymin == 52.0

    def test_multiple_layers_combines_extents(self):
        """Multiple device layers should have their extents combined."""
        from sartracker.controllers.layer_managers.tracking_manager import TrackingLayerManager

        mock_iface = MagicMock()
        manager = TrackingLayerManager(mock_iface)

        # Two devices at different locations
        manager._device_position_layers = {
            'device1': create_mock_layer(-9.50, 52.00, -9.50, 52.00),
            'device2': create_mock_layer(-9.55, 52.05, -9.55, 52.05),
        }

        with patch('sartracker.controllers.layer_managers.tracking_manager.QgsRectangle', MockQgsRectangle):
            result = manager._calculate_combined_device_extent()

        assert result is not None
        # Combined extent should span both points
        assert result._xmin == -9.55
        assert result._xmax == -9.50
        assert result._ymin == 52.00
        assert result._ymax == 52.05

    def test_empty_layers_returns_none(self):
        """No device layers should return None."""
        from sartracker.controllers.layer_managers.tracking_manager import TrackingLayerManager

        mock_iface = MagicMock()
        manager = TrackingLayerManager(mock_iface)
        manager._device_position_layers = {}

        with patch('sartracker.controllers.layer_managers.tracking_manager.QgsRectangle', MockQgsRectangle):
            result = manager._calculate_combined_device_extent()

        assert result is None

    def test_invalid_layers_are_skipped(self):
        """Invalid layers should be skipped in extent calculation."""
        from sartracker.controllers.layer_managers.tracking_manager import TrackingLayerManager

        mock_iface = MagicMock()
        manager = TrackingLayerManager(mock_iface)

        # One valid, one invalid layer
        valid_layer = create_mock_layer(-9.5, 52.0, -9.5, 52.0)
        invalid_layer = MagicMock()
        invalid_layer.isValid.return_value = False

        manager._device_position_layers = {
            'device1': valid_layer,
            'device2': invalid_layer,
        }

        with patch('sartracker.controllers.layer_managers.tracking_manager.QgsRectangle', MockQgsRectangle):
            result = manager._calculate_combined_device_extent()

        assert result is not None
        # Should only include the valid layer's extent
        assert result._xmin == -9.5
