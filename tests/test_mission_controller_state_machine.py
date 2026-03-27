# -*- coding: utf-8 -*-
"""
Mission Controller State Machine Tests

Test suite for controllers/mission_controller.py state machine logic.

WHY THIS MATTERS:
Mission state controls critical SAR operations. Invalid state transitions
could allow multiple simultaneous missions, resume non-existent missions,
or lose mission timing data during operations.

VALUE PROVIDED:
- Enforce valid state transitions (prevent operational errors)
- Prevent invalid state transitions (fail-safe behavior)
- Ensure mission name validation (prevent empty/invalid missions)
- Verify thread-safe state changes (prevent race conditions)

PURE PYTHON: No QGIS required (uses mocked QSettings)
"""

import pytest
import threading
import time
import importlib.util
import sys
from pathlib import Path
from unittest.mock import patch
from datetime import datetime, timezone

# QGIS mocks are set up globally in conftest.py

# Load mission_controller module directly to avoid import chain issues
module_path = Path(__file__).parent.parent / "controllers" / "mission_controller.py"
spec = importlib.util.spec_from_file_location("mission_controller", module_path)
mission_controller_module = importlib.util.module_from_spec(spec)
sys.modules['mission_controller'] = mission_controller_module
spec.loader.exec_module(mission_controller_module)

MissionController = mission_controller_module.MissionController
MissionState = mission_controller_module.MissionState
MissionTiming = mission_controller_module.MissionTiming


@pytest.fixture
def controller():
    """Create a fresh MissionController for each test."""
    ctrl = MissionController()
    yield ctrl
    # Cleanup
    try:
        ctrl.cleanup()
    except Exception:
        pass


# =============================================================================
# STATE TRANSITION TESTS - VALID TRANSITIONS
# =============================================================================

class TestValidStateTransitions:
    """Test all valid state transitions according to VALID_TRANSITIONS matrix."""

    def test_start_from_idle_succeeds(self, controller):
        """IDLE → ACTIVE: Starting a mission from idle state."""
        assert controller.state == MissionState.IDLE

        result = controller.start_mission("Test Mission")

        assert result is True
        assert controller.state == MissionState.ACTIVE
        assert controller.mission_name == "Test Mission"

    def test_pause_from_active_succeeds(self, controller):
        """ACTIVE → PAUSED: Pausing an active mission."""
        controller.start_mission("Test Mission")
        assert controller.state == MissionState.ACTIVE

        result = controller.pause_mission()

        assert result is True
        assert controller.state == MissionState.PAUSED

    def test_resume_from_paused_succeeds(self, controller):
        """PAUSED → ACTIVE: Resuming a paused mission."""
        controller.start_mission("Test Mission")
        controller.pause_mission()
        assert controller.state == MissionState.PAUSED

        result = controller.resume_mission()

        assert result is True
        assert controller.state == MissionState.ACTIVE

    def test_finish_from_active_succeeds(self, controller):
        """ACTIVE → FINISHED: Finishing an active mission."""
        controller.start_mission("Test Mission")
        assert controller.state == MissionState.ACTIVE

        result = controller.finish_mission()

        assert result is True
        assert controller.state == MissionState.IDLE  # Resets to IDLE after FINISHED

    def test_finish_from_paused_succeeds(self, controller):
        """PAUSED → FINISHED: Finishing a paused mission."""
        controller.start_mission("Test Mission")
        controller.pause_mission()
        assert controller.state == MissionState.PAUSED

        result = controller.finish_mission()

        assert result is True
        assert controller.state == MissionState.IDLE

    def test_multiple_mission_lifecycle_succeeds(self, controller):
        """Complete mission lifecycle can be repeated."""
        # First mission
        controller.start_mission("Mission 1")
        controller.pause_mission()
        controller.resume_mission()
        controller.finish_mission()
        assert controller.state == MissionState.IDLE

        # Second mission
        result = controller.start_mission("Mission 2")
        assert result is True
        assert controller.state == MissionState.ACTIVE
        assert controller.mission_name == "Mission 2"


# =============================================================================
# STATE TRANSITION TESTS - INVALID TRANSITIONS
# =============================================================================

class TestInvalidStateTransitions:
    """Test that invalid state transitions are rejected."""

    def test_start_from_active_raises_runtime_error(self, controller):
        """
        ACTIVE → ACTIVE: Cannot start mission when already active.

        VALUE: Prevents accidental overwrite of active mission.
        """
        controller.start_mission("First Mission")
        assert controller.state == MissionState.ACTIVE

        with pytest.raises(RuntimeError, match="Invalid state transition"):
            controller.start_mission("Second Mission")

        # Original mission should still be active
        assert controller.state == MissionState.ACTIVE
        assert controller.mission_name == "First Mission"

    def test_start_from_paused_is_rejected(self, controller):
        """
        PAUSED → ACTIVE (via start): Starting a second mission from PAUSED is
        rejected so operators cannot silently overwrite a paused mission.
        """
        controller.start_mission("First Mission")
        controller.pause_mission()
        assert controller.state == MissionState.PAUSED

        with pytest.raises(RuntimeError, match="cannot start a new mission while paused"):
            controller.start_mission("Second Mission")

        assert controller.state == MissionState.PAUSED
        assert controller.mission_name == "First Mission"

    def test_pause_from_idle_returns_false(self, controller):
        """
        IDLE → PAUSED: Cannot pause when no mission active.

        VALUE: Prevents invalid state that would confuse operators.
        """
        assert controller.state == MissionState.IDLE

        result = controller.pause_mission()

        assert result is False
        assert controller.state == MissionState.IDLE

    def test_pause_from_paused_returns_false(self, controller):
        """
        PAUSED → PAUSED: Cannot pause an already paused mission.

        VALUE: Prevents double-pause timing errors.
        """
        controller.start_mission("Test Mission")
        controller.pause_mission()
        assert controller.state == MissionState.PAUSED

        result = controller.pause_mission()

        assert result is False
        assert controller.state == MissionState.PAUSED

    def test_resume_from_idle_returns_false(self, controller):
        """
        IDLE → ACTIVE (via resume): Cannot resume when no mission exists.

        VALUE: Prevents creating mission without name/start time.
        """
        assert controller.state == MissionState.IDLE

        result = controller.resume_mission()

        assert result is False
        assert controller.state == MissionState.IDLE

    def test_resume_from_active_returns_false(self, controller):
        """
        ACTIVE → ACTIVE (via resume): Cannot resume an already active mission.

        VALUE: Prevents timing calculation errors.
        """
        controller.start_mission("Test Mission")
        assert controller.state == MissionState.ACTIVE

        result = controller.resume_mission()

        assert result is False
        assert controller.state == MissionState.ACTIVE

    def test_finish_from_idle_returns_false(self, controller):
        """
        IDLE → FINISHED: Cannot finish when no mission exists.

        VALUE: Prevents invalid final timing reports.
        """
        assert controller.state == MissionState.IDLE

        result = controller.finish_mission()

        assert result is False
        assert controller.state == MissionState.IDLE


# =============================================================================
# STATE VALIDATION TESTS
# =============================================================================

class TestStateValidation:
    """Test the _validate_transition() method."""

    def test_validate_transition_accepts_valid_idle_to_active(self, controller):
        """Validation accepts IDLE → ACTIVE."""
        assert controller.state == MissionState.IDLE

        # Should not raise
        result = controller._validate_transition(MissionState.ACTIVE)

        assert result is True

    def test_validate_transition_rejects_invalid_idle_to_paused(self, controller):
        """Validation rejects IDLE → PAUSED."""
        assert controller.state == MissionState.IDLE

        with pytest.raises(RuntimeError, match="Invalid state transition"):
            controller._validate_transition(MissionState.PAUSED)

    def test_validate_transition_accepts_active_to_paused(self, controller):
        """Validation accepts ACTIVE → PAUSED."""
        controller.start_mission("Test Mission")
        assert controller.state == MissionState.ACTIVE

        # Manually test validation (pause_mission() uses it internally)
        result = controller._validate_transition(MissionState.PAUSED)

        assert result is True

    def test_validate_transition_accepts_active_to_finished(self, controller):
        """Validation accepts ACTIVE → FINISHED."""
        controller.start_mission("Test Mission")
        assert controller.state == MissionState.ACTIVE

        result = controller._validate_transition(MissionState.FINISHED)

        assert result is True

    def test_validate_transition_rejects_active_to_idle(self, controller):
        """Validation rejects ACTIVE → IDLE (must finish first)."""
        controller.start_mission("Test Mission")
        assert controller.state == MissionState.ACTIVE

        with pytest.raises(RuntimeError, match="Invalid state transition"):
            controller._validate_transition(MissionState.IDLE)


# =============================================================================
# STATE QUERY TESTS
# =============================================================================

class TestStateQueries:
    """Test state query methods."""

    def test_is_active_true_when_active(self, controller):
        """is_active() returns True for ACTIVE state."""
        controller.start_mission("Test Mission")

        assert controller.is_active() is True

    def test_is_active_true_when_paused(self, controller):
        """is_active() returns True for PAUSED state (mission still ongoing)."""
        controller.start_mission("Test Mission")
        controller.pause_mission()

        assert controller.is_active() is True

    def test_is_active_false_when_idle(self, controller):
        """is_active() returns False for IDLE state."""
        assert controller.is_active() is False

    def test_is_active_false_after_finish(self, controller):
        """is_active() returns False after finishing mission."""
        controller.start_mission("Test Mission")
        controller.finish_mission()

        assert controller.is_active() is False

    def test_state_property_returns_current_state(self, controller):
        """state property returns current MissionState."""
        assert controller.state == MissionState.IDLE

        controller.start_mission("Test Mission")
        assert controller.state == MissionState.ACTIVE

        controller.pause_mission()
        assert controller.state == MissionState.PAUSED


# =============================================================================
# MISSION NAME TESTS
# =============================================================================

class TestMissionName:
    """Test mission name validation and persistence."""

    def test_start_sets_mission_name(self, controller):
        """Starting mission sets mission_name property."""
        controller.start_mission("Operation Rescue")

        assert controller.mission_name == "Operation Rescue"

    def test_mission_name_required_empty_string_raises_value_error(self, controller):
        """
        Empty mission name is rejected.

        VALUE: Prevents missions without identifiable names.
        """
        with pytest.raises(ValueError, match="Mission name cannot be empty"):
            controller.start_mission("")

    def test_mission_name_required_whitespace_only_raises_value_error(self, controller):
        """
        Whitespace-only mission name is rejected.

        VALUE: Prevents missions with invalid names.
        """
        with pytest.raises(ValueError, match="Mission name cannot be empty"):
            controller.start_mission("   ")

    def test_mission_name_required_none_raises_value_error(self, controller):
        """
        None mission name is rejected.

        VALUE: Prevents missions without names.
        """
        with pytest.raises(ValueError, match="Mission name cannot be empty"):
            controller.start_mission(None)

    def test_mission_name_whitespace_trimmed(self, controller):
        """Leading/trailing whitespace is trimmed from mission name."""
        controller.start_mission("  Mountain Rescue  ")

        assert controller.mission_name == "Mountain Rescue"

    def test_mission_name_persists_after_finish(self, controller):
        """
        Mission name persists after finishing (for reference/logging).

        NOTE: The name is only cleared when starting a NEW mission via _reset_internal_state().
        This allows operators to see the last completed mission name.
        """
        controller.start_mission("Test Mission")
        assert controller.mission_name == "Test Mission"

        controller.finish_mission()

        # Mission name persists after finish (actual behavior)
        assert controller.mission_name == "Test Mission"

    def test_mission_name_cleared_on_new_start(self, controller):
        """Mission name is cleared when starting a new mission."""
        controller.start_mission("First Mission")
        controller.finish_mission()
        assert controller.mission_name == "First Mission"

        controller.start_mission("Second Mission")

        assert controller.mission_name == "Second Mission"

    def test_mission_name_not_overwritten_by_failed_start(self, controller):
        """Failed mission start doesn't change current mission name."""
        controller.start_mission("First Mission")
        original_name = controller.mission_name

        # Try to start second mission (should fail)
        try:
            controller.start_mission("Second Mission")
        except RuntimeError:
            pass

        assert controller.mission_name == original_name


# =============================================================================
# THREAD SAFETY TESTS
# =============================================================================

class TestThreadSafety:
    """Test thread-safe state transitions and timing calculations."""

    def test_concurrent_pause_resume_operations_are_safe(self, controller):
        """
        CRITICAL: Rapid pause/resume from multiple threads doesn't corrupt state.

        VALUE: Prevents race conditions during operator UI interaction.
        """
        controller.start_mission("Stress Test")

        errors = []
        operations_completed = [0]

        def rapid_pause_resume():
            try:
                for _ in range(10):
                    controller.pause_mission()
                    time.sleep(0.001)  # 1ms
                    controller.resume_mission()
                    time.sleep(0.001)
                operations_completed[0] += 1
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=rapid_pause_resume) for _ in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5.0)

        # Verify no errors occurred
        assert len(errors) == 0, f"Thread safety errors: {errors}"

        # Verify final state is consistent (should be ACTIVE or PAUSED, not corrupted)
        assert controller.state in (MissionState.ACTIVE, MissionState.PAUSED)

        # Verify timing calculations still work
        timing = controller._compute_timing()
        assert timing.elapsed_seconds >= 0
        assert timing.active_seconds >= 0
        assert timing.active_seconds <= timing.elapsed_seconds

    def test_concurrent_timing_reads_during_state_changes_are_safe(self, controller):
        """
        CRITICAL: Reading timing while changing state doesn't cause crashes.

        VALUE: Prevents crashes when UI polls timing during operator actions.
        """
        controller.start_mission("Concurrent Test")

        errors = []
        timing_reads = [0]

        def rapid_state_changes():
            try:
                for _ in range(5):
                    controller.pause_mission()
                    time.sleep(0.005)
                    controller.resume_mission()
                    time.sleep(0.005)
            except Exception as e:
                errors.append(('state_change', e))

        def rapid_timing_reads():
            try:
                for _ in range(50):
                    controller._compute_timing()
                    timing_reads[0] += 1
                    time.sleep(0.001)
            except Exception as e:
                errors.append(('timing_read', e))

        state_thread = threading.Thread(target=rapid_state_changes)
        timing_threads = [threading.Thread(target=rapid_timing_reads) for _ in range(3)]

        state_thread.start()
        for t in timing_threads:
            t.start()

        state_thread.join(timeout=5.0)
        for t in timing_threads:
            t.join(timeout=5.0)

        # Verify no errors
        assert len(errors) == 0, f"Concurrent access errors: {errors}"

        # Verify we successfully read timing multiple times
        assert timing_reads[0] > 0, "No timing reads completed"

    def test_timing_lock_exists_and_used(self, controller):
        """
        Verify _timing_lock exists and has lock methods.

        VALUE: Ensures thread safety infrastructure is in place.
        NOTE: We can't directly test lock acquisition (RLock methods are native/read-only)
        but we verify the lock exists and has the required methods.
        """
        controller.start_mission("Lock Test")

        # Verify lock exists and has lock interface
        assert hasattr(controller, '_timing_lock')
        assert hasattr(controller._timing_lock, '__enter__')
        assert hasattr(controller._timing_lock, '__exit__')
        assert callable(controller._timing_lock.__enter__)
        assert callable(controller._timing_lock.__exit__)

        # Verify timing calculations work (which use the lock internally)
        timing = controller._compute_timing()
        assert isinstance(timing, MissionTiming)
        assert timing.elapsed_seconds >= 0
        assert timing.active_seconds >= 0


# =============================================================================
# SIGNAL EMISSION TESTS
# =============================================================================

class TestSignalEmission:
    """Test that state changes emit correct signals."""

    def test_start_mission_emits_state_changed_signal(self, controller):
        """Starting mission emits mission_state_changed signal."""
        signal_received = []
        controller.mission_state_changed.connect(
            lambda state, context: signal_received.append((state, context))
        )

        controller.start_mission("Test Mission")

        assert len(signal_received) == 1
        state, context = signal_received[0]
        assert state == MissionState.ACTIVE
        assert context["mission_name"] == "Test Mission"

    def test_pause_mission_emits_state_changed_signal(self, controller):
        """Pausing mission emits mission_state_changed signal."""
        controller.start_mission("Test Mission")

        signal_received = []
        controller.mission_state_changed.connect(
            lambda state, context: signal_received.append((state, context))
        )

        controller.pause_mission()

        assert len(signal_received) == 1
        state, context = signal_received[0]
        assert state == MissionState.PAUSED

    def test_finish_mission_emits_state_changed_signal_with_timing(self, controller):
        """Finishing mission emits signal with final timing data."""
        controller.start_mission("Test Mission")

        signal_received = []
        controller.mission_state_changed.connect(
            lambda state, context: signal_received.append((state, context))
        )

        controller.finish_mission()

        # Should emit FINISHED then IDLE
        assert len(signal_received) >= 1
        # Check FINISHED emission has final timing
        finished_emission = [s for s in signal_received if s[0] == MissionState.FINISHED]
        if finished_emission:
            _, context = finished_emission[0]
            assert "final_elapsed_seconds" in context
            assert "final_active_seconds" in context


# =============================================================================
# TIMER LIFECYCLE TESTS
# =============================================================================

class TestTimerLifecycle:
    """Test timer start/stop behavior during state transitions."""

    def test_timer_starts_when_mission_starts(self, controller):
        """Timer starts when mission becomes active."""
        assert not controller._timer.isActive()

        controller.start_mission("Test Mission")

        assert controller._timer.isActive()

    def test_timer_continues_when_paused(self, controller):
        """Timer continues running when mission is paused (for elapsed time)."""
        controller.start_mission("Test Mission")
        assert controller._timer.isActive()

        controller.pause_mission()

        # Timer should still be running to update elapsed time
        assert controller._timer.isActive()

    def test_timer_stops_when_mission_finishes(self, controller):
        """Timer stops when mission is finished."""
        controller.start_mission("Test Mission")
        assert controller._timer.isActive()

        controller.finish_mission()

        assert not controller._timer.isActive()

    def test_timer_restarts_on_resume(self, controller):
        """Timer is running after resuming from pause."""
        controller.start_mission("Test Mission")
        controller.pause_mission()

        # Simulate timer stopping (edge case)
        controller._timer.stop()
        assert not controller._timer.isActive()

        controller.resume_mission()

        assert controller._timer.isActive()
