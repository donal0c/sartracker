# -*- coding: utf-8 -*-
"""
BreadcrumbAccumulator - Accumulates breadcrumb positions across refresh cycles.

This module provides the BreadcrumbAccumulator class which solves two critical issues:
1. **Disappearing breadcrumbs**: Old breadcrumbs no longer vanish over time
2. **Performance**: Enables incremental fetching (99%+ reduction in data transfer)

The accumulator replaces the "clear-and-replace" pattern with "accumulate-and-update",
ensuring no breadcrumb data is lost during long missions.

Part of SAR-eyo (Incremental Breadcrumb Collection) epic.

LIFE-SAFETY CRITICAL: This module preserves position data that rescuers rely on
to understand movement patterns during search operations.
"""

import bisect
import heapq
import logging
import re
import threading
from collections import defaultdict, deque
from typing import Any, Deque, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

# ISO 8601 timestamp pattern for validation
# Matches: 2026-01-04T10:00:00Z, 2026-01-04T10:00:00.123Z, 2026-01-04T10:00:00+00:00
_ISO_TIMESTAMP_PATTERN = re.compile(
    r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})?$'
)

# Capacity warning threshold
_CAPACITY_WARNING_THRESHOLD = 0.8


class BreadcrumbAccumulator:
    """
    Accumulates breadcrumb positions across refresh cycles without data loss.

    This class maintains a deduplicated, memory-bounded collection of breadcrumb
    positions across multiple devices. It enables incremental fetching by tracking
    the latest timestamp per device.

    Key features:
    - Deduplication by (device_id, timestamp) key
    - FIFO eviction when memory limit reached (oldest positions removed first)
    - Thread-safe for async refresh operations
    - Positions returned sorted by timestamp
    - O(1) eviction using deque and heap-based tracking

    Usage:
        accumulator = BreadcrumbAccumulator(max_positions=100_000)

        # Add positions from provider
        added = accumulator.add(positions_from_fetch)

        # Get latest timestamps for next incremental fetch
        timestamps = accumulator.get_latest_timestamps()

        # Get all positions for preprocessing
        all_positions = accumulator.get_all()

    Args:
        max_positions: Maximum positions to store (default 100,000).
                      Oldest positions evicted when exceeded.
    """

    def __init__(self, max_positions: int = 100_000):
        """Initialize the accumulator with a maximum position limit.

        Args:
            max_positions: Maximum number of positions to store across all devices.
                          When exceeded, oldest positions are evicted (FIFO).
        """
        self._max_positions = max(1, max_positions)  # Clamp to at least 1

        # Use deque for O(1) popleft during eviction
        self._positions: Dict[str, Deque[Dict]] = defaultdict(deque)

        # Deduplication set
        self._seen_keys: Set[Tuple[str, str]] = set()

        self._total_count = 0
        self._lock = threading.RLock()

        # Statistics
        self._total_added = 0
        self._total_duplicates_rejected = 0
        self._total_evicted = 0
        self._malformed_positions = 0

        # Rate-limiting for capacity warning
        self._capacity_warning_logged = False

    def _make_key(self, pos: Dict) -> Tuple[str, str]:
        """Create deduplication key from position dict.

        Key is (device_id, timestamp) tuple. Both are converted to strings
        to handle numeric device IDs gracefully.

        Args:
            pos: Position dictionary with device_id and ts fields.

        Returns:
            Tuple of (device_id_str, timestamp_str) for deduplication.
        """
        device_id = str(pos.get('device_id', ''))
        timestamp = str(pos.get('ts', ''))
        return (device_id, timestamp)

    def _validate_timestamp(self, ts: str) -> bool:
        """Validate that timestamp is ISO 8601 format for correct sorting.

        ISO 8601 timestamps sort correctly as strings lexicographically.
        Non-ISO formats could cause incorrect eviction order.

        Args:
            ts: Timestamp string to validate.

        Returns:
            True if valid ISO 8601 format, False otherwise.
        """
        if not ts:
            return False
        return bool(_ISO_TIMESTAMP_PATTERN.match(ts))

    def _enforce_limit(self) -> None:
        """Evict oldest positions when over the memory limit.

        Uses FIFO (First In, First Out) eviction strategy with O(n log n) heap.
        Removes oldest position globally (across all devices) until under limit.
        """
        while self._total_count > self._max_positions:
            # Build heap of (oldest_ts, device_id) for all devices with positions
            # This is O(devices) but only when eviction is needed
            candidates = []
            for device_id, positions in self._positions.items():
                if positions:
                    oldest_ts = positions[0].get('ts', '')
                    heapq.heappush(candidates, (oldest_ts, device_id))

            if not candidates:
                # Safety check - shouldn't happen, log error
                logger.error(
                    "BreadcrumbAccumulator: _enforce_limit found no candidates "
                    "but _total_count=%d > 0. Data inconsistency detected.",
                    self._total_count
                )
                # Reset count to match reality
                self._total_count = sum(len(d) for d in self._positions.values())
                break

            # Pop from device with oldest timestamp
            _, oldest_device = heapq.heappop(candidates)

            if self._positions[oldest_device]:
                # O(1) popleft from deque
                removed = self._positions[oldest_device].popleft()
                removed_key = self._make_key(removed)
                self._seen_keys.discard(removed_key)
                self._total_count -= 1
                self._total_evicted += 1

                # Clean up empty device entries
                if not self._positions[oldest_device]:
                    del self._positions[oldest_device]

    def _insert_sorted(self, device_deque: Deque[Dict], pos: Dict) -> None:
        """Insert position into deque maintaining sorted order by timestamp.

        Uses binary search for O(log n) insertion point finding.
        Since deque doesn't support efficient mid-insertion, we only
        optimize for the common case (appending newer positions).

        Args:
            device_deque: The device's position deque.
            pos: Position to insert.
        """
        ts = pos.get('ts', '')

        # Fast path: if deque is empty or new position is newest, append
        if not device_deque or ts >= device_deque[-1].get('ts', ''):
            device_deque.append(pos)
            return

        # Slow path: need to insert in middle (rare case)
        # Convert to list, insert, convert back
        # This is O(n) but should be rare in practice
        positions_list = list(device_deque)
        timestamps = [p.get('ts', '') for p in positions_list]
        insert_idx = bisect.bisect_left(timestamps, ts)
        positions_list.insert(insert_idx, pos)

        device_deque.clear()
        device_deque.extend(positions_list)

    def add(self, positions: Optional[List[Dict]]) -> int:
        """Add new positions, deduplicating by (device_id, timestamp).

        Positions already seen (same device_id and timestamp) are rejected.
        When memory limit is exceeded, oldest positions are evicted.

        Validates that positions have required fields and logs warnings for
        malformed data (missing coordinates or invalid timestamps).

        Args:
            positions: List of position dictionaries. Each should have:
                      - device_id: Device identifier (string or numeric)
                      - ts: ISO 8601 timestamp string (REQUIRED for correct ordering)
                      - lat, lon: Coordinates (REQUIRED for meaningful position data)

        Returns:
            Count of NEW positions actually added (duplicates not counted).
        """
        if positions is None or len(positions) == 0:
            return 0

        added_count = 0
        devices_modified: Set[str] = set()

        with self._lock:
            for pos in positions:
                # Validate required fields
                ts = pos.get('ts')
                device_id_raw = pos.get('device_id')

                # SAFETY FIX: Reject positions without device_id to prevent collision
                # Empty string device_id would cause different devices to collide
                if device_id_raw is None or str(device_id_raw).strip() == '':
                    self._malformed_positions += 1
                    logger.error(
                        "Position missing device_id - SKIPPING to prevent data collision: ts=%s",
                        ts
                    )
                    continue

                # SAFETY FIX: Reject positions without valid timestamp
                # Invalid timestamps corrupt FIFO eviction order, causing wrong positions
                # to be evicted (old kept, new evicted = data loss)
                ts_str = str(ts) if ts is not None else ''
                if not ts_str:
                    self._malformed_positions += 1
                    logger.error(
                        "Position missing timestamp - SKIPPING: device_id=%s",
                        device_id_raw
                    )
                    continue

                if not self._validate_timestamp(ts_str):
                    self._malformed_positions += 1
                    logger.error(
                        "Position has non-ISO timestamp - SKIPPING to prevent ordering corruption: "
                        "device_id=%s, ts=%s",
                        device_id_raw, ts_str
                    )
                    continue

                # Warn about missing coordinates (safety-critical data, but don't reject)
                if 'lat' not in pos or 'lon' not in pos:
                    self._malformed_positions += 1
                    logger.warning(
                        "Position missing coordinates: device_id=%s, ts=%s",
                        device_id_raw, ts
                    )

                key = self._make_key(pos)

                # Skip if already seen
                if key in self._seen_keys:
                    self._total_duplicates_rejected += 1
                    continue

                # Add position
                device_id = str(device_id_raw)
                self._insert_sorted(self._positions[device_id], pos)
                self._seen_keys.add(key)
                self._total_count += 1
                self._total_added += 1
                added_count += 1
                devices_modified.add(device_id)

            # Enforce memory limit
            self._enforce_limit()

            # Rate-limited capacity warning (only log once when crossing threshold)
            capacity_ratio = self._total_count / self._max_positions
            if capacity_ratio >= _CAPACITY_WARNING_THRESHOLD:
                if not self._capacity_warning_logged:
                    logger.warning(
                        "BreadcrumbAccumulator at %.1f%% capacity (%d/%d positions)",
                        capacity_ratio * 100,
                        self._total_count,
                        self._max_positions
                    )
                    self._capacity_warning_logged = True
            else:
                # Reset flag when back under threshold
                self._capacity_warning_logged = False

        return added_count

    def get_all(self) -> List[Dict]:
        """Get all accumulated positions across all devices.

        Returns copies of position dictionaries to prevent external code
        from corrupting internal state.

        Returns:
            List of all position dictionaries (copies). Positions are sorted
            by timestamp within each device's contribution, but the overall
            list merges all devices in arbitrary device order.
        """
        with self._lock:
            all_positions = []
            for positions in self._positions.values():
                # Return copies to prevent external mutation
                all_positions.extend(dict(p) for p in positions)
            return all_positions

    def get_device_positions(self, device_id: str) -> List[Dict]:
        """Get positions for a specific device, sorted by timestamp.

        Returns copies of position dictionaries to prevent external code
        from corrupting internal state.

        Args:
            device_id: Device identifier (will be converted to string).

        Returns:
            List of position dictionaries (copies) for the device, sorted
            by timestamp. Empty list if device not found.
        """
        device_id_str = str(device_id)

        with self._lock:
            positions = self._positions.get(device_id_str, deque())
            # Return copies to prevent external modification
            return [dict(p) for p in positions]

    def get_latest_timestamps(self) -> Dict[str, str]:
        """Get the latest timestamp per device for incremental fetching.

        Used by providers to determine the 'from' time for the next fetch.
        Only positions newer than these timestamps need to be fetched.

        Returns:
            Dictionary mapping device_id to latest ISO timestamp string.
            Empty dict if no positions accumulated. Devices with empty
            timestamps are excluded.
        """
        with self._lock:
            result = {}
            for device_id, positions in self._positions.items():
                if positions:
                    # Positions are sorted, so last one is latest
                    latest_ts = positions[-1].get('ts', '')
                    if latest_ts:  # Only include if timestamp is non-empty
                        result[device_id] = latest_ts
            return result

    def clear(self) -> None:
        """Clear all accumulated positions (mission reset).

        Call this when starting a new mission to reset the accumulator.
        """
        with self._lock:
            self._positions.clear()
            self._seen_keys.clear()
            self._total_count = 0

            # Reset statistics
            self._total_added = 0
            self._total_duplicates_rejected = 0
            self._total_evicted = 0
            self._malformed_positions = 0

            # Reset capacity warning
            self._capacity_warning_logged = False

            logger.info("BreadcrumbAccumulator cleared")

    def clear_device(self, device_id: str) -> None:
        """Clear data for a specific device.

        Args:
            device_id: Device identifier to clear (will be converted to string).
        """
        device_id_str = str(device_id)

        with self._lock:
            if device_id_str in self._positions:
                # Remove keys from seen set
                for pos in self._positions[device_id_str]:
                    key = self._make_key(pos)
                    self._seen_keys.discard(key)

                # Update count
                self._total_count -= len(self._positions[device_id_str])

                # Remove device data
                del self._positions[device_id_str]

                logger.debug("BreadcrumbAccumulator cleared device %s", device_id_str)

    def stats(self) -> Dict[str, Any]:
        """Return statistics for diagnostics and monitoring.

        Returns:
            Dictionary with:
            - total_positions: Current count of accumulated positions
            - device_count: Number of unique devices
            - max_positions: Configured limit
            - positions_per_device: Dict mapping device_id to position count
            - total_added: Lifetime count of positions added
            - total_duplicates_rejected: Lifetime count of duplicates rejected
            - total_evicted: Lifetime count of positions evicted due to limit
            - malformed_positions: Count of positions missing coordinates
            - capacity_percent: Current usage as percentage of limit
        """
        with self._lock:
            positions_per_device = {
                device_id: len(positions)
                for device_id, positions in self._positions.items()
            }

            capacity_percent = (
                (self._total_count / self._max_positions) * 100
                if self._max_positions > 0 else 0
            )

            return {
                'total_positions': self._total_count,
                'device_count': len(self._positions),
                'max_positions': self._max_positions,
                'positions_per_device': positions_per_device,
                'total_added': self._total_added,
                'total_duplicates_rejected': self._total_duplicates_rejected,
                'total_evicted': self._total_evicted,
                'malformed_positions': self._malformed_positions,
                'capacity_percent': round(capacity_percent, 1),
            }

    def __len__(self) -> int:
        """Return total number of accumulated positions."""
        with self._lock:
            return self._total_count

    def __repr__(self) -> str:
        """Return string representation for debugging."""
        with self._lock:
            return (
                f"BreadcrumbAccumulator("
                f"positions={self._total_count}, "
                f"devices={len(self._positions)}, "
                f"max={self._max_positions})"
            )
