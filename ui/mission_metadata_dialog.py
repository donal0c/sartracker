# -*- coding: utf-8 -*-
"""
Mission Metadata Dialog

Collects coordinators on mission start/resume and optionally allows
operators to set a custom resume timestamp.
"""

from typing import List, Optional
from qgis.PyQt.QtWidgets import (
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QLineEdit,
    QPushButton,
    QDialogButtonBox,
    QDateTimeEdit
)
from qgis.PyQt.QtCore import Qt, QDateTime

from ..utils.dialog_utils import BaseDialog


class MissionMetadataDialog(BaseDialog):
    """
    Collect coordinator selection and optional resume timestamp.

    Args:
        coordinators: Known coordinator roster.
        mode: "start" or "resume" (affects copy).
        allow_resume_time: Whether to show resume timestamp field.
        preselected: Coordinators to pre-select.
    """

    def __init__(
        self,
        coordinators: List[str],
        mode: str = "start",
        allow_resume_time: bool = False,
        preselected: Optional[List[str]] = None,
        parent=None
    ):
        super().__init__(parent)
        self._coordinators = coordinators or []
        self._allow_resume_time = allow_resume_time
        self._preselected = set(preselected or [])

        self.setWindowTitle("Mission Coordinators")
        self.setMinimumWidth(420)
        self._build_ui(mode)

    # ------------------------------------------------------------------#
    # UI
    # ------------------------------------------------------------------#
    def _build_ui(self, mode: str):
        layout = QVBoxLayout()

        intro = "Select on-duty coordinators for this mission."
        if mode == "resume":
            intro = "Confirm coordinators and optional resume timestamp."
        layout.addWidget(QLabel(intro))

        self.roster_list = QListWidget()
        for name in self._coordinators:
            item = QListWidgetItem(name)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if name in self._preselected else Qt.Unchecked)
            self.roster_list.addItem(item)
        # If nothing preselected, default all to checked so operators don't have to tick each entry
        if self.roster_list.count() > 0:
            has_checked = any(self.roster_list.item(i).checkState() == Qt.Checked for i in range(self.roster_list.count()))
            if not has_checked:
                for i in range(self.roster_list.count()):
                    self.roster_list.item(i).setCheckState(Qt.Checked)
        layout.addWidget(self.roster_list)

        add_layout = QHBoxLayout()
        self.new_coordinator_input = QLineEdit()
        self.new_coordinator_input.setPlaceholderText("Add coordinator name")
        add_layout.addWidget(self.new_coordinator_input)
        add_button = QPushButton("Add")
        add_button.clicked.connect(self._add_new_coordinator)
        add_layout.addWidget(add_button)
        layout.addLayout(add_layout)

        self.resume_time_edit = None
        if self._allow_resume_time:
            layout.addWidget(QLabel("Custom resume timestamp (optional):"))
            self.resume_time_edit = QDateTimeEdit(QDateTime.currentDateTime())
            self.resume_time_edit.setCalendarPopup(True)
            layout.addWidget(self.resume_time_edit)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.setLayout(layout)

    # ------------------------------------------------------------------#
    # Helpers
    # ------------------------------------------------------------------#
    def _add_new_coordinator(self):
        name = self.new_coordinator_input.text().strip()
        if not name:
            return
        self.new_coordinator_input.clear()

        item = QListWidgetItem(name)
        item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
        item.setCheckState(Qt.Checked)
        self.roster_list.addItem(item)

    def selected_coordinators(self) -> List[str]:
        names: List[str] = []
        for i in range(self.roster_list.count()):
            item = self.roster_list.item(i)
            if item.checkState() == Qt.Checked:
                text = item.text().strip()
                if text:
                    names.append(text)
        # If nothing checked but user selected rows, treat selected rows as chosen
        if not names:
            for item in self.roster_list.selectedItems():
                text = item.text().strip()
                if text and text not in names:
                    names.append(text)
        return names

    def pending_entry(self) -> Optional[str]:
        """Return text entered but not added to the list yet."""
        text = self.new_coordinator_input.text().strip()
        return text or None

    def all_entries(self) -> List[str]:
        """Return all coordinator names currently in the list (checked or not)."""
        names: List[str] = []
        for i in range(self.roster_list.count()):
            text = self.roster_list.item(i).text().strip()
            if text and text not in names:
                names.append(text)
        return names

    def updated_roster(self) -> List[str]:
        roster: List[str] = []
        for i in range(self.roster_list.count()):
            text = self.roster_list.item(i).text().strip()
            if text and text not in roster:
                roster.append(text)
        return roster

    def resume_timestamp(self) -> Optional[QDateTime]:
        if not self.resume_time_edit:
            return None
        return self.resume_time_edit.dateTime()
