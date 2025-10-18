# -*- coding: utf-8 -*-
"""
Qt5/Qt6 Compatibility Module

This module provides compatibility constants for Qt enums that changed from
Qt5 to Qt6. In Qt6, many enums moved to scoped enums.

For example:
- Qt5: Qt.LeftDockWidgetArea
- Qt6: Qt.DockWidgetArea.LeftDockWidgetArea

This module detects the Qt version and exports the correct constants,
allowing code to work with both Qt5 and Qt6.

Usage:
    from utils.qt_compat import (
        LeftDockWidgetArea, RightDockWidgetArea,
        Checked, Unchecked,
        CrossCursor
    )

    # Then use the constants directly:
    self.setAllowedAreas(LeftDockWidgetArea | RightDockWidgetArea)
    if state == Checked:
        ...
"""

from qgis.PyQt.QtCore import Qt

# Try to detect Qt version by checking for scoped enum attributes
try:
    # Qt6 style - enums are in sub-namespaces
    _test = Qt.DockWidgetArea.LeftDockWidgetArea
    QT_VERSION = 6
except AttributeError:
    # Qt5 style - enums are directly in Qt namespace
    QT_VERSION = 5


# =============================================================================
# DockWidgetArea enums
# =============================================================================
if QT_VERSION == 6:
    LeftDockWidgetArea = Qt.DockWidgetArea.LeftDockWidgetArea
    RightDockWidgetArea = Qt.DockWidgetArea.RightDockWidgetArea
    TopDockWidgetArea = Qt.DockWidgetArea.TopDockWidgetArea
    BottomDockWidgetArea = Qt.DockWidgetArea.BottomDockWidgetArea
    AllDockWidgetAreas = Qt.DockWidgetArea.AllDockWidgetAreas
    NoDockWidgetArea = Qt.DockWidgetArea.NoDockWidgetArea
else:  # Qt5
    LeftDockWidgetArea = Qt.LeftDockWidgetArea
    RightDockWidgetArea = Qt.RightDockWidgetArea
    TopDockWidgetArea = Qt.TopDockWidgetArea
    BottomDockWidgetArea = Qt.BottomDockWidgetArea
    AllDockWidgetAreas = Qt.AllDockWidgetAreas
    NoDockWidgetArea = Qt.NoDockWidgetArea


# =============================================================================
# CheckState enums
# =============================================================================
if QT_VERSION == 6:
    Unchecked = Qt.CheckState.Unchecked
    PartiallyChecked = Qt.CheckState.PartiallyChecked
    Checked = Qt.CheckState.Checked
else:  # Qt5
    Unchecked = Qt.Unchecked
    PartiallyChecked = Qt.PartiallyChecked
    Checked = Qt.Checked


# =============================================================================
# CursorShape enums
# =============================================================================
if QT_VERSION == 6:
    ArrowCursor = Qt.CursorShape.ArrowCursor
    CrossCursor = Qt.CursorShape.CrossCursor
    WaitCursor = Qt.CursorShape.WaitCursor
    IBeamCursor = Qt.CursorShape.IBeamCursor
    PointingHandCursor = Qt.CursorShape.PointingHandCursor
    SizeVerCursor = Qt.CursorShape.SizeVerCursor
    SizeHorCursor = Qt.CursorShape.SizeHorCursor
    SizeBDiagCursor = Qt.CursorShape.SizeBDiagCursor
    SizeFDiagCursor = Qt.CursorShape.SizeFDiagCursor
    SizeAllCursor = Qt.CursorShape.SizeAllCursor
    BlankCursor = Qt.CursorShape.BlankCursor
    WhatsThisCursor = Qt.CursorShape.WhatsThisCursor
    ForbiddenCursor = Qt.CursorShape.ForbiddenCursor
    BusyCursor = Qt.CursorShape.BusyCursor
    OpenHandCursor = Qt.CursorShape.OpenHandCursor
    ClosedHandCursor = Qt.CursorShape.ClosedHandCursor
else:  # Qt5
    ArrowCursor = Qt.ArrowCursor
    CrossCursor = Qt.CrossCursor
    WaitCursor = Qt.WaitCursor
    IBeamCursor = Qt.IBeamCursor
    PointingHandCursor = Qt.PointingHandCursor
    SizeVerCursor = Qt.SizeVerCursor
    SizeHorCursor = Qt.SizeHorCursor
    SizeBDiagCursor = Qt.SizeBDiagCursor
    SizeFDiagCursor = Qt.SizeFDiagCursor
    SizeAllCursor = Qt.SizeAllCursor
    BlankCursor = Qt.BlankCursor
    WhatsThisCursor = Qt.WhatsThisCursor
    ForbiddenCursor = Qt.ForbiddenCursor
    BusyCursor = Qt.BusyCursor
    OpenHandCursor = Qt.OpenHandCursor
    ClosedHandCursor = Qt.ClosedHandCursor


# =============================================================================
# AlignmentFlag enums
# =============================================================================
if QT_VERSION == 6:
    AlignLeft = Qt.AlignmentFlag.AlignLeft
    AlignRight = Qt.AlignmentFlag.AlignRight
    AlignHCenter = Qt.AlignmentFlag.AlignHCenter
    AlignJustify = Qt.AlignmentFlag.AlignJustify
    AlignTop = Qt.AlignmentFlag.AlignTop
    AlignBottom = Qt.AlignmentFlag.AlignBottom
    AlignVCenter = Qt.AlignmentFlag.AlignVCenter
    AlignCenter = Qt.AlignmentFlag.AlignCenter
else:  # Qt5
    AlignLeft = Qt.AlignLeft
    AlignRight = Qt.AlignRight
    AlignHCenter = Qt.AlignHCenter
    AlignJustify = Qt.AlignJustify
    AlignTop = Qt.AlignTop
    AlignBottom = Qt.AlignBottom
    AlignVCenter = Qt.AlignVCenter
    AlignCenter = Qt.AlignCenter


# =============================================================================
# MouseButton enums
# =============================================================================
if QT_VERSION == 6:
    NoButton = Qt.MouseButton.NoButton
    LeftButton = Qt.MouseButton.LeftButton
    RightButton = Qt.MouseButton.RightButton
    MiddleButton = Qt.MouseButton.MiddleButton
    BackButton = Qt.MouseButton.BackButton
    ForwardButton = Qt.MouseButton.ForwardButton
else:  # Qt5
    NoButton = Qt.NoButton
    LeftButton = Qt.LeftButton
    RightButton = Qt.RightButton
    MiddleButton = Qt.MiddleButton
    BackButton = Qt.BackButton
    ForwardButton = Qt.ForwardButton


# =============================================================================
# Key enums (common ones)
# =============================================================================
if QT_VERSION == 6:
    Key_Return = Qt.Key.Key_Return
    Key_Enter = Qt.Key.Key_Enter
    Key_Escape = Qt.Key.Key_Escape
    Key_Delete = Qt.Key.Key_Delete
    Key_Backspace = Qt.Key.Key_Backspace
    Key_Tab = Qt.Key.Key_Tab
    Key_Space = Qt.Key.Key_Space
else:  # Qt5
    Key_Return = Qt.Key_Return
    Key_Enter = Qt.Key_Enter
    Key_Escape = Qt.Key_Escape
    Key_Delete = Qt.Key_Delete
    Key_Backspace = Qt.Key_Backspace
    Key_Tab = Qt.Key_Tab
    Key_Space = Qt.Key_Space


# =============================================================================
# Orientation enums
# =============================================================================
if QT_VERSION == 6:
    Horizontal = Qt.Orientation.Horizontal
    Vertical = Qt.Orientation.Vertical
else:  # Qt5
    Horizontal = Qt.Horizontal
    Vertical = Qt.Vertical


# =============================================================================
# WindowType enums (common ones)
# =============================================================================
if QT_VERSION == 6:
    WindowType_Widget = Qt.WindowType.Widget
    WindowType_Window = Qt.WindowType.Window
    WindowType_Dialog = Qt.WindowType.Dialog
    WindowType_Popup = Qt.WindowType.Popup
else:  # Qt5
    WindowType_Widget = Qt.Widget
    WindowType_Window = Qt.Window
    WindowType_Dialog = Qt.Dialog
    WindowType_Popup = Qt.Popup


# =============================================================================
# Export all compatibility constants
# =============================================================================
__all__ = [
    'QT_VERSION',
    # DockWidgetArea
    'LeftDockWidgetArea',
    'RightDockWidgetArea',
    'TopDockWidgetArea',
    'BottomDockWidgetArea',
    'AllDockWidgetAreas',
    'NoDockWidgetArea',
    # CheckState
    'Unchecked',
    'PartiallyChecked',
    'Checked',
    # CursorShape
    'ArrowCursor',
    'CrossCursor',
    'WaitCursor',
    'IBeamCursor',
    'PointingHandCursor',
    'SizeVerCursor',
    'SizeHorCursor',
    'SizeBDiagCursor',
    'SizeFDiagCursor',
    'SizeAllCursor',
    'BlankCursor',
    'WhatsThisCursor',
    'ForbiddenCursor',
    'BusyCursor',
    'OpenHandCursor',
    'ClosedHandCursor',
    # AlignmentFlag
    'AlignLeft',
    'AlignRight',
    'AlignHCenter',
    'AlignJustify',
    'AlignTop',
    'AlignBottom',
    'AlignVCenter',
    'AlignCenter',
    # MouseButton
    'NoButton',
    'LeftButton',
    'RightButton',
    'MiddleButton',
    'BackButton',
    'ForwardButton',
    # Key
    'Key_Return',
    'Key_Enter',
    'Key_Escape',
    'Key_Delete',
    'Key_Backspace',
    'Key_Tab',
    'Key_Space',
    # Orientation
    'Horizontal',
    'Vertical',
    # WindowType
    'WindowType_Widget',
    'WindowType_Window',
    'WindowType_Dialog',
    'WindowType_Popup',
]
