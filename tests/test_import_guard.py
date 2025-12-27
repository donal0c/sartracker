# -*- coding: utf-8 -*-
"""
Unit tests for services/import_guard.py

Phase 2 Refactor: Tests import error tracking and safe-mode support

These tests verify:
1. ImportErrorRecord and ImportReport dataclasses work correctly
2. Error tracking functions capture failures with proper classification
3. Error logging writes correct format to temp files
4. Error formatting produces human-readable output
5. Critical vs optional error distinction is preserved
"""
import pytest
import sys
import os
from pathlib import Path
from unittest.mock import patch, MagicMock
import tempfile


class TestImportErrorRecord:
    """Tests for ImportErrorRecord dataclass."""

    def test_create_critical_error(self):
        """Test creating a critical (non-optional) error record."""
        from sartracker.services.import_guard import ImportErrorRecord

        exc = ValueError("Test error")
        record = ImportErrorRecord(
            module_name="test.module",
            exception=exc,
            traceback_str="Traceback...",
            is_optional=False,
        )

        assert record.module_name == "test.module"
        assert record.exception is exc
        assert record.traceback_str == "Traceback..."
        assert record.is_optional is False

    def test_create_optional_error(self):
        """Test creating an optional error record."""
        from sartracker.services.import_guard import ImportErrorRecord

        exc = ImportError("Optional module missing")
        record = ImportErrorRecord(
            module_name="test.optional",
            exception=exc,
            traceback_str="Traceback...",
            is_optional=True,
        )

        assert record.is_optional is True

    def test_default_is_optional_false(self):
        """Test that is_optional defaults to False (critical)."""
        from sartracker.services.import_guard import ImportErrorRecord

        record = ImportErrorRecord(
            module_name="test",
            exception=Exception("test"),
            traceback_str="tb",
        )

        assert record.is_optional is False


class TestImportReport:
    """Tests for ImportReport dataclass."""

    def test_default_values(self):
        """Test ImportReport has correct defaults."""
        from sartracker.services.import_guard import ImportReport

        report = ImportReport()

        assert report.ok is True
        assert report.errors == []
        assert report.warnings == []

    def test_report_with_errors(self):
        """Test ImportReport can hold multiple errors."""
        from sartracker.services.import_guard import ImportReport, ImportErrorRecord

        err1 = ImportErrorRecord("mod1", Exception("e1"), "tb1", is_optional=False)
        err2 = ImportErrorRecord("mod2", Exception("e2"), "tb2", is_optional=True)

        report = ImportReport(
            ok=False,
            errors=[err1, err2],
            warnings=["warning1"],
        )

        assert report.ok is False
        assert len(report.errors) == 2
        assert "warning1" in report.warnings


class TestTrackImportError:
    """Tests for track_import_error function."""

    def test_critical_error_sets_ok_false(self):
        """Test track_import_error sets ok=False for critical errors."""
        from sartracker.services.import_guard import ImportReport, track_import_error

        report = ImportReport()
        assert report.ok is True

        result = track_import_error(
            report,
            'test.critical.module',
            ImportError("Critical failure"),
        )

        assert result is None  # Default fallback value
        assert report.ok is False
        assert len(report.errors) == 1
        assert report.errors[0].module_name == 'test.critical.module'
        assert report.errors[0].is_optional is False

    def test_optional_error_preserves_ok_true(self):
        """Test track_import_error preserves ok=True for optional errors."""
        from sartracker.services.import_guard import ImportReport, track_import_error

        report = ImportReport()
        assert report.ok is True

        result = track_import_error(
            report,
            'test.optional.module',
            ImportError("Optional failure"),
            is_optional=True,
        )

        assert result is None
        assert report.ok is True  # Still True for optional failures
        assert len(report.errors) == 1
        assert report.errors[0].is_optional is True
        assert len(report.warnings) == 1

    def test_custom_fallback_value(self):
        """Test track_import_error returns custom fallback value."""
        from sartracker.services.import_guard import ImportReport, track_import_error

        report = ImportReport()

        class MockClass:
            pass

        result = track_import_error(
            report,
            'test.module',
            ImportError("error"),
            fallback_value=MockClass,
        )

        assert result is MockClass


class TestTrackOptionalImportError:
    """Tests for track_optional_import_error convenience function."""

    def test_always_optional(self):
        """Test track_optional_import_error always creates optional errors."""
        from sartracker.services.import_guard import (
            ImportReport, track_optional_import_error
        )

        report = ImportReport()

        result = track_optional_import_error(
            report,
            'test.optional',
            ImportError("error"),
        )

        assert result is None
        assert report.ok is True
        assert len(report.errors) == 1
        assert report.errors[0].is_optional is True


class TestWriteErrorLog:
    """Tests for write_error_log function."""

    def test_write_no_errors(self):
        """Test write_error_log with empty error list returns None."""
        from sartracker.services.import_guard import ImportReport, write_error_log

        report = ImportReport()
        result = write_error_log(report)

        assert result is None

    def test_write_critical_error(self, tmp_path):
        """Test write_error_log creates file with critical error."""
        from sartracker.services.import_guard import (
            ImportReport, ImportErrorRecord, write_error_log
        )

        report = ImportReport(
            ok=False,
            errors=[ImportErrorRecord(
                module_name="test.critical",
                exception=ImportError("Critical failure"),
                traceback_str="Full traceback here",
                is_optional=False,
            )],
        )

        with patch('tempfile.gettempdir', return_value=str(tmp_path)):
            log_path = write_error_log(report)

        assert log_path is not None
        assert log_path.exists()

        content = log_path.read_text()
        assert "SAR TRACKER IMPORT ERRORS" in content
        assert "test.critical" in content
        assert "Critical failure" in content
        assert "[CRITICAL]" in content
        assert "Full traceback here" in content

    def test_write_optional_error(self, tmp_path):
        """Test write_error_log marks optional errors correctly."""
        from sartracker.services.import_guard import (
            ImportReport, ImportErrorRecord, write_error_log
        )

        report = ImportReport(
            ok=True,
            errors=[ImportErrorRecord(
                module_name="test.optional",
                exception=ImportError("Optional failure"),
                traceback_str="Optional traceback",
                is_optional=True,
            )],
        )

        with patch('tempfile.gettempdir', return_value=str(tmp_path)):
            log_path = write_error_log(report)

        assert log_path is not None
        content = log_path.read_text()
        assert "[OPTIONAL]" in content

    def test_write_multiple_errors(self, tmp_path):
        """Test write_error_log handles multiple errors."""
        from sartracker.services.import_guard import (
            ImportReport, ImportErrorRecord, write_error_log
        )

        report = ImportReport(
            ok=False,
            errors=[
                ImportErrorRecord("mod1", ImportError("e1"), "tb1", is_optional=False),
                ImportErrorRecord("mod2", ImportError("e2"), "tb2", is_optional=True),
                ImportErrorRecord("mod3", ImportError("e3"), "tb3", is_optional=False),
            ],
        )

        with patch('tempfile.gettempdir', return_value=str(tmp_path)):
            log_path = write_error_log(report)

        content = log_path.read_text()
        assert "Critical failures: 2" in content
        assert "Optional failures: 1" in content
        assert "mod1" in content
        assert "mod2" in content
        assert "mod3" in content


class TestFormatErrorSummary:
    """Tests for format_error_summary function."""

    def test_format_critical_errors(self):
        """Test formatting with critical errors."""
        from sartracker.services.import_guard import (
            ImportReport, ImportErrorRecord, format_error_summary
        )

        report = ImportReport(
            ok=False,
            errors=[ImportErrorRecord(
                module_name="critical.module",
                exception=ImportError("Module not found"),
                traceback_str="Traceback (most recent call last):\n  ...",
                is_optional=False,
            )],
        )

        summary = format_error_summary(report)

        assert "failed to load" in summary.lower()
        assert "CRITICAL ERRORS" in summary
        assert "critical.module" in summary
        assert "Module not found" in summary
        assert "SUGGESTED ACTIONS" in summary
        assert "Diagnostics" in summary
        assert "Traceback" in summary

    def test_format_optional_errors(self):
        """Test formatting with optional errors only."""
        from sartracker.services.import_guard import (
            ImportReport, ImportErrorRecord, format_error_summary
        )

        report = ImportReport(
            ok=True,
            errors=[ImportErrorRecord(
                module_name="optional.module",
                exception=ImportError("Optional missing"),
                traceback_str="Traceback...",
                is_optional=True,
            )],
        )

        summary = format_error_summary(report)

        assert "OPTIONAL FEATURES UNAVAILABLE" in summary
        assert "optional.module" in summary

    def test_format_with_log_path(self):
        """Test formatting includes log path when provided."""
        from sartracker.services.import_guard import (
            ImportReport, ImportErrorRecord, format_error_summary
        )

        report = ImportReport(
            ok=False,
            errors=[ImportErrorRecord(
                module_name="test",
                exception=Exception("error"),
                traceback_str="tb",
                is_optional=False,
            )],
        )

        log_path = Path("/tmp/test_log.log")
        summary = format_error_summary(report, log_path)

        assert str(log_path) in summary

    def test_format_mixed_errors(self):
        """Test formatting with both critical and optional errors."""
        from sartracker.services.import_guard import (
            ImportReport, ImportErrorRecord, format_error_summary
        )

        report = ImportReport(
            ok=False,
            errors=[
                ImportErrorRecord("critical1", Exception("c1"), "tb1", is_optional=False),
                ImportErrorRecord("optional1", Exception("o1"), "tb2", is_optional=True),
                ImportErrorRecord("critical2", Exception("c2"), "tb3", is_optional=False),
            ],
        )

        summary = format_error_summary(report)

        assert "CRITICAL ERRORS" in summary
        assert "OPTIONAL FEATURES" in summary
        assert "critical1" in summary
        assert "optional1" in summary
        # First critical error traceback should be in technical details
        assert "tb1" in summary


class TestGetCriticalErrorCount:
    """Tests for get_critical_error_count function."""

    def test_no_errors(self):
        """Test count with no errors."""
        from sartracker.services.import_guard import ImportReport, get_critical_error_count

        report = ImportReport()
        assert get_critical_error_count(report) == 0

    def test_only_optional_errors(self):
        """Test count with only optional errors."""
        from sartracker.services.import_guard import (
            ImportReport, ImportErrorRecord, get_critical_error_count
        )

        report = ImportReport(
            errors=[
                ImportErrorRecord("opt1", Exception("e1"), "tb1", is_optional=True),
                ImportErrorRecord("opt2", Exception("e2"), "tb2", is_optional=True),
            ],
        )
        assert get_critical_error_count(report) == 0

    def test_mixed_errors(self):
        """Test count with mixed errors."""
        from sartracker.services.import_guard import (
            ImportReport, ImportErrorRecord, get_critical_error_count
        )

        report = ImportReport(
            errors=[
                ImportErrorRecord("crit1", Exception("e1"), "tb1", is_optional=False),
                ImportErrorRecord("opt1", Exception("e2"), "tb2", is_optional=True),
                ImportErrorRecord("crit2", Exception("e3"), "tb3", is_optional=False),
            ],
        )
        assert get_critical_error_count(report) == 2


class TestGetFirstCriticalError:
    """Tests for get_first_critical_error function."""

    def test_no_errors(self):
        """Test with no errors returns None."""
        from sartracker.services.import_guard import ImportReport, get_first_critical_error

        report = ImportReport()
        assert get_first_critical_error(report) is None

    def test_only_optional_errors(self):
        """Test with only optional errors returns None."""
        from sartracker.services.import_guard import (
            ImportReport, ImportErrorRecord, get_first_critical_error
        )

        report = ImportReport(
            errors=[
                ImportErrorRecord("opt1", Exception("e1"), "tb1", is_optional=True),
            ],
        )
        assert get_first_critical_error(report) is None

    def test_returns_first_critical(self):
        """Test returns first critical error even if optional comes first."""
        from sartracker.services.import_guard import (
            ImportReport, ImportErrorRecord, get_first_critical_error
        )

        crit1 = ImportErrorRecord("crit1", Exception("c1"), "tb1", is_optional=False)
        crit2 = ImportErrorRecord("crit2", Exception("c2"), "tb2", is_optional=False)

        report = ImportReport(
            errors=[
                ImportErrorRecord("opt1", Exception("o1"), "tb0", is_optional=True),
                crit1,
                crit2,
            ],
        )

        result = get_first_critical_error(report)
        assert result is crit1
        assert result.module_name == "crit1"


class TestGetSafeModeReason:
    """Tests for get_safe_mode_reason function."""

    def test_no_errors(self):
        """Test with no errors returns generic message."""
        from sartracker.services.import_guard import ImportReport, get_safe_mode_reason

        report = ImportReport()
        reason = get_safe_mode_reason(report)
        assert "Critical import failures detected" in reason

    def test_with_critical_error(self):
        """Test with critical error includes module and exception."""
        from sartracker.services.import_guard import (
            ImportReport, ImportErrorRecord, get_safe_mode_reason
        )

        report = ImportReport(
            errors=[ImportErrorRecord(
                module_name="test.critical",
                exception=ImportError("Module not found"),
                traceback_str="tb",
                is_optional=False,
            )],
        )

        reason = get_safe_mode_reason(report)
        assert "test.critical" in reason
        assert "Module not found" in reason


class TestConvertLegacyErrors:
    """Tests for convert_legacy_errors function."""

    def test_empty_list(self):
        """Test converting empty error list."""
        from sartracker.services.import_guard import convert_legacy_errors

        report = convert_legacy_errors([])
        assert report.ok is True
        assert report.errors == []

    def test_critical_error(self):
        """Test converting critical error."""
        from sartracker.services.import_guard import convert_legacy_errors

        errors = [
            ('test.module', ImportError('error'), 'traceback'),
        ]
        report = convert_legacy_errors(errors)

        assert report.ok is False
        assert len(report.errors) == 1
        assert report.errors[0].module_name == 'test.module'
        assert report.errors[0].is_optional is False

    def test_optional_http_provider(self):
        """Test that traccar_http is detected as optional."""
        from sartracker.services.import_guard import convert_legacy_errors

        errors = [
            ('providers.traccar_http', ImportError('error'), 'traceback'),
        ]
        report = convert_legacy_errors(errors)

        # BUG FIX VERIFIED: Optional-only errors should have ok=True
        assert report.ok is True
        assert len(report.errors) == 1
        assert report.errors[0].is_optional is True

    def test_mixed_critical_and_optional(self):
        """Test that mixed errors correctly sets ok=False."""
        from sartracker.services.import_guard import convert_legacy_errors

        errors = [
            ('providers.traccar_http', ImportError('optional error'), 'tb1'),
            ('layers.LayerManager', ImportError('critical error'), 'tb2'),
        ]
        report = convert_legacy_errors(errors)

        assert report.ok is False  # Critical error present
        assert len(report.errors) == 2
        assert report.errors[0].is_optional is True
        assert report.errors[1].is_optional is False

    def test_malformed_tuple_skipped(self):
        """Test that malformed tuples are skipped with warning."""
        from sartracker.services.import_guard import convert_legacy_errors

        errors = [
            ('valid.module', ImportError('error'), 'traceback'),
            ('two_element_only', ImportError('error')),  # Missing traceback
            'not_a_tuple_at_all',
        ]
        report = convert_legacy_errors(errors)

        # Only the valid entry should be processed
        assert len(report.errors) == 1
        assert report.errors[0].module_name == 'valid.module'


class TestSetAndGetImportReport:
    """Tests for set_import_report and get_import_report functions."""

    def test_set_and_get(self):
        """Test setting and getting import report."""
        from sartracker.services.import_guard import (
            ImportReport, set_import_report, get_import_report
        )

        # Create and set a report
        report = ImportReport(ok=True)
        set_import_report(report)

        # Get it back
        retrieved = get_import_report()
        assert retrieved is report


class TestEdgeCases:
    """Edge case and robustness tests."""

    def test_exception_with_unicode(self):
        """Test handling exceptions with unicode characters."""
        from sartracker.services.import_guard import (
            ImportReport, ImportErrorRecord, format_error_summary
        )

        report = ImportReport(
            ok=False,
            errors=[ImportErrorRecord(
                module_name="test.unicode",
                exception=ValueError("Error with unicode: \u00e9\u00e8\u00ea"),
                traceback_str="Traceback with \u00e9\u00e8\u00ea",
                is_optional=False,
            )],
        )

        summary = format_error_summary(report)
        assert "unicode" in summary.lower()

    def test_very_long_traceback(self, tmp_path):
        """Test handling very long tracebacks."""
        from sartracker.services.import_guard import (
            ImportReport, ImportErrorRecord, write_error_log
        )

        long_tb = "Line " * 10000  # Very long traceback

        report = ImportReport(
            ok=False,
            errors=[ImportErrorRecord(
                module_name="test.long",
                exception=Exception("error"),
                traceback_str=long_tb,
                is_optional=False,
            )],
        )

        with patch('tempfile.gettempdir', return_value=str(tmp_path)):
            log_path = write_error_log(report)

        assert log_path is not None
        assert log_path.exists()
        # File should be written successfully despite long content

    def test_empty_module_name(self):
        """Test handling empty module name."""
        from sartracker.services.import_guard import (
            ImportReport, ImportErrorRecord, format_error_summary
        )

        report = ImportReport(
            ok=False,
            errors=[ImportErrorRecord(
                module_name="",
                exception=Exception("error"),
                traceback_str="tb",
                is_optional=False,
            )],
        )

        # Should not raise
        summary = format_error_summary(report)
        assert "CRITICAL ERRORS" in summary

    def test_track_multiple_errors(self):
        """Test tracking multiple errors in sequence."""
        from sartracker.services.import_guard import ImportReport, track_import_error

        report = ImportReport()

        track_import_error(report, 'mod1', ImportError('e1'))
        track_import_error(report, 'mod2', ImportError('e2'))
        track_import_error(report, 'mod3', ImportError('e3'), is_optional=True)

        assert report.ok is False
        assert len(report.errors) == 3
        assert len([e for e in report.errors if not e.is_optional]) == 2
        assert len([e for e in report.errors if e.is_optional]) == 1
