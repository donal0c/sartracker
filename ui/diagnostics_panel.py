# -*- coding: utf-8 -*-
"""
SAR Tracker Diagnostics Panel

User-facing diagnostics dialog showing environment information,
compatibility status, and configuration details.

Accesses plugin state via proper API (get_plugin_status()) rather than
widget tree scanning. See Issue #4 for architectural decision.

Qt5/Qt6 Compatible: Uses qgis.PyQt and BaseDialog.
"""

import sys
import platform
import os

from qgis.PyQt.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QGroupBox, QLabel,
    QPushButton, QTextEdit, QApplication, QFormLayout
)

from ..utils import capabilities
from ..utils.qt_compat import dialog_exec, TextSelectableByMouse
from ..utils.dialog_utils import BaseDialog
from ..utils.dependency_guard import get_charset_guard_status
from ..utils.secure_store import SecureStore
from ..utils.install_doctor import run_diagnostics, format_report_text


class DiagnosticsPanel(BaseDialog):
    """
    Diagnostics panel showing environment and configuration information.
    """

    def __init__(self, parent=None):
        """
        Initialize diagnostics panel.

        Args:
            parent: Parent widget (typically main window)
        """
        super().__init__(parent)
        self.setWindowTitle("SAR Tracker Diagnostics")
        self.setMinimumWidth(700)
        self.setMinimumHeight(600)
        self.setup_ui()

    def setup_ui(self):
        """Set up the user interface."""
        layout = QVBoxLayout()

        # Environment Section
        env_group = self._create_environment_section()
        layout.addWidget(env_group)

        # Plugin Section
        plugin_group = self._create_plugin_section()
        layout.addWidget(plugin_group)

        # Security & Guards Section (Phase 3)
        security_group = self._create_security_section()
        layout.addWidget(security_group)

        # Compatibility Paths Section
        compat_group = self._create_compatibility_section()
        layout.addWidget(compat_group)

        # Configuration Section
        config_group = self._create_configuration_section()
        layout.addWidget(config_group)

        # Full Details (collapsible text area)
        details_label = QLabel("<b>Full Details (for bug reports):</b>")
        layout.addWidget(details_label)

        self.details_text = QTextEdit()
        self.details_text.setReadOnly(True)
        self.details_text.setMaximumHeight(150)
        self.details_text.setPlainText(self._generate_full_report())
        layout.addWidget(self.details_text)

        # Buttons
        button_layout = QHBoxLayout()
        button_layout.addStretch()

        copy_button = QPushButton("Copy to Clipboard")
        copy_button.clicked.connect(self._copy_to_clipboard)
        button_layout.addWidget(copy_button)

        close_button = QPushButton("Close")
        close_button.clicked.connect(self.accept)
        close_button.setDefault(True)
        button_layout.addWidget(close_button)

        layout.addLayout(button_layout)

        self.setLayout(layout)

    def _create_environment_section(self):
        """Create environment information section."""
        group = QGroupBox("Environment")
        form = QFormLayout()

        # QGIS Version
        form.addRow("<b>QGIS Version:</b>", QLabel(capabilities.QGIS_VERSION_STR))

        # Qt Version
        form.addRow("<b>Qt Version:</b>", QLabel(capabilities.QT_VERSION_STR))

        # Python Version
        python_version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
        form.addRow("<b>Python Version:</b>", QLabel(python_version))

        # Operating System
        os_info = f"{platform.system()} {platform.release()}"
        form.addRow("<b>Operating System:</b>", QLabel(os_info))

        group.setLayout(form)
        return group

    def _create_plugin_section(self):
        """Create plugin information section."""
        group = QGroupBox("Plugin")
        form = QFormLayout()

        # Plugin Version (read from metadata.txt)
        plugin_version = self._get_plugin_version()
        form.addRow("<b>Plugin Version:</b>", QLabel(plugin_version))

        # Plugin Path
        plugin_path = os.path.dirname(os.path.dirname(__file__))
        path_label = QLabel(plugin_path)
        path_label.setWordWrap(True)
        path_label.setTextInteractionFlags(TextSelectableByMouse)
        form.addRow("<b>Plugin Path:</b>", path_label)

        group.setLayout(form)
        return group

    def _create_security_section(self):
        """Create security and guard status section (Phase 3)."""
        group = QGroupBox("Security & Hardening")
        form = QFormLayout()

        # Secure Store Status
        backend = SecureStore.get_backend_name()
        if SecureStore.is_secure():
            # System keychain active
            secure_icon = "✅"
            backend_style = "color: green;"
        else:
            # File fallback
            secure_icon = "⚠️"
            backend_style = "color: orange;"
        
        backend_label = QLabel(f"{secure_icon} {backend}")
        backend_label.setStyleSheet(backend_style)
        form.addRow("<b>Credential Storage:</b>", backend_label)

        # Vendor Bundle Status (uses plugin status if available)
        vendor_text = "❓ Unknown"
        vendor_style = "color: gray;"
        cert_text = None
        try:
            from qgis.utils import plugins
            status = {}
            if 'sartracker' in plugins:
                sar_plugin = plugins['sartracker']
                if hasattr(sar_plugin, 'get_plugin_status'):
                    status = sar_plugin.get_plugin_status()
            vendor_info = status.get('vendor', {}) if status else {}
            using_vendor = bool(vendor_info.get('using_vendor'))
            missing = vendor_info.get('missing') or []
            error_msg = vendor_info.get('error')
            requests_path = vendor_info.get('requests_path')
            cert_path = vendor_info.get('certifi_path')

            if error_msg:
                vendor_text = f"❌ Vendor error: {error_msg}"
                vendor_style = "color: red;"
            elif missing:
                vendor_text = f"❌ Missing vendor assets ({len(missing)})"
                vendor_style = "color: red;"
            elif using_vendor:
                vendor_text = f"✅ Active (Bundled)"
                vendor_style = "color: green;"
            elif requests_path:
                vendor_text = f"ℹ️ System ({requests_path})"
                vendor_style = "color: black;"
            else:
                vendor_text = "❓ Unknown"
                vendor_style = "color: gray;"

            if cert_path:
                cert_text = cert_path
            elif vendor_info:
                cert_text = "Unknown certificate bundle path"

            # Fallback if no status available
            if not vendor_info:
                import requests
                # Do not rely on `import sartracker` here: users often install the
                # GitHub source ZIP which extracts to `sartracker-main/` or
                # `sartracker-master/`, and that folder name is not importable as
                # a Python package. Derive the plugin root from this file path.
                plugin_dir = os.path.dirname(os.path.dirname(__file__))
                vendor_dir = os.path.join(plugin_dir, 'vendor')
                try:
                    common = os.path.commonpath([requests.__file__, vendor_dir])
                except Exception:
                    common = ""
                if common == vendor_dir:
                    vendor_text = "✅ Active (Bundled)"
                    vendor_style = "color: green;"
                else:
                    vendor_text = f"ℹ️ System ({requests.__file__})"
                    vendor_style = "color: black;"
                    cert_text = getattr(requests, "__file__", None)

        except Exception:
            vendor_text = "❓ Unknown"
            vendor_style = "color: gray;"

        try:
            vendor_label = QLabel(vendor_text)
            vendor_label.setStyleSheet(vendor_style)
            vendor_label.setToolTip("Ensures plugin works without installing python libraries")
            form.addRow("<b>Dependency Bundle:</b>", vendor_label)
            if cert_text:
                cert_label = QLabel(cert_text)
                cert_label.setWordWrap(True)
                cert_label.setTextInteractionFlags(TextSelectableByMouse)
                form.addRow("<b>Cert Store:</b>", cert_label)
        except Exception:
            pass

        # Install Doctor - comprehensive installation health checks
        try:
            doctor_report = run_diagnostics()
            if doctor_report.is_healthy:
                doctor_text = "✅ All checks passed"
                doctor_style = "color: green;"
            elif doctor_report.has_errors:
                doctor_text = f"❌ {len([i for i in doctor_report.issues if i.severity == 'error'])} error(s) found"
                doctor_style = "color: red;"
            elif doctor_report.has_warnings:
                doctor_text = f"⚠️ {len([i for i in doctor_report.issues if i.severity == 'warning'])} warning(s)"
                doctor_style = "color: orange;"
            else:
                doctor_text = "ℹ️ Info available"
                doctor_style = "color: gray;"

            doctor_label = QLabel(doctor_text)
            doctor_label.setStyleSheet(doctor_style)
            doctor_label.setToolTip("Click 'Show Details' below for full report")
            form.addRow("<b>Install Doctor:</b>", doctor_label)

            # Show detailed issues if any problems found
            if not doctor_report.is_healthy:
                details_text = format_report_text(doctor_report)
                details_label = QLabel(details_text)
                details_label.setWordWrap(True)
                details_label.setTextInteractionFlags(TextSelectableByMouse)
                details_label.setStyleSheet("font-family: monospace; font-size: 11px;")
                form.addRow("", details_label)
        except Exception as e:
            doctor_label = QLabel(f"❓ Check failed: {e}")
            doctor_label.setStyleSheet("color: gray;")
            form.addRow("<b>Install Doctor:</b>", doctor_label)

        # Charset Guard Status (moved from Plugin section)
        guard_status = get_charset_guard_status()
        if guard_status["using_fallback"]:
            fallback_text = ", ".join(guard_status["fallbacks"]) or "fallback modules"
            guard_text = f"✅ Active (Bundled {fallback_text})"
            guard_style = "color: green;"
        elif guard_status["invoked"]:
            guard_text = "✅ Ready (System modules)"
            guard_style = "color: green;"
        else:
            guard_text = "⚪ Not invoked"
            guard_style = "color: gray;"
            
        guard_label = QLabel(guard_text)
        guard_label.setStyleSheet(guard_style)
        form.addRow("<b>Charset Guard:</b>", guard_label)

        group.setLayout(form)
        return group

    def _create_compatibility_section(self):
        """Create compatibility paths section."""
        group = QGroupBox("Compatibility Status")
        form = QFormLayout()

        # Dialog execution method
        dialog_method = f"{capabilities.DIALOG_EXEC_NAME}() {'(Qt6)' if capabilities.HAS_QT6 else '(Qt5)'}"
        form.addRow("<b>Dialog Execution:</b>", QLabel(dialog_method))

        # Message bar API
        message_api = "Qgis.MessageLevel enum" if capabilities.HAS_MESSAGE_ENUM else "Direct integer levels"
        form.addRow("<b>Message Bar API:</b>", QLabel(message_api))

        # QVariant usage
        qvariant_info = "QVariant.Type pattern (Qt5/Qt6 compatible)"
        form.addRow("<b>QgsField Creation:</b>", QLabel(qvariant_info))

        # Compatibility verdict
        if capabilities.QGIS_VERSION_INT >= 32800:  # 3.28.0
            verdict = "✓ Fully compatible (QGIS 3.28+)"
            verdict_color = "color: green; font-weight: bold;"
        else:
            verdict = "⚠ Old QGIS version (< 3.28) - features may not work correctly"
            verdict_color = "color: orange; font-weight: bold;"

        verdict_label = QLabel(verdict)
        verdict_label.setStyleSheet(verdict_color)
        form.addRow("<b>Verdict:</b>", verdict_label)

        group.setLayout(form)
        return group

    def _create_configuration_section(self):
        """
        Create configuration section.

        ARCHITECTURE NOTE: Uses plugin status API (get_plugin_status()) rather
        than scanning widget tree. This maintains proper layering and makes
        dependencies explicit. See Issue #4 for historical context.
        """
        group = QGroupBox("Current Configuration")
        form = QFormLayout()

        # Try to get mission status from plugin via proper API
        mission_status = "Unable to detect"
        data_source = "No data source loaded"

        try:
            from qgis.utils import plugins

            # Access plugin via QGIS plugin registry (proper way)
            if 'sartracker' in plugins:
                sar_plugin = plugins['sartracker']

                # Check if plugin has status API (defensive check)
                if hasattr(sar_plugin, 'get_plugin_status'):
                    status = sar_plugin.get_plugin_status()

                    # Format mission status
                    if status['mission_active']:
                        if status['mission_paused']:
                            mission_status = "Active (Paused)"
                        else:
                            mission_status = "Active"

                        # Add mission name if available
                        if status['mission_name']:
                            mission_status += f" - {status['mission_name']}"
                    else:
                        mission_status = "Inactive"

                    # Format data source
                    if status['data_source']:
                        device_count = status['devices_count']
                        data_source = f"{status['data_source']} ({device_count} devices)"

                        # ============================================================
                        # ISSUE #1 FIX: Show last refresh time to indicate data freshness
                        # This tells user the device count is cached, not real-time
                        # ============================================================
                        if status['last_refresh']:
                            # Parse ISO timestamp and format as human-readable
                            try:
                                from datetime import datetime
                                refresh_time = datetime.fromisoformat(status['last_refresh'])
                                time_str = refresh_time.strftime('%Y-%m-%d %H:%M:%S')
                                data_source += f"\n  Last refreshed: {time_str}"
                            except Exception:
                                # If parsing fails, just show count
                                pass
                        
                        # Phase 4.5: Cache Status (if available)
                        if status.get('provider_type') == 'traccar_http':
                            # Add cache indicator if last-good cache was used
                            provider_msg = status.get('provider_status_message', '')
                            if 'last-good cache' in str(provider_msg):
                                data_source += " [OFFLINE CACHE]"
                    else:
                        data_source = "No data source loaded"
                else:
                    # Plugin doesn't have status API (old version?)
                    mission_status = "Unable to detect (old plugin version)"
            else:
                # Plugin not loaded
                mission_status = "Plugin not loaded"

        except Exception as e:
            # Fail gracefully
            print(f"[DIAGNOSTICS] Error reading plugin status: {e}")
            mission_status = "Unable to detect"
            data_source = "Unable to detect"

        form.addRow("<b>Mission Status:</b>", QLabel(mission_status))
        form.addRow("<b>Data Source:</b>", QLabel(data_source))

        # Tool Registry Status (Issue #2 fix)
        tool_status = "Unable to detect"
        try:
            if 'sartracker' in plugins:
                sar_plugin = plugins['sartracker']
                if hasattr(sar_plugin, 'get_plugin_status'):
                    status = sar_plugin.get_plugin_status()

                    if status.get('tool_registry_loaded'):
                        if status.get('drawing_tools_available'):
                            tool_status = "✅ Loaded and operational"
                        else:
                            tool_status = "⚠ Loaded but no tools registered"
                    else:
                        tool_status = "❌ Failed to load"
        except Exception as e:
            print(f"[DIAGNOSTICS] Error reading tool registry status: {e}")
            tool_status = "Unable to detect"

        form.addRow("<b>Drawing Tools:</b>", QLabel(tool_status))

        # Device Color Status (Phase 5 addition)
        color_method = "MD5 hash (deterministic)"
        color_label = QLabel(f"{color_method}")
        color_label.setToolTip("Device colors use stable MD5 hashing for consistency across sessions")
        form.addRow("<b>Device Colors:</b>", color_label)

        # Active Tasks Status (Phase 0 addition)
        # See AI_CODE_REFERENCE.md – Pattern 6 (TaskManager)
        active_tasks_text = "Unable to detect"
        try:
            if 'sartracker' in plugins:
                sar_plugin = plugins['sartracker']
                if hasattr(sar_plugin, 'get_plugin_status'):
                    status = sar_plugin.get_plugin_status()
                    active_tasks_count = status.get('active_tasks_count', 0)
                    if active_tasks_count == 0:
                        active_tasks_text = "0 (Idle)"
                    elif active_tasks_count == 1:
                        active_tasks_text = "1 task running"
                    else:
                        active_tasks_text = f"{active_tasks_count} tasks running"
        except Exception as e:
            print(f"[DIAGNOSTICS] Error reading active tasks status: {e}")
            active_tasks_text = "Unable to detect"

        active_tasks_label = QLabel(active_tasks_text)
        active_tasks_label.setToolTip("Number of background tasks (refresh, connection test, etc.)")
        form.addRow("<b>Active Tasks:</b>", active_tasks_label)

        # FIX ISSUE #3: Provider Controller Status (Phase 3 addition)
        provider_ctrl_text = "Unable to detect"
        try:
            if 'sartracker' in plugins:
                sar_plugin = plugins['sartracker']
                if hasattr(sar_plugin, 'get_plugin_status'):
                    status = sar_plugin.get_plugin_status()

                    # Get provider controller state
                    ctrl_state = status.get('provider_controller_state', 'unknown')
                    poll_active = status.get('provider_poll_active', False)
                    poll_interval = status.get('provider_poll_interval', None)

                    # Format based on state
                    if ctrl_state == 'ok':
                        provider_ctrl_text = "✅ Connected"
                        if poll_active and poll_interval:
                            provider_ctrl_text += f" (Polling every {poll_interval}s)"
                        elif poll_active:
                            provider_ctrl_text += " (Polling)"
                    elif ctrl_state == 'error':
                        provider_ctrl_text = "❌ Error"
                    elif ctrl_state == 'testing':
                        provider_ctrl_text = "⏳ Testing connection..."
                    elif ctrl_state == 'connecting':
                        provider_ctrl_text = "⏳ Connecting..."
                    else:
                        provider_ctrl_text = "Not connected"
        except Exception as e:
            print(f"[DIAGNOSTICS] Error reading provider controller status: {e}")
            provider_ctrl_text = "Unable to detect"

        provider_label = QLabel(provider_ctrl_text)
        provider_label.setToolTip("Provider Controller manages data source connections and polling")
        form.addRow("<b>Provider Controller:</b>", provider_label)

        # Provider details (base URL, refresh info, last error)
        provider_details_lines = []
        try:
            from qgis.utils import plugins as detail_plugins
            if 'sartracker' in detail_plugins:
                detail_plugin = detail_plugins['sartracker']
                if hasattr(detail_plugin, 'get_plugin_status'):
                    detail_status = detail_plugin.get_plugin_status()
                    base_url = detail_status.get('provider_base_url')
                    if base_url:
                        provider_details_lines.append(f"Base URL: {base_url}")
                    last_refresh = detail_status.get('last_refresh')
                    if last_refresh:
                        provider_details_lines.append(f"Last Refresh: {last_refresh}")
                    device_count = detail_status.get('devices_count')
                    if device_count:
                        provider_details_lines.append(f"Devices: {device_count}")
                    refresh_duration_ms = detail_status.get('provider_refresh_duration_ms') or detail_status.get('last_refresh_duration_ms')
                    if refresh_duration_ms:
                        provider_details_lines.append(f"Last Refresh Duration: {refresh_duration_ms:.0f} ms")
                    poll_interval = detail_status.get('provider_poll_interval')
                    poll_active = detail_status.get('provider_poll_active')
                    if poll_interval:
                        provider_details_lines.append(f"Polling: every {poll_interval}s" + (" (active)" if poll_active else " (paused)"))
                    elif poll_active:
                        provider_details_lines.append("Polling: active")
                    last_error = detail_status.get('provider_last_error')
                    if last_error:
                        provider_details_lines.append(f"Last Error: {last_error}")
                    status_message = detail_status.get('provider_status_message')
                    if status_message:
                        provider_details_lines.append(f"Status: {status_message}")
                    cache_stats = detail_status.get('provider_cache_stats') or {}
                    if cache_stats:
                        ttl = cache_stats.get('cache_ttl_s')
                        if ttl is not None:
                            provider_details_lines.append(f"Device Cache TTL: {ttl}s")
                        dc_size = cache_stats.get('device_cache_size')
                        dc_age = cache_stats.get('device_cache_age_s')
                        if dc_size is not None:
                            provider_details_lines.append(f"Device Cache: {dc_size} entries" + (f" (age {dc_age:.0f}s)" if dc_age is not None else ""))
                        lg_age = cache_stats.get('last_good_cache_age_s')
                        lg_ts = cache_stats.get('last_good_cache_ts')
                        lg_pos = cache_stats.get('last_good_positions')
                        lg_bc = cache_stats.get('last_good_breadcrumbs')
                        if lg_pos is not None:
                            provider_details_lines.append(f"Last-Good Positions: {lg_pos}" + (f" (age {lg_age:.0f}s)" if lg_age is not None else ""))
                        if lg_bc:
                            provider_details_lines.append(f"Last-Good Breadcrumbs: {lg_bc}" + (f" (age {lg_age:.0f}s)" if lg_age is not None else ""))
        except Exception as detail_error:
            print(f"[DIAGNOSTICS] Error reading provider details: {detail_error}")

        provider_details_text = "\n".join(provider_details_lines) if provider_details_lines else "No provider details available"
        provider_details_label = QLabel(provider_details_text)
        provider_details_label.setWordWrap(True)
        form.addRow("<b>Provider Details:</b>", provider_details_label)

        group.setLayout(form)
        return group

    def _get_plugin_version(self):
        """
        Read plugin version from metadata.txt.

        Returns:
            str: Plugin version or "Unknown"
        """
        try:
            metadata_path = os.path.join(
                os.path.dirname(os.path.dirname(__file__)),
                'metadata.txt'
            )

            if os.path.exists(metadata_path):
                with open(metadata_path, 'r') as f:
                    for line in f:
                        if line.startswith('version='):
                            return line.split('=')[1].strip()
        except Exception as e:
            return f"Unknown (error: {e})"

        return "Unknown"

    def _generate_full_report(self):
        """
        Generate full diagnostics report text.

        Returns:
            str: Complete diagnostics report
        """
        lines = []
        lines.append("=" * 70)
        lines.append("SAR TRACKER DIAGNOSTICS REPORT")
        lines.append("=" * 70)
        lines.append("")

        # Environment
        lines.append("ENVIRONMENT:")
        lines.append(f"  QGIS Version:      {capabilities.QGIS_VERSION_STR}")
        lines.append(f"  QGIS Version Int:  {capabilities.QGIS_VERSION_INT}")
        lines.append(f"  Qt Version:        {capabilities.QT_VERSION_STR} (Qt{capabilities.QT_VERSION})")
        lines.append(f"  Python Version:    {sys.version}")
        lines.append(f"  OS:                {platform.system()} {platform.release()} ({platform.machine()})")
        lines.append(f"  Platform:          {platform.platform()}")
        lines.append("")

        # Plugin
        lines.append("PLUGIN:")
        lines.append(f"  Version:           {self._get_plugin_version()}")
        plugin_path = os.path.dirname(os.path.dirname(__file__))
        lines.append(f"  Path:              {plugin_path}")
        
        # Security
        lines.append("")
        lines.append("SECURITY & GUARDS:")
        lines.append(f"  Credential Store:  {SecureStore.get_backend_name()}")

        vendor_info = {}
        try:
            from qgis.utils import plugins
            if 'sartracker' in plugins:
                sar_plugin = plugins['sartracker']
                if hasattr(sar_plugin, 'get_plugin_status'):
                    vendor_info = sar_plugin.get_plugin_status().get('vendor', {}) or {}
        except Exception:
            vendor_info = {}

        try:
            if vendor_info:
                if vendor_info.get('error'):
                    lines.append(f"  Dependency Bundle: ERROR ({vendor_info.get('error')})")
                elif vendor_info.get('missing'):
                    lines.append(f"  Dependency Bundle: Missing assets ({len(vendor_info.get('missing'))})")
                    for missing in vendor_info.get('missing'):
                        lines.append(f"    - {missing}")
                elif vendor_info.get('using_vendor'):
                    lines.append(f"  Dependency Bundle: Active (Bundled)")
                else:
                    rp = vendor_info.get('requests_path', 'unknown')
                    lines.append(f"  Dependency Bundle: System ({rp})")
                if vendor_info.get('requests_path'):
                    lines.append(f"  Requests Path:     {vendor_info.get('requests_path')}")
                if vendor_info.get('certifi_path'):
                    lines.append(f"  Cert Store:        {vendor_info.get('certifi_path')}")
            else:
                import requests
                # Derive plugin root from this file path; avoids failures when the
                # plugin folder name is `sartracker-main/` or `sartracker-master/`.
                plugin_dir = os.path.dirname(os.path.dirname(__file__))
                vendor_dir = os.path.join(plugin_dir, 'vendor')
                try:
                    common = os.path.commonpath([requests.__file__, vendor_dir])
                except Exception:
                    common = ""
                if common == vendor_dir:
                    lines.append("  Dependency Bundle: Active (Bundled)")
                else:
                    lines.append(f"  Dependency Bundle: System ({requests.__file__})")
        except Exception as e:
            lines.append(f"  Dependency Bundle: Check Failed ({e})")

        guard_status = get_charset_guard_status()
        if guard_status["using_fallback"]:
            fallback_text = ", ".join(guard_status["fallbacks"]) or "fallback modules"
            guard_line = f"  Charset Guard:     Active (bundled {fallback_text})"
        elif guard_status["invoked"]:
            guard_line = "  Charset Guard:     Ready (system modules present)"
        else:
            guard_line = "  Charset Guard:     Not invoked"
        lines.append(guard_line)
        lines.append("")

        # Compatibility
        lines.append("COMPATIBILITY:")
        lines.append(f"  Has Qt6:           {capabilities.HAS_QT6}")
        lines.append(f"  Dialog Exec Name:  {capabilities.DIALOG_EXEC_NAME}()")
        lines.append(f"  Has Message Enum:  {capabilities.HAS_MESSAGE_ENUM}")
        lines.append(f"  Message Bar API:   {'Qgis.MessageLevel enum' if capabilities.HAS_MESSAGE_ENUM else 'Direct integer levels'}")
        lines.append("")

        # Python Path
        lines.append("PYTHON PATH:")
        for i, path in enumerate(sys.path[:10], 1):  # First 10 paths only
            lines.append(f"  [{i}] {path}")
        if len(sys.path) > 10:
            lines.append(f"  ... and {len(sys.path) - 10} more paths")
        lines.append("")

        lines.append("=" * 70)
        lines.append("END OF REPORT")
        lines.append("=" * 70)

        return "\n".join(lines)

    def _copy_to_clipboard(self):
        """Copy diagnostics report to clipboard."""
        clipboard = QApplication.clipboard()
        clipboard.setText(self.details_text.toPlainText())

        # Give user feedback
        from ..utils.notify import success
        from qgis.utils import iface
        success(
            iface.messageBar(),
            "Diagnostics",
            "Report copied to clipboard",
            duration=2
        )
