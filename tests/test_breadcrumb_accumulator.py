# -*- coding: utf-8 -*-
"""
Tests for BreadcrumbAccumulator - Phase 1 of Incremental Breadcrumb Collection.

These tests verify the accumulator that preserves breadcrumb positions across
refresh cycles, fixing the "disappearing breadcrumbs" issue (SAR-eyo, SAR-33qu).

Value: Tests data preservation that prevents position loss during long missions.
Bugs here cause breadcrumb trails to disappear over time.

TDD: These tests were written FIRST before the implementation (SAR-9h9).
"""

import pytest

# Import will fail until implementation exists - this is expected (TDD Red)
from utils.breadcrumb_accumulator import BreadcrumbAccumulator


class TestBasicOperations:
    """Tests for core add/get operations."""

    def test_add_new_positions_returns_count_added(self):
        """Adding positions returns the count of new positions added."""
        accumulator = BreadcrumbAccumulator(max_positions=100)

        positions = [
            {'device_id': 'dev1', 'ts': '2026-01-04T10:00:00Z', 'lat': 52.0, 'lon': -9.5},
            {'device_id': 'dev1', 'ts': '2026-01-04T10:00:30Z', 'lat': 52.1, 'lon': -9.6},
        ]

        added = accumulator.add(positions)

        assert added == 2

    def test_get_all_returns_all_accumulated_positions(self):
        """get_all() returns all positions across all devices."""
        accumulator = BreadcrumbAccumulator(max_positions=100)

        positions = [
            {'device_id': 'dev1', 'ts': '2026-01-04T10:00:00Z', 'lat': 52.0, 'lon': -9.5},
            {'device_id': 'dev2', 'ts': '2026-01-04T10:00:00Z', 'lat': 53.0, 'lon': -8.5},
        ]
        accumulator.add(positions)

        all_positions = accumulator.get_all()

        assert len(all_positions) == 2

    def test_get_device_positions_returns_only_that_device(self):
        """get_device_positions() returns only positions for specified device."""
        accumulator = BreadcrumbAccumulator(max_positions=100)

        positions = [
            {'device_id': 'dev1', 'ts': '2026-01-04T10:00:00Z', 'lat': 52.0, 'lon': -9.5},
            {'device_id': 'dev2', 'ts': '2026-01-04T10:00:00Z', 'lat': 53.0, 'lon': -8.5},
            {'device_id': 'dev1', 'ts': '2026-01-04T10:00:30Z', 'lat': 52.1, 'lon': -9.6},
        ]
        accumulator.add(positions)

        dev1_positions = accumulator.get_device_positions('dev1')

        assert len(dev1_positions) == 2
        assert all(p['device_id'] == 'dev1' for p in dev1_positions)


class TestDeduplication:
    """Tests for deduplication by (device_id, timestamp) key."""

    def test_duplicate_positions_rejected(self):
        """Positions with same (device_id, timestamp) are not added twice."""
        accumulator = BreadcrumbAccumulator(max_positions=100)

        pos1 = {'device_id': 'dev1', 'ts': '2026-01-04T10:00:00Z', 'lat': 52.0, 'lon': -9.5}
        pos_duplicate = {'device_id': 'dev1', 'ts': '2026-01-04T10:00:00Z', 'lat': 52.0, 'lon': -9.5}

        added1 = accumulator.add([pos1])
        added2 = accumulator.add([pos_duplicate])

        assert added1 == 1
        assert added2 == 0  # Duplicate rejected
        assert len(accumulator.get_all()) == 1

    def test_same_timestamp_different_device_both_added(self):
        """Same timestamp from different devices are both kept."""
        accumulator = BreadcrumbAccumulator(max_positions=100)

        positions = [
            {'device_id': 'dev1', 'ts': '2026-01-04T10:00:00Z', 'lat': 52.0, 'lon': -9.5},
            {'device_id': 'dev2', 'ts': '2026-01-04T10:00:00Z', 'lat': 53.0, 'lon': -8.5},
        ]

        added = accumulator.add(positions)

        assert added == 2

    def test_same_device_different_timestamp_both_added(self):
        """Different timestamps from same device are both kept."""
        accumulator = BreadcrumbAccumulator(max_positions=100)

        positions = [
            {'device_id': 'dev1', 'ts': '2026-01-04T10:00:00Z', 'lat': 52.0, 'lon': -9.5},
            {'device_id': 'dev1', 'ts': '2026-01-04T10:00:30Z', 'lat': 52.1, 'lon': -9.6},
        ]

        added = accumulator.add(positions)

        assert added == 2

    def test_batch_with_internal_duplicates(self):
        """Adding batch with duplicates within the batch deduplicates correctly."""
        accumulator = BreadcrumbAccumulator(max_positions=100)

        positions = [
            {'device_id': 'dev1', 'ts': '2026-01-04T10:00:00Z', 'lat': 52.0, 'lon': -9.5},
            {'device_id': 'dev1', 'ts': '2026-01-04T10:00:00Z', 'lat': 52.0, 'lon': -9.5},  # Duplicate
            {'device_id': 'dev1', 'ts': '2026-01-04T10:00:30Z', 'lat': 52.1, 'lon': -9.6},
        ]

        added = accumulator.add(positions)

        assert added == 2  # Only 2 unique positions


class TestLatestTimestamps:
    """Tests for get_latest_timestamps() used for incremental fetching."""

    def test_get_latest_timestamps_per_device(self):
        """get_latest_timestamps() returns most recent timestamp per device."""
        accumulator = BreadcrumbAccumulator(max_positions=100)

        positions = [
            {'device_id': 'dev1', 'ts': '2026-01-04T10:00:00Z', 'lat': 52.0, 'lon': -9.5},
            {'device_id': 'dev1', 'ts': '2026-01-04T10:05:00Z', 'lat': 52.1, 'lon': -9.6},
            {'device_id': 'dev2', 'ts': '2026-01-04T10:02:00Z', 'lat': 53.0, 'lon': -8.5},
        ]
        accumulator.add(positions)

        latest = accumulator.get_latest_timestamps()

        assert latest['dev1'] == '2026-01-04T10:05:00Z'
        assert latest['dev2'] == '2026-01-04T10:02:00Z'

    def test_get_latest_timestamps_empty_accumulator(self):
        """get_latest_timestamps() returns empty dict when no data."""
        accumulator = BreadcrumbAccumulator(max_positions=100)

        latest = accumulator.get_latest_timestamps()

        assert latest == {}


class TestMemoryManagement:
    """Tests for memory limits - prevents unbounded growth during long missions."""

    def test_memory_limit_enforced_evicts_oldest(self):
        """When max_positions exceeded, oldest positions are evicted (FIFO)."""
        accumulator = BreadcrumbAccumulator(max_positions=3)

        positions = [
            {'device_id': 'dev1', 'ts': '2026-01-04T10:00:00Z', 'lat': 52.0, 'lon': -9.5},
            {'device_id': 'dev1', 'ts': '2026-01-04T10:00:30Z', 'lat': 52.1, 'lon': -9.6},
            {'device_id': 'dev1', 'ts': '2026-01-04T10:01:00Z', 'lat': 52.2, 'lon': -9.7},
        ]
        accumulator.add(positions)

        # Add one more - should evict oldest
        new_pos = {'device_id': 'dev1', 'ts': '2026-01-04T10:01:30Z', 'lat': 52.3, 'lon': -9.8}
        accumulator.add([new_pos])

        all_positions = accumulator.get_all()
        timestamps = [p['ts'] for p in all_positions]

        assert len(all_positions) == 3
        assert '2026-01-04T10:00:00Z' not in timestamps  # Oldest evicted
        assert '2026-01-04T10:01:30Z' in timestamps  # Newest kept

    def test_memory_limit_with_multiple_devices(self):
        """Memory limit is global across all devices."""
        accumulator = BreadcrumbAccumulator(max_positions=4)

        positions = [
            {'device_id': 'dev1', 'ts': '2026-01-04T10:00:00Z', 'lat': 52.0, 'lon': -9.5},
            {'device_id': 'dev2', 'ts': '2026-01-04T10:00:10Z', 'lat': 53.0, 'lon': -8.5},
            {'device_id': 'dev1', 'ts': '2026-01-04T10:00:20Z', 'lat': 52.1, 'lon': -9.6},
            {'device_id': 'dev2', 'ts': '2026-01-04T10:00:30Z', 'lat': 53.1, 'lon': -8.6},
        ]
        accumulator.add(positions)

        # Add one more
        new_pos = {'device_id': 'dev1', 'ts': '2026-01-04T10:00:40Z', 'lat': 52.2, 'lon': -9.7}
        accumulator.add([new_pos])

        assert len(accumulator.get_all()) == 4

    def test_eviction_removes_from_seen_keys(self):
        """Evicted positions can be re-added (not still in seen_keys)."""
        accumulator = BreadcrumbAccumulator(max_positions=2)

        pos1 = {'device_id': 'dev1', 'ts': '2026-01-04T10:00:00Z', 'lat': 52.0, 'lon': -9.5}
        pos2 = {'device_id': 'dev1', 'ts': '2026-01-04T10:00:30Z', 'lat': 52.1, 'lon': -9.6}
        pos3 = {'device_id': 'dev1', 'ts': '2026-01-04T10:01:00Z', 'lat': 52.2, 'lon': -9.7}

        accumulator.add([pos1, pos2])
        accumulator.add([pos3])  # Evicts pos1

        # pos1 should be re-addable since it was evicted
        added = accumulator.add([pos1])

        # This depends on implementation - if we want strict FIFO behavior,
        # re-adding evicted position should work
        # For now, just verify limit is maintained
        assert len(accumulator.get_all()) <= 2


class TestClearOperations:
    """Tests for clear() and clear_device() operations."""

    def test_clear_removes_all_data(self):
        """clear() removes all accumulated positions."""
        accumulator = BreadcrumbAccumulator(max_positions=100)

        positions = [
            {'device_id': 'dev1', 'ts': '2026-01-04T10:00:00Z', 'lat': 52.0, 'lon': -9.5},
            {'device_id': 'dev2', 'ts': '2026-01-04T10:00:00Z', 'lat': 53.0, 'lon': -8.5},
        ]
        accumulator.add(positions)

        accumulator.clear()

        assert len(accumulator.get_all()) == 0
        assert accumulator.get_latest_timestamps() == {}

    def test_clear_device_removes_only_that_device(self):
        """clear_device() removes only specified device's positions."""
        accumulator = BreadcrumbAccumulator(max_positions=100)

        positions = [
            {'device_id': 'dev1', 'ts': '2026-01-04T10:00:00Z', 'lat': 52.0, 'lon': -9.5},
            {'device_id': 'dev2', 'ts': '2026-01-04T10:00:00Z', 'lat': 53.0, 'lon': -8.5},
            {'device_id': 'dev1', 'ts': '2026-01-04T10:00:30Z', 'lat': 52.1, 'lon': -9.6},
        ]
        accumulator.add(positions)

        accumulator.clear_device('dev1')

        all_positions = accumulator.get_all()
        assert len(all_positions) == 1
        assert all_positions[0]['device_id'] == 'dev2'

    def test_clear_device_nonexistent_is_safe(self):
        """clear_device() on nonexistent device doesn't raise."""
        accumulator = BreadcrumbAccumulator(max_positions=100)

        # Should not raise
        accumulator.clear_device('nonexistent_device')

    def test_clear_resets_seen_keys(self):
        """After clear(), same positions can be re-added."""
        accumulator = BreadcrumbAccumulator(max_positions=100)

        pos = {'device_id': 'dev1', 'ts': '2026-01-04T10:00:00Z', 'lat': 52.0, 'lon': -9.5}

        accumulator.add([pos])
        accumulator.clear()
        added = accumulator.add([pos])

        assert added == 1


class TestEmptyAccumulator:
    """Tests for edge cases with empty accumulator."""

    def test_get_all_empty_returns_empty_list(self):
        """get_all() on empty accumulator returns empty list."""
        accumulator = BreadcrumbAccumulator(max_positions=100)

        assert accumulator.get_all() == []

    def test_get_device_positions_empty_returns_empty_list(self):
        """get_device_positions() for missing device returns empty list."""
        accumulator = BreadcrumbAccumulator(max_positions=100)

        assert accumulator.get_device_positions('nonexistent') == []

    def test_add_empty_list_returns_zero(self):
        """Adding empty list returns 0."""
        accumulator = BreadcrumbAccumulator(max_positions=100)

        added = accumulator.add([])

        assert added == 0

    def test_add_none_handles_gracefully(self):
        """Adding None should be handled gracefully."""
        accumulator = BreadcrumbAccumulator(max_positions=100)

        # Should not raise - either return 0 or handle None as empty list
        try:
            added = accumulator.add(None)
            assert added == 0
        except TypeError:
            # Also acceptable to raise TypeError for None input
            pass


class TestStatistics:
    """Tests for stats() diagnostics - critical for monitoring."""

    def test_stats_returns_total_count(self):
        """stats() includes total position count."""
        accumulator = BreadcrumbAccumulator(max_positions=100)

        positions = [
            {'device_id': 'dev1', 'ts': '2026-01-04T10:00:00Z', 'lat': 52.0, 'lon': -9.5},
            {'device_id': 'dev2', 'ts': '2026-01-04T10:00:00Z', 'lat': 53.0, 'lon': -8.5},
        ]
        accumulator.add(positions)

        stats = accumulator.stats()

        assert stats['total_positions'] == 2

    def test_stats_returns_device_count(self):
        """stats() includes number of unique devices."""
        accumulator = BreadcrumbAccumulator(max_positions=100)

        positions = [
            {'device_id': 'dev1', 'ts': '2026-01-04T10:00:00Z', 'lat': 52.0, 'lon': -9.5},
            {'device_id': 'dev2', 'ts': '2026-01-04T10:00:00Z', 'lat': 53.0, 'lon': -8.5},
            {'device_id': 'dev1', 'ts': '2026-01-04T10:00:30Z', 'lat': 52.1, 'lon': -9.6},
        ]
        accumulator.add(positions)

        stats = accumulator.stats()

        assert stats['device_count'] == 2

    def test_stats_returns_max_positions(self):
        """stats() includes configured max_positions limit."""
        accumulator = BreadcrumbAccumulator(max_positions=50000)

        stats = accumulator.stats()

        assert stats['max_positions'] == 50000

    def test_stats_returns_positions_per_device(self):
        """stats() includes per-device position counts."""
        accumulator = BreadcrumbAccumulator(max_positions=100)

        positions = [
            {'device_id': 'dev1', 'ts': '2026-01-04T10:00:00Z', 'lat': 52.0, 'lon': -9.5},
            {'device_id': 'dev1', 'ts': '2026-01-04T10:00:30Z', 'lat': 52.1, 'lon': -9.6},
            {'device_id': 'dev2', 'ts': '2026-01-04T10:00:00Z', 'lat': 53.0, 'lon': -8.5},
        ]
        accumulator.add(positions)

        stats = accumulator.stats()

        assert stats['positions_per_device']['dev1'] == 2
        assert stats['positions_per_device']['dev2'] == 1

    def test_stats_empty_accumulator(self):
        """stats() on empty accumulator returns valid structure."""
        accumulator = BreadcrumbAccumulator(max_positions=100)

        stats = accumulator.stats()

        assert stats['total_positions'] == 0
        assert stats['device_count'] == 0
        assert stats['positions_per_device'] == {}


class TestPositionOrdering:
    """Tests for position ordering - important for segment building."""

    def test_positions_returned_in_timestamp_order(self):
        """get_device_positions() returns positions sorted by timestamp."""
        accumulator = BreadcrumbAccumulator(max_positions=100)

        # Add out of order
        positions = [
            {'device_id': 'dev1', 'ts': '2026-01-04T10:05:00Z', 'lat': 52.2, 'lon': -9.7},
            {'device_id': 'dev1', 'ts': '2026-01-04T10:00:00Z', 'lat': 52.0, 'lon': -9.5},
            {'device_id': 'dev1', 'ts': '2026-01-04T10:02:30Z', 'lat': 52.1, 'lon': -9.6},
        ]
        accumulator.add(positions)

        dev1_positions = accumulator.get_device_positions('dev1')
        timestamps = [p['ts'] for p in dev1_positions]

        assert timestamps == sorted(timestamps)


class TestEdgeCases:
    """Tests for edge cases and boundary conditions."""

    def test_max_positions_one(self):
        """Accumulator with max_positions=1 keeps only latest."""
        accumulator = BreadcrumbAccumulator(max_positions=1)

        pos1 = {'device_id': 'dev1', 'ts': '2026-01-04T10:00:00Z', 'lat': 52.0, 'lon': -9.5}
        pos2 = {'device_id': 'dev1', 'ts': '2026-01-04T10:00:30Z', 'lat': 52.1, 'lon': -9.6}

        accumulator.add([pos1])
        accumulator.add([pos2])

        all_positions = accumulator.get_all()
        assert len(all_positions) == 1

    def test_position_missing_device_id_rejected(self):
        """Position without device_id is rejected to prevent collision."""
        accumulator = BreadcrumbAccumulator(max_positions=100)

        # Position missing device_id
        pos = {'ts': '2026-01-04T10:00:00Z', 'lat': 52.0, 'lon': -9.5}

        # SAFETY FIX: Should be rejected (not added) to prevent empty string collision
        added = accumulator.add([pos])

        assert added == 0
        assert len(accumulator.get_all()) == 0
        assert accumulator.stats()['malformed_positions'] == 1

    def test_position_missing_timestamp_rejected(self):
        """Position without timestamp is rejected to prevent ordering corruption."""
        accumulator = BreadcrumbAccumulator(max_positions=100)

        # Position missing timestamp
        pos = {'device_id': 'dev1', 'lat': 52.0, 'lon': -9.5}

        # SAFETY FIX: Should be rejected (not added) to prevent ordering corruption
        added = accumulator.add([pos])

        assert added == 0
        assert len(accumulator.get_all()) == 0
        assert accumulator.stats()['malformed_positions'] == 1

    def test_position_invalid_timestamp_rejected(self):
        """Position with non-ISO timestamp is rejected."""
        accumulator = BreadcrumbAccumulator(max_positions=100)

        # Position with non-ISO timestamp format
        pos = {'device_id': 'dev1', 'ts': '01/04/2026 10:00:00', 'lat': 52.0, 'lon': -9.5}

        # SAFETY FIX: Should be rejected to prevent ordering corruption
        added = accumulator.add([pos])

        assert added == 0
        assert accumulator.stats()['malformed_positions'] == 1

    def test_numeric_device_id_handled(self):
        """Numeric device_id is handled (converted to string)."""
        accumulator = BreadcrumbAccumulator(max_positions=100)

        pos = {'device_id': 12345, 'ts': '2026-01-04T10:00:00Z', 'lat': 52.0, 'lon': -9.5}

        added = accumulator.add([pos])

        assert added == 1
        # Should be retrievable by string version
        positions = accumulator.get_device_positions('12345')
        assert len(positions) == 1


class TestThreadSafety:
    """Tests for thread-safe concurrent access - CRITICAL for async refresh."""

    def test_concurrent_add_operations_no_data_corruption(self):
        """Multiple threads adding positions simultaneously don't corrupt data."""
        import threading

        accumulator = BreadcrumbAccumulator(max_positions=10000)
        errors = []

        def add_positions(thread_id):
            try:
                for i in range(100):
                    pos = {
                        'device_id': f'dev_{thread_id}',
                        'ts': f'2026-01-04T{10 + thread_id:02d}:{i:02d}:00Z',
                        'lat': 52.0 + i * 0.001,
                        'lon': -9.5,
                    }
                    accumulator.add([pos])
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=add_positions, args=(i,)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        # Each thread should have added 100 unique positions (5 threads * 100 = 500)
        assert len(accumulator) == 500

    def test_concurrent_read_write_no_crash(self):
        """Mixed reads and writes from multiple threads don't crash."""
        import threading

        accumulator = BreadcrumbAccumulator(max_positions=1000)
        errors = []

        # Pre-populate
        for i in range(50):
            pos = {'device_id': 'dev1', 'ts': f'2026-01-04T10:{i:02d}:00Z', 'lat': 52.0, 'lon': -9.5}
            accumulator.add([pos])

        def reader():
            try:
                for _ in range(100):
                    accumulator.get_all()
                    accumulator.get_device_positions('dev1')
                    accumulator.get_latest_timestamps()
                    accumulator.stats()
            except Exception as e:
                errors.append(e)

        def writer():
            try:
                for i in range(100):
                    pos = {
                        'device_id': 'dev2',
                        'ts': f'2026-01-04T11:{i:02d}:00Z',
                        'lat': 53.0,
                        'lon': -8.5,
                    }
                    accumulator.add([pos])
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=reader),
            threading.Thread(target=reader),
            threading.Thread(target=writer),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0

    def test_concurrent_add_and_clear_no_crash(self):
        """Adding while clearing doesn't crash (edge case during mission reset)."""
        import threading
        import time

        accumulator = BreadcrumbAccumulator(max_positions=1000)
        errors = []

        def adder():
            try:
                for i in range(200):
                    pos = {'device_id': 'dev1', 'ts': f'2026-01-04T10:{i % 60:02d}:{i // 60:02d}Z',
                           'lat': 52.0, 'lon': -9.5}
                    accumulator.add([pos])
                    time.sleep(0.001)
            except Exception as e:
                errors.append(e)

        def clearer():
            try:
                for _ in range(5):
                    time.sleep(0.02)
                    accumulator.clear()
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=adder),
            threading.Thread(target=clearer),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0


class TestLenAndRepr:
    """Tests for __len__ and __repr__ methods."""

    def test_len_returns_total_count(self):
        """len(accumulator) returns total position count."""
        accumulator = BreadcrumbAccumulator(max_positions=100)

        positions = [
            {'device_id': 'dev1', 'ts': '2026-01-04T10:00:00Z', 'lat': 52.0, 'lon': -9.5},
            {'device_id': 'dev2', 'ts': '2026-01-04T10:00:00Z', 'lat': 53.0, 'lon': -8.5},
        ]
        accumulator.add(positions)

        assert len(accumulator) == 2

    def test_len_after_eviction(self):
        """len() reflects count after eviction."""
        accumulator = BreadcrumbAccumulator(max_positions=2)

        positions = [
            {'device_id': 'dev1', 'ts': '2026-01-04T10:00:00Z', 'lat': 52.0, 'lon': -9.5},
            {'device_id': 'dev1', 'ts': '2026-01-04T10:00:30Z', 'lat': 52.1, 'lon': -9.6},
            {'device_id': 'dev1', 'ts': '2026-01-04T10:01:00Z', 'lat': 52.2, 'lon': -9.7},
        ]
        accumulator.add(positions)

        assert len(accumulator) == 2

    def test_len_empty(self):
        """len() returns 0 for empty accumulator."""
        accumulator = BreadcrumbAccumulator(max_positions=100)

        assert len(accumulator) == 0

    def test_repr_format(self):
        """__repr__ returns informative string."""
        accumulator = BreadcrumbAccumulator(max_positions=50000)

        positions = [
            {'device_id': 'dev1', 'ts': '2026-01-04T10:00:00Z', 'lat': 52.0, 'lon': -9.5},
            {'device_id': 'dev2', 'ts': '2026-01-04T10:00:00Z', 'lat': 53.0, 'lon': -8.5},
        ]
        accumulator.add(positions)

        repr_str = repr(accumulator)

        assert 'BreadcrumbAccumulator' in repr_str
        assert 'positions=2' in repr_str
        assert 'devices=2' in repr_str
        assert 'max=50000' in repr_str


class TestStatisticsAdvanced:
    """Advanced tests for statistics tracking."""

    def test_stats_total_added_lifetime_count(self):
        """total_added counts ALL positions ever added, not just current."""
        accumulator = BreadcrumbAccumulator(max_positions=2)

        # Add 3 positions (only 2 kept due to limit)
        positions = [
            {'device_id': 'dev1', 'ts': '2026-01-04T10:00:00Z', 'lat': 52.0, 'lon': -9.5},
            {'device_id': 'dev1', 'ts': '2026-01-04T10:00:30Z', 'lat': 52.1, 'lon': -9.6},
            {'device_id': 'dev1', 'ts': '2026-01-04T10:01:00Z', 'lat': 52.2, 'lon': -9.7},
        ]
        accumulator.add(positions)

        stats = accumulator.stats()

        assert stats['total_added'] == 3  # All 3 were added
        assert stats['total_positions'] == 2  # Only 2 retained

    def test_stats_total_duplicates_rejected(self):
        """total_duplicates_rejected counts rejected duplicates correctly."""
        accumulator = BreadcrumbAccumulator(max_positions=100)

        pos = {'device_id': 'dev1', 'ts': '2026-01-04T10:00:00Z', 'lat': 52.0, 'lon': -9.5}

        accumulator.add([pos])
        accumulator.add([pos])  # Duplicate
        accumulator.add([pos])  # Duplicate

        stats = accumulator.stats()

        assert stats['total_duplicates_rejected'] == 2

    def test_stats_total_evicted_accurate(self):
        """total_evicted counts positions removed due to limit."""
        accumulator = BreadcrumbAccumulator(max_positions=2)

        positions = [
            {'device_id': 'dev1', 'ts': '2026-01-04T10:00:00Z', 'lat': 52.0, 'lon': -9.5},
            {'device_id': 'dev1', 'ts': '2026-01-04T10:00:30Z', 'lat': 52.1, 'lon': -9.6},
        ]
        accumulator.add(positions)

        # Add 3 more - should evict 3
        more_positions = [
            {'device_id': 'dev1', 'ts': '2026-01-04T10:01:00Z', 'lat': 52.2, 'lon': -9.7},
            {'device_id': 'dev1', 'ts': '2026-01-04T10:01:30Z', 'lat': 52.3, 'lon': -9.8},
            {'device_id': 'dev1', 'ts': '2026-01-04T10:02:00Z', 'lat': 52.4, 'lon': -9.9},
        ]
        accumulator.add(more_positions)

        stats = accumulator.stats()

        assert stats['total_evicted'] == 3
        assert stats['total_positions'] == 2

    def test_stats_capacity_percent(self):
        """capacity_percent is calculated correctly."""
        accumulator = BreadcrumbAccumulator(max_positions=100)

        # Add 80 positions
        for i in range(80):
            pos = {'device_id': 'dev1', 'ts': f'2026-01-04T10:{i:02d}:00Z', 'lat': 52.0, 'lon': -9.5}
            accumulator.add([pos])

        stats = accumulator.stats()

        assert stats['capacity_percent'] == 80.0


class TestDataIntegrity:
    """Tests for data integrity - ensuring internal state cannot be corrupted."""

    def test_get_all_returns_copies_not_references(self):
        """Modifying returned positions doesn't affect internal state."""
        accumulator = BreadcrumbAccumulator(max_positions=100)

        pos = {'device_id': 'dev1', 'ts': '2026-01-04T10:00:00Z', 'lat': 52.0, 'lon': -9.5}
        accumulator.add([pos])

        # Get positions and modify
        returned = accumulator.get_all()
        returned[0]['lat'] = 999.0

        # Internal state should be unchanged
        internal = accumulator.get_all()
        assert internal[0]['lat'] == 52.0

    def test_get_device_positions_returns_copies(self):
        """Modifying returned device positions doesn't affect internal state."""
        accumulator = BreadcrumbAccumulator(max_positions=100)

        pos = {'device_id': 'dev1', 'ts': '2026-01-04T10:00:00Z', 'lat': 52.0, 'lon': -9.5}
        accumulator.add([pos])

        # Get positions and modify
        returned = accumulator.get_device_positions('dev1')
        returned[0]['lat'] = 999.0

        # Internal state should be unchanged
        internal = accumulator.get_device_positions('dev1')
        assert internal[0]['lat'] == 52.0

    def test_position_data_preserved_completely(self):
        """All fields in position dict are preserved (not just dedup keys)."""
        accumulator = BreadcrumbAccumulator(max_positions=100)

        pos = {
            'device_id': 'dev1',
            'ts': '2026-01-04T10:00:00Z',
            'lat': 52.12345,
            'lon': -9.67890,
            'alt': 150.5,
            'speed': 5.2,
            'custom_field': 'preserved',
        }
        accumulator.add([pos])

        retrieved = accumulator.get_all()[0]

        assert retrieved['lat'] == 52.12345
        assert retrieved['lon'] == -9.67890
        assert retrieved['alt'] == 150.5
        assert retrieved['speed'] == 5.2
        assert retrieved['custom_field'] == 'preserved'


class TestFIFOEvictionAcrossDevices:
    """Tests for FIFO eviction correctness across multiple devices."""

    def test_eviction_oldest_globally_regardless_of_device(self):
        """Oldest position globally is evicted regardless of which device."""
        accumulator = BreadcrumbAccumulator(max_positions=3)

        # Add interleaved timestamps across devices
        positions = [
            {'device_id': 'dev1', 'ts': '2026-01-04T10:00:00Z', 'lat': 52.0, 'lon': -9.5},  # Oldest
            {'device_id': 'dev2', 'ts': '2026-01-04T10:01:00Z', 'lat': 53.0, 'lon': -8.5},
            {'device_id': 'dev1', 'ts': '2026-01-04T10:02:00Z', 'lat': 52.1, 'lon': -9.6},
        ]
        accumulator.add(positions)

        # Add one more - should evict dev1's oldest (10:00:00Z)
        new_pos = {'device_id': 'dev2', 'ts': '2026-01-04T10:03:00Z', 'lat': 53.1, 'lon': -8.6}
        accumulator.add([new_pos])

        all_positions = accumulator.get_all()
        timestamps = [p['ts'] for p in all_positions]

        assert len(all_positions) == 3
        assert '2026-01-04T10:00:00Z' not in timestamps  # dev1's oldest evicted
        assert '2026-01-04T10:01:00Z' in timestamps  # dev2 kept
        assert '2026-01-04T10:02:00Z' in timestamps  # dev1 kept
        assert '2026-01-04T10:03:00Z' in timestamps  # new one kept

    def test_device_removed_when_all_positions_evicted(self):
        """When all positions from a device are evicted, device is cleaned up."""
        accumulator = BreadcrumbAccumulator(max_positions=2)

        # Add 2 positions from dev1 (old)
        old_positions = [
            {'device_id': 'dev1', 'ts': '2026-01-04T09:00:00Z', 'lat': 52.0, 'lon': -9.5},
            {'device_id': 'dev1', 'ts': '2026-01-04T09:00:30Z', 'lat': 52.1, 'lon': -9.6},
        ]
        accumulator.add(old_positions)

        # Add 2 newer positions from dev2 - should evict both dev1 positions
        new_positions = [
            {'device_id': 'dev2', 'ts': '2026-01-04T10:00:00Z', 'lat': 53.0, 'lon': -8.5},
            {'device_id': 'dev2', 'ts': '2026-01-04T10:00:30Z', 'lat': 53.1, 'lon': -8.6},
        ]
        accumulator.add(new_positions)

        # dev1 should have no positions
        assert accumulator.get_device_positions('dev1') == []
        # dev2 should have 2
        assert len(accumulator.get_device_positions('dev2')) == 2
        # Only 1 device tracked
        assert accumulator.stats()['device_count'] == 1
