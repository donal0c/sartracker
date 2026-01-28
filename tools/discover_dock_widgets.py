#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Discover all dock widgets in QGIS and their properties.

This script helps identify the correct object name and title for the Layers panel
dock widget across different QGIS versions.

Run from QGIS Python Console:
    exec(open('/Users/donalocallaghan/Documents/Qgis/sartracker/tools/discover_dock_widgets.py').read())

Purpose:
    - List all QDockWidget instances in QGIS main window
    - Show their object names, window titles, and visibility
    - Identify the Layers panel by traversing from iface.layerTreeView()
    - Help verify Focus Mode Plus implementation
"""

from qgis.utils import iface
from qgis.PyQt.QtWidgets import QDockWidget

print("\n" + "=" * 70)
print("QGIS DOCK WIDGET DISCOVERY")
print("=" * 70)

# Get QGIS version
from qgis.core import Qgis
print(f"\nQGIS Version: {Qgis.version()}")
print(f"Qt Version: {Qgis.qtVersion() if hasattr(Qgis, 'qtVersion') else 'N/A'}")

# Get main window
main_window = iface.mainWindow()
print(f"\nMain Window: {main_window}")
print(f"Main Window Object Name: {main_window.objectName()}")

# Find all dock widgets
print("\n" + "-" * 70)
print("ALL DOCK WIDGETS")
print("-" * 70)

all_docks = main_window.findChildren(QDockWidget)
print(f"\nFound {len(all_docks)} dock widget(s):\n")

for i, dock in enumerate(all_docks):
    obj_name = dock.objectName()
    title = dock.windowTitle()
    visible = dock.isVisible()
    floating = dock.isFloating()
    widget = dock.widget()
    widget_class = type(widget).__name__ if widget else "None"

    print(f"  [{i+1}] Object Name: '{obj_name}'")
    print(f"      Window Title: '{title}'")
    print(f"      Visible: {visible}, Floating: {floating}")
    print(f"      Widget Class: {widget_class}")
    if widget:
        widget_obj_name = widget.objectName()
        print(f"      Widget Object Name: '{widget_obj_name}'")
    print()

# Find layers panel via layerTreeView traversal
print("-" * 70)
print("LAYERS PANEL IDENTIFICATION")
print("-" * 70)

layer_tree_view = iface.layerTreeView()
if layer_tree_view:
    print(f"\niface.layerTreeView() returns: {layer_tree_view}")
    print(f"  Object Name: '{layer_tree_view.objectName()}'")
    print(f"  Class: {type(layer_tree_view).__name__}")

    # Traverse up to find parent dock widget
    print("\nParent hierarchy:")
    parent = layer_tree_view.parent()
    level = 1
    layers_dock = None

    while parent:
        parent_name = parent.objectName()
        parent_class = type(parent).__name__
        is_dock = isinstance(parent, QDockWidget)

        print(f"  [{level}] {parent_class}: '{parent_name}'" + (" <-- QDockWidget!" if is_dock else ""))

        if is_dock and layers_dock is None:
            layers_dock = parent
            print(f"      --> LAYERS DOCK FOUND!")
            print(f"          Window Title: '{parent.windowTitle()}'")

        parent = parent.parent()
        level += 1

        if level > 20:  # Safety limit
            print("  ... (stopping at 20 levels)")
            break

    if layers_dock:
        print(f"\n*** LAYERS PANEL IDENTIFICATION ***")
        print(f"  Object Name: '{layers_dock.objectName()}'")
        print(f"  Window Title: '{layers_dock.windowTitle()}'")
        print(f"  Use objectName '{layers_dock.objectName()}' to identify this dock!")
    else:
        print("\n*** WARNING: Could not find parent QDockWidget for layer tree view!")
        print("    The layer tree view may not be in a standard dock widget.")
else:
    print("\nERROR: iface.layerTreeView() returned None!")

# Summary of common dock names
print("\n" + "-" * 70)
print("COMMON DOCK WIDGET OBJECT NAMES")
print("-" * 70)
print("""
Based on QGIS source code analysis:
  - Layer Tree View object name: 'theLayerTreeView'
  - The dock widget containing it may have a different name
  - Common pattern: dock.widget().objectName() == 'theLayerTreeView'

Recommended identification approach:
  1. Primary: Use iface.layerTreeView() and traverse to parent QDockWidget
  2. Fallback: Check dock.widget() for 'theLayerTreeView' object name
  3. Fallback: Check window title contains 'Layers' (localized!)
""")

print("=" * 70)
print("DISCOVERY COMPLETE")
print("=" * 70 + "\n")
