# -*- coding: utf-8 -*-
"""Tests for runtime capability detection."""

from types import SimpleNamespace

from sartracker.utils.capabilities import detect_qt_major_version


class _DialogWithExecUnderscore:
    def exec_(self):
        return 0


class _DialogWithoutExecUnderscore:
    def exec(self):
        return 0


def test_detect_qt_major_version_prefers_qtcore_version_string_over_dialog_shape():
    qtcore = SimpleNamespace(QT_VERSION_STR="6.8.1")

    major = detect_qt_major_version(qtcore, _DialogWithExecUnderscore)

    assert major == 6


def test_detect_qt_major_version_falls_back_to_dialog_shape_for_qt6():
    qtcore = SimpleNamespace()

    major = detect_qt_major_version(qtcore, _DialogWithoutExecUnderscore)

    assert major == 6


def test_detect_qt_major_version_falls_back_to_qt5_when_exec_looks_available():
    qtcore = SimpleNamespace(QT_VERSION_STR="not-a-version")

    major = detect_qt_major_version(qtcore, _DialogWithExecUnderscore)

    assert major == 5
