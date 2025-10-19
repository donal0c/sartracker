# SAR Drawing Tools Implementation Plan

## Summary of Research Findings

Based on the comprehensive research of QGIS's drawing and digitizing capabilities, here's what we've learned:

### What QGIS Provides (We Can Leverage)

1. **Robust Infrastructure**
   - `QgsMapTool` base class for all interactive tools
   - `QgsRubberBand` for real-time visual feedback
   - `QgsVertexMarker` for point highlighting
   - Complete geometry creation and manipulation APIs

2. **Coordinate & Measurement Systems**
   - `QgsCoordinateTransform` for Irish Grid ↔ WGS84 conversion
   - `QgsDistanceArea` for accurate geodesic calculations
   - Built-in bearing and distance calculations

3. **Data Management**
   - Memory layers for temporary features
   - Full symbology and styling engine
   - Feature attribute management

### What We Need to Build (SAR-Specific)

1. **Custom Drawing Tools**
   - ✅ Range rings (implemented in `range_ring_tool.py`)
   - ✅ Search sectors (implemented in `sector_tool.py`)
   - ⏳ Search grids
   - ⏳ Bearing lines with distance markers
   - ⏳ Search patterns (expanding square, sector, contour)

2. **Enhanced Features**
   - Tool configuration dialogs
   - Persistent tool settings
   - Export capabilities
   - Integration with mission data

## Implemented Tools

### 1. Range Ring Tool (`maptools/range_ring_tool.py`)
- **Status**: ✅ Complete
- **Features**:
  - Single-click creation at predefined distances
  - Preview during mouse movement
  - Configurable distances
  - Geodesic calculations for accuracy
  - Labeled rings with distance
- **Usage**: Click on map to create concentric circles at 100m, 250m, 500m, 1km, 2km

### 2. Search Sector Tool (`maptools/sector_tool.py`)
- **Status**: ✅ Complete
- **Features**:
  - Three-click creation (center → radius/start → end)
  - Real-time preview during creation
  - Area calculation
  - Arc length display
- **Usage**: Click center, click to set radius and start angle, click to set end angle

## Tools to Implement Next

### 3. Search Grid Tool
**Purpose**: Create grid overlay for systematic area search

**Implementation Approach**:
```python
class SearchGridTool(QgsMapTool):
    # Two-click rectangle definition
    # Configurable cell size
    # Track searched/unsearched cells
    # Export as GPX waypoints
```

**Key Features**:
- Define area with rectangle
- Configurable grid cell size (50m, 100m, 200m)
- Checkbox attribute for marking searched cells
- Label cells with grid reference
- Calculate total area and coverage percentage

### 4. Bearing Line Tool
**Purpose**: Create directional lines from a point

**Implementation Approach**:
```python
class BearingLineTool(QgsMapTool):
    # Click origin point
    # Enter bearing and distance via dialog
    # Create line with distance markers
    # Optional: extend to multiple bearings
```

**Key Features**:
- Input bearing in degrees or mils
- Configurable distance
- Distance markers at intervals
- Reciprocal bearing display
- Multiple lines from same origin

### 5. Search Pattern Generator
**Purpose**: Create standard SAR search patterns

**Implementation Approach**:
```python
class SearchPatternTool(QgsMapTool):
    # Select pattern type via dialog
    # Configure parameters
    # Generate waypoints and tracks
    # Export for GPS upload
```

**Pattern Types**:
- **Expanding Square**: Start point, leg length, expansion factor
- **Sector Search**: Center, radius, number of sweeps
- **Contour Search**: Follow elevation contours
- **Parallel Track**: Area, track spacing, orientation

## Integration with Existing Plugin

### 1. Add Tool Buttons to SAR Panel
```python
# In sar_panel.py
self.range_ring_btn = QPushButton("Range Rings")
self.search_sector_btn = QPushButton("Search Sector")
self.search_grid_btn = QPushButton("Search Grid")

# Connect signals
self.range_ring_btn.clicked.connect(self.on_range_ring_clicked)
```

### 2. Tool Management in Main Plugin
```python
# In sartracker.py
def initGui(self):
    # Initialize new tools
    self.range_ring_tool = RangeRingTool(self.iface.mapCanvas())
    self.sector_tool = SearchSectorTool(self.iface.mapCanvas())

    # Connect signals
    self.range_ring_tool.rings_created.connect(self._on_rings_created)
    self.sector_tool.sector_created.connect(self._on_sector_created)
```

### 3. Layer Organization
```
SAR Tracking (Group)
├── Points of Interest
├── Casualties
├── Current Positions
├── Breadcrumbs
├── Search Areas (New Group)
│   ├── Range Rings
│   ├── Search Sectors
│   ├── Search Grids
│   └── Search Patterns
└── Measurements
```

## Configuration and Persistence

### 1. Tool Settings Dialog
Create a settings dialog for configuring default values:
- Range ring distances
- Grid cell sizes
- Default units (metric/imperial)
- Color schemes
- Label preferences

### 2. QSettings Integration
```python
# Save tool preferences
settings = QSettings()
settings.setValue("sartracker/range_distances", [100, 250, 500, 1000])
settings.setValue("sartracker/grid_size", 100)
settings.setValue("sartracker/units", "metric")
```

### 3. Project Storage
Store drawn features in QGIS project:
- Use memory layers during session
- Convert to saved layers on project save
- Restore on project load

## Testing Requirements

### 1. Coordinate System Testing
- [ ] Test with different project CRS
- [ ] Verify Irish Grid transformations
- [ ] Check accuracy of distance calculations
- [ ] Test at different latitudes

### 2. Performance Testing
- [ ] Large number of features (>1000)
- [ ] Complex geometries (high segment count)
- [ ] Real-time preview responsiveness
- [ ] Memory usage monitoring

### 3. User Experience Testing
- [ ] Tool activation/deactivation
- [ ] Keyboard shortcuts (ESC to cancel)
- [ ] Visual feedback clarity
- [ ] Error handling and messages

## Documentation Needs

### 1. User Guide
- Tool descriptions and use cases
- Step-by-step instructions
- Screenshots/GIFs
- Keyboard shortcuts reference

### 2. API Documentation
- Class and method documentation
- Signal descriptions
- Code examples
- Integration guide

### 3. Training Materials
- SAR-specific workflows
- Best practices
- Common patterns
- Troubleshooting guide

## Performance Optimizations

### 1. Geometry Simplification
- Use appropriate segment counts
- Simplify for display vs. calculation
- Cache transformed geometries

### 2. Rendering Optimization
- Use QgsMapCanvas.freeze()/freeze(False)
- Batch feature additions
- Selective layer updates

### 3. Memory Management
- Clean up rubber bands
- Remove temporary layers
- Clear tool state on deactivation

## Future Enhancements

### 1. Advanced Features
- Magnetic declination adjustment
- GPS integration for live position
- Time-based search progression
- Probability maps
- Viewshed analysis

### 2. Data Integration
- Import search areas from GPX
- Export to common SAR formats
- Integration with incident management systems
- Real-time collaboration features

### 3. Analysis Tools
- Coverage statistics
- Overlap detection
- Gap analysis
- Search efficiency metrics

## Recommended Next Steps

1. **Immediate (Week 1)**
   - Integrate range ring and sector tools into main plugin
   - Add tool buttons to SAR panel
   - Test with real SAR scenarios
   - Fix any issues found

2. **Short Term (Weeks 2-3)**
   - Implement search grid tool
   - Add bearing line tool
   - Create settings dialog
   - Write user documentation

3. **Medium Term (Weeks 4-6)**
   - Implement search pattern generator
   - Add export capabilities
   - Create training materials
   - Performance optimization

4. **Long Term (Months 2-3)**
   - Advanced analysis features
   - GPS integration
   - Collaborative features
   - Mobile companion app

## Key Takeaways

1. **QGIS provides excellent foundation** - No need to reinvent basic drawing capabilities
2. **Focus on SAR-specific features** - Add value through domain-specific tools
3. **Maintain consistency** - Follow QGIS UI/UX patterns
4. **Test thoroughly** - Especially coordinate transformations and measurements
5. **Document well** - Both code and user documentation are critical

## Resources

- **QGIS PyQGIS Cookbook**: Primary reference for API usage
- **Implemented Examples**: `range_ring_tool.py` and `sector_tool.py` as patterns
- **QGIS Source**: Study core digitizing tools for best practices
- **SAR References**: Standard search patterns and procedures

This implementation plan provides a clear roadmap for building out the complete set of SAR drawing tools while leveraging QGIS's powerful built-in capabilities.