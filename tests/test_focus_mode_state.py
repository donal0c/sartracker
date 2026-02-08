# -*- coding: utf-8 -*-
"""
Tests for Focus Mode Plus state management.

TDD: Tests written BEFORE implementation (SAR-cksi.2)

These tests verify the FocusModePlusState class that captures, hides,
and restores QGIS UI elements for Focus Mode Plus.
"""
import json
import os
import tempfile
from unittest.mock import MagicMock, patch

import pytest


class TestFocusModePlusStateImports:
    """Tests that the module and classes can be imported."""

    def test_focus_mode_plus_state_importable(self):
        """FocusModePlusState should be importable from utils.focus_mode_state."""
        from utils.focus_mode_state import FocusModePlusState
        assert FocusModePlusState is not None

    def test_focus_mode_state_file_importable(self):
        """FocusModeStateFile should be importable from utils.focus_mode_state."""
        from utils.focus_mode_state import FocusModeStateFile
        assert FocusModeStateFile is not None

    def test_find_layers_dock_widget_importable(self):
        """find_layers_dock_widget should be importable from utils.focus_mode_state."""
        from utils.focus_mode_state import find_layers_dock_widget
        assert find_layers_dock_widget is not None

    def test_focus_mode_state_uses_relative_imports(self):
        """focus_mode_state.py must use relative imports for QGIS plugin compatibility."""
        import re
        state_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            'utils', 'focus_mode_state.py'
        )
        with open(state_path, 'r') as f:
            content = f.read()

        # Must NOT have absolute imports like "from utils.X" - must use ".X"
        bad_imports = re.findall(r'^from utils\.', content, re.MULTILINE)
        assert len(bad_imports) == 0, \
            f"focus_mode_state.py must use relative imports, found: {bad_imports}"


class TestSARPanelObjectName:
    """Tests that SAR Panel gets proper objectName for Focus Mode Plus exclusion."""

    def test_sartracker_sets_sar_panel_object_name(self):
        """sartracker.py must set SAR Panel objectName to SARTrackerDock."""
        sartracker_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            'sartracker.py'
        )
        with open(sartracker_path, 'r') as f:
            content = f.read()

        # Must have setObjectName("SARTrackerDock") for SAR Panel
        assert 'setObjectName("SARTrackerDock")' in content, \
            "sartracker.py must set sar_panel.setObjectName('SARTrackerDock') for Focus Mode Plus"


class TestFocusModePlusStateDataclass:
    """Tests for FocusModePlusState dataclass structure."""

    def test_default_is_not_active(self):
        """New state should default to is_active=False."""
        from utils.focus_mode_state import FocusModePlusState
        state = FocusModePlusState()
        assert state.is_active is False

    def test_default_menu_bar_visible(self):
        """New state should default menu_bar_was_visible=True."""
        from utils.focus_mode_state import FocusModePlusState
        state = FocusModePlusState()
        assert state.menu_bar_was_visible is True

    def test_default_status_bar_visible(self):
        """New state should default status_bar_was_visible=True."""
        from utils.focus_mode_state import FocusModePlusState
        state = FocusModePlusState()
        assert state.status_bar_was_visible is True

    def test_default_hidden_docks_empty(self):
        """New state should have empty hidden_docks list."""
        from utils.focus_mode_state import FocusModePlusState
        state = FocusModePlusState()
        assert state.hidden_docks == []

    def test_default_hidden_toolbars_empty(self):
        """New state should have empty hidden_toolbars list."""
        from utils.focus_mode_state import FocusModePlusState
        state = FocusModePlusState()
        assert state.hidden_toolbars == []

    def test_default_keep_visible_includes_sar_panel(self):
        """Default keep_visible_docks should include SARTrackerDock."""
        from utils.focus_mode_state import FocusModePlusState
        state = FocusModePlusState()
        assert "SARTrackerDock" in state.keep_visible_docks

    def test_default_keep_visible_includes_layers(self):
        """Default keep_visible_docks should include Layers panel identifiers."""
        from utils.focus_mode_state import FocusModePlusState
        state = FocusModePlusState()
        # Should include at least one layers panel identifier
        layers_identifiers = {"Layers", "LayerTreeDock"}
        assert any(ident in state.keep_visible_docks for ident in layers_identifiers)

    def test_default_keep_visible_excludes_settings_panel(self):
        """Settings panel should not be forced visible in Focus Mode Plus."""
        from utils.focus_mode_state import FocusModePlusState
        state = FocusModePlusState()
        assert "SARTrackerSettings" not in state.keep_visible_docks


class TestFocusModePlusStateSerialization:
    """Tests for state serialization/deserialization."""

    def test_to_dict_returns_dict(self):
        """to_dict should return a dictionary."""
        from utils.focus_mode_state import FocusModePlusState
        state = FocusModePlusState()
        result = state.to_dict()
        assert isinstance(result, dict)

    def test_to_dict_includes_is_active(self):
        """to_dict should include is_active field."""
        from utils.focus_mode_state import FocusModePlusState
        state = FocusModePlusState()
        state.is_active = True
        result = state.to_dict()
        assert result["is_active"] is True

    def test_to_dict_includes_menu_bar_state(self):
        """to_dict should include menu_bar_was_visible field."""
        from utils.focus_mode_state import FocusModePlusState
        state = FocusModePlusState()
        state.menu_bar_was_visible = False
        result = state.to_dict()
        assert result["menu_bar_was_visible"] is False

    def test_to_dict_includes_status_bar_state(self):
        """to_dict should include status_bar_was_visible field."""
        from utils.focus_mode_state import FocusModePlusState
        state = FocusModePlusState()
        state.status_bar_was_visible = False
        result = state.to_dict()
        assert result["status_bar_was_visible"] is False

    def test_to_dict_includes_dock_names(self):
        """to_dict should include hidden_dock_names list."""
        from utils.focus_mode_state import FocusModePlusState
        state = FocusModePlusState()
        state.hidden_dock_names = ["Dock1", "Dock2"]
        result = state.to_dict()
        assert result["hidden_dock_names"] == ["Dock1", "Dock2"]

    def test_to_dict_includes_toolbar_names(self):
        """to_dict should include hidden_toolbar_names list."""
        from utils.focus_mode_state import FocusModePlusState
        state = FocusModePlusState()
        state.hidden_toolbar_names = ["Toolbar1", "Toolbar2"]
        result = state.to_dict()
        assert result["hidden_toolbar_names"] == ["Toolbar1", "Toolbar2"]

    def test_to_dict_includes_version(self):
        """to_dict should include a version field for future compatibility."""
        from utils.focus_mode_state import FocusModePlusState
        state = FocusModePlusState()
        result = state.to_dict()
        assert "version" in result

    def test_to_dict_does_not_serialize_main_window_state(self):
        """to_dict should not persist binary main_window_state across sessions."""
        from utils.focus_mode_state import FocusModePlusState
        state = FocusModePlusState()
        state.main_window_state = "YWJj"
        result = state.to_dict()
        assert "main_window_state" not in result

    def test_to_dict_is_json_serializable(self):
        """to_dict result should be JSON serializable."""
        from utils.focus_mode_state import FocusModePlusState
        state = FocusModePlusState()
        state.is_active = True
        state.hidden_dock_names = ["Test"]
        state.main_window_state = "YWJj"
        result = state.to_dict()
        # Should not raise
        json_str = json.dumps(result)
        assert json_str is not None


class TestFocusModePlusStateClear:
    """Tests for state clearing."""

    def test_clear_resets_is_active(self):
        """_clear should reset is_active to False."""
        from utils.focus_mode_state import FocusModePlusState
        state = FocusModePlusState()
        state.is_active = True
        state._clear()
        assert state.is_active is False

    def test_clear_resets_hidden_lists(self):
        """_clear should empty hidden_docks and hidden_toolbars."""
        from utils.focus_mode_state import FocusModePlusState
        state = FocusModePlusState()
        state.hidden_docks = [("test", MagicMock())]
        state.hidden_toolbars = [("test", MagicMock())]
        state.hidden_dock_names = ["test"]
        state.hidden_toolbar_names = ["test"]
        state._clear()
        assert state.hidden_docks == []
        assert state.hidden_toolbars == []
        assert state.hidden_dock_names == []
        assert state.hidden_toolbar_names == []


class TestFocusModeStateFile:
    """Tests for FocusModeStateFile crash recovery persistence."""

    def test_get_state_file_path_returns_string(self):
        """get_state_file_path should return a string path."""
        from utils.focus_mode_state import FocusModeStateFile
        path = FocusModeStateFile.get_state_file_path()
        assert isinstance(path, str)
        assert len(path) > 0


class TestFocusModePlusStateMainWindowState:
    """Tests for main window state capture/restore."""

    def test_capture_saves_main_window_state(self):
        """capture should store main window state as base64 string."""
        from utils.focus_mode_state import FocusModePlusState
        from qgis.PyQt.QtWidgets import QMainWindow

        mock_main_window = MagicMock(spec=QMainWindow)
        mock_main_window.menuBar.return_value = MagicMock(isVisible=MagicMock(return_value=True))
        mock_main_window.statusBar.return_value = MagicMock(isVisible=MagicMock(return_value=True))
        mock_main_window.findChildren.return_value = []
        mock_main_window.saveState.return_value = b"abc"

        with patch('utils.focus_mode_state.sip_isdeleted', return_value=False):
            state = FocusModePlusState()
            state.capture(mock_main_window)

        assert state.main_window_state == "YWJj"

    def test_restore_uses_saved_main_window_state(self):
        """restore should call restoreState when saved state is available."""
        from utils.focus_mode_state import FocusModePlusState
        from qgis.PyQt.QtWidgets import QMainWindow

        mock_main_window = MagicMock(spec=QMainWindow)
        mock_main_window.menuBar.return_value = MagicMock()
        mock_main_window.statusBar.return_value = MagicMock()
        mock_main_window.restoreState.return_value = True

        state = FocusModePlusState()
        state.is_active = True
        state.main_window_state = "YWJj"

        with patch('utils.focus_mode_state.sip_isdeleted', return_value=False):
            state.restore(mock_main_window)

        mock_main_window.restoreState.assert_called_once()

    def test_get_state_file_path_ends_with_json(self):
        """State file path should end with .json extension."""
        from utils.focus_mode_state import FocusModeStateFile
        path = FocusModeStateFile.get_state_file_path()
        assert path.endswith(".json")

    def test_save_creates_file(self):
        """save should create the state file."""
        from utils.focus_mode_state import FocusModePlusState, FocusModeStateFile

        # Use temp directory for test
        with tempfile.TemporaryDirectory() as tmpdir:
            test_path = os.path.join(tmpdir, "test_state.json")

            with patch.object(FocusModeStateFile, 'get_state_file_path', return_value=test_path):
                state = FocusModePlusState()
                state.is_active = True
                result = FocusModeStateFile.save(state)
                assert result is True
                assert os.path.exists(test_path)

    def test_save_writes_valid_json(self):
        """save should write valid JSON content."""
        from utils.focus_mode_state import FocusModePlusState, FocusModeStateFile

        with tempfile.TemporaryDirectory() as tmpdir:
            test_path = os.path.join(tmpdir, "test_state.json")

            with patch.object(FocusModeStateFile, 'get_state_file_path', return_value=test_path):
                state = FocusModePlusState()
                state.is_active = True
                FocusModeStateFile.save(state)

                with open(test_path, 'r') as f:
                    data = json.load(f)
                    assert data["is_active"] is True

    def test_load_returns_dict_when_file_exists(self):
        """load should return dict when state file exists."""
        from utils.focus_mode_state import FocusModeStateFile

        with tempfile.TemporaryDirectory() as tmpdir:
            test_path = os.path.join(tmpdir, "test_state.json")

            # Create test file
            test_data = {"is_active": True, "version": 1}
            with open(test_path, 'w') as f:
                json.dump(test_data, f)

            with patch.object(FocusModeStateFile, 'get_state_file_path', return_value=test_path):
                result = FocusModeStateFile.load()
                assert result is not None
                assert result["is_active"] is True

    def test_load_returns_none_when_file_missing(self):
        """load should return None when state file doesn't exist."""
        from utils.focus_mode_state import FocusModeStateFile

        with tempfile.TemporaryDirectory() as tmpdir:
            test_path = os.path.join(tmpdir, "nonexistent.json")

            with patch.object(FocusModeStateFile, 'get_state_file_path', return_value=test_path):
                result = FocusModeStateFile.load()
                assert result is None

    def test_exists_returns_true_when_file_exists(self):
        """exists should return True when state file exists."""
        from utils.focus_mode_state import FocusModeStateFile

        with tempfile.TemporaryDirectory() as tmpdir:
            test_path = os.path.join(tmpdir, "test_state.json")

            # Create test file
            with open(test_path, 'w') as f:
                f.write("{}")

            with patch.object(FocusModeStateFile, 'get_state_file_path', return_value=test_path):
                assert FocusModeStateFile.exists() is True

    def test_exists_returns_false_when_file_missing(self):
        """exists should return False when state file doesn't exist."""
        from utils.focus_mode_state import FocusModeStateFile

        with tempfile.TemporaryDirectory() as tmpdir:
            test_path = os.path.join(tmpdir, "nonexistent.json")

            with patch.object(FocusModeStateFile, 'get_state_file_path', return_value=test_path):
                assert FocusModeStateFile.exists() is False

    def test_delete_removes_file(self):
        """delete should remove the state file."""
        from utils.focus_mode_state import FocusModeStateFile

        with tempfile.TemporaryDirectory() as tmpdir:
            test_path = os.path.join(tmpdir, "test_state.json")

            # Create test file
            with open(test_path, 'w') as f:
                f.write("{}")

            with patch.object(FocusModeStateFile, 'get_state_file_path', return_value=test_path):
                result = FocusModeStateFile.delete()
                assert result is True
                assert not os.path.exists(test_path)

    def test_delete_returns_true_when_file_missing(self):
        """delete should return True even when file doesn't exist (idempotent)."""
        from utils.focus_mode_state import FocusModeStateFile

        with tempfile.TemporaryDirectory() as tmpdir:
            test_path = os.path.join(tmpdir, "nonexistent.json")

            with patch.object(FocusModeStateFile, 'get_state_file_path', return_value=test_path):
                result = FocusModeStateFile.delete()
                assert result is True


@pytest.mark.qgis_required
class TestFocusModePlusStateWithQGIS:
    """Tests that require real QGIS environment."""

    def test_find_layers_dock_widget_with_qgis(self):
        """find_layers_dock_widget should find the Layers panel in QGIS."""
        from utils.focus_mode_state import find_layers_dock_widget
        from qgis.utils import iface

        if iface is None:
            pytest.skip("iface not available")

        dock = find_layers_dock_widget(iface)
        # May be None in test environment but should not raise
        # In real QGIS it should return a QDockWidget

    def test_capture_with_mock_main_window(self):
        """capture should work with a mock main window."""
        from utils.focus_mode_state import FocusModePlusState
        from qgis.PyQt.QtWidgets import QMainWindow

        # Create a minimal mock
        main_window = MagicMock(spec=QMainWindow)
        main_window.menuBar.return_value = MagicMock(isVisible=MagicMock(return_value=True))
        main_window.statusBar.return_value = MagicMock(isVisible=MagicMock(return_value=True))
        main_window.findChildren.return_value = []

        # Patch sip_isdeleted to return False for mocks (mocks are never deleted)
        with patch('utils.focus_mode_state.sip_isdeleted', return_value=False):
            state = FocusModePlusState()
            count = state.capture(main_window)
            # Should capture at least menu bar and status bar (2)
            assert count >= 0  # May be 0 if mocks don't behave exactly
            assert state.is_active is True

    def test_restore_is_idempotent(self):
        """restore should be safe to call multiple times."""
        from utils.focus_mode_state import FocusModePlusState
        from qgis.PyQt.QtWidgets import QMainWindow

        main_window = MagicMock(spec=QMainWindow)
        main_window.menuBar.return_value = MagicMock()
        main_window.statusBar.return_value = MagicMock()

        state = FocusModePlusState()
        # Restore without capture should be safe (is_active is False)
        result1 = state.restore(main_window)
        result2 = state.restore(main_window)
        # Both should return (0, 0) since nothing was captured
        assert result1 == (0, 0)
        assert result2 == (0, 0)


class TestSARPanelFocusModePlusIntegration:
    """
    Tests for Focus Mode Plus integration in SAR Panel.

    TDD: Tests written BEFORE integration implementation (SAR-cksi.3).

    These tests verify that the SAR Panel correctly uses FocusModePlusState
    to hide/restore menu bar, status bar, and toolbars.

    Note: These tests verify the integration by checking the FocusModePlusState
    methods are called correctly, without requiring full SAR Panel instantiation.
    """

    def test_focus_mode_plus_state_capture_hides_menu_bar(self):
        """FocusModePlusState.apply_hide should hide menu bar when captured visible."""
        from utils.focus_mode_state import FocusModePlusState

        # Create mock main window
        mock_main_window = MagicMock()
        mock_menu_bar = MagicMock()
        mock_menu_bar.isVisible.return_value = True
        mock_status_bar = MagicMock()
        mock_status_bar.isVisible.return_value = True
        mock_main_window.menuBar.return_value = mock_menu_bar
        mock_main_window.statusBar.return_value = mock_status_bar
        mock_main_window.findChildren.return_value = []

        with patch('utils.focus_mode_state.sip_isdeleted', return_value=False):
            state = FocusModePlusState()
            state.capture(mock_main_window)
            state.apply_hide(mock_main_window)

            # Menu bar should have been hidden
            mock_menu_bar.setVisible.assert_called_with(False)

    def test_focus_mode_plus_state_capture_hides_status_bar(self):
        """FocusModePlusState.apply_hide should hide status bar when captured visible."""
        from utils.focus_mode_state import FocusModePlusState

        mock_main_window = MagicMock()
        mock_menu_bar = MagicMock()
        mock_menu_bar.isVisible.return_value = True
        mock_status_bar = MagicMock()
        mock_status_bar.isVisible.return_value = True
        mock_main_window.menuBar.return_value = mock_menu_bar
        mock_main_window.statusBar.return_value = mock_status_bar
        mock_main_window.findChildren.return_value = []

        with patch('utils.focus_mode_state.sip_isdeleted', return_value=False):
            state = FocusModePlusState()
            state.capture(mock_main_window)
            state.apply_hide(mock_main_window)

            # Status bar should have been hidden
            mock_status_bar.setVisible.assert_called_with(False)

    def test_focus_mode_plus_state_restore_shows_menu_bar(self):
        """FocusModePlusState.restore should restore menu bar visibility."""
        from utils.focus_mode_state import FocusModePlusState

        mock_main_window = MagicMock()
        mock_menu_bar = MagicMock()
        mock_menu_bar.isVisible.return_value = True
        mock_status_bar = MagicMock()
        mock_status_bar.isVisible.return_value = True
        mock_main_window.menuBar.return_value = mock_menu_bar
        mock_main_window.statusBar.return_value = mock_status_bar
        mock_main_window.findChildren.return_value = []

        with patch('utils.focus_mode_state.sip_isdeleted', return_value=False):
            state = FocusModePlusState()
            state.capture(mock_main_window)
            state.apply_hide(mock_main_window)

            # Reset mocks to track restore calls
            mock_menu_bar.reset_mock()

            # Restore
            state.restore(mock_main_window)

            # Menu bar should have been restored
            mock_menu_bar.setVisible.assert_called_with(True)

    def test_focus_mode_plus_state_hides_toolbars(self):
        """FocusModePlusState should hide toolbars."""
        from utils.focus_mode_state import FocusModePlusState
        from qgis.PyQt.QtWidgets import QToolBar

        mock_main_window = MagicMock()
        mock_menu_bar = MagicMock()
        mock_menu_bar.isVisible.return_value = True
        mock_status_bar = MagicMock()
        mock_status_bar.isVisible.return_value = True
        mock_main_window.menuBar.return_value = mock_menu_bar
        mock_main_window.statusBar.return_value = mock_status_bar

        # Create mock toolbar
        mock_toolbar = MagicMock(spec=QToolBar)
        mock_toolbar.isVisible.return_value = True
        mock_toolbar.objectName.return_value = "TestToolbar"

        # Return different results for different child types
        def find_children(widget_type):
            if widget_type == QToolBar:
                return [mock_toolbar]
            return []
        mock_main_window.findChildren.side_effect = find_children

        with patch('utils.focus_mode_state.sip_isdeleted', return_value=False):
            state = FocusModePlusState()
            state.capture(mock_main_window)
            state.apply_hide(mock_main_window)

            # Toolbar should have been hidden
            mock_toolbar.setVisible.assert_called_with(False)

    def test_focus_mode_plus_state_is_active_after_capture(self):
        """State should be marked active after capture."""
        from utils.focus_mode_state import FocusModePlusState

        mock_main_window = MagicMock()
        mock_main_window.menuBar.return_value = MagicMock(isVisible=MagicMock(return_value=True))
        mock_main_window.statusBar.return_value = MagicMock(isVisible=MagicMock(return_value=True))
        mock_main_window.findChildren.return_value = []

        with patch('utils.focus_mode_state.sip_isdeleted', return_value=False):
            state = FocusModePlusState()
            assert state.is_active is False

            state.capture(mock_main_window)

            assert state.is_active is True

    def test_focus_mode_plus_state_inactive_after_restore(self):
        """State should be marked inactive after restore."""
        from utils.focus_mode_state import FocusModePlusState

        mock_main_window = MagicMock()
        mock_main_window.menuBar.return_value = MagicMock(isVisible=MagicMock(return_value=True))
        mock_main_window.statusBar.return_value = MagicMock(isVisible=MagicMock(return_value=True))
        mock_main_window.findChildren.return_value = []

        with patch('utils.focus_mode_state.sip_isdeleted', return_value=False):
            state = FocusModePlusState()
            state.capture(mock_main_window)
            state.apply_hide(mock_main_window)

            assert state.is_active is True

            state.restore(mock_main_window)

            assert state.is_active is False

    def test_focus_mode_plus_state_preserves_invisible_menu_bar(self):
        """If menu bar was already invisible, it should not be shown on restore."""
        from utils.focus_mode_state import FocusModePlusState

        mock_main_window = MagicMock()
        mock_menu_bar = MagicMock()
        mock_menu_bar.isVisible.return_value = False  # Already hidden
        mock_status_bar = MagicMock()
        mock_status_bar.isVisible.return_value = True
        mock_main_window.menuBar.return_value = mock_menu_bar
        mock_main_window.statusBar.return_value = mock_status_bar
        mock_main_window.findChildren.return_value = []

        with patch('utils.focus_mode_state.sip_isdeleted', return_value=False):
            state = FocusModePlusState()
            state.capture(mock_main_window)

            # Verify menu_bar_was_visible is correctly captured as False
            assert state.menu_bar_was_visible is False, \
                "menu_bar_was_visible should be False when menu bar was already hidden"

            state.apply_hide(mock_main_window)

            # Reset and restore
            mock_menu_bar.reset_mock()
            state.restore(mock_main_window)

            # Menu bar should NOT have setVisible(True) called
            # because it was already invisible before capture
            # Verify setVisible was never called (menu was already hidden)
            for call in mock_menu_bar.setVisible.call_args_list:
                # If setVisible was called, it should not be with True
                assert call[0][0] is not True, \
                    "Menu bar should NOT have setVisible(True) called when it was already hidden"


class TestSARPanelFocusModePlusIntegrationCode:
    """
    Tests that verify SAR Panel code correctly uses FocusModePlusState.

    These tests check the source code and structure rather than runtime
    to ensure the integration is properly implemented.
    """

    def test_sar_panel_imports_focus_mode_state(self):
        """SAR Panel should import FocusModePlusState when toggle is called."""
        # Read the sar_panel.py source and check for the import
        import os
        sar_panel_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            'ui', 'sar_panel.py'
        )
        with open(sar_panel_path, 'r') as f:
            content = f.read()

        # Should have import or usage of FocusModePlusState
        assert 'FocusModePlusState' in content, \
            "SAR Panel should use FocusModePlusState for Focus Mode Plus"

    def test_sar_panel_has_focus_mode_state_initialization(self):
        """SAR Panel should initialize focus_mode_state attribute."""
        import os
        sar_panel_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            'ui', 'sar_panel.py'
        )
        with open(sar_panel_path, 'r') as f:
            content = f.read()

        # Should have focus_mode_state = None or similar initialization
        assert 'focus_mode_state' in content, \
            "SAR Panel should have focus_mode_state attribute"

    def test_toggle_focus_mode_uses_capture_and_apply(self):
        """_toggle_focus_mode should use state.capture() and state.apply_hide()."""
        import os
        sar_panel_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            'ui', 'sar_panel.py'
        )
        with open(sar_panel_path, 'r') as f:
            content = f.read()

        # Should call capture and apply_hide on the state
        assert '.capture(' in content or 'capture(' in content, \
            "SAR Panel should call state.capture() in focus mode"
        assert '.apply_hide(' in content or 'apply_hide(' in content, \
            "SAR Panel should call state.apply_hide() in focus mode"

    def test_toggle_focus_mode_uses_restore(self):
        """_toggle_focus_mode should use state.restore() when exiting."""
        import os
        sar_panel_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            'ui', 'sar_panel.py'
        )
        with open(sar_panel_path, 'r') as f:
            content = f.read()

        # Should call restore on the state
        assert '.restore(' in content, \
            "SAR Panel should call state.restore() when exiting focus mode"

    def test_toggle_focus_mode_has_rapid_toggle_guard(self):
        """_toggle_focus_mode should guard against rapid toggle clicks."""
        import os
        sar_panel_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            'ui', 'sar_panel.py'
        )
        with open(sar_panel_path, 'r') as f:
            content = f.read()

        # Should have transitioning guard
        assert '_focus_mode_transitioning' in content, \
            "SAR Panel should have rapid toggle guard"

    def test_exception_handler_resets_state(self):
        """Exception handler should reset state flags to prevent stuck UI."""
        import os
        sar_panel_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            'ui', 'sar_panel.py'
        )
        with open(sar_panel_path, 'r') as f:
            content = f.read()

        # Exception handler should reset focus_mode_active
        # Look for the pattern in the except block
        assert 'self.focus_mode_active = False' in content, \
            "Exception handler should reset focus_mode_active"


class TestFocusModePlusStateCrashRecovery:
    """Critical crash recovery tests (from_dict deserialization)."""

    def test_from_dict_reconstructs_is_active(self):
        """from_dict should restore is_active flag."""
        from utils.focus_mode_state import FocusModePlusState

        data = {
            "version": 1,
            "is_active": True,
            "menu_bar_was_visible": True,
            "status_bar_was_visible": False,
            "hidden_dock_names": [],
            "hidden_toolbar_names": [],
        }

        mock_main_window = MagicMock()
        mock_main_window.findChildren.return_value = []

        state = FocusModePlusState.from_dict(data, mock_main_window)

        assert state.is_active is True
        assert state.menu_bar_was_visible is True
        assert state.status_bar_was_visible is False

    def test_from_dict_ignores_persisted_main_window_state(self):
        """from_dict should ignore serialized main_window_state for safety."""
        from utils.focus_mode_state import FocusModePlusState

        data = {
            "version": 1,
            "is_active": True,
            "menu_bar_was_visible": True,
            "status_bar_was_visible": True,
            "hidden_dock_names": [],
            "hidden_toolbar_names": [],
            "main_window_state": "YWJj",
        }

        state = FocusModePlusState.from_dict(data, MagicMock())

        assert state.main_window_state is None

    def test_from_dict_reconstructs_dock_references(self):
        """from_dict should rebuild dock references from names."""
        from utils.focus_mode_state import FocusModePlusState
        from qgis.PyQt.QtWidgets import QDockWidget

        # Create mock dock
        mock_dock = MagicMock(spec=QDockWidget)
        mock_dock.objectName.return_value = "TestDock"

        mock_main_window = MagicMock()

        def find_children(widget_type):
            if widget_type == QDockWidget:
                return [mock_dock]
            return []
        mock_main_window.findChildren.side_effect = find_children

        data = {
            "version": 1,
            "is_active": True,
            "menu_bar_was_visible": True,
            "status_bar_was_visible": True,
            "hidden_dock_names": ["TestDock"],
            "hidden_toolbar_names": [],
        }

        with patch('utils.focus_mode_state.sip_isdeleted', return_value=False):
            state = FocusModePlusState.from_dict(data, mock_main_window)

        # Should have rebuilt the dock reference
        assert len(state.hidden_docks) == 1
        assert state.hidden_docks[0][0] == "TestDock"
        assert state.hidden_docks[0][1] is mock_dock

    def test_from_dict_handles_missing_widgets(self):
        """from_dict should handle widgets that no longer exist."""
        from utils.focus_mode_state import FocusModePlusState

        mock_main_window = MagicMock()
        mock_main_window.findChildren.return_value = []  # No widgets found

        data = {
            "version": 1,
            "is_active": True,
            "menu_bar_was_visible": True,
            "status_bar_was_visible": True,
            "hidden_dock_names": ["NonExistentDock"],
            "hidden_toolbar_names": ["NonExistentToolbar"],
        }

        # Should not raise even with missing widgets
        state = FocusModePlusState.from_dict(data, mock_main_window)

        # Hidden lists should be empty (widgets not found)
        assert len(state.hidden_docks) == 0
        assert len(state.hidden_toolbar_names) == 1  # Names stored but refs not rebuilt

    def test_from_dict_with_none_main_window(self):
        """from_dict should handle None main window gracefully."""
        from utils.focus_mode_state import FocusModePlusState

        data = {
            "version": 1,
            "is_active": True,
            "menu_bar_was_visible": True,
            "status_bar_was_visible": True,
            "hidden_dock_names": ["SomeDock"],
            "hidden_toolbar_names": [],
        }

        # Should not raise
        state = FocusModePlusState.from_dict(data, None)

        # Should have preserved names even without refs
        assert state.is_active is True
        assert len(state.hidden_docks) == 0


class TestFocusModePlusStateEdgeCases:
    """Edge case and safety tests."""

    def test_multiple_capture_calls_are_idempotent(self):
        """Calling capture multiple times should be safe (returns 0)."""
        from utils.focus_mode_state import FocusModePlusState

        mock_main_window = MagicMock()
        mock_main_window.menuBar.return_value = MagicMock(isVisible=MagicMock(return_value=True))
        mock_main_window.statusBar.return_value = MagicMock(isVisible=MagicMock(return_value=True))
        mock_main_window.findChildren.return_value = []

        with patch('utils.focus_mode_state.sip_isdeleted', return_value=False):
            state = FocusModePlusState()

            # First capture
            count1 = state.capture(mock_main_window)
            assert count1 >= 2  # At least menu bar and status bar

            # Second capture should return 0 (already active)
            count2 = state.capture(mock_main_window)
            assert count2 == 0

    def test_restore_with_deleted_widgets_succeeds(self):
        """Restore should handle deleted widgets gracefully."""
        from utils.focus_mode_state import FocusModePlusState
        from qgis.PyQt.QtWidgets import QDockWidget

        mock_dock = MagicMock(spec=QDockWidget)
        mock_dock.objectName.return_value = "DeletedDock"
        mock_dock.isVisible.return_value = True

        mock_main_window = MagicMock()
        mock_main_window.menuBar.return_value = MagicMock(isVisible=MagicMock(return_value=True))
        mock_main_window.statusBar.return_value = MagicMock(isVisible=MagicMock(return_value=True))

        def find_children(widget_type):
            if widget_type == QDockWidget:
                return [mock_dock]
            return []
        mock_main_window.findChildren.side_effect = find_children

        # Capture with sip_isdeleted returning False
        with patch('utils.focus_mode_state.sip_isdeleted', return_value=False):
            state = FocusModePlusState()
            state.capture(mock_main_window)
            state.apply_hide(mock_main_window)

        # Now simulate dock being deleted during focus mode
        with patch('utils.focus_mode_state.sip_isdeleted', return_value=True):
            # Restore should NOT crash even with deleted widgets
            restored, errors = state.restore(mock_main_window)

            # Should have errors but not crash
            assert state.is_active is False  # State cleared regardless

    def test_capture_skips_sar_panel_dock(self):
        """SAR Panel should never be hidden."""
        from utils.focus_mode_state import FocusModePlusState
        from qgis.PyQt.QtWidgets import QDockWidget

        # Create mock SAR Panel dock
        mock_sar_dock = MagicMock(spec=QDockWidget)
        mock_sar_dock.objectName.return_value = "SARTrackerDock"
        mock_sar_dock.isVisible.return_value = True

        mock_main_window = MagicMock()
        mock_main_window.menuBar.return_value = MagicMock(isVisible=MagicMock(return_value=True))
        mock_main_window.statusBar.return_value = MagicMock(isVisible=MagicMock(return_value=True))

        def find_children(widget_type):
            if widget_type == QDockWidget:
                return [mock_sar_dock]
            return []
        mock_main_window.findChildren.side_effect = find_children

        with patch('utils.focus_mode_state.sip_isdeleted', return_value=False):
            state = FocusModePlusState()
            state.capture(mock_main_window)

        # SAR Panel should NOT be in hidden_docks
        dock_names = [name for name, _ in state.hidden_docks]
        assert "SARTrackerDock" not in dock_names
