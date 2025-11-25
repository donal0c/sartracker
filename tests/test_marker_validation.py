# -*- coding: utf-8 -*-
"""
Tests for Marker Validation Utilities (Phase 5 Refactor).

Tests coordinate and marker validation logic for life-safety critical operations.
"""
import pytest

from sartracker.utils.marker_validation import (
    is_number,
    validate_latitude,
    validate_longitude,
    validate_latlon,
    validate_marker_name,
    validate_marker_type,
    extract_marker_coordinates,
    build_marker_update_payload,
    validate_marker_id,
    VALID_MARKER_TYPES,
)


class TestIsNumber:
    """Tests for is_number utility."""

    def test_int_is_number(self):
        assert is_number(42) is True
        assert is_number(-10) is True
        assert is_number(0) is True

    def test_float_is_number(self):
        assert is_number(3.14) is True
        assert is_number(-273.15) is True
        assert is_number(0.0) is True

    def test_numeric_string_is_number(self):
        assert is_number("42") is True
        assert is_number("-3.14") is True
        assert is_number("0") is True

    def test_none_is_not_number(self):
        assert is_number(None) is False

    def test_bool_is_not_number(self):
        """Booleans should not be treated as numbers for safety."""
        assert is_number(True) is False
        assert is_number(False) is False

    def test_invalid_string_is_not_number(self):
        assert is_number("abc") is False
        assert is_number("") is False
        assert is_number("12.34.56") is False


class TestValidateLatitude:
    """Tests for validate_latitude."""

    def test_valid_latitudes(self):
        assert validate_latitude(0.0) == 0.0
        assert validate_latitude(45.5) == 45.5
        assert validate_latitude(-45.5) == -45.5
        assert validate_latitude(90.0) == 90.0
        assert validate_latitude(-90.0) == -90.0

    def test_string_latitude_converted(self):
        assert validate_latitude("52.2345") == pytest.approx(52.2345)

    def test_invalid_latitude_too_high(self):
        with pytest.raises(ValueError, match="must be between"):
            validate_latitude(91.0)

    def test_invalid_latitude_too_low(self):
        with pytest.raises(ValueError, match="must be between"):
            validate_latitude(-91.0)

    def test_non_numeric_latitude(self):
        with pytest.raises(ValueError, match="must be a number"):
            validate_latitude("not a number")

    def test_none_latitude(self):
        with pytest.raises(ValueError, match="must be a number"):
            validate_latitude(None)


class TestValidateLongitude:
    """Tests for validate_longitude."""

    def test_valid_longitudes(self):
        assert validate_longitude(0.0) == 0.0
        assert validate_longitude(90.0) == 90.0
        assert validate_longitude(-90.0) == -90.0
        assert validate_longitude(180.0) == 180.0
        assert validate_longitude(-180.0) == -180.0

    def test_string_longitude_converted(self):
        assert validate_longitude("-9.1234") == pytest.approx(-9.1234)

    def test_invalid_longitude_too_high(self):
        with pytest.raises(ValueError, match="must be between"):
            validate_longitude(181.0)

    def test_invalid_longitude_too_low(self):
        with pytest.raises(ValueError, match="must be between"):
            validate_longitude(-181.0)


class TestValidateLatLon:
    """Tests for validate_latlon."""

    def test_valid_coordinates(self):
        lat, lon = validate_latlon(52.2345, -9.1234)
        assert lat == pytest.approx(52.2345)
        assert lon == pytest.approx(-9.1234)

    def test_invalid_lat_raises(self):
        with pytest.raises(ValueError, match="latitude"):
            validate_latlon(999, 0)

    def test_invalid_lon_raises(self):
        with pytest.raises(ValueError, match="longitude"):
            validate_latlon(0, 999)


class TestValidateMarkerName:
    """Tests for validate_marker_name."""

    def test_valid_name(self):
        assert validate_marker_name("Search Base 1") == "Search Base 1"

    def test_name_stripped(self):
        assert validate_marker_name("  Test  ") == "Test"

    def test_empty_name_raises(self):
        with pytest.raises(ValueError, match="cannot be empty"):
            validate_marker_name("")

    def test_whitespace_only_raises(self):
        with pytest.raises(ValueError, match="cannot be empty"):
            validate_marker_name("   ")

    def test_none_name_raises(self):
        with pytest.raises(ValueError, match="cannot be None"):
            validate_marker_name(None)

    def test_too_long_name_raises(self):
        with pytest.raises(ValueError, match="too long"):
            validate_marker_name("x" * 300)

    def test_non_string_converted(self):
        assert validate_marker_name(123) == "123"


class TestValidateMarkerType:
    """Tests for validate_marker_type."""

    def test_valid_types(self):
        for valid_type in VALID_MARKER_TYPES:
            assert validate_marker_type(valid_type) == valid_type

    def test_case_insensitive(self):
        assert validate_marker_type("IPP_LKP") == "ipp_lkp"
        assert validate_marker_type("Clue") == "clue"

    def test_invalid_type_raises(self):
        with pytest.raises(ValueError, match="Invalid marker type"):
            validate_marker_type("unknown_type")

    def test_none_type_raises(self):
        with pytest.raises(ValueError, match="cannot be None"):
            validate_marker_type(None)


class TestExtractMarkerCoordinates:
    """Tests for extract_marker_coordinates."""

    def test_lat_lon_fields(self):
        data = {'lat': 52.0, 'lon': -9.0, 'name': 'Test'}
        lat, lon = extract_marker_coordinates(data)
        assert lat == 52.0
        assert lon == -9.0

    def test_latitude_longitude_fields(self):
        data = {'latitude': 52.0, 'longitude': -9.0}
        lat, lon = extract_marker_coordinates(data)
        assert lat == 52.0
        assert lon == -9.0

    def test_x_y_fields(self):
        data = {'x': -9.0, 'y': 52.0}
        lat, lon = extract_marker_coordinates(data)
        assert lat == 52.0
        assert lon == -9.0

    def test_missing_coordinates_raises(self):
        with pytest.raises(ValueError, match="missing coordinates"):
            extract_marker_coordinates({'name': 'Test'})

    def test_empty_data_raises(self):
        with pytest.raises(ValueError, match="cannot be empty"):
            extract_marker_coordinates({})

    def test_none_data_raises(self):
        with pytest.raises(ValueError, match="cannot be empty"):
            extract_marker_coordinates(None)


class TestBuildMarkerUpdatePayload:
    """Tests for build_marker_update_payload."""

    def test_basic_payload(self):
        payload = build_marker_update_payload(
            name="Test Marker",
            lat=52.0,
            lon=-9.0,
            marker_type="clue"
        )
        assert payload['name'] == "Test Marker"
        assert payload['lat'] == 52.0
        assert payload['lon'] == -9.0
        assert payload['marker_type'] == "clue"

    def test_with_description(self):
        payload = build_marker_update_payload(
            name="Test",
            lat=52.0,
            lon=-9.0,
            marker_type="poi",
            description="Found item"
        )
        assert payload['description'] == "Found item"

    def test_with_attachment(self):
        payload = build_marker_update_payload(
            name="Test",
            lat=52.0,
            lon=-9.0,
            marker_type="poi",
            attachment_path="/path/to/photo.jpg"
        )
        assert payload['attachment_path'] == "/path/to/photo.jpg"

    def test_description_truncated(self):
        long_desc = "x" * 3000
        payload = build_marker_update_payload(
            name="Test",
            lat=52.0,
            lon=-9.0,
            marker_type="poi",
            description=long_desc
        )
        assert len(payload['description']) == 2000

    def test_invalid_name_raises(self):
        with pytest.raises(ValueError, match="empty"):
            build_marker_update_payload("", 52.0, -9.0, "poi")

    def test_invalid_coordinates_raises(self):
        with pytest.raises(ValueError, match="latitude"):
            build_marker_update_payload("Test", 999.0, -9.0, "poi")


class TestValidateMarkerId:
    """Tests for validate_marker_id."""

    def test_valid_id(self):
        assert validate_marker_id(1) == 1
        assert validate_marker_id(0) == 0
        assert validate_marker_id(12345) == 12345

    def test_string_id_converted(self):
        assert validate_marker_id("42") == 42

    def test_none_id_raises(self):
        with pytest.raises(ValueError, match="cannot be None"):
            validate_marker_id(None)

    def test_negative_id_raises(self):
        with pytest.raises(ValueError, match="cannot be negative"):
            validate_marker_id(-1)

    def test_non_integer_raises(self):
        with pytest.raises(ValueError, match="must be an integer"):
            validate_marker_id("abc")
