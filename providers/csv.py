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
from typing import List, Dict, Optional, Any, Tuple
from datetime import datetime
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
    
    def _parse_csv_file(self, filepath: str) -> Tuple[str, List[FeatureDict]]:
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
        if cached is not None:
            cached_mtime, cached_name, cached_positions = cached
            if cached_mtime == mtime:
                # Cache hit - file unchanged since last parse
                return cached_name, cached_positions

        # Cache miss or file modified - parse file
        device_name, positions = self._parse_csv_file_impl(filepath)

        # Update cache
        self._cache.set(filepath, (mtime, device_name, positions))

        return device_name, positions

    def _parse_csv_file_impl(self, filepath: str) -> Tuple[str, List[FeatureDict]]:
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

        f = None
        encoding_used = None

        for encoding, errors, description in encodings_to_try:
            try:
                f = open(filepath, 'r', encoding=encoding, errors=errors)
                encoding_used = (encoding, errors, description)
                break  # Successfully opened
            except (IOError, OSError) as e:
                # File access error - don't try other encodings
                raise ProviderDataError(
                    f"Cannot access CSV file {filepath}: {str(e)}",
                    provider_name='csv',
                    recoverable=True
                )
            except UnicodeDecodeError:
                # Try next encoding
                continue

        if f is None:
            raise ProviderDataError(
                f"Cannot decode CSV file {filepath}: tried UTF-8, Latin-1, Windows-1252",
                provider_name='csv',
                recoverable=True
            )

        # BUG-070 FIX: Warn if we had to use replacement encoding
        import logging
        logger = logging.getLogger(__name__)

        if encoding_used and encoding_used[1] == 'replace':
            logger.warning(
                f"BUG-070: CSV file {filepath} contains invalid UTF-8 characters. "
                f"Using replacement encoding - data may be corrupted. "
                f"Please re-export this file with proper UTF-8 encoding."
            )

        try:
            with f:
                # BUG-025 FIX: Use chunked reading to prevent memory exhaustion
                # with large CSV files. Read header section first, then stream data.

                # Phase 1: Read header section (first 50 lines max) to find structure
                header_lines = []
                header_idx = -1
                for i, line in enumerate(f):
                    header_lines.append(line)

                    # Check for device name in first 10 lines
                    if i < 10 and line.startswith('Device:'):
                        parts = line.strip().split(',')
                        if len(parts) > 1 and parts[1]:
                            device_name = parts[1]

                    # Check for header row
                    if 'Valid' in line and 'Time' in line and 'Latitude' in line:
                        header_idx = i
                        break

                    # Safety limit - if we haven't found headers in 50 lines, stop
                    if i >= 50:
                        break

                if header_idx == -1:
                    raise ProviderDataError(
                        f"CSV file missing required headers (Valid, Time, Latitude, Longitude): {filepath}",
                        provider_name='csv',
                        recoverable=False
                    )

                # BUG-025 FIX: Stream remaining data instead of loading all at once
                # Build header row from the identified header line
                import io
                header_line = header_lines[header_idx]

                # Create a streaming reader that starts from the header line
                # and continues with remaining file content
                def _streaming_lines():
                    """Generator that yields header + remaining file lines."""
                    yield header_line
                    for line in f:
                        yield line

                reader = csv.DictReader(_streaming_lines())

                # BUG-051 FIX: Track skipped rows for logging
                skipped_invalid = 0
                skipped_coord_range = 0
                skipped_no_timestamp = 0
                skipped_bad_timestamp = 0
                skipped_malformed = 0
                total_rows = 0

                for row in reader:
                    total_rows += 1

                    # Skip invalid rows
                    if row.get('Valid', '').strip().upper() not in ('TRUE', '1'):
                        skipped_invalid += 1
                        continue

                    try:
                        # Parse attributes
                        attrs = self._parse_attributes(row.get('Attributes', ''))

                        # Parse and validate coordinates
                        lat = float(row['Latitude'])
                        lon = float(row['Longitude'])

                        # LIFE-SAFETY CRITICAL: Reject NaN/Inf coordinates
                        # NaN comparisons always return False, so NaN would pass range checks
                        if math.isnan(lat) or math.isnan(lon) or math.isinf(lat) or math.isinf(lon):
                            skipped_coord_range += 1
                            continue  # Invalid NaN/Inf coordinate, skip row

                        # Validate coordinate ranges (skip invalid positions)
                        if not (-90 <= lat <= 90):
                            skipped_coord_range += 1
                            continue  # Invalid latitude, skip row
                        if not (-180 <= lon <= 180):
                            skipped_coord_range += 1
                            continue  # Invalid longitude, skip row

                        # LIFE-SAFETY CRITICAL: Reject Null Island (0,0) - common GPS failure indicator
                        # Consistent with HTTP provider validation (BUG-FIX: consistency across providers)
                        if abs(lat) < 0.0001 and abs(lon) < 0.0001:
                            skipped_coord_range += 1
                            logger.debug("Skipping Null Island position (0,0) - likely GPS failure")
                            continue

                        # Validate timestamp format (BUG-041 fix)
                        # CRITICAL: Invalid timestamps can cause wrong "latest" position
                        timestamp_str = row.get('Time', '')
                        if not timestamp_str:
                            skipped_no_timestamp += 1
                            continue  # No timestamp, skip row

                        # Validate timestamp is parseable
                        try:
                            # Try ISO format first (most common)
                            datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
                        except (ValueError, AttributeError, TypeError):
                            try:
                                # Fallback: try common format YYYY-MM-DD HH:MM:SS
                                datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S")
                            except (ValueError, AttributeError, TypeError):
                                # Invalid timestamp format, skip this row
                                skipped_bad_timestamp += 1
                                continue

                        # Build position dict
                        position = {
                            'device_id': device_name,
                            'name': device_name,
                            'lat': lat,
                            'lon': lon,
                            'ts': timestamp_str,  # Validated timestamp string
                            'altitude': float(row['Altitude'].replace(' m', '')) if row.get('Altitude') else None,
                            'speed': float(row['Speed'].replace(' kn', '')) if row.get('Speed') else None,
                            'battery': attrs.get('batteryLevel'),
                            'motion': attrs.get('motion', True),
                            'distance': attrs.get('distance'),
                            'total_distance': attrs.get('totalDistance')
                        }

                        positions.append(position)

                    except (ValueError, KeyError) as e:
                        # Skip malformed rows (non-critical, some rows may be metadata)
                        skipped_malformed += 1
                        continue

                # BUG-051 FIX: Log summary of skipped rows if significant
                total_skipped = skipped_invalid + skipped_coord_range + skipped_no_timestamp + skipped_bad_timestamp + skipped_malformed
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

                return device_name, positions

        except ProviderDataError:
            # Re-raise provider errors
            raise
        except Exception as e:
            # Wrap unexpected errors
            raise ProviderDataError(
                f"Error parsing CSV file {filepath}: {str(e)}",
                provider_name='csv',
                recoverable=False
            )
    
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
        import logging
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
    
    def get_current(self) -> List[FeatureDict]:
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

        csv_files = self._get_csv_files()

        for csv_file in csv_files:
            device_name, positions = self._parse_csv_file(csv_file)

            if positions:
                # Collect last position from this file
                if device_name not in device_positions:
                    device_positions[device_name] = []

                # Last position in file (within-file ordering assumed correct)
                device_positions[device_name].append(positions[-1])

        # For each device, select position with maximum (newest) timestamp
        # Use datetime parsing for reliable comparison (handles various formats)
        def parse_timestamp(ts_str):
            """Parse timestamp string to datetime for comparison."""
            try:
                # Try ISO format first (most common)
                return datetime.fromisoformat(ts_str.replace('Z', '+00:00'))
            except (ValueError, AttributeError):
                try:
                    # Fallback: try common format YYYY-MM-DD HH:MM:SS
                    return datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")
                except (ValueError, AttributeError):
                    # Last resort: return epoch (will sort to beginning)
                    return datetime.min

        current_positions = []
        for device_name, positions in device_positions.items():
            latest = max(positions, key=lambda x: parse_timestamp(x['ts']))
            current_positions.append(latest)

        return current_positions
    
    def get_breadcrumbs(self, since_iso: Optional[str] = None,
                       mission_id: Optional[int] = None) -> List[FeatureDict]:
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
        all_positions = []
        
        csv_files = self._get_csv_files()
        
        for csv_file in csv_files:
            device_name, positions = self._parse_csv_file(csv_file)
            
            # Filter by time if specified
            if since_iso:
                try:
                    since_dt = datetime.fromisoformat(since_iso.replace('Z', '+00:00'))
                    filtered_positions = []
                    for p in positions:
                        try:
                            p_ts = datetime.fromisoformat(p['ts'].replace('Z', '+00:00'))
                            if p_ts >= since_dt:
                                filtered_positions.append(p)
                        except (ValueError, AttributeError):
                            # Can't parse timestamp, include position to be safe
                            filtered_positions.append(p)
                    positions = filtered_positions
                except (ValueError, AttributeError):
                    # Can't parse since_iso, skip filtering
                    pass
            
            all_positions.extend(positions)
        
        # Sort by device then time
        all_positions.sort(key=lambda x: (x['device_id'], x['ts']))
        
        return all_positions
    
    def get_devices(self) -> List[Dict[str, Any]]:
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

        csv_files = self._get_csv_files()

        for csv_file in csv_files:
            device_name, positions = self._parse_csv_file(csv_file)

            if positions:
                # Collect last position from this file
                if device_name not in device_positions:
                    device_positions[device_name] = []

                # Last position in file (within-file ordering assumed correct)
                device_positions[device_name].append(positions[-1])

        # For each device, find position with maximum (newest) timestamp
        # ISO timestamps (YYYY-MM-DD HH:MM:SS) compare correctly as strings
        devices = []
        for device_name, positions in device_positions.items():
            latest_position = max(positions, key=lambda x: x['ts'])

            devices.append({
                'device_id': device_name,
                'name': device_name,
                'status': 'online',  # Assume online for CSV data
                'last_update': latest_position['ts']
            })

        return devices
    
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
            import logging
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
        since_iso: Optional[str] = None
    ) -> 'ProviderRefreshTask':
        """
        Create CSV-specific refresh task.

        Args:
            description: Task description for progress display
            since_iso: Optional ISO8601 timestamp to filter breadcrumbs from.

        Returns:
            CSVRefreshTask instance for background parsing

        Qt5/Qt6 Compatible: Returns QgsTask subclass.
        """
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
