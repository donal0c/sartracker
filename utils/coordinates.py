# -*- coding: utf-8 -*-
"""
Coordinate Conversion Utilities

Convert between Irish Grid (ITM) and WGS84 coordinate systems.
"""

from typing import Tuple
from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsPointXY,
    QgsProject
)


class CoordinateConverter:
    """
    Convert between Irish Grid (ITM EPSG:29903) and WGS84 (EPSG:4326).
    """

    def __init__(self):
        self.wgs84 = QgsCoordinateReferenceSystem("EPSG:4326")
        self.itm = QgsCoordinateReferenceSystem("EPSG:29903")  # Irish Transverse Mercator
        self.project = QgsProject.instance()

    def irish_grid_to_wgs84(self, easting: float, northing: float) -> Tuple[float, float]:
        """
        Convert Irish Grid (ITM) to WGS84 Lat/Lon.
        
        Args:
            easting: Easting coordinate (ITM)
            northing: Northing coordinate (ITM)
            
        Returns:
            Tuple of (latitude, longitude) in WGS84
        """
        transform = QgsCoordinateTransform(
            self.itm,
            self.wgs84,
            self.project
        )
        point = QgsPointXY(easting, northing)
        transformed = transform.transform(point)
        return transformed.y(), transformed.x()  # lat, lon

    def wgs84_to_irish_grid(self, lat: float, lon: float) -> Tuple[float, float]:
        """
        Convert WGS84 Lat/Lon to Irish Grid (ITM).
        
        Args:
            lat: Latitude (WGS84)
            lon: Longitude (WGS84)
            
        Returns:
            Tuple of (easting, northing) in ITM
        """
        transform = QgsCoordinateTransform(
            self.wgs84,
            self.itm,
            self.project
        )
        point = QgsPointXY(lon, lat)
        transformed = transform.transform(point)
        return transformed.x(), transformed.y()  # easting, northing

    def format_irish_grid(self, easting: float, northing: float) -> str:
        """
        Format Irish Grid coordinates as string.

        Args:
            easting: Easting coordinate
            northing: Northing coordinate

        Returns:
            Formatted string "E: 123456  N: 234567"
        """
        return f"E: {easting:.0f}  N: {northing:.0f}"

    def format_wgs84(self, lat: float, lon: float) -> str:
        """
        Format WGS84 coordinates as string.
        
        Args:
            lat: Latitude
            lon: Longitude
            
        Returns:
            Formatted string "52.2345°N, -9.1234°W"
        """
        lat_dir = 'N' if lat >= 0 else 'S'
        lon_dir = 'E' if lon >= 0 else 'W'
        return f"{abs(lat):.4f}°{lat_dir}, {abs(lon):.4f}°{lon_dir}"
