# -*- coding: utf-8 -*-
"""
Path security validation tests.

Tests MissionStorageHelper.sanitize_mission_name() which creates safe
folder names from user input. This is ACTUAL PRODUCTION CODE testing.

VALUE: Prevents path traversal attacks and data corruption in mission storage.
"""
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from utils.mission_storage import MissionStorageHelper  # noqa: E402


class TestSanitizeMissionName:
    """
    Test MissionStorageHelper.sanitize_mission_name() - ACTUAL PRODUCTION CODE.

    This function creates safe folder names from user input.
    Failures could allow path traversal or filesystem corruption.
    """

    # --- Normal operation ---

    def test_normal_name_preserved(self):
        """Normal mission names work correctly."""
        assert MissionStorageHelper.sanitize_mission_name("Kerry-MR-2024") == "Kerry-MR-2024"
        assert MissionStorageHelper.sanitize_mission_name("Mission_Alpha") == "Mission_Alpha"

    def test_spaces_to_underscores(self):
        """Spaces converted to underscores."""
        result = MissionStorageHelper.sanitize_mission_name("Kerry Mountain Rescue")
        assert result == "Kerry_Mountain_Rescue"

    def test_empty_gets_default(self):
        """Empty/None input gets timestamp-based default."""
        result = MissionStorageHelper.sanitize_mission_name("")
        assert result.startswith("mission_")
        assert re.match(r'mission_\d{8}_\d{6}', result)

    # --- Security: Path traversal ---

    def test_path_traversal_blocked(self):
        """Path traversal attempts neutralized."""
        result = MissionStorageHelper.sanitize_mission_name("../../../etc/passwd")
        assert ".." not in result
        assert "/" not in result

    def test_windows_path_blocked(self):
        """Windows paths stripped."""
        result = MissionStorageHelper.sanitize_mission_name("C:\\Windows\\System32")
        assert "\\" not in result
        assert ":" not in result

    # --- Security: Injection ---

    def test_null_byte_stripped(self):
        """Null bytes removed (prevent null byte injection)."""
        result = MissionStorageHelper.sanitize_mission_name("mission\x00.gpkg")
        assert "\x00" not in result

    def test_shell_metacharacters_stripped(self):
        """Shell metacharacters removed."""
        result = MissionStorageHelper.sanitize_mission_name("file; rm -rf /")
        assert ";" not in result
        assert "|" not in result

    # --- Edge cases ---

    def test_unicode_stripped_ascii_preserved(self):
        """Unicode removed but ASCII preserved."""
        result = MissionStorageHelper.sanitize_mission_name("Mission★Test")
        assert "★" not in result
        assert "Mission" in result
        assert "Test" in result

    def test_special_characters_stripped(self):
        """HTML/script characters stripped."""
        result = MissionStorageHelper.sanitize_mission_name("<script>alert(1)</script>")
        assert "<" not in result
        assert ">" not in result

    def test_result_is_filesystem_safe(self):
        """Result contains only safe characters."""
        result = MissionStorageHelper.sanitize_mission_name("Test!@#$%^&*()")
        # Only alphanumeric, underscore, hyphen should remain
        assert re.match(r'^[A-Za-z0-9_-]*$', result) or result.startswith("mission_")
