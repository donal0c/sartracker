# -*- coding: utf-8 -*-
"""Unit tests for TM65 grid-reference parsing."""

import pytest

from utils.coordinates import format_irish_grid_reference, parse_irish_grid_reference


def test_parse_tm65_grid_reference_standard_format():
    easting, northing = parse_irish_grid_reference("Q 99840 04018")
    assert easting == 99840
    assert northing == 104018


def test_parse_tm65_grid_reference_compact_format():
    easting, northing = parse_irish_grid_reference("Q9984004018")
    assert easting == 99840
    assert northing == 104018


def test_parse_tm65_grid_reference_round_trip_with_formatter():
    grid_ref = format_irish_grid_reference(83835, 84835)
    easting, northing = parse_irish_grid_reference(grid_ref)
    assert easting == 83835
    assert northing == 84835


def test_parse_tm65_grid_reference_rejects_invalid_letter():
    with pytest.raises(ValueError, match="Invalid Irish Grid letter"):
        parse_irish_grid_reference("I 12345 67890")


def test_parse_tm65_grid_reference_rejects_invalid_structure():
    with pytest.raises(ValueError, match="Invalid Irish Grid reference"):
        parse_irish_grid_reference("Q 1234")
