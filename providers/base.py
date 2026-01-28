# -*- coding: utf-8 -*-
"""
Base Provider ABC

Defines the interface for all data providers (CSV, PostGIS, SpatiaLite).
All providers must implement this interface and follow the error handling
contract specified in AI_CODE_REFERENCE.md.

Phase 1 - Provider Abstraction Hardening:
This module establishes the formal provider contract with comprehensive
docstrings covering return schemas, thread-safety, and error expectations.

Qt5/Qt6 Compatible: No Qt dependencies in this module.
"""

from abc import ABC, abstractmethod
from typing import List, Dict, Optional, Any

# Type alias for feature dictionaries
FeatureDict = Dict[str, Any]


class Provider(ABC):
    """
    Abstract base class for data providers.

    All providers must implement these methods to supply tracking data,
    save features, and manage connections. Providers plug into the SAR
    Tracker architecture through the provider registry (providers/registry.py).

    ERROR HANDLING CONTRACT:
    All methods must raise utils.exceptions.ProviderError subclasses for
    failures. Never raise generic RuntimeError or Exception. Use the most
    specific error class:
        - ProviderAuthError: Authentication/authorization failures (401/403)
        - ProviderNetworkError: Transport issues (timeout, DNS, SSL)
        - ProviderDataError: Malformed data, missing files, schema errors

    THREAD-SAFETY REQUIREMENTS:
    Provider methods may be called from background threads (via QgsTask).
    Implementations must:
        1. NOT touch Qt objects directly (violates Pattern 6 in AI reference)
        2. Use thread-safe data structures for shared state
        3. Document any non-thread-safe methods explicitly

    See AI_CODE_REFERENCE.md for complete patterns and examples.

    Qt5/Qt6 Compatible: Implementations must not introduce Qt dependencies.
    """

    @abstractmethod
    def get_current(self) -> List[FeatureDict]:
        """
        Get latest position per device.

        Returns the most recent position for each device known to the provider.
        For CSV providers, this is the last position in each file. For API
        providers, this queries the live server state.

        RETURN SCHEMA:
        Each dict in the returned list must contain:
            - device_id: str (unique device identifier, mandatory)
            - name: str (device display name, mandatory)
            - lat: float (latitude WGS84, mandatory, -90 to 90)
            - lon: float (longitude WGS84, mandatory, -180 to 180)
            - ts: str (ISO8601 timestamp, mandatory, e.g., "2025-11-15T14:30:00Z")
            - altitude: Optional[float] (meters above sea level)
            - speed: Optional[float] (speed in knots or m/s, provider-dependent)
            - battery: Optional[float] (battery percentage 0-100)

        OPTIONAL ATTRIBUTES:
        Providers may include additional keys (e.g., motion, distance) but
        must document them in provider-specific docstrings.

        Returns:
            List of position dicts, one per device. Empty list if no devices
            or no recent positions available.

        Raises:
            ProviderAuthError: If authentication fails (API providers)
            ProviderNetworkError: If network request fails (API providers)
            ProviderDataError: If data files missing/malformed (CSV providers)
                               or API response has invalid schema

        THREAD-SAFETY:
        Method is called from background threads (QgsTask). Must not access
        Qt objects. See Pattern 6 in AI_CODE_REFERENCE.md.

        Qt5/Qt6 Compatible: Pure Python return types.
        """
        pass

    @abstractmethod
    def get_breadcrumbs(self, since_iso: Optional[str] = None,
                       until_iso: Optional[str] = None,
                       mission_id: Optional[int] = None) -> List[FeatureDict]:
        """
        Get breadcrumb trail for all devices.

        Returns historical position data for all devices, optionally filtered
        by time range and/or mission. Used to render device tracks/trails on
        the map for situational awareness and track analysis.

        Args:
            since_iso: Optional ISO8601 timestamp to filter from (inclusive).
                      Format: "2025-11-15T14:30:00Z" or "2025-11-15T14:30:00+00:00"
                      If None, provider chooses reasonable default (e.g., last 3 hours)
            until_iso: Optional ISO8601 timestamp to cap history (exclusive or inclusive
                       provider-defined). Used for replay windows; providers may ignore
                       if unsupported.
            mission_id: Optional mission ID for filtering positions associated
                       with specific mission. CSV providers may ignore this.
                       Database providers should filter by mission.

        RETURN SCHEMA:
        Each dict must contain the same mandatory fields as get_current():
            - device_id: str
            - name: str
            - lat: float (WGS84)
            - lon: float (WGS84)
            - ts: str (ISO8601 timestamp)
            - altitude: Optional[float]
            - speed: Optional[float]
            - battery: Optional[float]

        ORDERING:
        Results must be sorted by (device_id, ts) for efficient UI rendering.
        Positions for the same device must be time-ordered to draw accurate trails.

        Returns:
            List of position dicts, sorted by device then time. Empty list if
            no positions match the filter criteria.

        Raises:
            ProviderAuthError: If authentication fails (API providers)
            ProviderNetworkError: If network request fails (API providers)
            ProviderDataError: If data files missing/malformed (CSV providers)
                               or API response has invalid schema

        THREAD-SAFETY:
        Method is called from background threads (QgsTask). Must not access
        Qt objects. See Pattern 6 in AI_CODE_REFERENCE.md.

        Qt5/Qt6 Compatible: Pure Python return types.
        """
        pass

    @abstractmethod
    def get_devices(self) -> List[Dict[str, Any]]:
        """
        Get list of all devices known to provider.

        Returns metadata about all devices without full position history.
        Used for device selection UI, status monitoring, and diagnostics.

        RETURN SCHEMA:
        Each dict must contain:
            - device_id: str (unique device identifier, mandatory)
            - name: str (device display name, mandatory)
            - status: str ('online', 'offline', 'unknown', mandatory)
            - last_update: Optional[str] (ISO8601 timestamp of last known position)

        STATUS VALUES:
            - 'online': Device is actively reporting (has recent position)
            - 'offline': Device is known but not reporting
            - 'unknown': Device status cannot be determined

        Returns:
            List of device metadata dicts. Empty list if no devices configured.

        Raises:
            ProviderAuthError: If authentication fails (API providers)
            ProviderNetworkError: If network request fails (API providers)
            ProviderDataError: If data files missing/malformed (CSV providers)
                               or API response has invalid schema

        THREAD-SAFETY:
        Method is called from background threads (QgsTask). Must not access
        Qt objects. See Pattern 6 in AI_CODE_REFERENCE.md.

        Qt5/Qt6 Compatible: Pure Python return types.
        """
        pass

    @abstractmethod
    def save_casualty(self, mission_id: int, name: str,
                     lat: float, lon: float,
                     irish_grid_e: Optional[float] = None,
                     irish_grid_n: Optional[float] = None,
                     description: str = "") -> int:
        """
        Save casualty location to provider's persistent storage.

        Casualties are life-safety critical features. Providers that cannot
        persist data (e.g., CSV, read-only APIs) must raise NotImplementedError.

        INPUT VALIDATION:
        Implementations must validate all inputs before persistence:
            - lat/lon must be within valid WGS84 ranges
            - mission_id must reference existing mission (if applicable)
            - name must be non-empty string

        Use utils.exceptions.validate_coordinate_pair() for coordinate validation.

        Args:
            mission_id: ID of current mission (must be > 0)
            name: Casualty name/identifier (non-empty)
            lat: Latitude in WGS84 decimal degrees (-90 to 90)
            lon: Longitude in WGS84 decimal degrees (-180 to 180)
            irish_grid_e: Optional Easting in ITM (Irish Transverse Mercator)
            irish_grid_n: Optional Northing in ITM
            description: Additional notes (free text, default empty)

        Returns:
            Integer ID of saved casualty (provider-specific, must be > 0)

        Raises:
            NotImplementedError: If provider does not support persistence
            ProviderDataError: If validation fails or persistence fails
            DataValidationError: If coordinates invalid (from validation helper)

        THREAD-SAFETY:
        May be called from background threads. Database providers must use
        thread-safe connection handling.

        Qt5/Qt6 Compatible: Pure Python types.
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
        Save point of interest to provider's persistent storage.

        POIs include operational features like base camps, hazards, landmarks,
        and staging areas. Providers that cannot persist data must raise
        NotImplementedError.

        INPUT VALIDATION:
        Implementations must validate all inputs before persistence:
            - lat/lon must be within valid WGS84 ranges
            - mission_id must reference existing mission (if applicable)
            - name must be non-empty string
            - color must be valid hex color (if provided)

        Use utils.exceptions.validate_coordinate_pair() for coordinate validation.

        Args:
            mission_id: ID of current mission (must be > 0)
            name: POI name/identifier (non-empty)
            lat: Latitude in WGS84 decimal degrees (-90 to 90)
            lon: Longitude in WGS84 decimal degrees (-180 to 180)
            poi_type: Type category ('base', 'vehicle', 'landmark', 'hazard', etc.)
                     Empty string if unspecified
            irish_grid_e: Optional Easting in ITM (Irish Transverse Mercator)
            irish_grid_n: Optional Northing in ITM
            description: Additional notes (free text, default empty)
            color: Hex color for map marker (e.g., "#007BFF", default blue)

        Returns:
            Integer ID of saved POI (provider-specific, must be > 0)

        Raises:
            NotImplementedError: If provider does not support persistence
            ProviderDataError: If validation fails or persistence fails
            DataValidationError: If coordinates invalid (from validation helper)

        THREAD-SAFETY:
        May be called from background threads. Database providers must use
        thread-safe connection handling.

        Qt5/Qt6 Compatible: Pure Python types.
        """
        pass

    @abstractmethod
    def test_connection(self) -> bool:
        """
        Test if provider can access its data source.

        Performs a lightweight check to verify:
        - CSV providers: Files exist and are readable
        - API providers: Server is reachable and credentials valid
        - Database providers: Connection can be established

        This method should be fast (< 5 seconds) and safe to call repeatedly.
        It must NOT raise exceptions - all failures return False.

        ERROR HANDLING:
        Must NOT raise exceptions. Catch all errors internally and return False.
        This differs from other methods because test_connection() is used for
        health checks and UI indicators where exceptions would disrupt flow.

        Returns:
            True if provider can access data source, False otherwise

        THREAD-SAFETY:
        May be called from background threads or main thread. Must not access
        Qt objects.

        Qt5/Qt6 Compatible: Pure Python return types.
        """
        pass

    @abstractmethod
    def create_refresh_task(self, description: str,
                            since_iso: Optional[str] = None,
                            until_iso: Optional[str] = None,
                            device_timestamps: Optional[Dict[str, str]] = None) -> 'ProviderRefreshTask':
        """
        Create provider-specific refresh task for background data fetching.

        Each provider implements its own QgsTask subclass (CSVRefreshTask,
        HTTPRefreshTask, etc.) that handles provider-specific data fetching
        in a background thread managed by QGIS TaskManager.

        The returned task will be scheduled by the controller and must:
        1. Fetch data in run() method (background thread)
        2. Emit signals with results on success/failure
        3. Never access Qt widgets/UI directly (Pattern 6)

        See providers/tasks.py for implementation examples.

        Args:
            description: Human-readable task description for QGIS task manager
                        display (e.g., "Fetching device positions")
            since_iso: Optional ISO8601 timestamp to filter breadcrumbs from.
                       If provided (e.g., mission start time), breadcrumbs will
                       be fetched from this time. Providers may ignore if not
                       applicable (e.g., CSV provider loads all data).
            until_iso: Optional ISO8601 timestamp to cap breadcrumb history.
                       Used for historical replay windows; providers may ignore
                       if not supported.
            device_timestamps: Optional dict mapping device_id to ISO8601 timestamp
                              for incremental fetch (Phase 3). Providers that don't
                              support incremental fetch may ignore this parameter.

        Returns:
            ProviderRefreshTask subclass instance (inherits QgsTask)

        THREAD-SAFETY:
        This method is called from main thread. The returned task's run()
        method will execute in background thread. The task must not access
        Qt widgets.

        Qt5/Qt6 Compatible: Returns QgsTask subclass.
        """
        pass
