#!/usr/bin/env python3
"""
Layer Diagnostic Script for SAR Tracker
Run from QGIS Python Console with:
    exec(open('/Users/donalocallaghan/Documents/Qgis/sartracker/tools/diagnose_layers.py').read())
"""

from qgis.core import QgsProject, QgsLayerTreeGroup, QgsLayerTreeLayer, QgsVectorLayer, QgsMapLayer

print("\n" + "="*60)
print("SAR TRACKER LAYER DIAGNOSTIC")
print("="*60)

# Part 1: Check layer tree structure
print("\n--- LAYER TREE STRUCTURE ---\n")

root = QgsProject.instance().layerTreeRoot()

def check_tree(node, indent=0):
    if isinstance(node, QgsLayerTreeLayer):
        marker = "L"
        layer = node.layer()
        if layer:
            if isinstance(layer, QgsVectorLayer):
                extra = f" (valid={layer.isValid()}, features={layer.featureCount()})"
            else:
                layer_type = "raster" if layer.type() == QgsMapLayer.RasterLayer else "other"
                extra = f" (valid={layer.isValid()}, type={layer_type})"
        else:
            extra = " (NO LAYER!)"
    elif isinstance(node, QgsLayerTreeGroup):
        marker = "G"
        extra = ""
    else:
        marker = "?"
        extra = ""

    print("  " * indent + f"[{marker}] {node.name()}{extra}")

    if hasattr(node, 'children'):
        for child in node.children():
            check_tree(child, indent + 1)

check_tree(root)

# Part 2: Check SAR Tracker layers in project registry
print("\n--- SAR TRACKER LAYERS IN REGISTRY ---\n")

sar_layers_found = 0
for layer in QgsProject.instance().mapLayers().values():
    if not isinstance(layer, QgsVectorLayer):
        continue
    try:
        is_sar = (
            layer.customProperty('sartracker:item_type') is not None
            or layer.customProperty('sartracker:layer_id') is not None
            or layer.customProperty('sartracker:device_id') is not None
        )
    except Exception:
        is_sar = False
    if is_sar:
        sar_layers_found += 1
        print(f"Layer: {layer.name()}")
        print(f"  - Valid: {layer.isValid()}")
        print(f"  - Features: {layer.featureCount() if layer.isValid() else 'N/A'}")
        print(f"  - Item Type: {layer.customProperty('sartracker:item_type')}")
        print(f"  - Device ID: {layer.customProperty('sartracker:device_id')}")
        print(f"  - Device Name: {layer.customProperty('sartracker:device_name')}")
        print(f"  - Source: {layer.source()[:80]}..." if len(layer.source()) > 80 else f"  - Source: {layer.source()}")
        print()

if sar_layers_found == 0:
    print("NO SAR TRACKER LAYERS FOUND IN REGISTRY!")

print("="*60)
print(f"SUMMARY: Found {sar_layers_found} SAR Tracker layers in registry")
print("="*60 + "\n")
