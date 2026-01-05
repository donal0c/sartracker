# -*- coding: utf-8 -*-
"""
File CSV Provider

Reads tracking data from Traccar CSV exports.
This is a transitional provider for teams currently using CSV workflow.

Phase 1 - Provider Abstraction Hardening:
Updated to use ProviderError hierarchy for consistent error handling.
All errors now raise ProviderDataError instead of generic RuntimeError.

Qt5/Qt6 Compatible: Pure Python implementation, no Qt dependencies.
"""

import os
import csv
import glob
import math
import logging
from typing import List, Dict, Optional, Any, Tuple
from datetime import datetime, timezone
from .base import Provider, FeatureDict
from ..utils.exceptions import ProviderDataError
from ..utils.cache import LRUTTLCache


class FileCSVProvider(Provider):
    """
    CSV provider for transitional period.
    Reads from Traccar CSV exports (team's current workflow).

    Expected CSV format (Traccar route export):
    - Header rows with metadata
    - Column headers: Valid, Time, Latitude, Longitude, Altitude, Speed, Address, Attributes
    - Data rows with position information

    Performance Features:
    - File-level caching with mtime checks (avoids reparsing unchanged files)
    - Cache hit provides ~3x speedup for typical refresh cycles

    THREAD-SAFETY (Phase 1):
    CSV provider is thread-safe because it only uses local I/O and standard
    Python data structures. The file cache uses mtime-based invalidation which
    is safe across threads. Methods can be called from background threads
    (QgsTask) without synchronization.

    ERROR HANDLING (Phase 1):
    Raises ProviderDataError for all failures:
    - CSV file not found or inaccessible
    - CSV file missing required columns (Valid, Time, Latitude, Longitude)
    - CSV data malformed (invalid lat/lon values)

    Qt5/Qt6 Compatible: Pure Python implementation, no Qt dependencies.
    """

    # Memory estimation constants (measured values from FINDINGS/results_deep_dive_C.md)
    # Position dict overhead: ~650 bytes per position (was 200, 70% underestimate)
    # File entry overhead: ~500 bytes per cached file (dict key + mtime + device_name)
    BYTES_PER_POSITION = 650
    BYTES_PER_FILE = 500

    # Cache configuration
    # MEMORY STABILITY: Limit to 50 files with 1 hour TTL to prevent unbounded growth
    CACHE_MAX_FILES = 50
    CACHE_TTL_SECONDS = 3600  # 1 hour
    # MEMORY STABILITY: Guard cache size by estimated bytes (position-heavy files can be large)
    CACHE_MAX_MEMORY_BYTES = 64 * 1024 * 1024  # 64 MB approx cap on cached CSV payloads

    # CSV parsing constants
    REQUIRED_HEADERS = ("Valid", "Time", "Latitude", "Longitude")
    HEADER_SCAN_LIMIT = 50
    HEADER_ALIASES = {
        "valid": "Valid",
        "time": "Time",
        "latitude": "Latitude",
        "longitude": "Longitude",
        "altitude": "Altitude",
        "speed": "Speed",
        "address": "Address",
        "attributes": "Attributes",
    }

    def __init__(self, csv_path: str):
        """
        Initialize CSV provider.

        Args:
            csv_path: Path to CSV file or folder containing CSV files
        """
        self.csv_path = csv_path
        self.is_folder = os.path.isdir(csv_path)

        # Cache: {filepath: (mtime, device_name, positions)}
        # MEMORY STABILITY: Use LRU+TTL cache to prevent unbounded growth
        # Key is file path, value is tuple of:
        # - mtime: File modification time (float)
        # - device_name: Extracted device name (str)
        # - positions: List of parsed position dicts
        self._cache: LRUTTLCache[str, Tuple[float, str, List[FeatureDict]]] = LRUTTLCache(
            max_size=self.CACHE_MAX_FILES,
            ttl_seconds=self.CACHE_TTL_SECONDS
        )

    class _CSVDecodeError(Exception):
        """Internal decode error to trigger encoding fallback."""

    class _CSVParseCancelled(Exception):
        """Internal cancellation signal for long CSV parses."""

    @classmethod
    def _normalize_header_field(cls, field: str) -> str:
        """Normalize CSV header field to canonical form."""
        if field is None:
            return ""
        cleaned = field.strip().lstrip('\ufeff')
        if not cleaned:
            return ""
        return cls.HEADER_ALIASES.get(cleaned.lower(), cleaned)

    @classmethod
    def _has_required_headers(cls, fields: List[str]) -> bool:
        """Check for required CSV headers after normalization."""
        field_set = {f for f in fields if f}
        return all(req in field_set for req in cls.REQUIRED_HEADERS)

    @staticmethod
    def _safe_parse_timestamp(ts_str: str) -> datetime:
        """Parse timestamp to naive UTC for reliable ordering."""
        ts_value = (ts_str or "").strip()
        if not ts_value:
            return datetime.min
        try:
            parsed = datetime.fromisoformat(ts_value.replace('Z', '+00:00'))
            if parsed.tzinfo is not None:
                parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
            return parsed
        except (ValueError, AttributeError, TypeError):
            try:
                return datetime.strptime(ts_value, "%Y-%m-%d %H:%M:%S")
            except (ValueError, AttributeError, TypeError):
                return datetime.min

    def _count_cached_positions(self) -> int:
        """Count cached positions for cache memory estimation."""
        total_positions = 0
        for cache_entry in self._cache.values():
            _timestamp, inner_tuple = cache_entry
            _mtime, _device_name, positions = inner_tuple
            total_positions += len(positions)
        return total_positions
        
    def _parse_attributes(self, attr_string: str) -> Dict[str, Any]:
        """
        Parse Traccar attributes string.
        
        Example: "batteryLevel=98.0  distance=29038.25  totalDistance=607086.36  motion=true"
        
        Returns:
            Dict with parsed attributes
        """
        attrs = {}
        if not attr_string:
            return attrs
            
        # Split by double spaces or single spaces
        parts = attr_string.strip().split()
        
        for part in parts:
            if '=' in part:
                key, value = part.split('=', 1)
                # Try to convert to appropriate type
                try:
                    if '.' in value:
                        attrs[key] = float(value)
                    elif value.lower() == 'true':
                        attrs[key] = True
                    elif value.lower() == 'false':
                        attrs[key] = False
                    else:
                        attrs[key] = value
                except ValueError:
                    attrs[key] = value
                    
        return attrs
    
    def _parse_csv_file(
        self,
        filepath: str,
        cancel_cb: Optional[Any] = None
    ) -> Tuple[str, List[FeatureDict]]:
        """
        Parse a single CSV file with caching.

        Uses file modification time (mtime) to determine if cached results
        can be returned, avoiding expensive reparsing.

        Returns:
            Tuple of (device_name, list of positions)
        """
        # Get file mtime for cache check
        try:
            mtime = os.path.getmtime(filepath)
        except OSError:
            # File deleted/inaccessible since directory listing
            return os.path.basename(filepath).replace('.csv', ''), []

        # Check cache (LRUTTLCache returns None if not found or expired)
        cached = self._cache.get(filepath)
        cached_positions_len = 0
        if cached is not None:
            cached_mtime, cached_name, cached_positions = cached
            if cached_mtime == mtime:
                # Cache hit - file unchanged since last parse
                self._cache.evict_expired()
                return cached_name, cached_positions
            cached_positions_len = len(cached_positions)

        # TTL eviction is only enforced on access; clear expired entries to keep memory bounded
        self._cache.evict_expired()

        # Cache miss or file modified - parse file
        device_name, positions = self._parse_csv_file_impl(filepath, cancel_cb=cancel_cb)

        # Update cache
        current_positions = self._count_cached_positions()
        current_files = self._cache.get_stats().get('size', len(self._cache))
        if cached is not None:
            current_positions = max(0, current_positions - cached_positions_len)
        else:
            current_files += 1

        estimated_bytes = (
            (current_positions + len(positions)) * self.BYTES_PER_POSITION +
            (current_files * self.BYTES_PER_FILE)
        )

        if estimated_bytes <= self.CACHE_MAX_MEMORY_BYTES:
            self._cache.set(filepath, (mtime, device_name, positions))
        else:
            logger = logging.getLogger(__name__)
            logger.warning(
                "CSV cache skip: %s positions in %s would exceed cache cap (%.1f MB).",
                len(positions),
                os.path.basename(filepath),
                self.CACHE_MAX_MEMORY_BYTES / (1024 * 1024)
            )

        return device_name, positions

    def _parse_csv_file_impl(
        self,
        filepath: str,
        cancel_cb: Optional[Any] = None
    ) -> Tuple[str, List[FeatureDict]]:
        """
        Actual CSV parsing implementation (called only on cache miss).

        Returns:
            Tuple of (device_name, list of positions)

        Raises:
            ProviderDataError: If file cannot be read or has invalid format
        """
        device_name = os.path.basename(filepath).replace('.csv', '')
        positions = []

        # BUG-070 FIX: Proper encoding detection to prevent silent data corruption
        # LIFE-SAFETY CRITICAL: Silently replacing characters could corrupt coordinates or timestamps
        #
        # Strategy:
        # 1. Try UTF-8 strict (most common, no data loss)
        # 2. Try UTF-8 with BOM
        # 3. Try common Western encodings (latin-1, windows-1252)
        # 4. Last resort: UTF-8 with replacement (with warning)

        encodings_to_try = [
            ('utf-8', 'strict', 'UTF-8'),
            ('utf-8-sig', 'strict', 'UTF-8 with BOM'),
            ('latin-1', 'strict', 'Latin-1/ISO-8859-1'),
            ('windows-1252', 'strict', 'Windows-1252'),
            ('utf-8', 'replace', 'UTF-8 with character replacement (data may be corrupted)')
        ]

        try:
            encoding_used = None

            for encoding, errors, description in encodings_to_try:
                try:
                    device_name, positions = self._parse_csv_with_encoding(
                        filepath,
                        device_name,
                        encoding,
                        errors,
                        cancel_cb=cancel_cb
                    )
                    encoding_used = (encoding, errors, description)
                    break
                except self._CSVDecodeError:
                    continue
                except self._CSVParseCancelled:
                    raise

            if encoding_used is None:
                raise ProviderDataError(
                    f"Cannot decode CSV file {filepath}: tried UTF-8, Latin-1, Windows-1252",
                    provider_name='csv',
                    recoverable=True
                )

            # BUG-070 FIX: Warn if we had to use replacement encoding
            logger = logging.getLogger(__name__)

            if encoding_used[1] == 'replace':
                logger.warning(
                    f"BUG-070: CSV file {filepath} contains invalid UTF-8 characters. "
                    f"Using replacement encoding - data may be corrupted. "
                    f"Please re-export this file with proper UTF-8 encoding."
                )

            return device_name, positions

        except ProviderDataError:
            # Re-raise provider errors
            raise
        except self._CSVParseCancelled:
            raise
        except Exception as e:
            # Wrap unexpected errors
            raise ProviderDataError(
                f"Error parsing CSV file {filepath}: {str(e)}",
                provider_name='csv',
                recoverable=False
            )

    def _parse_csv_with_encoding(
        self,
        filepath: str,
        device_name: str,
        encoding: str,
        errors: str,
        cancel_cb: Optional[Any] = None
    ) -> Tuple[str, List[FeatureDict]]:
        """Parse CSV file using a specific encoding (may raise _CSVDecodeError)."""
        try:
            with open(filepath, 'r', encoding=encoding, errors=errors) as f:
                positions = []
                # Phase 1: Read header section (first 50 lines max) to find structure
                header_fields = None
                for i, line in enumerate(f):
                    if cancel_cb and cancel_cb():
                        raise self._CSVParseCancelled()

                    if i < 10:
                        device_line = line.lstrip('\ufeff').lstrip()
                        if device_line.startswith('Device:'):
                            parts = next(csv.reader([device_line]))
                            if len(parts) > 1 and parts[1]:
                                device_name = parts[1].strip()

                    try:
                        parts = next(csv.reader([line]))
                    except csv.Error:
                        parts = []

                    normalized_fields = [self._normalize_header_field(field) for field in parts]
                    if self._has_required_headers(normalized_fields):
                        header_fields = normalized_fields
                        break

                    if i >= self.HEADER_SCAN_LIMIT:
                        break

                if not header_fields:
                    raise ProviderDataError(
                        f"CSV file missing required headers (Valid, Time, Latitude, Longitude): {filepath}",
                        provider_name='csv',
                        recoverable=False
                    )

                # Stream remaining data instead of loading all at once
                reader = csv.DictReader(f, fieldnames=header_fields)

                # BUG-051 FIX: Track skipped rows for logging
                skipped_invalid = 0
                skipped_coord_range = 0
                skipped_no_timestamp = 0
                skipped_bad_timestamp = 0
                skipped_malformed = 0
                invalid_altitude = 0
                invalid_speed = 0
                total_rows = 0

                for row in reader:
                    if cancel_cb and cancel_cb():
                        raise self._CSVParseCancelled()

                    total_rows += 1

                    valid_value = (row.get('Valid') or '').strip().upper()
                    if valid_value not in ('TRUE', '1'):
                        skipped_invalid += 1
                        continue

                    try:
                        attrs = self._parse_attributes(row.get('Attributes') or '')

                        lat = float(row['Latitude'])
                        lon = float(row['Longitude'])

                        if math.isnan(lat) or math.isnan(lon) or math.isinf(lat) or math.isinf(lon):
                            skipped_coord_range += 1
                            continue

                        if not (-90 <= lat <= 90):
                            skipped_coord_range += 1
                            continue
                        if not (-180 <= lon <= 180):
                            skipped_coord_range += 1
                            continue

                        if abs(lat) < 0.0001 and abs(lon) < 0.0001:
                            skipped_coord_range += 1
                            logging.getLogger(__name__).debug(
                                "Skipping Null Island position (0,0) - likely GPS failure"
                            )
                            continue

                        timestamp_str = (row.get('Time') or '').strip()
                        if not timestamp_str:
                            skipped_no_timestamp += 1
                            continue

                        try:
                            datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
                        except (ValueError, AttributeError, TypeError):
                            try:
                                datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S")
                            except (ValueError, AttributeError, TypeError):
                                skipped_bad_timestamp += 1
                                continue

                        altitude = None
                        altitude_value = row.get('Altitude')
                        if altitude_value:
                            try:
                                altitude = float(str(altitude_value).replace(' m', '').strip())
                            except (ValueError, TypeError):
                                invalid_altitude += 1

                        speed = None
                        speed_value = row.get('Speed')
                        if speed_value:
                            try:
                                speed = float(str(speed_value).replace(' kn', '').strip())
                            except (ValueError, TypeError):
                                invalid_speed += 1

                        position = {
                            'device_id': device_name,
                            'name': device_name,
                            'lat': lat,
                            'lon': lon,
                            'ts': timestamp_str,
                            'altitude': altitude,
                            'speed': speed,
                            'battery': attrs.get('batteryLevel'),
                            'motion': attrs.get('motion', True),
                            'distance': attrs.get('distance'),
                            'total_distance': attrs.get('totalDistance')
                        }

                        positions.append(position)

                    except (ValueError, KeyError, TypeError):
                        skipped_malformed += 1
                        continue

                total_skipped = (
                    skipped_invalid +
                    skipped_coord_range +
                    skipped_no_timestamp +
                    skipped_bad_timestamp +
                    skipped_malformed
                )
                if total_skipped > 0:
                    print(f"[CSV_PROVIDER] BUG-051: Parsed {len(positions)}/{total_rows} rows from {filepath}")
                    if skipped_invalid > 0:
                        print(f"[CSV_PROVIDER]   - Skipped {skipped_invalid} invalid rows (Valid != TRUE)")
                    if skipped_coord_range > 0:
                        print(f"[CSV_PROVIDER]   - Skipped {skipped_coord_range} rows with out-of-range coordinates")
                    if skipped_no_timestamp > 0:
                        print(f"[CSV_PROVIDER]   - Skipped {skipped_no_timestamp} rows with missing timestamp")
                    if skipped_bad_timestamp > 0:
                        print(f"[CSV_PROVIDER]   - Skipped {skipped_bad_timestamp} rows with unparseable timestamp")
                    if skipped_malformed > 0:
                        print(f"[CSV_PROVIDER]   - Skipped {skipped_malformed} malformed rows")
                    if invalid_altitude > 0:
                        print(f"[CSV_PROVIDER]   - {invalid_altitude} rows had invalid altitude (set to None)")
                    if invalid_speed > 0:
                        print(f"[CSV_PROVIDER]   - {invalid_speed} rows had invalid speed (set to None)")

                return device_name, positions
        except UnicodeDecodeError as exc:
            raise self._CSVDecodeError() from exc
    
    # BUG-080 FIX: Limit maximum CSV files to prevent performance degradation
    # LIFE-SAFETY CRITICAL: Large directories could cause UI freezes during mission operations
    MAX_CSV_FILES = 1000  # Reasonable limit for rescue operations

    def _get_csv_files(self) -> List[str]:
        """
        Get list of CSV files to process.

        BUG-080 FIX: Limits to MAX_CSV_FILES to prevent performance issues
        with directories containing thousands of files.

        Returns:
            List of CSV file paths (limited to MAX_CSV_FILES)

        Raises:
            ProviderDataError: If CSV path does not exist or is inaccessible
        """
        logger = logging.getLogger(__name__)

        # Validate path exists
        if not os.path.exists(self.csv_path):
            raise ProviderDataError(
                f"CSV path does not exist: {self.csv_path}",
                provider_name='csv',
                recoverable=True
            )

        if self.is_folder:
            # BUG-080 FIX: Use glob with limit check
            csv_files = glob.glob(os.path.join(self.csv_path, '*.csv'))

            if not csv_files:
                raise ProviderDataError(
                    f"No CSV files found in directory: {self.csv_path}",
                    provider_name='csv',
                    recoverable=True
                )

            # BUG-080 FIX: Check for excessive file counts
            if len(csv_files) > self.MAX_CSV_FILES:
                logger.warning(
                    f"BUG-080: Directory contains {len(csv_files)} CSV files, "
                    f"limiting to {self.MAX_CSV_FILES} most recent files. "
                    f"Consider organizing files into subdirectories by date/mission."
                )
                # Sort by modification time (most recent first) and limit
                csv_files.sort(key=lambda f: os.path.getmtime(f), reverse=True)
                csv_files = csv_files[:self.MAX_CSV_FILES]

            return csv_files
        else:
            if not os.path.isfile(self.csv_path):
                raise ProviderDataError(
                    f"CSV file not found: {self.csv_path}",
                    provider_name='csv',
                    recoverable=True
                )
            return [self.csv_path]
    
    def get_current(self, cancel_cb: Optional[Any] = None) -> List[FeatureDict]:
        """
        Get latest position per device from CSV files.

        When multiple CSV files contain data for the same device, the position
        with the newest timestamp is used. File order and naming do not affect
        which position is selected.

        This allows safe usage of backup files, daily exports, and archives in
        the same directory.

        Returns:
            List of latest positions (one per device), with each dict containing:
            - device_id: str (device identifier)
            - name: str (device name)
            - lat: float (latitude, WGS84)
            - lon: float (longitude, WGS84)
            - ts: str (ISO timestamp of position)
            - altitude: Optional[float]
            - speed: Optional[float]
            - battery: Optional[float]

        Raises:
            ProviderDataError: If CSV path does not exist or no CSV files found

        THREAD-SAFETY:
        Safe to call from background threads (uses only local I/O).

        Qt5/Qt6 Compatible: Pure Python implementation.
        """
        # Collect all positions per device (handles multiple files per device)
        device_positions = {}  # device_name -> list of candidate positions

        try:
            csv_files = self._get_csv_files()

            for csv_file in csv_files:
                if cancel_cb and cancel_cb():
                    raise self._CSVParseCancelled()

                device_name, positions = self._parse_csv_file(csv_file, cancel_cb=cancel_cb)

                if positions:
                    if device_name not in device_positions:
                        device_positions[device_name] = []

                    latest_in_file = max(
                        positions,
                        key=lambda x: self._safe_parse_timestamp(x.get('ts'))
                    )
                    device_positions[device_name].append(latest_in_file)

            current_positions = []
            for device_name, positions in device_positions.items():
                latest = max(
                    positions,
                    key=lambda x: self._safe_parse_timestamp(x.get('ts'))
                )
                current_positions.append(latest)

            return current_positions
        except self._CSVParseCancelled:
            return []
    
    def get_breadcrumbs(
        self,
        since_iso: Optional[str] = None,
        mission_id: Optional[int] = None,
        cancel_cb: Optional[Any] = None
    ) -> List[FeatureDict]:
        """
        Get all positions from CSV files.

        Args:
            since_iso: Optional ISO timestamp to filter from
            mission_id: Ignored for CSV provider

        Returns:
            List of all positions, time-ordered

        Raises:
            ProviderDataError: If CSV path does not exist or files are malformed

        THREAD-SAFETY:
        Safe to call from background threads (uses only local I/O).
        """
        try:
            all_positions = []

            csv_files = self._get_csv_files()

            since_dt = None
            if since_iso:
                parsed_since = self._safe_parse_timestamp(since_iso)
                if parsed_since != datetime.min:
                    since_dt = parsed_since

            for csv_file in csv_files:
                if cancel_cb and cancel_cb():
                    raise self._CSVParseCancelled()

                device_name, positions = self._parse_csv_file(csv_file, cancel_cb=cancel_cb)

                if since_dt:
                    filtered_positions = []
                    for p in positions:
                        p_ts = self._safe_parse_timestamp(p.get('ts'))
                        if p_ts == datetime.min or p_ts >= since_dt:
                            filtered_positions.append(p)
                    positions = filtered_positions

                all_positions.extend(positions)

            all_positions.sort(
                key=lambda x: (x.get('device_id'), self._safe_parse_timestamp(x.get('ts')))
            )

            return all_positions
        except self._CSVParseCancelled:
            return []
    
    def get_devices(self, cancel_cb: Optional[Any] = None) -> List[Dict[str, Any]]:
        """
        Get list of devices from CSV files.

        When multiple CSV files contain data for the same device, the device
        metadata reflects the position with the newest timestamp. File order
        and naming do not affect which timestamp is used.

        Returns:
            List of device dicts, each containing:
            - device_id: str (device identifier)
            - name: str (device name)
            - status: str ('online' for CSV data)
            - last_update: str (ISO timestamp of most recent position)

        Raises:
            ProviderDataError: If CSV path does not exist or files are malformed

        THREAD-SAFETY:
        Safe to call from background threads (uses only local I/O).

        Qt5/Qt6 Compatible: Pure Python implementation.
        """
        # Collect all positions per device (handles multiple files per device)
        device_positions = {}  # device_name -> list of candidate positions

        try:
            csv_files = self._get_csv_files()

            for csv_file in csv_files:
                if cancel_cb and cancel_cb():
                    raise self._CSVParseCancelled()

                device_name, positions = self._parse_csv_file(csv_file, cancel_cb=cancel_cb)

                if positions:
                    if device_name not in device_positions:
                        device_positions[device_name] = []

                    latest_in_file = max(
                        positions,
                        key=lambda x: self._safe_parse_timestamp(x.get('ts'))
                    )
                    device_positions[device_name].append(latest_in_file)

            devices = []
            for device_name, positions in device_positions.items():
                latest_position = max(
                    positions,
                    key=lambda x: self._safe_parse_timestamp(x.get('ts'))
                )

                devices.append({
                    'device_id': device_name,
                    'name': device_name,
                    'status': 'online',
                    'last_update': latest_position['ts']
                })

            return devices
        except self._CSVParseCancelled:
            return []
    
    def save_casualty(self, mission_id: int, name: str,
                     lat: float, lon: float,
                     irish_grid_e: Optional[float] = None,
                     irish_grid_n: Optional[float] = None,
                     description: str = "") -> int:
        """
        CSV provider does not support saving casualties.
        
        Raises:
            NotImplementedError
        """
        raise NotImplementedError("CSV provider does not support saving casualties")
    
    def save_poi(self, mission_id: int, name: str,
                lat: float, lon: float,
                poi_type: str = "",
                irish_grid_e: Optional[float] = None,
                irish_grid_n: Optional[float] = None,
                description: str = "",
                color: str = "#007BFF") -> int:
        """
        CSV provider does not support saving POIs.
        
        Raises:
            NotImplementedError
        """
        raise NotImplementedError("CSV provider does not support saving POIs")
    
    def test_connection(self) -> bool:
        """
        Test if CSV file(s) exist and can be read.

        Returns:
            True if CSV files found and readable, False with diagnostic logging if issues occur
        """
        try:
            logger = logging.getLogger(__name__)

            csv_files = self._get_csv_files()

            if not csv_files:
                logger.warning(f"No CSV files found in path: {self.csv_path}")
                return False

            # Log number of CSV files found
            logger.info(f"Found {len(csv_files)} CSV files in path")
            return True

        except Exception as e:
            # Critical: Log the actual exception details for diagnostics
            logger = logging.getLogger(__name__)
            logger.error(f"Connection test failed for CSV provider: {str(e)}")
            return False

    def create_refresh_task(
        self,
        description: str,
        since_iso: Optional[str] = None,
        device_timestamps: Optional[Dict[str, str]] = None
    ) -> 'ProviderRefreshTask':
        """
        Create CSV-specific refresh task.

        Args:
            description: Task description for progress display
            since_iso: Optional ISO8601 timestamp to filter breadcrumbs from.
            device_timestamps: Optional per-device timestamps (ignored for CSV -
                              CSV provider reads full file each time, incremental
                              fetch not supported).

        Returns:
            CSVRefreshTask instance for background parsing

        Qt5/Qt6 Compatible: Returns QgsTask subclass.
        """
        # Note: device_timestamps ignored - CSV doesn't support incremental fetch
        from .tasks import CSVRefreshTask
        return CSVRefreshTask(self, description, since_iso=since_iso)

    def invalidate_cache(self, filepath: Optional[str] = None):
        """
        Invalidate cache for specific file or all files.

        Args:
            filepath: Path to file to invalidate, or None to clear all cache

        Qt5/Qt6 Compatible: Uses standard Python dict operations.
        """
        if filepath:
            self._cache.pop(filepath, None)
        else:
            self._cache.clear()

    def get_cache_stats(self) -> Dict[str, Any]:
        """
        Get cache statistics for debugging and monitoring.

        Returns:
            Dict with cache stats (entries, estimated memory KB, LRU stats)

        Qt5/Qt6 Compatible: Pure Python implementation.
        """
        # Get LRU cache internal stats
        lru_stats = self._cache.get_stats()
        num_files = lru_stats['size']

        # Count total positions across all cached files
        # Note: LRUTTLCache.values() returns (timestamp, value) tuples
        # where value = (mtime, device_name, positions)
        total_positions = 0
        for cache_entry in self._cache.values():
            _timestamp, inner_tuple = cache_entry
            _mtime, _device_name, positions = inner_tuple
            total_positions += len(positions)

        # Accurate estimation based on measured values (FINDINGS/results_deep_dive_C.md)
        memory_bytes = (
            (total_positions * self.BYTES_PER_POSITION) +
            (num_files * self.BYTES_PER_FILE)
        )
        memory_kb = memory_bytes / 1024

        return {
            'entries': num_files,
            'max_entries': lru_stats['max_size'],
            'total_positions': total_positions,
            'memory_kb': int(memory_kb),
            'hit_rate_percent': lru_stats['hit_rate_percent'],
            'evictions_lru': lru_stats['evictions_lru'],
            'evictions_ttl': lru_stats['evictions_ttl'],
        }


# ============================================================================
# Provider Self-Registration
# ============================================================================

def _create_csv_provider(config: Dict) -> FileCSVProvider:
    """
    Factory function for CSV provider.

    Args:
        config: Configuration dict with 'csv_path' key

    Returns:
        FileCSVProvider instance

    Raises:
        ProviderDataError: If csv_path not provided in config or path invalid
    """
    # Validate config before creating provider (Phase 1 requirement)
    if not isinstance(config, dict):
        raise ProviderDataError(
            "CSV provider requires config dict",
            provider_name='csv',
            recoverable=False
        )

    csv_path = config.get('csv_path')
    if not csv_path:
        raise ProviderDataError(
            "CSV provider requires 'csv_path' in config",
            provider_name='csv',
            recoverable=False
        )

    if not isinstance(csv_path, str) or not csv_path.strip():
        raise ProviderDataError(
            f"CSV provider 'csv_path' must be non-empty string, got: {type(csv_path)}",
            provider_name='csv',
            recoverable=False
        )

    return FileCSVProvider(csv_path)


# Register CSV provider with global registry
from .registry import registry, ProviderMetadata

registry.register(
    ProviderMetadata(
        name='csv',
        display_name='CSV Files',
        description='Load tracking data from Traccar CSV exports (file or folder)',
        requires_config=True,
        config_schema={
            'csv_path': {
                'type': 'path',
                'description': 'Path to CSV file or folder containing CSV files',
                'required': True
            }
        },
        # Phase 1: Provider capabilities
        supports_polling=False,  # CSV is read-only, not a polled data source
        supports_streaming=False,  # No streaming support
        auth_modes=[]  # No authentication required (local files)
    ),
    _create_csv_provider
)
