# -*- coding: utf-8 -*-
"""Tests for the Qt compatibility guard script."""

from pathlib import Path
import subprocess


def test_compatibility_guard_passes_for_current_repository():
    result = subprocess.run(
        ["./tools/check_compatibility.sh"],
        cwd=Path(__file__).resolve().parent.parent,
        capture_output=True,
        text=True,
        check=False,
    )

    output = result.stdout + result.stderr

    assert result.returncode == 0, output
    assert "No deprecated EPSG:29903" in output
    assert "Compatibility documentation exists" in output
