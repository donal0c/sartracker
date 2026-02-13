# -*- coding: utf-8 -*-
"""Regression tests for ITM/TM65 EPSG references in documentation."""

from pathlib import Path


def test_readme_uses_itm_epsg_2157_not_tm65_epsg_29903():
    content = Path("README.md").read_text(encoding="utf-8")
    assert "Irish Grid ITM" in content
    assert "EPSG:2157" in content
    assert "Irish Grid ITM (EPSG:29903)" not in content


def test_roadmap_uses_itm_epsg_2157_not_tm65_epsg_29903():
    content = Path("FUTURE_WORK/ROADMAP.md").read_text(encoding="utf-8")
    assert "Irish Grid (ITM) supported via transformation" in content
    assert "EPSG:2157" in content
    assert "Irish Grid (ITM) supported via transformation (EPSG:29903)" not in content
