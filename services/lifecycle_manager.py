# -*- coding: utf-8 -*-
"""
Plugin Lifecycle Manager - Phase 1 Refactor

Centralizes plugin initialization/teardown coordination to make QGIS
enable/disable cycles predictable and testable.

This module provides:
- ComponentRegistry: Track registered components and their dependencies
- PluginLifecycleManager: Coordinate init/cleanup with proper error handling

Usage:
    lifecycle = PluginLifecycleManager(iface)
    lifecycle.register_component('task_manager', task_manager, cleanup_fn=task_manager.cancel_all)
    lifecycle.register_component('sar_panel', panel, cleanup_fn=panel.cleanup, deps=['task_manager'])
    # On shutdown:
    lifecycle.cleanup_all()

Qt5/Qt6 Compatible: Uses qgis.PyQt imports and utils.qt_compat patterns.
"""
from typing import Optional, Dict, List, Callable, Any, Set
from dataclasses import dataclass, field
from enum import Enum
import traceback


class ComponentState(Enum):
    """State of a registered component."""
    PENDING = "pending"
    INITIALIZED = "initialized"
    FAILED = "failed"
    CLEANED_UP = "cleaned_up"


@dataclass
class ComponentInfo:
    """Information about a registered component."""
    name: str
    instance: Any
    cleanup_fn: Optional[Callable[[], None]] = None
    dependencies: List[str] = field(default_factory=list)
    state: ComponentState = ComponentState.PENDING
    error: Optional[str] = None
    error_traceback: Optional[str] = None

    def mark_initialized(self):
        """Mark component as successfully initialized."""
        self.state = ComponentState.INITIALIZED
        self.error = None
        self.error_traceback = None

    def mark_failed(self, error: Exception):
        """Mark component as failed with error details."""
        self.state = ComponentState.FAILED
        self.error = str(error)
        try:
            self.error_traceback = traceback.format_exc()
        except Exception:
            self.error_traceback = None

    def mark_cleaned_up(self):
        """Mark component as cleaned up."""
        self.state = ComponentState.CLEANED_UP


class ComponentRegistry:
    """
    Registry for tracking plugin components and their dependencies.

    Provides ordered cleanup based on dependency graph and tracks
    initialization/cleanup failures for diagnostics.
    """

    def __init__(self):
        self._components: Dict[str, ComponentInfo] = {}
        self._init_order: List[str] = []

    def register(
        self,
        name: str,
        instance: Any,
        cleanup_fn: Optional[Callable[[], None]] = None,
        dependencies: Optional[List[str]] = None
    ) -> None:
        """
        Register a component with optional cleanup function and dependencies.

        Args:
            name: Unique identifier for the component
            instance: The component instance
            cleanup_fn: Optional function to call during cleanup
            dependencies: List of component names this component depends on
        """
        if name in self._components:
            # Allow re-registration (useful for hot reload scenarios)
            pass

        info = ComponentInfo(
            name=name,
            instance=instance,
            cleanup_fn=cleanup_fn,
            dependencies=dependencies or [],
            state=ComponentState.INITIALIZED
        )
        self._components[name] = info

        # Track initialization order
        if name not in self._init_order:
            self._init_order.append(name)

    def get(self, name: str) -> Optional[Any]:
        """Get component instance by name, or None if not registered."""
        info = self._components.get(name)
        return info.instance if info else None

    def get_info(self, name: str) -> Optional[ComponentInfo]:
        """Get full component info by name."""
        return self._components.get(name)

    def is_initialized(self, name: str) -> bool:
        """Check if component is registered and successfully initialized."""
        info = self._components.get(name)
        return info is not None and info.state == ComponentState.INITIALIZED

    def all_ready(self, *names: str) -> bool:
        """Check if all named components are initialized."""
        return all(self.is_initialized(name) for name in names)

    def cleanup_order(self) -> List[str]:
        """
        Return component names in reverse dependency order for cleanup.

        Components that depend on others are cleaned up first.
        """
        if not self._components:
            return []

        # Build dependency graph (dep -> dependents) for topo sort.
        graph: Dict[str, Set[str]] = {name: set() for name in self._components.keys()}
        for name, info in self._components.items():
            for dep in info.dependencies:
                if dep in graph:
                    graph[dep].add(name)

        order: List[str] = []
        temp: Set[str] = set()
        perm: Set[str] = set()
        cycle_detected = False

        def visit(node: str) -> None:
            nonlocal cycle_detected
            if node in perm:
                return
            if node in temp:
                cycle_detected = True
                return
            temp.add(node)
            for child in graph.get(node, ()):
                visit(child)
            temp.remove(node)
            perm.add(node)
            order.append(node)

        # Use init order for deterministic traversal
        for node in self._init_order:
            if node in graph:
                visit(node)
        for node in graph:
            if node not in perm:
                visit(node)

        if cycle_detected:
            # Fallback: best-effort reverse init order
            return list(reversed(self._init_order))

        # Topo order has deps before dependents; cleanup wants dependents first.
        return list(reversed(order))

    def cleanup_all(self, log_fn: Optional[Callable[[str], None]] = None) -> Dict[str, str]:
        """
        Clean up all components in reverse dependency order.

        Args:
            log_fn: Optional logging function for debug output

        Returns:
            Dict mapping component names to error messages (empty if all succeeded)
        """
        errors = {}

        for name in self.cleanup_order():
            info = self._components.get(name)
            if not info:
                continue

            if info.state == ComponentState.CLEANED_UP:
                continue

            if log_fn:
                log_fn(f"Cleaning up: {name}")

            if info.cleanup_fn:
                try:
                    info.cleanup_fn()
                    info.mark_cleaned_up()
                except Exception as e:
                    info.mark_failed(e)
                    errors[name] = str(e)
                    if log_fn:
                        log_fn(f"Error cleaning up {name}: {e}")
            else:
                info.mark_cleaned_up()

        return errors

    def get_status(self) -> Dict[str, Dict[str, Any]]:
        """
        Get status snapshot of all registered components.

        Returns:
            Dict mapping component names to status info
        """
        return {
            name: {
                'state': info.state.value,
                'has_cleanup': info.cleanup_fn is not None,
                'dependencies': info.dependencies,
                'error': info.error
            }
            for name, info in self._components.items()
        }

    def clear(self):
        """Clear all registered components."""
        self._components.clear()
        self._init_order.clear()


class PluginLifecycleManager:
    """
    Coordinates plugin initialization and teardown.

    Provides:
    - Structured component registration
    - Dependency-aware cleanup ordering
    - Error tracking and diagnostics
    - Signal connection management
    """

    def __init__(self, iface=None, log_prefix: str = "[SARTRACKER]"):
        """
        Initialize lifecycle manager.

        Args:
            iface: QGIS interface reference (can be None for testing)
            log_prefix: Prefix for log messages
        """
        self.iface = iface
        self.log_prefix = log_prefix
        self.registry = ComponentRegistry()
        self._signal_connections: List[tuple] = []
        self._import_errors: List[tuple] = []
        self._init_complete = False

    def log(self, message: str):
        """Log a message with prefix."""
        print(f"{self.log_prefix} {message}")

    def register_component(
        self,
        name: str,
        instance: Any,
        cleanup_fn: Optional[Callable[[], None]] = None,
        dependencies: Optional[List[str]] = None
    ) -> None:
        """
        Register a component for lifecycle management.

        Args:
            name: Unique component identifier
            instance: Component instance
            cleanup_fn: Optional cleanup function
            dependencies: Names of components this one depends on
        """
        self.registry.register(name, instance, cleanup_fn, dependencies)

    def get_component(self, name: str) -> Optional[Any]:
        """Get a registered component by name."""
        return self.registry.get(name)

    def components_ready(self, *names: str) -> bool:
        """Check if all named components are ready for use."""
        return self.registry.all_ready(*names)

    def track_signal(self, signal, slot):
        """
        Track a signal connection for cleanup.

        Args:
            signal: Qt signal
            slot: Connected slot function
        """
        self._signal_connections.append((signal, slot))

    def disconnect_all_signals(self):
        """Disconnect all tracked signals."""
        for signal, slot in self._signal_connections:
            try:
                signal.disconnect(slot)
            except (TypeError, RuntimeError):
                # Signal not connected or object deleted
                pass
        self._signal_connections.clear()

    def record_import_error(self, module_name: str, exception: Exception, tb: str = None):
        """
        Record an import error for later reporting.

        Args:
            module_name: Name of module that failed to import
            exception: The exception raised
            tb: Optional traceback string
        """
        if tb is None:
            try:
                tb = traceback.format_exc()
            except Exception:
                tb = ""
        self._import_errors.append((module_name, exception, tb))

    def has_import_errors(self) -> bool:
        """Check if any import errors were recorded."""
        return len(self._import_errors) > 0

    def get_import_errors(self) -> List[tuple]:
        """Get list of recorded import errors."""
        return self._import_errors.copy()

    def format_import_errors(self) -> str:
        """Format import errors for display to user."""
        if not self._import_errors:
            return ""

        lines = ["SAR Tracker failed to load due to the following import errors:\n"]

        for module_name, exc, tb in self._import_errors:
            lines.append(f"Module: {module_name}")
            lines.append(f"Error: {type(exc).__name__}: {exc}\n")

        lines.append("=" * 70)
        lines.append("SUGGESTED ACTIONS:")
        lines.append("=" * 70)
        lines.append("1. Verify all plugin files are present and not corrupted")
        lines.append("2. Run Diagnostics: Plugins > SAR Tracker > Diagnostics")
        lines.append("3. Try reinstalling the plugin")
        lines.append("4. Ensure you have compatible QGIS version (3.28+)\n")

        if self._import_errors:
            lines.append("=" * 70)
            lines.append("TECHNICAL DETAILS (first error):")
            lines.append("=" * 70)
            lines.append(self._import_errors[0][2])

        return "\n".join(lines)

    def mark_init_complete(self):
        """Mark initialization as complete."""
        self._init_complete = True

    def is_init_complete(self) -> bool:
        """Check if initialization completed successfully."""
        return self._init_complete and not self.has_import_errors()

    def cleanup(self) -> Dict[str, str]:
        """
        Perform full cleanup of all components.

        Order:
        1. Disconnect all tracked signals
        2. Clean up components in reverse dependency order

        Returns:
            Dict of component names to error messages (empty if all ok)
        """
        self.log("Beginning cleanup...")

        # First disconnect signals
        self.disconnect_all_signals()

        # Then clean up components
        errors = self.registry.cleanup_all(log_fn=self.log)

        self._init_complete = False

        if errors:
            self.log(f"Cleanup completed with {len(errors)} error(s)")
        else:
            self.log("Cleanup completed successfully")

        return errors

    def get_diagnostics(self) -> Dict[str, Any]:
        """
        Get diagnostic information about lifecycle state.

        Returns:
            Dict with diagnostic info
        """
        return {
            'init_complete': self._init_complete,
            'import_errors_count': len(self._import_errors),
            'tracked_signals_count': len(self._signal_connections),
            'components': self.registry.get_status()
        }


def validate_init_preconditions(iface) -> List[str]:
    """
    Validate preconditions for plugin initialization.

    Args:
        iface: QGIS interface

    Returns:
        List of validation warnings (empty if all ok)
    """
    warnings = []

    if iface is None:
        warnings.append("QGIS interface (iface) is None")

    # Check QGIS version
    try:
        from qgis.core import Qgis
        if Qgis.QGIS_VERSION_INT < 32800:
            warnings.append(
                f"QGIS version {Qgis.QGIS_VERSION} is older than 3.28. "
                "Some features may not work correctly."
            )
    except ImportError:
        warnings.append("Could not import qgis.core.Qgis for version check")

    return warnings


def setup_status_bar_coords(iface, wgs84_crs, itm_crs, update_callback) -> Dict[str, Any]:
    """
    Set up coordinate display in status bar.

    Args:
        iface: QGIS interface
        wgs84_crs: WGS84 coordinate reference system
        itm_crs: Irish Grid (ITM) coordinate reference system
        update_callback: Callback for coordinate updates

    Returns:
        Dict with 'label', 'timer', 'connected' keys, or None on failure

    Raises:
        RuntimeError: If setup fails
    """
    from qgis.PyQt.QtWidgets import QLabel
    from qgis.PyQt.QtGui import QFont
    from qgis.PyQt.QtCore import QTimer

    result = {
        'label': None,
        'timer': None,
        'connected': False
    }

    try:
        # Create label
        label = QLabel()
        label.setMinimumWidth(550)
        label.setMaximumWidth(550)

        # Use monospace font for stable width
        font = QFont("Courier New", 10)
        if not font.exactMatch():
            font = QFont("Monospace", 10)
        label.setFont(font)
        label.setStyleSheet("QLabel { padding: 2px 8px; background-color: #f0f0f0; }")

        iface.statusBarIface().addPermanentWidget(label)
        result['label'] = label

        # Create timer with parent for proper lifecycle
        timer = QTimer(iface.mainWindow())
        timer.timeout.connect(update_callback)
        timer.start(50)  # 20 updates/sec max
        result['timer'] = timer

        # Connect to map canvas
        iface.mapCanvas().xyCoordinates.connect(update_callback)
        result['connected'] = True

        return result

    except Exception as e:
        # Clean up partial setup
        if result['timer']:
            result['timer'].stop()
        if result['label']:
            try:
                iface.statusBarIface().removeWidget(result['label'])
            except Exception:
                pass
        raise RuntimeError(f"Status bar setup failed: {e}") from e


def cleanup_status_bar_coords(iface, label, timer, mouse_handler, connected: bool):
    """
    Clean up status bar coordinate display.

    Args:
        iface: QGIS interface
        label: QLabel widget
        timer: QTimer instance
        mouse_handler: Mouse move handler function
        connected: Whether xyCoordinates signal is connected
    """
    # Disconnect signal first
    if connected:
        try:
            iface.mapCanvas().xyCoordinates.disconnect(mouse_handler)
        except (TypeError, RuntimeError):
            pass

    # Stop timer
    if timer:
        try:
            timer.stop()
            timer.deleteLater()
        except Exception:
            pass

    # Remove label
    if label:
        try:
            iface.statusBarIface().removeWidget(label)
            label.deleteLater()
        except Exception:
            pass
