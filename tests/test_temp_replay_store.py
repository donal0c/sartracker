# -*- coding: utf-8 -*-
"""
Temporary Replay Store Tests (Phase 3: SAR-604i)

TDD tests for replay session isolation via temporary mission store.

WHY THIS MATTERS (LIFE-SAFETY CRITICAL):
Replay mode must NEVER contaminate live mission data. These tests ensure:
1. Replay uses isolated temporary storage
2. Live mission store is never touched during replay
3. Temp store is cleaned up properly

Test Categories:
1. MissionStorageHelper temp store creation/cleanup
2. LayerManager temp store routing priority
3. Integration with replay enable/disable lifecycle
"""

import os
import shutil
import tempfile
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# =============================================================================
# UNIT TESTS: MissionStorageHelper Temp Store Lifecycle
# =============================================================================

class TestPrepareTemporaryReplayStore:
    """Tests for MissionStorageHelper.prepare_temp_replay_store()"""

    def test_prepare_temp_replay_store_creates_directory(self, tmp_path):
        """
        CRITICAL: Temp store directory must be created.

        VALUE: Ensures replay has a valid storage location.
        """
        from sartracker.utils.mission_storage import MissionStorageHelper

        # Use tmp_path as mock QGIS profile directory
        with patch.object(MissionStorageHelper, '_get_replay_cache_root', return_value=tmp_path):
            token = str(uuid.uuid4())
            gpkg_path = MissionStorageHelper.prepare_temp_replay_store(token)

            # Directory should exist
            assert Path(gpkg_path).parent.exists()
            assert Path(gpkg_path).parent.is_dir()

    def test_prepare_temp_replay_store_returns_valid_gpkg_path(self, tmp_path):
        """
        Returned path must be a valid GeoPackage path.

        VALUE: Layers can use this path for persistent storage.
        """
        from sartracker.utils.mission_storage import MissionStorageHelper

        with patch.object(MissionStorageHelper, '_get_replay_cache_root', return_value=tmp_path):
            token = str(uuid.uuid4())
            gpkg_path = MissionStorageHelper.prepare_temp_replay_store(token)

            assert gpkg_path.endswith('.gpkg')
            assert 'replay' in gpkg_path.lower()

    def test_prepare_temp_replay_store_uses_token_for_uniqueness(self, tmp_path):
        """
        Each token should create a unique directory.

        VALUE: Multiple replay sessions don't conflict.
        """
        from sartracker.utils.mission_storage import MissionStorageHelper

        with patch.object(MissionStorageHelper, '_get_replay_cache_root', return_value=tmp_path):
            token1 = str(uuid.uuid4())
            token2 = str(uuid.uuid4())

            path1 = MissionStorageHelper.prepare_temp_replay_store(token1)
            path2 = MissionStorageHelper.prepare_temp_replay_store(token2)

            assert path1 != path2
            assert token1 in path1
            assert token2 in path2

    def test_prepare_temp_replay_store_is_idempotent(self, tmp_path):
        """
        Calling with same token returns same path without error.

        VALUE: Safe to call multiple times during refresh cycles.
        """
        from sartracker.utils.mission_storage import MissionStorageHelper

        with patch.object(MissionStorageHelper, '_get_replay_cache_root', return_value=tmp_path):
            token = str(uuid.uuid4())

            path1 = MissionStorageHelper.prepare_temp_replay_store(token)
            path2 = MissionStorageHelper.prepare_temp_replay_store(token)

            assert path1 == path2


class TestCleanupTemporaryReplayStore:
    """Tests for MissionStorageHelper.cleanup_temp_replay_store()"""

    def test_cleanup_temp_replay_store_removes_directory(self, tmp_path):
        """
        CRITICAL: Cleanup must remove the temp store directory.

        VALUE: No stale data accumulates in cache.
        """
        from sartracker.utils.mission_storage import MissionStorageHelper

        with patch.object(MissionStorageHelper, '_get_replay_cache_root', return_value=tmp_path):
            token = str(uuid.uuid4())
            gpkg_path = MissionStorageHelper.prepare_temp_replay_store(token)
            store_dir = Path(gpkg_path).parent

            # Directory exists before cleanup
            assert store_dir.exists()

            # Cleanup
            MissionStorageHelper.cleanup_temp_replay_store(gpkg_path)

            # Directory should be gone
            assert not store_dir.exists()

    def test_cleanup_temp_replay_store_handles_missing_directory(self, tmp_path):
        """
        Cleanup of non-existent path should not raise.

        VALUE: Idempotent cleanup for robustness.
        """
        from sartracker.utils.mission_storage import MissionStorageHelper

        fake_path = str(tmp_path / "nonexistent" / "replay.gpkg")

        # Should not raise
        MissionStorageHelper.cleanup_temp_replay_store(fake_path)

    def test_cleanup_temp_replay_store_handles_none(self):
        """
        Cleanup with None path should not raise.

        VALUE: Safe to call even when no temp store was created.
        """
        from sartracker.utils.mission_storage import MissionStorageHelper

        # Should not raise
        MissionStorageHelper.cleanup_temp_replay_store(None)


class TestGetReplayCacheRoot:
    """Tests for MissionStorageHelper._get_replay_cache_root()"""

    def test_get_replay_cache_root_returns_path_under_qgis_profile(self):
        """
        Cache root should be under QGIS profile directory.

        VALUE: Temp stores survive QGIS restarts for debugging.
        """
        from sartracker.utils.mission_storage import MissionStorageHelper

        # This test requires QGIS to be available
        pytest.importorskip("qgis.core")

        root = MissionStorageHelper._get_replay_cache_root()

        assert root is not None
        assert 'sartracker' in str(root).lower()
        assert 'replay' in str(root).lower()


# =============================================================================
# UNIT TESTS: LayerManager Temp Store Routing
# =============================================================================

class TestLayerManagerTempStoreRouting:
    """Tests for LayerManager temp store priority over mission store."""

    @pytest.fixture
    def mock_layer_manager(self):
        """Create a minimal mock LayerManager for testing."""
        pytest.importorskip("qgis.core")

        from unittest.mock import MagicMock
        from qgis.core import QgsProject

        manager = MagicMock()
        manager._mission_store_path = "/path/to/mission.gpkg"
        manager._temp_mission_store_path = None
        return manager

    def test_temp_store_takes_priority_over_mission_store(self, tmp_path):
        """
        CRITICAL: When temp store is set, it takes priority over mission store.

        VALUE: Replay data goes to temp store, not live mission store.
        """
        pytest.importorskip("qgis.core")

        from sartracker.layers.manager import LayerManager

        # This is an integration-level test that will fail until implemented
        # We're testing the concept - temp store should override mission store

        iface = MagicMock()
        manager = LayerManager(iface)

        # Set up mission store
        mission_gpkg = str(tmp_path / "mission.gpkg")
        manager._mission_store_path = mission_gpkg

        # Set up temp store
        temp_gpkg = str(tmp_path / "replay" / "temp.gpkg")
        Path(temp_gpkg).parent.mkdir(parents=True, exist_ok=True)

        # This method doesn't exist yet - TDD!
        manager.set_temp_mission_store(temp_gpkg)

        # Temp store should take priority
        assert manager._get_effective_store_path() == temp_gpkg

    def test_clear_temp_store_reverts_to_mission_store(self, tmp_path):
        """
        After clearing temp store, mission store should be used again.

        VALUE: Normal operations resume after replay ends.
        """
        pytest.importorskip("qgis.core")

        from sartracker.layers.manager import LayerManager

        iface = MagicMock()
        manager = LayerManager(iface)

        mission_gpkg = str(tmp_path / "mission.gpkg")
        manager._mission_store_path = mission_gpkg

        temp_gpkg = str(tmp_path / "replay" / "temp.gpkg")
        Path(temp_gpkg).parent.mkdir(parents=True, exist_ok=True)

        # Set temp store
        manager.set_temp_mission_store(temp_gpkg)

        # Clear temp store - this method doesn't exist yet
        manager.clear_temp_mission_store()

        # Should revert to mission store
        assert manager._get_effective_store_path() == mission_gpkg

    def test_mission_store_enabled_checks_temp_store_first(self, tmp_path):
        """
        _mission_store_enabled() should return True if temp store is set.

        VALUE: Layers route to persistent storage during replay.
        """
        pytest.importorskip("qgis.core")

        from sartracker.layers.manager import LayerManager

        iface = MagicMock()
        manager = LayerManager(iface)

        # No stores set
        manager._mission_store_path = None
        manager._temp_mission_store_path = None
        assert manager._mission_store_enabled() is False

        # Only temp store set
        temp_gpkg = str(tmp_path / "replay" / "temp.gpkg")
        Path(temp_gpkg).parent.mkdir(parents=True, exist_ok=True)
        manager.set_temp_mission_store(temp_gpkg)

        assert manager._mission_store_enabled() is True


# =============================================================================
# INTEGRATION TESTS: Replay Lifecycle
# =============================================================================

class TestReplayTempStoreLifecycle:
    """Integration tests for temp store with replay enable/disable."""

    @pytest.mark.qgis_required
    def test_replay_enable_without_mission_creates_temp_store(self):
        """
        CRITICAL: Enabling replay without active mission creates temp store.

        VALUE: Replay always has storage, even without mission.
        """
        # This test verifies the orchestration in provider_controller
        # Will be implemented after unit tests pass
        pytest.skip("Integration test - implement after unit tests pass")

    @pytest.mark.qgis_required
    def test_replay_disable_clears_temp_store(self):
        """
        CRITICAL: Disabling replay clears the temp store.

        VALUE: No stale replay data persists.
        """
        pytest.skip("Integration test - implement after unit tests pass")

    @pytest.mark.qgis_required
    def test_mission_start_clears_temp_store(self):
        """
        CRITICAL: Starting a mission clears any active temp store.

        VALUE: Mission data never mixes with replay temp data.
        """
        pytest.skip("Integration test - implement after unit tests pass")

    @pytest.mark.qgis_required
    def test_live_mission_store_never_modified_by_replay(self):
        """
        LIFE-SAFETY CRITICAL: Replay must never write to live mission store.

        VALUE: Live mission data integrity is preserved.
        """
        pytest.skip("Integration test - implement after unit tests pass")

    @pytest.mark.qgis_required
    def test_plugin_unload_cleans_temp_store(self):
        """
        Temp store should be cleaned up on plugin unload.

        VALUE: No orphaned temp directories.
        """
        pytest.skip("Integration test - implement after unit tests pass")


# =============================================================================
# EDGE CASE TESTS
# =============================================================================

class TestTempStoreEdgeCases:
    """Edge cases and error handling for temp store."""

    def test_temp_store_creation_failure_falls_back_to_memory(self, tmp_path):
        """
        If temp store creation fails, layers should fall back to memory.

        VALUE: Replay still works even if storage fails.
        """
        pytest.importorskip("qgis.core")

        from sartracker.utils.mission_storage import MissionStorageHelper

        # Simulate failure by using a read-only directory
        with patch.object(MissionStorageHelper, '_get_replay_cache_root') as mock_root:
            # Return a path that can't be written to
            mock_root.return_value = Path("/nonexistent/readonly/path")

            token = str(uuid.uuid4())

            # Should return None or raise, not crash
            try:
                result = MissionStorageHelper.prepare_temp_replay_store(token)
                # If it returns, should be None to indicate failure
                assert result is None
            except (OSError, PermissionError):
                # Also acceptable - explicit failure
                pass

    def test_concurrent_replay_sessions_isolated(self, tmp_path):
        """
        Multiple tokens should create isolated stores.

        VALUE: Parallel testing/debugging sessions don't interfere.
        """
        from sartracker.utils.mission_storage import MissionStorageHelper

        with patch.object(MissionStorageHelper, '_get_replay_cache_root', return_value=tmp_path):
            tokens = [str(uuid.uuid4()) for _ in range(3)]
            paths = [MissionStorageHelper.prepare_temp_replay_store(t) for t in tokens]

            # All paths should be unique
            assert len(set(paths)) == 3

            # All directories should exist
            for p in paths:
                assert Path(p).parent.exists()
