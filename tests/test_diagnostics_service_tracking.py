# -*- coding: utf-8 -*-
"""DiagnosticsService tracking diagnostics wiring tests."""

from sartracker.services.diagnostics_service import DiagnosticsService


class _LayersControllerStub:
    def get_all_diagnostics(self):
        return {
            "tracking": {
                "status": "operational",
                "stale_layer_cache_events": 2,
            }
        }


def test_get_status_includes_tracking_diagnostics_from_layers_controller():
    svc = DiagnosticsService()
    svc.set_layers_controller(_LayersControllerStub())

    status = svc.get_status()

    assert "tracking_diagnostics" in status
    assert status["tracking_diagnostics"]["status"] == "operational"
    assert status["tracking_diagnostics"]["stale_layer_cache_events"] == 2
