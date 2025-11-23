# -*- coding: utf-8 -*-
"""
Drawing validation helpers.

Pure-Python utilities (no QGIS imports) so they can be unit tested without a QGIS
runtime. These functions validate basic geometry parameters to keep downstream
layer operations safer.
"""

from typing import Iterable, Tuple, Any, Sequence
import re


HEX_COLOR_RE = re.compile(r"^#(?:[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")


def _extract_lon_lat(point: Any) -> Tuple[float, float]:
    """
    Extract lon/lat from a QgsPointXY-like object or a (lon, lat) pair.

    Returns:
        (lon, lat) as floats
    """
    # QgsPointXY exposes callable x()/y()
    if hasattr(point, "x") and hasattr(point, "y"):
        x = point.x() if callable(point.x) else point.x
        y = point.y() if callable(point.y) else point.y
        return float(x), float(y)

    # Sequence of length 2: assume (lon, lat)
    if isinstance(point, Sequence) and len(point) == 2:
        return float(point[0]), float(point[1])

    raise ValueError("Invalid point: expected QgsPointXY-like or (lon, lat) pair")


def validate_point(point: Any, name: str = "point") -> Tuple[float, float]:
    """
    Validate a single point is numeric and within WGS84 bounds.

    Args:
        point: QgsPointXY-like (x/y) or (lon, lat) tuple
        name: Context name for error messages
    """
    lon, lat = _extract_lon_lat(point)

    if not (-180.0 <= lon <= 180.0):
        raise ValueError(f"{name}: longitude must be between -180 and 180 (got {lon})")
    if not (-90.0 <= lat <= 90.0):
        raise ValueError(f"{name}: latitude must be between -90 and 90 (got {lat})")

    return lon, lat


def validate_point_sequence(points: Iterable[Any], min_points: int, name: str) -> None:
    """
    Validate a sequence of points.

    Args:
        points: iterable of QgsPointXY-like or (lon, lat) tuples
        min_points: minimum required number of points
        name: context name for error messages
    """
    if not isinstance(points, Iterable):
        raise ValueError(f"{name}: must be an iterable of points")

    count = 0
    for idx, point in enumerate(points):
        validate_point(point, f"{name}[{idx}]")
        count += 1

    if count < min_points:
        raise ValueError(f"{name}: requires at least {min_points} point(s), got {count}")


def validate_positive_number(value: Any, field_name: str) -> float:
    """Ensure value is a positive float."""
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{field_name} must be a number (got {value!r})")

    if numeric <= 0:
        raise ValueError(f"{field_name} must be greater than zero (got {numeric})")
    return numeric


def validate_bearing(value: Any, field_name: str = "bearing") -> float:
    """Ensure bearing is between 0 and 360 inclusive."""
    try:
        bearing = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{field_name} must be a number (got {value!r})")

    if not (0.0 <= bearing <= 360.0):
        raise ValueError(f"{field_name} must be between 0 and 360 degrees (got {bearing})")
    return bearing


def validate_color_hex(color: Any, field_name: str = "color") -> str:
    """
    Ensure color is a hex string (#RRGGBB or #RRGGBBAA).
    """
    if not isinstance(color, str):
        raise ValueError(f"{field_name} must be a hex string (got {color!r})")
    if not HEX_COLOR_RE.match(color):
        raise ValueError(f"{field_name} must be in #RRGGBB or #RRGGBBAA format (got {color})")
    return color


def validate_font_size(size: Any, field_name: str = "font_size") -> int:
    """Ensure font size is a positive integer."""
    try:
        as_int = int(size)
    except (TypeError, ValueError):
        raise ValueError(f"{field_name} must be an integer (got {size!r})")
    if as_int <= 0:
        raise ValueError(f"{field_name} must be greater than zero (got {as_int})")
    return as_int


def validate_width(width: Any, field_name: str = "width") -> int:
    """Ensure line width is a positive integer."""
    try:
        as_int = int(width)
    except (TypeError, ValueError):
        raise ValueError(f"{field_name} must be an integer (got {width!r})")
    if as_int <= 0:
        raise ValueError(f"{field_name} must be greater than zero (got {as_int})")
    return as_int
