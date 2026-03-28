# -*- coding: utf-8 -*-
"""
Baseline tests for MarkerDialog and CoordinateConverterDialog.

These tests provide safety-net coverage before TM65-first workflow changes.
"""

import sys

import pytest

pytestmark = [
    pytest.mark.qgis_required,
    pytest.mark.skipif(
        sys.platform == "darwin",
        reason="Qt widget tests can crash on macOS/Rosetta (SAR-efn7)",
    ),
]

from sartracker.ui import coordinate_converter_dialog as converter_module
from sartracker.ui.coordinate_converter_dialog import CoordinateConverterDialog
from sartracker.ui.marker_grid_dialog import MarkerGridDialog
from sartracker.ui.marker_dialog import MarkerDialog
from qgis.PyQt.QtWidgets import QLabel


class _FakePoint:
    def __init__(self, x, y):
        self._x = float(x)
        self._y = float(y)

    def x(self):
        return self._x

    def y(self):
        return self._y


class _FakeValidCrs:
    def isValid(self):
        return True


class _FakeInvalidCrs:
    def isValid(self):
        return False


def _make_fake_transform(results):
    class _FakeTransform:
        def __init__(self, *_args, **_kwargs):
            pass

        def transform(self, _point):
            if not results:
                raise AssertionError("No fake transform results left")
            return results.pop(0)

    return _FakeTransform


@pytest.fixture
def converter_dialog(qgis_app):
    dialog = CoordinateConverterDialog()
    yield dialog
    dialog.close()


@pytest.fixture
def marker_dialog(qgis_app):
    dialog = MarkerDialog(52.274681, -9.530912, 500000, 700000)
    yield dialog
    dialog.close()


class TestMarkerDialogBaseline:
    def test_construction_with_valid_coordinates_and_default_type(self, marker_dialog):
        assert marker_dialog.marker_type == "ipp_lkp"
        assert marker_dialog.ipp_lkp_radio.isChecked()

    def test_invalid_coordinate_rejected_before_ui_setup(self):
        with pytest.raises(ValueError, match="Invalid longitude"):
            MarkerDialog(52.274681, float("nan"), 500000, 700000)

    def test_coordinate_display_uses_directional_wgs84_format(self, marker_dialog):
        label_texts = [label.text() for label in marker_dialog.findChildren(QLabel)]
        assert any("52.274681\u00b0N, 9.530912\u00b0W" in text for text in label_texts)

    def test_type_selection_toggles_marker_mode_and_fields(self, marker_dialog):
        marker_dialog.hazard_radio.setChecked(True)
        marker_dialog._on_type_changed()

        assert marker_dialog.marker_type == "hazard"
        assert not marker_dialog.hazard_type_combo.isHidden()
        assert marker_dialog.subject_category_combo.isHidden()

    def test_clue_mode_shows_found_by_and_round_trips_data(self, marker_dialog):
        marker_dialog.clue_radio.setChecked(True)
        marker_dialog._on_type_changed()

        assert not marker_dialog.found_by_input.isHidden()

        marker_dialog.found_by_input.setText("Team Alpha")
        data = marker_dialog.get_marker_data()

        assert data["type"] == "clue"
        assert data["found_by"] == "Team Alpha"

    def test_edit_mode_clue_loads_found_by(self, qgis_app):
        dialog = MarkerDialog(
            52.274681,
            -9.530912,
            95553,
            114716,
            existing_data={
                "id": "clue-1",
                "type": "clue",
                "name": "Boot print",
                "found_by": "Team Bravo",
            },
        )
        try:
            assert dialog.clue_radio.isChecked()
            assert dialog.found_by_input.text() == "Team Bravo"
        finally:
            dialog.close()

    def test_tm65_reference_is_shown_when_available(self, qgis_app, monkeypatch):
        fake_transform = _make_fake_transform([_FakePoint(99840, 104018)])
        monkeypatch.setattr(
            "sartracker.ui.marker_dialog.QgsCoordinateTransform",
            fake_transform,
        )
        monkeypatch.setattr(
            "sartracker.ui.marker_dialog.format_irish_grid_reference",
            lambda _e, _n: "Q 99840 04018",
        )
        monkeypatch.setattr(
            "sartracker.ui.marker_dialog.build_tm65_crs",
            lambda: _FakeValidCrs(),
        )

        dialog = MarkerDialog(52.274681, -9.530912, 95553, 114716)
        try:
            label_texts = [label.text() for label in dialog.findChildren(QLabel)]
            assert any("Q 99840 04018" in text for text in label_texts)
        finally:
            dialog.close()


class TestCoordinateConverterDialogBaseline:
    def test_wgs84_to_itm_conversion_updates_results(self, converter_dialog, monkeypatch):
        fake_transform = _make_fake_transform([_FakePoint(95553.7, 114716.2)])
        monkeypatch.setattr(converter_module, "QgsCoordinateTransform", fake_transform)

        converter_dialog.tm65 = None
        converter_dialog.lat_input.setText("52.274681")
        converter_dialog.lon_input.setText("-9.530912")

        converter_dialog._on_convert()

        text = converter_dialog.result_label.text()
        assert "Source:</b> WGS84 (Lat/Lon)" in text
        assert "WGS84:" in text
        assert "Irish Grid (ITM):" in text
        assert "Latitude: 52.274681\u00b0N" in text
        assert "Longitude: 9.530912\u00b0W" in text
        assert "Easting: 95,554" in text
        assert "Northing: 114,716" in text
        assert converter_dialog.copy_button.isEnabled()
        assert converter_dialog.goto_button.isEnabled()

    def test_itm_to_wgs84_conversion_updates_results(self, converter_dialog, monkeypatch):
        fake_transform = _make_fake_transform([_FakePoint(-9.530912, 52.274681)])
        monkeypatch.setattr(converter_module, "QgsCoordinateTransform", fake_transform)

        converter_dialog.irish_grid_radio.setChecked(True)
        converter_dialog._on_input_type_changed()
        converter_dialog.easting_input.setText("95553")
        converter_dialog.northing_input.setText("114716")

        converter_dialog._on_convert()

        text = converter_dialog.result_label.text()
        assert "Source:</b> Irish Grid (ITM)" in text
        assert "WGS84:" in text
        assert "Latitude: 52.274681\u00b0N" in text
        assert "Longitude: 9.530912\u00b0W" in text
        assert converter_dialog.last_lat == pytest.approx(52.274681)
        assert converter_dialog.last_lon == pytest.approx(-9.530912)

    def test_tm65_reference_is_shown_when_available(self, converter_dialog, monkeypatch):
        fake_transform = _make_fake_transform(
            [_FakePoint(95553.7, 114716.2), _FakePoint(99840, 104018)]
        )
        monkeypatch.setattr(converter_module, "QgsCoordinateTransform", fake_transform)
        monkeypatch.setattr(
            converter_module,
            "format_irish_grid_reference",
            lambda _e, _n: "Q 99840 04018",
        )

        converter_dialog.tm65 = _FakeValidCrs()
        converter_dialog.lat_input.setText("52.274681")
        converter_dialog.lon_input.setText("-9.530912")

        converter_dialog._on_convert()

        text = converter_dialog.result_label.text()
        assert "Irish Grid (TM65) Reference:" in text
        assert "Q 99840 04018" in text

    def test_invalid_wgs84_input_sets_validation_error(self, converter_dialog):
        converter_dialog.lat_input.setText("abc")
        converter_dialog.lon_input.setText("-9.530912")

        converter_dialog._on_convert()

        assert "Invalid number format" in converter_dialog.result_label.text()


class TestMarkerGridDialogBaseline:
    def test_dialog_defaults_to_ipp_lkp_and_trims_grid_reference(self, qgis_app):
        dialog = MarkerGridDialog()
        try:
            dialog.grid_ref_input.setText("  Q 99840 04018  ")

            marker_type, grid_ref = dialog.get_marker_request()

            assert marker_type == "ipp_lkp"
            assert grid_ref == "Q 99840 04018"
        finally:
            dialog.close()

    def test_dialog_allows_switching_marker_type(self, qgis_app):
        dialog = MarkerGridDialog()
        try:
            dialog.marker_type_combo.setCurrentIndex(
                dialog.marker_type_combo.findData("casualty")
            )
            dialog.grid_ref_input.setText("Q9984004018")

            marker_type, grid_ref = dialog.get_marker_request()

            assert marker_type == "casualty"
            assert grid_ref == "Q9984004018"
        finally:
            dialog.close()
