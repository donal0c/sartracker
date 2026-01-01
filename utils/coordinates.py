# -*- coding: utf-8 -*-
"""
Coordinate Conversion Utilities

Convert between Irish Grid (ITM) and WGS84 coordinate systems.

LIFE-SAFETY CRITICAL: This module handles coordinate transformations used
in search and rescue operations. Invalid coordinates could lead rescue teams
to wrong locations. All inputs are validated before transformation.
"""

import logging
import math
from typing import Tuple

from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsPointXY,
    QgsProject,
    QgsCsException
)

logger = logging.getLogger(__name__)

# ITM (Irish Transverse Mercator) valid coordinate ranges
# These are generous bounds that cover all of Ireland with margin
ITM_EASTING_MIN = 0
ITM_EASTING_MAX = 1_000_000
ITM_NORTHING_MIN = 0
ITM_NORTHING_MAX = 1_500_000

# WGS84 valid ranges
WGS84_LAT_MIN = -90.0
WGS84_LAT_MAX = 90.0
WGS84_LON_MIN = -180.0
WGS84_LON_MAX = 180.0


class CoordinateConverter:
    """
    Convert between Irish Grid (ITM EPSG:2157) and WGS84 (EPSG:4326).

    All conversion methods include comprehensive input validation:
    - Type checking (must be numeric)
    - NaN/Infinity checks
    - Range validation for both CRS
    - Transform error handling

    LIFE-SAFETY CRITICAL: Invalid coordinates are rejected with clear errors.
    """

    def __init__(self):
        self.wgs84 = QgsCoordinateReferenceSystem("EPSG:4326")
        # Use EPSG:2157 (Irish Transverse Mercator / ITM) - the modern Irish Grid
        # Note: EPSG:29903 is the older TM65 Irish Grid which has 1-3m accuracy issues
        self.itm = QgsCoordinateReferenceSystem("EPSG:2157")
        self.project = QgsProject.instance()

        # Validate CRS initialization
        if not self.wgs84.isValid():
            logger.error("WGS84 CRS (EPSG:4326) failed to initialize")
        if not self.itm.isValid():
            logger.error("ITM CRS (EPSG:2157) failed to initialize")

    def _validate_numeric(self, value, name: str, context: str) -> float:
        """
        Validate that a value is numeric (int or float).

        Args:
            value: The value to validate
            name: Name of the parameter for error messages
            context: Operation context for error messages

        Returns:
            The value as a float

        Raises:
            TypeError: If value is not numeric
        """
        if not isinstance(value, (int, float)):
            error_msg = (
                f"Invalid {name} during {context}: "
                f"expected numeric, got {type(value).__name__}"
            )
            logger.error(error_msg)
            raise TypeError(error_msg)
        return float(value)

    def _validate_finite(self, value: float, name: str, context: str) -> None:
        """
        Validate that a numeric value is finite (not NaN or Infinity).

        Args:
            value: The numeric value to validate
            name: Name of the parameter for error messages
            context: Operation context for error messages

        Raises:
            ValueError: If value is NaN or Infinity
        """
        if math.isnan(value):
            error_msg = f"Invalid {name} during {context}: value is NaN"
            logger.error(error_msg)
            raise ValueError(error_msg)
        if math.isinf(value):
            error_msg = f"Invalid {name} during {context}: value is Infinity"
            logger.error(error_msg)
            raise ValueError(error_msg)

    def _validate_itm_range(self, easting: float, northing: float, context: str) -> None:
        """
        Validate ITM coordinates are within valid ranges.

        Args:
            easting: ITM easting coordinate
            northing: ITM northing coordinate
            context: Operation context for error messages

        Raises:
            ValueError: If coordinates are outside valid ITM range
        """
        if not (ITM_EASTING_MIN <= easting <= ITM_EASTING_MAX):
            error_msg = (
                f"Invalid easting during {context}: {easting:.2f} is outside "
                f"valid ITM range [{ITM_EASTING_MIN}, {ITM_EASTING_MAX}]"
            )
            logger.error(error_msg)
            raise ValueError(error_msg)

        if not (ITM_NORTHING_MIN <= northing <= ITM_NORTHING_MAX):
            error_msg = (
                f"Invalid northing during {context}: {northing:.2f} is outside "
                f"valid ITM range [{ITM_NORTHING_MIN}, {ITM_NORTHING_MAX}]"
            )
            logger.error(error_msg)
            raise ValueError(error_msg)

    def _validate_wgs84_range(self, lat: float, lon: float, context: str) -> None:
        """
        Validate WGS84 coordinates are within valid ranges.

        Args:
            lat: Latitude (-90 to 90)
            lon: Longitude (-180 to 180)
            context: Operation context for error messages

        Raises:
            ValueError: If coordinates are outside valid WGS84 range
        """
        if not (WGS84_LAT_MIN <= lat <= WGS84_LAT_MAX):
            error_msg = (
                f"Invalid latitude during {context}: {lat:.6f} is outside "
                f"valid range [{WGS84_LAT_MIN}, {WGS84_LAT_MAX}]"
            )
            logger.error(error_msg)
            raise ValueError(error_msg)

        if not (WGS84_LON_MIN <= lon <= WGS84_LON_MAX):
            error_msg = (
                f"Invalid longitude during {context}: {lon:.6f} is outside "
                f"valid range [{WGS84_LON_MIN}, {WGS84_LON_MAX}]"
            )
            logger.error(error_msg)
            raise ValueError(error_msg)

    def irish_grid_to_wgs84(self, easting: float, northing: float) -> Tuple[float, float]:
        """
        Convert Irish Grid (ITM) to WGS84 Lat/Lon.

        LIFE-SAFETY CRITICAL: Validates all inputs before transformation.

        Args:
            easting: Easting coordinate (ITM, 0-1,000,000)
            northing: Northing coordinate (ITM, 0-1,500,000)

        Returns:
            Tuple of (latitude, longitude) in WGS84

        Raises:
            TypeError: If inputs are not numeric
            ValueError: If inputs are NaN, Infinity, or out of range
            RuntimeError: If coordinate transformation fails
        """
        context = "irish_grid_to_wgs84"

        # Validate inputs
        easting = self._validate_numeric(easting, "easting", context)
        northing = self._validate_numeric(northing, "northing", context)
        self._validate_finite(easting, "easting", context)
        self._validate_finite(northing, "northing", context)
        self._validate_itm_range(easting, northing, context)

        # Check CRS validity
        if not self.itm.isValid() or not self.wgs84.isValid():
            error_msg = f"CRS not valid during {context}: ITM={self.itm.isValid()}, WGS84={self.wgs84.isValid()}"
            logger.error(error_msg)
            raise RuntimeError(error_msg)

        # Perform transformation with error handling
        try:
            transform = QgsCoordinateTransform(
                self.itm,
                self.wgs84,
                self.project
            )
            if not transform.isValid():
                error_msg = f"Transform not valid during {context}"
                logger.error(error_msg)
                raise RuntimeError(error_msg)

            point = QgsPointXY(easting, northing)
            transformed = transform.transform(point)
            lat, lon = transformed.y(), transformed.x()

            # Validate output
            self._validate_finite(lat, "output latitude", context)
            self._validate_finite(lon, "output longitude", context)
            self._validate_wgs84_range(lat, lon, context)

            return lat, lon

        except (TypeError, ValueError):
            # Re-raise validation errors as-is
            raise
        except Exception as e:
            # Catch all transform errors (QgsCsException included)
            error_msg = f"Coordinate transform failed during {context}: {e}"
            logger.error(error_msg)
            raise RuntimeError(error_msg) from e

    def wgs84_to_irish_grid(self, lat: float, lon: float) -> Tuple[float, float]:
        """
        Convert WGS84 Lat/Lon to Irish Grid (ITM).

        LIFE-SAFETY CRITICAL: Validates all inputs before transformation.

        Args:
            lat: Latitude (WGS84, -90 to 90)
            lon: Longitude (WGS84, -180 to 180)

        Returns:
            Tuple of (easting, northing) in ITM

        Raises:
            TypeError: If inputs are not numeric
            ValueError: If inputs are NaN, Infinity, or out of range
            RuntimeError: If coordinate transformation fails
        """
        context = "wgs84_to_irish_grid"

        # Validate inputs
        lat = self._validate_numeric(lat, "latitude", context)
        lon = self._validate_numeric(lon, "longitude", context)
        self._validate_finite(lat, "latitude", context)
        self._validate_finite(lon, "longitude", context)
        self._validate_wgs84_range(lat, lon, context)

        # Check CRS validity
        if not self.wgs84.isValid() or not self.itm.isValid():
            error_msg = f"CRS not valid during {context}: WGS84={self.wgs84.isValid()}, ITM={self.itm.isValid()}"
            logger.error(error_msg)
            raise RuntimeError(error_msg)

        # Perform transformation with error handling
        try:
            transform = QgsCoordinateTransform(
                self.wgs84,
                self.itm,
                self.project
            )
            if not transform.isValid():
                error_msg = f"Transform not valid during {context}"
                logger.error(error_msg)
                raise RuntimeError(error_msg)

            point = QgsPointXY(lon, lat)
            transformed = transform.transform(point)
            easting, northing = transformed.x(), transformed.y()

            # Validate output
            self._validate_finite(easting, "output easting", context)
            self._validate_finite(northing, "output northing", context)
            self._validate_itm_range(easting, northing, context)

            return easting, northing

        except (TypeError, ValueError):
            # Re-raise validation errors as-is
            raise
        except Exception as e:
            # Catch all transform errors (QgsCsException included)
            error_msg = f"Coordinate transform failed during {context}: {e}"
            logger.error(error_msg)
            raise RuntimeError(error_msg) from e

    def format_irish_grid(self, easting: float, northing: float) -> str:
        """
        Format Irish Grid coordinates as string.

        Args:
            easting: Easting coordinate
            northing: Northing coordinate

        Returns:
            Formatted string "E: 123456  N: 234567"

        Raises:
            TypeError: If inputs are not numeric
            ValueError: If inputs are NaN or Infinity
        """
        context = "format_irish_grid"

        # Validate inputs (no range check - may be displaying invalid coords)
        easting = self._validate_numeric(easting, "easting", context)
        northing = self._validate_numeric(northing, "northing", context)
        self._validate_finite(easting, "easting", context)
        self._validate_finite(northing, "northing", context)

        return f"E: {easting:.0f}  N: {northing:.0f}"

    def format_wgs84(self, lat: float, lon: float) -> str:
        """
        Format WGS84 coordinates as string.

        Args:
            lat: Latitude
            lon: Longitude

        Returns:
            Formatted string "52.2345N, -9.1234W"

        Raises:
            TypeError: If inputs are not numeric
            ValueError: If inputs are NaN or Infinity
        """
        context = "format_wgs84"

        # Validate inputs (no range check - may be displaying invalid coords)
        lat = self._validate_numeric(lat, "latitude", context)
        lon = self._validate_numeric(lon, "longitude", context)
        self._validate_finite(lat, "latitude", context)
        self._validate_finite(lon, "longitude", context)

        lat_dir = 'N' if lat >= 0 else 'S'
        lon_dir = 'E' if lon >= 0 else 'W'
        return f"{abs(lat):.4f}{lat_dir}, {abs(lon):.4f}{lon_dir}"
