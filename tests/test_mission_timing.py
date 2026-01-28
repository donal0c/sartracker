# -*- coding: utf-8 -*-
"""
Mission timing calculation tests.

Tests the mission elapsed/active time calculations used to display
mission duration to coordinators during SAR operations.

VALUE: Wrong timing = coordinators see incorrect mission duration,
affecting operational decisions and handover timing.

These tests verify:
- Elapsed time calculation from mission start
- Active time calculation (elapsed minus paused)
- Pause/resume timing accumulation
- Midnight crossing edge cases
- Long mission precision (24+ hours)
"""
import sys
import types
import threading
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from enum import Enum
from pathlib import Path
from typing import Optional

import pytest

ROOT = Path(__file__).resolve().parent.parent

# Add sartracker root to path
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# =============================================================================
# Stubs for Qt dependencies
# =============================================================================

def _setup_qt_stubs():
    """Stub PyQt so we can import MissionController."""
    if "qgis" not in sys.modules:
        qgis_pkg = types.ModuleType("qgis")
        qgis_pkg.__path__ = []
        sys.modules["qgis"] = qgis_pkg

    if "qgis.PyQt" not in sys.modules:
        pyqt = types.ModuleType("qgis.PyQt")
        pyqt.__path__ = []
        sys.modules["qgis.PyQt"] = pyqt

    if "qgis.PyQt.QtCore" not in sys.modules:
        qtcore = types.ModuleType("qgis.PyQt.QtCore")

        class QObjectStub:
            def __init__(self, parent=None):
                pass

        class QSettingsStub:
            _data = {}

            def value(self, key, default=None, type=None):
                return self._data.get(key, default)

            def setValue(self, key, value):
                self._data[key] = value

            def remove(self, key):
                self._data.pop(key, None)

        class SignalStub:
            def connect(self, callback):
                pass
            def disconnect(self, callback=None):
                pass
            def emit(self, *args):
                pass

        class QTimerStub:
            def __init__(self, parent=None):
                self._interval = 0
                self._timeout = SignalStub()

            def setInterval(self, ms):
                self._interval = ms

            @property
            def timeout(self):
                return self._timeout

            def start(self):
                pass

            def stop(self):
                pass

            def isActive(self):
                return False

        def pyqtSignal(*args, **kwargs):
            class SignalStub:
                def emit(self, *args):
                    pass
                def connect(self, callback):
                    pass
                def disconnect(self, callback=None):
                    pass
            return SignalStub()

        qtcore.QObject = QObjectStub
        qtcore.QSettings = QSettingsStub
        qtcore.QTimer = QTimerStub
        qtcore.pyqtSignal = pyqtSignal
        sys.modules["qgis.PyQt.QtCore"] = qtcore


_setup_qt_stubs()

# Stub the controllers package to prevent other imports
if "controllers" not in sys.modules:
    controllers_pkg = types.ModuleType("controllers")
    controllers_pkg.__path__ = [str(ROOT / "controllers")]
    sys.modules["controllers"] = controllers_pkg

# Now import directly from the file, bypassing __init__.py
import importlib.util
spec = importlib.util.spec_from_file_location(
    "controllers.mission_controller",
    ROOT / "controllers" / "mission_controller.py"
)
mission_controller_mod = importlib.util.module_from_spec(spec)
sys.modules["controllers.mission_controller"] = mission_controller_mod
spec.loader.exec_module(mission_controller_mod)

MissionController = mission_controller_mod.MissionController
MissionState = mission_controller_mod.MissionState
MissionTiming = mission_controller_mod.MissionTiming


# =============================================================================
# Test Fixtures
# =============================================================================

@pytest.fixture
def controller():
    """Create a fresh MissionController for testing."""
    return MissionController()


def make_utc(year, month, day, hour=0, minute=0, second=0):
    """Helper to create UTC datetime."""
    return datetime(year, month, day, hour, minute, second, tzinfo=timezone.utc)


# =============================================================================
# Test: Basic Elapsed Time Calculation
# =============================================================================

class TestElapsedTimeCalculation:
    """Test basic elapsed time from mission start."""

    def test_no_mission_returns_zero(self, controller):
        """Before mission starts, timing should be zero."""
        timing = controller._compute_timing()
        assert timing.elapsed_seconds == 0.0
        assert timing.active_seconds == 0.0

    def test_elapsed_time_simple(self, controller):
        """Elapsed time = now - mission_start."""
        start = make_utc(2024, 6, 15, 10, 0, 0)
        now = make_utc(2024, 6, 15, 10, 30, 0)  # 30 minutes later

        controller._mission_start_ts = start
        controller._state = MissionState.ACTIVE

        timing = controller._compute_timing(now=now)

        assert timing.elapsed_seconds == pytest.approx(30 * 60, abs=1)  # 1800 seconds
        assert timing.active_seconds == pytest.approx(30 * 60, abs=1)

    def test_elapsed_time_hours(self, controller):
        """Test elapsed time over several hours."""
        start = make_utc(2024, 6, 15, 8, 0, 0)
        now = make_utc(2024, 6, 15, 14, 30, 0)  # 6.5 hours later

        controller._mission_start_ts = start
        controller._state = MissionState.ACTIVE

        timing = controller._compute_timing(now=now)

        expected = 6.5 * 60 * 60  # 23400 seconds
        assert timing.elapsed_seconds == pytest.approx(expected, abs=1)


# =============================================================================
# Test: Mission Start Override (Back-date)
# =============================================================================

class TestMissionStartOverride:
    """Test optional mission start timestamp overrides."""

    def test_start_mission_with_past_start_uses_backdated_time(self, controller):
        """Back-dated start should drive elapsed time calculations."""
        start = make_utc(2024, 6, 15, 8, 0, 0)
        now = make_utc(2024, 6, 15, 9, 0, 0)

        controller.start_mission("Backdated Mission", start_ts=start)

        timing = controller._compute_timing(now=now)

        assert timing.elapsed_seconds == pytest.approx(60 * 60, abs=1)
        assert timing.active_seconds == pytest.approx(60 * 60, abs=1)

    def test_start_mission_rejects_future_timestamp(self, controller):
        """Future start timestamps must be rejected."""
        future = datetime.now(timezone.utc) + timedelta(hours=1)

        with pytest.raises(ValueError):
            controller.start_mission("Future Mission", start_ts=future)

    def test_start_mission_rejects_naive_timestamp(self, controller):
        """Naive (non-timezone-aware) timestamps must be rejected."""
        naive = datetime(2024, 6, 15, 8, 0, 0)

        with pytest.raises(ValueError):
            controller.start_mission("Naive Mission", start_ts=naive)


# =============================================================================
# Test: Pause/Resume Timing
# =============================================================================

class TestPauseResumeTiming:
    """Test active time calculation with pauses."""

    def test_active_time_with_pause(self, controller):
        """Active time = elapsed - total paused time."""
        start = make_utc(2024, 6, 15, 10, 0, 0)
        now = make_utc(2024, 6, 15, 11, 0, 0)  # 1 hour elapsed

        controller._mission_start_ts = start
        controller._state = MissionState.ACTIVE
        controller._paused_total_seconds = 15 * 60  # 15 minutes paused

        timing = controller._compute_timing(now=now)

        assert timing.elapsed_seconds == pytest.approx(60 * 60, abs=1)  # 1 hour
        assert timing.active_seconds == pytest.approx(45 * 60, abs=1)  # 45 minutes

    def test_currently_paused_accumulates(self, controller):
        """While paused, pause time should continue accumulating."""
        start = make_utc(2024, 6, 15, 10, 0, 0)
        pause_start = make_utc(2024, 6, 15, 10, 30, 0)
        now = make_utc(2024, 6, 15, 10, 45, 0)  # 45 min elapsed, 15 min into pause

        controller._mission_start_ts = start
        controller._state = MissionState.PAUSED
        controller._pause_started_at = pause_start
        controller._paused_total_seconds = 0  # No previous pauses

        timing = controller._compute_timing(now=now)

        assert timing.elapsed_seconds == pytest.approx(45 * 60, abs=1)
        # Active = 45 - 15 = 30 minutes (only counting current pause)
        assert timing.active_seconds == pytest.approx(30 * 60, abs=1)

    def test_multiple_pauses_accumulate(self, controller):
        """Multiple pause periods should sum correctly."""
        start = make_utc(2024, 6, 15, 10, 0, 0)
        now = make_utc(2024, 6, 15, 12, 0, 0)  # 2 hours elapsed

        controller._mission_start_ts = start
        controller._state = MissionState.ACTIVE
        # Accumulated 30 minutes of previous pauses
        controller._paused_total_seconds = 30 * 60

        timing = controller._compute_timing(now=now)

        assert timing.elapsed_seconds == pytest.approx(2 * 60 * 60, abs=1)  # 2 hours
        assert timing.active_seconds == pytest.approx(90 * 60, abs=1)  # 1.5 hours


# =============================================================================
# Test: Edge Cases
# =============================================================================

class TestTimingEdgeCases:
    """Test edge cases in timing calculations."""

    def test_midnight_crossing(self, controller):
        """Mission crossing midnight should calculate correctly."""
        start = make_utc(2024, 6, 15, 23, 30, 0)  # 11:30 PM
        now = make_utc(2024, 6, 16, 0, 30, 0)  # 12:30 AM next day

        controller._mission_start_ts = start
        controller._state = MissionState.ACTIVE

        timing = controller._compute_timing(now=now)

        assert timing.elapsed_seconds == pytest.approx(60 * 60, abs=1)  # 1 hour

    def test_long_mission_24_hours(self, controller):
        """24+ hour mission should maintain precision (BUG-023)."""
        start = make_utc(2024, 6, 15, 8, 0, 0)
        now = make_utc(2024, 6, 16, 10, 0, 0)  # 26 hours later

        controller._mission_start_ts = start
        controller._state = MissionState.ACTIVE

        timing = controller._compute_timing(now=now)

        expected = 26 * 60 * 60  # 93600 seconds
        # BUG-023 fix rounds to 1 decimal place
        assert timing.elapsed_seconds == pytest.approx(expected, abs=1)

    def test_negative_time_clamped_to_zero(self, controller):
        """If clock drifts backward, time should not go negative."""
        start = make_utc(2024, 6, 15, 10, 30, 0)
        now = make_utc(2024, 6, 15, 10, 0, 0)  # Clock went backward

        controller._mission_start_ts = start
        controller._state = MissionState.ACTIVE

        timing = controller._compute_timing(now=now)

        # Should clamp to 0, not return negative
        assert timing.elapsed_seconds >= 0.0
        assert timing.active_seconds >= 0.0

    def test_active_never_exceeds_elapsed(self, controller):
        """Active time should never be greater than elapsed time."""
        start = make_utc(2024, 6, 15, 10, 0, 0)
        now = make_utc(2024, 6, 15, 11, 0, 0)

        controller._mission_start_ts = start
        controller._state = MissionState.ACTIVE
        controller._paused_total_seconds = 0

        timing = controller._compute_timing(now=now)

        assert timing.active_seconds <= timing.elapsed_seconds

    def test_precision_rounding(self, controller):
        """Times should be rounded to 1 decimal place (BUG-023 fix)."""
        start = make_utc(2024, 6, 15, 10, 0, 0)
        # Add 123.456 seconds
        now = start + timedelta(seconds=123.456)

        controller._mission_start_ts = start
        controller._state = MissionState.ACTIVE

        timing = controller._compute_timing(now=now)

        # Should be rounded to 1 decimal place
        assert timing.elapsed_seconds == 123.5 or timing.elapsed_seconds == 123.4


# =============================================================================
# Test: State Transitions
# =============================================================================

class TestMissionStateTransitions:
    """Test valid state transition matrix (BUG-064)."""

    def test_idle_can_become_active(self, controller):
        """IDLE -> ACTIVE is valid (start mission)."""
        controller._state = MissionState.IDLE
        assert controller._validate_transition(MissionState.ACTIVE)

    def test_active_can_become_paused(self, controller):
        """ACTIVE -> PAUSED is valid (pause mission)."""
        controller._state = MissionState.ACTIVE
        assert controller._validate_transition(MissionState.PAUSED)

    def test_active_can_become_finished(self, controller):
        """ACTIVE -> FINISHED is valid (end mission)."""
        controller._state = MissionState.ACTIVE
        assert controller._validate_transition(MissionState.FINISHED)

    def test_paused_can_become_active(self, controller):
        """PAUSED -> ACTIVE is valid (resume mission)."""
        controller._state = MissionState.PAUSED
        assert controller._validate_transition(MissionState.ACTIVE)

    def test_paused_can_become_finished(self, controller):
        """PAUSED -> FINISHED is valid (end while paused)."""
        controller._state = MissionState.PAUSED
        assert controller._validate_transition(MissionState.FINISHED)

    def test_finished_can_become_idle(self, controller):
        """FINISHED -> IDLE is valid (reset)."""
        controller._state = MissionState.FINISHED
        assert controller._validate_transition(MissionState.IDLE)

    def test_invalid_transition_raises(self, controller):
        """Invalid transitions should raise RuntimeError."""
        controller._state = MissionState.IDLE

        with pytest.raises(RuntimeError, match="Invalid state transition"):
            controller._validate_transition(MissionState.PAUSED)

    def test_idle_cannot_pause(self, controller):
        """IDLE -> PAUSED is invalid."""
        controller._state = MissionState.IDLE
        with pytest.raises(RuntimeError):
            controller._validate_transition(MissionState.PAUSED)

    def test_idle_cannot_finish(self, controller):
        """IDLE -> FINISHED is invalid."""
        controller._state = MissionState.IDLE
        with pytest.raises(RuntimeError):
            controller._validate_transition(MissionState.FINISHED)
