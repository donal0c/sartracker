# -*- coding: utf-8 -*-
"""
Provider Registry

Central registry for data providers. Supports dynamic provider
discovery and instantiation without hardcoding imports.

Phase 1 - Provider Abstraction Hardening:
Extended ProviderMetadata to include provider capabilities (polling,
streaming, auth modes) for future UI/provider selection.

Qt5/Qt6 Compatible: Pure Python implementation.
"""

from typing import Dict, List, Callable, Optional, Any


class ProviderMetadata:
    """
    Metadata about a registered provider.

    Phase 1 Extension:
    Added supports_polling, supports_streaming, and auth_modes to expose
    provider capabilities. Future provider selection UI will use these
    fields to filter/display appropriate options.
    """

    def __init__(self, name: str, display_name: str,
                 description: str, requires_config: bool,
                 config_schema: Optional[Dict] = None,
                 supports_polling: bool = False,
                 supports_streaming: bool = False,
                 auth_modes: Optional[List[str]] = None):
        """
        Initialize provider metadata.

        Args:
            name: Internal provider name (e.g., 'csv', 'http_traccar')
            display_name: Human-readable name (e.g., 'CSV Files', 'Traccar Server (HTTP)')
            description: Provider description for UI tooltips
            requires_config: Whether provider requires configuration
            config_schema: Dict describing required configuration fields
            supports_polling: Whether provider supports polling (HTTP requests)
            supports_streaming: Whether provider supports streaming (WebSocket/SSE)
            auth_modes: List of supported auth modes (e.g., ['basic', 'token', 'oauth'])
                       Empty list for providers without authentication (e.g., CSV)
        """
        self.name = name
        self.display_name = display_name
        self.description = description
        self.requires_config = requires_config
        self.config_schema = config_schema or {}
        self.supports_polling = supports_polling
        self.supports_streaming = supports_streaming
        self.auth_modes = auth_modes or []


class ProviderRegistry:
    """
    Singleton registry for data providers.

    Providers register themselves at import time using decorators
    or explicit registration calls.

    This pattern allows adding new providers without modifying
    core plugin code - critical for life-safety extensibility.

    Phase 1 Extension:
    Added get_metadata() helper to retrieve provider capabilities
    for future UI/provider selection workflows.
    """

    _instance = None

    def __new__(cls):
        """Singleton pattern implementation."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._providers = {}
            cls._instance._metadata = {}
        return cls._instance

    def register(self, metadata: ProviderMetadata,
                 factory: Callable[[Dict], 'Provider']):
        """
        Register a provider.

        Args:
            metadata: Provider metadata (including Phase 1 capabilities)
            factory: Callable that takes config dict and returns Provider instance

        Raises:
            ValueError: If provider with same name already registered
        """
        if metadata.name in self._providers:
            raise ValueError(f"Provider '{metadata.name}' already registered")

        self._providers[metadata.name] = factory
        self._metadata[metadata.name] = metadata

    def get_provider(self, name: str, config: Optional[Dict] = None) -> 'Provider':
        """
        Get provider instance.

        Args:
            name: Provider name (e.g., 'csv', 'http_traccar')
            config: Provider-specific configuration dict

        Returns:
            Provider instance

        Raises:
            KeyError: If provider not registered
            ProviderDataError: If config invalid for provider (from factory)
        """
        if name not in self._providers:
            available = ', '.join(self._providers.keys())
            raise KeyError(
                f"Provider '{name}' not registered. "
                f"Available providers: {available}"
            )

        factory = self._providers[name]
        return factory(config or {})

    def get_metadata(self, name: str) -> ProviderMetadata:
        """
        Get metadata for registered provider.

        Phase 1 Addition:
        Provides access to provider capabilities (polling, streaming, auth modes)
        for UI/provider selection. Future provider selection UI will use this
        to filter and display appropriate provider options.

        Args:
            name: Provider name (e.g., 'csv', 'http_traccar')

        Returns:
            ProviderMetadata instance with capabilities

        Raises:
            KeyError: If provider not registered

        Example:
            >>> metadata = registry.get_metadata('http_traccar')
            >>> if metadata.supports_polling:
            ...     print(f"Auth modes: {metadata.auth_modes}")
        """
        if name not in self._metadata:
            available = ', '.join(self._metadata.keys())
            raise KeyError(
                f"Provider '{name}' not registered. "
                f"Available providers: {available}"
            )

        return self._metadata[name]

    def list_providers(self) -> List[ProviderMetadata]:
        """
        Get list of all registered providers.

        Returns:
            List of ProviderMetadata objects (including Phase 1 capabilities)
        """
        return list(self._metadata.values())

    def is_registered(self, name: str) -> bool:
        """
        Check if provider is registered.

        Args:
            name: Provider name

        Returns:
            True if registered, False otherwise
        """
        return name in self._providers


# Global singleton instance
registry = ProviderRegistry()
