# -*- coding: utf-8 -*-
"""
Geodesic helpers for drawing operations.

These are pure-Python math utilities (no QGIS imports) to allow regression testing
outside a QGIS runtime. They return plain (lon, lat) tuples.
"""

import math
from typing import List, Tuple


def _earth_radius_at_lat(lat_rad: float) -> float:
    """
    Compute Earth radius at a given latitude using WGS84 ellipsoid.
    """
    a = 6378137.0  # semi-major axis
    f = 1 / 298.257223563
    b = a * (1 - f)  # semi-minor axis

    cos_lat = math.cos(lat_rad)
    sin_lat = math.sin(lat_rad)

    numerator = (a * a * cos_lat) ** 2 + (b * b * sin_lat) ** 2
    denominator = (a * cos_lat) ** 2 + (b * sin_lat) ** 2

    if denominator < 1e-10:
        return b

    return math.sqrt(numerator / denominator)


def geodesic_circle_points(center_lon: float, center_lat: float, radius_m: float, segments: int = 64) -> List[Tuple[float, float]]:
    """
    Generate geodesic circle points around a center.
    """
    lat_rad = math.radians(center_lat)
    earth_radius = _earth_radius_at_lat(lat_rad)
    angular_distance = radius_m / earth_radius

    points: List[Tuple[float, float]] = []
    for i in range(segments + 1):
        bearing = (360.0 * i) / segments
        bearing_rad = math.radians(bearing)
        lon_rad = math.radians(center_lon)

        sin_lat2 = (
            math.sin(lat_rad) * math.cos(angular_distance) +
            math.cos(lat_rad) * math.sin(angular_distance) * math.cos(bearing_rad)
        )
        sin_lat2 = max(-1.0, min(1.0, sin_lat2))
        lat2 = math.asin(sin_lat2)

        lon2 = lon_rad + math.atan2(
            math.sin(bearing_rad) * math.sin(angular_distance) * math.cos(lat_rad),
            math.cos(angular_distance) - math.sin(lat_rad) * math.sin(lat2)
        )

        points.append((math.degrees(lon2), math.degrees(lat2)))

    return points


def geodesic_bearing_endpoint(origin_lon: float, origin_lat: float, bearing: float, distance_m: float) -> Tuple[float, float]:
    """
    Compute the endpoint from an origin, bearing, and distance using WGS84.
    """
    bearing_rad = math.radians(bearing)
    lat1 = math.radians(origin_lat)
    lon1 = math.radians(origin_lon)

    earth_radius = _earth_radius_at_lat(lat1)
    angular_dist = distance_m / earth_radius

    sin_lat2 = (
        math.sin(lat1) * math.cos(angular_dist) +
        math.cos(lat1) * math.sin(angular_dist) * math.cos(bearing_rad)
    )
    sin_lat2 = max(-1.0, min(1.0, sin_lat2))
    lat2 = math.asin(sin_lat2)

    lon2 = lon1 + math.atan2(
        math.sin(bearing_rad) * math.sin(angular_dist) * math.cos(lat1),
        math.cos(angular_dist) - math.sin(lat1) * math.sin(lat2)
    )

    return math.degrees(lon2), math.degrees(lat2)


def geodesic_sector_points(center_lon: float, center_lat: float, start_bearing: float, end_bearing: float, radius_m: float, num_segments: int = 36) -> List[Tuple[float, float]]:
    """
    Generate sector (wedge) points starting at center, sweeping bearings, and closing to center.
    """
    angle_range = end_bearing - start_bearing
    if angle_range < 0:
        angle_range += 360

    lat1 = math.radians(center_lat)
    lon1 = math.radians(center_lon)
    earth_radius = _earth_radius_at_lat(lat1)
    angular_dist = radius_m / earth_radius

    points: List[Tuple[float, float]] = [(center_lon, center_lat)]
    for i in range(num_segments + 1):
        angle = start_bearing + (angle_range * i / num_segments)
        angle_rad = math.radians(angle)

        sin_lat2 = (
            math.sin(lat1) * math.cos(angular_dist) +
            math.cos(lat1) * math.sin(angular_dist) * math.cos(angle_rad)
        )
        sin_lat2 = max(-1.0, min(1.0, sin_lat2))
        lat2 = math.asin(sin_lat2)

        lon2 = lon1 + math.atan2(
            math.sin(angle_rad) * math.sin(angular_dist) * math.cos(lat1),
            math.cos(angular_dist) - math.sin(lat1) * math.sin(lat2)
        )

        points.append((math.degrees(lon2), math.degrees(lat2)))

    points.append((center_lon, center_lat))
    return points
