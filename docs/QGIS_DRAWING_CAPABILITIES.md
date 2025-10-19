# QGIS Drawing and Digitizing Capabilities - Technical Report

## Executive Summary

QGIS provides extensive built-in drawing and digitizing capabilities through PyQGIS that can be leveraged for SAR tracking tools. The platform offers robust APIs for geometry creation, coordinate transformation, measurement, and visual feedback. This report outlines what QGIS provides out-of-the-box versus what needs custom implementation for SAR-specific features.

## 1. QGIS Capabilities Summary

### 1.1 Built-in Capabilities We Can Leverage

QGIS provides the following out-of-the-box capabilities that are directly applicable to SAR drawing tools:

#### Core Drawing Infrastructure
- **QgsMapTool**: Base class for all interactive map tools
- **QgsRubberBand**: Temporary geometry visualization during drawing
- **QgsVertexMarker**: Point highlighting and marking
- **QgsMapCanvasItem**: Custom canvas overlay items

#### Geometry Creation
- **QgsGeometry**: Full geometry creation and manipulation
- **QgsCircle**: Native circle creation with multiple construction methods
- **QgsCircularString**: Arc and curved geometry support
- **QgsLineString/QgsPolygon**: Standard linear geometries

#### Measurement & Calculation
- **QgsDistanceArea**: Ellipsoidal distance/area calculations
- **Bearing calculations**: Built-in geodetic bearing computation
- **QgsCoordinateTransform**: Seamless CRS transformations (Irish Grid ↔ WGS84)

#### Data Management
- **Memory Layers**: Temporary vector layers for features
- **Feature Management**: Add, edit, delete with full attribute support
- **Symbology Engine**: Advanced styling and categorization

### 1.2 What Needs Custom Implementation

While QGIS provides excellent infrastructure, SAR-specific features require custom implementation:

#### SAR-Specific Drawing Tools
- Range rings at specific distances
- Search sectors (wedges/pie slices)
- Search patterns (expanding square, sector search, contour search)
- Bearing lines with distance markers
- Grid overlays for search areas

#### Interactive Features
- Multi-step drawing workflows (e.g., center → radius → angle)
- Real-time measurement display during drawing
- Snap-to-feature for precise positioning
- Custom context menus on drawn features

#### Data Integration
- Integration with SAR tracking data
- Time-based feature visualization
- Dynamic updates from GPS feeds
- Custom attribute schemas for SAR features

## 2. PyQGIS API Reference

### 2.1 Essential Map Tool Classes

```python
from qgis.gui import QgsMapTool, QgsMapToolEmitPoint, QgsRubberBand
from qgis.core import QgsWkbTypes, QgsGeometry, QgsPointXY

class CustomDrawingTool(QgsMapTool):
    """Base pattern for custom drawing tools"""

    def __init__(self, canvas):
        super().__init__(canvas)
        self.rubber_band = QgsRubberBand(canvas, QgsWkbTypes.PolygonGeometry)

    def canvasPressEvent(self, event):
        """Handle mouse press"""
        point = self.toMapCoordinates(event.pos())
        # Custom drawing logic

    def canvasMoveEvent(self, event):
        """Handle mouse move for preview"""
        point = self.toMapCoordinates(event.pos())
        # Update rubber band preview

    def canvasReleaseEvent(self, event):
        """Handle mouse release"""
        # Finalize geometry
```

### 2.2 Geometry Creation Methods

```python
from qgis.core import QgsCircle, QgsGeometry, QgsPoint

# Create circle from center and radius
center = QgsPoint(x, y)
circle = QgsCircle(center, radius)
polygon = circle.toPolygon(segments=36)  # Convert to polygon
geometry = QgsGeometry.fromPolygonXY([polygon])

# Create sector/wedge
def create_sector(center, radius, start_angle, end_angle):
    """Create a pie-slice sector geometry"""
    points = [QgsPointXY(center)]
    for angle in range(int(start_angle), int(end_angle) + 1):
        x = center.x() + radius * math.cos(math.radians(angle))
        y = center.y() + radius * math.sin(math.radians(angle))
        points.append(QgsPointXY(x, y))
    points.append(QgsPointXY(center))  # Close the polygon
    return QgsGeometry.fromPolygonXY([points])
```

### 2.3 Coordinate Transformation

```python
from qgis.core import QgsCoordinateTransform, QgsCoordinateReferenceSystem, QgsProject

# Setup CRS objects
wgs84 = QgsCoordinateReferenceSystem("EPSG:4326")
irish_grid = QgsCoordinateReferenceSystem("EPSG:29903")

# Create transformer
transform = QgsCoordinateTransform(
    wgs84,
    irish_grid,
    QgsProject.instance()
)

# Transform point
point_wgs84 = QgsPointXY(lon, lat)
point_irish = transform.transform(point_wgs84)
```

### 2.4 Distance and Bearing Calculations

```python
from qgis.core import QgsDistanceArea

# Setup distance calculator
calc = QgsDistanceArea()
calc.setSourceCrs(QgsCoordinateReferenceSystem("EPSG:4326"),
                  QgsProject.instance().transformContext())
calc.setEllipsoid('WGS84')

# Calculate distance
distance_m = calc.measureLine(point1, point2)

# Calculate bearing
bearing = calc.bearing(point1, point2)  # Returns radians
bearing_deg = math.degrees(bearing)
```

### 2.5 Memory Layer Creation

```python
from qgis.core import QgsVectorLayer, QgsField, QgsFeature

# Create memory layer
layer = QgsVectorLayer(
    "Polygon?crs=EPSG:4326&field=id:integer&field=name:string&field=type:string",
    "SAR Search Areas",
    "memory"
)

# Add features
feature = QgsFeature()
feature.setGeometry(geometry)
feature.setAttributes([1, "Search Area 1", "sector"])
layer.dataProvider().addFeatures([feature])

# Add to project
QgsProject.instance().addMapLayer(layer)
```

## 3. Implementation Approach

### 3.1 Range Rings Tool

```python
class RangeRingTool(QgsMapTool):
    """Tool for creating concentric range rings"""

    def __init__(self, canvas):
        super().__init__(canvas)
        self.center = None
        self.rubber_bands = []

    def canvasPressEvent(self, event):
        """Set center point"""
        self.center = self.toMapCoordinates(event.pos())
        self.start_drawing()

    def canvasMoveEvent(self, event):
        """Preview rings at cursor distance"""
        if self.center:
            cursor = self.toMapCoordinates(event.pos())
            distance = self.calculate_distance(self.center, cursor)
            self.update_preview(distance)

    def create_rings(self, center, distances):
        """Create multiple range rings"""
        geometries = []
        for distance in distances:
            circle = QgsCircle(QgsPoint(center), distance)
            # Use more segments for larger circles
            segments = min(360, max(36, int(distance / 10)))
            polygon = circle.toPolygon(segments)
            geometries.append(QgsGeometry.fromPolygonXY([polygon]))
        return geometries
```

### 3.2 Search Sector Tool

```python
class SearchSectorTool(QgsMapTool):
    """Tool for creating search sectors/wedges"""

    def __init__(self, canvas):
        super().__init__(canvas)
        self.center = None
        self.radius = None
        self.start_angle = None
        self.clicks = 0

    def canvasPressEvent(self, event):
        point = self.toMapCoordinates(event.pos())

        if self.clicks == 0:
            # First click: set center
            self.center = point
            self.clicks = 1
        elif self.clicks == 1:
            # Second click: set radius and start angle
            self.radius = self.calculate_distance(self.center, point)
            self.start_angle = self.calculate_bearing(self.center, point)
            self.clicks = 2
        elif self.clicks == 2:
            # Third click: set end angle and create sector
            end_angle = self.calculate_bearing(self.center, point)
            self.create_sector(self.start_angle, end_angle)
            self.reset()
```

### 3.3 Bearing Line Tool

```python
class BearingLineTool(QgsMapTool):
    """Tool for creating bearing lines with distance markers"""

    def create_bearing_line(self, start_point, bearing_deg, distance_m):
        """Create a line along a bearing for a specific distance"""
        # Convert to radians
        bearing_rad = math.radians(bearing_deg)

        # Calculate end point using geodesic calculation
        calc = QgsDistanceArea()
        calc.setSourceCrs(self.crs, QgsProject.instance().transformContext())
        calc.setEllipsoid('WGS84')

        # Project point along bearing
        end_point = self.project_point(start_point, bearing_rad, distance_m)

        # Create line geometry
        line = QgsGeometry.fromPolylineXY([start_point, end_point])

        # Add distance markers at intervals
        markers = self.create_distance_markers(line, distance_m)

        return line, markers
```

## 4. Code Examples

### 4.1 Complete Range Ring Implementation

```python
from qgis.core import (
    QgsVectorLayer, QgsFeature, QgsGeometry,
    QgsCircle, QgsPoint, QgsPointXY, QgsField
)
from qgis.gui import QgsMapTool, QgsRubberBand
from qgis.PyQt.QtCore import pyqtSignal
from qgis.PyQt.QtGui import QColor

class RangeRingTool(QgsMapTool):
    """Complete implementation of range ring drawing tool"""

    rings_created = pyqtSignal(QgsPointXY, list)  # center, distances

    def __init__(self, canvas, default_rings=[100, 250, 500, 1000]):
        super().__init__(canvas)
        self.canvas = canvas
        self.default_rings = default_rings  # distances in meters
        self.rubber_bands = []
        self.center = None

    def canvasPressEvent(self, event):
        """Handle mouse press - set center and create rings"""
        # Get click position
        self.center = self.toMapCoordinates(event.pos())

        # Transform to appropriate CRS for distance calculation
        canvas_crs = self.canvas.mapSettings().destinationCrs()

        # Create rings at default distances
        self.create_rings_at_distances(self.center, self.default_rings)

        # Emit signal
        self.rings_created.emit(self.center, self.default_rings)

    def create_rings_at_distances(self, center, distances):
        """Create range rings at specified distances"""
        # Clear any existing previews
        self.clear_rubber_bands()

        # Create memory layer for permanent storage
        layer = QgsVectorLayer(
            "Polygon?crs=EPSG:4326&field=distance:integer&field=units:string",
            "Range Rings",
            "memory"
        )

        provider = layer.dataProvider()
        features = []

        for distance in distances:
            # Create circle geometry
            circle = QgsCircle(QgsPoint(center.x(), center.y()), distance)

            # Convert to polygon (36 segments per 100m radius)
            segments = max(36, int(distance / 100) * 36)
            polygon_points = []

            for i in range(segments + 1):
                angle = (2 * math.pi * i) / segments
                x = center.x() + distance * math.cos(angle)
                y = center.y() + distance * math.sin(angle)
                polygon_points.append(QgsPointXY(x, y))

            # Create feature
            feature = QgsFeature()
            feature.setGeometry(QgsGeometry.fromPolygonXY([polygon_points]))
            feature.setAttributes([distance, "meters"])
            features.append(feature)

            # Also create rubber band for preview
            rubber_band = QgsRubberBand(self.canvas, QgsWkbTypes.PolygonGeometry)
            rubber_band.setColor(QColor(255, 0, 0, 50))
            rubber_band.setWidth(2)
            rubber_band.setToGeometry(feature.geometry(), None)
            self.rubber_bands.append(rubber_band)

        # Add features to layer
        provider.addFeatures(features)
        QgsProject.instance().addMapLayer(layer)

    def clear_rubber_bands(self):
        """Clear all rubber band previews"""
        for rb in self.rubber_bands:
            self.canvas.scene().removeItem(rb)
        self.rubber_bands = []

    def deactivate(self):
        """Clean up when tool is deactivated"""
        self.clear_rubber_bands()
        super().deactivate()
```

### 4.2 Search Pattern Grid Generator

```python
def create_search_grid(bounds, cell_size_m, crs):
    """
    Create a search grid within specified bounds

    Args:
        bounds: QgsRectangle defining search area
        cell_size_m: Grid cell size in meters
        crs: Coordinate reference system

    Returns:
        QgsVectorLayer with grid cells
    """
    # Create memory layer
    layer = QgsVectorLayer(
        f"Polygon?crs={crs.authid()}&field=id:integer&field=searched:boolean",
        "Search Grid",
        "memory"
    )

    provider = layer.dataProvider()
    features = []

    # Calculate grid dimensions
    x_min, y_min = bounds.xMinimum(), bounds.yMinimum()
    x_max, y_max = bounds.xMaximum(), bounds.yMaximum()

    # Convert cell size to degrees (approximate)
    if crs.isGeographic():
        # Rough conversion for geographic CRS
        cell_size = cell_size_m / 111000.0  # Very approximate
    else:
        cell_size = cell_size_m

    # Generate grid cells
    cell_id = 0
    y = y_min
    while y < y_max:
        x = x_min
        while x < x_max:
            # Create cell polygon
            points = [
                QgsPointXY(x, y),
                QgsPointXY(x + cell_size, y),
                QgsPointXY(x + cell_size, y + cell_size),
                QgsPointXY(x, y + cell_size),
                QgsPointXY(x, y)  # Close polygon
            ]

            # Create feature
            feature = QgsFeature()
            feature.setGeometry(QgsGeometry.fromPolygonXY([points]))
            feature.setAttributes([cell_id, False])  # Not searched initially
            features.append(feature)

            cell_id += 1
            x += cell_size
        y += cell_size

    # Add all features
    provider.addFeatures(features)

    # Apply styling
    layer.renderer().symbol().setColor(QColor(0, 0, 255, 30))
    layer.renderer().symbol().symbolLayer(0).setStrokeColor(QColor(0, 0, 255))

    return layer
```

## 5. Best Practices

### 5.1 Tool Design Patterns

1. **Single Responsibility**: Each tool should do one thing well
2. **Visual Feedback**: Always use rubber bands for preview
3. **Clear State Management**: Reset tool state properly
4. **Error Handling**: Validate user input and handle edge cases
5. **Coordinate System Awareness**: Always consider CRS transformations

### 5.2 Performance Optimization

1. **Geometry Simplification**: Use appropriate segment counts for circles
2. **Batch Operations**: Add multiple features at once
3. **Layer Updates**: Use `beginEditCommand()` and `endEditCommand()`
4. **Canvas Refresh**: Only refresh when necessary, use `triggerRepaint()`

### 5.3 User Experience

1. **Status Messages**: Provide clear feedback via message bar
2. **Tool Cursors**: Use appropriate cursors for each tool
3. **Keyboard Shortcuts**: Support ESC to cancel, Enter to confirm
4. **Context Menus**: Add right-click options on features
5. **Undo/Redo**: Integrate with QGIS edit commands

## 6. Potential Pitfalls

### 6.1 Common Issues to Avoid

1. **CRS Mismatches**: Always transform coordinates appropriately
2. **Memory Leaks**: Clean up rubber bands and temporary objects
3. **Thread Safety**: GUI operations must be on main thread
4. **Large Geometries**: Simplify complex geometries for performance
5. **Projection Distortion**: Use appropriate CRS for measurements

### 6.2 QGIS Version Compatibility

```python
# Handle API changes between QGIS versions
try:
    # QGIS 3.x
    from qgis.core import QgsWkbTypes
    geometry_type = QgsWkbTypes.PolygonGeometry
except:
    # Older QGIS
    from qgis.core import QGis
    geometry_type = QGis.Polygon
```

## 7. Dependencies and Requirements

### 7.1 Core Dependencies

- **QGIS 3.16+**: Minimum version for stable PyQGIS API
- **Python 3.7+**: Required by modern QGIS
- **PyQt5/PyQt6**: Handled by QGIS installation

### 7.2 Optional Enhancements

- **shapely**: Advanced geometry operations
- **geopy**: Additional geodesic calculations
- **numpy**: Efficient coordinate arrays

### 7.3 QGIS Features to Enable

- **Snapping**: Enable snapping toolbar for precision
- **Digitizing**: Advanced digitizing panel
- **GPS**: GPS information panel for live tracking

## 8. Implementation Roadmap

### Phase 1: Basic Drawing Tools
1. Range rings at fixed distances
2. Simple bearing lines
3. Point markers (POI, casualties)
4. Basic measurement tool

### Phase 2: Advanced Geometries
1. Search sectors/wedges
2. Search grid generation
3. Expanding square pattern
4. Contour search pattern

### Phase 3: Interactive Features
1. Editable geometries (move, resize)
2. Snap-to-feature
3. Multi-step wizards
4. Real-time measurements

### Phase 4: Integration
1. GPS track integration
2. Time-based visualization
3. Animation of search progress
4. Export to standard formats

## 9. Code Architecture Recommendations

### 9.1 Module Structure

```
sartracker/
├── maptools/
│   ├── base_tool.py          # Base class for all tools
│   ├── range_ring_tool.py    # Range ring implementation
│   ├── sector_tool.py        # Search sector tool
│   ├── bearing_tool.py       # Bearing line tool
│   ├── grid_tool.py          # Search grid generator
│   └── pattern_tools.py      # Search pattern tools
├── geometry/
│   ├── builders.py           # Geometry creation utilities
│   ├── calculations.py       # Distance/bearing calculations
│   └── transformations.py    # CRS transformation helpers
└── layers/
    ├── style_manager.py      # Consistent styling
    └── feature_manager.py    # Feature CRUD operations
```

### 9.2 Tool Registry Pattern

```python
class DrawingToolRegistry:
    """Registry for all drawing tools"""

    def __init__(self, canvas):
        self.canvas = canvas
        self.tools = {}
        self.active_tool = None

    def register_tool(self, name, tool_class):
        """Register a drawing tool"""
        self.tools[name] = tool_class(self.canvas)

    def activate_tool(self, name):
        """Activate a specific tool"""
        if self.active_tool:
            self.canvas.unsetMapTool(self.active_tool)
        self.active_tool = self.tools.get(name)
        if self.active_tool:
            self.canvas.setMapTool(self.active_tool)
```

## 10. Conclusion

QGIS provides excellent foundational capabilities for building SAR drawing tools through PyQGIS. The platform's native support for geometry creation, coordinate transformation, and visual feedback significantly reduces development effort. While SAR-specific features require custom implementation, the robust PyQGIS API makes this straightforward.

### Key Takeaways

1. **Leverage Native APIs**: Use QgsMapTool, QgsRubberBand, and QgsGeometry
2. **Build Incrementally**: Start with simple tools, add complexity gradually
3. **Follow QGIS Patterns**: Consistency with QGIS UX improves usability
4. **Test Thoroughly**: Especially CRS transformations and measurements
5. **Document Clearly**: Both code and user documentation are essential

### Next Steps

1. Implement basic range ring tool as proof of concept
2. Create standardized tool base class
3. Build geometry utility library
4. Develop comprehensive test suite
5. Create user documentation with screenshots

This technical foundation provides everything needed to build professional-grade SAR drawing tools that integrate seamlessly with QGIS while maintaining the specific requirements of search and rescue operations.