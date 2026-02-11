# -*- coding: utf-8 -*-
"""
Tests for Mission Logs refresh guard helper.

TDD: Tests written BEFORE implementation (SAR-MLOG-REFRESH-GUARD)
"""
from sartracker.ui.mission_logs_window import safe_refresh_call


def test_safe_refresh_call_returns_false_on_exception():
    def _boom():
        raise RuntimeError("fail")

    assert safe_refresh_call(_boom, "test") is False


def test_safe_refresh_call_returns_true_on_success():
    hit = {"ok": False}

    def _ok():
        hit["ok"] = True

    assert safe_refresh_call(_ok, "test") is True
    assert hit["ok"] is True
