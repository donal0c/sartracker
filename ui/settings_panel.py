# -*- coding: utf-8 -*-
"""
Settings Panel UI

Dedicated configuration workspace for SAR Tracker settings that persist across
missions. Separates long-lived configuration from mission operations.

Qt5/Qt6 Compatible: Uses qgis.PyQt and qt_compat for all Qt imports.

Phase N1 Implementation - Settings/Configuration Workspace
"""

from qgis.PyQt.QtWidgets import (
    QDockWidget, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QPushButton, QLabel, QGroupBox, QSpinBox, QCheckBox,
    QFileDialog, QLineEdit, QScrollArea, QComboBox, QStackedWidget,
    QMessageBox
)
from qgis.PyQt.QtCore import QTimer, pyqtSignal, QSettings
from qgis.PyQt.QtGui import QFont
from typing import Optional, List, Dict, Any

# Import Qt5/Qt6 compatible constants
from ..utils.qt_compat import (
    LeftDockWidgetArea, RightDockWidgetArea,
    Checked
)
from ..utils.notify import info, warning, error, success

# Import centralized config keys
from ..config.keys import SETTINGS_KEYS, ConfigStore


class SettingsPanel(QDockWidget):
    """
    Settings and configuration panel for SAR Tracker.

    Provides UI for configuring persistent settings that apply across missions:
    - Auto-refresh configuration
    - Auto-save configuration
    - Provider selection and credentials
    - Feature flags and advanced settings

    Signals:
        settings_changed: Emitted when any setting changes (dict of changes)
        provider_test_requested: Emitted when user tests provider connection
        provider_save_requested: Emitted when user saves provider configuration

    Qt5/Qt6 Compatible: Inherits from QDockWidget, uses qgis.PyQt imports.
    Life-Safety: All inputs validated before saving (Pattern: Input Validation).
    """

    # Signals
    settings_changed = pyqtSignal(dict)  # Changed settings
    provider_test_requested = pyqtSignal(str, dict)  # provider_name, config
    provider_save_requested = pyqtSignal(str, dict)  # provider_name, config

    def __init__(self, parent=None):
        """
        Initialize Settings Panel.

        Args:
            parent: Parent widget (should be iface.mainWindow())
        """
        super().__init__("SAR Tracker – Settings", parent)

        self.setAllowedAreas(LeftDockWidgetArea | RightDockWidgetArea)

        # Provider page indices (for maintainability)
        self.PROVIDER_PAGE_CSV = 0
        self.PROVIDER_PAGE_HTTP_TRACCAR = 1

        # Internal provider metadata/state
        self._provider_metadata: List[Dict[str, Any]] = []
        self._pending_provider_name: Optional[str] = None
        self._pending_provider_config: Optional[Dict[str, Any]] = None

        # Setup UI
        self._setup_ui()

        # Load current settings from QSettings
        self._load_settings()

        print("[SETTINGS_PANEL] Settings panel initialized")

    def _setup_ui(self):
        """Build the settings panel UI."""
        main_widget = QWidget()
        layout = QVBoxLayout()
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        # ========================================================================
        # HEADER SECTION
        # ========================================================================
        header_label = QLabel(
            "<h3>Settings & Configuration</h3>"
            "<p style='color: #666;'>Configure persistent settings that apply across all missions.</p>"
        )
        header_label.setWordWrap(True)
        layout.addWidget(header_label)

        # ========================================================================
        # MISSION DEFAULTS SECTION
        # ========================================================================
        defaults_group = QGroupBox("Mission Defaults")
        defaults_layout = QVBoxLayout()

        # Auto-Refresh Settings
        auto_refresh_header = QLabel("<b>Auto-Refresh</b>")
        defaults_layout.addWidget(auto_refresh_header)

        self.auto_refresh_checkbox = QCheckBox("Enable auto-refresh by default")
        self.auto_refresh_checkbox.setToolTip(
            "When enabled, new missions will automatically refresh tracking data at the specified interval."
        )
        self.auto_refresh_checkbox.stateChanged.connect(self._on_auto_refresh_changed)
        defaults_layout.addWidget(self.auto_refresh_checkbox)

        refresh_interval_layout = QHBoxLayout()
        refresh_interval_layout.addWidget(QLabel("Default interval (seconds):"))
        self.refresh_interval_spin = QSpinBox()
        self.refresh_interval_spin.setMinimum(SETTINGS_KEYS.AUTO_REFRESH_INTERVAL_MIN)
        self.refresh_interval_spin.setMaximum(SETTINGS_KEYS.AUTO_REFRESH_INTERVAL_MAX)
        self.refresh_interval_spin.setValue(SETTINGS_KEYS.AUTO_REFRESH_INTERVAL_DEFAULT)
        self.refresh_interval_spin.setToolTip(
            f"Refresh interval in seconds ({SETTINGS_KEYS.AUTO_REFRESH_INTERVAL_MIN}-{SETTINGS_KEYS.AUTO_REFRESH_INTERVAL_MAX})"
        )
        self.refresh_interval_spin.valueChanged.connect(self._on_refresh_interval_changed)
        refresh_interval_layout.addWidget(self.refresh_interval_spin)
        refresh_interval_layout.addStretch()
        defaults_layout.addLayout(refresh_interval_layout)

        defaults_layout.addSpacing(10)

        # Auto-Save Settings
        auto_save_header = QLabel("<b>Auto-Save</b>")
        defaults_layout.addWidget(auto_save_header)

        self.auto_save_checkbox = QCheckBox("Enable auto-save by default")
        self.auto_save_checkbox.setToolTip(
            "When enabled, QGIS project will automatically save at the specified interval."
        )
        self.auto_save_checkbox.stateChanged.connect(self._on_auto_save_changed)
        defaults_layout.addWidget(self.auto_save_checkbox)

        save_interval_layout = QHBoxLayout()
        save_interval_layout.addWidget(QLabel("Default interval (minutes):"))
        self.autosave_interval_spin = QSpinBox()
        self.autosave_interval_spin.setMinimum(SETTINGS_KEYS.AUTO_SAVE_INTERVAL_MIN)
        self.autosave_interval_spin.setMaximum(SETTINGS_KEYS.AUTO_SAVE_INTERVAL_MAX)
        self.autosave_interval_spin.setValue(SETTINGS_KEYS.AUTO_SAVE_INTERVAL_DEFAULT)
        self.autosave_interval_spin.setToolTip(
            f"Auto-save interval in minutes ({SETTINGS_KEYS.AUTO_SAVE_INTERVAL_MIN}-{SETTINGS_KEYS.AUTO_SAVE_INTERVAL_MAX})"
        )
        self.autosave_interval_spin.valueChanged.connect(self._on_autosave_interval_changed)
        save_interval_layout.addWidget(self.autosave_interval_spin)
        save_interval_layout.addStretch()
        defaults_layout.addLayout(save_interval_layout)

        defaults_group.setLayout(defaults_layout)
        layout.addWidget(defaults_group)

        # ========================================================================
        # DATA SOURCES SECTION
        # ========================================================================
        datasources_group = QGroupBox("Data Sources")
        datasources_layout = QVBoxLayout()

        # Provider selection
        provider_select_layout = QHBoxLayout()
        provider_select_layout.addWidget(QLabel("Provider:"))
        self.provider_combo = QComboBox()
        self.provider_combo.setToolTip("Select data provider for tracking data")
        self.provider_combo.currentTextChanged.connect(self._on_provider_changed)
        provider_select_layout.addWidget(self.provider_combo)
        datasources_layout.addLayout(provider_select_layout)

        # Provider configuration stack (different UI for each provider)
        self.provider_config_stack = QStackedWidget()

        # CSV Provider Configuration Page
        csv_config_page = self._create_csv_config_page()
        self.provider_config_stack.addWidget(csv_config_page)

        # HTTP Traccar Provider Configuration Page
        http_config_page = self._create_http_config_page()
        self.provider_config_stack.addWidget(http_config_page)

        datasources_layout.addWidget(self.provider_config_stack)

        # Auto-connect checkbox
        self.auto_connect_checkbox = QCheckBox("Auto-connect to provider on startup")
        self.auto_connect_checkbox.setToolTip(
            "Automatically connect to the configured provider when QGIS starts."
        )
        self.auto_connect_checkbox.stateChanged.connect(self._on_auto_connect_changed)
        datasources_layout.addWidget(self.auto_connect_checkbox)

        # Provider action buttons
        provider_buttons_layout = QHBoxLayout()
        self.provider_test_button = QPushButton("Test Connection")
        self.provider_test_button.setToolTip("Test connection to selected provider")
        self.provider_test_button.clicked.connect(self._on_provider_test)
        provider_buttons_layout.addWidget(self.provider_test_button)

        self.provider_save_button = QPushButton("Save & Connect")
        self.provider_save_button.setToolTip("Save provider configuration and connect")
        self.provider_save_button.clicked.connect(self._on_provider_save)
        provider_buttons_layout.addWidget(self.provider_save_button)
        datasources_layout.addLayout(provider_buttons_layout)

        datasources_group.setLayout(datasources_layout)
        layout.addWidget(datasources_group)

        # ========================================================================
        # ADVANCED SETTINGS SECTION
        # ========================================================================
        advanced_group = QGroupBox("Advanced Settings")
        advanced_group.setCheckable(True)
        advanced_group.setChecked(False)  # Collapsed by default
        advanced_layout = QVBoxLayout()

        # Feature flags
        feature_flags_header = QLabel("<b>Feature Flags</b>")
        advanced_layout.addWidget(feature_flags_header)

        self.traccar_http_feature_checkbox = QCheckBox("Enable Traccar HTTP Provider (experimental)")
        self.traccar_http_feature_checkbox.setToolTip(
            "Enable the new Traccar HTTP provider with enhanced features.\n"
            "Requires plugin reload to take effect."
        )
        self.traccar_http_feature_checkbox.stateChanged.connect(self._on_traccar_feature_changed)
        advanced_layout.addWidget(self.traccar_http_feature_checkbox)

        advanced_layout.addStretch()
        advanced_group.setLayout(advanced_layout)
        layout.addWidget(advanced_group)

        # ========================================================================
        # ACTION BUTTONS
        # ========================================================================
        buttons_layout = QHBoxLayout()

        self.apply_button = QPushButton("Apply")
        self.apply_button.setToolTip("Apply settings changes")
        self.apply_button.clicked.connect(self._on_apply)
        self.apply_button.setEnabled(False)  # Disabled until changes made
        buttons_layout.addWidget(self.apply_button)

        self.reset_button = QPushButton("Reset to Defaults")
        self.reset_button.setToolTip("Reset all settings to default values")
        self.reset_button.clicked.connect(self._on_reset_to_defaults)
        buttons_layout.addWidget(self.reset_button)

        buttons_layout.addStretch()
        layout.addLayout(buttons_layout)

        # Spacer
        layout.addStretch()

        main_widget.setLayout(layout)

        # Wrap in scroll area for accessibility
        scroll_area = QScrollArea()
        scroll_area.setWidget(main_widget)
        scroll_area.setWidgetResizable(True)

        self.setWidget(scroll_area)

    def _create_csv_config_page(self) -> QWidget:
        """
        Create CSV provider configuration page.

        Returns:
            QWidget: CSV configuration widget
        """
        csv_config_page = QWidget()
        csv_config_layout = QVBoxLayout()

        csv_file_layout = QHBoxLayout()
        csv_file_layout.addWidget(QLabel("File/Folder:"))
        self.csv_path_input = QLineEdit()
        self.csv_path_input.setPlaceholderText("Select CSV file or folder...")
        self.csv_path_input.setReadOnly(True)
        csv_file_layout.addWidget(self.csv_path_input)

        self.csv_browse_button = QPushButton("Browse...")
        self.csv_browse_button.clicked.connect(self._on_csv_browse)
        csv_file_layout.addWidget(self.csv_browse_button)
        csv_config_layout.addLayout(csv_file_layout)

        csv_config_layout.addStretch()
        csv_config_page.setLayout(csv_config_layout)

        return csv_config_page

    def _create_http_config_page(self) -> QWidget:
        """
        Create HTTP Traccar provider configuration page.

        Returns:
            QWidget: HTTP configuration widget
        """
        http_config_page = QWidget()
        http_config_layout = QVBoxLayout()

        # Server URL
        http_config_layout.addWidget(QLabel("Server URL:"))
        self.http_url_input = QLineEdit()
        self.http_url_input.setPlaceholderText("http://kmrtsar.eu:8082")
        self.http_url_input.setToolTip("Traccar server base URL (e.g., http://server:8082)")
        http_config_layout.addWidget(self.http_url_input)

        # Authentication Type
        auth_type_layout = QHBoxLayout()
        auth_type_layout.addWidget(QLabel("Auth Type:"))
        self.http_auth_type_combo = QComboBox()
        self.http_auth_type_combo.addItem("Basic Authentication", "basic")
        self.http_auth_type_combo.addItem("Bearer Token", "bearer")
        self.http_auth_type_combo.setToolTip("Authentication method for Traccar API")
        self.http_auth_type_combo.currentIndexChanged.connect(self._on_auth_type_changed)
        auth_type_layout.addWidget(self.http_auth_type_combo)
        http_config_layout.addLayout(auth_type_layout)

        # Basic Auth Fields
        self.http_basic_auth_widget = QWidget()
        basic_auth_layout = QVBoxLayout()
        basic_auth_layout.setContentsMargins(0, 0, 0, 0)
        basic_auth_layout.addWidget(QLabel("Username:"))
        self.http_username_input = QLineEdit()
        self.http_username_input.setPlaceholderText("admin")
        self.http_username_input.setToolTip("Traccar API username")
        basic_auth_layout.addWidget(self.http_username_input)
        basic_auth_layout.addWidget(QLabel("Password:"))
        self.http_password_input = QLineEdit()
        self.http_password_input.setEchoMode(QLineEdit.Password)
        self.http_password_input.setPlaceholderText("••••••••")
        self.http_password_input.setToolTip("Traccar API password")
        basic_auth_layout.addWidget(self.http_password_input)
        self.http_basic_auth_widget.setLayout(basic_auth_layout)
        http_config_layout.addWidget(self.http_basic_auth_widget)

        # Bearer Token Field
        self.http_bearer_auth_widget = QWidget()
        bearer_auth_layout = QVBoxLayout()
        bearer_auth_layout.setContentsMargins(0, 0, 0, 0)
        bearer_auth_layout.addWidget(QLabel("Bearer Token:"))
        self.http_token_input = QLineEdit()
        self.http_token_input.setEchoMode(QLineEdit.Password)
        self.http_token_input.setPlaceholderText("Enter API token")
        self.http_token_input.setToolTip("Traccar API bearer token")
        bearer_auth_layout.addWidget(self.http_token_input)
        self.http_bearer_auth_widget.setLayout(bearer_auth_layout)
        self.http_bearer_auth_widget.setVisible(False)
        http_config_layout.addWidget(self.http_bearer_auth_widget)

        # Advanced HTTP Settings
        http_advanced_group = QGroupBox("Advanced Settings (Optional)")
        http_advanced_group.setCheckable(True)
        http_advanced_group.setChecked(False)
        http_advanced_layout = QGridLayout()

        # Timeout
        http_advanced_layout.addWidget(QLabel("Timeout (seconds):"), 0, 0)
        self.http_timeout_spin = QSpinBox()
        self.http_timeout_spin.setMinimum(5)
        self.http_timeout_spin.setMaximum(60)
        self.http_timeout_spin.setValue(SETTINGS_KEYS.PROVIDER_HTTP_TIMEOUT_DEFAULT)
        self.http_timeout_spin.setToolTip("HTTP request timeout in seconds")
        http_advanced_layout.addWidget(self.http_timeout_spin, 0, 1)

        # Cache TTL
        http_advanced_layout.addWidget(QLabel("Cache TTL (seconds):"), 1, 0)
        self.http_cache_ttl_spin = QSpinBox()
        self.http_cache_ttl_spin.setMinimum(0)
        self.http_cache_ttl_spin.setMaximum(3600)
        self.http_cache_ttl_spin.setValue(SETTINGS_KEYS.PROVIDER_TRACCAR_CACHE_TTL_DEFAULT)
        self.http_cache_ttl_spin.setToolTip("Device cache time-to-live (0 = no cache)")
        http_advanced_layout.addWidget(self.http_cache_ttl_spin, 1, 1)

        # Last-good cache
        self.http_enable_cache_check = QCheckBox("Enable offline cache")
        self.http_enable_cache_check.setChecked(SETTINGS_KEYS.PROVIDER_TRACCAR_CACHE_ENABLED_DEFAULT)
        self.http_enable_cache_check.setToolTip("Cache last good positions for offline resilience")
        http_advanced_layout.addWidget(self.http_enable_cache_check, 2, 0, 1, 2)

        http_advanced_group.setLayout(http_advanced_layout)
        http_config_layout.addWidget(http_advanced_group)

        http_config_layout.addStretch()
        http_config_page.setLayout(http_config_layout)

        return http_config_page

    def _load_settings(self):
        """
        Load current settings from QSettings and populate UI.

        Qt5/Qt6 Compatible: Uses ConfigStore helper which wraps QSettings.
        """
        try:
            # Load auto-refresh settings
            auto_refresh_enabled = ConfigStore.get_auto_refresh_enabled()
            self.auto_refresh_checkbox.setChecked(auto_refresh_enabled)

            auto_refresh_interval = ConfigStore.get_auto_refresh_interval()
            self.refresh_interval_spin.setValue(auto_refresh_interval)

            # Load auto-save settings
            auto_save_enabled = ConfigStore.get_auto_save_enabled()
            self.auto_save_checkbox.setChecked(auto_save_enabled)

            auto_save_interval = ConfigStore.get_auto_save_interval()
            self.autosave_interval_spin.setValue(auto_save_interval)

            # Load provider auto-connect setting
            auto_connect = ConfigStore.get_provider_auto_connect()
            self.auto_connect_checkbox.setChecked(auto_connect)

            # Load feature flags
            traccar_http_enabled = ConfigStore.get(
                SETTINGS_KEYS.PROVIDER_TRACCAR_FEATURE_FLAG,
                SETTINGS_KEYS.PROVIDER_TRACCAR_FEATURE_FLAG_DEFAULT,
                bool
            )
            self.traccar_http_feature_checkbox.setChecked(traccar_http_enabled)

            # Load last provider configuration
            self._load_provider_config()

            print("[SETTINGS_PANEL] Settings loaded from QSettings")

        except Exception as e:
            print(f"[SETTINGS_PANEL] Error loading settings: {e}")
            error(
                None,  # No message bar in docked widget
                "Settings Load Error",
                f"Failed to load settings: {e}"
            )

    def _load_provider_config(self):
        """
        Load provider configuration from QSettings and populate provider UI.

        Qt5/Qt6 Compatible: Uses ConfigStore helper.
        """
        try:
            # Load last provider
            provider_name = ConfigStore.get(SETTINGS_KEYS.PROVIDER_LAST, None)
            if not provider_name:
                print("[SETTINGS_PANEL] No saved provider config found")
                return

            config = self._build_provider_config_from_store(provider_name)
            if not config:
                print(f"[SETTINGS_PANEL] Saved config for {provider_name} incomplete; skipping restore")
                return

            self._pending_provider_name = provider_name
            self._pending_provider_config = config
            if self.provider_combo.count() > 0:
                applied = self._apply_provider_config_ui()
                if applied:
                    print(f"[SETTINGS_PANEL] Restored provider config: {provider_name}")
            else:
                print(f"[SETTINGS_PANEL] Queued provider config restore for {provider_name} (awaiting provider list)")

        except Exception as e:
            print(f"[SETTINGS_PANEL] Warning: Failed to load provider config: {e}")

    def _build_provider_config_from_store(self, provider_name: str) -> Optional[dict]:
        """Reconstruct provider config dict from persisted QSettings values."""
        if provider_name == 'csv':
            csv_path = ConfigStore.get(SETTINGS_KEYS.PROVIDER_CSV_PATH, "")
            if csv_path:
                return {'csv_path': csv_path}
            return None

        if provider_name == 'http_traccar':
            server_url = ConfigStore.get(SETTINGS_KEYS.PROVIDER_HTTP_SERVER_URL, "")
            username = ConfigStore.get(SETTINGS_KEYS.PROVIDER_HTTP_USERNAME, "")
            password = ConfigStore.get(SETTINGS_KEYS.PROVIDER_HTTP_PASSWORD, "")
            timeout = ConfigStore.get(
                SETTINGS_KEYS.PROVIDER_HTTP_TIMEOUT,
                SETTINGS_KEYS.PROVIDER_HTTP_TIMEOUT_DEFAULT,
                int
            )
            if server_url and username and password:
                return {
                    'server_url': server_url,
                    'username': username,
                    'password': password,
                    'timeout': timeout
                }
            return None

        if provider_name == 'traccar_http':
            base_url = ConfigStore.get(SETTINGS_KEYS.PROVIDER_TRACCAR_BASE_URL, "")
            auth_type = ConfigStore.get(SETTINGS_KEYS.PROVIDER_TRACCAR_AUTH_TYPE, "basic")
            timeout = ConfigStore.get(
                SETTINGS_KEYS.PROVIDER_TRACCAR_TIMEOUT,
                SETTINGS_KEYS.PROVIDER_TRACCAR_TIMEOUT_DEFAULT,
                int
            )
            cache_ttl = ConfigStore.get(
                SETTINGS_KEYS.PROVIDER_TRACCAR_CACHE_TTL,
                SETTINGS_KEYS.PROVIDER_TRACCAR_CACHE_TTL_DEFAULT,
                int
            )
            cache_enabled = ConfigStore.get(
                SETTINGS_KEYS.PROVIDER_TRACCAR_CACHE_ENABLED,
                SETTINGS_KEYS.PROVIDER_TRACCAR_CACHE_ENABLED_DEFAULT,
                bool
            )
            if not base_url:
                return None

            config = {
                'base_url': base_url,
                'auth_type': auth_type,
                'timeout_s': timeout,
                'cache_ttl': cache_ttl,
                'enable_last_good_cache': cache_enabled
            }

            if auth_type == 'basic':
                username = ConfigStore.get(SETTINGS_KEYS.PROVIDER_TRACCAR_USERNAME, "")
                password = ConfigStore.get(SETTINGS_KEYS.PROVIDER_TRACCAR_PASSWORD, "")
                if not username or not password:
                    return None
                config['username'] = username
                config['password'] = password
            else:
                token = ConfigStore.get(SETTINGS_KEYS.PROVIDER_TRACCAR_TOKEN, "")
                if not token:
                    return None
                config['token'] = token

            return config

        return None

    def _apply_provider_config_ui(self) -> bool:
        """Apply pending provider selection/config to the UI if possible."""
        if not self._pending_provider_name:
            return False

        index = self._find_provider_index(self._pending_provider_name)
        if index < 0:
            return False

        self.provider_combo.blockSignals(True)
        self.provider_combo.setCurrentIndex(index)
        self.provider_combo.blockSignals(False)

        self._populate_provider_fields(
            self._pending_provider_name,
            self._pending_provider_config or {}
        )
        return True

    def _populate_provider_fields(self, provider_name: str, config: Dict[str, Any]):
        """Populate provider-specific widgets from config dict."""
        if provider_name == 'csv':
            self.provider_config_stack.setCurrentIndex(self.PROVIDER_PAGE_CSV)
            self.csv_path_input.setText(config.get('csv_path', ''))
            return

        if provider_name in ['http_traccar', 'traccar_http']:
            self.provider_config_stack.setCurrentIndex(self.PROVIDER_PAGE_HTTP_TRACCAR)
            self.http_url_input.setText(config.get('server_url') or config.get('base_url', ''))

            if provider_name == 'http_traccar':
                # Legacy provider always uses basic auth
                self.http_auth_type_combo.setCurrentIndex(
                    self.http_auth_type_combo.findData('basic')
                )
                self._on_auth_type_changed(self.http_auth_type_combo.currentIndex())
                self.http_username_input.setText(config.get('username', ''))
                self.http_password_input.setText(config.get('password', ''))
                self.http_timeout_spin.setValue(config.get('timeout', SETTINGS_KEYS.PROVIDER_HTTP_TIMEOUT_DEFAULT))
            else:
                auth_type = config.get('auth_type', 'basic')
                auth_index = self.http_auth_type_combo.findData(auth_type)
                if auth_index >= 0:
                    self.http_auth_type_combo.setCurrentIndex(auth_index)
                self._on_auth_type_changed(self.http_auth_type_combo.currentIndex())

                if auth_type == 'basic':
                    self.http_username_input.setText(config.get('username', ''))
                    self.http_password_input.setText(config.get('password', ''))
                else:
                    self.http_token_input.setText(config.get('token', ''))

                self.http_timeout_spin.setValue(config.get('timeout_s', SETTINGS_KEYS.PROVIDER_TRACCAR_TIMEOUT_DEFAULT))
                self.http_cache_ttl_spin.setValue(config.get('cache_ttl', SETTINGS_KEYS.PROVIDER_TRACCAR_CACHE_TTL_DEFAULT))
                self.http_enable_cache_check.setChecked(
                    config.get('enable_last_good_cache', SETTINGS_KEYS.PROVIDER_TRACCAR_CACHE_ENABLED_DEFAULT)
                )

    def _find_provider_index(self, provider_name: str) -> int:
        """Return combo index for provider name, or -1 if not present."""
        for i in range(self.provider_combo.count()):
            if self.provider_combo.itemData(i) == provider_name:
                return i
        return -1

    # ========================================================================
    # SIGNAL HANDLERS - Settings Changes
    # ========================================================================

    def _on_auto_refresh_changed(self, state):
        """Handle auto-refresh checkbox change."""
        self.apply_button.setEnabled(True)

    def _on_refresh_interval_changed(self, value):
        """Handle refresh interval change."""
        self.apply_button.setEnabled(True)

    def _on_auto_save_changed(self, state):
        """Handle auto-save checkbox change."""
        self.apply_button.setEnabled(True)

    def _on_autosave_interval_changed(self, value):
        """Handle auto-save interval change."""
        self.apply_button.setEnabled(True)

    def _on_auto_connect_changed(self, state):
        """Handle auto-connect checkbox change."""
        self.apply_button.setEnabled(True)

    def _on_traccar_feature_changed(self, state):
        """Handle Traccar HTTP feature flag change."""
        self.apply_button.setEnabled(True)
        # Update dropdown immediately so users see the effect without restart
        self._refresh_provider_list()

    # ========================================================================
    # SIGNAL HANDLERS - Provider Configuration
    # ========================================================================

    def _on_provider_changed(self):
        """Handle provider dropdown selection change."""
        provider_name = self.provider_combo.currentData()
        if not provider_name:
            return

        print(f"[SETTINGS_PANEL] Provider changed to: {provider_name}")
        self._pending_provider_name = provider_name

        # Switch to appropriate config page
        if provider_name == 'csv':
            self.provider_config_stack.setCurrentIndex(self.PROVIDER_PAGE_CSV)
        elif provider_name in ['http_traccar', 'traccar_http']:
            self.provider_config_stack.setCurrentIndex(self.PROVIDER_PAGE_HTTP_TRACCAR)

        self.apply_button.setEnabled(True)

    def _on_csv_browse(self):
        """Handle CSV browse button click."""
        # Show dialog with option to select file or folder
        file_path = QFileDialog.getExistingDirectory(
            self,
            "Select Folder with CSV Files (or Cancel and select single file)",
            ""
        )

        # If user cancelled folder selection, try file selection
        if not file_path:
            file_path, _ = QFileDialog.getOpenFileName(
                self,
                "Select Traccar CSV Export",
                "",
                "CSV Files (*.csv);;All Files (*)"
            )

        if file_path:
            self.csv_path_input.setText(file_path)
            self.apply_button.setEnabled(True)

    def _on_auth_type_changed(self, index):
        """Handle authentication type change."""
        auth_type = self.http_auth_type_combo.itemData(index)

        # Show/hide appropriate auth widgets
        if auth_type == 'basic':
            self.http_basic_auth_widget.setVisible(True)
            self.http_bearer_auth_widget.setVisible(False)
        else:  # bearer
            self.http_basic_auth_widget.setVisible(False)
            self.http_bearer_auth_widget.setVisible(True)

        self.apply_button.setEnabled(True)

    def _on_provider_test(self):
        """
        Handle provider test connection button click.

        Validates provider configuration and emits test signal.
        Does NOT save configuration.
        """
        try:
            provider_name, config = self._get_provider_config()

            # Validate configuration
            validation_error = self._validate_provider_config(provider_name, config)
            if validation_error:
                QMessageBox.warning(
                    self,
                    "Invalid Configuration",
                    validation_error
                )
                return

            # Emit test signal (plugin will handle connection test)
            self.provider_test_requested.emit(provider_name, config)

        except Exception as e:
            print(f"[SETTINGS_PANEL] Error in provider test: {e}")
            QMessageBox.critical(
                self,
                "Test Error",
                f"Failed to test provider: {e}"
            )

    def _on_provider_save(self):
        """
        Handle provider save button click.

        Validates provider configuration, saves to QSettings, and emits save signal.
        """
        try:
            provider_name, config = self._get_provider_config()

            # Validate configuration
            validation_error = self._validate_provider_config(provider_name, config)
            if validation_error:
                QMessageBox.warning(
                    self,
                    "Invalid Configuration",
                    validation_error
                )
                return

            # Save provider configuration to QSettings
            self._save_provider_config(provider_name, config)

            # Emit save signal (plugin will handle connection)
            self.provider_save_requested.emit(provider_name, config)

        except Exception as e:
            print(f"[SETTINGS_PANEL] Error in provider save: {e}")
            QMessageBox.critical(
                self,
                "Save Error",
                f"Failed to save provider: {e}"
            )

    # ========================================================================
    # SIGNAL HANDLERS - Action Buttons
    # ========================================================================

    def _on_apply(self):
        """Handle Apply button click - save all settings."""
        try:
            # Save all non-provider settings
            ConfigStore.set(
                SETTINGS_KEYS.AUTO_REFRESH_ENABLED,
                self.auto_refresh_checkbox.isChecked()
            )
            ConfigStore.set(
                SETTINGS_KEYS.AUTO_REFRESH_INTERVAL,
                self.refresh_interval_spin.value()
            )
            ConfigStore.set(
                SETTINGS_KEYS.AUTO_SAVE_ENABLED,
                self.auto_save_checkbox.isChecked()
            )
            ConfigStore.set(
                SETTINGS_KEYS.AUTO_SAVE_INTERVAL,
                self.autosave_interval_spin.value()
            )
            ConfigStore.set(
                SETTINGS_KEYS.PROVIDER_AUTO_CONNECT,
                self.auto_connect_checkbox.isChecked()
            )
            ConfigStore.set(
                SETTINGS_KEYS.PROVIDER_TRACCAR_FEATURE_FLAG,
                self.traccar_http_feature_checkbox.isChecked()
            )

            # Disable Apply button
            self.apply_button.setEnabled(False)

            # Emit settings changed signal
            self.settings_changed.emit({
                'auto_refresh_enabled': self.auto_refresh_checkbox.isChecked(),
                'auto_refresh_interval': self.refresh_interval_spin.value(),
                'auto_save_enabled': self.auto_save_checkbox.isChecked(),
                'auto_save_interval': self.autosave_interval_spin.value(),
                'provider_auto_connect': self.auto_connect_checkbox.isChecked()
            })

            # Show success message (import iface locally to avoid circular imports)
            from qgis.utils import iface
            success(
                iface.messageBar(),
                "Settings Saved",
                "Settings have been saved successfully.",
                duration=3
            )

            print("[SETTINGS_PANEL] Settings saved to QSettings")

        except Exception as e:
            print(f"[SETTINGS_PANEL] Error saving settings: {e}")
            from qgis.utils import iface
            error(
                iface.messageBar(),
                "Settings Save Error",
                f"Failed to save settings: {e}",
                duration=5
            )

    def _on_reset_to_defaults(self):
        """Handle Reset to Defaults button click."""
        # Confirm with user
        reply = QMessageBox.question(
            self,
            "Reset Settings",
            "Are you sure you want to reset all settings to default values?\n\n"
            "This will NOT affect provider credentials.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )

        if reply != QMessageBox.Yes:
            return

        try:
            # Reset to defaults (but preserve provider config)
            self.auto_refresh_checkbox.setChecked(SETTINGS_KEYS.AUTO_REFRESH_ENABLED_DEFAULT)
            self.refresh_interval_spin.setValue(SETTINGS_KEYS.AUTO_REFRESH_INTERVAL_DEFAULT)
            self.auto_save_checkbox.setChecked(SETTINGS_KEYS.AUTO_SAVE_ENABLED_DEFAULT)
            self.autosave_interval_spin.setValue(SETTINGS_KEYS.AUTO_SAVE_INTERVAL_DEFAULT)
            self.auto_connect_checkbox.setChecked(SETTINGS_KEYS.PROVIDER_AUTO_CONNECT_DEFAULT)
            self.traccar_http_feature_checkbox.setChecked(SETTINGS_KEYS.PROVIDER_TRACCAR_FEATURE_FLAG_DEFAULT)

            # Enable Apply button
            self.apply_button.setEnabled(True)

            print("[SETTINGS_PANEL] Settings reset to defaults")

        except Exception as e:
            print(f"[SETTINGS_PANEL] Error resetting settings: {e}")
            QMessageBox.critical(
                self,
                "Reset Error",
                f"Failed to reset settings: {e}"
            )

    # ========================================================================
    # HELPER METHODS
    # ========================================================================

    def _get_provider_config(self) -> tuple:
        """
        Get current provider configuration from UI.

        Returns:
            Tuple of (provider_name: str, config: dict)

        Raises:
            ValueError: If provider not selected or config incomplete
        """
        provider_name = self.provider_combo.currentData()
        if not provider_name:
            raise ValueError("No provider selected")

        config = {}

        if provider_name == 'csv':
            csv_path = self.csv_path_input.text().strip()
            if not csv_path:
                raise ValueError("CSV file path not specified")
            config['csv_path'] = csv_path

        elif provider_name == 'http_traccar':
            server_url = self.http_url_input.text().strip()
            username = self.http_username_input.text().strip()
            password = self.http_password_input.text().strip()
            timeout = self.http_timeout_spin.value()

            if not server_url or not username or not password:
                raise ValueError("HTTP provider requires URL, username, and password")

            config = {
                'server_url': server_url,
                'username': username,
                'password': password,
                'timeout': timeout
            }

        elif provider_name == 'traccar_http':
            base_url = self.http_url_input.text().strip()
            auth_type = self.http_auth_type_combo.currentData()
            timeout = self.http_timeout_spin.value()
            cache_ttl = self.http_cache_ttl_spin.value()
            cache_enabled = self.http_enable_cache_check.isChecked()

            if not base_url:
                raise ValueError("Base URL required")

            config = {
                'base_url': base_url,
                'auth_type': auth_type,
                'timeout_s': timeout,
                'cache_ttl': cache_ttl,
                'enable_last_good_cache': cache_enabled
            }

            if auth_type == 'basic':
                username = self.http_username_input.text().strip()
                password = self.http_password_input.text().strip()
                if not username or not password:
                    raise ValueError("Username and password required for basic auth")
                config['username'] = username
                config['password'] = password
            else:  # bearer
                token = self.http_token_input.text().strip()
                if not token:
                    raise ValueError("Bearer token required")
                config['token'] = token

        return provider_name, config

    def _validate_provider_config(self, provider_name: str, config: dict) -> Optional[str]:
        """
        Validate provider configuration.

        Args:
            provider_name: Provider identifier
            config: Provider configuration dict

        Returns:
            Error message if invalid, None if valid
        """
        try:
            if provider_name == 'csv':
                csv_path = config.get('csv_path', '')
                if not SETTINGS_KEYS.validate_file_path(csv_path):
                    return "Invalid CSV file path"

            elif provider_name in ['http_traccar', 'traccar_http']:
                url_key = 'server_url' if provider_name == 'http_traccar' else 'base_url'
                url = config.get(url_key, '')
                if not SETTINGS_KEYS.validate_url(url):
                    return "Invalid server URL (must start with http:// or https://)"

                timeout = config.get('timeout' if provider_name == 'http_traccar' else 'timeout_s', 0)
                if not isinstance(timeout, int) or timeout < 5 or timeout > 60:
                    return "Timeout must be between 5 and 60 seconds"

            return None  # Valid

        except Exception as e:
            return f"Validation error: {e}"

    def _save_provider_config(self, provider_name: str, config: dict):
        """
        Save provider configuration to QSettings.

        Args:
            provider_name: Provider identifier
            config: Provider configuration dict
        """
        try:
            # Save last provider
            ConfigStore.set(SETTINGS_KEYS.PROVIDER_LAST, provider_name)

            # Save provider-specific config
            if provider_name == 'csv':
                ConfigStore.set(SETTINGS_KEYS.PROVIDER_CSV_PATH, config.get('csv_path', ''))

            elif provider_name == 'http_traccar':
                ConfigStore.set(SETTINGS_KEYS.PROVIDER_HTTP_SERVER_URL, config.get('server_url', ''))
                ConfigStore.set(SETTINGS_KEYS.PROVIDER_HTTP_USERNAME, config.get('username', ''))
                ConfigStore.set(SETTINGS_KEYS.PROVIDER_HTTP_PASSWORD, config.get('password', ''))
                ConfigStore.set(SETTINGS_KEYS.PROVIDER_HTTP_TIMEOUT, config.get('timeout', 10))

            elif provider_name == 'traccar_http':
                ConfigStore.set(SETTINGS_KEYS.PROVIDER_TRACCAR_BASE_URL, config.get('base_url', ''))
                ConfigStore.set(SETTINGS_KEYS.PROVIDER_TRACCAR_AUTH_TYPE, config.get('auth_type', 'basic'))
                ConfigStore.set(SETTINGS_KEYS.PROVIDER_TRACCAR_TIMEOUT, config.get('timeout_s', 10))
                ConfigStore.set(SETTINGS_KEYS.PROVIDER_TRACCAR_CACHE_TTL, config.get('cache_ttl', 300))
                ConfigStore.set(SETTINGS_KEYS.PROVIDER_TRACCAR_CACHE_ENABLED, config.get('enable_last_good_cache', True))

                if config.get('auth_type') == 'basic':
                    ConfigStore.set(SETTINGS_KEYS.PROVIDER_TRACCAR_USERNAME, config.get('username', ''))
                    ConfigStore.set(SETTINGS_KEYS.PROVIDER_TRACCAR_PASSWORD, config.get('password', ''))
                else:
                    ConfigStore.set(SETTINGS_KEYS.PROVIDER_TRACCAR_TOKEN, config.get('token', ''))

            print(f"[SETTINGS_PANEL] Saved provider config: {provider_name}")

        except Exception as e:
            print(f"[SETTINGS_PANEL] Error saving provider config: {e}")
            raise
        else:
            # Keep local copy so dropdown refreshes retain selection
            self._pending_provider_name = provider_name
            self._pending_provider_config = dict(config)

    def populate_providers(self, providers_metadata: List[Dict]):
        """
        Populate provider dropdown from registry metadata.

        Args:
            providers_metadata: List of provider metadata dicts with keys:
                - name: str (internal provider name)
                - display_name: str (UI display name)
                - description: str (tooltip)

        Qt5/Qt6 Compatible: Uses QComboBox standard methods.
        """
        self._provider_metadata = providers_metadata or []
        self._refresh_provider_list()

    def _refresh_provider_list(self):
        """Rebuild provider combo from stored metadata + feature flags."""
        if not self._provider_metadata:
            return

        current_provider = self.provider_combo.currentData()
        enabled_providers = []

        self.provider_combo.blockSignals(True)
        self.provider_combo.clear()

        for metadata in self._provider_metadata:
            provider_name = metadata['name']

            if provider_name == 'traccar_http' and not self._is_provider_enabled('traccar_http'):
                continue

            enabled_providers.append(provider_name)

            self.provider_combo.addItem(metadata['display_name'], provider_name)
            self.provider_combo.setItemData(
                self.provider_combo.count() - 1,
                metadata.get('description', ''),
                2  # ToolTipRole
            )

        self.provider_combo.blockSignals(False)

        applied = self._apply_provider_config_ui()
        if not applied and current_provider in enabled_providers:
            idx = self._find_provider_index(current_provider)
            if idx >= 0:
                self.provider_combo.setCurrentIndex(idx)
        elif not applied and self.provider_combo.count() > 0:
            self.provider_combo.setCurrentIndex(0)

        print(f"[SETTINGS_PANEL] Provider list refreshed ({self.provider_combo.count()} entries)")

    def _is_provider_enabled(self, provider_name: str) -> bool:
        """
        Check if provider is enabled via feature flag.

        Checks both environment variable and QSettings.

        Args:
            provider_name: Provider identifier (e.g., 'traccar_http')

        Returns:
            True if provider is enabled, False otherwise
        """
        import os

        # Check environment variable first
        if provider_name == 'traccar_http':
            env_var = os.environ.get('SARTRACKER_ENABLE_TRACCAR_HTTP', '0')
            if env_var == '1':
                return True

            # Check QSettings
            return self.traccar_http_feature_checkbox.isChecked()

        return True  # Other providers enabled by default

    def closeEvent(self, event):
        """
        Handle widget close event.

        Cleanup before closing (no timers in this widget, but good practice).

        Args:
            event: Close event
        """
        print("[SETTINGS_PANEL] Settings panel closing")
        super().closeEvent(event)
