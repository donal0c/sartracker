# -*- coding: utf-8 -*-
"""
SAR Tracker Exception Hierarchy

Custom exceptions for clean error handling without GUI dependencies.
All exceptions are testable and can be used in headless environments.

Qt5/Qt6 Compatible: No Qt dependencies in this module.
"""


class SARTrackerError(Exception):
    """
    Base exception for all SAR Tracker errors.

    Attributes:
        title: Short error title for UI display
        message: Detailed error message
        severity: Error severity (info, warning, error, critical)
        recoverable: Whether the operation can be retried
    """

    def __init__(self, message, title=None, severity='error', recoverable=False):
        """
        Initialize SAR Tracker error.

        Args:
            message: Detailed error message
            title: Short error title (defaults to class name)
            severity: Error severity ('info', 'warning', 'error', 'critical')
            recoverable: Whether operation can be retried
        """
        super().__init__(message)
        self.message = message
        self.title = title or self.__class__.__name__
        self.severity = severity  # 'info', 'warning', 'error', 'critical'
        self.recoverable = recoverable


class LayerError(SARTrackerError):
    """Base class for layer-related errors."""

    def __init__(self, message, layer_name=None, **kwargs):
        """
        Initialize layer error.

        Args:
            message: Detailed error message
            layer_name: Name of the layer that caused the error
            **kwargs: Additional arguments passed to SARTrackerError
        """
        super().__init__(message, **kwargs)
        self.layer_name = layer_name


class LayerLockError(LayerError):
    """Raised when layer is locked/being edited."""

    def __init__(self, layer_name):
        """
        Initialize layer lock error.

        Args:
            layer_name: Name of the locked layer
        """
        super().__init__(
            f"{layer_name} is currently being edited. Try again shortly.",
            title="Layer Busy",
            severity='warning',
            recoverable=True,
            layer_name=layer_name
        )


class LayerTransactionError(LayerError):
    """Raised when layer transaction fails (startEditing, commitChanges)."""

    def __init__(self, layer_name, operation, details=None):
        """
        Initialize layer transaction error.

        Args:
            layer_name: Name of the layer
            operation: Operation that failed (e.g., "commit", "add feature")
            details: Additional error details
        """
        msg = f"Failed to {operation} {layer_name}"
        if details:
            msg += f": {details}"
        super().__init__(
            msg,
            title="Layer Transaction Failed",
            severity='error',
            recoverable=False,
            layer_name=layer_name
        )
        self.operation = operation
        self.details = details


class DataValidationError(SARTrackerError):
    """Raised when input data validation fails."""

    def __init__(self, message, field_name=None, field_value=None):
        """
        Initialize data validation error.

        Args:
            message: Detailed error message
            field_name: Name of the field that failed validation
            field_value: The invalid value
        """
        super().__init__(
            message,
            title="Validation Error",
            severity='warning',
            recoverable=True
        )
        self.field_name = field_name
        self.field_value = field_value


class CoordinateError(DataValidationError):
    """Raised when coordinate validation fails."""

    def __init__(self, coord_type, value, valid_range):
        """
        Initialize coordinate error.

        Args:
            coord_type: Type of coordinate (e.g., 'latitude', 'longitude')
            value: The invalid value
            valid_range: Description of valid range
        """
        super().__init__(
            f"Invalid {coord_type}: {value}. Must be {valid_range}",
            field_name=coord_type,
            field_value=value
        )
        self.coord_type = coord_type
        self.valid_range = valid_range


class GeometryError(SARTrackerError):
    """Raised when geometry creation/manipulation fails."""

    def __init__(self, message, geometry_type=None):
        """
        Initialize geometry error.

        Args:
            message: Detailed error message
            geometry_type: Type of geometry (e.g., 'point', 'line', 'polygon')
        """
        super().__init__(
            message,
            title="Geometry Error",
            severity='error',
            recoverable=False
        )
        self.geometry_type = geometry_type


class MapToolError(SARTrackerError):
    """Base class for map tool errors."""
    pass


class DrawingError(MapToolError):
    """Raised when drawing operation fails."""

    def __init__(self, message, tool_name=None):
        """
        Initialize drawing error.

        Args:
            message: Detailed error message
            tool_name: Name of the tool that failed
        """
        super().__init__(
            message,
            title=f"{tool_name} Error" if tool_name else "Drawing Error",
            severity='error',
            recoverable=False
        )
        self.tool_name = tool_name


# Convenience validation functions

def validate_latitude(lat):
    """
    Validate latitude value.

    Args:
        lat: Latitude value to validate

    Raises:
        CoordinateError: If latitude is invalid

    Returns:
        float: Validated latitude
    """
    if not isinstance(lat, (int, float)):
        raise CoordinateError('latitude', lat, '-90 to 90 degrees')
    if not -90 <= lat <= 90:
        raise CoordinateError('latitude', lat, '-90 to 90 degrees')
    return float(lat)


def validate_longitude(lon):
    """
    Validate longitude value.

    Args:
        lon: Longitude value to validate

    Raises:
        CoordinateError: If longitude is invalid

    Returns:
        float: Validated longitude
    """
    if not isinstance(lon, (int, float)):
        raise CoordinateError('longitude', lon, '-180 to 180 degrees')
    if not -180 <= lon <= 180:
        raise CoordinateError('longitude', lon, '-180 to 180 degrees')
    return float(lon)


def validate_coordinate_pair(lat, lon):
    """
    Validate latitude/longitude pair.

    Args:
        lat: Latitude value to validate
        lon: Longitude value to validate

    Raises:
        CoordinateError: If either coordinate is invalid

    Returns:
        tuple: Validated (latitude, longitude) as floats
    """
    validated_lat = validate_latitude(lat)
    validated_lon = validate_longitude(lon)
    return (validated_lat, validated_lon)
