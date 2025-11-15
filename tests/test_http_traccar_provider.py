import os
import sys
import types
import unittest
from pathlib import Path

try:
    import requests  # noqa: F401  # Needed to ensure provider module can be imported
except ImportError:
    dummy_requests = types.ModuleType("requests")

    class _DummySession:
        def __init__(self, *args, **kwargs):
            pass

    dummy_requests.Session = _DummySession

    class _DummyHTTPError(Exception):
        pass

    class _DummyTimeout(_DummyHTTPError):
        pass

    class _DummyConnectionError(_DummyHTTPError):
        pass

    class _DummyRequestException(_DummyHTTPError):
        pass

    dummy_requests.exceptions = types.SimpleNamespace(
        HTTPError=_DummyHTTPError,
        Timeout=_DummyTimeout,
        ConnectionError=_DummyConnectionError,
        RequestException=_DummyRequestException
    )

    sys.modules['requests'] = dummy_requests

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROJECT_PARENT = PROJECT_ROOT.parent
if str(PROJECT_PARENT) not in sys.path:
    sys.path.insert(0, str(PROJECT_PARENT))

from sartracker.providers.http_traccar import HttpTraccarProvider


class HttpTraccarProviderConfigTests(unittest.TestCase):
    ENV_LOOKBACK = "SARTRACKER_HTTP_ROUTE_LOOKBACK_HOURS"
    ENV_FALLBACK = "SARTRACKER_HTTP_ROUTE_FALLBACK_HOURS"

    def setUp(self):
        self._env_backup = {}
        for key in (self.ENV_LOOKBACK, self.ENV_FALLBACK):
            if key in os.environ:
                self._env_backup[key] = os.environ[key]
                del os.environ[key]

    def tearDown(self):
        for key in (self.ENV_LOOKBACK, self.ENV_FALLBACK):
            if key in os.environ:
                del os.environ[key]
        os.environ.update(self._env_backup)

    def test_defaults_used_when_no_config_or_env(self):
        provider = HttpTraccarProvider("http://example.com", "user", "pass")
        self.assertEqual(
            provider.route_lookback_hours,
            HttpTraccarProvider.DEFAULT_ROUTE_LOOKBACK_HOURS
        )
        self.assertGreaterEqual(provider.route_fallback_hours, provider.route_lookback_hours)

    def test_env_overrides_default(self):
        os.environ[self.ENV_LOOKBACK] = "12"
        os.environ[self.ENV_FALLBACK] = "24"
        provider = HttpTraccarProvider("http://example.com", "user", "pass")
        self.assertEqual(provider.route_lookback_hours, 12)
        self.assertEqual(provider.route_fallback_hours, 24)

    def test_config_overrides_env(self):
        os.environ[self.ENV_LOOKBACK] = "5"
        provider = HttpTraccarProvider(
            "http://example.com",
            "user",
            "pass",
            route_lookback_hours=8,
            route_fallback_hours=10
        )
        self.assertEqual(provider.route_lookback_hours, 8)
        self.assertEqual(provider.route_fallback_hours, 10)

    def test_fallback_never_less_than_lookback(self):
        provider = HttpTraccarProvider(
            "http://example.com",
            "user",
            "pass",
            route_lookback_hours=24,
            route_fallback_hours=12
        )
        self.assertEqual(provider.route_fallback_hours, 24)

    def test_normalize_device_handles_non_dict_payload(self):
        provider = HttpTraccarProvider("http://example.com", "user", "pass")
        result = provider._normalize_device(None)  # type: ignore[arg-type]
        self.assertIsInstance(result, dict)
        self.assertEqual(result['device_id'], 'Unknown')
        self.assertEqual(result['status'], 'unknown')
        self.assertIsNone(result['last_update'])


if __name__ == "__main__":
    unittest.main()

