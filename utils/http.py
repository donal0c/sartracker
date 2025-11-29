# -*- coding: utf-8 -*-
"""
HTTP utilities for SAR Tracker providers.

Provides reusable HTTP client wrapper with authentication, retries, and
structured error handling. All functions follow mandatory validation and
error-handling patterns defined in AI_CODE_REFERENCE.md.

Qt5/Qt6 Compatible: Pure Python implementation with no Qt dependencies.
Thread-safe for background task usage when each task uses its own Session.

Classification: CRITICAL - LIFE SAFETY SYSTEM
"""

import time
import logging
from typing import Dict, Any, Optional, Tuple, List
import requests
from requests.auth import HTTPBasicAuth

from .exceptions import ProviderNetworkError, ProviderAuthError, ProviderDataError

# Configure logger
logger = logging.getLogger(__name__)


class HttpClient:
    """
    HTTP client wrapper with authentication, retries, and error handling.

    Features:
    - Base URL management with automatic endpoint joining
    - Authentication support (Basic, Bearer token)
    - Automatic retry with exponential backoff
    - Structured error mapping to ProviderError subclasses
    - Request/response logging (PII-safe)
    - JSON response validation

    Thread Safety:
    - Safe for background tasks when each task creates its own Session
    - Use create_session() to configure session with auth/headers
    - Do not share HttpClient instances across threads

    Examples:
        >>> # Basic auth
        >>> client = HttpClient(
        ...     base_url="https://api.example.com",
        ...     timeout_s=10
        ... )
        >>> session = client.create_session(auth_type="basic", username="user", password="pass")
        >>> data = client.get("/api/devices", session=session)

        >>> # Bearer token
        >>> session = client.create_session(auth_type="bearer", token="abc123")
        >>> data = client.get("/api/positions", session=session)
    """

    def __init__(
        self,
        base_url: str,
        timeout_s: int = 10,
        max_retries: int = 3,
        retry_delays: Optional[List[float]] = None,
        session: Optional[requests.Session] = None
    ):
        """
        Initialize HTTP client.

        Args:
            base_url: Base URL for all requests (e.g., "https://api.example.com")
            timeout_s: Request timeout in seconds (default: 10)
            max_retries: Maximum retry attempts for failed requests (default: 3)
            retry_delays: Custom retry delay sequence in seconds (default: [0.5, 1.0, 2.0])
                         Configurable for testing purposes
            session: Optional pre-configured requests.Session (default: None, creates new)

        Raises:
            ValueError: If base_url is empty or invalid
        """
        # Validate base_url (MANDATORY - AI_CODE_REFERENCE.md Input Validation)
        if not base_url or not isinstance(base_url, str) or not base_url.strip():
            raise ValueError("base_url cannot be empty")

        if not base_url.startswith(('http://', 'https://')):
            raise ValueError(f"base_url must start with http:// or https://: {base_url}")

        # Validate timeout
        if not isinstance(timeout_s, int) or timeout_s <= 0:
            raise ValueError(f"timeout_s must be positive integer: {timeout_s}")

        # Validate max_retries
        if not isinstance(max_retries, int) or max_retries < 0:
            raise ValueError(f"max_retries must be non-negative integer: {max_retries}")

        # Strip trailing slash from base URL for consistent joining
        self.base_url = base_url.rstrip('/')
        self.timeout_s = timeout_s
        self.max_retries = max_retries

        # Set retry delays (default: exponential backoff with 5s cap)
        if retry_delays is None:
            self.retry_delays = [0.5, 1.0, 2.0]
        else:
            if not isinstance(retry_delays, list) or not all(isinstance(d, (int, float)) for d in retry_delays):
                raise ValueError("retry_delays must be list of numbers")
            self.retry_delays = retry_delays

        self._session = session

        logger.debug(f"HttpClient initialized: base_url={self.base_url}, timeout={timeout_s}s")

    def create_session(
        self,
        auth_type: Optional[str] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
        token: Optional[str] = None,
        headers: Optional[Dict[str, str]] = None
    ) -> requests.Session:
        """
        Create and configure a requests.Session with authentication and headers.

        Use this helper to centralize session configuration. Each background task
        should create its own session for thread safety.

        Args:
            auth_type: Authentication type ("basic", "bearer", or None)
            username: Username for basic auth
            password: Password for basic auth
            token: Bearer token for token auth
            headers: Additional headers to set on session (default: {})

        Returns:
            Configured requests.Session instance

        Raises:
            ValueError: If auth_type is invalid or required credentials missing

        Examples:
            >>> # Basic auth
            >>> session = client.create_session(
            ...     auth_type="basic",
            ...     username="admin",
            ...     password="secret"
            ... )

            >>> # Bearer token
            >>> session = client.create_session(
            ...     auth_type="bearer",
            ...     token="abc123xyz"
            ... )

            >>> # No auth
            >>> session = client.create_session()
        """
        session = requests.Session()

        # Configure authentication
        if auth_type is not None:
            if auth_type not in ["basic", "bearer"]:
                raise ValueError(f"Invalid auth_type: {auth_type}. Must be 'basic' or 'bearer'")

            if auth_type == "basic":
                if not username or not password:
                    raise ValueError("username and password required for basic auth")

                session.auth = HTTPBasicAuth(username, password)
                logger.debug(f"Session configured with basic auth (username: {username[:3]}***)")

            elif auth_type == "bearer":
                if not token:
                    raise ValueError("token required for bearer auth")

                session.headers['Authorization'] = f"Bearer {token}"
                logger.debug("Session configured with bearer token (****)")

        # Add custom headers
        if headers:
            if not isinstance(headers, dict):
                raise ValueError("headers must be dict")
            session.headers.update(headers)
            logger.debug(f"Session configured with {len(headers)} custom headers")

        return session

    def _build_url(self, endpoint: str) -> str:
        """
        Build full URL from base URL and endpoint.

        Args:
            endpoint: API endpoint (e.g., "/api/devices" or "api/devices")

        Returns:
            Full URL
        """
        # Ensure endpoint starts with /
        if not endpoint.startswith('/'):
            endpoint = '/' + endpoint

        return f"{self.base_url}{endpoint}"

    def _make_request(
        self,
        method: str,
        endpoint: str,
        session: Optional[requests.Session] = None,
        params: Optional[Dict[str, Any]] = None,
        json_data: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        """
        Make HTTP request with retry logic.

        Args:
            method: HTTP method ("GET", "POST", etc.)
            endpoint: API endpoint
            session: requests.Session (uses self._session if None)
            params: Query parameters
            json_data: JSON body for POST/PUT requests

        Returns:
            requests.Response object

        Raises:
            ProviderNetworkError: For connection/timeout errors
            ProviderAuthError: For 401/403 responses
        """
        url = self._build_url(endpoint)
        session = session or self._session or requests.Session()

        # Log request (PII-safe: no credentials, no user data)
        logger.debug(f"HTTP {method} {url} (timeout={self.timeout_s}s)")

        last_exception = None

        for attempt in range(self.max_retries + 1):
            try:
                response = session.request(
                    method=method,
                    url=url,
                    params=params,
                    json=json_data,
                    timeout=self.timeout_s
                )

                # Check for auth errors BEFORE returning
                if response.status_code in [401, 403]:
                    error_msg = f"Authentication failed (HTTP {response.status_code})"
                    try:
                        error_detail = response.json().get('message', '')
                        if error_detail:
                            error_msg += f": {error_detail}"
                    except (ValueError, KeyError, AttributeError, TypeError):
                        # JSON decode error, missing key, or unexpected response structure
                        pass

                    logger.warning(f"{error_msg} - URL: {url}")
                    raise ProviderAuthError(
                        error_msg,
                        provider_name='http',
                        recoverable=True
                    )

                # Check for server errors that should be retried
                if response.status_code >= 500:
                    error_msg = f"Server error (HTTP {response.status_code})"
                    logger.warning(f"{error_msg} - attempt {attempt + 1}/{self.max_retries + 1}")

                    if attempt < self.max_retries:
                        delay = self._get_retry_delay(attempt)
                        logger.debug(f"Retrying in {delay}s...")
                        time.sleep(delay)
                        continue
                    else:
                        # Final attempt failed
                        raise ProviderNetworkError(
                            f"{error_msg} after {self.max_retries + 1} attempts",
                            provider_name='http',
                            recoverable=True
                        )

                # Success or client error (4xx other than 401/403)
                logger.debug(f"HTTP {method} {url} -> {response.status_code}")
                return response

            except requests.exceptions.Timeout as e:
                last_exception = e
                logger.warning(f"Request timeout (attempt {attempt + 1}/{self.max_retries + 1})")

                if attempt < self.max_retries:
                    delay = self._get_retry_delay(attempt)
                    logger.debug(f"Retrying in {delay}s...")
                    time.sleep(delay)
                else:
                    raise ProviderNetworkError(
                        f"Request timeout after {self.timeout_s}s (tried {self.max_retries + 1} times)",
                        provider_name='http',
                        recoverable=True
                    )

            except (requests.exceptions.ConnectionError, requests.exceptions.SSLError) as e:
                last_exception = e
                logger.warning(f"Connection error: {type(e).__name__} (attempt {attempt + 1}/{self.max_retries + 1})")

                if attempt < self.max_retries:
                    delay = self._get_retry_delay(attempt)
                    logger.debug(f"Retrying in {delay}s...")
                    time.sleep(delay)
                else:
                    error_msg = f"Connection failed: {str(e)}"
                    raise ProviderNetworkError(
                        error_msg,
                        provider_name='http',
                        recoverable=True
                    )

            except requests.exceptions.RequestException as e:
                # Other request errors (not retryable)
                logger.error(f"Request error: {type(e).__name__}: {str(e)}")
                raise ProviderNetworkError(
                    f"Request failed: {str(e)}",
                    provider_name='http',
                    recoverable=False
                )

        # Should not reach here, but defensive guard
        if last_exception:
            raise ProviderNetworkError(
                f"Request failed after retries: {str(last_exception)}",
                provider_name='http',
                recoverable=True
            )

        raise ProviderNetworkError(
            "Request failed for unknown reason",
            provider_name='http',
            recoverable=False
        )

    def _get_retry_delay(self, attempt: int) -> float:
        """
        Get retry delay for given attempt number.

        Args:
            attempt: Attempt number (0-indexed)

        Returns:
            Delay in seconds (capped at 5 seconds)
        """
        if attempt < len(self.retry_delays):
            return self.retry_delays[attempt]
        else:
            # Cap at 5 seconds for subsequent retries
            return min(5.0, self.retry_delays[-1] * 2)

    def get(
        self,
        endpoint: str,
        session: Optional[requests.Session] = None,
        params: Optional[Dict[str, Any]] = None,
        expect_json: bool = True
    ) -> Any:
        """
        Perform GET request.

        Args:
            endpoint: API endpoint (e.g., "/api/devices")
            session: Optional requests.Session (uses internal session if None)
            params: Query parameters
            expect_json: If True, parse and validate JSON response (default: True)

        Returns:
            Parsed JSON data (dict or list) if expect_json=True, else Response object

        Raises:
            ProviderNetworkError: For connection/timeout errors
            ProviderAuthError: For authentication failures (401/403)
            ProviderDataError: For invalid JSON or unexpected response format

        Examples:
            >>> devices = client.get("/api/devices", session=session)
            >>> positions = client.get("/api/positions", params={"deviceId": 123})
        """
        response = self._make_request("GET", endpoint, session=session, params=params)

        if not expect_json:
            return response

        return self._parse_json_response(response, endpoint)

    def post(
        self,
        endpoint: str,
        session: Optional[requests.Session] = None,
        json_data: Optional[Dict[str, Any]] = None,
        expect_json: bool = True
    ) -> Any:
        """
        Perform POST request.

        Args:
            endpoint: API endpoint
            session: Optional requests.Session
            json_data: JSON body data
            expect_json: If True, parse and validate JSON response (default: True)

        Returns:
            Parsed JSON data if expect_json=True, else Response object

        Raises:
            ProviderNetworkError: For connection/timeout errors
            ProviderAuthError: For authentication failures
            ProviderDataError: For invalid JSON response
        """
        response = self._make_request("POST", endpoint, session=session, json_data=json_data)

        if not expect_json:
            return response

        return self._parse_json_response(response, endpoint)

    def _parse_json_response(self, response: requests.Response, endpoint: str) -> Any:
        """
        Parse and validate JSON response.

        Args:
            response: requests.Response object
            endpoint: API endpoint (for error messages)

        Returns:
            Parsed JSON data (dict or list)

        Raises:
            ProviderDataError: If response is not valid JSON or unexpected format
        """
        try:
            # Check content type (informational only, not strict)
            content_type = response.headers.get('Content-Type', '')
            if 'application/json' not in content_type and content_type:
                logger.warning(f"Response content-type is not JSON: {content_type}")

            # Parse JSON
            data = response.json()

            # Validate response structure (basic check)
            if not isinstance(data, (dict, list)):
                raise ProviderDataError(
                    f"Invalid JSON response: expected dict or list, got {type(data).__name__}",
                    provider_name='http',
                    recoverable=False
                )

            logger.debug(f"Parsed JSON response: {type(data).__name__} with {len(data) if isinstance(data, list) else len(data.keys())} items")
            return data

        except ValueError as e:
            # JSON decode error
            logger.error(f"Invalid JSON in response from {endpoint}: {str(e)}")

            # Include first 200 chars of response for debugging (PII-safe)
            response_preview = response.text[:200]
            if len(response.text) > 200:
                response_preview += "..."

            raise ProviderDataError(
                f"Invalid JSON response from {endpoint}: {str(e)}. Response: {response_preview}",
                provider_name='http',
                recoverable=False
            )
