#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Force a refresh of the QGIS layer tree view.

Use this to test whether layers exist in the tree but the UI is stale.

Run from QGIS Python Console:
    exec(open('/Users/donalocallaghan/Documents/Qgis/sartracker/tools/diagnose_layer_tree_refresh.py').read())
"""

from qgis.utils import iface

print("\n" + "=" * 60)
print("SAR TRACKER LAYER TREE REFRESH")
print("=" * 60)

view = iface.layerTreeView()
if not view:
    print("ERROR: layerTreeView not available.")
else:
    model = view.model()
    if model:
        try:
            model.layoutChanged.emit()
            print("Emitted layoutChanged on layer tree model.")
        except Exception as exc:
            print(f"Warning: layoutChanged emit failed: {exc}")
    try:
        view.viewport().update()
        print("Requested viewport update.")
    except Exception as exc:
        print(f"Warning: viewport update failed: {exc}")

print("If layers were missing in the Layers panel, check if they appear now.")
