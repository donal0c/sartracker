# -*- coding: utf-8 -*-
"""
Line Drawing Tool

Interactive tool for drawing lines on the map (routes, boundaries, paths).

Qt5/Qt6 Compatible: Uses qgis.PyQt and qt_compat for all Qt imports.
"""

from qgis.core import QgsPointXY, QgsGeometry, QgsWkbTypes
from qgis.gui import QgsRubberBand
from qgis.PyQt.QtGui import QColor

# Import Qt5/Qt6 compatible constants and functions
from ..utils.qt_compat import LeftButton, RightButton, Key_Escape, push_message

from .base_drawing_tool import BaseDrawingTool


class LineTool(BaseDrawingTool):
    """
    Tool for drawing multi-segment lines on the map.

    Click to add points, right-click or ESC to finish.
    Line is saved to Lines layer when complete.
    """

    def __init__(self, canvas, layers_controller):
        """
        Initialize line drawing tool.

        Args:
            canvas: QGIS map canvas
            layers_controller: LayersController instance for saving lines
        """
        super().__init__(canvas)
        self.layers_controller = layers_controller

        # Line drawing state
        self.points = []  # Points in canvas CRS
        self.is_drawing = False

        # Rubber band for preview
        self.line_rubber_band = None

    def activate(self):
        """Called when tool is activated."""
        super().activate()
        self.reset()

    def deactivate(self):
        """Called when tool is deactivated."""
        super().deactivate()
        self.reset()

    def reset(self):
        """Reset drawing state."""
        self.points = []
        self.is_drawing = False
        self.clear_rubber_bands()
        self.line_rubber_band = None  # Clear the rubber band reference

    def canvasPressEvent(self, event):
        """
        Handle mouse click to add point to line.

        Args:
            event: QgsMapMouseEvent
        """
        if event.button() == LeftButton:
            # Get click position
            point = self.toMapCoordinates(event.pos())
            self.points.append(point)
            self.is_drawing = True

            # Update preview
            self._update_rubber_band()

        elif event.button() == RightButton:
            # Right-click finishes the line
            self._finish_line()

    def canvasMoveEvent(self, event):
        """
        Handle mouse movement to show preview of next segment.

        Args:
            event: QgsMapMouseEvent
        """
        if self.is_drawing and len(self.points) > 0:
            # Show preview line from last point to cursor
            current_pos = self.toMapCoordinates(event.pos())

            # Update rubber band with preview
            self._update_rubber_band(preview_point=current_pos)

    def keyPressEvent(self, event):
        """
        Handle keyboard input.

        ESC cancels drawing, Enter finishes line.

        Args:
            event: QKeyEvent
        """
        if event.key() == Key_Escape:
            self.cancel()
        # Could add Key_Return to finish line if desired

    def _update_rubber_band(self, preview_point=None):
        """
        Update rubber band preview.

        Args:
            preview_point: Optional preview point (cursor position)
        """
        # Check canvas is valid
        if not self.canvas or not self.canvas.scene():
            return

        # Always create a fresh rubber band if we don't have a valid one
        if not self.line_rubber_band:
            # Remove old rubber band if it exists
            if self.line_rubber_band:
                try:
                    self.canvas.scene().removeItem(self.line_rubber_band)
                except Exception:
                    pass

            # Create new rubber band
            self.line_rubber_band = QgsRubberBand(
                self.canvas,
                QgsWkbTypes.LineGeometry
            )
            self.line_rubber_band.setColor(QColor(255, 0, 0, 180))  # Red
            self.line_rubber_band.setWidth(2)
            self.rubber_bands.append(self.line_rubber_band)

        # Build preview line
        preview_points = list(self.points)
        if preview_point:
            preview_points.append(preview_point)

        # Update rubber band - reset and rebuild
        self.line_rubber_band.reset(QgsWkbTypes.LineGeometry)
        for point in preview_points:
            self.line_rubber_band.addPoint(point)

        # Force update
        self.line_rubber_band.show()

    def _finish_line(self):
        """Finish drawing and save line to layer."""
        if len(self.points) < 2:
            # Need at least 2 points for a line
            self.cancel()
            return

        try:
            # Transform points to WGS84 for storage
            points_wgs84 = [self.transform_to_wgs84(p) for p in self.points]

            # Calculate total distance
            total_distance = 0
            for i in range(len(points_wgs84) - 1):
                dist = self.calculate_distance(points_wgs84[i], points_wgs84[i + 1])
                total_distance += dist

            # Create line name with distance
            name = f"Line {total_distance:.0f}m"

            # Save to layer
            feature_id = self.layers_controller.add_line(
                name=name,
                points_wgs84=points_wgs84,
                description="",
                color="#FF0000",
                width=2
            )

            # Emit completion signal with feature data
            self.drawing_complete.emit({
                'type': 'line',
                'feature_id': feature_id,
                'name': name,
                'distance_m': total_distance,
                'points': len(points_wgs84)
            })

        except Exception as e:
            print(f"Error saving line: {e}")
            import traceback
            traceback.print_exc()
            # Show error to user via iface if available
            try:
                from qgis.utils import iface
                if iface:
                    push_message(
                        iface.messageBar(),
                        "Error",
                        f"Failed to save line: {str(e)}",
                        level=2,  # Warning
                        duration=5
                    )
            except:
                pass  # iface not available

        finally:
            # Reset for next line
            self.reset()

    def cancel(self):
        """Cancel current line drawing."""
        self.reset()
        self.drawing_cancelled.emit()
