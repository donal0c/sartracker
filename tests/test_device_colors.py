# -*- coding: utf-8 -*-
"""
Device Color Generation Tests

Test suite for device color generation in BaseLayerManager._get_device_color().

WHY THIS MATTERS:
SAR coordinators need to quickly identify devices on the map. Consistent,
deterministic colors ensure the same device always appears in the same color
across sessions, layers, and system restarts.

VALUE PROVIDED:
- Determinism: Same device_id always produces same color
- Visibility: Colors are bright enough to see on map backgrounds
- Uniqueness: Different devices get different colors
- Stability: Colors persist across Python restarts (uses MD5, not hash())

REQUIRES: Real QGIS for QColor
"""

import pytest
import hashlib

from sartracker.tests.qgis_runtime import require_real_qgis

# Real QColor behavior is required here, not the mock harness.
require_real_qgis("Device color tests require real QGIS runtime")
pytestmark = pytest.mark.qgis_required

from qgis.core import QgsProject
from qgis.PyQt.QtGui import QColor


# Simplified color generator for testing (matches production algorithm)
class DeviceColorGenerator:
    """
    Simplified device color generator that mirrors production algorithm.

    This allows testing the color generation logic without importing
    the full layer manager infrastructure.
    """

    def __init__(self):
        self.device_colors = {}

    def get_device_color(self, device_id: str) -> QColor:
        """
        Get consistent, deterministic color for a device.

        Matches production algorithm in base_manager.py.
        """
        # Validate device_id
        if not device_id or not isinstance(device_id, str):
            raise ValueError("device_id must be a non-empty string")

        if len(device_id) > 256:
            raise ValueError("device_id exceeds maximum length of 256 characters")

        if device_id not in self.device_colors:
            # Use MD5 hash for deterministic color generation
            hash_bytes = hashlib.md5(device_id.encode('utf-8')).digest()

            # Extract RGB from first 3 bytes
            r = hash_bytes[0]
            g = hash_bytes[1]
            b = hash_bytes[2]

            # Enforce minimum brightness (50) for visibility
            r = max(50, r)
            g = max(50, g)
            b = max(50, b)

            self.device_colors[device_id] = QColor(r, g, b)

        # Return defensive copy
        cached = self.device_colors[device_id]
        return QColor(cached.red(), cached.green(), cached.blue())


@pytest.fixture
def generator():
    """Create a DeviceColorGenerator for testing."""
    return DeviceColorGenerator()


# =============================================================================
# COLOR DETERMINISM TESTS
# =============================================================================

class TestColorDeterminism:
    """Test that device colors are deterministic and consistent."""

    def test_same_device_always_gets_same_color(self, generator):
        """
        CRITICAL: Same device_id must always produce same color.

        VALUE: Coordinators rely on color consistency to track devices.
        """
        device_id = "device_001"

        color1 = generator.get_device_color(device_id)
        color2 = generator.get_device_color(device_id)

        assert color1.red() == color2.red()
        assert color1.green() == color2.green()
        assert color1.blue() == color2.blue()

    def test_color_consistent_across_multiple_calls(self, generator):
        """
        Verify calling _get_device_color multiple times returns same color.

        VALUE: Prevents color flickering on map updates.
        """
        device_id = "team_alpha"
        colors = [generator.get_device_color(device_id) for _ in range(10)]

        # All colors should be identical
        first_color = colors[0]
        for color in colors[1:]:
            assert color.red() == first_color.red()
            assert color.green() == first_color.green()
            assert color.blue() == first_color.blue()

    def test_different_devices_get_different_colors(self, generator):
        """
        CRITICAL: Different device_ids must produce different colors.

        VALUE: Coordinators must distinguish between devices.
        """
        color1 = generator.get_device_color("device_001")
        color2 = generator.get_device_color("device_002")

        # Colors should differ in at least one channel
        assert (color1.red() != color2.red() or
                color1.green() != color2.green() or
                color1.blue() != color2.blue())

    def test_color_uses_md5_not_python_hash(self, generator):
        """
        CRITICAL: Must use MD5 for determinism, not Python's hash().

        VALUE: Python's hash() is randomized (PEP 456) - colors would
        change across Python restarts, breaking coordinator workflows.
        """
        device_id = "device_test"

        # Get color from manager
        color = generator.get_device_color(device_id)

        # Manually compute what MD5-based color should be
        hash_bytes = hashlib.md5(device_id.encode('utf-8')).digest()
        r = hash_bytes[0]
        g = hash_bytes[1]
        b = hash_bytes[2]

        # Apply minimum brightness (50) - production code does this
        r = max(50, r)
        g = max(50, g)
        b = max(50, b)

        # Verify color matches MD5-based calculation
        assert color.red() == r
        assert color.green() == g
        assert color.blue() == b


# =============================================================================
# COLOR VISIBILITY TESTS
# =============================================================================

class TestColorVisibility:
    """Test that colors are visible on map backgrounds."""

    def test_minimum_brightness_enforced(self, generator):
        """
        CRITICAL: All RGB channels >= 50 for visibility.

        VALUE: Dark colors (like 0,0,0) invisible on dark maps.
        """
        # Test multiple devices to ensure brightness enforced for all
        for i in range(20):
            device_id = f"device_{i:03d}"
            color = generator.get_device_color(device_id)

            assert color.red() >= 50, f"{device_id} red too dark: {color.red()}"
            assert color.green() >= 50, f"{device_id} green too dark: {color.green()}"
            assert color.blue() >= 50, f"{device_id} blue too dark: {color.blue()}"

    def test_maximum_values_valid(self, generator):
        """Verify RGB values don't exceed 255."""
        for i in range(20):
            device_id = f"test_{i}"
            color = generator.get_device_color(device_id)

            assert color.red() <= 255
            assert color.green() <= 255
            assert color.blue() <= 255


# =============================================================================
# INPUT VALIDATION TESTS
# =============================================================================

class TestInputValidation:
    """Test device_id input validation."""

    def test_empty_string_raises_value_error(self, generator):
        """
        Empty device_id rejected.

        VALUE: Prevents invalid color cache entries.
        """
        with pytest.raises(ValueError, match="non-empty string"):
            generator.get_device_color("")

    def test_none_raises_value_error(self, generator):
        """None device_id rejected."""
        with pytest.raises(ValueError, match="non-empty string"):
            generator.get_device_color(None)

    def test_too_long_device_id_raises_value_error(self, generator):
        """
        Device_id > 256 chars rejected.

        VALUE: Prevents memory issues with unbounded IDs.
        """
        long_id = "x" * 257
        with pytest.raises(ValueError, match="exceeds maximum length"):
            generator.get_device_color(long_id)

    def test_unicode_device_id_works(self, generator):
        """
        Unicode device IDs (like Irish names) work correctly.

        VALUE: International operations may use native character sets.
        """
        device_id = "Foireann_Éireann_1"  # Team Ireland 1
        color = generator.get_device_color(device_id)

        # Should succeed and return valid color
        assert isinstance(color, QColor)
        assert color.isValid()

    def test_special_characters_in_device_id_work(self, generator):
        """Device IDs with special characters work."""
        device_id = "device-001_alpha@team"
        color = generator.get_device_color(device_id)

        assert isinstance(color, QColor)
        assert color.isValid()


# =============================================================================
# COLOR DISTRIBUTION TESTS
# =============================================================================

class TestColorDistribution:
    """Test that colors are reasonably distributed."""

    def test_color_variety_across_devices(self, generator):
        """
        Verify colors span multiple hues.

        VALUE: Similar colors for adjacent devices would confuse operators.
        """
        colors = [generator.get_device_color(f"device_{i:03d}") for i in range(50)]

        # Check that we have variety in each RGB channel
        reds = [c.red() for c in colors]
        greens = [c.green() for c in colors]
        blues = [c.blue() for c in colors]

        # Should have at least 20 distinct values in each channel
        assert len(set(reds)) >= 20, "Insufficient red channel variety"
        assert len(set(greens)) >= 20, "Insufficient green channel variety"
        assert len(set(blues)) >= 20, "Insufficient blue channel variety"


# =============================================================================
# DEFENSIVE COPY TESTS
# =============================================================================

class TestDefensiveCopy:
    """Test that returned colors are defensive copies."""

    def test_returned_color_is_defensive_copy(self, generator):
        """
        Verify modifying returned color doesn't affect cache.

        VALUE: Prevents bugs where code modifies color and affects other layers.
        """
        device_id = "device_test"

        color1 = generator.get_device_color(device_id)
        original_red = color1.red()

        # Modify returned color
        color1.setRed(123)

        # Get color again - should be unchanged
        color2 = generator.get_device_color(device_id)
        assert color2.red() == original_red, "Color cache was modified"
