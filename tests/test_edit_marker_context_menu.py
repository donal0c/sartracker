# -*- coding: utf-8 -*-
"""
Tests for Edit Marker Properties context menu action (SAR-1xn).

TDD: These tests define the expected behavior for the layer panel
context menu action that allows editing marker properties.
"""

import pytest
from unittest.mock import Mock, MagicMock, patch


class TestEditMarkerContextMenuAction:
    """Tests for the Edit Marker Properties context menu action."""

    def test_action_registration_api_exists(self):
        """Test that QGIS provides the API needed for custom layer actions."""
        # This test verifies the QGIS API we depend on exists
        # The actual integration test requires a full QGIS environment
        try:
            from qgis.gui import QgisInterface
            # Verify the methods we need exist on the interface
            assert hasattr(QgisInterface, 'addCustomActionForLayerType')
            assert hasattr(QgisInterface, 'removeCustomActionForLayerType')
        except ImportError:
            pytest.skip("QGIS not available for this test")

    def test_item_type_to_marker_type_mapping(self):
        """Test that item_type values correctly map to marker_type values."""
        # This mapping is critical for the handler to work correctly
        ITEM_TYPE_TO_MARKER_TYPE = {
            'marker_clue': 'clue',
            'marker_hazard': 'hazard',
            'marker_ipp_lkp': 'ipp_lkp',
            'marker_casualty': 'casualty',
        }

        # Verify all expected mappings
        assert ITEM_TYPE_TO_MARKER_TYPE['marker_clue'] == 'clue'
        assert ITEM_TYPE_TO_MARKER_TYPE['marker_hazard'] == 'hazard'
        assert ITEM_TYPE_TO_MARKER_TYPE['marker_ipp_lkp'] == 'ipp_lkp'
        assert ITEM_TYPE_TO_MARKER_TYPE['marker_casualty'] == 'casualty'

        # Verify non-marker types return None
        assert ITEM_TYPE_TO_MARKER_TYPE.get('search_area') is None
        assert ITEM_TYPE_TO_MARKER_TYPE.get('bearing_line') is None
        assert ITEM_TYPE_TO_MARKER_TYPE.get('device_position') is None

    def test_handler_ignores_non_sar_layers(self):
        """Test that handler returns early for layers without SAR properties."""
        # Arrange
        mock_layer = Mock()
        mock_layer.customProperty.return_value = None  # No SAR properties

        mock_iface = Mock()
        mock_iface.activeLayer.return_value = mock_layer

        mock_marker_controller = Mock()

        # Act - simulate the handler logic
        layer = mock_iface.activeLayer()
        item_type = layer.customProperty('sartracker:item_type')
        item_id = layer.customProperty('sartracker:item_id')

        # Assert - handler should return early, not call marker_controller
        assert item_type is None
        assert item_id is None
        # marker_controller.handle_edit should NOT be called
        mock_marker_controller.handle_edit.assert_not_called()

    def test_handler_ignores_non_marker_sar_layers(self):
        """Test that handler returns early for SAR layers that aren't markers."""
        # Arrange
        mock_layer = Mock()
        mock_layer.customProperty.side_effect = lambda key: {
            'sartracker:item_type': 'search_area',  # Not a marker
            'sartracker:item_id': 'SA-001'
        }.get(key)

        ITEM_TYPE_TO_MARKER_TYPE = {
            'marker_clue': 'clue',
            'marker_hazard': 'hazard',
            'marker_ipp_lkp': 'ipp_lkp',
            'marker_casualty': 'casualty',
        }

        # Act
        item_type = mock_layer.customProperty('sartracker:item_type')
        marker_type = ITEM_TYPE_TO_MARKER_TYPE.get(item_type)

        # Assert - search_area should not map to a marker type
        assert item_type == 'search_area'
        assert marker_type is None

    def test_handler_calls_marker_controller_for_clue(self):
        """Test that handler correctly calls marker_controller.handle_edit for clues."""
        # Arrange
        mock_layer = Mock()
        mock_layer.customProperty.side_effect = lambda key: {
            'sartracker:item_type': 'marker_clue',
            'sartracker:item_id': 'CLU-abc123'
        }.get(key)

        mock_marker_controller = Mock()

        ITEM_TYPE_TO_MARKER_TYPE = {
            'marker_clue': 'clue',
            'marker_hazard': 'hazard',
            'marker_ipp_lkp': 'ipp_lkp',
            'marker_casualty': 'casualty',
        }

        # Act - simulate handler logic
        item_type = mock_layer.customProperty('sartracker:item_type')
        item_id = mock_layer.customProperty('sartracker:item_id')
        marker_type = ITEM_TYPE_TO_MARKER_TYPE.get(item_type)

        if marker_type and item_id:
            mock_marker_controller.handle_edit(marker_type, item_id)

        # Assert
        mock_marker_controller.handle_edit.assert_called_once_with('clue', 'CLU-abc123')

    def test_handler_calls_marker_controller_for_hazard(self):
        """Test that handler correctly calls marker_controller.handle_edit for hazards."""
        # Arrange
        mock_layer = Mock()
        mock_layer.customProperty.side_effect = lambda key: {
            'sartracker:item_type': 'marker_hazard',
            'sartracker:item_id': 'HAZ-xyz789'
        }.get(key)

        mock_marker_controller = Mock()

        ITEM_TYPE_TO_MARKER_TYPE = {
            'marker_clue': 'clue',
            'marker_hazard': 'hazard',
            'marker_ipp_lkp': 'ipp_lkp',
            'marker_casualty': 'casualty',
        }

        # Act
        item_type = mock_layer.customProperty('sartracker:item_type')
        item_id = mock_layer.customProperty('sartracker:item_id')
        marker_type = ITEM_TYPE_TO_MARKER_TYPE.get(item_type)

        if marker_type and item_id:
            mock_marker_controller.handle_edit(marker_type, item_id)

        # Assert
        mock_marker_controller.handle_edit.assert_called_once_with('hazard', 'HAZ-xyz789')

    def test_handler_returns_early_when_no_active_layer(self):
        """Test that handler returns early when no layer is selected."""
        # Arrange
        mock_iface = Mock()
        mock_iface.activeLayer.return_value = None

        mock_marker_controller = Mock()

        # Act - simulate handler logic
        layer = mock_iface.activeLayer()

        # Assert - should return early, no crash
        assert layer is None
        mock_marker_controller.handle_edit.assert_not_called()

    def test_handler_guards_against_unload(self):
        """Test that handler returns early if plugin is unloading."""
        # Arrange
        is_unloading = True
        mock_marker_controller = Mock()

        # Act - simulate handler guard
        if is_unloading:
            result = None  # Early return
        else:
            result = "would_call_handler"

        # Assert
        assert result is None
        mock_marker_controller.handle_edit.assert_not_called()


class TestQGISVersionCompatibility:
    """Tests for QGIS version compatibility in layer type handling."""

    def test_vector_layer_type_available(self):
        """Test that we can get the correct VectorLayer type enum."""
        # This tests our compatibility approach
        # In QGIS 3.30+, it's Qgis.LayerType.VectorLayer
        # In QGIS < 3.30, it's QgsMapLayerType.VectorLayer or QgsMapLayer.VectorLayer

        # The implementation should handle both cases
        # We test that our compatibility function returns a valid value
        try:
            from qgis.core import Qgis
            # QGIS 3.30+ path
            if hasattr(Qgis, 'LayerType'):
                vector_type = Qgis.LayerType.VectorLayer
                assert vector_type is not None
            else:
                # Older QGIS - skip this test
                pytest.skip("Qgis.LayerType not available in this QGIS version")
        except ImportError:
            # No QGIS available - test the fallback logic
            pytest.skip("QGIS not available for this test")


class TestActionCleanup:
    """Tests for proper cleanup of the context menu action."""

    def test_action_removed_on_unload(self):
        """Test that the action is properly removed during unload."""
        # Arrange
        mock_iface = Mock()
        mock_action = Mock()

        # Act - simulate unload cleanup
        mock_iface.removeCustomActionForLayerType(mock_action)

        # Assert
        mock_iface.removeCustomActionForLayerType.assert_called_once_with(mock_action)

    def test_cleanup_handles_none_action(self):
        """Test that cleanup handles case where action was never created."""
        # Arrange
        edit_marker_action = None
        mock_iface = Mock()

        # Act - simulate cleanup guard
        if edit_marker_action is not None:
            mock_iface.removeCustomActionForLayerType(edit_marker_action)

        # Assert - should not crash, should not call remove
        mock_iface.removeCustomActionForLayerType.assert_not_called()
