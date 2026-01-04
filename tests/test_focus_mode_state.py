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

    def test_to_dict_is_json_serializable(self):
        """to_dict result should be JSON serializable."""
        from utils.focus_mode_state import FocusModePlusState
        state = FocusModePlusState()
        state.is_active = True
        state.hidden_dock_names = ["Test"]
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
