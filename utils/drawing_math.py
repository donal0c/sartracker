# -*- coding: utf-8 -*-
"""
Geodesic helpers for drawing operations.

These are pure-Python math utilities (no QGIS imports) to allow regression testing
outside a QGIS runtime. They return plain (lon, lat) tuples.
"""

import math
from typing import List, Tuple


def calculate_sector_arc_length(start_bearing: float, end_bearing: float) -> float:
    """
    Calculate the clockwise arc length between two bearings.

    CRITICAL FOR SAR OPERATIONS: This calculation determines search area size.
    The arc always goes CLOCKWISE from start to end.

    This is the single source of truth for arc length calculation, used by both
    sector_tool.py and drawing_manager.py to ensure consistency.

    Args:
        start_bearing: Start bearing in degrees (0 = North, can be any value)
        end_bearing: End bearing in degrees (can be any value)

    Returns:
        float: Arc length in degrees (0 to 360)

    Raises:
        ValueError: If calculated arc length is invalid

    Examples:
        >>> calculate_sector_arc_length(10, 350)
        340.0
        >>> calculate_sector_arc_length(350, 10)
        20.0
        >>> calculate_sector_arc_length(0, 360)
        360.0
        >>> calculate_sector_arc_length(45, 45)
        0.0
    """
    # Normalize angles to [0, 360)
    start = start_bearing % 360
    end = end_bearing % 360

    # CRITICAL BUG FIX (BUG-034): Handle full circle case
    # If both angles are the same after normalization, check if the original
    # end_bearing indicates a full circle
    if start == end:
        # If end_bearing was originally ≥ 360 or significantly different from start,
        # treat as full circle
        angle_diff = abs(end_bearing - start_bearing)
        if angle_diff >= 360 or (angle_diff > 180 and angle_diff < 360):
            return 360.0
        else:
            # True zero-arc case (degenerate)
            return 0.0

    # Standard case: calculate clockwise arc
    # If end < start (e.g., 350° to 10°), add 360 to end to get clockwise arc
    if end < start:
        end += 360

    arc_length = end - start

    # Safety check: arc_length should be in (0, 360]
    if arc_length < 0 or arc_length > 360:
        raise ValueError(f"Invalid arc length calculated: {arc_length}° (start={start_bearing}°, end={end_bearing}°)")

    return arc_length


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


def geodesic_bearing(origin_lon: float, origin_lat: float, dest_lon: float, dest_lat: float) -> float:
    """
    Calculate the initial geodesic bearing from origin to destination.

    Uses the spherical trigonometry formula for forward azimuth, which provides
    accuracy better than 0.1° for distances under 100km at mid-latitudes.

    For SAR operations, this accuracy is sufficient. For distances > 100km or
    near-polar regions, consider using QgsDistanceArea.bearing() directly.

    Args:
        origin_lon: Origin longitude in degrees
        origin_lat: Origin latitude in degrees
        dest_lon: Destination longitude in degrees
        dest_lat: Destination latitude in degrees

    Returns:
        float: Initial bearing in degrees (0-360, where 0 = North)

    Example:
        >>> geodesic_bearing(0.0, 52.0, 1.0, 53.0)  # ~0-45 degrees
    """
    # Convert to radians
    lat1 = math.radians(origin_lat)
    lat2 = math.radians(dest_lat)
    lon1 = math.radians(origin_lon)
    lon2 = math.radians(dest_lon)

    dlon = lon2 - lon1

    # Spherical formula for forward azimuth
    # This is more accurate than planar, sufficient for SAR operations
    x = math.sin(dlon) * math.cos(lat2)
    y = (math.cos(lat1) * math.sin(lat2) -
         math.sin(lat1) * math.cos(lat2) * math.cos(dlon))

    bearing_rad = math.atan2(x, y)
    bearing_deg = math.degrees(bearing_rad)

    # Normalize to [0, 360)
    return (bearing_deg + 360.0) % 360.0


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
