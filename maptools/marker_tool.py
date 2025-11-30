# -*- coding: utf-8 -*-
"""
Marker Map Tool

Custom QGIS map tool for adding POI and Casualty markers by clicking on map.
"""

import logging
from typing import Optional

from qgis.core import QgsPointXY, QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsProject
from qgis.gui import QgsMapTool
from qgis.PyQt.QtCore import pyqtSignal
from qgis.PyQt.QtGui import QCursor

# Import Qt5/Qt6 compatible constants
from ..utils.qt_compat import CrossCursor
# Import notification utilities
from ..utils.notify import warning as notify_warning

logger = logging.getLogger(__name__)


class MarkerMapTool(QgsMapTool):
    """
    Map tool for adding markers by clicking on the map.
    
    Signals:
        marker_clicked: Emitted when user clicks on map (lat, lon, easting, northing)
    """
    
    marker_clicked = pyqtSignal(float, float, float, float)  # lat, lon, e, n
    
    def __init__(self, canvas, iface=None):
        """
        Initialize marker map tool.
        
        Args:
            canvas: QGIS map canvas
            iface: Optional QGIS interface for user notifications
        """
        super().__init__(canvas)
        self.canvas = canvas
        self.iface = iface
        self.setCursor(QCursor(CrossCursor))
        self._message_bar = None
        
        # Setup coordinate systems
        self.wgs84 = QgsCoordinateReferenceSystem("EPSG:4326")
        self.itm = QgsCoordinateReferenceSystem("EPSG:29903")  # Irish Transverse Mercator
    
    def canvasPressEvent(self, event):
        """Handle mouse click on canvas."""
        # Get click position in map coordinates
        point = self.toMapCoordinates(event.pos())
        
        # Get canvas CRS
        canvas_crs = self.canvas.mapSettings().destinationCrs()

        if not canvas_crs.isValid():
            self._report_transform_failure(
                "Project CRS Unavailable",
                "Cannot determine map coordinate reference system. Check project CRS settings."
            )
            return

        if not self.wgs84.isValid() or not self.itm.isValid():
            self._report_transform_failure(
                "Coordinate Systems Not Ready",
                "Marker tool coordinate references failed to initialize. Restart the plugin or QGIS."
            )
            return

        # MARKER-TRANSFORM fix: Add error handling for coordinate transforms
        try:
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
        except Exception as e:
            detail = (
                f"Could not transform map point from {canvas_crs.authid()} to "
                f"WGS84/ITM: {e}"
            )
            logger.exception("Marker transform failure: %s", detail)
            self._report_transform_failure("Coordinate transform failed", detail)
            return  # Don't emit signal with bad coordinates
        
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
        self.canvas.setCursor(QCursor(CrossCursor))
    
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

    def _message_bar_safe(self):
        """Return cached message bar if iface provides one."""
        if self._message_bar:
            return self._message_bar
        iface = getattr(self, "iface", None)
        if not iface or not hasattr(iface, "messageBar"):
            return None

        try:
            self._message_bar = iface.messageBar()
        except Exception:
            self._message_bar = None
        return self._message_bar

    def _report_transform_failure(self, title: str, detail: str):
        """Log and display coordinate transform failures."""
        logger.warning("%s: %s", title, detail)
        bar = self._message_bar_safe()
        if bar:
            try:
                notify_warning(bar, title, detail, duration=6)
            except Exception:
                logger.debug("Marker tool notification suppressed", exc_info=True)
