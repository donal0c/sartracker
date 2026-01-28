"""
Diagnostics Service for SAR Tracker Plugin.

Phase 4.3: Provides a centralized, loosely-coupled API for gathering
plugin diagnostics without tight binding to plugin internals.

This service:
- Gathers status from all registered controllers
- Provides read-only snapshots for diagnostic tools
- Supports graceful degradation when components are unavailable
- Maintains Qt5/Qt6 compatibility (pure Python data structures)

Usage:
    service = DiagnosticsService()
    service.set_mission_controller(mission_ctrl)
    service.set_provider_controller(provider_ctrl)
    ...
    status = service.get_status()

LIFE-SAFETY CRITICAL: This service must never block the UI thread or
perform network I/O. All data comes from cached controller snapshots.
"""

import os
from typing import Any, Callable, Dict, List, Optional


class DiagnosticsService:
    """
    Centralized diagnostics gathering service.

    Phase 4.3: Extracts diagnostics logic from sartracker.py into a
    testable, reusable service with explicit dependency injection.
    """

    def __init__(self):
        """Initialize the diagnostics service with no dependencies."""
        # Controller references (set via dependency injection)
        self._mission_controller = None
        self._provider_controller = None
        self._mission_lifecycle_controller = None
        self._task_manager = None
        self._tool_registry = None
        self._sar_panel = None
        self._layer_manager = None

        # Callbacks for plugin-level state
        self._get_unavailable_features: Optional[Callable[[], List[str]]] = None
        self._get_safe_mode_active: Optional[Callable[[], bool]] = None
        self._get_available_providers: Optional[Callable[[], List[str]]] = None
        self._get_vendor_info: Optional[Callable[[], Dict[str, Any]]] = None
        self._get_charset_guard_status: Optional[Callable[[], Dict[str, Any]]] = None

        # Legacy fallback callbacks (for when controllers unavailable)
        self._get_mission_gpkg_path: Optional[Callable[[], Optional[str]]] = None
        self._get_mission_backup_dir: Optional[Callable[[], Optional[str]]] = None
        self._get_mission_finalized: Optional[Callable[[], bool]] = None
        self._get_coordinators_cache: Optional[Callable[[], str]] = None

    def reset(self) -> None:
        """Clear all references to allow safe teardown."""
        self._mission_controller = None
        self._provider_controller = None
        self._mission_lifecycle_controller = None
        self._task_manager = None
        self._tool_registry = None
        self._sar_panel = None
        self._layer_manager = None

        self._get_unavailable_features = None
        self._get_safe_mode_active = None
        self._get_available_providers = None
        self._get_vendor_info = None
        self._get_charset_guard_status = None

        self._get_mission_gpkg_path = None
        self._get_mission_backup_dir = None
        self._get_mission_finalized = None
        self._get_coordinators_cache = None

    def _is_deleted(self, obj: Any) -> bool:
        """Best-effort check for deleted Qt objects without importing Qt."""
        if obj is None:
            return True
        try:
            try:
                from qgis.PyQt.sip import isdeleted as sip_isdeleted
            except Exception:
                try:
                    import sip
                    sip_isdeleted = sip.isdeleted
                except Exception:
                    sip_isdeleted = None
            if sip_isdeleted is not None:
                return bool(sip_isdeleted(obj))
        except Exception:
            return True
        try:
            _ = obj.__class__
        except RuntimeError:
            return True
        return False

    # ========================================================================
    # Dependency Injection Methods
    # ========================================================================

    def set_mission_controller(self, controller) -> None:
        """Set the MissionController for status gathering."""
        self._mission_controller = controller

    def set_provider_controller(self, controller) -> None:
        """Set the ProviderController for status gathering."""
        self._provider_controller = controller

    def set_mission_lifecycle_controller(self, controller) -> None:
        """Set the MissionLifecycleController for status gathering."""
        self._mission_lifecycle_controller = controller

    def set_task_manager(self, task_manager) -> None:
        """Set the TaskManager for active task count."""
        self._task_manager = task_manager

    def set_tool_registry(self, tool_registry) -> None:
        """Set the ToolRegistry for drawing tools status."""
        self._tool_registry = tool_registry

    def set_sar_panel(self, panel) -> None:
        """Set the SARPanel for legacy state fallback."""
        self._sar_panel = panel

    def set_layer_manager(self, manager) -> None:
        """Set the LayerManager for storage status."""
        self._layer_manager = manager

    def set_unavailable_features_getter(self, getter: Callable[[], List[str]]) -> None:
        """Set callback to get unavailable features list."""
        self._get_unavailable_features = getter

    def set_safe_mode_active_getter(self, getter: Callable[[], bool]) -> None:
        """Set callback to get safe mode active status."""
        self._get_safe_mode_active = getter

    def set_available_providers_getter(self, getter: Callable[[], List[str]]) -> None:
        """Set callback to get available provider names."""
        self._get_available_providers = getter

    def set_vendor_info_getter(self, getter: Callable[[], Dict[str, Any]]) -> None:
        """Set callback to get vendor information."""
        self._get_vendor_info = getter

    def set_charset_guard_status_getter(self, getter: Callable[[], Dict[str, Any]]) -> None:
        """Set callback to get charset guard status."""
        self._get_charset_guard_status = getter

    def set_legacy_storage_getters(
        self,
        gpkg_path: Callable[[], Optional[str]],
        backup_dir: Callable[[], Optional[str]],
        finalized: Callable[[], bool],
        coordinators: Callable[[], str]
    ) -> None:
        """Set legacy storage callbacks for controller fallback."""
        self._get_mission_gpkg_path = gpkg_path
        self._get_mission_backup_dir = backup_dir
        self._get_mission_finalized = finalized
        self._get_coordinators_cache = coordinators

    # ========================================================================
    # Status Gathering Methods
    # ========================================================================

    def get_status(self, debug_hook: Optional[Callable[[Dict], None]] = None) -> Dict[str, Any]:
        """
        Get comprehensive plugin status for diagnostics.

        Phase 4.3: Centralized status gathering with graceful degradation.

        Returns:
            dict: Plugin status with all available diagnostics data.
                  Missing components result in default values, not errors.
        """
        status = self._build_base_status()

        try:
            # Gather status from each component
            self._gather_mission_status(status)
            self._gather_provider_status(status)
            self._gather_tool_status(status)
            self._gather_task_status(status)
            self._gather_lifecycle_status(status)

        except Exception as e:
            # Defensive: Don't let diagnostics crash
            print(f"[SARTRACKER] Warning: Error gathering diagnostics: {e}")

        # Call debug hook if provided
        if debug_hook:
            try:
                debug_hook(status)
            except Exception as exc:
                print(f"[SARTRACKER] Warning: diagnostics debug_hook failed: {exc}")

        return status

    def _build_base_status(self) -> Dict[str, Any]:
        """Build base status dict with defaults and plugin-level state."""
        status = {
            # Mission state
            'mission_active': False,
            'mission_name': None,
            'mission_paused': False,
            'mission_elapsed_seconds': 0.0,
            'mission_active_seconds': 0.0,

            # Provider state
            'data_source': None,
            'provider_type': None,
            'devices_count': 0,
            'last_refresh': None,
            'last_refresh_duration_ms': None,

            # Task state
            'active_tasks_count': 0,

            # Tool state
            'tool_registry_loaded': False,
            'drawing_tools_available': False,

            # Plugin state
            'charset_guard': self._safe_call(self._get_charset_guard_status, {}),
            'vendor': self._safe_call(self._get_vendor_info, {}),
            'available_providers': self._safe_call(self._get_available_providers, []),
            'unavailable_features': self._safe_call(self._get_unavailable_features, []),
            'safe_mode_active': self._safe_call(self._get_safe_mode_active, False),
        }
        return status

    def _safe_call(self, func: Optional[Callable], default: Any) -> Any:
        """Safely call a callback, returning default on failure."""
        if func is None:
            return default
        try:
            return func()
        except Exception:
            return default

    def _gather_mission_status(self, status: Dict[str, Any]) -> None:
        """Gather mission status from controller or panel fallback."""
        if self._mission_controller and not self._is_deleted(self._mission_controller):
            try:
                snapshot = self._mission_controller.status_snapshot()
                state_value = snapshot.get('state')
                status['mission_active'] = state_value in ('active', 'paused')
                status['mission_paused'] = state_value == 'paused'
                status['mission_name'] = snapshot.get('mission_name')
                status['mission_elapsed_seconds'] = snapshot.get('elapsed_seconds', 0.0)
                status['mission_active_seconds'] = snapshot.get('active_seconds', 0.0)
            except Exception as e:
                print(f"[SARTRACKER] Warning: Error reading mission controller: {e}")

        elif self._sar_panel and not self._is_deleted(self._sar_panel):
            # Legacy fallback to panel state
            try:
                status['mission_active'] = getattr(self._sar_panel, 'mission_active', False)
                status['mission_paused'] = getattr(self._sar_panel, 'is_paused', False)
                if hasattr(self._sar_panel, 'mission_name_input'):
                    mission_name = self._sar_panel.mission_name_input.text().strip()
                    status['mission_name'] = mission_name if mission_name else None
            except Exception as e:
                print(f"[SARTRACKER] Warning: Error reading SAR panel state: {e}")

    def _gather_provider_status(self, status: Dict[str, Any]) -> None:
        """Gather provider status from ProviderController."""
        if not self._provider_controller or self._is_deleted(self._provider_controller):
            return

        try:
            provider = self._provider_controller.provider
            if not provider:
                return

            status['provider_type'] = self._provider_controller.provider_name

            # Build data source display string
            provider_name = self._provider_controller.provider_name
            provider_config = self._provider_controller.provider_config or {}
            status['data_source'] = self._format_data_source(provider_name, provider_config)

            # Get cached stats from controller snapshot
            controller_snapshot = self._provider_controller.status_snapshot()
            status['devices_count'] = controller_snapshot.get('devices_count', 0)
            status['last_refresh'] = controller_snapshot.get('last_refresh')
            status['last_refresh_duration_ms'] = controller_snapshot.get('last_refresh_duration_ms')

            # Additional controller state
            status['provider_controller_state'] = controller_snapshot.get('state', 'unknown')
            status['provider_poll_active'] = controller_snapshot.get('poll_active', False)
            status['provider_poll_interval'] = controller_snapshot.get('poll_interval')
            status['provider_base_url'] = controller_snapshot.get('provider_base_url')
            status['provider_last_error'] = controller_snapshot.get('last_error')
            status['provider_status_message'] = controller_snapshot.get('message')
            status['provider_refresh_duration_ms'] = controller_snapshot.get('last_refresh_duration_ms')

            # Provider-specific cache stats
            if hasattr(provider, 'get_cache_stats'):
                try:
                    status['provider_cache_stats'] = provider.get_cache_stats()
                except Exception as e:
                    print(f"[SARTRACKER] Warning: Error reading provider cache stats: {e}")

            # Replay/test window settings (Traccar HTTP)
            if provider_name == 'traccar_http':
                try:
                    from ..config.keys import ConfigStore
                    status['replay_window_enabled'] = ConfigStore.get_traccar_test_window_enabled()
                    status['replay_window_start'] = ConfigStore.get_traccar_test_window_start()
                    status['replay_window_hours'] = ConfigStore.get_traccar_test_window_hours()
                except Exception as e:
                    print(f"[SARTRACKER] Warning: Error reading replay settings: {e}")

        except Exception as e:
            print(f"[SARTRACKER] Warning: Error reading provider status: {e}")

    def _format_data_source(self, provider_name: str, config: Dict[str, Any]) -> str:
        """Format data source display string from provider config."""
        if provider_name == 'csv':
            csv_path = config.get('csv_path', '')
            if csv_path:
                return f"CSV: {os.path.basename(csv_path)}"
        elif provider_name == 'http_traccar':
            return "HTTP: Traccar Server"
        elif provider_name == 'traccar_http':
            base_url = config.get('base_url')
            return f"HTTP: {base_url}" if base_url else "HTTP: Traccar Server"
        return provider_name or "Unknown"

    def _gather_tool_status(self, status: Dict[str, Any]) -> None:
        """Gather tool registry status."""
        status['tool_registry_loaded'] = self._tool_registry is not None

        if self._tool_registry and not self._is_deleted(self._tool_registry):
            try:
                if hasattr(self._tool_registry, 'get_registered_tools'):
                    registered_tools = self._tool_registry.get_registered_tools()
                    status['drawing_tools_available'] = len(registered_tools) > 0
                else:
                    status['drawing_tools_available'] = True
            except Exception as e:
                print(f"[SARTRACKER] Warning: Error reading tool registry: {e}")

    def _gather_task_status(self, status: Dict[str, Any]) -> None:
        """Gather task manager status."""
        if self._task_manager and not self._is_deleted(self._task_manager):
            try:
                status['active_tasks_count'] = self._task_manager.get_active_count()
            except Exception as e:
                print(f"[SARTRACKER] Warning: Error reading task manager: {e}")

    def _gather_lifecycle_status(self, status: Dict[str, Any]) -> None:
        """Gather mission lifecycle controller status."""
        if self._mission_lifecycle_controller and not self._is_deleted(self._mission_lifecycle_controller):
            try:
                lifecycle_status = self._mission_lifecycle_controller.status_snapshot()
                status['mission_lifecycle'] = lifecycle_status

                # Populate top-level fields for backwards compatibility
                gpkg_path = lifecycle_status.get('gpkg_path')
                backup_dir = lifecycle_status.get('backup_dir')
                status['mission_storage_path'] = str(gpkg_path) if gpkg_path else None
                status['mission_backup_path'] = str(backup_dir) if backup_dir else None
                status['mission_finalized'] = lifecycle_status.get('is_finalized', False)
                status['mission_coordinators'] = lifecycle_status.get('coordinators', '')
            except Exception as e:
                print(f"[SARTRACKER] Warning: Error reading lifecycle controller: {e}")
        else:
            # Legacy fallback
            status['mission_storage_path'] = self._safe_call(self._get_mission_gpkg_path, None)
            status['mission_backup_path'] = self._safe_call(self._get_mission_backup_dir, None)
            status['mission_finalized'] = self._safe_call(self._get_mission_finalized, False)
            status['mission_coordinators'] = self._safe_call(self._get_coordinators_cache, '')

    # ========================================================================
    # Convenience Methods
    # ========================================================================

    def get_mission_status(self) -> Dict[str, Any]:
        """Get only mission-related status."""
        status = {}
        self._gather_mission_status(status)
        self._gather_lifecycle_status(status)
        return status

    def get_provider_status(self) -> Dict[str, Any]:
        """Get only provider-related status."""
        status = {}
        self._gather_provider_status(status)
        return status

    def get_task_status(self) -> Dict[str, Any]:
        """Get only task manager status."""
        status = {'active_tasks_count': 0}
        self._gather_task_status(status)
        return status

    def is_healthy(self) -> bool:
        """
        Quick health check for the plugin.

        Returns True if essential components are loaded and functional.
        """
        return (
            self._task_manager is not None
            and self._tool_registry is not None
        )
