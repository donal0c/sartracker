# -*- coding: utf-8 -*-
"""
Provider Registry

Central registry for data providers. Supports dynamic provider
discovery and instantiation without hardcoding imports.

Qt5/Qt6 Compatible: Pure Python implementation.
"""

from typing import Dict, List, Callable, Optional, Any


class ProviderMetadata:
    """Metadata about a registered provider."""

    def __init__(self, name: str, display_name: str,
                 description: str, requires_config: bool,
                 config_schema: Optional[Dict] = None):
        """
        Initialize provider metadata.

        Args:
            name: Internal provider name (e.g., 'csv', 'http_traccar')
            display_name: Human-readable name (e.g., 'CSV Files', 'Traccar Server (HTTP)')
            description: Provider description for UI tooltips
            requires_config: Whether provider requires configuration
            config_schema: Dict describing required configuration fields
        """
        self.name = name
        self.display_name = display_name
        self.description = description
        self.requires_config = requires_config
        self.config_schema = config_schema or {}


class ProviderRegistry:
    """
    Singleton registry for data providers.

    Providers register themselves at import time using decorators
    or explicit registration calls.

    This pattern allows adding new providers without modifying
    core plugin code - critical for life-safety extensibility.
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
            metadata: Provider metadata
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
            ValueError: If config invalid for provider
        """
        if name not in self._providers:
            available = ', '.join(self._providers.keys())
            raise KeyError(
                f"Provider '{name}' not registered. "
                f"Available providers: {available}"
            )

        factory = self._providers[name]
        return factory(config or {})

    def list_providers(self) -> List[ProviderMetadata]:
        """
        Get list of all registered providers.

        Returns:
            List of ProviderMetadata objects
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
