# -*- coding: utf-8 -*-
"""
Mission Controller

Owns mission lifecycle state, timing, and persistence logic.

Responsibilities:
- Centralize mission state transitions (start, pause, resume, finish)
- Track elapsed vs. active search time with pause accounting
- Emit Qt signals for UI and plugin observers
- Persist paused missions to QSettings for crash-safe auto-resume

Qt5/Qt6 Compatible: Uses qgis.PyQt imports only (Pattern 1). Timer has
parent + explicit cleanup hooks (Pattern 7). All async callbacks have
defensive guards (Pattern 9).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, Optional, Set
import logging
import threading

from qgis.PyQt.QtCore import QObject, QSettings, QTimer, pyqtSignal

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    """Get timezone-aware UTC timestamp."""
    return datetime.now(timezone.utc)


class MissionState(Enum):
    """Enumerates mission lifecycle states."""

    IDLE = "idle"
    ACTIVE = "active"
    PAUSED = "paused"
    FINISHED = "finished"


@dataclass
class MissionTiming:
    """Simple timing container for diagnostics and consumers."""

    elapsed_seconds: float
    active_seconds: float


class MissionController(QObject):
    """
    Coordinates mission lifecycle events and exposes state via Qt signals.

    Signals:
        mission_state_changed(MissionState, dict):
            Fired on every state transition with context payload.
        mission_timing_updated(float, float):
            Fired at 1 Hz while mission running/paused with elapsed + active seconds.
    """

    mission_state_changed = pyqtSignal(object, dict)
    mission_timing_updated = pyqtSignal(float, float)

    SETTINGS_PREFIX = "SAR_Tracker"
    SETTINGS_KEY_PAUSED = f"{SETTINGS_PREFIX}/mission_paused"
    SETTINGS_KEY_NAME = f"{SETTINGS_PREFIX}/mission_name"
    SETTINGS_KEY_START = f"{SETTINGS_PREFIX}/mission_start_time"
    SETTINGS_KEY_PAUSED_SECONDS = f"{SETTINGS_PREFIX}/mission_paused_seconds"
    SETTINGS_KEY_PAUSE_STARTED = f"{SETTINGS_PREFIX}/mission_pause_started"
    SETTINGS_KEY_RESUME_STATE = f"{SETTINGS_PREFIX}/mission_resume_state"

    # BUG-064 FIX: Explicit state transition matrix
    # Maps current_state -> set of valid target states
    VALID_TRANSITIONS: Dict[MissionState, Set[MissionState]] = {
        MissionState.IDLE: {MissionState.ACTIVE},  # Start mission
        MissionState.ACTIVE: {MissionState.PAUSED, MissionState.FINISHED},  # Pause or finish
        MissionState.PAUSED: {MissionState.ACTIVE, MissionState.FINISHED},  # Resume or finish
        MissionState.FINISHED: {MissionState.IDLE},  # Reset
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self._state: MissionState = MissionState.IDLE
        self._mission_name: Optional[str] = None
        self._mission_start_ts: Optional[datetime] = None
        self._pause_started_at: Optional[datetime] = None
        self._paused_total_seconds: float = 0.0
        self._last_emitted: MissionTiming = MissionTiming(0.0, 0.0)

        # BUG-022 FIX: Thread-safe lock for timing calculations
        # Prevents race conditions during rapid pause/resume operations
        self._timing_lock = threading.RLock()

        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._on_timer_tick)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def mission_name(self) -> Optional[str]:
        return self._mission_name

    @property
    def state(self) -> MissionState:
        return self._state

    def is_active(self) -> bool:
        return self._state in (MissionState.ACTIVE, MissionState.PAUSED)

    def _validate_transition(self, target_state: MissionState) -> bool:
        """
        BUG-064 FIX: Validate state transition against explicit transition matrix.

        Args:
            target_state: The state we want to transition to

        Returns:
            bool: True if transition is valid

        Raises:
            RuntimeError: If transition is invalid
        """
        valid_targets = self.VALID_TRANSITIONS.get(self._state, set())
        if target_state not in valid_targets:
            logger.warning(
                "BUG-064: Invalid state transition attempted: %s -> %s (valid: %s)",
                self._state.value, target_state.value,
                [s.value for s in valid_targets]
            )
            raise RuntimeError(
                f"Invalid state transition: cannot go from {self._state.value} to {target_state.value}"
            )
        logger.debug(
            "BUG-064: Valid state transition: %s -> %s",
            self._state.value, target_state.value
        )
        return True

    def start_mission(self, name: str) -> bool:
        """
        Start a new mission.

        Args:
            name: Mission name (non-empty string)

        Returns:
            bool: True if mission started, False otherwise
        """
        mission_name = (name or "").strip()
        if not mission_name:
            raise ValueError("Mission name cannot be empty")

        # BUG-064 FIX: Use explicit state transition validation
        self._validate_transition(MissionState.ACTIVE)

        self._reset_internal_state()
        self._mission_name = mission_name
        self._mission_start_ts = _utcnow()

        # BUG-047 FIX: Use timing lock for atomic state + timer update
        # Prevents race conditions between state transitions and timer ticks
        with self._timing_lock:
            self._state = MissionState.ACTIVE
            self._timer.start()

        self._emit_state_changed()
        self._emit_timing_update(force=True)
        self._clear_saved_state()
        self._update_resume_state("active")
        return True

    def pause_mission(self) -> bool:
        """
        Pause an active mission.

        BUG-022 FIX: Uses timing lock to prevent race conditions during
        rapid pause/resume sequences.
        """
        # BUG-022 FIX: Atomic state transition with lock
        with self._timing_lock:
            if self._state != MissionState.ACTIVE:
                return False

            self._pause_started_at = _utcnow()
            self._state = MissionState.PAUSED

        self._emit_state_changed()
        self._emit_timing_update(force=True)
        self._save_paused_state()
        self._update_resume_state("paused")
        return True

    def resume_mission(self) -> bool:
        """
        Resume a paused mission.

        BUG-022 FIX: Uses timing lock to prevent race conditions during
        rapid pause/resume sequences. Ensures atomic update of pause timing.
        """
        # BUG-022 FIX: Atomic state transition with lock
        with self._timing_lock:
            if self._state != MissionState.PAUSED:
                return False

            now = _utcnow()
            if self._pause_started_at:
                pause_delta = (now - self._pause_started_at).total_seconds()
                if pause_delta > 0:
                    self._paused_total_seconds += pause_delta

            self._pause_started_at = None
            self._state = MissionState.ACTIVE

        if not self._timer.isActive():
            self._timer.start()

        self._emit_state_changed()
        self._emit_timing_update(force=True)
        self._clear_saved_state()
        self._update_resume_state("active")
        return True

    def finish_mission(self) -> bool:
        """Finish the current mission and reset timers."""
        if not self.is_active():
            return False

        now = _utcnow()
        if self._state == MissionState.PAUSED and self._pause_started_at:
            pause_delta = (now - self._pause_started_at).total_seconds()
            if pause_delta > 0:
                self._paused_total_seconds += pause_delta

        final_timing = self._compute_timing(now)

        # BUG-047 FIX: Use timing lock for atomic state + timer update
        with self._timing_lock:
            self._state = MissionState.FINISHED
            self._timer.stop()

        self._emit_state_changed(extra_context={
            "final_elapsed_seconds": final_timing.elapsed_seconds,
            "final_active_seconds": final_timing.active_seconds
        })

        self._clear_saved_state()
        self._update_resume_state("idle")

        # MISSION-DOUBLE-EMIT fix: Reset all state BEFORE emitting IDLE
        # This ensures both emissions have consistent data
        self._mission_start_ts = None
        self._pause_started_at = None
        self._paused_total_seconds = 0.0
        self._last_emitted = MissionTiming(0.0, 0.0)
        self._state = MissionState.IDLE

        # Single emission of IDLE state with zeroed timing (timing update handled by state change)
        self._emit_state_changed()
        return True

    # ------------------------------------------------------------------
    # Persistence API
    # ------------------------------------------------------------------

    def load_saved_state(self) -> Optional[Dict[str, str]]:
        """
        Return saved mission state from QSettings if mission was paused.

        BUG-046 FIX: Added comprehensive validation of restored state data
        to prevent corrupted or invalid state from being loaded.
        """
        settings = QSettings()
        paused = settings.value(self.SETTINGS_KEY_PAUSED, False, bool)
        if not paused:
            return None

        resume_state = str(settings.value(self.SETTINGS_KEY_RESUME_STATE, "") or "").strip().lower()
        if resume_state and resume_state != "paused":
            # Stale or conflicting state found – clear persisted data and skip prompt
            self.clear_saved_state()
            return None

        mission_name = settings.value(self.SETTINGS_KEY_NAME, None)
        start_time_str = settings.value(self.SETTINGS_KEY_START, None)
        paused_seconds = settings.value(self.SETTINGS_KEY_PAUSED_SECONDS, 0.0)
        pause_started = settings.value(self.SETTINGS_KEY_PAUSE_STARTED, None)

        if not mission_name or not start_time_str:
            self._clear_saved_state()
            return None

        # BUG-046 FIX: Validate mission name
        mission_name_clean = str(mission_name).strip()
        if not mission_name_clean or len(mission_name_clean) > 500:
            print(f"[MissionController] BUG-046: Invalid mission name, clearing state")
            self._clear_saved_state()
            return None

        # BUG-046 FIX: Validate start_time is a valid ISO timestamp
        start_time_clean = str(start_time_str).strip()
        try:
            parsed_start = datetime.fromisoformat(start_time_clean)
            # Sanity check: start time should not be in the future
            if parsed_start > _utcnow():
                print(f"[MissionController] BUG-046: Start time in future, clearing state")
                self._clear_saved_state()
                return None
        except (TypeError, ValueError) as e:
            print(f"[MissionController] BUG-046: Invalid start_time format: {e}")
            self._clear_saved_state()
            return None

        # BUG-046 FIX: Validate paused_seconds is non-negative
        try:
            paused_seconds_float = float(paused_seconds) if paused_seconds else 0.0
            if paused_seconds_float < 0:
                print(f"[MissionController] BUG-046: Negative paused_seconds, resetting to 0")
                paused_seconds_float = 0.0
        except (TypeError, ValueError):
            paused_seconds_float = 0.0

        # BUG-046 FIX: Validate pause_started if present
        pause_started_clean = ""
        if pause_started:
            pause_started_clean = str(pause_started).strip()
            if pause_started_clean:
                try:
                    datetime.fromisoformat(pause_started_clean)
                except (TypeError, ValueError) as e:
                    print(f"[MissionController] BUG-046: Invalid pause_started format: {e}")
                    pause_started_clean = ""

        return {
            "name": mission_name_clean,
            "start_time": start_time_clean,
            "paused_seconds": paused_seconds_float,
            "pause_started": pause_started_clean
        }

    def clear_saved_state(self):
        """Public helper for clearing persisted mission state."""
        self._clear_saved_state()
        self._update_resume_state("idle")

    def restore_from_state(self, state: Dict[str, str]) -> bool:
        """Restore mission controller from saved state."""
        if not state or "name" not in state or "start_time" not in state:
            raise ValueError("Invalid mission state payload")

        mission_name = state["name"].strip()
        start_str = state["start_time"].strip()
        if not mission_name or not start_str:
            raise ValueError("Mission state missing required fields")

        try:
            start_ts = datetime.fromisoformat(start_str)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Invalid mission start timestamp: {exc}") from exc

        paused_seconds = float(state.get("paused_seconds", 0.0))
        pause_started_str = state.get("pause_started") or ""
        pause_started_at = None
        if pause_started_str:
            try:
                pause_started_at = datetime.fromisoformat(pause_started_str)
            except (TypeError, ValueError) as exc:
                # MISSION-RESTORE fix: Raise error instead of defaulting to now()
                # Defaulting to current time would corrupt pause timing calculations
                raise ValueError(
                    f"Mission was in PAUSED state but pause_started timestamp is invalid: {exc}"
                ) from exc

        self._reset_internal_state()
        self._mission_name = mission_name
        self._mission_start_ts = start_ts
        self._paused_total_seconds = max(0.0, paused_seconds)
        # MISSION-RESTORE fix: Only restore as PAUSED if we have valid pause_started
        if pause_started_at:
            self._pause_started_at = pause_started_at
            self._state = MissionState.PAUSED
        else:
            self._pause_started_at = None
            self._state = MissionState.ACTIVE
        self._timer.start()

        self._emit_state_changed()
        self._emit_timing_update(force=True)
        return True

    def cleanup(self):
        """Stop timers and clear references during plugin unload."""
        try:
            if self._timer and self._timer.isActive():
                self._timer.stop()
        except Exception as exc:
            print(f"[MissionController] Warning: Failed to stop timer: {exc}")

    # ------------------------------------------------------------------
    # Diagnostics Helpers
    # ------------------------------------------------------------------

    def status_snapshot(self) -> Dict[str, Optional[str]]:
        """Return mission status for diagnostics panels."""
        now = _utcnow()
        timing = self._compute_timing(now)
        paused_since = self._pause_started_at.isoformat() if self._pause_started_at else None
        started_at = self._mission_start_ts.isoformat() if self._mission_start_ts else None

        return {
            "state": self._state.value,
            "mission_name": self._mission_name,
            "started_at": started_at,
            "paused_since": paused_since,
            "elapsed_seconds": timing.elapsed_seconds,
            "active_seconds": timing.active_seconds
        }

    # ------------------------------------------------------------------
    # Internal Helpers
    # ------------------------------------------------------------------

    def _reset_internal_state(self):
        self._mission_name = None
        self._mission_start_ts = None
        self._pause_started_at = None
        self._paused_total_seconds = 0.0
        self._last_emitted = MissionTiming(0.0, 0.0)

    def _compute_timing(self, now: Optional[datetime] = None) -> MissionTiming:
        """
        Compute elapsed and active timing for the current mission.

        BUG-022/BUG-023 FIX: Uses timing lock for thread safety and rounds
        values to limit floating-point precision loss in long missions.

        Args:
            now: Optional timestamp (defaults to UTC now)

        Returns:
            MissionTiming with elapsed and active seconds
        """
        now = now or _utcnow()
        if not self._mission_start_ts:
            return MissionTiming(0.0, 0.0)

        # BUG-022 FIX: Use lock to ensure consistent reads of timing state
        with self._timing_lock:
            elapsed = max(0.0, (now - self._mission_start_ts).total_seconds())
            paused = self._paused_total_seconds
            if self._pause_started_at:
                paused += max(0.0, (now - self._pause_started_at).total_seconds())

        active = max(0.0, elapsed - paused)

        # BUG-023 FIX: Round to 1 decimal place to limit floating-point
        # precision loss during long-duration missions (24+ hours).
        # This prevents cumulative errors from affecting displayed time.
        elapsed = round(elapsed, 1)
        active = round(active, 1)

        return MissionTiming(elapsed, active)

    def _emit_timing_update(self, *, force: bool = False):
        timing = self._compute_timing()
        if force or (
            abs(timing.elapsed_seconds - self._last_emitted.elapsed_seconds) >= 1.0
            or abs(timing.active_seconds - self._last_emitted.active_seconds) >= 1.0
        ):
            self._last_emitted = timing
            self.mission_timing_updated.emit(timing.elapsed_seconds, timing.active_seconds)

    def _emit_state_changed(self, extra_context: Optional[Dict] = None):
        context = {
            "mission_name": self._mission_name,
            "started_at": self._mission_start_ts.isoformat() if self._mission_start_ts else None,
            "paused_since": self._pause_started_at.isoformat() if self._pause_started_at else None
        }
        if extra_context:
            context.update(extra_context)
        self.mission_state_changed.emit(self._state, context)

    def _on_timer_tick(self):
        """
        Handle timer tick for mission timing updates.

        BUG-035 FIX: Uses timing lock to ensure atomic state checks and
        prevent race conditions between timer ticks and state transitions.
        """
        # BUG-035 FIX: Use timing lock for atomic state check
        # This prevents race where state changes between is_active() and _emit_timing_update()
        with self._timing_lock:
            if not self.is_active():
                # Stop timer if mission is no longer active
                if self._timer.isActive():
                    self._timer.stop()
                return
            self._emit_timing_update()

    # ------------------------------------------------------------------
    # Persistence helpers
    # ------------------------------------------------------------------

    def _save_paused_state(self):
        """Persist paused mission metadata for crash-safe resume."""
        if self._state != MissionState.PAUSED or not self._mission_start_ts:
            return

        settings = QSettings()
        settings.setValue(self.SETTINGS_KEY_PAUSED, True)
        settings.setValue(self.SETTINGS_KEY_NAME, self._mission_name or "")
        settings.setValue(self.SETTINGS_KEY_START, self._mission_start_ts.isoformat())

        paused_seconds = self._paused_total_seconds
        if self._pause_started_at:
            paused_seconds += max(0.0, (_utcnow() - self._pause_started_at).total_seconds())
        settings.setValue(self.SETTINGS_KEY_PAUSED_SECONDS, paused_seconds)
        settings.setValue(
            self.SETTINGS_KEY_PAUSE_STARTED,
            self._pause_started_at.isoformat() if self._pause_started_at else ""
        )
        settings.sync()

    def _clear_saved_state(self):
        settings = QSettings()
        settings.setValue(self.SETTINGS_KEY_PAUSED, False)
        settings.remove(self.SETTINGS_KEY_NAME)
        settings.remove(self.SETTINGS_KEY_START)
        settings.remove(self.SETTINGS_KEY_PAUSED_SECONDS)
        settings.remove(self.SETTINGS_KEY_PAUSE_STARTED)
        settings.sync()

    def _update_resume_state(self, state: str):
        """Persist high-level mission lifecycle state for resume guards."""
        state_value = (state or "").strip().lower() or "idle"
        settings = QSettings()
        settings.setValue(self.SETTINGS_KEY_RESUME_STATE, state_value)
        settings.sync()

