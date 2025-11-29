# -*- coding: utf-8 -*-
import math

import pytest

from utils import drawing_math as dm


def test_geodesic_circle_points_count_and_radius():
    center_lon, center_lat = 0.0, 0.0
    radius_m = 1000.0
    pts = dm.geodesic_circle_points(center_lon, center_lat, radius_m, segments=8)
    assert len(pts) == 9  # segments + 1 closure

    # First point should be due north with small latitude delta
    lon0, lat0 = pts[0]
    assert lon0 == pytest.approx(0.0, abs=1e-4)
    # Expected ~ radius / earth_radius in radians -> degrees
    expected_delta_deg = math.degrees(radius_m / 6378137.0)
    assert lat0 == pytest.approx(expected_delta_deg, rel=0.05)


def test_geodesic_bearing_endpoint_basic():
    lon, lat = dm.geodesic_bearing_endpoint(0.0, 0.0, 0.0, 1000.0)
    assert lon == pytest.approx(0.0, abs=1e-4)
    assert lat > 0
    lon2, lat2 = dm.geodesic_bearing_endpoint(0.0, 0.0, 90.0, 1000.0)
    assert lat2 == pytest.approx(0.0, abs=1e-4)
    assert lon2 > 0


def test_geodesic_sector_points_structure():
    pts = dm.geodesic_sector_points(0.0, 0.0, 0.0, 90.0, 500.0, num_segments=4)
    # center + 5 arc points + center
    assert len(pts) == 6 + 1  # center + segments+1 + center
    assert pts[0] == (0.0, 0.0)
    assert pts[-1] == (0.0, 0.0)
    # first arc point should be north-ish
    assert pts[1][1] > 0


def test_calculate_sector_arc_length_standard():
    """Test standard clockwise arc length calculations."""
    # 10° to 350° clockwise = 340°
    assert dm.calculate_sector_arc_length(10, 350) == pytest.approx(340.0)

    # 350° to 10° clockwise = 20°
    assert dm.calculate_sector_arc_length(350, 10) == pytest.approx(20.0)

    # 0° to 180° = 180°
    assert dm.calculate_sector_arc_length(0, 180) == pytest.approx(180.0)

    # 45° to 135° = 90°
    assert dm.calculate_sector_arc_length(45, 135) == pytest.approx(90.0)


def test_calculate_sector_arc_length_edge_cases():
    """Test edge cases: full circle and zero arc."""
    # Full circle: 0° to 360° = 360°
    assert dm.calculate_sector_arc_length(0, 360) == pytest.approx(360.0)

    # Full circle: 45° to 405° = 360°
    assert dm.calculate_sector_arc_length(45, 405) == pytest.approx(360.0)

    # Zero arc: same angle
    assert dm.calculate_sector_arc_length(45, 45) == pytest.approx(0.0)
    assert dm.calculate_sector_arc_length(0, 0) == pytest.approx(0.0)


def test_calculate_sector_arc_length_normalization():
    """Test that angles outside [0, 360) are normalized correctly."""
    # 370° normalizes to 10°
    assert dm.calculate_sector_arc_length(10, 370) == pytest.approx(0.0)  # Same angle

    # Large angles
    assert dm.calculate_sector_arc_length(10, 730) == pytest.approx(0.0)  # 730 % 360 = 10

    # Negative angles
    assert dm.calculate_sector_arc_length(-10, 350) == pytest.approx(0.0)  # -10 % 360 = 350


def test_geodesic_bearing_cardinal_directions():
    """Test bearing calculations for cardinal directions."""
    # North: lat increases
    bearing = dm.geodesic_bearing(0.0, 0.0, 0.0, 1.0)
    assert bearing == pytest.approx(0.0, abs=0.1)

    # East: lon increases at equator
    bearing = dm.geodesic_bearing(0.0, 0.0, 1.0, 0.0)
    assert bearing == pytest.approx(90.0, abs=0.1)

    # South: lat decreases
    bearing = dm.geodesic_bearing(0.0, 1.0, 0.0, 0.0)
    assert bearing == pytest.approx(180.0, abs=0.1)

    # West: lon decreases at equator
    bearing = dm.geodesic_bearing(1.0, 0.0, 0.0, 0.0)
    assert bearing == pytest.approx(270.0, abs=0.1)


def test_geodesic_bearing_realistic():
    """Test bearing calculation for realistic SAR scenario (Ireland)."""
    # Kerry to Cork: approximately 53° bearing
    kerry_lon, kerry_lat = -9.7, 52.27
    cork_lon, cork_lat = -8.47, 51.90

    bearing = dm.geodesic_bearing(kerry_lon, kerry_lat, cork_lon, cork_lat)
    # Should be roughly southeast (90° to 180°)
    assert 90 < bearing < 180

    # Reverse direction should be roughly opposite (±180°)
    reverse_bearing = dm.geodesic_bearing(cork_lon, cork_lat, kerry_lon, kerry_lat)
    diff = abs(reverse_bearing - bearing)
    assert 170 < diff < 190  # Approximately opposite direction
