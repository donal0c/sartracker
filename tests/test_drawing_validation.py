# -*- coding: utf-8 -*-
import pytest

from utils import drawing_validation as dv


class FakePoint:
    def __init__(self, lon, lat):
        self._lon = lon
        self._lat = lat

    def x(self):
        return self._lon

    def y(self):
        return self._lat


def test_validate_point_accepts_qgs_like():
    lon, lat = dv.validate_point(FakePoint(-8.3, 52.0))
    assert lon == pytest.approx(-8.3)
    assert lat == pytest.approx(52.0)


def test_validate_point_rejects_out_of_range():
    with pytest.raises(ValueError):
        dv.validate_point(FakePoint(200, 10))
    with pytest.raises(ValueError):
        dv.validate_point(FakePoint(10, -95))


def test_validate_point_sequence_enforces_minimum():
    pts = [FakePoint(-8.3, 52.0), FakePoint(-8.31, 52.01)]
    dv.validate_point_sequence(pts, min_points=2, name="line")
    with pytest.raises(ValueError):
        dv.validate_point_sequence([], min_points=1, name="empty")


def test_validate_positive_number():
    assert dv.validate_positive_number(5, "radius") == 5.0
    with pytest.raises(ValueError):
        dv.validate_positive_number(0, "radius")
    with pytest.raises(ValueError):
        dv.validate_positive_number("abc", "radius")


@pytest.mark.parametrize("bearing", [0, 45.5, 360])
def test_validate_bearing_ok(bearing):
    assert dv.validate_bearing(bearing) == pytest.approx(float(bearing))


@pytest.mark.parametrize("bearing", [-1, 361, "bad"])
def test_validate_bearing_invalid(bearing):
    with pytest.raises(ValueError):
        dv.validate_bearing(bearing)


@pytest.mark.parametrize("color", ["#FFA500", "#FFA500FF"])
def test_validate_color_hex_ok(color):
    assert dv.validate_color_hex(color) == color


@pytest.mark.parametrize("color", ["FFA500", "#GGGGGG", "#123", 123])
def test_validate_color_hex_invalid(color):
    with pytest.raises(ValueError):
        dv.validate_color_hex(color)


def test_validate_font_size_and_width():
    assert dv.validate_font_size(12) == 12
    assert dv.validate_width(3) == 3
    with pytest.raises(ValueError):
        dv.validate_font_size(0)
    with pytest.raises(ValueError):
        dv.validate_width("abc")


# ============================================================================
# BUG-081: NaN/Infinity validation tests
# ============================================================================

def test_validate_point_rejects_nan_longitude():
    """BUG-081: Ensure NaN longitude is rejected with clear error message."""
    nan = float('nan')
    with pytest.raises(ValueError, match="NaN"):
        dv.validate_point(FakePoint(nan, 52.0))


def test_validate_point_rejects_nan_latitude():
    """BUG-081: Ensure NaN latitude is rejected with clear error message."""
    nan = float('nan')
    with pytest.raises(ValueError, match="NaN"):
        dv.validate_point(FakePoint(-8.3, nan))


def test_validate_point_rejects_infinity_longitude():
    """BUG-081: Ensure Infinity longitude is rejected with clear error message."""
    inf = float('inf')
    with pytest.raises(ValueError, match="Infinity"):
        dv.validate_point(FakePoint(inf, 52.0))


def test_validate_point_rejects_negative_infinity_latitude():
    """BUG-081: Ensure -Infinity latitude is rejected with clear error message."""
    neg_inf = float('-inf')
    with pytest.raises(ValueError, match="Infinity"):
        dv.validate_point(FakePoint(-8.3, neg_inf))


def test_validate_positive_number_rejects_nan():
    """BUG-081: Ensure NaN is rejected for positive numbers."""
    nan = float('nan')
    with pytest.raises(ValueError, match="NaN"):
        dv.validate_positive_number(nan, "radius")


def test_validate_positive_number_rejects_infinity():
    """BUG-081: Ensure Infinity is rejected for positive numbers."""
    inf = float('inf')
    with pytest.raises(ValueError, match="Infinity"):
        dv.validate_positive_number(inf, "radius")


def test_validate_bearing_rejects_nan():
    """BUG-081: Ensure NaN is rejected for bearing values."""
    nan = float('nan')
    with pytest.raises(ValueError, match="NaN"):
        dv.validate_bearing(nan)


def test_validate_bearing_rejects_infinity():
    """BUG-081: Ensure Infinity is rejected for bearing values."""
    inf = float('inf')
    with pytest.raises(ValueError, match="Infinity"):
        dv.validate_bearing(inf)
