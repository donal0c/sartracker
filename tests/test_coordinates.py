# -*- coding: utf-8 -*-
"""
LIFE-SAFETY CRITICAL: Coordinate conversion tests

Test suite for utils/coordinates.py - validates coordinate transformations
between Irish Grid (ITM EPSG:2157) and WGS84 (EPSG:4326).

WHY THIS MATTERS:
Wrong coordinates = rescue teams sent to wrong location.
These tests verify that coordinate transforms are accurate and inputs are validated.

REQUIRES: pytest-qgis (real QGIS runtime for accurate CRS transforms)
"""

import math
import pytest

# These tests require real QGIS runtime
pytest.importorskip("qgis.core")

from qgis.core import QgsApplication, QgsProject
from utils.coordinates import CoordinateConverter


@pytest.fixture(scope="module")
def qgs_app():
    """Initialize QGIS application for tests."""
    # Initialize QGIS application
    qgs = QgsApplication([], False)
    qgs.initQgis()
    yield qgs
    qgs.exitQgis()


@pytest.fixture
def converter(qgs_app):
    """Create a fresh CoordinateConverter for each test."""
    return CoordinateConverter()


# =============================================================================
# INPUT VALIDATION TESTS
# These verify that invalid inputs are rejected with clear errors
# =============================================================================

class TestInputValidation:
    """Test that invalid inputs are rejected before transformation."""

    def test_itm_to_wgs84_with_nan_easting_raises_value_error(self, converter):
        """Reject NaN easting to prevent invalid coordinates."""
        with pytest.raises(ValueError, match="NaN"):
            converter.irish_grid_to_wgs84(float('nan'), 700000)

    def test_itm_to_wgs84_with_nan_northing_raises_value_error(self, converter):
        """Reject NaN northing to prevent invalid coordinates."""
        with pytest.raises(ValueError, match="NaN"):
            converter.irish_grid_to_wgs84(700000, float('nan'))

    def test_itm_to_wgs84_with_inf_easting_raises_value_error(self, converter):
        """Reject Infinity easting to prevent invalid coordinates."""
        with pytest.raises(ValueError, match="Infinity"):
            converter.irish_grid_to_wgs84(float('inf'), 700000)

    def test_itm_to_wgs84_with_inf_northing_raises_value_error(self, converter):
        """Reject Infinity northing to prevent invalid coordinates."""
        with pytest.raises(ValueError, match="Infinity"):
            converter.irish_grid_to_wgs84(700000, float('inf'))

    def test_itm_to_wgs84_with_string_easting_raises_type_error(self, converter):
        """Reject non-numeric easting."""
        with pytest.raises(TypeError, match="expected numeric"):
            converter.irish_grid_to_wgs84("not a number", 700000)

    def test_itm_to_wgs84_with_string_northing_raises_type_error(self, converter):
        """Reject non-numeric northing."""
        with pytest.raises(TypeError, match="expected numeric"):
            converter.irish_grid_to_wgs84(700000, "not a number")

    def test_itm_to_wgs84_with_negative_easting_raises_value_error(self, converter):
        """Reject easting below ITM range."""
        with pytest.raises(ValueError, match="outside valid ITM range"):
            converter.irish_grid_to_wgs84(-1000, 700000)

    def test_itm_to_wgs84_with_excessive_easting_raises_value_error(self, converter):
        """Reject easting above ITM range."""
        with pytest.raises(ValueError, match="outside valid ITM range"):
            converter.irish_grid_to_wgs84(1_100_000, 700000)

    def test_itm_to_wgs84_with_negative_northing_raises_value_error(self, converter):
        """Reject northing below ITM range."""
        with pytest.raises(ValueError, match="outside valid ITM range"):
            converter.irish_grid_to_wgs84(700000, -1000)

    def test_itm_to_wgs84_with_excessive_northing_raises_value_error(self, converter):
        """Reject northing above ITM range."""
        with pytest.raises(ValueError, match="outside valid ITM range"):
            converter.irish_grid_to_wgs84(700000, 1_600_000)

    def test_wgs84_to_itm_with_nan_latitude_raises_value_error(self, converter):
        """Reject NaN latitude to prevent invalid coordinates."""
        with pytest.raises(ValueError, match="NaN"):
            converter.wgs84_to_irish_grid(float('nan'), -8.0)

    def test_wgs84_to_itm_with_nan_longitude_raises_value_error(self, converter):
        """Reject NaN longitude to prevent invalid coordinates."""
        with pytest.raises(ValueError, match="NaN"):
            converter.wgs84_to_irish_grid(53.0, float('nan'))

    def test_wgs84_to_itm_with_inf_latitude_raises_value_error(self, converter):
        """Reject Infinity latitude to prevent invalid coordinates."""
        with pytest.raises(ValueError, match="Infinity"):
            converter.wgs84_to_irish_grid(float('inf'), -8.0)

    def test_wgs84_to_itm_with_inf_longitude_raises_value_error(self, converter):
        """Reject Infinity longitude to prevent invalid coordinates."""
        with pytest.raises(ValueError, match="Infinity"):
            converter.wgs84_to_irish_grid(53.0, float('inf'))

    def test_wgs84_to_itm_with_string_latitude_raises_type_error(self, converter):
        """Reject non-numeric latitude."""
        with pytest.raises(TypeError, match="expected numeric"):
            converter.wgs84_to_irish_grid("not a number", -8.0)

    def test_wgs84_to_itm_with_string_longitude_raises_type_error(self, converter):
        """Reject non-numeric longitude."""
        with pytest.raises(TypeError, match="expected numeric"):
            converter.wgs84_to_irish_grid(53.0, "not a number")

    def test_wgs84_to_itm_with_latitude_below_range_raises_value_error(self, converter):
        """Reject latitude below -90."""
        with pytest.raises(ValueError, match="outside valid range"):
            converter.wgs84_to_irish_grid(-91.0, -8.0)

    def test_wgs84_to_itm_with_latitude_above_range_raises_value_error(self, converter):
        """Reject latitude above 90."""
        with pytest.raises(ValueError, match="outside valid range"):
            converter.wgs84_to_irish_grid(91.0, -8.0)

    def test_wgs84_to_itm_with_longitude_below_range_raises_value_error(self, converter):
        """Reject longitude below -180."""
        with pytest.raises(ValueError, match="outside valid range"):
            converter.wgs84_to_irish_grid(53.0, -181.0)

    def test_wgs84_to_itm_with_longitude_above_range_raises_value_error(self, converter):
        """Reject longitude above 180."""
        with pytest.raises(ValueError, match="outside valid range"):
            converter.wgs84_to_irish_grid(53.0, 181.0)


# =============================================================================
# COORDINATE TRANSFORM ACCURACY TESTS
# These verify that transforms produce correct results with real QGIS CRS
# =============================================================================

class TestTransformAccuracy:
    """Test coordinate transform accuracy with known reference points."""

    # Reference points verified against OSI transform tool
    # https://www.osi.ie/apps/irish-transverse-mercator-itm/
    DUBLIN_GPO = {
        'wgs84': (53.349805, -6.260310),  # O'Connell Street
        'itm': (715830, 734697),
        'tolerance_m': 10  # Allow 10m tolerance for coordinate precision
    }

    KERRY_CARRAUNTOOHIL = {
        'wgs84': (52.003375, -9.691935),  # Ireland's highest peak (verified with QGIS)
        'itm': (483835, 584835),
        'tolerance_m': 10
    }

    GALWAY_CITY = {
        'wgs84': (53.270891, -9.060594),  # Eyre Square (verified with QGIS)
        'itm': (529255, 725031),
        'tolerance_m': 10
    }

    def test_itm_to_wgs84_dublin_gpo_accurate(self, converter):
        """
        CRITICAL: Verify Dublin GPO transforms correctly.

        VALUE: If this fails, all Dublin coordinates will be wrong.
        """
        ref = self.DUBLIN_GPO
        lat, lon = converter.irish_grid_to_wgs84(ref['itm'][0], ref['itm'][1])

        # Calculate error in meters (rough approximation)
        lat_error_m = abs(lat - ref['wgs84'][0]) * 111000  # 1° lat ≈ 111km
        lon_error_m = abs(lon - ref['wgs84'][1]) * 111000 * math.cos(math.radians(lat))

        assert lat_error_m < ref['tolerance_m'], (
            f"Dublin GPO latitude error {lat_error_m:.2f}m exceeds tolerance {ref['tolerance_m']}m. "
            f"Expected {ref['wgs84'][0]:.6f}, got {lat:.6f}"
        )
        assert lon_error_m < ref['tolerance_m'], (
            f"Dublin GPO longitude error {lon_error_m:.2f}m exceeds tolerance {ref['tolerance_m']}m. "
            f"Expected {ref['wgs84'][1]:.6f}, got {lon:.6f}"
        )

    def test_itm_to_wgs84_kerry_mountain_accurate(self, converter):
        """
        CRITICAL: Verify Kerry mountain transforms correctly.

        VALUE: SAR operations happen in Kerry mountains. Wrong coords = lost rescue team.
        """
        ref = self.KERRY_CARRAUNTOOHIL
        lat, lon = converter.irish_grid_to_wgs84(ref['itm'][0], ref['itm'][1])

        lat_error_m = abs(lat - ref['wgs84'][0]) * 111000
        lon_error_m = abs(lon - ref['wgs84'][1]) * 111000 * math.cos(math.radians(lat))

        assert lat_error_m < ref['tolerance_m'], (
            f"Carrauntoohil latitude error {lat_error_m:.2f}m exceeds tolerance. "
            f"Expected {ref['wgs84'][0]:.6f}, got {lat:.6f}"
        )
        assert lon_error_m < ref['tolerance_m'], (
            f"Carrauntoohil longitude error {lon_error_m:.2f}m exceeds tolerance. "
            f"Expected {ref['wgs84'][1]:.6f}, got {lon:.6f}"
        )

    def test_itm_to_wgs84_galway_city_accurate(self, converter):
        """
        CRITICAL: Verify Galway city transforms correctly.

        VALUE: Western Ireland reference point validation.
        """
        ref = self.GALWAY_CITY
        lat, lon = converter.irish_grid_to_wgs84(ref['itm'][0], ref['itm'][1])

        lat_error_m = abs(lat - ref['wgs84'][0]) * 111000
        lon_error_m = abs(lon - ref['wgs84'][1]) * 111000 * math.cos(math.radians(lat))

        assert lat_error_m < ref['tolerance_m'], (
            f"Galway latitude error {lat_error_m:.2f}m exceeds tolerance. "
            f"Expected {ref['wgs84'][0]:.6f}, got {lat:.6f}"
        )
        assert lon_error_m < ref['tolerance_m'], (
            f"Galway longitude error {lon_error_m:.2f}m exceeds tolerance. "
            f"Expected {ref['wgs84'][1]:.6f}, got {lon:.6f}"
        )

    def test_wgs84_to_itm_dublin_gpo_accurate(self, converter):
        """
        CRITICAL: Verify reverse transform for Dublin.

        VALUE: User inputs lat/lon, must convert to ITM correctly.
        """
        ref = self.DUBLIN_GPO
        easting, northing = converter.wgs84_to_irish_grid(
            ref['wgs84'][0], ref['wgs84'][1]
        )

        easting_error_m = abs(easting - ref['itm'][0])
        northing_error_m = abs(northing - ref['itm'][1])

        assert easting_error_m < ref['tolerance_m'], (
            f"Dublin GPO easting error {easting_error_m:.2f}m exceeds tolerance. "
            f"Expected {ref['itm'][0]:.0f}, got {easting:.0f}"
        )
        assert northing_error_m < ref['tolerance_m'], (
            f"Dublin GPO northing error {northing_error_m:.2f}m exceeds tolerance. "
            f"Expected {ref['itm'][1]:.0f}, got {northing:.0f}"
        )

    def test_wgs84_to_itm_kerry_mountain_accurate(self, converter):
        """
        CRITICAL: Verify reverse transform for Kerry.

        VALUE: Operators input search area coords in lat/lon.
        """
        ref = self.KERRY_CARRAUNTOOHIL
        easting, northing = converter.wgs84_to_irish_grid(
            ref['wgs84'][0], ref['wgs84'][1]
        )

        easting_error_m = abs(easting - ref['itm'][0])
        northing_error_m = abs(northing - ref['itm'][1])

        assert easting_error_m < ref['tolerance_m'], (
            f"Carrauntoohil easting error {easting_error_m:.2f}m exceeds tolerance. "
            f"Expected {ref['itm'][0]:.0f}, got {easting:.0f}"
        )
        assert northing_error_m < ref['tolerance_m'], (
            f"Carrauntoohil northing error {northing_error_m:.2f}m exceeds tolerance. "
            f"Expected {ref['itm'][1]:.0f}, got {northing:.0f}"
        )

    def test_round_trip_dublin_preserves_coordinates(self, converter):
        """
        CRITICAL: Verify round-trip conversion accuracy.

        VALUE: Multiple conversions should not accumulate errors.
        lat/lon → ITM → lat/lon should return to original.
        """
        original_lat, original_lon = self.DUBLIN_GPO['wgs84']

        # Forward: WGS84 → ITM
        easting, northing = converter.wgs84_to_irish_grid(original_lat, original_lon)

        # Reverse: ITM → WGS84
        result_lat, result_lon = converter.irish_grid_to_wgs84(easting, northing)

        # Check we're back to original within tolerance
        lat_error_m = abs(result_lat - original_lat) * 111000
        lon_error_m = abs(result_lon - original_lon) * 111000 * math.cos(math.radians(original_lat))

        tolerance_m = self.DUBLIN_GPO['tolerance_m']
        assert lat_error_m < tolerance_m, (
            f"Round-trip latitude error {lat_error_m:.2f}m exceeds tolerance. "
            f"Started {original_lat:.6f}, ended {result_lat:.6f}"
        )
        assert lon_error_m < tolerance_m, (
            f"Round-trip longitude error {lon_error_m:.2f}m exceeds tolerance. "
            f"Started {original_lon:.6f}, ended {result_lon:.6f}"
        )

    def test_round_trip_kerry_preserves_coordinates(self, converter):
        """
        CRITICAL: Verify round-trip conversion for Kerry mountains.

        VALUE: Operations in rough terrain require precise coordinates.
        """
        original_lat, original_lon = self.KERRY_CARRAUNTOOHIL['wgs84']

        easting, northing = converter.wgs84_to_irish_grid(original_lat, original_lon)
        result_lat, result_lon = converter.irish_grid_to_wgs84(easting, northing)

        lat_error_m = abs(result_lat - original_lat) * 111000
        lon_error_m = abs(result_lon - original_lon) * 111000 * math.cos(math.radians(original_lat))

        tolerance_m = self.KERRY_CARRAUNTOOHIL['tolerance_m']
        assert lat_error_m < tolerance_m, (
            f"Round-trip latitude error {lat_error_m:.2f}m exceeds tolerance"
        )
        assert lon_error_m < tolerance_m, (
            f"Round-trip longitude error {lon_error_m:.2f}m exceeds tolerance"
        )


# =============================================================================
# SAFETY TESTS
# These verify boundary conditions and prevent common coordinate errors
# =============================================================================

class TestSafetyChecks:
    """Test boundary conditions and safety checks."""

    def test_null_island_rejected_as_invalid_for_ireland(self, converter):
        """
        CRITICAL: Reject Null Island (0,0) which indicates GPS failure.

        VALUE: (0,0) is off the coast of Africa, not Ireland.
        This often indicates uninitialized or failed GPS.
        """
        # Null Island is way outside Ireland's ITM range
        # When converted to ITM, it should fail range validation
        with pytest.raises(ValueError, match="outside valid ITM range"):
            converter.wgs84_to_irish_grid(0.0, 0.0)

    def test_ireland_northern_boundary_accepted(self, converter):
        """Verify coordinates near Northern Ireland border work."""
        # Malin Head - Ireland's most northerly point
        lat, lon = 55.3783, -7.3660
        easting, northing = converter.wgs84_to_irish_grid(lat, lon)

        # Should succeed without error
        assert 0 <= easting <= 1_000_000
        assert 0 <= northing <= 1_500_000

    def test_ireland_southern_boundary_accepted(self, converter):
        """Verify coordinates near southern coast work."""
        # Mizen Head - Ireland's most southerly point
        lat, lon = 51.4494, -9.8161
        easting, northing = converter.wgs84_to_irish_grid(lat, lon)

        # Should succeed without error
        assert 0 <= easting <= 1_000_000
        assert 0 <= northing <= 1_500_000

    def test_ireland_eastern_boundary_accepted(self, converter):
        """Verify coordinates near eastern coast work."""
        # Wicklow Head - eastern point
        lat, lon = 52.9781, -5.9944
        easting, northing = converter.wgs84_to_irish_grid(lat, lon)

        # Should succeed without error
        assert 0 <= easting <= 1_000_000
        assert 0 <= northing <= 1_500_000

    def test_ireland_western_boundary_accepted(self, converter):
        """Verify coordinates near western coast work."""
        # Dunmore Head - Ireland's most westerly point
        lat, lon = 52.1086, -10.4783
        easting, northing = converter.wgs84_to_irish_grid(lat, lon)

        # Should succeed without error
        assert 0 <= easting <= 1_000_000
        assert 0 <= northing <= 1_500_000

    def test_coordinates_far_from_ireland_fail_range_check(self, converter):
        """
        CRITICAL: Reject coordinates nowhere near Ireland.

        VALUE: Prevents sending teams to wrong country.
        """
        # London coordinates - should fail ITM range check
        lat, lon = 51.5074, -0.1278
        with pytest.raises(ValueError, match="outside valid ITM range"):
            converter.wgs84_to_irish_grid(lat, lon)


# =============================================================================
# FORMATTING TESTS
# These verify coordinate formatting for display to users
# =============================================================================

class TestFormatting:
    """Test coordinate formatting methods."""

    def test_format_irish_grid_returns_correct_string(self, converter):
        """Verify ITM coordinate formatting."""
        result = converter.format_irish_grid(715830, 734697)
        assert result == "E: 715830  N: 734697"

    def test_format_irish_grid_reference_returns_expected(self):
        """Verify TM65 Irish Grid reference formatting."""
        from utils.coordinates import format_irish_grid_reference
        result = format_irish_grid_reference(99840, 104018)
        assert result == "Q 99840 04018"

    def test_format_irish_grid_reference_out_of_range_raises_value_error(self):
        """Reject TM65 grid references outside valid range."""
        from utils.coordinates import format_irish_grid_reference
        with pytest.raises(ValueError, match="TM65"):
            format_irish_grid_reference(-10, 1000)

    def test_format_wgs84_north_east_returns_correct_string(self, converter):
        """Verify WGS84 formatting for northern hemisphere, eastern longitude."""
        result = converter.format_wgs84(53.3498, 6.2603)
        assert result == "53.3498N, 6.2603E"

    def test_format_wgs84_north_west_returns_correct_string(self, converter):
        """Verify WGS84 formatting for Ireland (N/W)."""
        result = converter.format_wgs84(53.3498, -6.2603)
        assert result == "53.3498N, 6.2603W"

    def test_format_wgs84_south_west_returns_correct_string(self, converter):
        """Verify WGS84 formatting for southern hemisphere, western longitude."""
        result = converter.format_wgs84(-33.8688, -151.2093)
        assert result == "33.8688S, 151.2093W"

    def test_format_irish_grid_with_nan_raises_value_error(self, converter):
        """Reject formatting NaN coordinates."""
        with pytest.raises(ValueError, match="NaN"):
            converter.format_irish_grid(float('nan'), 700000)

    def test_format_wgs84_with_inf_raises_value_error(self, converter):
        """Reject formatting Infinity coordinates."""
        with pytest.raises(ValueError, match="Infinity"):
            converter.format_wgs84(53.0, float('inf'))


# =============================================================================
# CRS INITIALIZATION TESTS
# Verify QGIS coordinate systems initialize correctly
# =============================================================================

class TestCRSInitialization:
    """Test that CRS objects initialize correctly."""

    def test_wgs84_crs_is_valid(self, converter):
        """Verify WGS84 CRS initializes."""
        assert converter.wgs84.isValid()
        assert converter.wgs84.authid() == "EPSG:4326"

    def test_itm_crs_is_valid(self, converter):
        """Verify ITM CRS initializes."""
        assert converter.itm.isValid()
        assert converter.itm.authid() == "EPSG:2157"

    def test_transform_itm_to_wgs84_is_valid(self, converter):
        """Verify transform object is valid."""
        from qgis.core import QgsCoordinateTransform, QgsProject

        transform = QgsCoordinateTransform(
            converter.itm,
            converter.wgs84,
            QgsProject.instance()
        )
        assert transform.isValid()

    def test_transform_wgs84_to_itm_is_valid(self, converter):
        """Verify reverse transform object is valid."""
        from qgis.core import QgsCoordinateTransform, QgsProject

        transform = QgsCoordinateTransform(
            converter.wgs84,
            converter.itm,
            QgsProject.instance()
        )
        assert transform.isValid()
