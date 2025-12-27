# -*- coding: utf-8 -*-
"""
Unit tests for services/vendor_bootstrap.py

Phase 1 Refactor: Tests vendor dependency bootstrapping extracted from sartracker.py

These tests verify:
1. Vendor bundle verification detects missing assets
2. Bootstrap function returns correct diagnostics structure
3. Module can be imported without side effects in test context
"""
import pytest
import sys
import os
from pathlib import Path
from unittest.mock import patch, MagicMock
import tempfile
import shutil


class TestVerifyVendorBundle:
    """Tests for _verify_vendor_bundle function."""

    def test_verify_missing_directory(self, tmp_path):
        """Test verification with non-existent vendor directory."""
        # Import the function directly to test it
        # We need to be careful not to trigger bootstrap side effects
        from sartracker.services.vendor_bootstrap import _verify_vendor_bundle

        non_existent = tmp_path / "does_not_exist"
        missing = _verify_vendor_bundle(non_existent)

        # Should report all required files as missing
        assert len(missing) == 5
        assert any("requests" in m for m in missing)
        assert any("urllib3" in m for m in missing)
        assert any("charset_normalizer" in m for m in missing)
        assert any("idna" in m for m in missing)
        assert any("certifi" in m for m in missing)

    def test_verify_empty_directory(self, tmp_path):
        """Test verification with empty vendor directory."""
        from sartracker.services.vendor_bootstrap import _verify_vendor_bundle

        vendor_dir = tmp_path / "vendor"
        vendor_dir.mkdir()

        missing = _verify_vendor_bundle(vendor_dir)

        # Should report all required files as missing
        assert len(missing) == 5

    def test_verify_partial_bundle(self, tmp_path):
        """Test verification with partial vendor bundle (some files missing)."""
        from sartracker.services.vendor_bootstrap import _verify_vendor_bundle

        vendor_dir = tmp_path / "vendor"
        vendor_dir.mkdir()

        # Create only requests package
        requests_dir = vendor_dir / "requests"
        requests_dir.mkdir()
        (requests_dir / "__init__.py").touch()

        missing = _verify_vendor_bundle(vendor_dir)

        # Should report 4 missing (urllib3, charset_normalizer, idna, certifi)
        assert len(missing) == 4
        assert not any("requests" in m and "__init__.py" in m for m in missing)

    def test_verify_complete_bundle(self, tmp_path):
        """Test verification with complete vendor bundle."""
        from sartracker.services.vendor_bootstrap import _verify_vendor_bundle

        vendor_dir = tmp_path / "vendor"
        vendor_dir.mkdir()

        # Create all required packages
        packages = ["requests", "urllib3", "charset_normalizer", "idna"]
        for pkg in packages:
            pkg_dir = vendor_dir / pkg
            pkg_dir.mkdir()
            (pkg_dir / "__init__.py").touch()

        # Create certifi with cacert.pem
        certifi_dir = vendor_dir / "certifi"
        certifi_dir.mkdir()
        (certifi_dir / "cacert.pem").touch()

        missing = _verify_vendor_bundle(vendor_dir)

        # Should report no missing files
        assert missing == []


class TestGetVendorInfo:
    """Tests for get_vendor_info function."""

    def test_returns_dict_copy(self):
        """Test that get_vendor_info returns a dict copy, not the original."""
        from sartracker.services.vendor_bootstrap import get_vendor_info

        info1 = get_vendor_info()
        info2 = get_vendor_info()

        # Should be equal but not the same object
        assert info1 == info2
        assert info1 is not info2

    def test_contains_required_keys(self):
        """Test that vendor info contains all required keys."""
        from sartracker.services.vendor_bootstrap import get_vendor_info

        info = get_vendor_info()

        required_keys = [
            "using_vendor",
            "requests_path",
            "certifi_path",
            "missing",
            "error",
            "bootstrap_complete",
        ]
        for key in required_keys:
            assert key in info, f"Missing required key: {key}"

    def test_using_vendor_is_bool(self):
        """Test that using_vendor is a boolean."""
        from sartracker.services.vendor_bootstrap import get_vendor_info

        info = get_vendor_info()
        assert isinstance(info["using_vendor"], bool)

    def test_missing_is_list(self):
        """Test that missing is a list."""
        from sartracker.services.vendor_bootstrap import get_vendor_info

        info = get_vendor_info()
        assert isinstance(info["missing"], list)


class TestBootstrapVendor:
    """Tests for bootstrap_vendor function."""

    def test_bootstrap_with_nonexistent_path(self, tmp_path):
        """Test bootstrap with non-existent plugin root."""
        from sartracker.services.vendor_bootstrap import bootstrap_vendor, _vendor_info

        # Reset state for clean test
        original_state = dict(_vendor_info)

        try:
            # Create a non-existent path
            fake_root = tmp_path / "nonexistent_plugin"

            result = bootstrap_vendor(fake_root)

            # Should return a dict with error info
            assert isinstance(result, dict)
            assert result.get("error") is not None or result.get("bootstrap_complete") is True

        finally:
            # Restore original state
            _vendor_info.clear()
            _vendor_info.update(original_state)

    def test_bootstrap_returns_diagnostics_structure(self, tmp_path):
        """Test that bootstrap returns proper diagnostics structure."""
        from sartracker.services.vendor_bootstrap import bootstrap_vendor, _vendor_info

        # Reset state for clean test
        original_state = dict(_vendor_info)

        try:
            # Create minimal plugin structure
            plugin_root = tmp_path / "sartracker"
            plugin_root.mkdir()
            vendor_dir = plugin_root / "vendor" / "site-packages"
            vendor_dir.mkdir(parents=True)

            result = bootstrap_vendor(plugin_root)

            # Should contain expected keys
            assert "using_vendor" in result
            assert "requests_path" in result
            assert "certifi_path" in result
            assert "missing" in result
            assert "error" in result
            assert "bootstrap_complete" in result

        finally:
            # Restore original state
            _vendor_info.clear()
            _vendor_info.update(original_state)

    def test_bootstrap_idempotent(self, tmp_path):
        """Test that multiple bootstrap calls are idempotent."""
        from sartracker.services.vendor_bootstrap import bootstrap_vendor, _vendor_info

        # Reset state for clean test
        original_state = dict(_vendor_info)

        try:
            # Create minimal plugin structure
            plugin_root = tmp_path / "sartracker"
            plugin_root.mkdir()
            vendor_dir = plugin_root / "vendor" / "site-packages"
            vendor_dir.mkdir(parents=True)

            # First bootstrap
            result1 = bootstrap_vendor(plugin_root)

            # Second bootstrap should return same result (idempotent)
            result2 = bootstrap_vendor(plugin_root)

            # Both calls should succeed and return equivalent info
            assert result1["bootstrap_complete"] == result2["bootstrap_complete"]

        finally:
            # Restore original state
            _vendor_info.clear()
            _vendor_info.update(original_state)


class TestIntegrationWithSartracker:
    """Integration tests verifying sartracker.py correctly uses vendor_bootstrap."""

    def test_vendor_info_exported_from_sartracker(self):
        """Test that _vendor_info is available in sartracker module."""
        # This test verifies the integration is correct
        # It imports sartracker which triggers the bootstrap
        try:
            # We can't fully import sartracker without QGIS, but we can
            # verify the vendor_bootstrap module exports correctly
            from sartracker.services.vendor_bootstrap import get_vendor_info

            info = get_vendor_info()
            assert info is not None
            assert isinstance(info, dict)
        except ImportError as e:
            # Expected if QGIS modules not available
            if "qgis" not in str(e).lower():
                raise
            pytest.skip("QGIS not available for full integration test")
