# -*- coding: utf-8 -*-
"""
Time Parsing Utilities Test Suite

Phase 2 - HTTP Plumbing & Utility Layer:
Comprehensive tests for utils/timeparse.py time parsing and manipulation functions.

Tests cover:
1. ISO8601 parsing with various timezone formats
2. Datetime formatting to UTC ISO8601
3. Time window generation
4. Gap detection between timestamps
5. Timestamp clamping to intervals
6. Time difference calculations
7. Recency checks

Run with: pytest tests/test_timeparse.py -v

Qt5/Qt6 Compatible: No Qt dependencies in tests.
"""

import unittest
from datetime import datetime, timezone, timedelta

# Import modules under test
from utils.timeparse import (
    parse_iso,
    format_iso,
    window,
    is_gap,
    clamp_to_interval,
    seconds_between,
    is_recent
)


class TestParseIso(unittest.TestCase):
    """Test ISO8601 timestamp parsing."""

    def test_parse_iso_with_z_suffix(self):
        """Test parsing timestamp with Z suffix (UTC)."""
        dt = parse_iso("2025-11-15T14:30:00Z")

        self.assertEqual(dt.year, 2025)
        self.assertEqual(dt.month, 11)
        self.assertEqual(dt.day, 15)
        self.assertEqual(dt.hour, 14)
        self.assertEqual(dt.minute, 30)
        self.assertEqual(dt.second, 0)
        self.assertEqual(dt.tzinfo, timezone.utc)

    def test_parse_iso_with_plus_zero_offset(self):
        """Test parsing timestamp with +00:00 offset (UTC)."""
        dt = parse_iso("2025-11-15T14:30:00+00:00")

        self.assertEqual(dt.hour, 14)
        self.assertEqual(dt.tzinfo, timezone.utc)

    def test_parse_iso_with_negative_offset(self):
        """Test parsing timestamp with negative timezone offset."""
        dt = parse_iso("2025-11-15T14:30:00-05:00")

        # Should be converted to UTC (14:30 - 5 hours offset = 19:30 UTC)
        self.assertEqual(dt.tzinfo, timezone.utc)
        self.assertEqual(dt.hour, 19)  # 14 + 5 = 19

    def test_parse_iso_with_positive_offset(self):
        """Test parsing timestamp with positive timezone offset."""
        dt = parse_iso("2025-11-15T14:30:00+02:00")

        # Should be converted to UTC (14:30 - 2 hours offset = 12:30 UTC)
        self.assertEqual(dt.tzinfo, timezone.utc)
        self.assertEqual(dt.hour, 12)  # 14 - 2 = 12

    def test_parse_iso_with_microseconds(self):
        """Test parsing timestamp with microseconds."""
        dt = parse_iso("2025-11-15T14:30:00.123456Z")

        self.assertEqual(dt.microsecond, 123456)
        self.assertEqual(dt.tzinfo, timezone.utc)

    def test_parse_iso_empty_string_raises(self):
        """Test parsing empty string raises ValueError."""
        with self.assertRaises(ValueError) as ctx:
            parse_iso("")

        self.assertIn("cannot be empty", str(ctx.exception))

    def test_parse_iso_invalid_format_raises(self):
        """Test parsing invalid format raises ValueError."""
        with self.assertRaises(ValueError) as ctx:
            parse_iso("not-a-valid-timestamp")  # Truly invalid format

        self.assertIn("Invalid ISO8601", str(ctx.exception))

    def test_parse_iso_non_string_raises(self):
        """Test parsing non-string raises ValueError."""
        with self.assertRaises(ValueError) as ctx:
            parse_iso(None)

        self.assertIn("cannot be empty", str(ctx.exception))

    def test_parse_iso_whitespace_trimmed(self):
        """Test parsing trims whitespace."""
        dt = parse_iso("  2025-11-15T14:30:00Z  ")

        self.assertEqual(dt.year, 2025)
        self.assertEqual(dt.tzinfo, timezone.utc)


class TestFormatIso(unittest.TestCase):
    """Test ISO8601 timestamp formatting."""

    def test_format_iso_utc_datetime(self):
        """Test formatting UTC datetime."""
        dt = datetime(2025, 11, 15, 14, 30, 0, tzinfo=timezone.utc)
        formatted = format_iso(dt)

        self.assertEqual(formatted, "2025-11-15T14:30:00Z")

    def test_format_iso_removes_microseconds(self):
        """Test formatting removes microseconds for cleaner output."""
        dt = datetime(2025, 11, 15, 14, 30, 0, 123456, tzinfo=timezone.utc)
        formatted = format_iso(dt)

        self.assertEqual(formatted, "2025-11-15T14:30:00Z")
        self.assertNotIn("123456", formatted)

    def test_format_iso_converts_non_utc_to_utc(self):
        """Test formatting converts non-UTC timezone to UTC."""
        # Create datetime in UTC+2
        tz_plus2 = timezone(timedelta(hours=2))
        dt = datetime(2025, 11, 15, 14, 30, 0, tzinfo=tz_plus2)

        formatted = format_iso(dt)

        # 14:30 in UTC+2 = 12:30 in UTC
        self.assertEqual(formatted, "2025-11-15T12:30:00Z")

    def test_format_iso_non_datetime_raises(self):
        """Test formatting non-datetime raises ValueError."""
        with self.assertRaises(ValueError) as ctx:
            format_iso("not a datetime")

        self.assertIn("must be datetime instance", str(ctx.exception))


class TestWindow(unittest.TestCase):
    """Test time window generation."""

    def test_window_returns_tuple(self):
        """Test window returns tuple of two ISO strings."""
        from_iso, to_iso = window(hours=2)

        self.assertIsInstance(from_iso, str)
        self.assertIsInstance(to_iso, str)

        # Verify both are valid ISO8601
        from_dt = parse_iso(from_iso)
        to_dt = parse_iso(to_iso)

        # Verify time difference is approximately 2 hours
        diff = to_dt - from_dt
        self.assertAlmostEqual(diff.total_seconds(), 2 * 3600, delta=1)

    def test_window_with_reference_time(self):
        """Test window with explicit reference time."""
        ref_time = datetime(2025, 11, 15, 14, 0, 0, tzinfo=timezone.utc)
        from_iso, to_iso = window(hours=1, reference_time=ref_time)

        from_dt = parse_iso(from_iso)
        to_dt = parse_iso(to_iso)

        self.assertEqual(to_dt, ref_time)
        self.assertEqual(from_dt, ref_time - timedelta(hours=1))

    def test_window_invalid_hours_raises(self):
        """Test window with invalid hours raises ValueError."""
        with self.assertRaises(ValueError) as ctx:
            window(hours=0)

        self.assertIn("must be positive integer", str(ctx.exception))

    def test_window_negative_hours_raises(self):
        """Test window with negative hours raises ValueError."""
        with self.assertRaises(ValueError) as ctx:
            window(hours=-1)

        self.assertIn("must be positive integer", str(ctx.exception))


class TestIsGap(unittest.TestCase):
    """Test gap detection between timestamps."""

    def test_is_gap_no_gap(self):
        """Test is_gap returns False when difference is below threshold."""
        result = is_gap(
            "2025-11-15T14:00:00Z",
            "2025-11-15T14:05:00Z",
            gap_minutes=10
        )

        self.assertFalse(result)

    def test_is_gap_exactly_at_threshold(self):
        """Test is_gap returns False when difference equals threshold."""
        result = is_gap(
            "2025-11-15T14:00:00Z",
            "2025-11-15T14:10:00Z",
            gap_minutes=10
        )

        self.assertFalse(result)  # Equal to threshold, not greater

    def test_is_gap_exceeds_threshold(self):
        """Test is_gap returns True when difference exceeds threshold."""
        result = is_gap(
            "2025-11-15T14:00:00Z",
            "2025-11-15T14:15:00Z",
            gap_minutes=10
        )

        self.assertTrue(result)

    def test_is_gap_large_gap(self):
        """Test is_gap with large time difference."""
        result = is_gap(
            "2025-11-15T14:00:00Z",
            "2025-11-15T16:00:00Z",
            gap_minutes=15
        )

        self.assertTrue(result)  # 120 min > 15 min

    def test_is_gap_invalid_gap_minutes_raises(self):
        """Test is_gap with invalid gap_minutes raises ValueError."""
        with self.assertRaises(ValueError) as ctx:
            is_gap(
                "2025-11-15T14:00:00Z",
                "2025-11-15T14:05:00Z",
                gap_minutes=0
            )

        self.assertIn("must be positive integer", str(ctx.exception))

    def test_is_gap_swapped_timestamps_handles_gracefully(self):
        """Test is_gap handles swapped timestamps (not chronological)."""
        # Should not crash, swap internally for comparison
        result = is_gap(
            "2025-11-15T14:15:00Z",
            "2025-11-15T14:00:00Z",
            gap_minutes=10
        )

        self.assertTrue(result)  # 15 min > 10 min


class TestClampToInterval(unittest.TestCase):
    """Test timestamp clamping to intervals."""

    def test_clamp_before_start(self):
        """Test clamping timestamp before interval start."""
        result = clamp_to_interval(
            "2025-11-15T12:00:00Z",
            "2025-11-15T14:00:00Z",
            "2025-11-15T16:00:00Z"
        )

        self.assertEqual(result, "2025-11-15T14:00:00Z")

    def test_clamp_after_end(self):
        """Test clamping timestamp after interval end."""
        result = clamp_to_interval(
            "2025-11-15T18:00:00Z",
            "2025-11-15T14:00:00Z",
            "2025-11-15T16:00:00Z"
        )

        self.assertEqual(result, "2025-11-15T16:00:00Z")

    def test_clamp_within_interval_unchanged(self):
        """Test timestamp within interval is unchanged."""
        result = clamp_to_interval(
            "2025-11-15T15:00:00Z",
            "2025-11-15T14:00:00Z",
            "2025-11-15T16:00:00Z"
        )

        self.assertEqual(result, "2025-11-15T15:00:00Z")

    def test_clamp_at_start_boundary(self):
        """Test timestamp at interval start is unchanged."""
        result = clamp_to_interval(
            "2025-11-15T14:00:00Z",
            "2025-11-15T14:00:00Z",
            "2025-11-15T16:00:00Z"
        )

        self.assertEqual(result, "2025-11-15T14:00:00Z")

    def test_clamp_at_end_boundary(self):
        """Test timestamp at interval end is unchanged."""
        result = clamp_to_interval(
            "2025-11-15T16:00:00Z",
            "2025-11-15T14:00:00Z",
            "2025-11-15T16:00:00Z"
        )

        self.assertEqual(result, "2025-11-15T16:00:00Z")

    def test_clamp_invalid_interval_raises(self):
        """Test clamping with start > end raises ValueError."""
        with self.assertRaises(ValueError) as ctx:
            clamp_to_interval(
                "2025-11-15T15:00:00Z",
                "2025-11-15T16:00:00Z",
                "2025-11-15T14:00:00Z"
            )

        self.assertIn("Invalid interval", str(ctx.exception))


class TestSecondsBetween(unittest.TestCase):
    """Test time difference calculations."""

    def test_seconds_between_positive_difference(self):
        """Test seconds_between with chronological timestamps."""
        diff = seconds_between(
            "2025-11-15T14:00:00Z",
            "2025-11-15T14:05:30Z"
        )

        self.assertEqual(diff, 330.0)  # 5 min 30 sec

    def test_seconds_between_reverse_order(self):
        """Test seconds_between with reverse order (absolute value)."""
        diff = seconds_between(
            "2025-11-15T14:05:30Z",
            "2025-11-15T14:00:00Z"
        )

        self.assertEqual(diff, 330.0)  # Absolute value

    def test_seconds_between_same_timestamp(self):
        """Test seconds_between with identical timestamps."""
        diff = seconds_between(
            "2025-11-15T14:00:00Z",
            "2025-11-15T14:00:00Z"
        )

        self.assertEqual(diff, 0.0)

    def test_seconds_between_large_difference(self):
        """Test seconds_between with large time difference."""
        diff = seconds_between(
            "2025-11-15T14:00:00Z",
            "2025-11-16T14:00:00Z"
        )

        self.assertEqual(diff, 86400.0)  # 24 hours


class TestIsRecent(unittest.TestCase):
    """Test timestamp recency checks."""

    def test_is_recent_within_threshold(self):
        """Test is_recent returns True for recent timestamp."""
        ref_time = datetime(2025, 11, 15, 14, 0, 0, tzinfo=timezone.utc)
        ts = "2025-11-15T13:50:00Z"  # 10 minutes ago

        result = is_recent(ts, max_age_minutes=15, reference_time=ref_time)

        self.assertTrue(result)

    def test_is_recent_at_threshold_boundary(self):
        """Test is_recent at exact threshold boundary."""
        ref_time = datetime(2025, 11, 15, 14, 0, 0, tzinfo=timezone.utc)
        ts = "2025-11-15T13:45:00Z"  # Exactly 15 minutes ago

        result = is_recent(ts, max_age_minutes=15, reference_time=ref_time)

        self.assertTrue(result)  # Equal to threshold

    def test_is_recent_exceeds_threshold(self):
        """Test is_recent returns False for stale timestamp."""
        ref_time = datetime(2025, 11, 15, 14, 0, 0, tzinfo=timezone.utc)
        ts = "2025-11-15T13:30:00Z"  # 30 minutes ago

        result = is_recent(ts, max_age_minutes=15, reference_time=ref_time)

        self.assertFalse(result)

    def test_is_recent_future_timestamp_returns_false(self):
        """Test is_recent with future timestamp (negative age)."""
        ref_time = datetime(2025, 11, 15, 14, 0, 0, tzinfo=timezone.utc)
        ts = "2025-11-15T14:10:00Z"  # 10 minutes in future

        result = is_recent(ts, max_age_minutes=15, reference_time=ref_time)

        self.assertFalse(result)  # Future timestamp not considered recent

    def test_is_recent_invalid_max_age_raises(self):
        """Test is_recent with invalid max_age_minutes raises ValueError."""
        with self.assertRaises(ValueError) as ctx:
            is_recent("2025-11-15T14:00:00Z", max_age_minutes=0)

        self.assertIn("must be positive integer", str(ctx.exception))


class TestRoundTripConversion(unittest.TestCase):
    """Test round-trip conversion between parse and format."""

    def test_parse_format_roundtrip(self):
        """Test parsing and formatting produces consistent result."""
        original = "2025-11-15T14:30:00Z"

        dt = parse_iso(original)
        formatted = format_iso(dt)

        self.assertEqual(formatted, original)

    def test_format_parse_roundtrip(self):
        """Test formatting and parsing produces consistent result."""
        original_dt = datetime(2025, 11, 15, 14, 30, 0, tzinfo=timezone.utc)

        formatted = format_iso(original_dt)
        parsed_dt = parse_iso(formatted)

        self.assertEqual(parsed_dt, original_dt)


# ============================================================================
# Main (for running without pytest)
# ============================================================================

def run_all_tests():
    """Run all tests manually (if pytest not available)."""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    # Load all test classes
    suite.addTests(loader.loadTestsFromTestCase(TestParseIso))
    suite.addTests(loader.loadTestsFromTestCase(TestFormatIso))
    suite.addTests(loader.loadTestsFromTestCase(TestWindow))
    suite.addTests(loader.loadTestsFromTestCase(TestIsGap))
    suite.addTests(loader.loadTestsFromTestCase(TestClampToInterval))
    suite.addTests(loader.loadTestsFromTestCase(TestSecondsBetween))
    suite.addTests(loader.loadTestsFromTestCase(TestIsRecent))
    suite.addTests(loader.loadTestsFromTestCase(TestRoundTripConversion))

    # Run tests
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    return result.wasSuccessful()


if __name__ == '__main__':
    success = run_all_tests()
    exit(0 if success else 1)
