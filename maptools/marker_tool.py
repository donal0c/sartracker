# -*- coding: utf-8 -*-
"""
Marker Map Tool

Custom QGIS map tool for adding POI and Casualty markers by clicking on map.
"""

from qgis.core import QgsPointXY, QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsProject
from qgis.gui import QgsMapTool
from qgis.PyQt.QtCore import pyqtSignal
from qgis.PyQt.QtGui import QCursor
from qgis.PyQt.QtCore import Qt


class MarkerMapTool(QgsMapTool):
    """
    Map tool for adding markers by clicking on the map.
    
    Signals:
        marker_clicked: Emitted when user clicks on map (lat, lon, easting, northing)
    """
    
    marker_clicked = pyqtSignal(float, float, float, float)  # lat, lon, e, n
    
    def __init__(self, canvas):
        """
        Initialize marker map tool.
        
        Args:
            canvas: QGIS map canvas
        """
        super().__init__(canvas)
        self.canvas = canvas
        self.setCursor(QCursor(Qt.CrossCursor))
        
        # Setup coordinate systems
        self.wgs84 = QgsCoordinateReferenceSystem("EPSG:4326")
        self.itm = QgsCoordinateReferenceSystem("EPSG:29903")  # Irish Transverse Mercator
    
    def canvasPressEvent(self, event):
        """Handle mouse click on canvas."""
        # Get click position in map coordinates
        point = self.toMapCoordinates(event.pos())
        
        # Get canvas CRS
        canvas_crs = self.canvas.mapSettings().destinationCrs()
        
        # Transform to WGS84
        transform_to_wgs84 = QgsCoordinateTransform(
            canvas_crs,
            self.wgs84,
            QgsProject.instance()
        )
        wgs84_point = transform_to_wgs84.transform(point)
        
        # Transform to Irish Grid (ITM)
        transform_to_itm = QgsCoordinateTransform(
            canvas_crs,
            self.itm,
            QgsProject.instance()
        )
        itm_point = transform_to_itm.transform(point)
        
        # Emit signal with coordinates
        self.marker_clicked.emit(
            wgs84_point.y(),  # latitude
            wgs84_point.x(),  # longitude
            itm_point.x(),    # easting
            itm_point.y()     # northing
        )
    
    def canvasMoveEvent(self, event):
        """Handle mouse move (optional - could show preview)."""
        pass
    
    def canvasReleaseEvent(self, event):
        """Handle mouse release (not used)."""
        pass
    
    def activate(self):
        """Called when tool is activated."""
        super().activate()
        self.canvas.setCursor(QCursor(Qt.CrossCursor))
    
    def deactivate(self):
        """Called when tool is deactivated."""
        super().deactivate()
    
    def isZoomTool(self):
        """Return False - this is not a zoom tool."""
        return False
    
    def isTransient(self):
        """Return False - tool stays active until manually deactivated."""
        return False
    
    def isEditTool(self):
        """Return True - this is an editing tool."""
        return True
