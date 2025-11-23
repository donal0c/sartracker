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
