# -*- coding: utf-8 -*-
"""
SAR Tracker Diagnostics Panel

User-facing diagnostics dialog showing environment information,
compatibility status, and configuration details.
"""

import sys
import platform
import os

from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGroupBox, QLabel,
    QPushButton, QTextEdit, QApplication, QFormLayout
)
from qgis.PyQt.QtCore import Qt

from ..utils import capabilities
from ..utils.qt_compat import dialog_exec


class DiagnosticsPanel(QDialog):
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
        path_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        form.addRow("<b>Plugin Path:</b>", path_label)

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
        """Create configuration section."""
        group = QGroupBox("Current Configuration")
        form = QFormLayout()

        # Try to get mission status from SAR Panel (if accessible)
        try:
            from qgis.utils import iface
            # Try to find SAR Panel instance
            mission_status = "Unable to detect"
            data_source = "No data source loaded"

            # Look for SAR tracker plugin instance
            plugins = iface.mainWindow().findChildren(QDialog)
            for plugin_widget in plugins:
                if hasattr(plugin_widget, 'objectName') and 'sar' in plugin_widget.objectName().lower():
                    # Found potential SAR panel - try to get status
                    if hasattr(plugin_widget, 'mission_active'):
                        mission_status = "Active" if plugin_widget.mission_active else "Inactive"
                    break
        except:
            mission_status = "Unable to detect"
            data_source = "Unable to detect"

        form.addRow("<b>Mission Status:</b>", QLabel(mission_status))
        form.addRow("<b>Data Source:</b>", QLabel(data_source))

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
