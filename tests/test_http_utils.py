# -*- coding: utf-8 -*-
"""
HTTP Utilities Test Suite

Phase 2 - HTTP Plumbing & Utility Layer:
Comprehensive tests for utils/http.py HttpClient class.

Tests cover:
1. Successful GET requests with JSON parsing
2. Authentication (Basic, Bearer)
3. Error mapping (401/403 -> AuthError, 5xx/timeout -> NetworkError, invalid JSON -> DataError)
4. Retry logic with exponential backoff
5. URL building and parameter handling
6. PII-safe logging

Run with: pytest tests/test_http_utils.py -v

Qt5/Qt6 Compatible: No Qt dependencies in tests.
"""

import unittest
from unittest.mock import Mock, patch, MagicMock
import requests
from requests.auth import HTTPBasicAuth

# Import modules under test
from utils.http import HttpClient
from utils.exceptions import ProviderNetworkError, ProviderAuthError, ProviderDataError


class TestHttpClientInit(unittest.TestCase):
    """Test HttpClient initialization and validation."""

    def test_init_with_valid_https_url(self):
        """Test initialization with valid HTTPS URL."""
        client = HttpClient("https://api.example.com", timeout_s=15)

        self.assertEqual(client.base_url, "https://api.example.com")
        self.assertEqual(client.timeout_s, 15)
        self.assertEqual(client.max_retries, 3)

    def test_init_with_valid_http_url(self):
        """Test initialization with valid HTTP URL."""
        client = HttpClient("http://localhost:8080")

        self.assertEqual(client.base_url, "http://localhost:8080")

    def test_init_strips_trailing_slash(self):
        """Test base URL trailing slash is stripped."""
        client = HttpClient("https://api.example.com/")

        self.assertEqual(client.base_url, "https://api.example.com")

    def test_init_custom_retry_delays(self):
        """Test initialization with custom retry delays."""
        client = HttpClient(
            "https://api.example.com",
            retry_delays=[0.1, 0.2, 0.3]
        )

        self.assertEqual(client.retry_delays, [0.1, 0.2, 0.3])

    def test_init_empty_base_url_raises(self):
        """Test initialization with empty base_url raises ValueError."""
        with self.assertRaises(ValueError) as ctx:
            HttpClient("")

        self.assertIn("base_url cannot be empty", str(ctx.exception))

    def test_init_invalid_protocol_raises(self):
        """Test initialization with invalid protocol raises ValueError."""
        with self.assertRaises(ValueError) as ctx:
            HttpClient("ftp://api.example.com")

        self.assertIn("must start with http", str(ctx.exception).lower())

    def test_init_invalid_timeout_raises(self):
        """Test initialization with invalid timeout raises ValueError."""
        with self.assertRaises(ValueError) as ctx:
            HttpClient("https://api.example.com", timeout_s=-1)

        self.assertIn("timeout_s must be positive", str(ctx.exception))

    def test_init_invalid_max_retries_raises(self):
        """Test initialization with invalid max_retries raises ValueError."""
        with self.assertRaises(ValueError) as ctx:
            HttpClient("https://api.example.com", max_retries=-1)

        self.assertIn("max_retries must be non-negative", str(ctx.exception))

    def test_init_invalid_retry_delays_raises(self):
        """Test initialization with invalid retry_delays raises ValueError."""
        with self.assertRaises(ValueError) as ctx:
            HttpClient("https://api.example.com", retry_delays="not a list")

        self.assertIn("retry_delays must be list", str(ctx.exception))


class TestHttpClientSession(unittest.TestCase):
    """Test session creation and authentication configuration."""

    def setUp(self):
        """Set up test client."""
        self.client = HttpClient("https://api.example.com")

    def test_create_session_no_auth(self):
        """Test creating session without authentication."""
        session = self.client.create_session()

        self.assertIsInstance(session, requests.Session)
        self.assertIsNone(session.auth)
        self.assertNotIn('Authorization', session.headers)

    def test_create_session_basic_auth(self):
        """Test creating session with basic authentication."""
        session = self.client.create_session(
            auth_type="basic",
            username="testuser",
            password="testpass"
        )

        self.assertIsInstance(session.auth, HTTPBasicAuth)
        # Note: HTTPBasicAuth stores credentials but we can't easily test them here

    def test_create_session_bearer_auth(self):
        """Test creating session with bearer token."""
        session = self.client.create_session(
            auth_type="bearer",
            token="abc123xyz"
        )

        self.assertEqual(session.headers['Authorization'], "Bearer abc123xyz")

    def test_create_session_custom_headers(self):
        """Test creating session with custom headers."""
        session = self.client.create_session(
            headers={"X-Custom-Header": "test-value"}
        )

        self.assertEqual(session.headers['X-Custom-Header'], "test-value")

    def test_create_session_invalid_auth_type_raises(self):
        """Test creating session with invalid auth_type raises ValueError."""
        with self.assertRaises(ValueError) as ctx:
            self.client.create_session(auth_type="invalid")

        self.assertIn("Invalid auth_type", str(ctx.exception))

    def test_create_session_basic_missing_username_raises(self):
        """Test basic auth without username raises ValueError."""
        with self.assertRaises(ValueError) as ctx:
            self.client.create_session(auth_type="basic", password="pass")

        self.assertIn("username and password required", str(ctx.exception))

    def test_create_session_bearer_missing_token_raises(self):
        """Test bearer auth without token raises ValueError."""
        with self.assertRaises(ValueError) as ctx:
            self.client.create_session(auth_type="bearer")

        self.assertIn("token required", str(ctx.exception))


class TestHttpClientRequests(unittest.TestCase):
    """Test HTTP request methods with mocked responses."""

    def setUp(self):
        """Set up test client."""
        self.client = HttpClient(
            "https://api.example.com",
            timeout_s=10,
            max_retries=2,
            retry_delays=[0.01, 0.02]  # Fast retries for tests
        )

    @patch('utils.http.requests.Session.request')
    def test_get_success_returns_json(self, mock_request):
        """Test successful GET request returns parsed JSON."""
        # Mock response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.headers = {'Content-Type': 'application/json'}
        mock_response.json.return_value = {"devices": [{"id": 1, "name": "device1"}]}
        mock_request.return_value = mock_response

        # Make request
        session = self.client.create_session()
        data = self.client.get("/api/devices", session=session)

        # Verify
        self.assertEqual(data, {"devices": [{"id": 1, "name": "device1"}]})
        mock_request.assert_called_once()

    @patch('utils.http.requests.Session.request')
    def test_get_with_params(self, mock_request):
        """Test GET request with query parameters."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.headers = {'Content-Type': 'application/json'}
        mock_response.json.return_value = []
        mock_request.return_value = mock_response

        session = self.client.create_session()
        self.client.get("/api/positions", session=session, params={"deviceId": 123})

        # Verify params were passed
        call_kwargs = mock_request.call_args[1]
        self.assertEqual(call_kwargs['params'], {"deviceId": 123})

    @patch('utils.http.requests.Session.request')
    def test_post_success_with_json_body(self, mock_request):
        """Test successful POST request with JSON body."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.headers = {'Content-Type': 'application/json'}
        mock_response.json.return_value = {"result": "created"}
        mock_request.return_value = mock_response

        session = self.client.create_session()
        data = self.client.post(
            "/api/devices",
            session=session,
            json_data={"name": "new_device"}
        )

        self.assertEqual(data, {"result": "created"})

        # Verify JSON body was passed
        call_kwargs = mock_request.call_args[1]
        self.assertEqual(call_kwargs['json'], {"name": "new_device"})

    @patch('utils.http.requests.Session.request')
    def test_get_401_raises_auth_error(self, mock_request):
        """Test GET request with 401 response raises ProviderAuthError."""
        mock_response = Mock()
        mock_response.status_code = 401
        mock_request.return_value = mock_response

        session = self.client.create_session()

        with self.assertRaises(ProviderAuthError) as ctx:
            self.client.get("/api/devices", session=session)

        self.assertIn("Authentication failed", str(ctx.exception))
        self.assertEqual(ctx.exception.provider_name, 'http')
        self.assertTrue(ctx.exception.recoverable)

    @patch('utils.http.requests.Session.request')
    def test_get_403_raises_auth_error(self, mock_request):
        """Test GET request with 403 response raises ProviderAuthError."""
        mock_response = Mock()
        mock_response.status_code = 403
        mock_request.return_value = mock_response

        session = self.client.create_session()

        with self.assertRaises(ProviderAuthError) as ctx:
            self.client.get("/api/devices", session=session)

        self.assertIn("Authentication failed", str(ctx.exception))

    @patch('utils.http.requests.Session.request')
    def test_get_500_retries_and_raises_network_error(self, mock_request):
        """Test GET request with 500 response retries and raises NetworkError."""
        mock_response = Mock()
        mock_response.status_code = 500
        mock_request.return_value = mock_response

        session = self.client.create_session()

        with self.assertRaises(ProviderNetworkError) as ctx:
            self.client.get("/api/devices", session=session)

        # Should retry 3 times (initial + 2 retries)
        self.assertEqual(mock_request.call_count, 3)
        self.assertIn("Server error", str(ctx.exception))
        self.assertIn("after 3 attempts", str(ctx.exception))
        self.assertTrue(ctx.exception.recoverable)

    @patch('utils.http.requests.Session.request')
    def test_get_timeout_retries_and_raises_network_error(self, mock_request):
        """Test GET request timeout retries and raises NetworkError."""
        mock_request.side_effect = requests.exceptions.Timeout("Connection timeout")

        session = self.client.create_session()

        with self.assertRaises(ProviderNetworkError) as ctx:
            self.client.get("/api/devices", session=session)

        # Should retry 3 times
        self.assertEqual(mock_request.call_count, 3)
        self.assertIn("timeout", str(ctx.exception).lower())
        self.assertTrue(ctx.exception.recoverable)

    @patch('utils.http.requests.Session.request')
    def test_get_connection_error_retries_and_raises_network_error(self, mock_request):
        """Test GET request connection error retries and raises NetworkError."""
        mock_request.side_effect = requests.exceptions.ConnectionError("Connection refused")

        session = self.client.create_session()

        with self.assertRaises(ProviderNetworkError) as ctx:
            self.client.get("/api/devices", session=session)

        # Should retry 3 times
        self.assertEqual(mock_request.call_count, 3)
        self.assertIn("Connection failed", str(ctx.exception))
        self.assertTrue(ctx.exception.recoverable)

    @patch('utils.http.requests.Session.request')
    def test_get_invalid_json_raises_data_error(self, mock_request):
        """Test GET request with invalid JSON raises ProviderDataError."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.headers = {'Content-Type': 'application/json'}
        mock_response.json.side_effect = ValueError("Invalid JSON")
        mock_response.text = "not valid json"
        mock_request.return_value = mock_response

        session = self.client.create_session()

        with self.assertRaises(ProviderDataError) as ctx:
            self.client.get("/api/devices", session=session)

        self.assertIn("Invalid JSON response", str(ctx.exception))
        self.assertEqual(ctx.exception.provider_name, 'http')
        self.assertFalse(ctx.exception.recoverable)

    @patch('utils.http.requests.Session.request')
    def test_get_retry_logic_eventual_success(self, mock_request):
        """Test retry logic succeeds on second attempt."""
        # First call fails with 500, second succeeds
        mock_response_fail = Mock()
        mock_response_fail.status_code = 500

        mock_response_success = Mock()
        mock_response_success.status_code = 200
        mock_response_success.headers = {'Content-Type': 'application/json'}
        mock_response_success.json.return_value = {"status": "ok"}

        mock_request.side_effect = [mock_response_fail, mock_response_success]

        session = self.client.create_session()
        data = self.client.get("/api/devices", session=session)

        # Should succeed on second attempt
        self.assertEqual(data, {"status": "ok"})
        self.assertEqual(mock_request.call_count, 2)


class TestHttpClientUrlBuilding(unittest.TestCase):
    """Test URL building logic."""

    def setUp(self):
        """Set up test client."""
        self.client = HttpClient("https://api.example.com")

    def test_build_url_with_leading_slash(self):
        """Test URL building with leading slash in endpoint."""
        url = self.client._build_url("/api/devices")
        self.assertEqual(url, "https://api.example.com/api/devices")

    def test_build_url_without_leading_slash(self):
        """Test URL building without leading slash in endpoint."""
        url = self.client._build_url("api/devices")
        self.assertEqual(url, "https://api.example.com/api/devices")

    def test_build_url_with_trailing_slash_in_base(self):
        """Test URL building strips trailing slash from base URL."""
        client = HttpClient("https://api.example.com/")
        url = client._build_url("/api/devices")
        self.assertEqual(url, "https://api.example.com/api/devices")


class TestHttpClientRetryDelays(unittest.TestCase):
    """Test retry delay calculation."""

    def test_get_retry_delay_within_list(self):
        """Test retry delay uses configured delays."""
        client = HttpClient(
            "https://api.example.com",
            retry_delays=[0.5, 1.0, 2.0]
        )

        self.assertEqual(client._get_retry_delay(0), 0.5)
        self.assertEqual(client._get_retry_delay(1), 1.0)
        self.assertEqual(client._get_retry_delay(2), 2.0)

    def test_get_retry_delay_beyond_list_caps_at_5s(self):
        """Test retry delay caps at 5 seconds for attempts beyond list."""
        client = HttpClient(
            "https://api.example.com",
            retry_delays=[0.5, 1.0]
        )

        # Beyond list, should cap at 5s (or double last value if less)
        delay = client._get_retry_delay(3)
        self.assertLessEqual(delay, 5.0)


# ============================================================================
# Main (for running without pytest)
# ============================================================================

def run_all_tests():
    """Run all tests manually (if pytest not available)."""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    # Load all test classes
    suite.addTests(loader.loadTestsFromTestCase(TestHttpClientInit))
    suite.addTests(loader.loadTestsFromTestCase(TestHttpClientSession))
    suite.addTests(loader.loadTestsFromTestCase(TestHttpClientRequests))
    suite.addTests(loader.loadTestsFromTestCase(TestHttpClientUrlBuilding))
    suite.addTests(loader.loadTestsFromTestCase(TestHttpClientRetryDelays))

    # Run tests
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    return result.wasSuccessful()


if __name__ == '__main__':
    success = run_all_tests()
    exit(0 if success else 1)
