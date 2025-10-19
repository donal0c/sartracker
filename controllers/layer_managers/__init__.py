# -*- coding: utf-8 -*-
"""
Layer Managers Package

Specialized layer managers for SAR Tracker plugin.
Each manager handles one category of layers following Single Responsibility Principle.

Qt5/Qt6 Compatible: Uses qgis.PyQt for all imports.
"""

from .base_manager import BaseLayerManager
from .tracking_manager import TrackingLayerManager
from .marker_manager import MarkerLayerManager
from .drawing_manager import DrawingLayerManager

__all__ = [
    'BaseLayerManager',
    'TrackingLayerManager',
    'MarkerLayerManager',
    'DrawingLayerManager'
]
