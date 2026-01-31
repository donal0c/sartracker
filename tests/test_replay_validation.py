# -*- coding: utf-8 -*-
"""
Tests for replay window validation (save-time and controller safety net).

TDD: Tests written BEFORE implementation (SAR-d39o Phase 2)

These tests verify that invalid replay configurations are rejected
at save time in the settings panel, with the controller providing
a safety net for any edge cases.
"""
import pytest
from datetime import datetime, timezone, timedelta


class TestReplayValidation:
    """Unit tests for replay window validation logic."""

    def test_valid_window_accepted(self):
        """A valid replay window (recent past, reasonable duration) is accepted."""
        from sartracker.ui.settings_panel import validate_replay_settings

        now = datetime.now(timezone.utc)
        start = now - timedelta(hours=2)
        hours = 1

        error = validate_replay_settings(start, hours, now)
        assert error is None

    def test_start_in_future_rejected(self):
        """Start time in the future is rejected."""
        from sartracker.ui.settings_panel import validate_replay_settings

        now = datetime.now(timezone.utc)
        start = now + timedelta(hours=1)  # Future
        hours = 1

        error = validate_replay_settings(start, hours, now)
        assert error is not None
        assert "future" in error.lower()

    def test_start_beyond_30_days_rejected(self):
        """Start time more than 30 days ago is rejected."""
        from sartracker.ui.settings_panel import validate_replay_settings

        now = datetime.now(timezone.utc)
        start = now - timedelta(days=31)  # 31 days ago
        hours = 1

        error = validate_replay_settings(start, hours, now)
        assert error is not None
        assert "30" in error or "days" in error.lower()

    def test_end_in_future_rejected(self):
        """End time (start + hours) in the future is rejected."""
        from sartracker.ui.settings_panel import validate_replay_settings

        now = datetime.now(timezone.utc)
        start = now - timedelta(minutes=30)  # 30 min ago
        hours = 2  # End would be 1.5 hours in the future

        error = validate_replay_settings(start, hours, now)
        assert error is not None
        assert "end" in error.lower() or "future" in error.lower()

    def test_hours_zero_rejected(self):
        """Hours = 0 is rejected."""
        from sartracker.ui.settings_panel import validate_replay_settings

        now = datetime.now(timezone.utc)
        start = now - timedelta(hours=2)
        hours = 0

        error = validate_replay_settings(start, hours, now)
        assert error is not None
        assert "hour" in error.lower()

    def test_hours_negative_rejected(self):
        """Negative hours is rejected."""
        from sartracker.ui.settings_panel import validate_replay_settings

        now = datetime.now(timezone.utc)
        start = now - timedelta(hours=2)
        hours = -1

        error = validate_replay_settings(start, hours, now)
        assert error is not None
        assert "hour" in error.lower()

    def test_hours_over_24_rejected(self):
        """Hours > 24 is rejected."""
        from sartracker.ui.settings_panel import validate_replay_settings

        now = datetime.now(timezone.utc)
        start = now - timedelta(days=2)
        hours = 25

        error = validate_replay_settings(start, hours, now)
        assert error is not None
        assert "hour" in error.lower() or "24" in error

    def test_boundary_exactly_30_days_accepted(self):
        """Start time exactly 30 days ago is accepted."""
        from sartracker.ui.settings_panel import validate_replay_settings

        now = datetime.now(timezone.utc)
        start = now - timedelta(days=30)  # Exactly 30 days
        hours = 1

        error = validate_replay_settings(start, hours, now)
        assert error is None

    def test_boundary_end_exactly_now_accepted(self):
        """End time exactly at now is accepted."""
        from sartracker.ui.settings_panel import validate_replay_settings

        now = datetime.now(timezone.utc)
        start = now - timedelta(hours=2)
        hours = 2  # End is exactly now

        error = validate_replay_settings(start, hours, now)
        assert error is None

    def test_boundary_start_exactly_now_rejected(self):
        """Start time exactly at now is rejected (end would be in future)."""
        from sartracker.ui.settings_panel import validate_replay_settings

        now = datetime.now(timezone.utc)
        start = now  # Exactly now
        hours = 1  # End would be 1 hour in future

        error = validate_replay_settings(start, hours, now)
        assert error is not None


class TestControllerValidationSafetyNet:
    """Tests for controller-level validation safety net."""

    def test_controller_rejects_start_beyond_30_days(self):
        """Controller rejects start time more than 30 days ago."""
        from sartracker.controllers.provider_controller import validate_replay_window

        now = datetime.now(timezone.utc)
        start = now - timedelta(days=31)
        hours = 1

        error = validate_replay_window(start, hours, now)
        assert error is not None
        assert "30" in error or "days" in error.lower()

    def test_controller_rejects_end_in_future(self):
        """Controller rejects end time in the future."""
        from sartracker.controllers.provider_controller import validate_replay_window

        now = datetime.now(timezone.utc)
        start = now - timedelta(minutes=30)
        hours = 2  # End in future

        error = validate_replay_window(start, hours, now)
        assert error is not None
