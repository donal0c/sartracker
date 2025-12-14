# -*- coding: utf-8 -*-
"""
Marker Log Widget

Displays a searchable list of mission markers with quick actions
for zooming, editing, and deleting entries.

Qt5/Qt6 Compatible: Uses qgis.PyQt imports and qt_compat helpers.
"""

from typing import Callable, Dict, List, Optional

from qgis.PyQt.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QLabel,
    QComboBox, QPushButton, QTreeWidget, QTreeWidgetItem, QTextEdit
)
from qgis.PyQt.QtCore import pyqtSignal

from ..utils.qt_compat import AlignLeft, UserRole


class MarkerLogWidget(QWidget):
    """
    Lightweight marker log with filtering and actions.

    Signals:
        edit_requested(str marker_type, str marker_id)
        delete_requested(str marker_type, str marker_id)
        zoom_requested(float lat, float lon)
        open_attachment_requested(str attachment_path)
        refresh_requested()
    """

    edit_requested = pyqtSignal(str, str)
    delete_requested = pyqtSignal(str, str)
    zoom_requested = pyqtSignal(float, float)
    open_attachment_requested = pyqtSignal(str)
    refresh_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._data_fetcher: Optional[Callable[[], List[Dict[str, object]]]] = None
        self._records: List[Dict[str, object]] = []
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        # Filter controls
        filter_layout = QHBoxLayout()
        filter_layout.addWidget(QLabel("Type:"))
        self.type_filter = QComboBox()
        self.type_filter.addItem("All", None)
        self.type_filter.addItem("IPP/LKP", "ipp_lkp")
        self.type_filter.addItem("Clues", "clue")
        self.type_filter.addItem("Hazards", "hazard")
        self.type_filter.addItem("Casualties", "casualty")
        self.type_filter.currentIndexChanged.connect(self._apply_filters)
        filter_layout.addWidget(self.type_filter)

        filter_layout.addStretch()
        layout.addLayout(filter_layout)

        # Table
        self.table = QTreeWidget()
        self.table.setColumnCount(6)
        self.table.setHeaderLabels(["Type", "Name", "Description", "Created", "Updated", "Coordinates"])
        self.table.setAlternatingRowColors(True)
        self.table.itemSelectionChanged.connect(self._update_button_state)
        self.table.itemDoubleClicked.connect(self._emit_edit_from_item)
        layout.addWidget(self.table)

        # Detail pane
        detail_group = QGroupBox("Details")
        detail_layout = QVBoxLayout()
        self.detail_text = QTextEdit()
        self.detail_text.setReadOnly(True)
        detail_layout.addWidget(self.detail_text)
        detail_group.setLayout(detail_layout)
        layout.addWidget(detail_group)

        # Action buttons
        button_layout = QHBoxLayout()
        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.clicked.connect(self.refresh)
        button_layout.addWidget(self.refresh_button)

        button_layout.addStretch()

        self.zoom_button = QPushButton("Zoom")
        self.zoom_button.clicked.connect(self._emit_zoom)
        button_layout.addWidget(self.zoom_button)

        self.open_attachment_button = QPushButton("Open Attachment")
        self.open_attachment_button.clicked.connect(self._emit_open_attachment)
        button_layout.addWidget(self.open_attachment_button)

        self.edit_button = QPushButton("Edit")
        self.edit_button.clicked.connect(self._emit_edit)
        button_layout.addWidget(self.edit_button)

        self.delete_button = QPushButton("Delete")
        self.delete_button.clicked.connect(self._emit_delete)
        button_layout.addWidget(self.delete_button)

        layout.addLayout(button_layout)

        # Status label
        self.status_label = QLabel("Markers: 0")
        self.status_label.setAlignment(AlignLeft)
        layout.addWidget(self.status_label)

        self.setLayout(layout)
        self._update_button_state()

    def set_data_fetcher(self, fetcher: Callable[[], List[Dict[str, object]]]):
        """Provide callable used to populate the log."""
        self._data_fetcher = fetcher

    def refresh(self):
        """Refresh table contents."""
        if not self._data_fetcher:
            self.refresh_requested.emit()
            return

        try:
            self._records = self._data_fetcher() or []
        except Exception as exc:
            print(f"[MarkerLogWidget] Warning: Failed to fetch markers: {exc}")
            self._records = []

        self._apply_filters()

    def _apply_filters(self):
        """Apply type filter to underlying records."""
        self.table.clear()
        selected_type = self.type_filter.currentData()

        filtered = [
            record for record in self._records
            if selected_type is None or record.get("type") == selected_type
        ]

        for record in filtered:
            description = record.get("description") or ""
            coords = ""
            lat = record.get("lat")
            lon = record.get("lon")
            if lat is not None and lon is not None:
                coords = f"{lat:.5f}, {lon:.5f}"

            item = QTreeWidgetItem([
                record.get("type", "").title(),
                record.get("name", ""),
                description[:80],
                record.get("created_at") or record.get("created") or "",
                record.get("updated_at") or "",
                coords
            ])
            item.setData(0, UserRole, record)
            self.table.addTopLevelItem(item)

        self.table.resizeColumnToContents(0)
        self.table.resizeColumnToContents(1)
        self.table.resizeColumnToContents(3)
        self.status_label.setText(f"Markers: {len(filtered)}")
        self._update_button_state()
        self.detail_text.clear()

    def _selected_record(self) -> Optional[Dict[str, object]]:
        selected_items = self.table.selectedItems()
        if not selected_items:
            return None
        return selected_items[0].data(0, UserRole)

    def _update_button_state(self):
        """Enable/disable action buttons based on selection."""
        record = self._selected_record()
        enabled = record is not None
        self.edit_button.setEnabled(enabled)
        self.delete_button.setEnabled(enabled)
        self.zoom_button.setEnabled(enabled and record.get("lat") is not None and record.get("lon") is not None)
        self.open_attachment_button.setEnabled(enabled and bool(record.get("attachment_path")))

        if record:
            details = [
                f"Name: {record.get('name', '')}",
                f"Type: {record.get('type', '')}",
                f"Description: {record.get('description') or ''}",
                f"Created: {record.get('created_at') or record.get('created')}",
                f"Updated: {record.get('updated_at') or ''}",
                f"Updated By: {record.get('updated_by') or ''}",
                f"Coordinators: {record.get('coordinator_ids') or ''}",
                f"Attachment: {record.get('attachment_path') or ''}"
            ]
            self.detail_text.setPlainText("\n".join(details))
        else:
            self.detail_text.clear()

    def _emit_edit_from_item(self, item: QTreeWidgetItem):
        record = item.data(0, UserRole)
        if record:
            # Ensure str values (signal expects str, str)
            marker_type = record.get("type") or ""
            marker_id = record.get("id") or ""
            if marker_type and marker_id:
                self.edit_requested.emit(marker_type, marker_id)

    def _emit_edit(self):
        record = self._selected_record()
        if record:
            # Ensure str values (signal expects str, str)
            marker_type = record.get("type") or ""
            marker_id = record.get("id") or ""
            if marker_type and marker_id:
                self.edit_requested.emit(marker_type, marker_id)

    def _emit_delete(self):
        record = self._selected_record()
        if record:
            # Ensure str values (signal expects str, str)
            marker_type = record.get("type") or ""
            marker_id = record.get("id") or ""
            if marker_type and marker_id:
                self.delete_requested.emit(marker_type, marker_id)

    def _emit_zoom(self):
        record = self._selected_record()
        if record and record.get("lat") is not None and record.get("lon") is not None:
            self.zoom_requested.emit(record["lat"], record["lon"])

    def _emit_open_attachment(self):
        record = self._selected_record()
        if record and record.get("attachment_path"):
            self.open_attachment_requested.emit(record["attachment_path"])

    def cleanup(self):
        """
        Clean up internal resources and signal connections.

        Called during plugin unload to ensure no signal leaks.
        Disconnects all internal widget signals before destruction.
        """
        try:
            # Disconnect internal signal connections
            try:
                self.type_filter.currentIndexChanged.disconnect(self._apply_filters)
            except (TypeError, RuntimeError):
                pass
            try:
                self.table.itemSelectionChanged.disconnect(self._update_button_state)
            except (TypeError, RuntimeError):
                pass
            try:
                self.table.itemDoubleClicked.disconnect(self._emit_edit_from_item)
            except (TypeError, RuntimeError):
                pass
            try:
                self.refresh_button.clicked.disconnect(self.refresh)
            except (TypeError, RuntimeError):
                pass
            try:
                self.zoom_button.clicked.disconnect(self._emit_zoom)
            except (TypeError, RuntimeError):
                pass
            try:
                self.open_attachment_button.clicked.disconnect(self._emit_open_attachment)
            except (TypeError, RuntimeError):
                pass
            try:
                self.edit_button.clicked.disconnect(self._emit_edit)
            except (TypeError, RuntimeError):
                pass
            try:
                self.delete_button.clicked.disconnect(self._emit_delete)
            except (TypeError, RuntimeError):
                pass

            # Clear data references
            self._data_fetcher = None
            self._records = []
        except Exception as exc:
            print(f"[MarkerLogWidget] Warning: Error during cleanup: {exc}")
