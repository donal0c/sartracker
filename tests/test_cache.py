# -*- coding: utf-8 -*-
"""
Tests for LRU+TTL Cache Module.

These tests verify the ACTUAL utils/cache.py production code that provides
bounded caching for memory stability during long SAR missions.

Value: Tests memory management that prevents unbounded growth and stale data.
Bugs here cause memory leaks or serving stale position data.
"""

import time
import threading
import pytest
from utils.cache import LRUTTLCache


class TestBasicOperations:
    """Tests for core get/set/delete operations."""

    def test_set_and_get_returns_value(self):
        """Basic set/get roundtrip works."""
        cache = LRUTTLCache(max_size=10)
        cache.set('key1', 'value1')

        assert cache.get('key1') == 'value1'

    def test_get_missing_key_returns_none(self):
        """Missing key returns None, not raises."""
        cache = LRUTTLCache(max_size=10)

        assert cache.get('nonexistent') is None

    def test_delete_removes_entry(self):
        """Delete removes entry and returns True."""
        cache = LRUTTLCache(max_size=10)
        cache.set('key1', 'value1')

        result = cache.delete('key1')

        assert result is True
        assert cache.get('key1') is None

    def test_delete_missing_returns_false(self):
        """Delete on missing key returns False."""
        cache = LRUTTLCache(max_size=10)

        result = cache.delete('nonexistent')

        assert result is False

    def test_pop_returns_and_removes(self):
        """Pop returns value and removes entry."""
        cache = LRUTTLCache(max_size=10)
        cache.set('key1', 'value1')

        result = cache.pop('key1')

        assert result == 'value1'
        assert cache.get('key1') is None

    def test_clear_removes_all_entries(self):
        """Clear empties the cache."""
        cache = LRUTTLCache(max_size=10)
        cache.set('key1', 'value1')
        cache.set('key2', 'value2')

        cache.clear()

        assert len(cache) == 0


class TestLRUEviction:
    """Tests for LRU (Least Recently Used) eviction - prevents memory growth."""

    def test_evicts_oldest_when_full(self):
        """Cache evicts LRU entry when at capacity - critical for memory bounds."""
        cache = LRUTTLCache(max_size=3)
        cache.set('a', 1)
        cache.set('b', 2)
        cache.set('c', 3)

        # Cache full, adding d should evict 'a' (oldest)
        cache.set('d', 4)

        assert cache.get('a') is None  # Evicted
        assert cache.get('b') == 2
        assert cache.get('c') == 3
        assert cache.get('d') == 4
        assert len(cache) == 3

    def test_access_updates_lru_order(self):
        """Accessing entry moves it to most-recently-used."""
        cache = LRUTTLCache(max_size=3)
        cache.set('a', 1)
        cache.set('b', 2)
        cache.set('c', 3)

        # Access 'a' - moves it to most recent
        cache.get('a')

        # Adding 'd' should now evict 'b' (oldest after 'a' was accessed)
        cache.set('d', 4)

        assert cache.get('a') == 1  # Still present - was accessed
        assert cache.get('b') is None  # Evicted as LRU
        assert cache.get('c') == 3
        assert cache.get('d') == 4

    def test_update_existing_does_not_evict(self):
        """Updating existing key doesn't cause spurious eviction."""
        cache = LRUTTLCache(max_size=3)
        cache.set('a', 1)
        cache.set('b', 2)
        cache.set('c', 3)

        # Update 'a' - should not evict anything
        cache.set('a', 100)

        assert len(cache) == 3
        assert cache.get('a') == 100
        assert cache.get('b') == 2
        assert cache.get('c') == 3

    def test_max_size_one_evicts_immediately(self):
        """Edge case: max_size=1 evicts on every new key."""
        cache = LRUTTLCache(max_size=1)
        cache.set('a', 1)
        cache.set('b', 2)

        assert len(cache) == 1
        assert cache.get('a') is None
        assert cache.get('b') == 2

    def test_lru_eviction_counted_in_stats(self):
        """LRU evictions are tracked for diagnostics."""
        cache = LRUTTLCache(max_size=2)
        cache.set('a', 1)
        cache.set('b', 2)
        cache.set('c', 3)  # Evicts 'a'

        stats = cache.get_stats()
        assert stats['evictions_lru'] == 1


class TestTTLExpiration:
    """Tests for TTL (time-to-live) expiration - prevents stale data."""

    def test_expired_entry_returns_none(self):
        """Entry returns None after TTL expires - prevents stale position data."""
        cache = LRUTTLCache(max_size=10, ttl_seconds=1)
        cache.set('key1', 'value1')

        # Wait for expiration
        time.sleep(1.1)

        assert cache.get('key1') is None

    def test_fresh_entry_not_expired(self):
        """Entry within TTL returns value."""
        cache = LRUTTLCache(max_size=10, ttl_seconds=10)
        cache.set('key1', 'value1')

        # Immediate access - not expired
        assert cache.get('key1') == 'value1'

    def test_evict_expired_removes_old_entries(self):
        """evict_expired() bulk removes expired entries."""
        cache = LRUTTLCache(max_size=10, ttl_seconds=1)
        cache.set('old1', 1)
        cache.set('old2', 2)
        time.sleep(1.1)
        cache.set('fresh', 3)

        evicted = cache.evict_expired()

        assert evicted == 2
        assert len(cache) == 1
        assert cache.get('fresh') == 3

    def test_ttl_zero_disables_expiration(self):
        """TTL=0 means entries never expire by time."""
        cache = LRUTTLCache(max_size=10, ttl_seconds=0)
        cache.set('key1', 'value1')

        # Would normally expire, but TTL=0 disables
        time.sleep(0.1)

        assert cache.get('key1') == 'value1'

    def test_ttl_expiration_counted_in_stats(self):
        """TTL evictions are tracked for diagnostics."""
        cache = LRUTTLCache(max_size=10, ttl_seconds=1)
        cache.set('key1', 'value1')
        time.sleep(1.1)
        cache.get('key1')  # Triggers TTL eviction check

        stats = cache.get_stats()
        assert stats['evictions_ttl'] == 1


class TestStatistics:
    """Tests for hit/miss/eviction statistics - critical for diagnostics."""

    def test_hit_miss_tracking(self):
        """Hits and misses are counted accurately."""
        cache = LRUTTLCache(max_size=10)
        cache.set('key1', 'value1')

        cache.get('key1')  # Hit
        cache.get('key1')  # Hit
        cache.get('missing')  # Miss

        stats = cache.get_stats()
        assert stats['hits'] == 2
        assert stats['misses'] == 1

    def test_hit_rate_calculation(self):
        """Hit rate percentage is calculated correctly."""
        cache = LRUTTLCache(max_size=10)
        cache.set('key1', 'value1')

        cache.get('key1')  # Hit
        cache.get('key1')  # Hit
        cache.get('missing')  # Miss
        cache.get('missing2')  # Miss

        stats = cache.get_stats()
        assert stats['hit_rate_percent'] == 50.0  # 2 hits / 4 total

    def test_reset_stats_clears_counters(self):
        """reset_stats() clears all counters."""
        cache = LRUTTLCache(max_size=10)
        cache.set('key1', 'value1')
        cache.get('key1')
        cache.get('missing')

        cache.reset_stats()

        stats = cache.get_stats()
        assert stats['hits'] == 0
        assert stats['misses'] == 0

    def test_stats_includes_size_info(self):
        """Stats includes current and max size."""
        cache = LRUTTLCache(max_size=50, ttl_seconds=3600)
        cache.set('key1', 'value1')
        cache.set('key2', 'value2')

        stats = cache.get_stats()

        assert stats['size'] == 2
        assert stats['max_size'] == 50
        assert stats['ttl_seconds'] == 3600


class TestThreadSafety:
    """Tests for thread-safe concurrent access - critical for async polling."""

    def test_concurrent_writes_dont_corrupt(self):
        """Concurrent writes don't corrupt cache state."""
        cache = LRUTTLCache(max_size=100)
        errors = []

        def writer(thread_id):
            try:
                for i in range(50):
                    cache.set(f't{thread_id}_k{i}', i)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=writer, args=(i,)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        # Cache should have at most max_size entries
        assert len(cache) <= 100

    def test_concurrent_read_write_safe(self):
        """Mixed reads and writes are thread-safe."""
        cache = LRUTTLCache(max_size=50)
        errors = []

        # Pre-populate
        for i in range(20):
            cache.set(f'key{i}', i)

        def reader():
            try:
                for i in range(100):
                    cache.get(f'key{i % 20}')
            except Exception as e:
                errors.append(e)

        def writer():
            try:
                for i in range(100):
                    cache.set(f'new_key{i}', i)
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


class TestEdgeCases:
    """Tests for edge cases and boundary conditions."""

    def test_negative_max_size_clamped_to_one(self):
        """Negative max_size is clamped to 1."""
        cache = LRUTTLCache(max_size=-5)

        # Should work with effective max_size of 1
        cache.set('a', 1)
        cache.set('b', 2)

        assert len(cache) == 1
        assert cache.get('b') == 2

    def test_negative_ttl_clamped_to_zero(self):
        """Negative TTL is clamped to 0 (disabled)."""
        cache = LRUTTLCache(max_size=10, ttl_seconds=-5)

        cache.set('key', 'value')
        time.sleep(0.1)

        # Should still be present - TTL disabled
        assert cache.get('key') == 'value'

    def test_contains_operator(self):
        """'in' operator works correctly."""
        cache = LRUTTLCache(max_size=10)
        cache.set('key1', 'value1')

        assert 'key1' in cache
        assert 'missing' not in cache

    def test_keys_values_items_accessors(self):
        """Collection accessors return correct data."""
        cache = LRUTTLCache(max_size=10)
        cache.set('a', 1)
        cache.set('b', 2)

        keys = cache.keys()
        assert set(keys) == {'a', 'b'}

        values = cache.values()
        assert len(values) == 2

        items = cache.items()
        assert len(items) == 2
