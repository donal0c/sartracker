# -*- coding: utf-8 -*-
"""
Base Provider ABC

Defines the interface for all data providers (CSV, PostGIS, SpatiaLite)
"""

from abc import ABC, abstractmethod
from typing import List, Dict, Optional, Any

# Type alias for feature dictionaries
FeatureDict = Dict[str, Any]


class Provider(ABC):
    """
    Abstract base class for data providers.

    All providers must implement these methods to supply tracking data,
    save features, and manage connections.
    """

    @abstractmethod
    def get_current(self) -> List[FeatureDict]:
        """
        Get latest position per device.

        Returns:
            List of dicts with keys:
                - device_id: str
                - name: str
                - lat: float (WGS84)
                - lon: float (WGS84)
                - ts: str (ISO8601 timestamp)
                - altitude: Optional[float]
                - speed: Optional[float]
                - battery: Optional[float]
        """
        pass

    @abstractmethod
    def get_breadcrumbs(self, since_iso: Optional[str] = None,
                       mission_id: Optional[int] = None) -> List[FeatureDict]:
        """
        Get breadcrumb trail for all devices.

        Args:
            since_iso: Optional ISO timestamp to filter from
            mission_id: Optional mission ID to get breadcrumbs for specific mission

        Returns:
            List of position dicts (same format as get_current), time-ordered
        """
        pass

    @abstractmethod
    def get_devices(self) -> List[Dict[str, Any]]:
        """
        Get list of all devices.

        Returns:
            List of dicts with keys:
                - device_id: str
                - name: str
                - status: str ('online', 'offline', 'unknown')
                - last_update: Optional[str] (ISO timestamp)
        """
        pass

    @abstractmethod
    def save_casualty(self, mission_id: int, name: str,
                     lat: float, lon: float,
                     irish_grid_e: Optional[float] = None,
                     irish_grid_n: Optional[float] = None,
                     description: str = "") -> int:
        """
        Save casualty location.

        Args:
            mission_id: ID of current mission
            name: Casualty name/identifier
            lat: Latitude (WGS84)
            lon: Longitude (WGS84)
            irish_grid_e: Easting (ITM)
            irish_grid_n: Northing (ITM)
            description: Additional notes

        Returns:
            ID of saved casualty
        """
        pass

    @abstractmethod
    def save_poi(self, mission_id: int, name: str,
                lat: float, lon: float,
                poi_type: str = "",
                irish_grid_e: Optional[float] = None,
                irish_grid_n: Optional[float] = None,
                description: str = "",
                color: str = "#007BFF") -> int:
        """
        Save point of interest.

        Args:
            mission_id: ID of current mission
            name: POI name
            lat: Latitude (WGS84)
            lon: Longitude (WGS84)
            poi_type: Type ('base', 'vehicle', 'landmark', 'hazard', etc.)
            irish_grid_e: Easting (ITM)
            irish_grid_n: Northing (ITM)
            description: Additional notes
            color: Hex color for marker

        Returns:
            ID of saved POI
        """
        pass

    @abstractmethod
    def test_connection(self) -> bool:
        """
        Test if provider can access data source.

        Returns:
            True if connection successful, False otherwise
        """
        pass
