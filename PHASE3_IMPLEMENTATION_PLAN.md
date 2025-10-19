# Phase 3 Implementation Plan - CalTopo-Style Drawing Tools

**Created:** 2025-10-18
**Status:** Planning Phase
**Based on:** CalTopo/SARTopo Research Report

---

## Overview

Phase 3 will add CalTopo-style drawing and annotation tools to the SAR Tracker plugin, enabling SAR teams to plan operations, mark search areas, and document findings directly on the map.

### Key Design Principles
- **Simplicity First**: Tools must be intuitive under stressful SAR conditions
- **Coordinate Flexibility**: Support both Irish Grid (ITM) and WGS84 input
- **Measurement Integration**: Automatic distance, bearing, and area calculations
- **Visual Clarity**: Clear symbology and labels for field operations
- **Qt5/Qt6 Compatible**: Follow established patterns from Phase 1 & 2

---

## Research Findings Summary

Based on CalTopo/SARTopo analysis:
- **Core Tools**: Markers, Lines, Polygons, Range Rings, Bearing Lines, Sectors, Text Annotations
- **SAR Workflows**: Initial response → Search planning → Active operations → Documentation
- **Key Features**: Click-to-draw, coordinate entry, measurements, styling, export

---

## Implementation Priorities

### ✅ Already Implemented (Phase 2)
- **Marker Tool** → Our POI tool (blue markers)
- **Clue Tool** → Our Casualty tool (red markers)

### 🔨 Phase 3A - Core Drawing Tools (Build First)

#### 1. Line Tool
**Purpose**: Draw tracks, paths, boundaries, access routes

**Features to Implement**:
- Click-to-draw polyline with live preview
- Auto-calculate and display total distance
- Configurable styling (color, line width)
- Support for coordinate entry mode
- Properties dialog:
  - Name/label
  - Description/notes
  - Color picker
  - Line width selector
  - Show/hide distance labels

**SAR Use Cases**:
- Mark access routes to search areas
- Draw probable subject paths
- Define containment boundaries
- Record search team tracks

**Implementation Notes**:
- Use QgsMapToolEmitPoint subclass for click handling
- Store as QgsLineString in memory layer
- Add to "SAR Annotations" layer group
- Follow POI/Casualty pattern for coordinate system support
- Rubberband preview while drawing
- Right-click or double-click to finish

**UI Integration**:
- Add "Draw Line" button to SAR panel
- Cursor changes to crosshair when active
- Status bar shows "Click points to draw line, right-click to finish"

---

#### 2. Polygon/Search Area Tool
**Purpose**: Define search segments, completed areas, operational boundaries

**Features to Implement**:
- Click-to-draw polygon with live preview
- Auto-calculate and display area (km², hectares, acres)
- Semi-transparent fill with colored border
- Properties dialog:
  - Segment name (e.g., "Area Alpha", "Zone 1")
  - Team assignment
  - Status (Planned/In Progress/Complete)
  - Priority (High/Medium/Low)
  - Color picker (with team color presets)
  - Fill transparency slider
  - Notes field

**SAR Use Cases**:
- Divide search area into segments
- Track which areas completed
- Mark hazard zones
- Define operational boundaries

**Implementation Notes**:
- Use QgsMapToolEmitPoint for polygon digitizing
- Store as QgsPolygon in memory layer
- Calculate area using QgsDistanceArea
- Support both Irish Grid and WGS84
- Different fill patterns for status (hatched for complete, solid for in-progress)

**UI Integration**:
- Add "Draw Search Area" button
- Show area calculation in real-time as drawing
- Context menu on existing polygons: Edit Properties, Delete, Zoom To

---

#### 3. Range Ring/Circle Tool
**Purpose**: Distance circles for search planning, time-distance analysis

**Features to Implement**:
- Click to place center point OR enter coordinates
- Input dialog:
  - Center coordinates (Irish Grid or WGS84)
  - Radius (meters/km/miles)
  - Multiple rings (comma-separated: 1, 2, 5 km)
  - Optional: Time-based rings (e.g., "1 hour walking @ 3 km/h")
  - Ring label option
  - Color and transparency
- Display radius labels on each ring

**SAR Use Cases**:
- Statistical search areas from LKP
- Communication range circles
- Time-distance travel estimates
- Helicopter fuel range limits

**Implementation Notes**:
- Create circles using QgsCircle with calculated radius
- Support multiple concentric rings from single center
- Store in "Range Rings" memory layer
- Include time-distance calculator using standard travel speeds:
  - Walking (slow terrain): 2 km/h
  - Walking (moderate): 3 km/h
  - Walking (fast/road): 5 km/h
  - Running: 8 km/h

**UI Integration**:
- Add "Range Rings" button
- Dialog opens immediately (not map-tool mode)
- Option to click center OR type coordinates
- Preview updates in real-time as user adjusts values

---

### 🔨 Phase 3B - Advanced SAR Tools (Build Second)

#### 4. Bearing Line Tool
**Purpose**: Azimuth lines for direction-finding, witness reports

**Features to Implement**:
- Origin point (click OR coordinate entry)
- Input dialog:
  - Starting coordinates (Irish Grid or WGS84)
  - Bearing (degrees, 0-360)
  - Distance/length
  - Magnetic declination correction
  - Label text
  - Color and width
- Display bearing angle on line
- Support multiple bearings from same origin

**SAR Use Cases**:
- Direction of travel from LKP
- Radio direction finding (RDF) results
- Witness sighting directions
- Wind direction indicators

**Implementation Notes**:
- Calculate endpoint using bearing and distance
- Use QgsPoint.project() for geodetic calculations
- Store as attributed line in memory layer
- Include magnetic declination for Ireland (~-4.5° west)
- Show bearing both as true and magnetic

**UI Integration**:
- Add "Bearing Line" button
- Dialog with coordinate/bearing entry
- Visual preview as values change
- Option to add multiple bearings from same point

---

#### 5. Sector/Wedge Tool
**Purpose**: Probability-based search sectors, sweep width zones

**Features to Implement**:
- Center point selection
- Input dialog:
  - Center coordinates
  - Start bearing (degrees)
  - End bearing (degrees)
  - Radius
  - Sector label
  - Color and transparency
  - Priority level
- Calculate and display sector area

**SAR Use Cases**:
- High-probability search sectors
- Visual search patterns from aircraft
- Sound sweep areas
- Directional probability zones

**Implementation Notes**:
- Create arc/wedge geometry using QgsCircularString
- Support angles > 180° for wide sectors
- Semi-transparent fill
- Store in "Search Sectors" layer
- Include angle calculation (end - start bearing)

**UI Integration**:
- Add "Search Sector" button
- Visual preview while adjusting bearings
- Snap to bearing line endpoints if present

---

#### 6. Text Annotation Tool
**Purpose**: Add labels, notes, team assignments to map

**Features to Implement**:
- Click-to-place text label
- Input dialog:
  - Text content (multi-line)
  - Font size (small/medium/large)
  - Text color
  - Background (none/white/colored)
  - Border option
  - Rotation angle
- Labels visible at all zoom levels

**SAR Use Cases**:
- Segment identifiers ("Alpha", "Bravo")
- Team assignments ("Team 1 - In Progress")
- Operational notes
- Hazard warnings

**Implementation Notes**:
- Store as point feature with label styling
- Use QgsTextAnnotation for rendering
- Support multiple lines with \n
- Background halo for visibility over map

**UI Integration**:
- Add "Add Label" button
- Click on map, dialog opens
- Preview text placement before confirming

---

### 🔨 Phase 3C - Enhancement Features (Build Third)

#### 7. GPX Import Tool
**Purpose**: Load GPS tracks from team members, walkers, previous searches

**Features to Implement**:
- File picker for .gpx files
- Import as line layer with styling
- Extract track name from GPX metadata
- Display track statistics:
  - Total distance
  - Start/end times
  - Elevation gain/loss (if available)
- Option to convert track to search area polygon

**SAR Use Cases**:
- Import subject's known route from GPS
- Load previous search team tracks
- Import witness tracks
- Analyze walker routes in area

**Implementation Notes**:
- Use QgsVectorLayer with GPX driver
- Add to "SAR Tracking" group
- Style differently from live tracking
- Support multiple GPX imports

**UI Integration**:
- Add "Import GPX" button
- File browser opens
- Success message with track stats

---

#### 8. Measure Tool Enhancements
**Purpose**: Extend existing measurement capabilities

**Already Have** (Phase 2):
- ✅ Distance & Bearing between two points

**Add**:
- Multi-point distance (total path length)
- Area measurement tool
- Elevation at point (if DEM available)
- Grid reference at cursor (already in status bar)

---

#### 9. Edit/Delete Tools
**Purpose**: Modify or remove features after creation

**Features**:
- Identify tool (click feature to see properties)
- Edit properties dialog
- Move/reposition features
- Delete confirmation
- Undo/redo support

**Implementation Notes**:
- Add context menu to all annotation layers
- "Edit Properties" reopens creation dialog
- "Delete" with confirmation prompt
- Store features with unique IDs

---

## Layer Organization

Create new layer group structure:

```
SAR Tracking (group)
├── POIs (existing - blue markers)
├── Casualties (existing - red markers)
├── Text Labels (new - text annotations)
├── Search Sectors (new - wedge shapes)
├── Search Areas (new - polygons)
├── Range Rings (new - circles)
├── Bearing Lines (new - directional lines)
├── Lines (new - polylines)
├── Imported Tracks (new - GPX imports)
├── Current Positions (existing)
└── Breadcrumbs (existing)
```

**Layer Ordering Logic**:
- Labels on top (always visible)
- Markers next (POIs, Casualties)
- Sectors and search areas (semi-transparent)
- Lines and bearing lines
- Range rings (most transparent)
- Tracks at bottom
- Current positions and breadcrumbs below annotations

---

## Data Model

### Memory Layer Schema

#### Lines Layer
```python
fields = [
    QgsField("id", 10),           # String - unique ID
    QgsField("name", 10),         # String - line name
    QgsField("description", 10),  # String - notes
    QgsField("color", 10),        # String - hex color
    QgsField("width", 2),         # Int - line width
    QgsField("distance_m", 6),    # Double - length in meters
    QgsField("created", 10),      # String - timestamp
]
```

#### Search Areas Layer
```python
fields = [
    QgsField("id", 10),           # String - unique ID
    QgsField("name", 10),         # String - segment name
    QgsField("team", 10),         # String - assigned team
    QgsField("status", 10),       # String - Planned/InProgress/Complete
    QgsField("priority", 10),     # String - High/Medium/Low
    QgsField("color", 10),        # String - hex color
    QgsField("area_sqkm", 6),     # Double - area in km²
    QgsField("notes", 10),        # String - additional info
    QgsField("created", 10),      # String - timestamp
]
```

#### Range Rings Layer
```python
fields = [
    QgsField("id", 10),           # String - unique ID
    QgsField("center_lat", 6),    # Double - center latitude
    QgsField("center_lon", 6),    # Double - center longitude
    QgsField("radius_m", 6),      # Double - radius in meters
    QgsField("label", 10),        # String - ring label
    QgsField("color", 10),        # String - hex color
    QgsField("created", 10),      # String - timestamp
]
```

#### Bearing Lines Layer
```python
fields = [
    QgsField("id", 10),           # String - unique ID
    QgsField("origin_lat", 6),    # Double
    QgsField("origin_lon", 6),    # Double
    QgsField("bearing", 6),       # Double - degrees
    QgsField("distance_m", 6),    # Double
    QgsField("label", 10),        # String
    QgsField("color", 10),        # String
    QgsField("created", 10),      # String
]
```

#### Sectors Layer
```python
fields = [
    QgsField("id", 10),           # String - unique ID
    QgsField("center_lat", 6),    # Double
    QgsField("center_lon", 6),    # Double
    QgsField("start_bearing", 6), # Double - degrees
    QgsField("end_bearing", 6),   # Double - degrees
    QgsField("radius_m", 6),      # Double
    QgsField("label", 10),        # String
    QgsField("priority", 10),     # String
    QgsField("color", 10),        # String
    QgsField("area_sqkm", 6),     # Double
    QgsField("created", 10),      # String
]
```

---

## UI Design

### SAR Panel Updates

Add new collapsible section: **"Drawing Tools"**

```
╔══════════════════════════════════════╗
║ Drawing Tools                  ▼     ║
╠══════════════════════════════════════╣
║ [➕ Add POI]    [🔴 Add Casualty]    ║
║ [📏 Draw Line]  [⬟ Search Area]     ║
║ [🎯 Range Rings] [➡️ Bearing Line]   ║
║ [🥧 Search Sector] [📝 Add Label]    ║
║ [📂 Import GPX]                      ║
╠══════════════════════════════════════╣
║ Active Tool: [None]                  ║
║ [❌ Cancel Drawing]                  ║
╚══════════════════════════════════════╝
```

### Status Bar Integration

When a drawing tool is active:
```
Click to draw | Right-click to finish | ESC to cancel | WGS84: ... | Irish Grid: ...
```

---

## Implementation Order (Recommended)

### Sprint 1: Core Drawing Infrastructure (Week 1)
1. Create layer structure and initialization
2. Build base MapTool class for drawing
3. Implement Line Tool (simplest geometry)
4. Test coordinate conversion integration

### Sprint 2: Search Area Planning (Week 2)
5. Implement Polygon/Search Area Tool
6. Implement Range Ring Tool
7. Add area calculations
8. Test with sample search scenarios

### Sprint 3: Direction-Finding Tools (Week 3)
9. Implement Bearing Line Tool
10. Implement Sector/Wedge Tool
11. Add bearing calculations and display
12. Test directional tools

### Sprint 4: Enhancement & Polish (Week 4)
13. Implement Text Annotation Tool
14. Add GPX Import functionality
15. Implement Edit/Delete features
16. Add context menus
17. Polish UI and styling
18. Comprehensive testing

---

## Qt5/Qt6 Compatibility Checklist

For each new tool, ensure:
- [ ] No direct `Qt.SomeEnum` usage (use `utils/qt_compat.py`)
- [ ] No `QVariant.Type` usage (use integer constants)
- [ ] All imports use `qgis.PyQt` (not `PyQt5`/`PyQt6`)
- [ ] QSettings values handled with explicit type conversion
- [ ] Test on both Qt5 and Qt6 if possible

---

## Testing Plan

### Manual Testing Scenarios

**Line Tool**:
- [ ] Draw simple 2-point line
- [ ] Draw complex multi-point line
- [ ] Verify distance calculation
- [ ] Test coordinate entry mode
- [ ] Check styling options

**Search Area Tool**:
- [ ] Draw simple polygon
- [ ] Draw complex polygon
- [ ] Verify area calculation
- [ ] Test status changes
- [ ] Check semi-transparent fill

**Range Rings**:
- [ ] Single ring from click
- [ ] Multiple rings from coordinates
- [ ] Time-based ring calculation
- [ ] Verify radius measurements

**Bearing Lines**:
- [ ] Single bearing from click
- [ ] Multiple bearings from coordinates
- [ ] Magnetic declination correction
- [ ] Verify bearing angles

**Sectors**:
- [ ] Draw narrow sector (<90°)
- [ ] Draw wide sector (>180°)
- [ ] Verify area calculation
- [ ] Check transparency

**Text Labels**:
- [ ] Place simple label
- [ ] Multi-line text
- [ ] Different font sizes
- [ ] Background options

**GPX Import**:
- [ ] Import single track
- [ ] Import multiple tracks
- [ ] Verify statistics
- [ ] Check styling

**Edit/Delete**:
- [ ] Identify feature by clicking
- [ ] Edit feature properties
- [ ] Delete feature
- [ ] Verify undo/redo

### Integration Testing

- [ ] All tools work with Irish Grid coordinates
- [ ] All tools work with WGS84 coordinates
- [ ] Coordinate converter integrates with tools
- [ ] Features persist in QGIS project
- [ ] Auto-save includes new features
- [ ] Layer ordering maintained
- [ ] No conflicts with existing POI/Casualty tools

---

## Documentation Updates

When Phase 3 is complete, update:
- [ ] README.md - Add Phase 3 features to feature list
- [ ] TODO.md - Mark Phase 3 as complete
- [ ] Add Phase 3 screenshots/examples
- [ ] Create user guide for drawing tools
- [ ] Update keyboard shortcuts reference

---

## Known Challenges & Solutions

### Challenge 1: Coordinate System Consistency
**Issue**: Users need to work in both Irish Grid and WGS84
**Solution**: All dialogs offer both input methods; use coordinate converter helper

### Challenge 2: Memory-Only Storage
**Issue**: Features lost when QGIS closes
**Solution**: For now, rely on auto-save of QGIS project; Phase 4 will add database

### Challenge 3: Complex Geometries
**Issue**: Sectors/wedges require arc geometry
**Solution**: Use QgsCircularString or approximate with line segments

### Challenge 4: Tool State Management
**Issue**: Multiple map tools, need clear activation/deactivation
**Solution**: Single active tool at a time; clear visual feedback; ESC to cancel

---

## Success Criteria

Phase 3 will be considered complete when:
- ✅ All Priority 1 & 2 tools implemented and tested
- ✅ Tools work with both coordinate systems
- ✅ Features can be created, edited, and deleted
- ✅ Measurements (distance, bearing, area) are accurate
- ✅ Layer organization is clear and logical
- ✅ UI is intuitive for non-GIS users
- ✅ Qt5/Qt6 compatibility maintained
- ✅ Documentation updated
- ✅ Testing scenarios all pass
- ✅ Kerry Mountain Rescue team provides positive feedback

---

## Next Steps

1. **Review this plan** with stakeholders
2. **Clarify priorities** - Which tools are most urgent?
3. **Set up development environment** for testing
4. **Begin Sprint 1** - Core drawing infrastructure
5. **Iterate based on feedback** from SAR team

---

**Questions for Discussion:**
- Should we implement all tools, or focus on a subset first?
- Are there any CalTopo features we missed?
- Any Kerry Mountain Rescue-specific requirements?
- Should we add export formats (KML, GeoJSON)?
- How should "team colors" be configured?
