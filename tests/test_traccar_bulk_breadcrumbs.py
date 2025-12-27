# -*- coding: utf-8 -*-
"""
Regression tests for Traccar bulk breadcrumbs fallback (BC-TRACCAR-001).

These tests are pure-Python and do not require a live Traccar server.
They validate that when the bulk /api/positions?from&to path returns only
single points (effectively "current positions"), we fall back to per-device
queries so breadcrumbs can be drawn.
"""

import sys
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


def _bootstrap_imports():
    """
    Ensure repo root is importable as a lightweight `sartracker` package.

    Mirrors tests/conftest.py so tests can be run via `python -m unittest`
    without pytest.
    """
    root = Path(__file__).resolve().parent.parent
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    vendor_path = root / "vendor" / "site-packages"
    if vendor_path.exists() and str(vendor_path) not in sys.path:
        sys.path.insert(0, str(vendor_path))
    if "sartracker" not in sys.modules:
        pkg = types.ModuleType("sartracker")
        pkg.__path__ = [str(root)]
        sys.modules["sartracker"] = pkg


_bootstrap_imports()

from sartracker.providers.traccar_http import TraccarHttpProvider  # noqa: E402


class TestTraccarBulkBreadcrumbFallback(unittest.TestCase):
    def setUp(self):
        self.base_url = "http://test.example.com:8082"
        self.username = "testuser"
        self.password = "testpass"

    def test_bulk_payload_has_trail_history_requires_two_points(self):
        provider = TraccarHttpProvider(
            base_url=self.base_url,
            auth_type="basic",
            username=self.username,
            password=self.password,
        )

        one_each = [
            {"device_id": "1", "name": "A", "lat": 1.0, "lon": 2.0, "ts": "2025-11-15T14:30:00Z"},
            {"device_id": "2", "name": "B", "lat": 1.1, "lon": 2.1, "ts": "2025-11-15T14:31:00Z"},
        ]
        self.assertFalse(provider._bulk_payload_has_trail_history(one_each))

        two_for_one = [
            {"device_id": "1", "name": "A", "lat": 1.0, "lon": 2.0, "ts": "2025-11-15T14:30:00Z"},
            {"device_id": "1", "name": "A", "lat": 1.0, "lon": 2.0, "ts": "2025-11-15T14:31:00Z"},
        ]
        self.assertTrue(provider._bulk_payload_has_trail_history(two_for_one))

    @patch("sartracker.providers.traccar_http.concurrent.futures.as_completed")
    @patch("sartracker.providers.traccar_http.concurrent.futures.ThreadPoolExecutor")
    def test_get_breadcrumbs_bulk_single_points_falls_back_to_per_device(
        self,
        mock_executor_cls,
        mock_as_completed,
    ):
        provider = TraccarHttpProvider(
            base_url=self.base_url,
            auth_type="basic",
            username=self.username,
            password=self.password,
            breadcrumb_workers=1,
            enable_bulk_breadcrumbs=True,
        )

        provider._create_session = Mock(return_value=Mock())
        provider._load_devices = Mock(return_value={"1": "Device 1", "2": "Device 2"})

        class _Future:
            def __init__(self, value):
                self._value = value
            def result(self):
                return self._value

        class _Executor:
            def __init__(self, *args, **kwargs):
                self._futures = []
            def submit(self, fn, *args, **kwargs):
                fut = _Future(fn(*args, **kwargs))
                self._futures.append(fut)
                return fut
            def shutdown(self, wait=True, cancel_futures=False):
                return None

        executor = _Executor()
        mock_executor_cls.return_value = executor
        mock_as_completed.side_effect = lambda futures: list(futures)

        bulk_positions = [
            {"deviceId": 1, "latitude": 53.0, "longitude": -6.0, "fixTime": "2025-11-15T14:30:00Z"},
            {"deviceId": 2, "latitude": 53.1, "longitude": -6.1, "fixTime": "2025-11-15T14:31:00Z"},
        ]

        per_device_1 = [
            {"deviceId": 1, "latitude": 53.0, "longitude": -6.0, "fixTime": "2025-11-15T14:00:00Z"},
            {"deviceId": 1, "latitude": 53.0, "longitude": -6.0, "fixTime": "2025-11-15T14:10:00Z"},
        ]
        per_device_2 = [
            {"deviceId": 2, "latitude": 53.1, "longitude": -6.1, "fixTime": "2025-11-15T14:05:00Z"},
        ]

        def _http_get(path, session=None, params=None, expect_json=True):
            self.assertEqual(path, "/api/positions")
            if params and "deviceId" in params:
                return per_device_1 if str(params["deviceId"]) == "1" else per_device_2
            return bulk_positions

        provider.http_client.get = Mock(side_effect=_http_get)

        results = provider.get_breadcrumbs(since_iso="2025-11-15T13:00:00Z", session=Mock())

        self.assertEqual(len(results), 3)
        self.assertEqual([r["device_id"] for r in results].count("1"), 2)
        self.assertEqual([r["device_id"] for r in results].count("2"), 1)

