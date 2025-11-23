# -*- coding: utf-8 -*-
"""
Layer Console Widget (Phase 3)

Hierarchical console for mission layers with visibility toggles,
context actions, and bulk operations. Presentation-only: emits signals
for SARPanel/LayersController to handle.
"""

from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from qgis.PyQt.QtCore import Qt, QSettings, pyqtSignal
from qgis.PyQt.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QToolButton,
    QTreeWidget, QTreeWidgetItem, QPushButton, QMenu, QLineEdit
)

from ..config.keys import SETTINGS_KEYS
from ..utils.dialog_utils import BaseDialog
from ..utils.qt_compat import (
    Checked, Unchecked,
    ItemIsUserCheckable, ItemIsEnabled, ItemIsSelectable,
    dialog_exec, DialogAccepted
)


class LayerConsoleWidget(QWidget):
    """
    CalTopo-style layer console (presentation layer).

    Signals:
        layer_selected(str layer_id, object feature_id)
        layer_visibility_toggled(str layer_id, bool visible)
        layer_rename_requested(str layer_id, object feature_id, str new_name)
        layer_delete_requested(str layer_id, object feature_id)
        layer_zoom_requested(str layer_id, object feature_id)
        layer_export_requested(str layer_id, object feature_id)
        layer_duplicate_requested(str layer_id, object feature_id)
        bulk_delete_requested(str layer_id, list feature_ids)
        bulk_assign_team_requested(str layer_id, list feature_ids, str team)
        bulk_export_requested(str layer_id, list feature_ids)
        reorder_requested(str layer_id, list feature_ids_in_order)
        refresh_requested()
    """

    layer_selected = pyqtSignal(str, object)
    layer_visibility_toggled = pyqtSignal(str, bool)
    layer_rename_requested = pyqtSignal(str, object, str)
    layer_delete_requested = pyqtSignal(str, object)
    layer_zoom_requested = pyqtSignal(str, object)
    layer_export_requested = pyqtSignal(str, object)
    layer_duplicate_requested = pyqtSignal(str, object)
    bulk_delete_requested = pyqtSignal(str, list)
    bulk_assign_team_requested = pyqtSignal(str, list, str)
    bulk_export_requested = pyqtSignal(str, list)
    reorder_requested = pyqtSignal(str, list)
    refresh_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._catalog_fetcher: Optional[Callable[[], Dict[str, Any]]] = None
        self._catalog_data: Dict[str, Any] = {}
        self._expanded_groups: Set[str] = set()
        self._selected_layer_id: Optional[str] = None
        self._selected_feature_ids: List[object] = []
        self._selected_business_ids: List[object] = []
        self._pending_selection: Optional[Tuple[str, object]] = None

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
        self.filter_combo.addItem("All Layers", None)
        self.filter_combo.addItem("Favorites ⭐", "favorites")
        self.filter_combo.currentIndexChanged.connect(self._apply_filter)
        filter_layout.addWidget(self.filter_combo)

        self.refresh_button = QToolButton()
        self.refresh_button.setText("Refresh")
        self.refresh_button.clicked.connect(self._on_refresh_clicked)
        filter_layout.addWidget(self.refresh_button)

        filter_layout.addStretch()
        layout.addLayout(filter_layout)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Layer / Feature", "Count", "Type", "Updated"])
        self.tree.setColumnWidth(0, 280)
        self.tree.setColumnWidth(1, 60)
        self.tree.setColumnWidth(2, 120)
        self.tree.setAlternatingRowColors(True)
        self.tree.setSelectionMode(self.tree.ExtendedSelection)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.itemSelectionChanged.connect(self._on_selection_changed)
        self.tree.itemChanged.connect(self._on_item_changed)
        self.tree.itemDoubleClicked.connect(self._on_item_double_clicked)
        self.tree.customContextMenuRequested.connect(self._show_context_menu)
        layout.addWidget(self.tree)

        bulk_layout = QHBoxLayout()
        self.bulk_label = QLabel("0 selected")
        bulk_layout.addWidget(self.bulk_label)

        self.bulk_delete_button = QPushButton("Delete Selected")
        self.bulk_delete_button.clicked.connect(self._on_bulk_delete)
        self.bulk_delete_button.setEnabled(False)
        bulk_layout.addWidget(self.bulk_delete_button)

        self.bulk_export_button = QPushButton("Export Selected")
        self.bulk_export_button.clicked.connect(self._on_bulk_export)
        self.bulk_export_button.setEnabled(False)
        bulk_layout.addWidget(self.bulk_export_button)

        self.bulk_team_button = QPushButton("Assign Team")
        self.bulk_team_button.clicked.connect(self._on_bulk_assign_team)
        self.bulk_team_button.setEnabled(False)
        bulk_layout.addWidget(self.bulk_team_button)

        bulk_layout.addStretch()
        layout.addLayout(bulk_layout)

        self.setLayout(layout)

    # ------------------------------------------------------------------ Data
    def set_catalog_fetcher(self, fetcher: Callable[[], Dict[str, Any]]):
        """Provide callable that returns catalog data."""
        self._catalog_fetcher = fetcher

    def refresh(self, full: bool = True):
        """Refresh tree from catalog data."""
        if not self._catalog_fetcher:
            self.refresh_requested.emit()
            return

        try:
            self._catalog_data = self._catalog_fetcher() or {}
        except Exception as exc:
            print(f"[LayerConsole] Error fetching catalog: {exc}")
            self._catalog_data = {}

        if full:
            self._rebuild_tree()
        else:
            self._update_tree_incremental()

    def _apply_filter(self):
        """Apply current filter and rebuild tree."""
        self._rebuild_tree()

    def _rebuild_tree(self):
        """Rebuild entire tree from catalog data."""
        self._save_expanded_state()
        selection = self._get_selected_items()
        self.tree.clear()

        groups = self._get_filtered_groups(self._catalog_data.get("groups", []))
        self._sync_filter_options(groups)

        for group_data in groups:
            group_item = self._create_group_item(group_data)
            if group_item:
                self.tree.addTopLevelItem(group_item)

        self._restore_expanded_state()
        self._restore_selection(selection)
        self._apply_pending_selection()
        self._update_bulk_bar()
        self._restore_column_widths()

    def _update_tree_incremental(self):
        """
        Lightweight refresh: update counts and visibility without rebuilding.
        Falls back to full rebuild if structure changed.
        """
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

    # ------------------------------------------------------------------ Item creation
    def _create_group_item(self, group_data: Dict[str, Any]) -> Optional[QTreeWidgetItem]:
        group_id = group_data.get("id")
        group_name = group_data.get("name", "Group")
        layers = group_data.get("layers", []) or []
        if not layers:
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
        item.setData(0, Qt.UserRole, {
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
        layer_id = layer_data.get("layer_id")
        if not layer_id:
            return None
        layer_name = layer_data.get("display_name") or layer_data.get("name", "Layer")
        feature_count = layer_data.get("feature_count", 0)
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
        item.setData(0, Qt.UserRole, {
            "type": "layer",
            "layer_id": layer_id,
            "layer_name": layer_name,
            "feature_count": feature_count,
            "is_visible": is_visible,
            "is_favorite": is_favorite
        })

        features = layer_data.get("features", []) or []
        for feature_data in features:
            feature_item = self._create_feature_item(feature_data, layer_id)
            if feature_item:
                item.addChild(feature_item)

        # Warn when the catalog count exceeds included features (feature_limit truncation)
        if feature_count > len(features):
            missing = feature_count - len(features)
            notice = QTreeWidgetItem([f"  … {missing} more not shown", "", "", ""])
            notice.setFlags(notice.flags() & ~ItemIsSelectable & ~ItemIsEnabled)
            notice.setData(0, Qt.UserRole, {"type": "notice"})
            item.addChild(notice)

        if features:
            item.setExpanded(True)

        return item

    def _create_feature_item(self, feature_data: Dict[str, Any], layer_id: str) -> Optional[QTreeWidgetItem]:
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
        item.setData(0, Qt.UserRole, {
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
        if item.checkState(0) != (Checked if new_visible else Unchecked):
            item.setCheckState(0, Checked if new_visible else Unchecked)

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
        item.setData(0, Qt.UserRole, metadata)

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
                notice_item.setData(0, Qt.UserRole, {"type": "notice"})
                item.addChild(notice_item)
            else:
                notice_item.setText(0, f"  … {missing} more not shown")
        elif notice_item:
            parent = notice_item.parent()
            if parent:
                parent.removeChild(notice_item)

    # ------------------------------------------------------------------ Selection / actions
    def _on_item_changed(self, item: QTreeWidgetItem, column: int):
        if column != 0:
            return
        metadata = self._get_item_metadata(item)
        if not metadata or metadata.get("type") != "layer":
            return
        layer_id = metadata.get("layer_id")
        if not layer_id:
            return
        is_visible = item.checkState(0) == Checked
        self.layer_visibility_toggled.emit(layer_id, is_visible)

    def _on_selection_changed(self):
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
            self.layer_selected.emit(layer_id, primary_id)

    def _on_item_double_clicked(self, item: QTreeWidgetItem, column: int):
        metadata = self._get_item_metadata(item)
        if not metadata or metadata.get("type") != "feature":
            return
        layer_id = metadata.get("layer_id")
        fid, bid = self._extract_ids(metadata)
        feature_id = self._preferred_id(fid, bid)
        if layer_id and feature_id is not None:
            self.layer_zoom_requested.emit(layer_id, feature_id)

    def _show_context_menu(self, pos):
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
                lambda checked=False, lid=layer_id, fid=feature_id: self.layer_zoom_requested.emit(lid, fid)
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
        elif item_type == "layer":
            layer_id = metadata.get("layer_id")
            is_visible = metadata.get("is_visible", True)
            visibility_text = "👁️ Hide Layer" if is_visible else "👁️ Show Layer"
            visibility_action = menu.addAction(visibility_text)
            visibility_action.triggered.connect(
                lambda checked=False, lid=layer_id, vis=is_visible: self.layer_visibility_toggled.emit(lid, not vis)
            )

        elif item_type == "group":
            expand_action = menu.addAction("📂 Expand")
            expand_action.triggered.connect(lambda: item.setExpanded(True))
            collapse_action = menu.addAction("📁 Collapse")
            collapse_action.triggered.connect(lambda: item.setExpanded(False))

        menu.exec_(self.tree.viewport().mapToGlobal(pos))

    def _start_rename(self, item: QTreeWidgetItem):
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
        item.setText(0, f"  {new_name}")
        metadata["feature_name"] = new_name
        item.setData(0, Qt.UserRole, metadata)
        self.layer_rename_requested.emit(layer_id, feature_id, new_name.strip())

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
        confirmed = self._confirm_action(
            "Confirm Delete",
            "Delete selected feature?",
            "This action cannot be undone."
        )
        if confirmed:
            self.layer_delete_requested.emit(layer_id, feature_id)

    # ------------------------------------------------------------------ Bulk ops
    def _update_bulk_bar(self):
        count = len(self._selected_feature_ids)
        self.bulk_label.setText(f"{count} selected")
        enabled = count > 0 and self._selected_layer_id is not None
        self.bulk_delete_button.setEnabled(enabled)
        self.bulk_export_button.setEnabled(enabled)
        self.bulk_team_button.setEnabled(enabled)

    def _on_bulk_delete(self):
        if not self._selected_layer_id or not self._selected_feature_ids:
            return
        count = len(self._selected_feature_ids)
        confirmed = self._confirm_action(
            "Confirm Bulk Delete",
            f"Delete {count} features?",
            "This will permanently delete the selected features."
        )
        if not confirmed:
            return
        self.bulk_delete_requested.emit(self._selected_layer_id, list(self._selected_feature_ids))

    def _on_bulk_export(self):
        if not self._selected_layer_id or not self._selected_feature_ids:
            return
        self.bulk_export_requested.emit(self._selected_layer_id, list(self._selected_feature_ids))

    def _on_bulk_assign_team(self):
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
    def _on_refresh_clicked(self):
        self.refresh_requested.emit()
        self.refresh(full=True)

    def _get_item_metadata(self, item: QTreeWidgetItem) -> Optional[Dict[str, Any]]:
        if not item:
            return None
        metadata = item.data(0, Qt.UserRole)
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
        root = self.tree.invisibleRootItem()
        for i in range(root.childCount()):
            group_item = root.child(i)
            for j in range(group_item.childCount()):
                layer_item = group_item.child(j)
                for k in range(layer_item.childCount()):
                    feature_item = layer_item.child(k)
                    meta = self._get_item_metadata(feature_item)
                    if not meta or meta.get("type") != "feature":
                        continue
                    fid, bid = self._extract_ids(meta)
                    preferred = self._preferred_id(fid, bid)
                    lid = meta.get("layer_id")
                    if (lid, preferred) in selection_set:
                        feature_item.setSelected(True)

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

    def _sync_filter_options(self, groups: List[Dict[str, Any]]):
        """Ensure filter combo lists available groups."""
        existing_ids = {self.filter_combo.itemData(i) for i in range(self.filter_combo.count())}
        for group in groups:
            gid = group.get("id")
            name = group.get("name", gid)
            if gid and gid not in existing_ids and gid != "favorites":
                self.filter_combo.addItem(name, gid)
                existing_ids.add(gid)

    def _get_layer_icon(self, layer_id: str) -> str:
        icon_map = {
            "sar_markers_ipp_lkp": "📍",
            "sar_markers_clues": "🔍",
            "sar_markers_hazards": "⚠️",
            "sar_markers_casualties": "🏥",
            "sar_search_areas": "🔳",
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
        settings.setValue(SETTINGS_KEYS.LAYER_CONSOLE_EXPANDED_GROUPS, expanded_str)
        widths = [
            self.tree.columnWidth(0),
            self.tree.columnWidth(1),
            self.tree.columnWidth(2),
            self.tree.columnWidth(3)
        ]
        settings.setValue(
            SETTINGS_KEYS.LAYER_CONSOLE_COLUMN_WIDTHS,
            ",".join(str(w) for w in widths)
        )
        settings.setValue(SETTINGS_KEYS.LAYER_CONSOLE_FILTER_STATE, self.filter_combo.currentIndex())
        settings.setValue(SETTINGS_KEYS.LAYER_CONSOLE_SELECTED_LAYER, self._selected_layer_id or "")
        selected_first = self._selected_feature_ids[0] if self._selected_feature_ids else ""
        settings.setValue(SETTINGS_KEYS.LAYER_CONSOLE_SELECTED_FEATURE, selected_first)

    def _load_settings(self):
        settings = QSettings()
        expanded = settings.value(SETTINGS_KEYS.LAYER_CONSOLE_EXPANDED_GROUPS, "")
        if expanded:
            self._expanded_groups = set(str(expanded).split(","))
        try:
            filter_index = int(settings.value(SETTINGS_KEYS.LAYER_CONSOLE_FILTER_STATE, 0))
            if 0 <= filter_index < self.filter_combo.count():
                self.filter_combo.setCurrentIndex(filter_index)
        except Exception:
            pass
        saved_layer = settings.value(SETTINGS_KEYS.LAYER_CONSOLE_SELECTED_LAYER, "")
        saved_feature = settings.value(SETTINGS_KEYS.LAYER_CONSOLE_SELECTED_FEATURE, "")
        if saved_layer:
            self._pending_selection = (str(saved_layer), saved_feature if saved_feature != "" else None)
        self._restore_column_widths()

    def _restore_column_widths(self):
        settings = QSettings()
        widths = settings.value(SETTINGS_KEYS.LAYER_CONSOLE_COLUMN_WIDTHS, "")
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

        try:
            self._save_expanded_state()
            self._save_settings()
        except Exception as exc:
            print(f"[LayerConsole] Warning: failed to save settings: {exc}")

        # CRITICAL: Block ALL signals during cleanup to prevent crashes
        try:
            self.blockSignals(True)
            self.filter_combo.blockSignals(True)
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

        # Now safely disconnect all signals
        try:
            self.filter_combo.currentIndexChanged.disconnect()
        except (TypeError, RuntimeError):
            pass

        try:
            self.refresh_button.clicked.disconnect()
        except (TypeError, RuntimeError):
            pass

        try:
            self.tree.itemSelectionChanged.disconnect()
            self.tree.itemChanged.disconnect()
            self.tree.itemDoubleClicked.disconnect()
            self.tree.customContextMenuRequested.disconnect()
        except (TypeError, RuntimeError):
            pass

        try:
            self.bulk_delete_button.clicked.disconnect()
            self.bulk_export_button.clicked.disconnect()
            self.bulk_team_button.clicked.disconnect()
        except (TypeError, RuntimeError):
            pass

        # Release references
        self._catalog_fetcher = None
        self._catalog_data = {}
        self._selected_feature_ids = []
        self._selected_layer_id = None
        self._selected_business_ids = []

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
    def _extract_ids(self, meta: Dict[str, Any]) -> Tuple[object, object]:
        """Return (feature_id, business_id) from item metadata with None-safe defaults."""
        return meta.get("feature_id"), meta.get("business_id")

    def _preferred_id(self, feature_id: object, business_id: object) -> Optional[object]:
        """Prefer business_id when present; otherwise use feature_id (even if 0)."""
        if business_id is not None:
            return business_id
        return feature_id

    def _get_filtered_groups(self, groups: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Apply current filter to catalog groups."""
        filter_value = self.filter_combo.currentData()
        if filter_value == "favorites":
            return self._filter_favorites(groups)
        if filter_value:
            return [g for g in groups if g.get("id") == filter_value]
        return groups

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
