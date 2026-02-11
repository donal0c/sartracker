# -*- coding: utf-8 -*-
"""Provider contract tests for active providers.

CSV provider support has been removed; these tests verify the active
Traccar provider contract and exception hierarchy.
"""

try:
    import pytest
except ImportError:  # pragma: no cover
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
                        return False
                    self.value = exc_val
                    return True
            return RaisesContext()


from sartracker.providers.registry import registry
from sartracker.utils.exceptions import ProviderError

TRACCAR_HTTP_AVAILABLE = False
try:
    import sartracker.providers.traccar_http  # noqa: F401
    TRACCAR_HTTP_AVAILABLE = True
except ImportError as e:  # pragma: no cover - optional dependency path
    print(f"Warning: Traccar HTTP provider not available ({e}). Skipping provider metadata tests.")


def test_registry_csv_provider_removed():
    """CSV provider should not be registered in active provider registry."""
    assert registry.is_registered('csv') is False


@pytest.mark.skipif(not TRACCAR_HTTP_AVAILABLE, reason="traccar_http provider unavailable")
def test_registry_traccar_http_metadata_present():
    """Traccar HTTP provider is registered with expected metadata."""
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


@pytest.mark.skipif(not TRACCAR_HTTP_AVAILABLE, reason="traccar_http provider unavailable")
def test_registry_traccar_http_metadata_capabilities():
    """Traccar HTTP metadata advertises polling/auth capabilities."""
    metadata = registry.get_metadata('traccar_http')
    assert metadata.supports_polling is True
    assert metadata.supports_streaming is False
    assert metadata.auth_modes == ['basic', 'bearer']


def test_registry_get_metadata_missing_provider():
    """Unknown providers should raise KeyError from get_metadata."""
    with pytest.raises(KeyError) as exc_info:
        registry.get_metadata('nonexistent_provider')

    assert 'not registered' in str(exc_info.value).lower()


def test_registry_get_provider_missing_provider():
    """Unknown providers should raise KeyError from get_provider."""
    with pytest.raises(KeyError) as exc_info:
        registry.get_provider('csv', {})

    assert 'not registered' in str(exc_info.value).lower()


@pytest.mark.skipif(not TRACCAR_HTTP_AVAILABLE, reason="traccar_http provider unavailable")
def test_registry_list_providers_contains_traccar_http_only_active_source():
    """Provider list should include Traccar and exclude removed CSV provider."""
    providers = registry.list_providers()
    names = [p.name for p in providers]

    assert 'traccar_http' in names
    assert 'csv' not in names


def test_provider_errors_inherit_from_base():
    """Provider error types must derive from ProviderError."""
    from sartracker.utils.exceptions import ProviderAuthError, ProviderNetworkError, ProviderDataError

    assert issubclass(ProviderAuthError, ProviderError)
    assert issubclass(ProviderNetworkError, ProviderError)
    assert issubclass(ProviderDataError, ProviderError)


def test_provider_error_attributes():
    """ProviderDataError exposes expected structured attributes."""
    from sartracker.utils.exceptions import ProviderDataError

    error = ProviderDataError(
        "Test error message",
        provider_name='test_provider',
        recoverable=True,
    )

    assert error.message == "Test error message"
    assert error.provider_name == 'test_provider'
    assert error.recoverable is True
    assert error.severity == 'error'
