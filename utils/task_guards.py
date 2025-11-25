# -*- coding: utf-8 -*-
"""
Task Guard Utilities (Phase 6 Refactor).

Provides decorators and utilities for safe background task callback execution.
Ensures all async handlers verify component existence before touching UI.

LIFE-SAFETY CRITICAL: Callbacks may fire after plugin unload. Guards prevent
crashes that could disrupt rescue operations.

Usage:
    from utils.task_guards import safe_callback, require_components

    @safe_callback(log_prefix="[REFRESH]")
    def _on_refresh_complete(self, task):
        # Callback body is only executed if self is not None
        ...

    @require_components('sar_panel', 'layers_controller')
    def update_ui(self):
        # Only executed if both components exist and are not None
        ...
"""
import functools
import traceback
from typing import Callable, Optional, Tuple, Any


def log_exception(prefix: str, context: str, exc: Exception) -> None:
    """
    Log an exception with consistent formatting.

    Args:
        prefix: Log prefix (e.g., "[SARTRACKER]")
        context: Context description (e.g., "refresh callback")
        exc: The exception that occurred
    """
    print(f"{prefix} ERROR in {context}: {type(exc).__name__}: {exc}")
    try:
        traceback.print_exc()
    except Exception:
        pass


def safe_callback(
    log_prefix: str = "[CALLBACK]",
    return_on_error: Any = None,
    log_entry: bool = False
) -> Callable:
    """
    Decorator for safe async callback execution.

    Wraps callback methods to:
    - Catch and log all exceptions
    - Prevent crashes from propagating
    - Optionally log entry for debugging

    Args:
        log_prefix: Prefix for log messages
        return_on_error: Value to return if callback fails
        log_entry: If True, log when callback is entered

    Example:
        @safe_callback(log_prefix="[REFRESH]")
        def _on_refresh_complete(self, task):
            # Safe callback implementation
            pass
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            if log_entry:
                print(f"{log_prefix} Entering {func.__name__}")
            try:
                return func(*args, **kwargs)
            except Exception as exc:
                log_exception(log_prefix, func.__name__, exc)
                return return_on_error
        return wrapper
    return decorator


def require_components(*component_names: str, log_prefix: str = "[GUARD]") -> Callable:
    """
    Decorator to ensure required components exist before execution.

    Checks that all named attributes on self exist and are truthy.
    If any are missing, logs a warning and returns None without executing.

    Args:
        *component_names: Names of attributes to check on self
        log_prefix: Prefix for log messages

    Example:
        @require_components('sar_panel', 'layers_controller')
        def update_display(self):
            # Only runs if both self.sar_panel and self.layers_controller exist
            pass
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(self, *args, **kwargs):
            for name in component_names:
                component = getattr(self, name, None)
                if component is None:
                    print(f"{log_prefix} {func.__name__}: Required component '{name}' is None, skipping")
                    return None
            return func(self, *args, **kwargs)
        return wrapper
    return decorator


def guard_ui_update(
    iface_attr: str = 'iface',
    panel_attr: Optional[str] = None,
    log_prefix: str = "[UI_GUARD]"
) -> Callable:
    """
    Decorator to guard UI updates against component destruction.

    Checks that iface and optionally a panel exist before execution.
    Commonly used for task callbacks that need to update UI.

    Args:
        iface_attr: Name of iface attribute on self
        panel_attr: Optional name of panel attribute to check
        log_prefix: Prefix for log messages

    Example:
        @guard_ui_update(panel_attr='sar_panel')
        def _on_refresh_complete(self, task):
            self.sar_panel.update_status("Complete")
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(self, *args, **kwargs):
            # Check iface
            iface = getattr(self, iface_attr, None)
            if iface is None:
                print(f"{log_prefix} {func.__name__}: '{iface_attr}' is None (plugin unloaded?), skipping")
                return None

            # Check panel if specified
            if panel_attr:
                panel = getattr(self, panel_attr, None)
                if panel is None:
                    print(f"{log_prefix} {func.__name__}: '{panel_attr}' is None, skipping")
                    return None

            try:
                return func(self, *args, **kwargs)
            except Exception as exc:
                log_exception(log_prefix, func.__name__, exc)
                return None
        return wrapper
    return decorator


class CallbackGuard:
    """
    Context manager for guarding callback sections.

    Provides scoped protection for callback code with consistent
    logging and error handling.

    Example:
        def _on_task_complete(self, task):
            with CallbackGuard(self, 'sar_panel', 'layers_controller') as guard:
                if not guard.ready:
                    return
                # Safe to access components here
                self.sar_panel.update()
    """

    def __init__(
        self,
        instance: Any,
        *required_attrs: str,
        log_prefix: str = "[GUARD]",
        context: str = ""
    ):
        """
        Initialize callback guard.

        Args:
            instance: Object to check attributes on (usually self)
            *required_attrs: Names of attributes that must exist
            log_prefix: Prefix for log messages
            context: Optional context string for logging
        """
        self.instance = instance
        self.required_attrs = required_attrs
        self.log_prefix = log_prefix
        self.context = context
        self.ready = True
        self._missing: list = []

    def __enter__(self):
        for attr in self.required_attrs:
            if getattr(self.instance, attr, None) is None:
                self._missing.append(attr)

        if self._missing:
            self.ready = False
            ctx = f" ({self.context})" if self.context else ""
            print(f"{self.log_prefix}{ctx} Missing components: {', '.join(self._missing)}")

        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_val is not None:
            ctx = f" ({self.context})" if self.context else ""
            log_exception(self.log_prefix, f"callback{ctx}", exc_val)
            return True  # Suppress exception
        return False


def components_ready(instance: Any, *attr_names: str) -> bool:
    """
    Check if all named components exist on instance.

    Simple utility for inline component checks.

    Args:
        instance: Object to check (usually self)
        *attr_names: Names of attributes to check

    Returns:
        True if all attributes exist and are truthy
    """
    return all(getattr(instance, name, None) is not None for name in attr_names)


def notify_safe(
    message_bar,
    notify_func: Callable,
    title: str,
    message: str,
    duration: int = 5,
    log_prefix: str = "[NOTIFY]"
) -> bool:
    """
    Safely call a notification function.

    Guards against messageBar being None or deleted.

    Args:
        message_bar: QGIS message bar instance
        notify_func: Notification function (info, warning, error, success)
        title: Message title
        message: Message content
        duration: Display duration
        log_prefix: Prefix for log messages

    Returns:
        True if notification was shown, False otherwise
    """
    if message_bar is None:
        print(f"{log_prefix} Cannot show notification (message_bar is None): {title}: {message}")
        return False

    try:
        notify_func(message_bar, title, message, duration=duration)
        return True
    except Exception as exc:
        print(f"{log_prefix} Failed to show notification: {exc}")
        return False
