# -*- coding: utf-8 -*-
"""
Focus Mode Plus state management.

Handles capture and restoration of QGIS UI element visibility
for Focus Mode Plus feature. Designed for safety with multiple
fallback mechanisms.

SAFETY CRITICAL: This module manages UI state that must be
restored even after crashes or unexpected exits.

Usage:
    from utils.focus_mode_state import (
        FocusModePlusState,
        FocusModeStateFile,
        find_layers_dock_widget
    )

    # Capture and hide
    state = FocusModePlusState()
    state.capture(main_window)
    FocusModeStateFile.save(state)
    state.apply_hide(main_window)

    # Restore
    state.restore(main_window)
    FocusModeStateFile.delete()
"""

import base64
import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Tuple, Optional, Dict, Any

from qgis.PyQt.QtCore import QByteArray
from qgis.PyQt.QtWidgets import QDockWidget, QToolBar, QMainWindow

# Import sip_isdeleted from qt_compat to avoid duplication
from .qt_compat import sip_isdeleted


def find_layers_dock_widget(iface) -> Optional[QDockWidget]:
    """
    Reliably find the Layers panel dock widget across QGIS versions.

    Uses multiple strategies:
    1. Traverse from iface.layerTreeView() to parent QDockWidget (primary)
    2. Search dock widgets for one containing theLayerTreeView widget (fallback)

    Args:
        iface: QGIS interface object

    Returns:
        QDockWidget or None: The Layers panel dock widget

    Note:
        This works across QGIS 3.28-3.44+ and Qt5/Qt6.
    """
    if iface is None:
        return None

    # Strategy 1: Traverse from layerTreeView
    try:
        layer_tree_view = iface.layerTreeView()
        if layer_tree_view and not sip_isdeleted(layer_tree_view):
            parent = layer_tree_view.parent()
            depth = 0
            while parent and depth < 20:
                if sip_isdeleted(parent):
                    break
                if isinstance(parent, QDockWidget):
                    return parent
                parent = parent.parent()
                depth += 1
    except Exception as e:
        print(f"[FocusModePlus] Strategy 1 (parent traversal) failed: {e}")

    # Strategy 2: Search by widget object name
    try:
        main_window = iface.mainWindow()
        if main_window and not sip_isdeleted(main_window):
            for dock in main_window.findChildren(QDockWidget):
                if sip_isdeleted(dock):
                    continue
                try:
                    widget = dock.widget()
                    if widget and not sip_isdeleted(widget):
                        if widget.objectName() == "theLayerTreeView":
                            return dock
                except Exception:
                    continue
    except Exception as e:
        print(f"[FocusModePlus] Strategy 2 (widget search) failed: {e}")

    # Not found
    return None


def is_layers_dock(dock: QDockWidget, iface) -> bool:
    """
    Check if a given dock widget is the Layers panel.

    Args:
        dock: QDockWidget to check
        iface: QGIS interface object

    Returns:
        bool: True if this is the Layers panel
    """
    if not dock or not isinstance(dock, QDockWidget):
        return False

    if sip_isdeleted(dock):
        return False

    # Check if this dock is the layers dock
    layers_dock = find_layers_dock_widget(iface)
    if layers_dock and dock is layers_dock:
        return True

    # Fallback: check widget object name
    try:
        widget = dock.widget()
        if widget and not sip_isdeleted(widget):
            if widget.objectName() == "theLayerTreeView":
                return True
    except Exception:
        pass

    return False


@dataclass
class FocusModePlusState:
    """
    Captures QGIS UI state before entering Focus Mode Plus.

    Stores references to hidden elements for restoration.
    Can serialize to dict for file-based crash recovery.

    Attributes:
        is_active: Whether Focus Mode Plus is currently active
        menu_bar_was_visible: Whether menu bar was visible before hiding
        status_bar_was_visible: Whether status bar was visible before hiding
        hidden_docks: List of (name, dock) tuples for hidden dock widgets
        hidden_toolbars: List of (name, toolbar) tuples for hidden toolbars
        hidden_dock_names: List of dock object names (for serialization)
        hidden_toolbar_names: List of toolbar object names (for serialization)
        main_window_state: Base64-encoded main window state (QMainWindow.saveState)
        keep_visible_docks: List of dock object names to keep visible
    """

    is_active: bool = False

    # UI element states
    menu_bar_was_visible: bool = True
    status_bar_was_visible: bool = True

    # References to hidden elements (runtime only, not serialized)
    hidden_docks: List[Tuple[str, QDockWidget]] = field(default_factory=list)
    hidden_toolbars: List[Tuple[str, QToolBar]] = field(default_factory=list)

    # Names for serialization/recovery
    hidden_dock_names: List[str] = field(default_factory=list)
    hidden_toolbar_names: List[str] = field(default_factory=list)

    # Full main window state (QMainWindow.saveState) for exact restoration
    main_window_state: Optional[str] = None

    # Panels to keep visible (by objectName)
    keep_visible_docks: List[str] = field(default_factory=lambda: [
        "SARTrackerDock",      # SAR Panel
        "Layers",              # Layers panel (common name)
        "LayerTreeDock",       # Layers panel (alternative name)
    ])

    @staticmethod
    def _encode_main_window_state(state_obj: Any) -> Optional[str]:
        """Encode QMainWindow.saveState() output as base64 string."""
        if state_obj is None:
            return None
        try:
            if isinstance(state_obj, QByteArray):
                raw_bytes = bytes(state_obj.toBase64())
            elif isinstance(state_obj, (bytes, bytearray)):
                raw_bytes = base64.b64encode(bytes(state_obj))
            elif hasattr(state_obj, "toBase64"):
                raw_bytes = bytes(state_obj.toBase64())
            else:
                return None
            return raw_bytes.decode("ascii")
        except Exception as e:
            print(f"[FocusModePlus] Failed to encode window state: {e}")
            return None

    @staticmethod
    def _decode_main_window_state(state_b64: Optional[str]) -> Optional[QByteArray]:
        """Decode base64 window state into QByteArray for restoreState."""
        if not state_b64:
            return None
        try:
            if isinstance(state_b64, bytes):
                return QByteArray.fromBase64(state_b64)
            return QByteArray.fromBase64(state_b64.encode("ascii"))
        except Exception as e:
            print(f"[FocusModePlus] Failed to decode window state: {e}")
            return None

    def capture(self, main_window: QMainWindow, iface=None) -> int:
        """
        Capture current UI state before entering Focus Mode Plus.

        Args:
            main_window: QGIS main window
            iface: Optional QGIS interface for Layers panel detection

        Returns:
            Number of elements that will be hidden
        """
        if self.is_active:
            return 0

        # Validate main_window before proceeding
        if main_window is None or sip_isdeleted(main_window):
            print("[FocusModePlus] main_window is None or deleted, cannot capture")
            return 0

        hidden_count = 0

        # Find layers dock for exclusion
        layers_dock = find_layers_dock_widget(iface) if iface else None

        # Capture full main window state (for exact restoration)
        try:
            if hasattr(main_window, "saveState"):
                state_obj = main_window.saveState()
                self.main_window_state = self._encode_main_window_state(state_obj)
        except Exception as e:
            print(f"[FocusModePlus] Error capturing main window state: {e}")

        # Capture menu bar state
        try:
            menu_bar = main_window.menuBar()
            if menu_bar and not sip_isdeleted(menu_bar):
                self.menu_bar_was_visible = menu_bar.isVisible()
                if self.menu_bar_was_visible:
                    hidden_count += 1
        except Exception as e:
            print(f"[FocusModePlus] Error capturing menu bar state: {e}")

        # Capture status bar state
        try:
            status_bar = main_window.statusBar()
            if status_bar and not sip_isdeleted(status_bar):
                self.status_bar_was_visible = status_bar.isVisible()
                if self.status_bar_was_visible:
                    hidden_count += 1
        except Exception as e:
            print(f"[FocusModePlus] Error capturing status bar state: {e}")

        # Capture dock widgets
        self.hidden_docks = []
        self.hidden_dock_names = []
        try:
            for dock in main_window.findChildren(QDockWidget):
                if sip_isdeleted(dock):
                    continue
                obj_name = dock.objectName()

                # Skip docks in keep_visible list
                if obj_name in self.keep_visible_docks:
                    continue

                # Skip layers dock (identified dynamically)
                if layers_dock and dock is layers_dock:
                    continue

                if dock.isVisible():
                    self.hidden_docks.append((obj_name, dock))
                    self.hidden_dock_names.append(obj_name)
                    hidden_count += 1
        except Exception as e:
            print(f"[FocusModePlus] Error capturing dock states: {e}")

        # Capture toolbars
        self.hidden_toolbars = []
        self.hidden_toolbar_names = []
        try:
            for toolbar in main_window.findChildren(QToolBar):
                if sip_isdeleted(toolbar):
                    continue
                if toolbar.isVisible():
                    obj_name = toolbar.objectName()
                    self.hidden_toolbars.append((obj_name, toolbar))
                    self.hidden_toolbar_names.append(obj_name)
                    hidden_count += 1
        except Exception as e:
            print(f"[FocusModePlus] Error capturing toolbar states: {e}")

        # Only mark as active after successful capture
        self.is_active = True

        return hidden_count

    def apply_hide(self, main_window: QMainWindow) -> int:
        """
        Hide captured UI elements.

        Call this AFTER capture() to actually hide elements.
        Separated from capture for clarity and safety.

        Args:
            main_window: QGIS main window

        Returns:
            Number of elements hidden
        """
        if not self.is_active:
            return 0

        # CRITICAL: Validate main_window before accessing its children
        # main_window could be deleted between capture() and apply_hide()
        if main_window is None:
            print("[FocusModePlus] Cannot apply_hide: main_window is None")
            return 0
        if sip_isdeleted(main_window):
            print("[FocusModePlus] Cannot apply_hide: main_window is deleted")
            return 0

        hidden_count = 0

        # Hide menu bar
        try:
            menu_bar = main_window.menuBar()
            if menu_bar and not sip_isdeleted(menu_bar) and self.menu_bar_was_visible:
                menu_bar.setVisible(False)
                hidden_count += 1
        except Exception as e:
            print(f"[FocusModePlus] Error hiding menu bar: {e}")

        # Hide status bar
        try:
            status_bar = main_window.statusBar()
            if status_bar and not sip_isdeleted(status_bar) and self.status_bar_was_visible:
                status_bar.setVisible(False)
                hidden_count += 1
        except Exception as e:
            print(f"[FocusModePlus] Error hiding status bar: {e}")

        # Hide dock widgets
        for obj_name, dock in self.hidden_docks:
            try:
                if dock and not sip_isdeleted(dock):
                    dock.setVisible(False)
                    hidden_count += 1
            except Exception as e:
                print(f"[FocusModePlus] Error hiding dock {obj_name}: {e}")

        # Hide toolbars
        for obj_name, toolbar in self.hidden_toolbars:
            try:
                if toolbar and not sip_isdeleted(toolbar):
                    toolbar.setVisible(False)
                    hidden_count += 1
            except Exception as e:
                print(f"[FocusModePlus] Error hiding toolbar {obj_name}: {e}")

        return hidden_count

    def restore(self, main_window: QMainWindow) -> Tuple[int, int]:
        """
        Restore all hidden UI elements.

        Safe to call multiple times (idempotent).
        Handles deleted Qt objects gracefully.

        Args:
            main_window: QGIS main window

        Returns:
            Tuple of (restored_count, error_count)
        """
        if not self.is_active:
            return (0, 0)

        # Validate main_window - still clear state to prevent stuck focus mode
        if main_window is None or sip_isdeleted(main_window):
            print("[FocusModePlus] main_window is None or deleted during restore")
            self._clear()
            return (0, 1)

        restored_count = 0
        error_count = 0

        # Restore full main window state first (exact layout)
        try:
            if self.main_window_state and hasattr(main_window, "restoreState"):
                restored_state = self._decode_main_window_state(self.main_window_state)
                if restored_state is not None:
                    if not main_window.restoreState(restored_state):
                        print("[FocusModePlus] restoreState reported failure")
        except Exception as e:
            error_count += 1
            print(f"[FocusModePlus] Error restoring main window state: {e}")

        # Restore dock widgets
        for obj_name, dock in self.hidden_docks:
            try:
                if dock and not sip_isdeleted(dock):
                    dock.setVisible(True)
                    restored_count += 1
            except Exception as e:
                error_count += 1
                print(f"[FocusModePlus] Error restoring dock {obj_name}: {e}")

        # Restore toolbars
        for obj_name, toolbar in self.hidden_toolbars:
            try:
                if toolbar and not sip_isdeleted(toolbar):
                    toolbar.setVisible(True)
                    restored_count += 1
            except Exception as e:
                error_count += 1
                print(f"[FocusModePlus] Error restoring toolbar {obj_name}: {e}")

        # Restore status bar
        try:
            status_bar = main_window.statusBar()
            if status_bar and not sip_isdeleted(status_bar) and self.status_bar_was_visible:
                status_bar.setVisible(True)
                restored_count += 1
        except Exception as e:
            error_count += 1
            print(f"[FocusModePlus] Error restoring status bar: {e}")

        # Restore menu bar (LAST - most visible to user)
        try:
            menu_bar = main_window.menuBar()
            if menu_bar and not sip_isdeleted(menu_bar) and self.menu_bar_was_visible:
                menu_bar.setVisible(True)
                restored_count += 1
        except Exception as e:
            error_count += 1
            print(f"[FocusModePlus] Error restoring menu bar: {e}")

        # Clear state
        self._clear()

        return (restored_count, error_count)

    def _clear(self):
        """Reset state to initial values."""
        self.is_active = False
        self.menu_bar_was_visible = True
        self.status_bar_was_visible = True
        self.hidden_docks = []
        self.hidden_toolbars = []
        self.hidden_dock_names = []
        self.hidden_toolbar_names = []
        self.main_window_state = None

    def to_dict(self) -> Dict[str, Any]:
        """Serialize state for file-based persistence."""
        data = {
            "version": 1,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "is_active": self.is_active,
            "menu_bar_was_visible": self.menu_bar_was_visible,
            "status_bar_was_visible": self.status_bar_was_visible,
            "hidden_dock_names": self.hidden_dock_names,
            "hidden_toolbar_names": self.hidden_toolbar_names,
        }
        if self.main_window_state:
            data["main_window_state"] = self.main_window_state
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any], main_window: QMainWindow) -> 'FocusModePlusState':
        """
        Reconstruct state from serialized data (crash recovery).

        Rebuilds object references by looking up widgets by name.

        Args:
            data: Dictionary from to_dict() or loaded from file
            main_window: QGIS main window for widget lookup

        Returns:
            FocusModePlusState instance with restored references
        """
        state = cls()
        state.is_active = data.get("is_active", False)
        state.menu_bar_was_visible = data.get("menu_bar_was_visible", True)
        state.status_bar_was_visible = data.get("status_bar_was_visible", True)
        state.hidden_dock_names = data.get("hidden_dock_names", [])
        state.hidden_toolbar_names = data.get("hidden_toolbar_names", [])
        state.main_window_state = data.get("main_window_state")

        # Rebuild dock references
        if state.is_active and main_window:
            dock_names_set = set(state.hidden_dock_names)
            try:
                for dock in main_window.findChildren(QDockWidget):
                    if not sip_isdeleted(dock) and dock.objectName() in dock_names_set:
                        state.hidden_docks.append((dock.objectName(), dock))
            except Exception as e:
                print(f"[FocusModePlus] Error rebuilding dock references: {e}")

            toolbar_names_set = set(state.hidden_toolbar_names)
            try:
                for toolbar in main_window.findChildren(QToolBar):
                    if not sip_isdeleted(toolbar) and toolbar.objectName() in toolbar_names_set:
                        state.hidden_toolbars.append((toolbar.objectName(), toolbar))
            except Exception as e:
                print(f"[FocusModePlus] Error rebuilding toolbar references: {e}")

        return state


class FocusModeStateFile:
    """
    File-based state persistence for crash recovery.

    Writes state to a JSON file when entering Focus Mode Plus.
    File is deleted on clean exit. If file exists on plugin load,
    indicates a crash occurred while Focus Mode Plus was active.
    """

    _STATE_FILE_NAME = "sartracker_focus_mode_state.json"

    @classmethod
    def get_state_file_path(cls) -> str:
        """Get platform-appropriate state file location."""
        try:
            from qgis.core import QgsApplication
            profile_dir = QgsApplication.qgisSettingsDirPath()
            return os.path.join(profile_dir, cls._STATE_FILE_NAME)
        except Exception:
            import tempfile
            return os.path.join(tempfile.gettempdir(), cls._STATE_FILE_NAME)

    @classmethod
    def save(cls, state: FocusModePlusState) -> bool:
        """
        Atomically save state to file.

        Uses write-to-temp-then-rename for atomic operation.

        Args:
            state: FocusModePlusState to save

        Returns:
            True if save succeeded, False otherwise
        """
        temp_path = None  # Initialize before try block to avoid UnboundLocalError
        try:
            path = cls.get_state_file_path()
            temp_path = path + ".tmp"

            # Ensure directory exists (guard against empty dirname)
            dir_path = os.path.dirname(path)
            if dir_path:
                os.makedirs(dir_path, exist_ok=True)

            with open(temp_path, 'w', encoding='utf-8') as f:
                json.dump(state.to_dict(), f, indent=2)

            os.replace(temp_path, path)
            return True
        except Exception as e:
            print(f"[FocusModePlus] Failed to save state file: {e}")
            # Clean up temp file if it exists
            if temp_path:
                try:
                    if os.path.exists(temp_path):
                        os.remove(temp_path)
                except Exception:
                    pass
            return False

    @classmethod
    def load(cls) -> Optional[Dict[str, Any]]:
        """
        Load state from file.

        Returns:
            Dictionary with state data, or None if not found or invalid
        """
        try:
            path = cls.get_state_file_path()
            if os.path.exists(path):
                with open(path, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception as e:
            print(f"[FocusModePlus] Failed to load state file: {e}")
        return None

    @classmethod
    def exists(cls) -> bool:
        """Check if state file exists (indicates unclean exit)."""
        return os.path.exists(cls.get_state_file_path())

    @classmethod
    def delete(cls) -> bool:
        """
        Delete state file (called on clean exit).

        Returns:
            True if delete succeeded or file didn't exist
        """
        try:
            path = cls.get_state_file_path()
            if os.path.exists(path):
                os.remove(path)
            return True
        except Exception as e:
            print(f"[FocusModePlus] Failed to delete state file: {e}")
            return False
