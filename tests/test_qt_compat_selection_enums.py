# -*- coding: utf-8 -*-
"""
Tests for Qt5/Qt6 compatibility enums required for selection behavior.

TDD: Tests written BEFORE implementation (SAR-SelectItems-Qt6)
"""
import pytest


def test_select_items_importable():
    """SelectItems enum should be importable from qt_compat."""
    from utils.qt_compat import SelectItems
    assert SelectItems is not None


def test_extended_selection_importable():
    """ExtendedSelection enum should be importable from qt_compat."""
    from utils.qt_compat import ExtendedSelection
    assert ExtendedSelection is not None


def test_selection_enums_in_all():
    """Selection enums should be in __all__ export list."""
    from utils import qt_compat
    assert 'SelectItems' in qt_compat.__all__
    assert 'ExtendedSelection' in qt_compat.__all__


@pytest.mark.qgis_required
class TestSelectionEnumValuesWithQGIS:
    """Verify selection enums map to Qt values when QGIS is available."""

    def test_select_items_matches_qabstractitemview(self):
        """SelectItems should map to QAbstractItemView.SelectionBehavior.SelectItems."""
        from qgis.PyQt.QtWidgets import QAbstractItemView
        from utils.qt_compat import SelectItems
        assert int(SelectItems) == int(QAbstractItemView.SelectionBehavior.SelectItems)

    def test_extended_selection_matches_qabstractitemview(self):
        """ExtendedSelection should map to QAbstractItemView.SelectionMode.ExtendedSelection."""
        from qgis.PyQt.QtWidgets import QAbstractItemView
        from utils.qt_compat import ExtendedSelection
        assert int(ExtendedSelection) == int(QAbstractItemView.SelectionMode.ExtendedSelection)
