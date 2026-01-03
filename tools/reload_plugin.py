#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Reload the SAR Tracker plugin in QGIS.

Run from QGIS Python Console:
    exec(open('/Users/donalocallaghan/Documents/Qgis/sartracker/tools/reload_plugin.py').read())
"""

from qgis.utils import reloadPlugin

print("Reloading SAR Tracker plugin...")
reloadPlugin('sartracker')
print("Reload complete.")
