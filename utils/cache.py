# -*- coding: utf-8 -*-
"""
Thread-safe LRU cache with TTL eviction for SAR Tracker.

MEMORY STABILITY: Provides bounded caching with automatic eviction to prevent
unbounded memory growth during long missions.

Qt5/Qt6 Compatible: Pure Python implementation, no Qt dependencies.
"""

import time
import logging
from collections import OrderedDict
from threading import RLock
from typing import Any, Dict, Optional, TypeVar, Generic, Tuple

logger = logging.getLogger(__name__)

K = TypeVar('K')
V = TypeVar('V')


class LRUTTLCache(Generic[K, V]):
    """
    Thread-safe LRU cache with TTL-based expiration.

    MEMORY STABILITY: Provides bounded caching to prevent unbounded memory
    growth. Entries are evicted when:
    - Cache exceeds max_size (LRU eviction)
    - Entry exceeds ttl_seconds (TTL eviction)

    Thread-safe for concurrent read/write access via RLock.

    Attributes:
        max_size: Maximum number of entries (default: 50)
        ttl_seconds: Time-to-live in seconds (default: 3600 = 1 hour)
    """

    def __init__(self, max_size: int = 50, ttl_seconds: int = 3600):
        """
        Initialize LRU+TTL cache.

        Args:
            max_size: Maximum number of entries before LRU eviction
            ttl_seconds: Seconds before an entry expires
        """
        self._max_size = max(1, max_size)
        self._ttl_seconds = max(0, ttl_seconds)
        self._cache: OrderedDict[K, Tuple[float, V]] = OrderedDict()
        self._lock = RLock()

        # Statistics
        self._hits = 0
        self._misses = 0
        self._evictions_lru = 0
        self._evictions_ttl = 0

    def get(self, key: K) -> Optional[V]:
        """
        Get value by key, returning None if not found or expired.

        Updates access time for LRU tracking on hit.

        Args:
            key: Cache key

        Returns:
            Cached value or None
        """
        with self._lock:
            if key not in self._cache:
                self._misses += 1
                return None

            timestamp, value = self._cache[key]

            # Check TTL expiration
            if self._ttl_seconds > 0 and (time.time() - timestamp) > self._ttl_seconds:
                del self._cache[key]
                self._evictions_ttl += 1
                self._misses += 1
                return None

            # Move to end (most recently used)
            self._cache.move_to_end(key)
            self._hits += 1
            return value

    def set(self, key: K, value: V) -> None:
        """
        Set value with current timestamp.

        Evicts LRU entry if cache is at capacity.

        Args:
            key: Cache key
            value: Value to cache
        """
        with self._lock:
            current_time = time.time()

            # Update existing or add new
            if key in self._cache:
                self._cache.move_to_end(key)
            else:
                # Evict LRU if at capacity
                while len(self._cache) >= self._max_size:
                    evicted_key, _ = self._cache.popitem(last=False)
                    self._evictions_lru += 1
                    logger.debug(f"LRU evicted: {evicted_key}")

            self._cache[key] = (current_time, value)

    def delete(self, key: K) -> bool:
        """
        Delete entry by key.

        Args:
            key: Cache key

        Returns:
            True if key was found and deleted
        """
        with self._lock:
            if key in self._cache:
                del self._cache[key]
                return True
            return False

    def clear(self) -> None:
        """Clear all cache entries."""
        with self._lock:
            self._cache.clear()

    def pop(self, key: K, default: Optional[V] = None) -> Optional[V]:
        """
        Remove and return value by key.

        Args:
            key: Cache key
            default: Default value if key not found

        Returns:
            Cached value or default
        """
        with self._lock:
            if key in self._cache:
                _, value = self._cache.pop(key)
                return value
            return default

    def __contains__(self, key: K) -> bool:
        """Check if key exists (does not update access time or check TTL)."""
        with self._lock:
            return key in self._cache

    def __len__(self) -> int:
        """Return number of cached entries."""
        with self._lock:
            return len(self._cache)

    def keys(self):
        """Return list of cache keys."""
        with self._lock:
            return list(self._cache.keys())

    def values(self):
        """Return list of cached values (timestamp, value) tuples."""
        with self._lock:
            return list(self._cache.values())

    def items(self):
        """Return list of (key, (timestamp, value)) tuples."""
        with self._lock:
            return list(self._cache.items())

    def evict_expired(self) -> int:
        """
        Remove all expired entries.

        Returns:
            Number of entries evicted
        """
        if self._ttl_seconds <= 0:
            return 0

        with self._lock:
            current_time = time.time()
            expired_keys = [
                key for key, (timestamp, _) in self._cache.items()
                if (current_time - timestamp) > self._ttl_seconds
            ]

            for key in expired_keys:
                del self._cache[key]
                self._evictions_ttl += 1

            return len(expired_keys)

    def get_stats(self) -> Dict[str, Any]:
        """
        Get cache statistics for diagnostics.

        Returns:
            Dict with hits, misses, hit_rate, size, max_size, evictions
        """
        with self._lock:
            total = self._hits + self._misses
            hit_rate = (self._hits / total * 100) if total > 0 else 0.0

            return {
                'size': len(self._cache),
                'max_size': self._max_size,
                'ttl_seconds': self._ttl_seconds,
                'hits': self._hits,
                'misses': self._misses,
                'hit_rate_percent': round(hit_rate, 1),
                'evictions_lru': self._evictions_lru,
                'evictions_ttl': self._evictions_ttl,
            }

    def reset_stats(self) -> None:
        """Reset hit/miss/eviction counters."""
        with self._lock:
            self._hits = 0
            self._misses = 0
            self._evictions_lru = 0
            self._evictions_ttl = 0


__all__ = ['LRUTTLCache']
