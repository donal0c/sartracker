# -*- coding: utf-8 -*-
"""
Tests for incident bundle formatting.

TDD: Tests written BEFORE implementation (SAR-INCIDENT-BUNDLE)
"""
from sartracker.ui.diagnostics_panel import format_incident_bundle


def test_format_incident_bundle_includes_sections():
    payload = {
        "generated_at": "2026-01-30T12:00:00Z",
        "environment": {"qgis": "3.44.7", "qt": "6.7.0"},
        "plugin": {"version": "0.6.0"},
        "project": {"file": "test.qgz"},
        "plugin_status": {"mission_active": True},
        "config": {"auto_refresh_enabled": True},
        "ui_state": {"auto_refresh_timer_active": False},
        "diagnostics_report": "REPORT",
        "import_report": {"ok": True},
        "log_tail": {"path": "/tmp/qgis.log", "lines": ["a", "b"]},
        "audit_tail": {"path": "/tmp/audit.jsonl", "lines": []},
    }

    text = format_incident_bundle(payload)
    assert "SAR TRACKER INCIDENT BUNDLE" in text
    assert "[ENVIRONMENT]" in text
    assert "[PLUGIN STATUS]" in text
    assert "[DIAGNOSTICS REPORT]" in text
    assert "[LOG TAIL]" in text
    assert "[AUDIT LOG TAIL]" in text
    assert "[PLUGIN]" in text
    assert "[PROJECT]" in text
    assert "[CONFIG]" in text
    assert "[UI STATE]" in text
    assert "[IMPORT REPORT]" in text
    assert "Generated At:" in text
