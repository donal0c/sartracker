# -*- coding: utf-8 -*-
"""Mission lifecycle state sync tests."""

from types import SimpleNamespace


def test_sync_active_state_updates_session_snapshot():
    """sync_active_state should align lifecycle active state with MissionController."""
    from sartracker.controllers.mission_lifecycle_controller import MissionLifecycleController

    class _MissionControllerStub:
        def is_active(self):
            return True

        def status_snapshot(self):
            return {
                "started_at": "2026-02-17T20:57:00+00:00",
            }

    iface = SimpleNamespace(messageBar=lambda: None)
    controller = MissionLifecycleController(
        iface=iface,
        mission_controller=_MissionControllerStub(),
    )

    before = controller.status_snapshot()
    assert before["is_active"] is False
    assert before["start_time"] is None

    controller.sync_active_state()

    after = controller.status_snapshot()
    assert after["is_active"] is True
    assert after["start_time"] == "2026-02-17T20:57:00+00:00"
