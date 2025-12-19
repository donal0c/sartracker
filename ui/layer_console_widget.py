# -*- coding: utf-8 -*-
"""
Layer Console Widget (Phase 3 → Phase 4 bridge)

Hierarchical console for mission layers with visibility toggles,
context actions, and bulk operations. Presentation-only: emits signals
for SARPanel/LayersController to handle. This file is being aligned with
the Phase 4 specification while preserving backward compatibility.
"""

import logging
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, TYPE_CHECKING

logger = logging.getLogger(__name__)

from qgis.PyQt.QtCore import QObject, QSettings, pyqtSignal, QTimer
from qgis.PyQt.QtGui import QKeySequence
from qgis.PyQt.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QToolButton,
    QTreeWidget, QTreeWidgetItem, QPushButton, QMenu, QLineEdit, QCheckBox, QShortcut
)
from qgis.core import QgsTask

from ..config.keys import SETTINGS_KEYS
from ..utils.dialog_utils import BaseDialog
from ..utils.task_manager import TaskManager
from ..utils.qt_compat import (
    Checked, Unchecked,
    AlignCenter, CustomContextMenu, UserRole,
    ItemIsUserCheckable, ItemIsEnabled, ItemIsSelectable,
    dialog_exec, DialogAccepted,
    Key_Delete, Key_Backspace,
    Key_F5
)

if TYPE_CHECKING:
    from ..controllers.layer_catalog import LayerCatalogService


# Known layer identifiers used for type filtering and icon mapping
MARKER_LAYER_IDS = {
    "sar_markers_ipp_lkp",
    "sar_markers_clues",
    "sar_markers_hazards",
    "sar_markers_casualties",
}
SEARCH_AREA_LAYER_IDS = {"sar_search_areas", "sar_search_sectors"}
LINE_LAYER_IDS = {"sar_lines"}
RANGE_RING_LAYER_IDS = {"sar_range_rings"}
BEARING_LINE_LAYER_IDS = {"sar_bearing_lines"}
TEXT_LABEL_LAYER_IDS = {"sar_text_labels"}
POSITION_LAYER_IDS = {"sar_current_positions_active"}
TRACK_LAYER_IDS = {"sar_breadcrumbs"}


class LayerConsoleWidget(QWidget):
    """
    CalTopo-style layer console (presentation layer).

    Signals:
        visibility_toggled(str layer_id, bool visible)
        layer_alias_change_requested(str layer_id, str new_alias)
        layer_favorite_toggled(str layer_id, bool is_favorite)
        feature_selected(str layer_id, object feature_id)
        feature_rename_requested(str layer_id, object feature_id, str new_name)
        feature_delete_requested(str layer_id, object feature_id)
        feature_zoom_requested(str layer_id, object feature_id)
        bulk_delete_requested(str layer_id, list feature_ids)
        bulk_export_requested(str layer_id, list feature_ids)
        move_to_section_requested(int feature_id, str section_name)
        reorder_requested(str layer_id, list feature_ids_in_order)
        refresh_requested()

    Backward-compatible signals (Phase 3 naming) remain to avoid breaking
    existing handlers while Phase 4 wiring is completed.
    """

    # Phase 4 primary signals
    visibility_toggled = pyqtSignal(str, bool)
    layer_alias_change_requested = pyqtSignal(str, str)
    layer_favorite_toggled = pyqtSignal(str, bool)
    feature_selected = pyqtSignal(str, object)
    feature_rename_requested = pyqtSignal(str, object, str)
    feature_delete_requested = pyqtSignal(str, object)
    feature_zoom_requested = pyqtSignal(str, object)
    bulk_delete_requested = pyqtSignal(str, list)
    bulk_export_requested = pyqtSignal(str, list)
    move_to_section_requested = pyqtSignal(int, str)
    reorder_requested = pyqtSignal(str, list)
    refresh_requested = pyqtSignal()

    # Backward-compatible Phase 3 signals (deprecated)
    layer_selected = pyqtSignal(str, object)
    layer_visibility_toggled = pyqtSignal(str, bool)
    layer_rename_requested = pyqtSignal(str, object, str)
    layer_delete_requested = pyqtSignal(str, object)
    layer_zoom_requested = pyqtSignal(str, object)
    layer_export_requested = pyqtSignal(str, object)
    layer_duplicate_requested = pyqtSignal(str, object)
    bulk_assign_team_requested = pyqtSignal(str, list, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._catalog: Optional["LayerCatalogService"] = None
        self._catalog_fetcher: Optional[Callable[[], Dict[str, Any]]] = None
        self._catalog_data: Dict[str, Any] = {}
        self._expanded_groups: Set[str] = set()
        self._selected_layer_id: Optional[str] = None
        self._selected_feature_ids: List[object] = []
        self._selected_business_ids: List[object] = []
        self._pending_selection: Optional[Tuple[str, object]] = None
        self._catalog_connections: List[Tuple[Any, Callable]] = []
        self._ui_signal_connections: List[Tuple[Any, Callable]] = []  # Track UI signal handlers
        self._feature_limit: int = 300
        self._cleanup_in_progress: bool = False
        self._status_shown_items: int = 0
        self._status_total_items: int = 0
        self._search_active: bool = False
        self._empty_state_label: Optional[QLabel] = None
        self._suppress_item_changed: bool = False
        self._is_loading: bool = False  # Track loading state (Issue #2.1)
        self._catalog_task_id: Optional[str] = None

        # CRITICAL FIX: Issue #2.1 - TaskManager for background operations
        self._task_manager = TaskManager()

        # CRITICAL FIX: Issue #2.2 - Search debounce timer (prevents rebuild on every keystroke)
        self._search_debounce_timer: Optional["QTimer"] = None

        # CRITICAL FIX: Issue #2.3 - Catalog signal debounce timer (prevents redundant refreshes)
        self._catalog_refresh_timer: Optional["QTimer"] = None
        self._pending_full_refresh: bool = False

        self._setup_ui()
        self._load_settings()

    # ------------------------------------------------------------------ UI
    def _setup_ui(self):
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        filter_layout = QHBoxLayout()
        filter_layout.addWidget(QLabel("Filter:"))

        self.filter_combo = QComboBox()
        self.filter_combo.setToolTip("Filter layers by type (All Types shows everything)")
        self.filter_combo.addItem("All Types", None)
        self.filter_combo.addItem("Favorites ⭐", "favorites")
        self.filter_combo.addItem("Markers", "markers")
        self.filter_combo.addItem("Search Areas", "search_areas")
        self.filter_combo.addItem("Lines", "lines")
        self.filter_combo.addItem("Range Rings", "range_rings")
        self.filter_combo.addItem("Bearing Lines", "bearing_lines")
        self.filter_combo.addItem("Text Labels", "text_labels")
        self.filter_combo.addItem("Positions", "positions")
        self.filter_combo.addItem("Breadcrumbs", "breadcrumbs")
        self.filter_combo.currentIndexChanged.connect(self._apply_filter)
        self._ui_signal_connections.append((self.filter_combo.currentIndexChanged, self._apply_filter))
        filter_layout.addWidget(self.filter_combo)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search layers or features…")
        self.search_input.setToolTip("Search layers and features by name (Ctrl+F)")

        # CRITICAL FIX: Issue #2.2 - Setup debounce timer BEFORE connecting signal
        self._search_debounce_timer = QTimer(self)
        self._search_debounce_timer.setSingleShot(True)
        self._search_debounce_timer.setInterval(300)  # 300ms debounce
        self._search_debounce_timer.timeout.connect(self._execute_search)

        self.search_input.textChanged.connect(self._on_search_changed)
        self._ui_signal_connections.append((self.search_input.textChanged, self._on_search_changed))
        self.search_input.setClearButtonEnabled(True)
        filter_layout.addWidget(self.search_input)

        # CRITICAL FIX: Issue #2.3 - Setup catalog signal debounce timer
        self._catalog_refresh_timer = QTimer(self)
        self._catalog_refresh_timer.setSingleShot(True)
        self._catalog_refresh_timer.setInterval(100)  # 100ms debounce (shorter than search)
        self._catalog_refresh_timer.timeout.connect(self._execute_catalog_refresh)

        self.show_hidden_checkbox = QCheckBox("Show hidden")
        self.show_hidden_checkbox.setChecked(False)
        self.show_hidden_checkbox.setToolTip("Show layers currently hidden on map")
        self.show_hidden_checkbox.toggled.connect(self._apply_filter)
        self._ui_signal_connections.append((self.show_hidden_checkbox.toggled, self._apply_filter))
        filter_layout.addWidget(self.show_hidden_checkbox)

        self.refresh_button = QToolButton()
        self.refresh_button.setText("Refresh")
        self.refresh_button.setToolTip("Refresh catalog (F5)")
        self.refresh_button.clicked.connect(self._on_refresh_clicked)
        self._ui_signal_connections.append((self.refresh_button.clicked, self._on_refresh_clicked))
        filter_layout.addWidget(self.refresh_button)

        self.expand_button = QToolButton()
        self.expand_button.setText("Expand All")
        self.expand_button.setToolTip("Expand all groups to show all layers")
        self._expand_all_handler = lambda: self.tree.expandAll()
        self.expand_button.clicked.connect(self._expand_all_handler)
        self._ui_signal_connections.append((self.expand_button.clicked, self._expand_all_handler))
        filter_layout.addWidget(self.expand_button)

        self.collapse_button = QToolButton()
        self.collapse_button.setText("Collapse All")
        self.collapse_button.setToolTip("Collapse all groups to hide layers")
        self._collapse_all_handler = lambda: self.tree.collapseAll()
        self.collapse_button.clicked.connect(self._collapse_all_handler)
        self._ui_signal_connections.append((self.collapse_button.clicked, self._collapse_all_handler))
        filter_layout.addWidget(self.collapse_button)

        filter_layout.addStretch()
        layout.addLayout(filter_layout)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Layer / Feature", "Count", "Type", "Updated"])
        self.tree.setColumnWidth(0, 280)
        self.tree.setColumnWidth(1, 60)
        self.tree.setColumnWidth(2, 120)
        self.tree.setAlternatingRowColors(True)
        self.tree.setSelectionBehavior(self.tree.SelectItems)
        self.tree.setSelectionMode(self.tree.ExtendedSelection)
        self.tree.setContextMenuPolicy(CustomContextMenu)
        self.tree.itemSelectionChanged.connect(self._on_selection_changed)
        self._ui_signal_connections.append((self.tree.itemSelectionChanged, self._on_selection_changed))
        self.tree.itemChanged.connect(self._on_item_changed)
        self._ui_signal_connections.append((self.tree.itemChanged, self._on_item_changed))
        self.tree.itemDoubleClicked.connect(self._on_item_double_clicked)
        self._ui_signal_connections.append((self.tree.itemDoubleClicked, self._on_item_double_clicked))
        self.tree.customContextMenuRequested.connect(self._show_context_menu)
        self._ui_signal_connections.append((self.tree.customContextMenuRequested, self._show_context_menu))

        # PERFORMANCE FIX: Issue #3.3 - Track expansion state incrementally
        self.tree.itemExpanded.connect(self._on_item_expanded)
        self._ui_signal_connections.append((self.tree.itemExpanded, self._on_item_expanded))
        self.tree.itemCollapsed.connect(self._on_item_collapsed)
        self._ui_signal_connections.append((self.tree.itemCollapsed, self._on_item_collapsed))

        layout.addWidget(self.tree)

        bulk_layout = QHBoxLayout()
        self.bulk_label = QLabel("0 selected")
        bulk_layout.addWidget(self.bulk_label)

        self.bulk_delete_button = QPushButton("Delete Selected")
        self.bulk_delete_button.setToolTip("Delete selected features (Delete)")
        self.bulk_delete_button.clicked.connect(self._on_bulk_delete)
        self._ui_signal_connections.append((self.bulk_delete_button.clicked, self._on_bulk_delete))
        self.bulk_delete_button.setEnabled(False)
        bulk_layout.addWidget(self.bulk_delete_button)

        self.bulk_export_button = QPushButton("Export Selected")
        self.bulk_export_button.setToolTip("Export selected features")
        self.bulk_export_button.clicked.connect(self._on_bulk_export)
        self._ui_signal_connections.append((self.bulk_export_button.clicked, self._on_bulk_export))
        self.bulk_export_button.setEnabled(False)
        bulk_layout.addWidget(self.bulk_export_button)

        self.bulk_team_button = QPushButton("Assign Team")
        self.bulk_team_button.setToolTip("Assign team to selected features")
        self.bulk_team_button.clicked.connect(self._on_bulk_assign_team)
        self._ui_signal_connections.append((self.bulk_team_button.clicked, self._on_bulk_assign_team))
        self.bulk_team_button.setEnabled(False)
        bulk_layout.addWidget(self.bulk_team_button)

        bulk_layout.addStretch()
        layout.addLayout(bulk_layout)

        status_layout = QHBoxLayout()
        self.status_label = QLabel("Showing 0 of 0 items")
        status_layout.addWidget(self.status_label)
        status_layout.addStretch()
        layout.addLayout(status_layout)

        # Empty state label (shown when no data)
        self._empty_state_label = QLabel("No layers available")
        self._empty_state_label.setAlignment(AlignCenter)
        self._empty_state_label.setVisible(False)
        layout.addWidget(self._empty_state_label)

        self.setLayout(layout)

        # Keyboard shortcuts
        self._shortcut_refresh = QShortcut(QKeySequence(Key_F5), self)
        self._shortcut_refresh.activated.connect(self._on_refresh_clicked)
        self._ui_signal_connections.append((self._shortcut_refresh.activated, self._on_refresh_clicked))

        self._shortcut_delete = QShortcut(QKeySequence(Key_Delete), self)
        self._shortcut_delete.activated.connect(self._on_bulk_delete)
        self._ui_signal_connections.append((self._shortcut_delete.activated, self._on_bulk_delete))
        self._shortcut_delete_backspace = QShortcut(QKeySequence(Key_Backspace), self)
        self._shortcut_delete_backspace.activated.connect(self._on_bulk_delete)
        self._ui_signal_connections.append((self._shortcut_delete_backspace.activated, self._on_bulk_delete))

        self._shortcut_search = QShortcut(QKeySequence("Ctrl+F"), self)
        self._shortcut_search_handler = lambda: self.search_input.setFocus()
        self._shortcut_search.activated.connect(self._shortcut_search_handler)
        self._ui_signal_connections.append((self._shortcut_search.activated, self._shortcut_search_handler))

    # ------------------------------------------------------------------ Properties
    @property
    def feature_limit(self) -> int:
        """Get the feature limit.

        Returns:
            Current feature limit
        """
        return self._feature_limit

    @feature_limit.setter
    def feature_limit(self, value: int):
        """Set the feature limit with validation.

        Args:
            value: New feature limit (must be 1-500)

        Raises:
            ValueError: If value is invalid
        """
        if not isinstance(value, int):
            raise ValueError(f"feature_limit must be int, got {type(value).__name__}")
        if value < 1 or value > 500:
            raise ValueError(f"feature_limit must be 1-500, got {value}")
        self._feature_limit = value

    # ------------------------------------------------------------------ Data
    def set_catalog(self, catalog: Optional["LayerCatalogService"]):
        """
        Inject catalog service (Phase 4 pattern).

        Args:
            catalog: LayerCatalogService instance or None to clear.
        """
        if catalog is self._catalog:
            return

        self._disconnect_catalog_signals()
        self._catalog = catalog
        if catalog:
            # Prefer direct catalog access when available
            self._catalog_fetcher = lambda: catalog.get_console_model(
                include_features=True,
                feature_limit=self._feature_limit
            )
            self._wire_catalog_signals()
        else:
            self._catalog_fetcher = None

        self.refresh(full=True)

    def set_catalog_fetcher(self, fetcher: Callable[[], Dict[str, Any]]):
        """Provide callable that returns catalog data."""
        self._disconnect_catalog_signals()
        self._catalog = None
        self._catalog_fetcher = fetcher

    def refresh(self, full: bool = True):
        """
        Refresh tree from catalog data.

        CRITICAL FIX: Issue #2.1 - Now uses background task to prevent UI freeze.
        Previously blocked UI thread for 1-7 seconds with 1000 features.

        Args:
            full: If True, rebuild entire tree. If False, incremental update.
        """
        if self._cleanup_in_progress:
            return

        # Cancel any existing refresh task
        if self._catalog_task_id and self._catalog:
            try:
                self._catalog.cancel_task(self._catalog_task_id)
            except Exception:
                pass
            finally:
                self._catalog_task_id = None

        if self._task_manager:
            self._task_manager.cancel_task("refresh_fetcher")

        # CRITICAL: Use background task for both catalog service and fetcher paths
        if self._catalog or self._catalog_fetcher:
            # Show loading state
            self._show_loading_state()

            # PERFORMANCE FIX: Issue #3.4 - Pass filters to avoid fetching hidden layers
            show_hidden = self.show_hidden_checkbox.isChecked() if self.show_hidden_checkbox else True
            filter_favorites = (self.filter_combo.currentData() == "favorites") if self.filter_combo else False

            if self._catalog:
                def _on_catalog_complete(payload: Dict[str, Any]):
                    self._catalog_task_id = None
                    self._on_refresh_complete(payload, full)

                def _on_catalog_error(exc: Exception):
                    self._catalog_task_id = None
                    self._on_refresh_error(exc)

                try:
                    self._catalog_task_id = self._catalog.start_console_model_task(
                        include_features=True,
                        feature_limit=self._feature_limit,
                        show_hidden=show_hidden,
                        filter_favorites_only=filter_favorites,
                        on_complete=_on_catalog_complete,
                        on_error=_on_catalog_error,
                        task_id="layer_console_refresh"
                    )
                except Exception as exc:
                    _on_catalog_error(exc)
                return
            else:
                # Wrap synchronous fetcher in a QgsTask for background execution
                class FetcherTask(QgsTask):
                    def __init__(self, fetcher: Callable[[], Dict[str, Any]]):
                        super().__init__("Fetch Layer Console Model (fetcher)", QgsTask.CanCancel)
                        self.fetcher = fetcher
                        self.result = None
                        self.error_message = None

                    def run(self):
                        try:
                            self.result = self.fetcher() or {"groups": []}
                            return True
                        except Exception as exc:
                            self.error_message = str(exc)
                            logger.error("FetcherTask error: %s", exc, exc_info=True)
                            return False

                task = FetcherTask(self._catalog_fetcher)
                task_id = "refresh_fetcher"

                self._task_manager.start_task(
                    task=task,
                    on_complete=lambda t: self._on_refresh_complete(t.result, full),
                    on_error=lambda t: self._on_refresh_error(getattr(t, "error_message", "Refresh failed")),
                    task_id=task_id
                )
        else:
            # No catalog available - notify parent to attempt refresh
            self.refresh_requested.emit()

    def _show_loading_state(self):
        """
        Show loading state in UI.

        CRITICAL FIX: Issue #2.1 - Provide visual feedback during background refresh.
        """
        if self._cleanup_in_progress:
            return

        self._is_loading = True

        # Disable interactive elements during load
        if hasattr(self, 'tree') and self.tree:
            self.tree.setEnabled(False)

        if hasattr(self, 'refresh_button') and self.refresh_button:
            self.refresh_button.setEnabled(False)
            self.refresh_button.setText("Loading...")

        if hasattr(self, 'status_label') and self.status_label:
            self.status_label.setText("Loading layer data...")

    def _hide_loading_state(self):
        """
        Hide loading state and restore UI.

        CRITICAL FIX: Issue #2.1 - Restore UI after background refresh completes.
        """
        if self._cleanup_in_progress:
            return

        self._is_loading = False

        # Re-enable interactive elements
        if hasattr(self, 'tree') and self.tree:
            self.tree.setEnabled(True)

        if hasattr(self, 'refresh_button') and self.refresh_button:
            self.refresh_button.setEnabled(True)
            self.refresh_button.setText("↻")

        # Status will be updated by _update_status_bar()

    def _on_refresh_complete(self, payload: Optional[Dict[str, Any]], full: bool):
        """
        Handle successful completion of background refresh.

        CRITICAL FIX: Issue #2.1 - Process results on UI thread.

        Args:
            task: Completed task with results
            full: Whether to do full or incremental rebuild
        """
        # DEFENSIVE GUARD - Check components still exist
        if self._cleanup_in_progress:
            print("[LayerConsole] Refresh completed after cleanup, ignoring")
            return

        if not hasattr(self, '_catalog_data') or not hasattr(self, 'tree'):
            print("[LayerConsole] Refresh completed after widget destroyed, ignoring")
            return

        try:
            if not payload:
                print("[LayerConsole] Warning: Refresh completed without data")
                payload = {"groups": []}

            # ISSUE #4.8: Validate catalog data structure and types
            self._catalog_data = self._validate_catalog_data(payload)

            # Update tree on UI thread
            if full:
                self._rebuild_tree()
            else:
                self._update_tree_incremental()

        except Exception as e:
            print(f"[LayerConsole] Error processing refresh result: {e}")
            import traceback
            traceback.print_exc()
        finally:
            # Always restore UI state
            self._hide_loading_state()

    def _on_refresh_error(self, error):
        """
        Handle refresh task error or cancellation.

        CRITICAL FIX: Issue #2.1 - Gracefully handle background task failures.

        Args:
            task: Failed/cancelled task
        """
        # DEFENSIVE GUARD
        if self._cleanup_in_progress:
            return

        if not hasattr(self, 'status_label'):
            return

        try:
            message = "Refresh cancelled"
            if isinstance(error, Exception):
                message = str(error)
            elif isinstance(error, str):
                message = error

            print(f"[LayerConsole] Refresh failed: {message}")
            if hasattr(self, 'status_label') and self.status_label:
                self.status_label.setText(f"Refresh failed: {message}")
                self.status_label.setStyleSheet("color: red;")
        finally:
            # Always restore UI state
            self._hide_loading_state()

    def _fetch_catalog_model(self) -> Dict[str, Any]:
        """
        Safely retrieve the console model from catalog or fetcher.

        Returns:
            Catalog payload with "groups" key.
        """
        if self._cleanup_in_progress:
            return {"groups": []}

        # In async refactor, this method should only be used by background tasks or legacy callers.
        try:
            if self._catalog:
                return self._catalog.get_console_model(
                    include_features=True,
                    feature_limit=self._feature_limit
                ) or {"groups": []}

            if self._catalog_fetcher:
                return self._catalog_fetcher() or {"groups": []}

            # No catalog available - notify parent to attempt refresh
            self.refresh_requested.emit()
            return {"groups": []}
        except Exception as exc:
            print(f"[LayerConsole] Error fetching catalog: {exc}")
            if hasattr(self, 'status_label') and self.status_label:
                self.status_label.setText(f"Error loading catalog: {exc}")
                self.status_label.setStyleSheet("color: red;")
            return {"groups": []}

    def _validate_catalog_data(self, data: Any) -> Dict[str, Any]:
        """ISSUE #4.8: Validate and sanitize catalog data structure.

        Args:
            data: Raw catalog data from service

        Returns:
            Validated and sanitized catalog data
        """
        if not isinstance(data, dict):
            print(f"[LayerConsole] Security: Catalog data is not dict, got {type(data).__name__}")
            return {"groups": []}

        groups = data.get("groups")
        if not isinstance(groups, list):
            print(f"[LayerConsole] Security: groups is not list, got {type(groups).__name__}")
            return {"groups": []}

        # Limit number of groups to prevent DoS
        if len(groups) > 100:
            print(f"[LayerConsole] Security: Too many groups ({len(groups)}), truncating to 100")
            groups = groups[:100]

        # Validate group structure
        validated_groups = []
        for i, group in enumerate(groups):
            if not isinstance(group, dict):
                print(f"[LayerConsole] Security: group[{i}] is not dict, skipping")
                continue
            layers = group.get("layers", [])
            if not isinstance(layers, list):
                print(f"[LayerConsole] Security: group[{i}].layers is not list, skipping group")
                continue

            validated_layers: List[Dict[str, Any]] = []
            for j, layer in enumerate(layers):
                if not isinstance(layer, dict):
                    print(f"[LayerConsole] Security: group[{i}].layers[{j}] is not dict, skipping")
                    continue

                features = layer.get("features", [])
                if not isinstance(features, list):
                    print(f"[LayerConsole] Security: group[{i}].layers[{j}].features is not list, coercing to empty")
                    features = []

                # Clamp features to feature_limit to avoid UI overload / DoS
                max_features = max(1, int(self._feature_limit or 0)) if isinstance(self._feature_limit, int) else 300
                validated_features: List[Dict[str, Any]] = []
                for k, feature in enumerate(features[:max_features]):
                    if not isinstance(feature, dict):
                        print(f"[LayerConsole] Security: group[{i}].layers[{j}].features[{k}] is not dict, skipping")
                        continue
                    validated_features.append(feature)

                layer_copy = dict(layer)
                layer_copy["features"] = validated_features
                validated_layers.append(layer_copy)

            if validated_layers:
                group_copy = dict(group)
                group_copy["layers"] = validated_layers
                validated_groups.append(group_copy)

        return {"groups": validated_groups}

    def _wire_catalog_signals(self):
        """Connect to catalog signals for automatic updates."""
        if not self._catalog:
            return

        connections = [
            (getattr(self._catalog, "model_changed", None), self._on_catalog_model_changed),
            (getattr(self._catalog, "layer_updated", None), self._on_catalog_layer_updated),
            (getattr(self._catalog, "feature_count_changed", None), self._on_catalog_feature_count_changed),
            (getattr(self._catalog, "alias_changed", None), self._on_catalog_alias_changed)
        ]

        for signal, handler in connections:
            if not signal:
                continue
            try:
                signal.connect(handler)
                self._catalog_connections.append((signal, handler))
            except Exception as exc:
                print(f"[LayerConsole] Warning: failed to connect catalog signal: {exc}")

    def _disconnect_catalog_signals(self):
        """Disconnect catalog signal handlers defensively to avoid Qt crashes."""
        for signal, handler in list(self._catalog_connections):
            try:
                parent = getattr(signal, "__self__", None)
                if parent is None:
                    continue
                if isinstance(parent, QObject):
                    try:
                        _ = parent.objectName()
                    except (RuntimeError, AttributeError):
                        continue
                signal.disconnect(handler)
            except (TypeError, RuntimeError, AttributeError):
                pass
        self._catalog_connections = []

    # ------------------------------------------------------------------ Catalog callbacks
    def _on_catalog_model_changed(self, *_args, **_kwargs):
        """
        Handle catalog model changed signal.

        CRITICAL FIX: Issue #2.3 - Use debouncing to prevent redundant refreshes.
        Previously: 5 feature renames = 10 refreshes (2s-4s wasted).
        Now: Coalesces multiple signals into single refresh after 100ms.
        """
        if self._cleanup_in_progress:
            return

        # Mark that full refresh is needed (trumps incremental)
        self._pending_full_refresh = True

        # Restart debounce timer
        if self._catalog_refresh_timer:
            self._catalog_refresh_timer.start()

    def _on_catalog_layer_updated(self, *_args, **_kwargs):
        """
        Handle catalog layer updated signal.

        CRITICAL FIX: Issue #2.3 - Use debouncing for incremental updates.
        """
        if self._cleanup_in_progress:
            return

        # Only start timer if no full refresh already pending
        if not self._pending_full_refresh and self._catalog_refresh_timer:
            self._catalog_refresh_timer.start()

    def _on_catalog_feature_count_changed(self, *_args, **_kwargs):
        """
        Handle catalog feature count changed signal.

        CRITICAL FIX: Issue #2.3 - Use debouncing for count updates.
        """
        if self._cleanup_in_progress:
            return

        # Count changes don't require full refresh
        if not self._pending_full_refresh and self._catalog_refresh_timer:
            self._catalog_refresh_timer.start()

    def _on_catalog_alias_changed(self, *_args, **_kwargs):
        """
        Handle catalog alias changed signal.

        CRITICAL FIX: Issue #2.3 - Use debouncing for alias changes.
        """
        if self._cleanup_in_progress:
            return

        # Alias changes don't require full refresh
        if not self._pending_full_refresh and self._catalog_refresh_timer:
            self._catalog_refresh_timer.start()

    def _execute_catalog_refresh(self):
        """
        Execute catalog refresh after debounce delay.

        CRITICAL FIX: Issue #2.3 - Coalesces multiple catalog signals.
        Called once after catalog activity settles down (100ms quiet period).
        """
        if self._cleanup_in_progress:
            return

        # Determine refresh type and reset flag
        full = self._pending_full_refresh
        self._pending_full_refresh = False

        # Execute refresh
        self.refresh(full=full)

    def _apply_filter(self):
        """Apply current filter and rebuild tree."""
        if self._cleanup_in_progress:
            return
        self._rebuild_tree()

    def _on_search_changed(self, text: str):
        """
        Search box change handler.

        CRITICAL FIX: Issue #2.2 - Restart debounce timer instead of immediate rebuild.
        Prevents 2.5s lag when typing 5-char search with 1000 features.

        CRITICAL FIX: Issue #1.13 - Limit search string length to prevent DoS.
        """
        if self._cleanup_in_progress:
            return

        # CRITICAL FIX: Issue #1.13 - Limit search string length
        if len(text) > 256:
            # Truncate to 256 characters
            if hasattr(self, 'search_input') and self.search_input:
                self.search_input.setText(text[:256])
            if hasattr(self, 'status_label') and self.status_label:
                self.status_label.setText("Search truncated to 256 characters")
                self.status_label.setStyleSheet("color: orange;")
            return

        # Restart debounce timer on each keystroke
        if self._search_debounce_timer:
            self._search_debounce_timer.start()

    def _execute_search(self):
        """
        Execute search after debounce delay.

        CRITICAL FIX: Issue #2.2 - Only called once after user stops typing.
        Previously called on EVERY keystroke causing severe UI lag.
        """
        if self._cleanup_in_progress:
            return

        # Rebuild tree with current search text
        self._rebuild_tree()

    def _rebuild_tree(self):
        """Rebuild entire tree from catalog data."""
        if self._cleanup_in_progress:
            return
        self._suppress_item_changed = True
        try:
            self._save_expanded_state()
            selection = self._get_selected_items()
            self.tree.clear()

            groups = self._get_filtered_groups(self._catalog_data.get("groups", []))

            for group_data in groups:
                group_item = self._create_group_item(group_data)
                if group_item:
                    self.tree.addTopLevelItem(group_item)

            self._restore_expanded_state()
            self._restore_selection(selection)
            self._apply_pending_selection()
            self._update_bulk_bar()
            self._restore_column_widths()
            self._update_status_bar()
            self._update_empty_state()
        finally:
            self._suppress_item_changed = False

    def _update_tree_incremental(self):
        """
        Lightweight refresh: update counts and visibility without rebuilding.
        Falls back to full rebuild if structure changed.
        """
        # If search or non-default filter is active, rebuild to avoid stale view
        if (
            (self.search_input and self.search_input.text().strip())
            or (self.filter_combo and self.filter_combo.currentData() not in (None,))
            or (self.show_hidden_checkbox and not self.show_hidden_checkbox.isChecked())
        ):
            self._rebuild_tree()
            return

        if self._cleanup_in_progress:
            return
        self._suppress_item_changed = True
        try:
            groups = self._get_filtered_groups(self._catalog_data.get("groups", []))
            group_lookup = {g.get("id"): g for g in groups}
            root = self.tree.invisibleRootItem()

            # If group count changed under current filter, rebuild to avoid stale items
            if root.childCount() != len(group_lookup):
                self._rebuild_tree()
                return

            for i in range(root.childCount()):
                group_item = root.child(i)
                meta = self._get_item_metadata(group_item)
                if not meta or meta.get("type") != "group":
                    continue
                group_id = meta.get("group_id")
                group_data = group_lookup.get(group_id)
                if not group_data:
                    self._rebuild_tree()
                    return
                # If layer structure changed (add/remove or feature list change), rebuild
                if self._has_group_structure_changed(group_item, group_data):
                    self._rebuild_tree()
                    return
                self._update_group_item(group_item, group_data)

            self._update_bulk_bar()
            self._update_status_bar()
        finally:
            self._suppress_item_changed = False

    # ------------------------------------------------------------------ Item creation
    def _create_group_item(self, group_data: Dict[str, Any]) -> Optional[QTreeWidgetItem]:
        try:
            group_id = group_data.get("id")
            group_name = group_data.get("name", "Group")
            layers = group_data.get("layers", []) or []
            if not isinstance(layers, list) or not layers:
                return None
        except Exception as exc:
            print(f"[LayerConsole] Warning: failed to read group data: {exc}")
            return None

        total_features = sum(layer.get("feature_count", 0) for layer in layers)
        item = QTreeWidgetItem([
            f"📁 {group_name}",
            str(total_features),
            "Group",
            ""
        ])
        font = item.font(0)
        font.setBold(True)
        item.setFont(0, font)
        item.setData(0, UserRole, {
            "type": "group",
            "group_id": group_id,
            "feature_count": total_features
        })

        for layer_data in layers:
            layer_item = self._create_layer_item(layer_data)
            if layer_item:
                item.addChild(layer_item)

        if group_id in self._expanded_groups:
            item.setExpanded(True)

        return item

    def _create_layer_item(self, layer_data: Dict[str, Any]) -> Optional[QTreeWidgetItem]:
        try:
            layer_id = layer_data.get("layer_id")
            if not layer_id:
                return None
            layer_name = layer_data.get("display_name") or layer_data.get("name", "Layer")
        except Exception as exc:
            print(f"[LayerConsole] Warning: failed to read layer data: {exc}")
            return None

        # CRITICAL FIX: Issue #2.6 - Use display_feature_count for filtered views
        # Shows filtered count during search, total count otherwise
        feature_count = layer_data.get("display_feature_count", layer_data.get("feature_count", 0))
        geometry_type = layer_data.get("geometry_type", "")
        is_visible = layer_data.get("is_visible", True)
        is_favorite = layer_data.get("is_favorite", False)
        updated_at = layer_data.get("last_updated") or ""
        updated_text = ""
        if isinstance(updated_at, str):
            updated_text = updated_at[:16]
        elif updated_at:
            updated_text = str(updated_at)[:16]

        display_name = f"{self._get_layer_icon(layer_id)} {layer_name}"
        if is_favorite:
            display_name += " ⭐"

        item = QTreeWidgetItem([
            display_name,
            str(feature_count),
            geometry_type,
            updated_text
        ])
        item.setFlags(item.flags() | ItemIsUserCheckable | ItemIsEnabled | ItemIsSelectable)
        item.setCheckState(0, Checked if is_visible else Unchecked)
        item.setData(0, UserRole, {
            "type": "layer",
            "layer_id": layer_id,
            "layer_name": layer_name,
            "layer_alias": layer_data.get("display_name"),
            "feature_count": feature_count,
            "is_visible": is_visible,
            "is_favorite": is_favorite
        })

        features = layer_data.get("features", []) or []
        if not isinstance(features, list):
            print(f"[LayerConsole] Warning: features for layer {layer_id} is not list, skipping features")
            features = []
        for feature_data in features:
            feature_item = self._create_feature_item(feature_data, layer_id)
            if feature_item:
                item.addChild(feature_item)

        # Warn when the catalog count exceeds included features (feature_limit truncation)
        if feature_count > len(features):
            missing = feature_count - len(features)
            notice = QTreeWidgetItem([f"  … {missing} more not shown", "", "", ""])
            notice.setFlags(notice.flags() & ~ItemIsSelectable & ~ItemIsEnabled)
            notice.setData(0, UserRole, {"type": "notice"})
            item.addChild(notice)

        if features:
            item.setExpanded(True)

        return item

    def _create_feature_item(self, feature_data: Dict[str, Any], layer_id: str) -> Optional[QTreeWidgetItem]:
        if not isinstance(feature_data, dict):
            print(f"[LayerConsole] Warning: feature data for layer {layer_id} is not dict, skipping")
            return None

        feature_name = feature_data.get("name") or feature_data.get("id")
        feature_id = feature_data.get("feature_id", feature_data.get("id"))
        business_id = feature_data.get("business_id")
        created_at = feature_data.get("created_at") or ""
        updated_at = feature_data.get("updated_at") or ""

        item = QTreeWidgetItem([
            f"  {feature_name}",
            "",
            feature_data.get("type", ""),
            (updated_at or created_at)[:16]
        ])
        item.setFlags(item.flags() | ItemIsSelectable | ItemIsEnabled)
        item.setData(0, UserRole, {
            "type": "feature",
            "layer_id": layer_id,
            "feature_id": feature_id,
            "business_id": business_id,
            "feature_name": feature_name,
            "feature_data": feature_data
        })
        return item

    # ------------------------------------------------------------------ Updates
    def _update_group_item(self, item: QTreeWidgetItem, group_data: Dict[str, Any]):
        layers = group_data.get("layers", []) or []
        total_features = sum(layer.get("feature_count", 0) for layer in layers)
        item.setText(1, str(total_features))

        # Update layers under this group
        layer_lookup = {layer.get("layer_id"): layer for layer in layers}
        for i in range(item.childCount()):
            child = item.child(i)
            meta = self._get_item_metadata(child)
            if not meta or meta.get("type") != "layer":
                continue
            layer_id = meta.get("layer_id")
            layer_data = layer_lookup.get(layer_id)
            if not layer_data:
                continue
            self._update_layer_item(child, layer_data)

    def _update_layer_item(self, item: QTreeWidgetItem, layer_data: Dict[str, Any]):
        new_count = layer_data.get("feature_count", 0)
        if item.text(1) != str(new_count):
            item.setText(1, str(new_count))

        new_visible = layer_data.get("is_visible", True)
        desired_state = Checked if new_visible else Unchecked
        if item.checkState(0) != desired_state:
            self._set_item_check_state(item, desired_state)

        updated_at = layer_data.get("last_updated") or ""
        if isinstance(updated_at, str):
            updated_text = updated_at[:16]
        elif updated_at:
            updated_text = str(updated_at)[:16]
        else:
            updated_text = ""
        item.setText(3, updated_text)

        metadata = self._get_item_metadata(item) or {}
        metadata["feature_count"] = new_count
        metadata["is_visible"] = new_visible
        metadata["is_favorite"] = layer_data.get("is_favorite", False)
        metadata["layer_alias"] = layer_data.get("display_name")
        item.setData(0, UserRole, metadata)

        # Update display name with icon, alias, and favorite star
        base_name = layer_data.get("display_name") or layer_data.get("name", metadata.get("layer_name", "Layer"))
        display = f"{self._get_layer_icon(layer_data.get('layer_id'))} {base_name}"
        if metadata.get("is_favorite"):
            display += " ⭐"
        item.setText(0, display)

        # Update/maintain truncation notice if feature list is limited
        feature_children = [
            child for child in (item.child(i) for i in range(item.childCount()))
            if self._get_item_metadata(child) and self._get_item_metadata(child).get("type") == "feature"
        ]
        missing = max(0, new_count - len(feature_children))

        # Find existing notice child if present
        notice_item = None
        for i in range(item.childCount()):
            meta = self._get_item_metadata(item.child(i))
            if meta and meta.get("type") == "notice":
                notice_item = item.child(i)
                break

        if missing > 0:
            if notice_item is None:
                notice_item = QTreeWidgetItem([f"  … {missing} more not shown", "", "", ""])
                notice_item.setFlags(notice_item.flags() & ~ItemIsSelectable & ~ItemIsEnabled)
                notice_item.setData(0, UserRole, {"type": "notice"})
                item.addChild(notice_item)
            else:
                notice_item.setText(0, f"  … {missing} more not shown")
        elif notice_item:
            parent = notice_item.parent()
            if parent:
                parent.removeChild(notice_item)

    # ------------------------------------------------------------------ Selection / actions
    def _on_item_changed(self, item: QTreeWidgetItem, column: int):
        if self._cleanup_in_progress:
            return
        if self._suppress_item_changed:
            return
        if column != 0:
            return
        metadata = self._get_item_metadata(item)
        if not metadata or metadata.get("type") != "layer":
            return
        layer_id = metadata.get("layer_id")
        if not layer_id:
            return
        is_visible = item.checkState(0) == Checked
        metadata["is_visible"] = is_visible
        item.setData(0, UserRole, metadata)
        # Emit Phase 4 signal first, then legacy name for compatibility
        self._emit_layer_visibility(layer_id, is_visible)

    def _on_selection_changed(self):
        if self._cleanup_in_progress:
            return
        selected_items = self.tree.selectedItems()
        features: List[Tuple[object, object]] = []  # (feature_id, business_id)
        layer_id: Optional[str] = None

        for item in selected_items:
            meta = self._get_item_metadata(item)
            if not meta:
                continue
            if meta.get("type") != "feature":
                continue

            fid, bid = self._extract_ids(meta)
            features.append((fid, bid))
            item_layer_id = meta.get("layer_id")
            if layer_id is None:
                layer_id = item_layer_id
            elif layer_id != item_layer_id:
                layer_id = None
                break

        self._selected_layer_id = layer_id
        self._selected_feature_ids = [
            self._preferred_id(fid, bid)
            for fid, bid in features
            if self._preferred_id(fid, bid) is not None
        ]
        self._selected_business_ids = [bid for _, bid in features if bid is not None]
        self._update_bulk_bar()

        if features and layer_id:
            primary_id = self._preferred_id(features[0][0], features[0][1])
            if primary_id is not None:
                self.feature_selected.emit(layer_id, primary_id)
                self.layer_selected.emit(layer_id, primary_id)

    def _on_item_double_clicked(self, item: QTreeWidgetItem, column: int):
        if self._cleanup_in_progress:
            return
        metadata = self._get_item_metadata(item)
        if not metadata or metadata.get("type") != "feature":
            return
        layer_id = metadata.get("layer_id")
        fid, bid = self._extract_ids(metadata)
        feature_id = self._preferred_id(fid, bid)
        if layer_id and feature_id is not None:
            self.feature_zoom_requested.emit(layer_id, feature_id)
            self.layer_zoom_requested.emit(layer_id, feature_id)

    def _show_context_menu(self, pos):
        if self._cleanup_in_progress:
            return
        item = self.tree.itemAt(pos)
        if not item:
            return
        metadata = self._get_item_metadata(item)
        if not metadata:
            return

        menu = QMenu(self)
        item_type = metadata.get("type")

        if item_type == "feature":
            layer_id = metadata.get("layer_id")
            fid, bid = self._extract_ids(metadata)
            feature_id = self._preferred_id(fid, bid)

            zoom_action = menu.addAction("🔍 Zoom to Feature")
            zoom_action.triggered.connect(
                lambda checked=False, lid=layer_id, fid=feature_id: self._emit_zoom_request(lid, fid)
            )

            rename_action = menu.addAction("✏️ Rename...")
            rename_action.triggered.connect(lambda: self._start_rename(item))

            duplicate_action = menu.addAction("📋 Duplicate")
            duplicate_action.triggered.connect(
                lambda checked=False, lid=layer_id, fid=feature_id: self.layer_duplicate_requested.emit(lid, fid)
            )

            export_action = menu.addAction("💾 Export")
            export_action.triggered.connect(
                lambda checked=False, lid=layer_id, fid=feature_id: self.layer_export_requested.emit(lid, fid)
            )

            menu.addSeparator()

            delete_action = menu.addAction("🗑️ Delete")
            delete_action.triggered.connect(
                lambda: self._confirm_delete_single(layer_id, feature_id)
            )
            # Move to section (search areas)
            # ISSUE #4.3: Use QGIS feature_id (fid) consistently, not preferred_id
            if layer_id in SEARCH_AREA_LAYER_IDS and fid is not None:
                menu.addSeparator()
                move_menu = menu.addMenu("Move to Section")
                for section_id, section_label in [
                    ("planning", "Planning"),
                    ("active", "Active"),
                    ("reserves", "Reserve"),
                    ("completed", "Completed")
                ]:
                    act = move_menu.addAction(section_label)
                    act.triggered.connect(
                        # Use fid (QGIS feature_id), not feature_id (which may be business_id)
                        lambda checked=False, f=fid, sect=section_id: self._emit_move_to_section(f, sect)
                    )

            move_up = menu.addAction("⬆️ Move Up")
            move_up.triggered.connect(lambda: self._move_feature_item(item, -1))
            move_down = menu.addAction("⬇️ Move Down")
            move_down.triggered.connect(lambda: self._move_feature_item(item, 1))
        elif item_type == "layer":
            layer_id = metadata.get("layer_id")
            is_visible = metadata.get("is_visible", True)
            visibility_text = "👁️ Hide Layer" if is_visible else "👁️ Show Layer"
            visibility_action = menu.addAction(visibility_text)
            visibility_action.triggered.connect(
                lambda checked=False, lid=layer_id, vis=is_visible, it=item: self._emit_layer_visibility(lid, not vis, it)
            )
            alias_action = menu.addAction("✏️ Set Alias…")
            alias_action.triggered.connect(lambda: self._start_layer_alias(item))

            favorite = metadata.get("is_favorite", False)
            favorite_text = "⭐ Unfavorite" if favorite else "⭐ Mark Favorite"
            favorite_action = menu.addAction(favorite_text)
            favorite_action.triggered.connect(
                lambda checked=False, lid=layer_id, fav=not favorite: self._emit_favorite_toggle(lid, fav)
            )

        elif item_type == "group":
            expand_action = menu.addAction("📂 Expand")
            expand_action.triggered.connect(lambda: item.setExpanded(True))
            collapse_action = menu.addAction("📁 Collapse")
            collapse_action.triggered.connect(lambda: item.setExpanded(False))

        exec_fn = getattr(menu, "exec", None) or getattr(menu, "exec_", None)
        if exec_fn:
            exec_fn(self.tree.viewport().mapToGlobal(pos))

    def _start_rename(self, item: QTreeWidgetItem):
        if self._cleanup_in_progress:
            return
        metadata = self._get_item_metadata(item)
        if not metadata or metadata.get("type") != "feature":
            return
        layer_id = metadata.get("layer_id")
        fid, bid = self._extract_ids(metadata)
        feature_id = self._preferred_id(fid, bid)
        if not layer_id or feature_id is None:
            return

        current_name = metadata.get("feature_name") or ""
        new_name = self._prompt_text("Rename Feature", "Enter new name:", current_name)
        if new_name is None or not new_name.strip():
            return

        new_value = new_name.strip()

        # CRITICAL FIX: Issue #1.11 - Validate feature name length and content
        if len(new_value) > 256:
            if hasattr(self, 'status_label') and self.status_label:
                self.status_label.setText("Error: Name must be ≤ 256 characters")
                self.status_label.setStyleSheet("color: red;")
            return

        if '\n' in new_value or '\r' in new_value:
            if hasattr(self, 'status_label') and self.status_label:
                self.status_label.setText("Error: Name cannot contain line breaks")
                self.status_label.setStyleSheet("color: red;")
            return

        if any(ord(c) < 32 for c in new_value if c not in '\t\n\r'):
            if hasattr(self, 'status_label') and self.status_label:
                self.status_label.setText("Error: Name contains invalid control characters")
                self.status_label.setStyleSheet("color: red;")
            return

        # Emit request and let catalog signal trigger UI update (no optimistic update)
        self.feature_rename_requested.emit(layer_id, feature_id, new_value)
        self.layer_rename_requested.emit(layer_id, feature_id, new_value)

    def _start_layer_alias(self, item: QTreeWidgetItem):
        """Prompt for layer alias and emit request."""
        if self._cleanup_in_progress:
            return
        metadata = self._get_item_metadata(item)
        if not metadata or metadata.get("type") != "layer":
            return
        layer_id = metadata.get("layer_id")
        if not layer_id:
            return
        current_alias = metadata.get("layer_alias") or metadata.get("layer_name") or ""
        new_alias = self._prompt_text("Set Layer Alias", "Enter alias (leave blank to clear):", current_alias)
        if new_alias is None:
            return

        new_alias = new_alias.strip()

        # CRITICAL FIX: Issue #1.12 - Validate layer alias length and content
        if new_alias:  # Only validate if not clearing alias
            if len(new_alias) > 128:
                if hasattr(self, 'status_label') and self.status_label:
                    self.status_label.setText("Error: Alias must be ≤ 128 characters")
                    self.status_label.setStyleSheet("color: red;")
                return

            if '\n' in new_alias or '\r' in new_alias:
                if hasattr(self, 'status_label') and self.status_label:
                    self.status_label.setText("Error: Alias cannot contain line breaks")
                    self.status_label.setStyleSheet("color: red;")
                return

        # Emit request and let catalog signal trigger UI update (no optimistic update)
        self.layer_alias_change_requested.emit(layer_id, new_alias)

    def _prompt_text(self, title: str, label: str, value: str = "") -> Optional[str]:
        """Qt5/Qt6 safe text prompt using BaseDialog."""
        class PromptDialog(BaseDialog):
            def __init__(self, parent=None, caption="", prompt="", initial=""):
                super().__init__(parent)
                self.setWindowTitle(caption)
                layout = QVBoxLayout()
                layout.addWidget(QLabel(prompt))
                self.input = QLineEdit()
                self.input.setText(initial)
                layout.addWidget(self.input)
                button_row = QHBoxLayout()
                ok_button = QPushButton("OK")
                ok_button.clicked.connect(self.accept)
                cancel_button = QPushButton("Cancel")
                cancel_button.clicked.connect(self.reject)
                button_row.addStretch()
                button_row.addWidget(ok_button)
                button_row.addWidget(cancel_button)
                layout.addLayout(button_row)
                self.setLayout(layout)

            def value(self) -> str:
                return self.input.text().strip()

        dialog = PromptDialog(self, caption=title, prompt=label, initial=value)
        if dialog_exec(dialog) == DialogAccepted:
            return dialog.value()
        return None

    def _confirm_delete_single(self, layer_id: str, feature_id: object):
        if self._cleanup_in_progress:
            return
        confirmed = self._confirm_action(
            "Confirm Delete",
            "Delete selected feature?",
            "This action CANNOT BE UNDONE."
        )
        if confirmed:
            self.feature_delete_requested.emit(layer_id, feature_id)
            self.layer_delete_requested.emit(layer_id, feature_id)

    def _emit_favorite_toggle(self, layer_id: Optional[str], new_state: bool):
        """Emit favorite toggle - UI update handled by catalog signal.

        ISSUE #4.5: Removed unused 'item' parameter for cleaner API.
        """
        if not layer_id or self._cleanup_in_progress:
            return
        # Emit request and let catalog signal trigger UI update (no optimistic update)
        self.layer_favorite_toggled.emit(layer_id, new_state)

    def _emit_move_to_section(self, feature_id: object, section: str):
        """Emit move request for search areas."""
        if self._cleanup_in_progress:
            return
        try:
            coerced_id = int(str(feature_id))
        except Exception:
            coerced_id = feature_id
        self.move_to_section_requested.emit(coerced_id, section)

    def _move_feature_item(self, item: QTreeWidgetItem, direction: int):
        """Reorder a feature item within its layer and emit reorder signal."""
        if self._cleanup_in_progress:
            return
        meta = self._get_item_metadata(item)
        if not meta or meta.get("type") != "feature":
            return
        parent = item.parent()
        if not parent:
            return
        # Collect feature children (skip notices)
        feature_children = [
            child for child in (parent.child(i) for i in range(parent.childCount()))
            if self._get_item_metadata(child) and self._get_item_metadata(child).get("type") == "feature"
        ]
        if item not in feature_children:
            return
        current_index = feature_children.index(item)
        new_index = current_index + direction
        if new_index < 0 or new_index >= len(feature_children):
            return

        # Reinsert item at new index
        parent.removeChild(item)
        parent.insertChild(new_index, item)

        # Emit reorder signal with new ordering
        self._emit_reorder_for_layer(parent)

    def _emit_reorder_for_layer(self, layer_item: QTreeWidgetItem):
        """Emit reorder request based on current child order of a layer item."""
        meta = self._get_item_metadata(layer_item)
        if not meta or meta.get("type") != "layer":
            return
        layer_id = meta.get("layer_id")
        if not layer_id:
            return

        feature_children = [
            child for child in (layer_item.child(i) for i in range(layer_item.childCount()))
            if self._get_item_metadata(child) and self._get_item_metadata(child).get("type") == "feature"
        ]
        feature_ids: List[object] = []
        for child in feature_children:
            child_meta = self._get_item_metadata(child) or {}
            fid, bid = self._extract_ids(child_meta)
            # CRITICAL FIX: Always use QGIS feature_id for reorder, not business_id
            # Reordering requires the actual QGIS feature ID to update display_order
            if fid is not None:
                feature_ids.append(fid)

        if feature_ids:
            self.reorder_requested.emit(layer_id, feature_ids)

    # ------------------------------------------------------------------ Bulk ops
    def _layer_supports_bulk_operations(self, layer_id: Optional[str]) -> bool:
        """Check if layer supports bulk operations.

        ISSUE #3.9: Tracking layers should not support bulk delete/edit.

        Args:
            layer_id: Layer identifier

        Returns:
            True if bulk operations supported, False otherwise
        """
        if not layer_id:
            return False

        # Protected tracking layers
        protected_layers = {"sar_current_positions_active", "sar_breadcrumbs"}
        return layer_id not in protected_layers

    def _update_bulk_bar(self):
        count = len(self._selected_feature_ids)

        # ISSUE #3.10: Provide feedback for mixed layer selection
        if self._selected_layer_id is None and count > 0:
            self.bulk_label.setText(f"{count} selected (mixed layers)")
            self.bulk_delete_button.setEnabled(False)
            self.bulk_export_button.setEnabled(False)
            self.bulk_team_button.setEnabled(False)
            self.bulk_delete_button.setToolTip(
                "Cannot delete features from multiple layers.\nSelect from single layer only."
            )
            self.bulk_export_button.setToolTip("Cannot export from multiple layers")
            self.bulk_team_button.setToolTip("Cannot assign team to multiple layers")
            self._update_status_bar()
            return

        # ISSUE #3.9: Check if layer supports bulk operations
        layer_supports_bulk = self._layer_supports_bulk_operations(self._selected_layer_id)
        enabled = count > 0 and self._selected_layer_id and layer_supports_bulk

        self.bulk_label.setText(f"{count} selected")

        if count > 0 and not layer_supports_bulk:
            # Disable with explanation
            self.bulk_delete_button.setEnabled(False)
            self.bulk_export_button.setEnabled(False)
            self.bulk_team_button.setEnabled(False)
            self.bulk_delete_button.setToolTip("Bulk delete not available for tracking layers")
            self.bulk_export_button.setToolTip("Export not available for tracking layers")
            self.bulk_team_button.setToolTip("Team assignment not available for tracking layers")
        else:
            # Normal state
            self.bulk_delete_button.setEnabled(enabled)
            self.bulk_export_button.setEnabled(enabled)
            self.bulk_team_button.setEnabled(enabled)
            self.bulk_delete_button.setToolTip("Delete selected features (Delete key)")
            self.bulk_export_button.setToolTip("Export selected features")
            self.bulk_team_button.setToolTip("Assign team to selected features")

        self._update_status_bar()

    def _update_status_bar(self):
        """Update status label with current counts."""
        if not hasattr(self, "status_label") or not self.status_label:
            return
        shown = max(0, int(self._status_shown_items or 0))
        total = max(0, int(self._status_total_items or 0))
        text = f"Showing {shown} of {total} items"
        self.status_label.setText(text)

    def _update_empty_state(self):
        """ISSUE #3.7: Update empty state with contextual message.

        Shows appropriate message based on why tree is empty:
        - No matching items (filters/search active)
        - No mission data loaded
        - No layers available
        """
        if not self._empty_state_label:
            return

        has_items = self.tree.topLevelItemCount() > 0

        if has_items:
            self._empty_state_label.setVisible(False)
            self.tree.setVisible(True)
            return

        # Determine WHY empty
        filter_active = (
            self.filter_combo
            and self.filter_combo.currentData() not in (None,)
        )
        search_active = bool(self.search_input and self.search_input.text().strip())
        has_raw_data = bool(self._catalog_data.get("groups"))

        if search_active or filter_active:
            self._empty_state_label.setText(
                "No matching items.\nAdjust filters or clear search."
            )
        elif not has_raw_data:
            self._empty_state_label.setText(
                "No mission data loaded.\nStart mission or refresh."
            )
        else:
            self._empty_state_label.setText("No layers available")

        self._empty_state_label.setVisible(True)
        self.tree.setVisible(False)

    def _on_bulk_delete(self):
        if self._cleanup_in_progress:
            return
        if not self._selected_layer_id or not self._selected_feature_ids:
            return

        count = len(self._selected_feature_ids)
        layer_total = self._get_layer_total_count(self._selected_layer_id)
        percent_of_layer = (count / layer_total * 100) if layer_total > 0 else 0

        # CRITICAL: Check for truncated view (hidden features exist)
        has_hidden = layer_total > self._feature_limit
        deleting_all_visible = count >= self._feature_limit

        # CRITICAL: Show escalating warnings based on deletion percentage and truncation
        if has_hidden and deleting_all_visible:
            # Deleting all visible features but hidden ones remain - special warning
            layer_name = self._get_layer_display_name(self._selected_layer_id)
            remaining = layer_total - count
            confirmed = self._confirm_action(
                "⚠️ Truncated View Warning",
                f"Delete {count} visible features from '{layer_name}'?",
                f"Layer contains {layer_total} total features.\n"
                f"Only first {self._feature_limit} shown in console.\n\n"
                f"This deletes VISIBLE features only.\n"
                f"{remaining} features will remain.\n\n"
                f"This action CANNOT BE UNDONE."
            )
        elif percent_of_layer >= 100:
            # Deleting ALL features - strongest warning
            layer_name = self._get_layer_display_name(self._selected_layer_id)
            confirmed = self._confirm_action(
                "⚠️ DELETE ALL FEATURES",
                f"You are about to delete ALL {count} features from '{layer_name}'.",
                "This will PERMANENTLY ERASE all data in this layer.\n\nThis action CANNOT BE UNDONE.\n\nAre you absolutely certain?"
            )
        elif percent_of_layer >= 50:
            # Deleting majority of layer - show percentage warning
            layer_name = self._get_layer_display_name(self._selected_layer_id)
            confirmed = self._confirm_action(
                "⚠️ Bulk Delete Warning",
                f"Delete {count} of {layer_total} features ({percent_of_layer:.0f}%) from '{layer_name}'?",
                "This deletes the MAJORITY of data in this layer.\n\nThis action CANNOT BE UNDONE."
            )
        else:
            # Normal bulk delete confirmation
            layer_name = self._get_layer_display_name(self._selected_layer_id)
            confirmed = self._confirm_action(
                "Confirm Bulk Delete",
                f"Delete {count} features from '{layer_name}'?",
                "This will permanently delete the selected features.\n\nThis action CANNOT BE UNDONE."
            )

        if not confirmed:
            return
        self.bulk_delete_requested.emit(self._selected_layer_id, list(self._selected_feature_ids))

    def _on_bulk_export(self):
        if self._cleanup_in_progress:
            return
        if not self._selected_layer_id or not self._selected_feature_ids:
            return
        self.bulk_export_requested.emit(self._selected_layer_id, list(self._selected_feature_ids))

    def _on_bulk_assign_team(self):
        if self._cleanup_in_progress:
            return
        if not self._selected_layer_id or not self._selected_feature_ids:
            return

        class TeamDialog(BaseDialog):
            def __init__(self, parent=None):
                super().__init__(parent)
                self.setWindowTitle("Assign Team")
                layout = QVBoxLayout()
                layout.addWidget(QLabel("Select team:"))
                self.combo = QComboBox()
                self.combo.addItems(["Team Alpha", "Team Bravo", "Team Charlie", "Reserve"])
                layout.addWidget(self.combo)
                button_row = QHBoxLayout()
                ok_btn = QPushButton("OK")
                ok_btn.clicked.connect(self.accept)
                cancel_btn = QPushButton("Cancel")
                cancel_btn.clicked.connect(self.reject)
                button_row.addStretch()
                button_row.addWidget(ok_btn)
                button_row.addWidget(cancel_btn)
                layout.addLayout(button_row)
                self.setLayout(layout)

            def value(self) -> str:
                return self.combo.currentText()

        dialog = TeamDialog(self)
        if dialog_exec(dialog) != DialogAccepted:
            return
        self.bulk_assign_team_requested.emit(
            self._selected_layer_id,
            list(self._selected_feature_ids),
            dialog.value()
        )

    # ------------------------------------------------------------------ Helpers
    def _get_layer_total_count(self, layer_id: str) -> int:
        """
        Get total feature count for a layer.

        Args:
            layer_id: Layer identifier

        Returns:
            Total feature count (0 if layer not found)
        """
        if not layer_id:
            return 0

        # Try to get from cached catalog data first
        if self._catalog_data:
            for group in self._catalog_data.get("groups", []):
                for layer in group.get("layers", []):
                    if layer.get("layer_id") == layer_id:
                        return layer.get("feature_count", 0)

        # Fallback: Get from catalog service
        # Attempt to retrieve feature count from catalog service with diagnostic logging
        if self._catalog:
            try:
                layer_info = self._catalog.get_layer(layer_id)
                if layer_info:
                    return layer_info.feature_count
            except Exception as e:
                # Log the exception without blocking, but provide diagnostic information
                import logging
                logger = logging.getLogger(__name__)
                logger.warning(f"Failed to retrieve feature count for layer {layer_id}: {str(e)}")

        return 0  # Return 0 if unable to retrieve feature count

    def _get_layer_display_name(self, layer_id: str) -> str:
        """
        Get display name (alias or canonical name) for a layer.

        Args:
            layer_id: Layer identifier

        Returns:
            Display name (returns layer_id if not found)
        """
        if not layer_id:
            return "Unknown Layer"

        # Try to get from cached catalog data first
        if self._catalog_data:
            for group in self._catalog_data.get("groups", []):
                for layer in group.get("layers", []):
                    if layer.get("layer_id") == layer_id:
                        return layer.get("display_name") or layer.get("name", layer_id)

        # Fallback: Get from catalog service
        if self._catalog:
            try:
                layer_info = self._catalog.get_layer(layer_id)
                if layer_info:
                    return layer_info.display_name
            except Exception:
                pass

        return layer_id

    def _on_refresh_clicked(self):
        if self._cleanup_in_progress:
            return
        self.refresh_requested.emit()
        self.refresh(full=True)

    def _get_item_metadata(self, item: QTreeWidgetItem) -> Optional[Dict[str, Any]]:
        if not item:
            return None
        metadata = item.data(0, UserRole)
        if not metadata or not isinstance(metadata, dict):
            return None
        return metadata

    def _filter_favorites(self, groups: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        filtered = []
        for group in groups:
            layers = [
                layer for layer in group.get("layers", [])
                if layer.get("is_favorite", False)
            ]
            if layers:
                new_group = dict(group)
                new_group["layers"] = layers
                filtered.append(new_group)
        return filtered

    def _get_selected_items(self) -> List[Tuple[str, object]]:
        selected = []
        for item in self.tree.selectedItems():
            meta = self._get_item_metadata(item)
            if meta and meta.get("type") == "feature":
                fid, bid = self._extract_ids(meta)
                selected.append((
                    meta.get("layer_id"),
                    self._preferred_id(fid, bid)
                ))
        return selected

    def _restore_selection(self, selection: List[Tuple[str, object]]):
        if not selection:
            return
        selection_set = {(layer, fid) for layer, fid in selection if layer}

        # PERFORMANCE FIX: Issue #3.2 - Early termination when all selections found
        found_count = 0
        target_count = len(selection_set)

        root = self.tree.invisibleRootItem()
        for i in range(root.childCount()):
            if found_count >= target_count:
                break  # Early termination - all selections found

            group_item = root.child(i)
            for j in range(group_item.childCount()):
                if found_count >= target_count:
                    break

                layer_item = group_item.child(j)
                for k in range(layer_item.childCount()):
                    if found_count >= target_count:
                        break

                    feature_item = layer_item.child(k)
                    meta = self._get_item_metadata(feature_item)
                    if not meta or meta.get("type") != "feature":
                        continue
                    fid, bid = self._extract_ids(meta)
                    preferred = self._preferred_id(fid, bid)
                    lid = meta.get("layer_id")
                    if (lid, preferred) in selection_set:
                        feature_item.setSelected(True)
                        found_count += 1

    def _save_expanded_state(self):
        self._expanded_groups.clear()
        root = self.tree.invisibleRootItem()
        for i in range(root.childCount()):
            item = root.child(i)
            meta = self._get_item_metadata(item)
            if meta and meta.get("type") == "group" and item.isExpanded():
                group_id = meta.get("group_id")
                if group_id:
                    self._expanded_groups.add(group_id)

    def _restore_expanded_state(self):
        root = self.tree.invisibleRootItem()
        for i in range(root.childCount()):
            item = root.child(i)
            meta = self._get_item_metadata(item)
            if meta and meta.get("type") == "group":
                group_id = meta.get("group_id")
                if group_id in self._expanded_groups:
                    item.setExpanded(True)

    def _on_item_expanded(self, item: QTreeWidgetItem):
        """PERFORMANCE FIX: Issue #3.3 - Track expansion incrementally."""
        if self._cleanup_in_progress:
            return
        meta = self._get_item_metadata(item)
        if meta and meta.get("type") == "group":
            group_id = meta.get("group_id")
            if group_id:
                self._expanded_groups.add(group_id)

    def _on_item_collapsed(self, item: QTreeWidgetItem):
        """PERFORMANCE FIX: Issue #3.3 - Track collapse incrementally."""
        if self._cleanup_in_progress:
            return
        meta = self._get_item_metadata(item)
        if meta and meta.get("type") == "group":
            group_id = meta.get("group_id")
            if group_id:
                self._expanded_groups.discard(group_id)

    def _get_layer_icon(self, layer_id: str) -> str:
        icon_map = {
            "sar_markers_ipp_lkp": "📍",
            "sar_markers_clues": "🔍",
            "sar_markers_hazards": "⚠️",
            "sar_markers_casualties": "🏥",
            "sar_search_areas": "🔳",
            "sar_search_sectors": "🧭",
            "sar_lines": "📏",
            "sar_bearing_lines": "📐",
            "sar_range_rings": "⭕",
            "sar_text_labels": "📝",
            "sar_current_positions_active": "🛰️",
            "sar_breadcrumbs": "🔴",
        }
        return icon_map.get(layer_id, "📄")

    def _save_settings(self):
        settings = QSettings()
        expanded_str = ",".join(self._expanded_groups)
        for key in (
            SETTINGS_KEYS.LAYER_CONSOLE_EXPANDED_GROUPS,
            SETTINGS_KEYS.LAYER_CONSOLE_EXPANDED_GROUPS_LEGACY
        ):
            settings.setValue(key, expanded_str)
        widths = [
            self.tree.columnWidth(0),
            self.tree.columnWidth(1),
            self.tree.columnWidth(2),
            self.tree.columnWidth(3)
        ]
        widths_str = ",".join(str(w) for w in widths)
        for key in (
            SETTINGS_KEYS.LAYER_CONSOLE_COLUMN_WIDTHS,
            SETTINGS_KEYS.LAYER_CONSOLE_COLUMN_WIDTHS_LEGACY
        ):
            settings.setValue(key, widths_str)

        filter_index = self.filter_combo.currentIndex()
        for key in (
            SETTINGS_KEYS.LAYER_CONSOLE_FILTER_STATE,
            SETTINGS_KEYS.LAYER_CONSOLE_FILTER_STATE_LEGACY
        ):
            settings.setValue(key, filter_index)
        settings.setValue(
            SETTINGS_KEYS.LAYER_CONSOLE_FILTER_TYPE,
            str(self.filter_combo.currentData() or "")
        )

        settings.setValue(SETTINGS_KEYS.LAYER_CONSOLE_SELECTED_LAYER, self._selected_layer_id or "")
        settings.setValue(SETTINGS_KEYS.LAYER_CONSOLE_SELECTED_LAYER_LEGACY, self._selected_layer_id or "")
        selected_first = self._selected_feature_ids[0] if self._selected_feature_ids else ""
        settings.setValue(SETTINGS_KEYS.LAYER_CONSOLE_SELECTED_FEATURE, selected_first)
        settings.setValue(SETTINGS_KEYS.LAYER_CONSOLE_SELECTED_FEATURE_LEGACY, selected_first)

        # Combined selection token for Phase 4 spec compatibility
        selection_token = ""
        if self._selected_layer_id:
            feature_token = str(selected_first) if selected_first != "" else ""
            selection_token = f"{self._selected_layer_id}:{feature_token}"
        settings.setValue(SETTINGS_KEYS.LAYER_CONSOLE_LAST_SELECTION, selection_token)

        # Persist search and show-hidden states (Phase 4 keys)
        if hasattr(self, "search_input") and self.search_input:
            settings.setValue(SETTINGS_KEYS.LAYER_CONSOLE_SEARCH_TEXT, self.search_input.text())
        if hasattr(self, "show_hidden_checkbox") and self.show_hidden_checkbox:
            settings.setValue(SETTINGS_KEYS.LAYER_CONSOLE_SHOW_HIDDEN, self.show_hidden_checkbox.isChecked())

    def _load_settings(self):
        """
        Load persisted settings from QSettings.

        CRITICAL FIX: Issue #2.8 - Wrapped in try/except to handle corrupted settings.
        Plugin will continue with defaults rather than crash.
        """
        try:
            settings = QSettings()
            expanded = settings.value(SETTINGS_KEYS.LAYER_CONSOLE_EXPANDED_GROUPS, "")
            if not expanded:
                expanded = settings.value(SETTINGS_KEYS.LAYER_CONSOLE_EXPANDED_GROUPS_LEGACY, "")
            if expanded:
                self._expanded_groups = set(str(expanded).split(","))

            filter_value = settings.value(SETTINGS_KEYS.LAYER_CONSOLE_FILTER_STATE, None)
            if filter_value is None:
                filter_value = settings.value(SETTINGS_KEYS.LAYER_CONSOLE_FILTER_STATE_LEGACY, 0)
            try:
                filter_index = int(filter_value or 0)
            except Exception:
                filter_index = 0
            if 0 <= filter_index < self.filter_combo.count():
                self.filter_combo.setCurrentIndex(filter_index)
            else:
                saved_filter_type = settings.value(SETTINGS_KEYS.LAYER_CONSOLE_FILTER_TYPE, None)
                if saved_filter_type:
                    for i in range(self.filter_combo.count()):
                        if str(self.filter_combo.itemData(i)) == str(saved_filter_type):
                            self.filter_combo.setCurrentIndex(i)
                            break

            saved_layer = settings.value(SETTINGS_KEYS.LAYER_CONSOLE_SELECTED_LAYER, "")
            if not saved_layer:
                saved_layer = settings.value(SETTINGS_KEYS.LAYER_CONSOLE_SELECTED_LAYER_LEGACY, "")
            saved_feature = settings.value(SETTINGS_KEYS.LAYER_CONSOLE_SELECTED_FEATURE, "")
            if saved_feature == "":
                saved_feature = settings.value(SETTINGS_KEYS.LAYER_CONSOLE_SELECTED_FEATURE_LEGACY, "")

            pending = None
            selection_token = settings.value(SETTINGS_KEYS.LAYER_CONSOLE_LAST_SELECTION, "")
            if selection_token:
                try:
                    layer_part, feature_part = str(selection_token).split(":", 1)
                    if layer_part:
                        pending = (layer_part, feature_part if feature_part != "" else None)
                except ValueError:
                    pending = None

            if not pending and saved_layer:
                pending = (str(saved_layer), saved_feature if saved_feature not in (None, "") else None)

            if pending:
                self._pending_selection = pending

            # Restore search/filter visibility options if available
            search_value = settings.value(SETTINGS_KEYS.LAYER_CONSOLE_SEARCH_TEXT, "")
            if search_value and hasattr(self, "search_input") and self.search_input:
                self.search_input.setText(str(search_value))

            # CRITICAL FIX: Issue #2.4 - Use type=bool for Qt5/Qt6 compatibility
            # Qt5 stores booleans as strings ("true"/"false"), Qt6 as actual booleans
            # ISSUE #4.6: Use explicit default constant
            show_hidden_value = settings.value(
                SETTINGS_KEYS.LAYER_CONSOLE_SHOW_HIDDEN,
                SETTINGS_KEYS.LAYER_CONSOLE_SHOW_HIDDEN_DEFAULT,
                type=bool  # Forces consistent conversion across Qt versions
            )
            if hasattr(self, "show_hidden_checkbox") and self.show_hidden_checkbox:
                self.show_hidden_checkbox.setChecked(bool(show_hidden_value))

            self._restore_column_widths()

        except Exception as exc:
            # CRITICAL FIX: Issue #2.8 - Don't crash on corrupted settings
            # ISSUE #4.7: Enhanced error logging for debugging
            print(f"[LayerConsole] Warning: Failed to load settings: {exc}")
            print(f"[LayerConsole] Exception type: {type(exc).__name__}")
            import traceback
            traceback.print_exc()
            print("[LayerConsole] Continuing with default settings")
            # Continue with defaults - widget will still function

    def _restore_column_widths(self):
        settings = QSettings()
        widths = settings.value(SETTINGS_KEYS.LAYER_CONSOLE_COLUMN_WIDTHS, "")
        if not widths:
            widths = settings.value(SETTINGS_KEYS.LAYER_CONSOLE_COLUMN_WIDTHS_LEGACY, "")
        if not widths:
            return
        try:
            values = [int(w) for w in str(widths).split(",") if w]
            if len(values) >= 4:
                self.tree.setColumnWidth(0, values[0])
                self.tree.setColumnWidth(1, values[1])
                self.tree.setColumnWidth(2, values[2])
                self.tree.setColumnWidth(3, values[3])
        except Exception:
            return

    def cleanup(self):
        """Persist state, disconnect signals, and release references."""
        print("[LayerConsole] Starting cleanup...")
        self._cleanup_in_progress = True

        # CRITICAL FIX: Issue #2.1 - Cancel all background tasks FIRST
        if hasattr(self, '_task_manager') and self._task_manager:
            try:
                self._task_manager.cancel_all()
                print("[LayerConsole] Cancelled all background tasks")
            except Exception as exc:
                print(f"[LayerConsole] Warning: failed to cancel tasks: {exc}")

        # CRITICAL FIX: Issue #2.2 - Stop search debounce timer
        if hasattr(self, '_search_debounce_timer') and self._search_debounce_timer:
            try:
                if self._search_debounce_timer.isActive():
                    self._search_debounce_timer.stop()
                self._search_debounce_timer.timeout.disconnect()
                print("[LayerConsole] Stopped search debounce timer")
            except (RuntimeError, TypeError):
                pass

        # CRITICAL FIX: Issue #2.3 - Stop catalog refresh debounce timer
        if hasattr(self, '_catalog_refresh_timer') and self._catalog_refresh_timer:
            try:
                if self._catalog_refresh_timer.isActive():
                    self._catalog_refresh_timer.stop()
                self._catalog_refresh_timer.timeout.disconnect()
                print("[LayerConsole] Stopped catalog refresh timer")
            except (RuntimeError, TypeError):
                pass

        try:
            self._save_expanded_state()
            self._save_settings()
        except Exception as exc:
            print(f"[LayerConsole] Warning: failed to save settings: {exc}")

        # Disconnect catalog callbacks early to avoid post-destruction invocations
        try:
            self._disconnect_catalog_signals()
        except Exception as exc:
            print(f"[LayerConsole] Warning: failed to disconnect catalog signals: {exc}")

        # CRITICAL: Block ALL signals during cleanup to prevent crashes
        try:
            self.blockSignals(True)
            self.filter_combo.blockSignals(True)
            if hasattr(self, "search_input") and self.search_input:
                self.search_input.blockSignals(True)
            if hasattr(self, "show_hidden_checkbox") and self.show_hidden_checkbox:
                self.show_hidden_checkbox.blockSignals(True)
            self.refresh_button.blockSignals(True)
            self.tree.blockSignals(True)
            self.bulk_delete_button.blockSignals(True)
            self.bulk_export_button.blockSignals(True)
            self.bulk_team_button.blockSignals(True)
        except Exception as exc:
            print(f"[LayerConsole] Warning: failed to block signals: {exc}")

        # Clear tree to release item references BEFORE disconnecting
        try:
            self.tree.clear()
        except Exception as exc:
            print(f"[LayerConsole] Warning: failed to clear tree: {exc}")

        # Now safely disconnect all tracked UI signals (targeted disconnection)
        for signal, handler in list(self._ui_signal_connections):
            try:
                signal.disconnect(handler)
            except (TypeError, RuntimeError):
                pass
        self._ui_signal_connections = []

        # Release references
        self._catalog_fetcher = None
        self._catalog_data = {}
        self._selected_feature_ids = []
        self._selected_layer_id = None
        self._selected_business_ids = []
        self._catalog = None

        print("[LayerConsole] Cleanup complete")

    def _apply_pending_selection(self):
        """Apply persisted selection after first refresh."""
        if not self._pending_selection:
            return
        layer_id, feature_id = self._pending_selection
        root = self.tree.invisibleRootItem()
        for i in range(root.childCount()):
            group_item = root.child(i)
            for j in range(group_item.childCount()):
                layer_item = group_item.child(j)
                layer_meta = self._get_item_metadata(layer_item)
                if not layer_meta or layer_meta.get("layer_id") != layer_id:
                    continue
                for k in range(layer_item.childCount()):
                    feature_item = layer_item.child(k)
                    meta = self._get_item_metadata(feature_item)
                    fid, bid = self._extract_ids(meta)
                    preferred = self._preferred_id(fid, bid)
                    if feature_id is None or (preferred is not None and str(preferred) == str(feature_id)):
                        feature_item.setSelected(True)
                        self.tree.scrollToItem(feature_item)
                        self._pending_selection = None
                        return

    def _confirm_action(self, title: str, text: str, detail: str = "") -> bool:
        """Qt-compatible confirmation dialog using BaseDialog."""
        dialog = BaseDialog(self)
        dialog.setWindowTitle(title)
        layout = QVBoxLayout()
        label = QLabel(text)
        label.setWordWrap(True)
        layout.addWidget(label)
        if detail:
            detail_label = QLabel(detail)
            detail_label.setWordWrap(True)
            layout.addWidget(detail_label)

        buttons = QHBoxLayout()
        yes_btn = QPushButton("Yes")
        yes_btn.clicked.connect(dialog.accept)
        no_btn = QPushButton("No")
        no_btn.clicked.connect(dialog.reject)
        buttons.addStretch()
        buttons.addWidget(yes_btn)
        buttons.addWidget(no_btn)
        layout.addLayout(buttons)

        dialog.setLayout(layout)
        return dialog_exec(dialog) == DialogAccepted

    # ------------------------------------------------------------------ Helpers (IDs / structure)
    def _emit_zoom_request(self, layer_id: Optional[str], feature_id: Optional[object]):
        """Emit zoom signals with safety guards."""
        if not layer_id or feature_id is None or self._cleanup_in_progress:
            return
        self.feature_zoom_requested.emit(layer_id, feature_id)
        self.layer_zoom_requested.emit(layer_id, feature_id)

    def _extract_ids(self, meta: Dict[str, Any]) -> Tuple[object, object]:
        """Return (feature_id, business_id) from item metadata with None-safe defaults."""
        return meta.get("feature_id"), meta.get("business_id")

    def _preferred_id(self, feature_id: object, business_id: object) -> Optional[object]:
        """Prefer business_id when present; otherwise use feature_id (even if 0)."""
        if business_id is not None:
            return business_id
        return feature_id

    def _get_filtered_groups(self, groups: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Apply current filter/search/show-hidden settings to catalog groups.

        Returns:
            Filtered groups list with feature lists trimmed to search results.
        """
        filter_value = self.filter_combo.currentData() if self.filter_combo else None
        search_text = self.search_input.text().strip().lower() if self.search_input else ""
        show_hidden = self.show_hidden_checkbox.isChecked() if self.show_hidden_checkbox else True

        filtered_groups, shown_items, total_items, search_active = self._shape_filtered_groups(
            groups=groups,
            filter_value=filter_value,
            search_text=search_text,
            show_hidden=show_hidden,
            feature_limit=self._feature_limit
        )

        self._status_total_items = total_items
        self._status_shown_items = shown_items
        self._search_active = search_active
        return filtered_groups

    def _matches_search(self, text: str, needle: str) -> bool:
        """Case-insensitive substring search with None safety."""
        return self._matches_search_static(text, needle)

    def _layer_matches_type_filter(self, layer: Dict[str, Any], filter_value: Optional[str]) -> bool:
        """Determine if a layer matches the selected type filter."""
        return self._layer_matches_type_filter_static(layer, filter_value)

    @staticmethod
    def _matches_search_static(text: str, needle: str) -> bool:
        """Case-insensitive substring search with None safety (pure helper)."""
        if not needle:
            return True
        if text is None:
            return False
        return needle in str(text).lower()

    @staticmethod
    def _layer_matches_type_filter_static(layer: Dict[str, Any], filter_value: Optional[str]) -> bool:
        """Determine if a layer matches the selected type filter (pure helper)."""
        if not filter_value:
            return True
        if not isinstance(layer, dict):
            return False
        layer_id = layer.get("layer_id")
        if not layer_id:
            return False
        if filter_value == "favorites":
            return layer.get("is_favorite", False)
        if filter_value == "markers":
            return layer_id in MARKER_LAYER_IDS
        if filter_value == "search_areas":
            return layer_id in SEARCH_AREA_LAYER_IDS
        if filter_value == "lines":
            return layer_id in LINE_LAYER_IDS
        if filter_value == "range_rings":
            return layer_id in RANGE_RING_LAYER_IDS
        if filter_value == "bearing_lines":
            return layer_id in BEARING_LINE_LAYER_IDS
        if filter_value == "text_labels":
            return layer_id in TEXT_LABEL_LAYER_IDS
        if filter_value == "positions":
            return layer_id in POSITION_LAYER_IDS
        if filter_value == "breadcrumbs":
            return layer_id in TRACK_LAYER_IDS
        return True

    @staticmethod
    def _shape_filtered_groups(groups: List[Dict[str, Any]], filter_value: Optional[str],
                               search_text: str, show_hidden: bool,
                               feature_limit: Optional[int]) -> Tuple[List[Dict[str, Any]], int, int, bool]:
        """
        Pure helper: apply filter/search/show-hidden rules and return shaped groups.

        Returns:
            (filtered_groups, shown_items, total_items, search_active)
        """
        filtered_groups: List[Dict[str, Any]] = []
        total_items = 0
        shown_items = 0
        search_active = bool(search_text)
        search_text = search_text or ""
        max_features = max(1, int(feature_limit or 0)) if isinstance(feature_limit, int) else 300

        for group in groups or []:
            if not isinstance(group, dict):
                print("[LayerConsole] Warning: skipping non-dict group in filtered view")
                continue

            layers = group.get("layers", []) or []
            if not isinstance(layers, list):
                print("[LayerConsole] Warning: skipping group with non-list layers in filtered view")
                continue
            new_layers: List[Dict[str, Any]] = []

            for layer in layers:
                if not isinstance(layer, dict):
                    print("[LayerConsole] Warning: skipping non-dict layer in filtered view")
                    continue
                features = layer.get("features", []) or []
                if not isinstance(features, list):
                    print("[LayerConsole] Warning: features payload is not list, coercing to empty")
                    features = []
                if max_features and len(features) > max_features:
                    features = features[:max_features]
                feature_count = max(layer.get("feature_count", 0), len(features))

                if not LayerConsoleWidget._layer_matches_type_filter_static(layer, filter_value):
                    continue

                if filter_value in (None, "favorites"):
                    if not show_hidden and not layer.get("is_visible", True):
                        continue

                layer_name = layer.get("display_name") or layer.get("name", "")
                layer_matches_search = LayerConsoleWidget._matches_search_static(layer_name, search_text)

                filtered_features = features
                if search_text:
                    filtered_features = [
                        f for f in features
                        if LayerConsoleWidget._matches_search_static(f.get("name") or f.get("id", ""), search_text)
                        or LayerConsoleWidget._matches_search_static(str(f.get("business_id", "")), search_text)
                        or LayerConsoleWidget._matches_search_static(str(f.get("type", "")), search_text)
                    ]

                if search_text and not layer_matches_search and not filtered_features:
                    continue

                layer_copy = dict(layer)
                layer_copy["features"] = filtered_features

                if search_text and not layer_matches_search:
                    layer_copy["display_feature_count"] = len(filtered_features)
                else:
                    layer_copy["display_feature_count"] = layer_copy.get("feature_count", 0)

                new_layers.append(layer_copy)
                displayed_features = len(filtered_features) if search_active else len(features)
                shown_items += 1 + displayed_features
                total_items += 1 + feature_count

            if new_layers:
                new_group = dict(group)
                new_group["layers"] = new_layers
                filtered_groups.append(new_group)

        return filtered_groups, shown_items, total_items, search_active

    def _has_group_structure_changed(self, group_item: QTreeWidgetItem, group_data: Dict[str, Any]) -> bool:
        """Detect add/remove layer or feature changes requiring rebuild."""
        layers = group_data.get("layers", []) or []
        expected_layer_ids = [layer.get("layer_id") for layer in layers if layer.get("layer_id")]

        # Compare layer count and ordering
        existing_layer_ids = []
        for i in range(group_item.childCount()):
            meta = self._get_item_metadata(group_item.child(i))
            if meta and meta.get("type") == "layer":
                existing_layer_ids.append(meta.get("layer_id"))

        if existing_layer_ids != expected_layer_ids:
            return True

        # Compare feature lists per layer
        layer_lookup = {layer.get("layer_id"): layer for layer in layers}
        for i in range(group_item.childCount()):
            layer_item = group_item.child(i)
            meta = self._get_item_metadata(layer_item)
            if not meta or meta.get("type") != "layer":
                continue
            layer_id = meta.get("layer_id")
            layer_data = layer_lookup.get(layer_id, {})
            features = layer_data.get("features", []) or []

            # Skip non-feature children (e.g., notice rows) when comparing
            feature_children = [
                child for child in (layer_item.child(j) for j in range(layer_item.childCount()))
                if self._get_item_metadata(child) and self._get_item_metadata(child).get("type") == "feature"
            ]
            if len(feature_children) != len(features):
                return True

            existing_ids = [
                str(self._preferred_id(*self._extract_ids(self._get_item_metadata(child))))
                for child in feature_children
            ]
            incoming_ids = [
                str(self._preferred_id(f.get("feature_id", f.get("id")), f.get("business_id")))
                for f in features
            ]
            if existing_ids != incoming_ids:
                return True

        return False

    # ------------------------------------------------------------------ Internal helpers
    def _set_item_check_state(self, item: QTreeWidgetItem, state: int):
        """Set check state without emitting itemChanged feedback."""
        if not item:
            return
        self._suppress_item_changed = True
        try:
            item.setCheckState(0, state)
        finally:
            self._suppress_item_changed = False

    def _emit_layer_visibility(self, layer_id: Optional[str], visible: bool, item: Optional[QTreeWidgetItem] = None):
        """Emit both Phase 4 and legacy visibility signals and update UI state."""
        if not layer_id or self._cleanup_in_progress:
            return
        if item:
            self._set_item_check_state(item, Checked if visible else Unchecked)
            meta = self._get_item_metadata(item) or {}
            meta["is_visible"] = visible
            item.setData(0, UserRole, meta)
        self.visibility_toggled.emit(layer_id, visible)
        self.layer_visibility_toggled.emit(layer_id, visible)
