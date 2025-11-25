# -*- coding: utf-8 -*-
"""
Marker Validation Utilities (Phase 5 Refactor).

Centralizes coordinate and marker validation to ensure all marker operations
use consistent validation logic.

LIFE-SAFETY CRITICAL: Invalid coordinates can endanger rescuers. All marker
coordinates must be validated before use.

Pure-Python utilities (no QGIS imports) for testability.
"""
from typing import Any, Optional, Dict, Tuple
from .drawing_validation import validate_point, validate_positive_number


# Valid marker types for SAR operations
VALID_MARKER_TYPES = frozenset([
    'ipp_lkp',      # Initial Planning Point / Last Known Position
    'clue',         # Clue marker
    'hazard',       # Hazard marker
    'casualty',     # Casualty location
    'poi',          # Point of Interest
])


def is_number(value: Any) -> bool:
    """
    Check if value is a valid number (int or float).

    Args:
        value: Any value to check

    Returns:
        True if value is numeric, False otherwise
    """
    if value is None:
        return False
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        return True
    if isinstance(value, str):
        try:
            float(value)
            return True
        except ValueError:
            return False
    return False


def validate_latitude(lat: Any, field_name: str = "latitude") -> float:
    """
    Validate latitude value.

    Args:
        lat: Latitude value to validate
        field_name: Name for error messages

    Returns:
        Validated latitude as float

    Raises:
        ValueError: If latitude is invalid
    """
    if not is_number(lat):
        raise ValueError(f"{field_name} must be a number, got {type(lat).__name__}: {lat!r}")

    lat_float = float(lat)

    if lat_float < -90.0 or lat_float > 90.0:
        raise ValueError(f"{field_name} must be between -90 and 90, got {lat_float}")

    return lat_float


def validate_longitude(lon: Any, field_name: str = "longitude") -> float:
    """
    Validate longitude value.

    Args:
        lon: Longitude value to validate
        field_name: Name for error messages

    Returns:
        Validated longitude as float

    Raises:
        ValueError: If longitude is invalid
    """
    if not is_number(lon):
        raise ValueError(f"{field_name} must be a number, got {type(lon).__name__}: {lon!r}")

    lon_float = float(lon)

    if lon_float < -180.0 or lon_float > 180.0:
        raise ValueError(f"{field_name} must be between -180 and 180, got {lon_float}")

    return lon_float


def validate_latlon(lat: Any, lon: Any) -> Tuple[float, float]:
    """
    Validate both latitude and longitude.

    Args:
        lat: Latitude value
        lon: Longitude value

    Returns:
        Tuple of (validated_lat, validated_lon)

    Raises:
        ValueError: If either coordinate is invalid
    """
    return validate_latitude(lat), validate_longitude(lon)


def validate_marker_name(name: Any) -> str:
    """
    Validate marker name.

    Args:
        name: Marker name to validate

    Returns:
        Validated name as string

    Raises:
        ValueError: If name is empty or invalid
    """
    if name is None:
        raise ValueError("Marker name cannot be None")

    if not isinstance(name, str):
        name = str(name)

    name = name.strip()

    if not name:
        raise ValueError("Marker name cannot be empty")

    # Max length check (reasonable limit for UI display)
    if len(name) > 255:
        raise ValueError(f"Marker name too long (max 255 chars, got {len(name)})")

    return name


def validate_marker_type(marker_type: Any) -> str:
    """
    Validate marker type.

    Args:
        marker_type: Marker type string

    Returns:
        Validated marker type

    Raises:
        ValueError: If marker type is invalid
    """
    if marker_type is None:
        raise ValueError("Marker type cannot be None")

    if not isinstance(marker_type, str):
        marker_type = str(marker_type)

    marker_type = marker_type.lower().strip()

    if marker_type not in VALID_MARKER_TYPES:
        valid_list = ', '.join(sorted(VALID_MARKER_TYPES))
        raise ValueError(
            f"Invalid marker type '{marker_type}'. "
            f"Valid types are: {valid_list}"
        )

    return marker_type


def extract_marker_coordinates(marker_data: Dict[str, Any]) -> Tuple[float, float]:
    """
    Extract and validate coordinates from marker data dictionary.

    Supports multiple coordinate field naming conventions:
    - 'lat'/'lon'
    - 'latitude'/'longitude'
    - 'y'/'x'

    Args:
        marker_data: Dictionary containing marker data

    Returns:
        Tuple of (latitude, longitude)

    Raises:
        ValueError: If coordinates cannot be extracted or are invalid
    """
    if not marker_data:
        raise ValueError("Marker data cannot be empty")

    # Try different field name conventions
    lat = None
    lon = None

    # Priority 1: lat/lon
    if 'lat' in marker_data and 'lon' in marker_data:
        lat = marker_data['lat']
        lon = marker_data['lon']
    # Priority 2: latitude/longitude
    elif 'latitude' in marker_data and 'longitude' in marker_data:
        lat = marker_data['latitude']
        lon = marker_data['longitude']
    # Priority 3: y/x (QGIS convention)
    elif 'y' in marker_data and 'x' in marker_data:
        lat = marker_data['y']
        lon = marker_data['x']

    if lat is None or lon is None:
        raise ValueError(
            "Marker data missing coordinates. "
            "Expected 'lat'/'lon', 'latitude'/'longitude', or 'y'/'x' fields."
        )

    return validate_latlon(lat, lon)


def build_marker_update_payload(
    name: str,
    lat: float,
    lon: float,
    marker_type: str = 'poi',
    description: Optional[str] = None,
    attachment_path: Optional[str] = None
) -> Dict[str, Any]:
    """
    Build a validated marker update payload.

    Args:
        name: Marker name
        lat: Latitude
        lon: Longitude
        marker_type: Type of marker
        description: Optional description
        attachment_path: Optional attachment path

    Returns:
        Dictionary with validated marker data

    Raises:
        ValueError: If any field is invalid
    """
    validated_name = validate_marker_name(name)
    validated_lat, validated_lon = validate_latlon(lat, lon)
    validated_type = validate_marker_type(marker_type)

    payload = {
        'name': validated_name,
        'lat': validated_lat,
        'lon': validated_lon,
        'marker_type': validated_type,
    }

    if description is not None:
        # Basic sanitization - no validation failure for description
        payload['description'] = str(description)[:2000]  # Max length

    if attachment_path is not None:
        payload['attachment_path'] = str(attachment_path)

    return payload


def validate_marker_id(marker_id: Any) -> int:
    """
    Validate marker feature ID.

    Args:
        marker_id: Feature ID to validate

    Returns:
        Validated ID as integer

    Raises:
        ValueError: If ID is invalid
    """
    if marker_id is None:
        raise ValueError("Marker ID cannot be None")

    try:
        id_int = int(marker_id)
    except (TypeError, ValueError):
        raise ValueError(f"Marker ID must be an integer, got {type(marker_id).__name__}: {marker_id!r}")

    if id_int < 0:
        raise ValueError(f"Marker ID cannot be negative, got {id_int}")

    return id_int
