# -*- coding: utf-8 -*-
"""
Provider Contract Tests

Phase 1 - Provider Abstraction Hardening:
Tests to verify provider implementations follow the base provider interface
and error handling contract defined in AI_CODE_REFERENCE.md.

These tests ensure:
1. Providers raise ProviderError subclasses (not RuntimeError/Exception)
2. CSV provider handles missing files gracefully
3. Registry metadata includes polling/streaming/auth info
4. Factory functions validate config inputs

Run with: pytest tests/test_provider_contract.py

Qt5/Qt6 Compatible: No Qt dependencies in tests.
"""

import os
import tempfile
import shutil
from pathlib import Path

# Use try/except for pytest import to allow running without pytest installed
try:
    import pytest
    PYTEST_AVAILABLE = True
except ImportError:
    PYTEST_AVAILABLE = False
    # Provide minimal test harness if pytest not available
    class pytest:
        @staticmethod
        def raises(exc_class):
            class RaisesContext:
                def __init__(self):
                    self.value = None
                def __enter__(self):
                    return self
                def __exit__(self, exc_type, exc_val, exc_tb):
                    if exc_type is None:
                        raise AssertionError(f"Expected {exc_class} but no exception raised")
                    if not issubclass(exc_type, exc_class):
                        return False  # Re-raise
                    self.value = exc_val  # Store exception for inspection
                    return True  # Suppress
            return RaisesContext()

        @staticmethod
        def fixture(func):
            return func


from sartracker.providers.csv import FileCSVProvider, _create_csv_provider
from sartracker.providers.registry import registry, ProviderMetadata
from sartracker.utils.exceptions import ProviderError, ProviderDataError

# Import traccar_http to trigger its self-registration (optional - needs requests)
TRACCAR_HTTP_AVAILABLE = False
try:
    import sartracker.providers.traccar_http  # noqa: F401
    TRACCAR_HTTP_AVAILABLE = True
except ImportError as e:
    print(f"Warning: Traccar HTTP provider not available ({e}). Skipping HTTP tests.")


# ============================================================================
# Test Fixtures
# ============================================================================

@pytest.fixture
def temp_dir():
    """Create temporary directory for test CSV files."""
    temp_path = tempfile.mkdtemp()
    yield temp_path
    shutil.rmtree(temp_path)


@pytest.fixture
def valid_csv_file(temp_dir):
    """Create valid Traccar CSV export file."""
    csv_path = os.path.join(temp_dir, 'test_device.csv')
    content = """Device:,test_device,,,,,,
Valid,Time,Latitude,Longitude,Altitude,Speed,Address,Attributes
true,2025-11-15T14:30:00Z,52.123,-9.456,100 m,5.0 kn,,batteryLevel=98.0
true,2025-11-15T14:31:00Z,52.124,-9.457,101 m,6.0 kn,,batteryLevel=97.0
"""
    with open(csv_path, 'w') as f:
        f.write(content)
    return csv_path


@pytest.fixture
def invalid_csv_file(temp_dir):
    """Create CSV file missing required headers."""
    csv_path = os.path.join(temp_dir, 'invalid.csv')
    content = """Invalid,Headers,Only
foo,bar,baz
"""
    with open(csv_path, 'w') as f:
        f.write(content)
    return csv_path


# ============================================================================
# CSV Provider Contract Tests
# ============================================================================

def test_csv_provider_missing_file():
    """Test CSV provider raises ProviderDataError for missing file."""
    provider = FileCSVProvider('/nonexistent/path/file.csv')

    with pytest.raises(ProviderDataError) as exc_info:
        provider.get_current()

    # Verify error attributes
    assert exc_info.value.provider_name == 'csv'
    assert exc_info.value.recoverable is True
    assert 'does not exist' in str(exc_info.value).lower()


def test_csv_provider_missing_directory():
    """Test CSV provider raises ProviderDataError for missing directory."""
    provider = FileCSVProvider('/nonexistent/directory')

    with pytest.raises(ProviderDataError) as exc_info:
        provider.get_devices()

    assert exc_info.value.provider_name == 'csv'
    assert exc_info.value.recoverable is True


def test_csv_provider_empty_directory(temp_dir):
    """Test CSV provider raises ProviderDataError for empty directory."""
    provider = FileCSVProvider(temp_dir)

    with pytest.raises(ProviderDataError) as exc_info:
        provider.get_breadcrumbs()

    # Debug output (will be visible if test fails)
    error_msg = str(exc_info.value).lower()
    if 'no csv files found' not in error_msg:
        print(f"DEBUG: Expected 'no csv files found' in error message")
        print(f"DEBUG: Actual message: {repr(error_msg)}")

    assert exc_info.value.provider_name == 'csv'
    assert 'no csv files found' in error_msg or 'no csv files' in error_msg


def test_csv_provider_invalid_headers(invalid_csv_file):
    """Test CSV provider raises ProviderDataError for missing required headers."""
    provider = FileCSVProvider(invalid_csv_file)

    with pytest.raises(ProviderDataError) as exc_info:
        provider.get_current()

    assert exc_info.value.provider_name == 'csv'
    assert 'missing required headers' in str(exc_info.value).lower()


def test_csv_provider_valid_file(valid_csv_file):
    """Test CSV provider successfully reads valid file."""
    provider = FileCSVProvider(valid_csv_file)

    positions = provider.get_current()

    assert len(positions) == 1  # One device
    assert positions[0]['device_id'] == 'test_device'
    assert positions[0]['name'] == 'test_device'
    assert positions[0]['lat'] == 52.124  # Last position
    assert positions[0]['lon'] == -9.457
    assert 'battery' in positions[0]


def test_csv_provider_test_connection_false_for_missing():
    """Test CSV provider test_connection returns False (no exception)."""
    provider = FileCSVProvider('/nonexistent/path')

    result = provider.test_connection()

    assert result is False  # Must not raise exception


def test_csv_provider_test_connection_true_for_valid(valid_csv_file):
    """Test CSV provider test_connection returns True for valid file."""
    provider = FileCSVProvider(valid_csv_file)

    result = provider.test_connection()

    assert result is True


# ============================================================================
# CSV Factory Function Tests
# ============================================================================

def test_csv_factory_missing_csv_path():
    """Test CSV factory raises ProviderDataError for missing csv_path."""
    with pytest.raises(ProviderDataError) as exc_info:
        _create_csv_provider({})

    assert exc_info.value.provider_name == 'csv'
    assert 'csv_path' in str(exc_info.value).lower()


def test_csv_factory_invalid_config_type():
    """Test CSV factory raises ProviderDataError for non-dict config."""
    with pytest.raises(ProviderDataError) as exc_info:
        _create_csv_provider("not a dict")

    assert exc_info.value.provider_name == 'csv'


def test_csv_factory_empty_csv_path():
    """Test CSV factory raises ProviderDataError for empty csv_path."""
    with pytest.raises(ProviderDataError) as exc_info:
        _create_csv_provider({'csv_path': ''})

    assert exc_info.value.provider_name == 'csv'


def test_csv_factory_valid_config(valid_csv_file):
    """Test CSV factory creates provider with valid config."""
    provider = _create_csv_provider({'csv_path': valid_csv_file})

    assert isinstance(provider, FileCSVProvider)
    assert provider.csv_path == valid_csv_file


# ============================================================================
# Registry Metadata Tests
# ============================================================================

def test_registry_csv_metadata_present():
    """Test CSV provider is registered with correct metadata."""
    assert registry.is_registered('csv')

    metadata = registry.get_metadata('csv')

    assert metadata.name == 'csv'
    assert metadata.display_name == 'CSV Files'
    assert metadata.requires_config is True
    assert 'csv_path' in metadata.config_schema


def test_registry_csv_metadata_capabilities():
    """Test CSV provider metadata includes Phase 1 capabilities."""
    metadata = registry.get_metadata('csv')

    assert metadata.supports_polling is False
    assert metadata.supports_streaming is False
    assert metadata.auth_modes == []


def test_registry_traccar_http_metadata_present():
    """Test Traccar HTTP provider is registered with correct metadata."""
    if not TRACCAR_HTTP_AVAILABLE:
        print("  (skipped - requests not available)")
        return

    assert registry.is_registered('traccar_http')

    metadata = registry.get_metadata('traccar_http')

    assert metadata.name == 'traccar_http'
    assert metadata.display_name == 'Traccar Server (HTTP)'
    assert metadata.requires_config is True
    assert 'base_url' in metadata.config_schema
    assert 'auth_type' in metadata.config_schema
    assert 'timeout_s' in metadata.config_schema
    assert 'cache_ttl' in metadata.config_schema
    assert 'enable_last_good_cache' in metadata.config_schema


def test_registry_traccar_http_metadata_capabilities():
    """Test Traccar HTTP provider metadata includes Phase 1 capabilities."""
    if not TRACCAR_HTTP_AVAILABLE:
        print("  (skipped - requests not available)")
        return

    metadata = registry.get_metadata('traccar_http')

    assert metadata.supports_polling is True
    assert metadata.supports_streaming is False
    assert metadata.auth_modes == ['basic', 'bearer']


def test_registry_get_metadata_missing_provider():
    """Test registry.get_metadata raises KeyError for unknown provider."""
    with pytest.raises(KeyError) as exc_info:
        registry.get_metadata('nonexistent_provider')

    assert 'not registered' in str(exc_info.value).lower()


def test_registry_get_provider_via_factory(valid_csv_file):
    """Test registry.get_provider uses factory with validation."""
    provider = registry.get_provider('csv', {'csv_path': valid_csv_file})

    assert isinstance(provider, FileCSVProvider)


def test_registry_list_providers_includes_both():
    """Test registry.list_providers returns all registered providers."""
    providers = registry.list_providers()

    provider_names = [p.name for p in providers]
    assert 'csv' in provider_names

    # Traccar HTTP is only registered if requests module available
    if TRACCAR_HTTP_AVAILABLE:
        assert 'traccar_http' in provider_names
    else:
        print("  (traccar_http check skipped - requests not available)")


# ============================================================================
# Exception Hierarchy Tests
# ============================================================================

def test_provider_errors_inherit_from_base():
    """Test ProviderError subclasses inherit from ProviderError."""
    from sartracker.utils.exceptions import ProviderAuthError, ProviderNetworkError, ProviderDataError

    assert issubclass(ProviderAuthError, ProviderError)
    assert issubclass(ProviderNetworkError, ProviderError)
    assert issubclass(ProviderDataError, ProviderError)


def test_provider_error_attributes():
    """Test ProviderError has expected attributes."""
    error = ProviderDataError(
        "Test error message",
        provider_name='test_provider',
        recoverable=True
    )

    assert error.message == "Test error message"
    assert error.provider_name == 'test_provider'
    assert error.recoverable is True
    assert error.severity == 'error'  # Default for ProviderDataError


# ============================================================================
# Main (for running without pytest)
# ============================================================================

def run_all_tests():
    """Run all tests manually (if pytest not available)."""
    print("Running provider contract tests...")

    tests = [
        test_csv_provider_missing_file,
        test_csv_provider_missing_directory,
        test_csv_factory_missing_csv_path,
        test_csv_factory_invalid_config_type,
        test_csv_factory_empty_csv_path,
        test_registry_csv_metadata_present,
        test_registry_csv_metadata_capabilities,
        test_registry_traccar_http_metadata_present,
        test_registry_traccar_http_metadata_capabilities,
        test_registry_get_metadata_missing_provider,
        test_registry_list_providers_includes_both,
        test_provider_errors_inherit_from_base,
        test_provider_error_attributes,
    ]

    # Tests requiring fixtures - create separate temp directories for each
    # Test 1: Empty directory (must be truly empty)
    empty_temp_dir = tempfile.mkdtemp()
    try:
        test_csv_provider_empty_directory(empty_temp_dir)
    finally:
        shutil.rmtree(empty_temp_dir)

    # Test 2: Invalid CSV file (separate directory)
    invalid_temp_dir = tempfile.mkdtemp()
    try:
        invalid_csv_path = os.path.join(invalid_temp_dir, 'invalid.csv')
        with open(invalid_csv_path, 'w') as f:
            f.write("Invalid,Headers,Only\nfoo,bar,baz\n")
        test_csv_provider_invalid_headers(invalid_csv_path)
    finally:
        shutil.rmtree(invalid_temp_dir)

    # Test 3: Valid CSV file (separate directory)
    valid_temp_dir = tempfile.mkdtemp()
    try:
        valid_csv_path = os.path.join(valid_temp_dir, 'test_device.csv')
        with open(valid_csv_path, 'w') as f:
            f.write("""Device:,test_device,,,,,,
Valid,Time,Latitude,Longitude,Altitude,Speed,Address,Attributes
true,2025-11-15T14:30:00Z,52.123,-9.456,100 m,5.0 kn,,batteryLevel=98.0
true,2025-11-15T14:31:00Z,52.124,-9.457,101 m,6.0 kn,,batteryLevel=97.0
""")
        test_csv_provider_valid_file(valid_csv_path)
        test_csv_provider_test_connection_true_for_valid(valid_csv_path)
        test_csv_factory_valid_config(valid_csv_path)
        test_registry_get_provider_via_factory(valid_csv_path)
    finally:
        shutil.rmtree(valid_temp_dir)

    passed = 0
    failed = 0

    for test_func in tests:
        try:
            test_func()
            print(f"✓ {test_func.__name__}")
            passed += 1
        except Exception as e:
            print(f"✗ {test_func.__name__}: {e}")
            failed += 1

    print(f"\n{passed} passed, {failed} failed")
    return failed == 0


if __name__ == '__main__':
    if not PYTEST_AVAILABLE:
        success = run_all_tests()
        exit(0 if success else 1)
    else:
        print("Use 'pytest tests/test_provider_contract.py' to run tests")
