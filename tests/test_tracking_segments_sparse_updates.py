# -*- coding: utf-8 -*-
"""
Regression tests for sparse-update breadcrumb segmentation.

Breadcrumb layers are LineStrings. If the device update interval is greater than
time_gap_minutes (default 5), naive segmentation can yield zero drawable segments
even when multiple points exist. This test ensures we still generate minimal
adjacent-pair segments so operators see movement history.
"""

import sys
import types
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent

# Provide lightweight package stubs so importing controllers.* doesn't pull heavy QGIS deps
if "controllers" not in sys.modules:
    controllers_pkg = types.ModuleType("controllers")
    controllers_pkg.__path__ = [str(ROOT / "controllers")]
    sys.modules["controllers"] = controllers_pkg

if "controllers.layer_managers" not in sys.modules:
    lm_pkg = types.ModuleType("controllers.layer_managers")
    lm_pkg.__path__ = [str(ROOT / "controllers" / "layer_managers")]
    sys.modules["controllers.layer_managers"] = lm_pkg

from controllers.layer_managers.tracking_segments import build_segments_from_positions  # noqa: E402


class TestSparseUpdateSegmentation(unittest.TestCase):
    def test_sparse_updates_produce_adjacent_pair_segment(self):
        positions = [
            {"device_id": "team1", "name": "Team 1", "ts": "2024-01-01T00:00:00Z", "lat": 51.1, "lon": -9.1},
            # 10 minute gap with default 5 minute threshold
            {"device_id": "team1", "name": "Team 1", "ts": "2024-01-01T00:10:00Z", "lat": 51.2, "lon": -9.2},
        ]

        segments = build_segments_from_positions(positions, time_gap_minutes=5)

        self.assertEqual(len(segments), 1)
        self.assertEqual(segments[0]["device_id"], "team1")
        self.assertEqual(len(segments[0]["points"]), 2)

    def test_mixed_updates_do_not_connect_across_gap_when_drawable_segment_exists(self):
        positions = [
            {"device_id": "team1", "name": "Team 1", "ts": "2024-01-01T00:00:00Z", "lat": 51.1, "lon": -9.1},
            {"device_id": "team1", "name": "Team 1", "ts": "2024-01-01T00:02:00Z", "lat": 51.11, "lon": -9.11},
            # Gap beyond threshold; last point is isolated
            {"device_id": "team1", "name": "Team 1", "ts": "2024-01-01T00:12:00Z", "lat": 51.2, "lon": -9.2},
        ]

        segments = build_segments_from_positions(positions, time_gap_minutes=5)

        # Only the first two points should form a segment; we should not connect 00:02 -> 00:12.
        self.assertEqual(len(segments), 1)
        self.assertEqual(len(segments[0]["points"]), 2)
        self.assertEqual(segments[0]["points"][0]["ts"], "2024-01-01T00:00:00Z")
        self.assertEqual(segments[0]["points"][1]["ts"], "2024-01-01T00:02:00Z")

