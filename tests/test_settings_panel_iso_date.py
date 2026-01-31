# -*- coding: utf-8 -*-
"""
Tests for ISODate helpers in Settings Panel (Qt5/Qt6 compatibility).

TDD: Tests written BEFORE implementation (SAR-ISODate-Qt6)
"""
import pytest


@pytest.mark.qgis_required
def test_format_iso_datetime_matches_qt_iso_date():
    """Formatting should use Qt ISODate enum for Qt5/Qt6 compatibility."""
    from qgis.PyQt.QtCore import QDateTime
    from sartracker.utils.qt_compat import ISODate
    from sartracker.ui.settings_panel import _format_iso_datetime

    dt = QDateTime.currentDateTimeUtc()
    expected = dt.toString(ISODate)
    assert _format_iso_datetime(dt) == expected


@pytest.mark.qgis_required
def test_parse_iso_datetime_is_valid():
    """Parsing ISODate should yield a valid QDateTime."""
    from qgis.PyQt.QtCore import QDateTime
    from sartracker.utils.qt_compat import ISODate
    from sartracker.ui.settings_panel import _parse_iso_datetime

    dt = QDateTime.currentDateTimeUtc()
    iso = dt.toString(ISODate)
    parsed = _parse_iso_datetime(iso)
    assert parsed.isValid()
