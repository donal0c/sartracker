# -*- coding: utf-8 -*-
"""Source-level regression guards for TM65-first converter workflow."""

from pathlib import Path


def test_coordinate_converter_has_tm65_input_mode():
    content = Path("ui/coordinate_converter_dialog.py").read_text(encoding="utf-8")
    assert "Irish Grid Reference (TM65)" in content
    assert "parse_irish_grid_reference" in content


def test_coordinate_converter_reads_persisted_display_mode():
    content = Path("ui/coordinate_converter_dialog.py").read_text(encoding="utf-8")
    assert "get_coordinate_display_mode" in content
    assert "set_coordinate_display_mode" in content
