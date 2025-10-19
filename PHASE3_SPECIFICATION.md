# SAR Tracker - Phase 3 Complete Technical Specification

**Version:** 3.0
**Date:** 2025-10-18
**Status:** ✅ READY FOR IMPLEMENTATION
**Estimated Duration:** 4 weeks (20 working days)

---

## 📋 Document Purpose

This specification is **complete and self-contained**. A fresh instance of Claude Code can use this document to implement Phase 3 with full confidence. It includes:

- ✅ Complete research findings
- ✅ Detailed feature specifications
- ✅ Working code examples
- ✅ Known issues and gotchas
- ✅ Qt5/Qt6 compatibility guidelines
- ✅ Phased implementation plan
- ✅ Testing requirements
- ✅ Success criteria

---

## 📊 Executive Summary

### What Is Phase 3?

Phase 3 adds **CalTopo-style drawing and annotation tools** to the SAR Tracker QGIS plugin, transforming it from a tracking system into a complete search planning and operations platform.

### Key Additions

1. **SAR Terminology Updates** - Standardize UI to match international SAR conventions
2. **Lost Person Behavior (LPB) Integration** - Auto-generate statistical search areas
3. **Drawing Tools** - Lines, polygons, range rings, bearing lines, sectors
4. **Search Management** - Status tracking, team assignments
5. **Enhanced Markers** - IPP/LKP, clues, hazards with proper categorization

### Research Foundation

This spec is based on comprehensive research:
- **CalTopo/SARTopo** analysis (professional SAR mapping platform)
- **QGIS PyQGIS capabilities** (confirmed QGIS provides 80% of infrastructure)
- **International SAR standards** (IAMSAR, ICS, Lost Person Behavior statistics)
- **Working code examples** (Range Ring and Sector tools already implemented)

### Confidence Level: 🟢 Very High

All technical unknowns resolved. Clear path forward. Ready to build.

---

## 🎯 Phase 3 Goals

###Primary Objectives

1. **Update terminology** to match SAR standards (IPP, LKP, POA, POD)
2. **Integrate LPB statistics** for automatic search area generation
3. **Implement 7 core drawing tools** (lines, polygons, rings, bearings, sectors, labels, GPX)
4. **Add search management** (status tracking, team assignments)
5. **Enhance marker system** (IPP/LKP, clues with types, hazards)
6. **Maintain Qt5/Qt6 compatibility** throughout

### Success Criteria

- ✅ All SAR terminology standardized
- ✅ LPB integration functional with subject categories
- ✅ All 7 drawing tools working and tested
- ✅ Search areas track status and team assignments
- ✅ Clue and hazard marking fully operational
- ✅ Qt5/Qt6 compatible (follows established patterns)
- ✅ Documentation complete
- ✅ User testing successful

---

## 📚 Research Summary

### CalTopo Analysis

CalTopo (SARTopo) is the industry-standard SAR mapping platform. Phase 3 implements equivalent features:

| CalTopo Feature | Our Implementation | Priority |
|----------------|-------------------|----------|
| Markers (IPP/LKP/Clues) | Enhanced marker system | Critical |
| Lines | Line drawing tool | High |
| Polygons (Search areas) | Search area tool with status | Critical |
| Range Rings | Range ring tool (already built!) | High |
| Bearing Lines | Bearing line tool | Medium |
| Sectors | Sector tool (already built!) | Medium |
| Text Labels | Text annotation tool | Medium |
| GPX Import | GPX import feature | Medium |

**Reference:** `research/caltopo_research_report.md` (in repo)

### SAR Standards & Requirements

#### Critical Terminology Changes

| Current | Should Be | Why |
|---------|-----------|-----|
| POI | **IPP/LKP** | Initial Planning Point / Last Known Position (standard SAR terms) |
| Casualty | **Clue** | Casualties are a specific type of clue (expand to footprints, clothing, etc.) |
| - | **Status tracking** | Essential for search coordination |
| - | **Team assignment** | Required for multi-team operations |

#### Lost Person Behavior (LPB) Statistics

**CRITICAL FEATURE:** Different lost person categories have statistically predictable search distances.

| Subject Category | 50% Found Within | 95% Found Within | Use Case |
|-----------------|------------------|------------------|----------|
| **Child (1-3 yrs)** | 0.3 km | 1.9 km | Wandered from home |
| **Child (4-6 yrs)** | 0.5 km | 2.4 km | Playground/park |
| **Child (7-12 yrs)** | 1.3 km | 3.8 km | Older child missing |
| **Hiker** | 2.0 km | 8.0 km | Adult on trail |
| **Hunter** | 3.0 km | 10.0 km | Hunting activity |
| **Elderly** | 0.5 km | 2.5 km | Elderly adult |
| **Dementia** | 0.3 km | 2.0 km | Dementia patient |
| **Despondent** | 0.5 km | 3.0 km | Suicidal intent |
| **Autistic** | 0.6 km | 2.0 km | Autistic individual |

**Implementation:** When marking IPP/LKP, user selects subject category → system auto-generates range rings at 25%, 50%, 75%, 95% probability distances.

**Reference:** `research/SAR_REQUIREMENTS_REPORT.md` (46 pages, in repo)

### QGIS Capabilities

**Good News:** QGIS provides ~80% of the infrastructure we need via PyQGIS.

#### What QGIS Provides (Leverage These!)

- ✅ **QgsMapTool** - Robust base class for interactive map tools
- ✅ **QgsRubberBand** - Real-time visual feedback during drawing
- ✅ **QgsGeometry** - Complete geometry creation (circles, polygons, lines, arcs)
- ✅ **QgsDistanceArea** - Accurate geodesic distance/bearing calculations
- ✅ **QgsCoordinateTransform** - Seamless CRS transformation (Irish Grid ↔ WGS84)
- ✅ **Memory Layers** - Perfect for temporary features
- ✅ **Symbology Engine** - Professional styling capabilities

#### What We Build (SAR-Specific Features)

- 🔨 Range rings at LPB-based distances
- 🔨 Search sectors with probability zones
- 🔨 Team assignment and status tracking
- 🔨 Hazard marking system
- 🔨 Enhanced clue management
- 🔨 Search pattern generation (future)

**Key Insight:** Build on QGIS's foundation, don't reinvent the wheel.

**Reference:** `docs/QGIS_DRAWING_CAPABILITIES.md` (technical guide, in repo)

### Working Code Examples

Research agents created **production-ready** implementations:

1. **`maptools/range_ring_tool.py`** - Complete range ring tool (333 lines)
   - Click to place center
   - Multiple concentric rings
   - Geodesic calculations
   - Preview during mouse movement
   - **Ready to integrate!**

2. **`maptools/sector_tool.py`** - Complete sector/wedge tool (428 lines)
   - Three-click workflow (center → radius → angle)
   - Real-time preview
   - Area calculations
   - Proper geometry creation
   - **Ready to integrate!**

These serve as reference implementations for other tools.

---

## ⚠️ Critical Issues & Gotchas

### Qt5/Qt6 Compatibility

**CRITICAL:** Plugin must support both Qt5 (QGIS 3.x) and Qt6 (QGIS 3.40+).

#### The Qt6 Breaking Changes

Qt6 moved enums into nested classes, breaking Qt5 code:

```python
# ❌ Qt5 style (breaks in Qt6)
from qgis.PyQt.QtCore import Qt
self.setCursor(QCursor(Qt.CrossCursor))  # AttributeError in Qt6!
if state == Qt.Checked:  # AttributeError in Qt6!

# ✅ Correct way (works in both)
from utils.qt_compat import CrossCursor, Checked
self.setCursor(QCursor(CrossCursor))  # Works everywhere
if state == Checked:  # Works everywhere
```

#### Compatibility Module Already Exists

File: `utils/qt_compat.py` (already in repo)

Provides 52 constants covering:
- DockWidgetArea (6 constants)
- CheckState (3 constants)
- CursorShape (16 constants)
- AlignmentFlag (8 constants)
- MouseButton (6 constants)
- Key (7 constants)
- Orientation (2 constants)
- WindowType (4 constants)

**Usage:**
```python
from utils.qt_compat import (
    CrossCursor, LeftDockWidgetArea, RightDockWidgetArea,
    Checked, Unchecked, AlignLeft, AlignCenter
)
```

#### Qt5/Qt6 Compliance Checklist

For **EVERY** new file you create:

- [ ] Import Qt constants from `utils.qt_compat`, NEVER from `Qt` directly
- [ ] Use integer constants for QgsField types (NOT `QVariant.String`)
  ```python
  # ❌ Wrong (Qt6 breaks)
  QgsField("name", QVariant.String)

  # ✅ Correct
  QgsField("name", 10)  # 10 = String, 2 = Int, 6 = Double
  ```
- [ ] Handle QSettings return values safely
  ```python
  # ❌ Wrong (Qt6 can return None or different types)
  value = QSettings().value('key')
  result = value[0:2]  # May crash!

  # ✅ Correct
  value = QSettings().value('key')
  if value:
      result = str(value)  # Explicit conversion
  else:
      result = 'default'
  ```
- [ ] All imports use `qgis.PyQt` (NOT `PyQt5` or `PyQt6`)
- [ ] Test on both Qt5 and Qt6 if possible

**Reference:** `README.md` lines 286-398 (Qt5/Qt6 compatibility section)

### QgsField Type Constants

**CRITICAL:** QVariant enum removed in Qt6.

```python
# Type mappings (use integers)
10 = String (QVariant.String in Qt5)
2  = Int (QVariant.Int in Qt5)
6  = Double (QVariant.Double in Qt5)
1  = Bool (QVariant.Bool in Qt5)
14 = Date (QVariant.Date in Qt5)
16 = DateTime (QVariant.DateTime in Qt5)
```

**Example:**
```python
from qgis.core import QgsField

fields = [
    QgsField("id", 10),          # String
    QgsField("name", 10),        # String
    QgsField("count", 2),        # Int
    QgsField("distance_m", 6),   # Double
    QgsField("enabled", 1),      # Bool
    QgsField("timestamp", 10),   # String (format as ISO datetime)
]
```

### Coordinate System Handling

**Current Implementation (Good):**
- Irish Grid (ITM): EPSG:29903
- WGS84: EPSG:4326
- Conversion handled by existing `utils/coordinates.py`

**For All New Tools:**
- Always perform geodesic calculations in WGS84
- Use `QgsCoordinateTransform` for CRS conversions
- Use `QgsDistanceArea` for accurate distance/bearing
- Follow pattern from existing `MarkerMapTool` (lines 38-72)

### Memory Layer Persistence

**IMPORTANT:** Features are currently memory-only.

- Memory layers created by drawing tools
- Features persist in QGIS project saves (.qgs/.qgz files)
- **Lost when QGIS closes if project not saved**
- Auto-save feature helps (Phase 2, already implemented)
- Phase 4 will add database persistence

**User Communication:** Document this limitation clearly in UI tooltips/docs.

### Layer Ordering

**Critical for Usability:** Layer stacking order affects visibility.

**Correct Order (top to bottom):**
```
SAR Tracking (group)
├── Text Labels (always on top)
├── IPP/LKP Markers
├── Clues
├── Hazards
├── Search Sectors (semi-transparent)
├── Search Areas (semi-transparent)
├── Bearing Lines
├── Lines
├── Range Rings (most transparent)
├── Imported Tracks
├── Current Positions
└── Breadcrumbs (bottom)
```

**Implementation:** Use `insertLayer(index, layer)` on group, not `addLayer()`.

**Reference:** `controllers/layers_controller.py` lines 50-61 (layer group management)

---

## 📐 Architecture Overview

### Current Codebase Structure

```
sartracker/
├── __init__.py
├── sartracker.py                 # Main plugin class
├── metadata.txt
├── icon.png
├── resources.py
│
├── ui/
│   ├── __init__.py
│   ├── sar_panel.py             # Main control panel
│   ├── marker_dialog.py         # POI/Casualty dialog
│   └── coordinate_converter_dialog.py
│
├── maptools/
│   ├── __init__.py
│   ├── marker_tool.py           # Click-to-place markers
│   ├── measure_tool.py          # Distance/bearing tool
│   ├── range_ring_tool.py       # ✅ Already built (Phase 3)
│   └── sector_tool.py           # ✅ Already built (Phase 3)
│
├── controllers/
│   ├── __init__.py
│   └── layers_controller.py     # Layer management
│
├── providers/
│   ├── __init__.py
│   ├── base.py
│   ├── csv.py                   # CSV data provider
│   └── http_traccar.py
│
└── utils/
    ├── __init__.py
    ├── coordinates.py           # Coordinate conversion
    └── qt_compat.py             # ✅ Qt5/Qt6 compatibility
```

### Phase 3 Additions (New Files)

```
sartracker/
├── maptools/
│   ├── base_drawing_tool.py     # 🆕 Base class for drawing tools
│   ├── line_tool.py             # 🆕 Line drawing
│   ├── polygon_tool.py          # 🆕 Search area/polygon drawing
│   ├── bearing_line_tool.py     # 🆕 Bearing/azimuth lines
│   ├── text_annotation_tool.py  # 🆕 Text labels
│   └── tool_registry.py         # 🆕 Tool activation management
│
├── ui/
│   ├── lpb_range_dialog.py      # 🆕 LPB range ring configuration
│   ├── search_area_dialog.py    # 🆕 Search area properties
│   ├── bearing_line_dialog.py   # 🆕 Bearing line input
│   ├── hazard_dialog.py         # 🆕 Hazard marker properties
│   └── clue_dialog.py           # 🆕 Enhanced clue properties
│
└── utils/
    ├── lpb_statistics.py        # 🆕 Lost Person Behavior data
    └── geometry_helpers.py      # 🆕 Geometry creation utilities
```

### Integration Points

#### Main Plugin (`sartracker.py`)

**Existing signals to connect:**
- Drawing tool button clicks → Activate appropriate map tool
- Tool completion → Add features to layers
- Dialog opened → Pre-fill with current data

**New signals needed:**
- `line_tool_requested`
- `search_area_requested`
- `range_rings_requested`
- `bearing_line_requested`
- `sector_requested`
- `text_label_requested`
- `gpx_import_requested`

#### SAR Panel (`ui/sar_panel.py`)

**Add new section: "Drawing Tools"**
- Insert after "Markers & Tools" section (around line 200)
- Collapsible QGroupBox
- Grid layout with tool buttons
- Active tool indicator
- Cancel button

#### Layers Controller (`controllers/layers_controller.py`)

**New methods needed:**
- `create_lines_layer()`
- `create_search_areas_layer()`
- `create_range_rings_layer()`
- `create_bearing_lines_layer()`
- `create_sectors_layer()`
- `create_text_labels_layer()`
- `add_line(name, points, **kwargs)`
- `add_search_area(name, polygon, status, team, **kwargs)`
- `add_bearing_line(origin, bearing, distance, **kwargs)`
- `update_search_area_status(area_id, new_status)`

---

## 🔨 Phase 3 Implementation Plan

### Timeline: 4 Weeks (20 Working Days)

```
Week 1: Foundation & Terminology Updates (5 days)
Week 2: Core Drawing Tools (5 days)
Week 3: Advanced SAR Features (5 days)
Week 4: Polish & Integration (5 days)
```

---

## 📅 Week 1: Foundation & Terminology

### Day 1: Terminology Updates & LPB Foundation

**Goal:** Update UI to use correct SAR terminology, create LPB statistics module

#### Task 1.1: Update Marker Dialog (2 hours)

**File:** `ui/marker_dialog.py`

**Changes:**
1. Update radio buttons from "POI" / "Casualty" to:
   - "IPP/LKP" (Initial Planning Point / Last Known Position)
   - "Clue"
   - "Hazard"

2. Add subject category dropdown (shown when IPP/LKP selected):
   ```python
   self.subject_category_combo = QComboBox()
   categories = [
       "Child (1-3 years)",
       "Child (4-6 years)",
       "Child (7-12 years)",
       "Hiker",
       "Hunter",
       "Elderly",
       "Dementia Patient",
       "Despondent",
       "Autistic",
       "Other"
   ]
   self.subject_category_combo.addItems(categories)
   ```

3. Add clue type dropdown (shown when Clue selected):
   ```python
   clue_types = [
       "Footprint",
       "Clothing",
       "Equipment",
       "Witness Sighting",
       "Physical Evidence",
       "Other"
   ]
   ```

4. Add hazard type dropdown (shown when Hazard selected):
   ```python
   hazard_types = [
       "Cliff/Drop-off",
       "Water Hazard",
       "Bog/Peatland",
       "Dense Vegetation",
       "Wildlife Danger",
       "Weather Exposure",
       "Other"
   ]
   ```

5. Add confidence level for clues:
   ```python
   confidence_levels = ["Confirmed", "Probable", "Possible"]
   ```

**Testing:**
- [ ] Dialog opens correctly
- [ ] Dropdowns appear/hide based on marker type
- [ ] All options selectable
- [ ] Data returned correctly from `get_marker_data()`

#### Task 1.2: Create LPB Statistics Module (3 hours)

**New File:** `utils/lpb_statistics.py`

**Contents:**
```python
# -*- coding: utf-8 -*-
"""
Lost Person Behavior Statistics Module

Statistical data for search planning based on subject categories.
Data sources: "Lost Person Behavior" by Robert Koester, NASAR guidelines.
"""

class LPBStatistics:
    """Lost Person Behavior statistical data for search planning."""

    # Statistical distances in meters
    # Format: {category: {percentile: distance_in_meters}}
    STATISTICS = {
        'child_1_3': {
            'name': 'Child (1-3 years)',
            25: 100,    # 25% found within 100m
            50: 300,    # 50% found within 300m
            75: 700,    # 75% found within 700m
            95: 1900,   # 95% found within 1.9km
        },
        'child_4_6': {
            'name': 'Child (4-6 years)',
            25: 200,
            50: 500,
            75: 1100,
            95: 2400,
        },
        'child_7_12': {
            'name': 'Child (7-12 years)',
            25: 500,
            50: 1300,
            75: 2500,
            95: 3800,
        },
        'hiker': {
            'name': 'Hiker',
            25: 800,
            50: 2000,
            75: 4000,
            95: 8000,
        },
        'hunter': {
            'name': 'Hunter',
            25: 1200,
            50: 3000,
            75: 5500,
            95: 10000,
        },
        'elderly': {
            'name': 'Elderly',
            25: 200,
            50: 500,
            75: 1200,
            95: 2500,
        },
        'dementia': {
            'name': 'Dementia Patient',
            25: 100,
            50: 300,
            75: 800,
            95: 2000,
        },
        'despondent': {
            'name': 'Despondent',
            25: 200,
            50: 500,
            75: 1500,
            95: 3000,
        },
        'autistic': {
            'name': 'Autistic',
            25: 200,
            50: 600,
            75: 1200,
            95: 2000,
        },
    }

    @classmethod
    def get_distances(cls, category_key, percentiles=[25, 50, 75, 95]):
        """
        Get distances for a subject category.

        Args:
            category_key: String key (e.g., 'child_1_3', 'hiker')
            percentiles: List of percentiles to retrieve

        Returns:
            Dict mapping percentile to distance in meters
        """
        if category_key not in cls.STATISTICS:
            return None

        stats = cls.STATISTICS[category_key]
        return {p: stats[p] for p in percentiles if p in stats}

    @classmethod
    def get_category_from_display_name(cls, display_name):
        """
        Convert display name to category key.

        Args:
            display_name: Display name (e.g., "Child (1-3 years)")

        Returns:
            Category key (e.g., 'child_1_3') or None
        """
        for key, data in cls.STATISTICS.items():
            if data['name'] == display_name:
                return key
        return None

    @classmethod
    def get_all_categories(cls):
        """Get list of all category display names."""
        return [data['name'] for data in cls.STATISTICS.values()]
```

**Testing:**
- [ ] Can retrieve distances for all categories
- [ ] Display name to key mapping works
- [ ] Returns None for invalid categories

#### Task 1.3: Update UI Labels (1 hour)

**Files to update:**
- `ui/sar_panel.py` - Update button labels
- `sartracker.py` - Update status messages

**Changes:**
- "Add POI" button → "Add IPP/LKP"
- "Add Casualty" button → "Add Clue"
- Add "Add Hazard" button
- Status messages: "POI added" → "IPP/LKP added"

#### Task 1.4: Add Tooltips (1 hour)

Add explanatory tooltips for SAR terms:

```python
self.ipp_button.setToolTip(
    "IPP (Initial Planning Point) / LKP (Last Known Position)\n"
    "The starting point for search planning, typically where the\n"
    "subject was last reliably seen or located."
)
```

**Testing:**
- [ ] All new terminology visible in UI
- [ ] Tooltips display on hover
- [ ] Messages updated in status bar

### Day 2: Base Drawing Tool Infrastructure

**Goal:** Create reusable base classes and tool management system

#### Task 2.1: Base Drawing Tool Class (3 hours)

**New File:** `maptools/base_drawing_tool.py`

```python
# -*- coding: utf-8 -*-
"""
Base Drawing Tool

Abstract base class for all SAR drawing tools.
Provides common functionality for coordinate transformation,
preview management, and tool lifecycle.
"""

from qgis.core import (
    QgsPointXY, QgsCoordinateReferenceSystem, QgsCoordinateTransform,
    QgsProject, QgsDistanceArea
)
from qgis.gui import QgsMapTool, QgsRubberBand
from qgis.PyQt.QtCore import pyqtSignal
from qgis.PyQt.QtGui import QCursor, QColor

# Import Qt5/Qt6 compatible constants
from ..utils.qt_compat import CrossCursor


class BaseDrawingTool(QgsMapTool):
    """
    Base class for SAR drawing tools.

    Provides:
    - Coordinate system handling (WGS84 ↔ Irish Grid ↔ Canvas CRS)
    - Distance/bearing calculations
    - Rubber band preview management
    - Common signal patterns

    Subclasses must implement:
    - canvasPressEvent()
    - canvasMoveEvent()
    - _create_feature() - Create the actual feature
    """

    # Signals
    drawing_complete = pyqtSignal(object)  # Emits feature data
    drawing_cancelled = pyqtSignal()

    def __init__(self, canvas):
        """
        Initialize base drawing tool.

        Args:
            canvas: QGIS map canvas
        """
        super().__init__(canvas)
        self.canvas = canvas
        self.setCursor(QCursor(CrossCursor))

        # Coordinate systems
        self.wgs84 = QgsCoordinateReferenceSystem("EPSG:4326")
        self.itm = QgsCoordinateReferenceSystem("EPSG:29903")  # Irish Grid

        # Distance calculator (geodesic)
        self.distance_calc = QgsDistanceArea()
        self.distance_calc.setSourceCrs(
            self.wgs84,
            QgsProject.instance().transformContext()
        )
        self.distance_calc.setEllipsoid('WGS84')

        # Rubber bands for preview
        self.rubber_bands = []

        # State
        self.is_active = False

    def transform_to_wgs84(self, point):
        """
        Transform point from canvas CRS to WGS84.

        Args:
            point: QgsPointXY in canvas CRS

        Returns:
            QgsPointXY in WGS84
        """
        canvas_crs = self.canvas.mapSettings().destinationCrs()
        if canvas_crs.authid() == "EPSG:4326":
            return point

        transform = QgsCoordinateTransform(
            canvas_crs,
            self.wgs84,
            QgsProject.instance()
        )
        return transform.transform(point)

    def transform_to_itm(self, point):
        """
        Transform point from canvas CRS to Irish Grid (ITM).

        Args:
            point: QgsPointXY in canvas CRS

        Returns:
            QgsPointXY in ITM
        """
        canvas_crs = self.canvas.mapSettings().destinationCrs()
        if canvas_crs.authid() == "EPSG:29903":
            return point

        transform = QgsCoordinateTransform(
            canvas_crs,
            self.itm,
            QgsProject.instance()
        )
        return transform.transform(point)

    def transform_from_wgs84(self, point):
        """
        Transform point from WGS84 to canvas CRS.

        Args:
            point: QgsPointXY in WGS84

        Returns:
            QgsPointXY in canvas CRS
        """
        canvas_crs = self.canvas.mapSettings().destinationCrs()
        if canvas_crs.authid() == "EPSG:4326":
            return point

        transform = QgsCoordinateTransform(
            self.wgs84,
            canvas_crs,
            QgsProject.instance()
        )
        return transform.transform(point)

    def calculate_distance(self, point1_wgs84, point2_wgs84):
        """
        Calculate geodesic distance between two points.

        Args:
            point1_wgs84: First point in WGS84
            point2_wgs84: Second point in WGS84

        Returns:
            Distance in meters
        """
        return self.distance_calc.measureLine(point1_wgs84, point2_wgs84)

    def calculate_bearing(self, point1_wgs84, point2_wgs84):
        """
        Calculate bearing from point1 to point2.

        Args:
            point1_wgs84: Start point in WGS84
            point2_wgs84: End point in WGS84

        Returns:
            Bearing in degrees (0-360, where 0 = North)
        """
        import math

        lat1 = math.radians(point1_wgs84.y())
        lat2 = math.radians(point2_wgs84.y())
        lon1 = math.radians(point1_wgs84.x())
        lon2 = math.radians(point2_wgs84.x())

        dlon = lon2 - lon1

        x = math.sin(dlon) * math.cos(lat2)
        y = (math.cos(lat1) * math.sin(lat2) -
             math.sin(lat1) * math.cos(lat2) * math.cos(dlon))

        bearing = math.atan2(x, y)
        bearing = math.degrees(bearing)

        # Normalize to 0-360
        return (bearing + 360) % 360

    def clear_rubber_bands(self):
        """Clear all rubber band previews."""
        for band in self.rubber_bands:
            self.canvas.scene().removeItem(band)
        self.rubber_bands = []

    def activate(self):
        """Called when tool is activated."""
        super().activate()
        self.is_active = True
        self.canvas.setCursor(QCursor(CrossCursor))
        self.clear_rubber_bands()

    def deactivate(self):
        """Called when tool is deactivated."""
        super().deactivate()
        self.is_active = False
        self.clear_rubber_bands()

    def keyPressEvent(self, event):
        """Handle keyboard input."""
        # ESC key cancels drawing
        from ..utils.qt_compat import Key_Escape
        if event.key() == Key_Escape:
            self.cancel()
            event.ignore()

    def cancel(self):
        """Cancel current drawing operation."""
        self.clear_rubber_bands()
        self.drawing_cancelled.emit()

    def isZoomTool(self):
        """Return False - drawing tools are not zoom tools."""
        return False

    def isEditTool(self):
        """Return True - drawing tools are editing tools."""
        return True
```

**Testing:**
- [ ] Can subclass and override methods
- [ ] Coordinate transformations work correctly
- [ ] Distance/bearing calculations accurate
- [ ] Rubber bands clear properly
- [ ] ESC key cancels drawing

#### Task 2.2: Tool Registry (2 hours)

**New File:** `maptools/tool_registry.py`

```python
# -*- coding: utf-8 -*-
"""
Tool Registry

Manages activation and deactivation of SAR drawing tools.
Ensures only one tool active at a time.
"""

from qgis.PyQt.QtCore import QObject, pyqtSignal


class ToolRegistry(QObject):
    """
    Central registry for managing SAR drawing tools.

    Ensures:
    - Only one tool active at a time
    - Proper cleanup when switching tools
    - Tool state tracking

    Signals:
        tool_activated: Emitted when a tool is activated (tool_name)
        tool_deactivated: Emitted when a tool is deactivated (tool_name)
    """

    tool_activated = pyqtSignal(str)
    tool_deactivated = pyqtSignal(str)

    def __init__(self, canvas):
        """
        Initialize tool registry.

        Args:
            canvas: QGIS map canvas
        """
        super().__init__()
        self.canvas = canvas
        self.tools = {}
        self.active_tool_name = None
        self.active_tool = None

    def register_tool(self, name, tool_instance):
        """
        Register a drawing tool.

        Args:
            name: Unique tool name (e.g., 'line', 'polygon', 'range_ring')
            tool_instance: Instance of a map tool
        """
        self.tools[name] = tool_instance

    def activate_tool(self, name):
        """
        Activate a drawing tool by name.

        Args:
            name: Tool name to activate

        Returns:
            bool: True if activated successfully
        """
        if name not in self.tools:
            return False

        # Deactivate current tool
        if self.active_tool:
            self.canvas.unsetMapTool(self.active_tool)
            self.tool_deactivated.emit(self.active_tool_name)

        # Activate new tool
        self.active_tool = self.tools[name]
        self.active_tool_name = name
        self.canvas.setMapTool(self.active_tool)
        self.tool_activated.emit(name)

        return True

    def deactivate_current(self):
        """Deactivate the currently active tool."""
        if self.active_tool:
            self.canvas.unsetMapTool(self.active_tool)
            self.tool_deactivated.emit(self.active_tool_name)
            self.active_tool = None
            self.active_tool_name = None

    def get_active_tool_name(self):
        """
        Get name of currently active tool.

        Returns:
            str: Tool name or None
        """
        return self.active_tool_name

    def is_tool_active(self, name):
        """
        Check if a specific tool is active.

        Args:
            name: Tool name to check

        Returns:
            bool: True if tool is active
        """
        return self.active_tool_name == name
```

**Testing:**
- [ ] Can register multiple tools
- [ ] Only one tool active at a time
- [ ] Tool switching works correctly
- [ ] Signals emitted properly

### Day 3-4: Update Layers Controller

**Goal:** Add layer management for new drawing tools

#### Task 3.1: Add New Layer Creation Methods (4 hours)

**File:** `controllers/layers_controller.py`

**Add after existing layer constants:**
```python
LINE_LAYER_NAME = "Lines"
SEARCH_AREAS_LAYER_NAME = "Search Areas"
RANGE_RINGS_LAYER_NAME = "Range Rings"
BEARING_LINES_LAYER_NAME = "Bearing Lines"
SECTORS_LAYER_NAME = "Search Sectors"
TEXT_LABELS_LAYER_NAME = "Text Labels"
HAZARDS_LAYER_NAME = "Hazards"
```

**New methods:**
```python
def _get_or_create_lines_layer(self):
    """Get or create Lines layer."""
    layer = self.project.mapLayersByName(self.LINE_LAYER_NAME)
    if layer:
        return layer[0]

    # Create memory layer
    layer = QgsVectorLayer(
        "LineString?crs=EPSG:4326"
        "&field=id:string"
        "&field=name:string"
        "&field=description:string"
        "&field=color:string"
        "&field=width:integer"
        "&field=distance_m:double"
        "&field=created:string",
        self.LINE_LAYER_NAME,
        "memory"
    )

    # Style layer
    self._style_lines_layer(layer)

    # Add to project in correct position
    group = self.get_or_create_layer_group()
    self.project.addMapLayer(layer, False)
    group.insertLayer(5, layer)  # Position in layer stack

    return layer

def add_line(self, name, points_wgs84, description="", color="#FF0000", width=2):
    """
    Add a line feature.

    Args:
        name: Line name
        points_wgs84: List of QgsPointXY in WGS84
        description: Optional description
        color: Hex color string
        width: Line width in pixels

    Returns:
        str: Feature ID
    """
    layer = self._get_or_create_lines_layer()

    # Calculate distance
    total_distance = 0
    for i in range(len(points_wgs84) - 1):
        dist = self._calculate_distance(points_wgs84[i], points_wgs84[i+1])
        total_distance += dist

    # Create feature
    feature = QgsFeature(layer.fields())
    feature.setGeometry(QgsGeometry.fromPolylineXY(points_wgs84))

    import uuid
    from datetime import datetime

    feature.setAttributes([
        str(uuid.uuid4()),
        name,
        description,
        color,
        width,
        total_distance,
        datetime.now().isoformat()
    ])

    # Add to layer
    layer.startEditing()
    layer.addFeature(feature)
    layer.commitChanges()
    layer.triggerRepaint()

    return feature.id()
```

**Add similar methods for:**
- `_get_or_create_search_areas_layer()` + `add_search_area()`
- `_get_or_create_bearing_lines_layer()` + `add_bearing_line()`
- `_get_or_create_text_labels_layer()` + `add_text_label()`
- `_get_or_create_hazards_layer()` + `add_hazard()`

**Critical:** Search Areas layer needs status tracking:
```python
def _get_or_create_search_areas_layer(self):
    layer = QgsVectorLayer(
        "Polygon?crs=EPSG:4326"
        "&field=id:string"
        "&field=name:string"
        "&field=team:string"                # Team assignment
        "&field=status:string"              # Planned/Assigned/InProgress/Completed/Cleared
        "&field=priority:string"            # High/Medium/Low
        "&field=area_sqkm:double"
        "&field=POA:double"                 # Probability of Area (0-100)
        "&field=POD:double"                 # Probability of Detection (0-100)
        "&field=terrain:string"
        "&field=search_method:string"
        "&field=color:string"
        "&field=start_time:string"
        "&field=end_time:string"
        "&field=notes:string"
        "&field=created:string",
        self.SEARCH_AREAS_LAYER_NAME,
        "memory"
    )
    # ... styling with status-based colors
    return layer
```

**Testing:**
- [ ] All new layers created successfully
- [ ] Layers appear in correct order
- [ ] Features can be added to each layer
- [ ] Layer styling applies correctly

### Day 5: Update SAR Panel UI

**Goal:** Add Drawing Tools section to SAR Panel

#### Task 5.1: Add Drawing Tools Section (3 hours)

**File:** `ui/sar_panel.py`

**Add after "Markers & Tools" section (around line 200):**

```python
# Drawing Tools Section
drawing_group = QGroupBox("Drawing Tools")
drawing_layout = QVBoxLayout()

# Button grid (2 columns)
grid = QGridLayout()

self.line_btn = QPushButton("📏 Draw Line")
self.search_area_btn = QPushButton("🔷 Search Area")
self.range_rings_btn = QPushButton("⭕ Range Rings")
self.bearing_line_btn = QPushButton("➡️ Bearing Line")
self.sector_btn = QPushButton("🥧 Search Sector")
self.text_label_btn = QPushButton("📝 Add Label")
self.gpx_import_btn = QPushButton("📂 Import GPX")

# Add to grid (2 columns)
grid.addWidget(self.line_btn, 0, 0)
grid.addWidget(self.search_area_btn, 0, 1)
grid.addWidget(self.range_rings_btn, 1, 0)
grid.addWidget(self.bearing_line_btn, 1, 1)
grid.addWidget(self.sector_btn, 2, 0)
grid.addWidget(self.text_label_btn, 2, 1)
grid.addWidget(self.gpx_import_btn, 3, 0, 1, 2)  # Full width

drawing_layout.addLayout(grid)

# Active tool indicator
active_tool_layout = QHBoxLayout()
active_tool_layout.addWidget(QLabel("Active Tool:"))
self.active_tool_label = QLabel("[None]")
self.active_tool_label.setStyleSheet("font-weight: bold;")
active_tool_layout.addWidget(self.active_tool_label)
active_tool_layout.addStretch()
drawing_layout.addLayout(active_tool_layout)

# Cancel button
self.cancel_drawing_btn = QPushButton("❌ Cancel Drawing")
self.cancel_drawing_btn.setEnabled(False)
drawing_layout.addWidget(self.cancel_drawing_btn)

drawing_group.setLayout(drawing_layout)
layout.addWidget(drawing_group)
```

**Add new signals:**
```python
line_tool_requested = pyqtSignal()
search_area_requested = pyqtSignal()
range_rings_requested = pyqtSignal()
bearing_line_requested = pyqtSignal()
sector_requested = pyqtSignal()
text_label_requested = pyqtSignal()
gpx_import_requested = pyqtSignal()
cancel_drawing_requested = pyqtSignal()
```

**Connect buttons:**
```python
self.line_btn.clicked.connect(self.line_tool_requested.emit)
self.search_area_btn.clicked.connect(self.search_area_requested.emit)
self.range_rings_btn.clicked.connect(self.range_rings_requested.emit)
self.bearing_line_btn.clicked.connect(self.bearing_line_requested.emit)
self.sector_btn.clicked.connect(self.sector_requested.emit)
self.text_label_btn.clicked.connect(self.text_label_requested.emit)
self.gpx_import_btn.clicked.connect(self.gpx_import_requested.emit)
self.cancel_drawing_btn.clicked.connect(self.cancel_drawing_requested.emit)
```

**Add method to update active tool indicator:**
```python
def set_active_tool(self, tool_name):
    """
    Update active tool indicator.

    Args:
        tool_name: Name of active tool or None
    """
    if tool_name:
        self.active_tool_label.setText(f"[{tool_name}]")
        self.active_tool_label.setStyleSheet("font-weight: bold; color: blue;")
        self.cancel_drawing_btn.setEnabled(True)
    else:
        self.active_tool_label.setText("[None]")
        self.active_tool_label.setStyleSheet("font-weight: bold;")
        self.cancel_drawing_btn.setEnabled(False)
```

**Testing:**
- [ ] Drawing Tools section appears in panel
- [ ] All buttons visible and clickable
- [ ] Signals emit correctly
- [ ] Active tool indicator updates

---

## 📅 Week 2: Core Drawing Tools

### Day 6: Line Drawing Tool

**Goal:** Implement polyline drawing with distance calculation

#### Task 6.1: Line Tool Implementation (4 hours)

**New File:** `maptools/line_tool.py`

```python
# -*- coding: utf-8 -*-
"""
Line Drawing Tool

Click-to-draw polyline tool for marking paths, boundaries, and routes.
"""

from qgis.core import QgsGeometry, QgsWkbTypes
from qgis.gui import QgsRubberBand
from qgis.PyQt.QtCore import pyqtSignal
from qgis.PyQt.QtGui import QColor

from .base_drawing_tool import BaseDrawingTool


class LineTool(BaseDrawingTool):
    """
    Tool for drawing polylines on the map.

    Features:
    - Click to add points
    - Right-click or double-click to finish
    - Shows real-time distance
    - Preview rubber band during drawing

    Signals:
        line_complete: Emitted when line is finished (points, distance)
    """

    line_complete = pyqtSignal(list, float)  # points_wgs84, distance_m

    def __init__(self, canvas):
        super().__init__(canvas)

        # Drawing state
        self.points_canvas = []  # Points in canvas CRS
        self.points_wgs84 = []   # Points in WGS84
        self.rubber_band = None
        self.temp_rubber_band = None  # For mouse movement preview

    def canvasPressEvent(self, event):
        """Handle mouse click - add point to line."""
        # Right-click finishes the line
        from ..utils.qt_compat import RightButton
        if event.button() == RightButton:
            self.finish_line()
            return

        # Left-click adds a point
        point_canvas = self.toMapCoordinates(event.pos())
        point_wgs84 = self.transform_to_wgs84(point_canvas)

        self.points_canvas.append(point_canvas)
        self.points_wgs84.append(point_wgs84)

        # Update preview
        self.update_rubber_band()

    def canvasMoveEvent(self, event):
        """Handle mouse move - show preview of next segment."""
        if len(self.points_canvas) == 0:
            return

        # Get current cursor position
        cursor_point = self.toMapCoordinates(event.pos())

        # Update temporary rubber band showing cursor position
        self.update_temp_rubber_band(cursor_point)

    def canvasDoubleClickEvent(self, event):
        """Handle double-click - finish line."""
        self.finish_line()

    def update_rubber_band(self):
        """Update the main rubber band showing confirmed points."""
        if not self.rubber_band:
            self.rubber_band = QgsRubberBand(self.canvas, QgsWkbTypes.LineGeometry)
            self.rubber_band.setColor(QColor(255, 0, 0, 200))
            self.rubber_band.setWidth(2)

        self.rubber_band.reset(QgsWkbTypes.LineGeometry)
        for point in self.points_canvas:
            self.rubber_band.addPoint(point)

    def update_temp_rubber_band(self, cursor_point):
        """Update temporary rubber band showing preview to cursor."""
        if not self.temp_rubber_band:
            self.temp_rubber_band = QgsRubberBand(self.canvas, QgsWkbTypes.LineGeometry)
            self.temp_rubber_band.setColor(QColor(255, 0, 0, 100))
            self.temp_rubber_band.setWidth(1)
            self.temp_rubber_band.setLineStyle(2)  # Dashed

        # Draw line from last point to cursor
        self.temp_rubber_band.reset(QgsWkbTypes.LineGeometry)
        if self.points_canvas:
            self.temp_rubber_band.addPoint(self.points_canvas[-1])
            self.temp_rubber_band.addPoint(cursor_point)

    def finish_line(self):
        """Finish drawing the line and emit signal."""
        if len(self.points_wgs84) < 2:
            # Need at least 2 points
            self.cancel()
            return

        # Calculate total distance
        total_distance = 0
        for i in range(len(self.points_wgs84) - 1):
            dist = self.calculate_distance(self.points_wgs84[i], self.points_wgs84[i+1])
            total_distance += dist

        # Emit signal
        self.line_complete.emit(self.points_wgs84, total_distance)

        # Reset for next line
        self.reset()

    def reset(self):
        """Reset tool state for new line."""
        self.points_canvas = []
        self.points_wgs84 = []

        if self.rubber_band:
            self.canvas.scene().removeItem(self.rubber_band)
            self.rubber_band = None

        if self.temp_rubber_band:
            self.canvas.scene().removeItem(self.temp_rubber_band)
            self.temp_rubber_band = None

    def activate(self):
        """Activate tool."""
        super().activate()
        self.reset()

    def deactivate(self):
        """Deactivate tool."""
        super().deactivate()
        self.reset()
```

**Testing:**
- [ ] Click to add points
- [ ] Line preview appears
- [ ] Right-click finishes line
- [ ] Double-click finishes line
- [ ] Distance calculated correctly
- [ ] ESC cancels drawing

#### Task 6.2: Integrate Line Tool (2 hours)

**File:** `sartracker.py`

In `initGui()` after existing map tools:
```python
# Initialize drawing tools
from .maptools.line_tool import LineTool
from .maptools.tool_registry import ToolRegistry

self.tool_registry = ToolRegistry(self.iface.mapCanvas())

# Create and register line tool
self.line_tool = LineTool(self.iface.mapCanvas())
self.line_tool.line_complete.connect(self._on_line_complete)
self.tool_registry.register_tool('line', self.line_tool)

# Connect SAR Panel signal
self.sar_panel.line_tool_requested.connect(self._on_line_tool_requested)

# Connect tool registry signals to update UI
self.tool_registry.tool_activated.connect(self.sar_panel.set_active_tool)
self.tool_registry.tool_deactivated.connect(lambda: self.sar_panel.set_active_tool(None))
```

Add handler methods:
```python
def _on_line_tool_requested(self):
    """Handle line tool button click."""
    self.tool_registry.activate_tool('line')
    self.iface.messageBar().pushMessage(
        "SAR Tracker",
        "Click on map to draw line. Right-click to finish.",
        level=0,
        duration=5
    )

def _on_line_complete(self, points_wgs84, distance_m):
    """Handle line drawing completion."""
    # Show dialog for line properties
    from .ui.line_dialog import LineDialog

    dialog = LineDialog(distance_m, self.iface.mainWindow())
    result = dialog.exec_()

    if result == LineDialog.Accepted:
        data = dialog.get_line_data()

        # Add to map
        line_id = self.layers_controller.add_line(
            name=data['name'],
            points_wgs84=points_wgs84,
            description=data['description'],
            color=data['color'],
            width=data['width']
        )

        self.iface.messageBar().pushMessage(
            "SAR Tracker",
            f"Line '{data['name']}' added ({distance_m:.1f}m)",
            level=3,
            duration=3
        )

    # Deactivate tool
    self.tool_registry.deactivate_current()
```

**Testing:**
- [ ] Button activates tool
- [ ] Tool indicator updates
- [ ] Line added to map
- [ ] Layer created correctly

### Day 7: Polygon/Search Area Tool

**Goal:** Implement polygon drawing with status and team assignment

#### Task 7.1: Search Area Dialog (2 hours)

**New File:** `ui/search_area_dialog.py`

```python
# -*- coding: utf-8 -*-
"""
Search Area Properties Dialog

Dialog for configuring search area/polygon properties.
"""

from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLineEdit, QComboBox, QTextEdit, QDialogButtonBox,
    QColorDialog, QPushButton, QLabel, QSpinBox
)
from qgis.PyQt.QtGui import QColor


class SearchAreaDialog(QDialog):
    """Dialog for search area properties."""

    def __init__(self, area_sqkm, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Search Area Properties")
        self.setMinimumWidth(400)

        self.area_sqkm = area_sqkm
        self.selected_color = QColor(0, 100, 255, 100)  # Default blue

        self._setup_ui()

    def _setup_ui(self):
        """Build dialog UI."""
        layout = QVBoxLayout()

        # Form layout
        form = QFormLayout()

        # Name
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("e.g., Area Alpha, Zone 1")
        form.addRow("Name:", self.name_input)

        # Team assignment
        self.team_combo = QComboBox()
        self.team_combo.setEditable(True)
        self.team_combo.addItems([
            "Team 1",
            "Team 2",
            "Team 3",
            "K9 Unit",
            "Hasty Team",
            "Unassigned"
        ])
        form.addRow("Team:", self.team_combo)

        # Status (CRITICAL for SAR)
        self.status_combo = QComboBox()
        self.status_combo.addItems([
            "Planned",
            "Assigned",
            "In Progress",
            "Completed",
            "Cleared",
            "Suspended"
        ])
        form.addRow("Status:", self.status_combo)

        # Priority
        self.priority_combo = QComboBox()
        self.priority_combo.addItems(["High", "Medium", "Low"])
        self.priority_combo.setCurrentText("Medium")
        form.addRow("Priority:", self.priority_combo)

        # Area size (read-only)
        area_label = QLabel(f"{self.area_sqkm:.3f} km²")
        area_label.setStyleSheet("font-weight: bold;")
        form.addRow("Area:", area_label)

        # POA (Probability of Area)
        self.poa_spin = QSpinBox()
        self.poa_spin.setRange(0, 100)
        self.poa_spin.setValue(50)
        self.poa_spin.setSuffix("%")
        form.addRow("POA:", self.poa_spin)

        # Terrain type
        self.terrain_combo = QComboBox()
        self.terrain_combo.addItems([
            "Easy",
            "Moderate",
            "Difficult",
            "Extreme"
        ])
        form.addRow("Terrain:", self.terrain_combo)

        # Search method
        self.method_combo = QComboBox()
        self.method_combo.addItems([
            "Grid Search",
            "Contour Search",
            "Sound Sweep",
            "Hasty Search",
            "Other"
        ])
        form.addRow("Method:", self.method_combo)

        # Color picker
        color_layout = QHBoxLayout()
        self.color_btn = QPushButton("Choose Color")
        self.color_btn.clicked.connect(self._choose_color)
        self.color_preview = QLabel("     ")
        self.color_preview.setStyleSheet(
            f"background-color: {self.selected_color.name()}; border: 1px solid black;"
        )
        color_layout.addWidget(self.color_btn)
        color_layout.addWidget(self.color_preview)
        color_layout.addStretch()
        form.addRow("Color:", color_layout)

        # Notes
        self.notes_input = QTextEdit()
        self.notes_input.setMaximumHeight(80)
        self.notes_input.setPlaceholderText("Additional notes...")
        form.addRow("Notes:", self.notes_input)

        layout.addLayout(form)

        # Buttons
        button_box = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel
        )
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

        self.setLayout(layout)

        # Focus name field
        self.name_input.setFocus()

    def _choose_color(self):
        """Open color picker dialog."""
        color = QColorDialog.getColor(self.selected_color, self)
        if color.isValid():
            self.selected_color = color
            self.color_preview.setStyleSheet(
                f"background-color: {color.name()}; border: 1px solid black;"
            )

    def get_search_area_data(self):
        """
        Get search area data from dialog.

        Returns:
            dict with search area properties
        """
        return {
            'name': self.name_input.text() or "Unnamed Area",
            'team': self.team_combo.currentText(),
            'status': self.status_combo.currentText(),
            'priority': self.priority_combo.currentText(),
            'area_sqkm': self.area_sqkm,
            'POA': self.poa_spin.value(),
            'terrain': self.terrain_combo.currentText(),
            'search_method': self.method_combo.currentText(),
            'color': self.selected_color.name(),
            'notes': self.notes_input.toPlainText()
        }
```

**Testing:**
- [ ] Dialog opens
- [ ] All fields functional
- [ ] Color picker works
- [ ] Data returned correctly

#### Task 7.2: Polygon Tool Implementation (3 hours)

**New File:** `maptools/polygon_tool.py`

Similar to LineTool but creates closed polygon. Key differences:
- Minimum 3 points
- Auto-closes polygon
- Calculates area instead of distance

(Implementation similar to LineTool - reference base_drawing_tool.py patterns)

**Testing:**
- [ ] Click to draw polygon
- [ ] Right-click closes
- [ ] Area calculated
- [ ] Dialog shows and saves

### Day 8-9: Range Ring Integration & Polish

**Goal:** Integrate existing range ring tool, connect to LPB

#### Task 8.1: LPB Range Dialog (3 hours)

**New File:** `ui/lpb_range_dialog.py`

Dialog that shows:
- Subject category selector (links to LPB statistics)
- Auto-fills ring distances based on category
- Manual override option
- Displays probability percentiles (25%, 50%, 75%, 95%)

#### Task 8.2: Connect Range Rings to IPP Markers (2 hours)

When IPP/LKP marker created with subject category:
- Offer to auto-generate LPB ranges
- Use category to look up distances
- Create rings automatically

#### Task 8.3: Style Range Rings (1 hour)

- Semi-transparent fills
- Distance labels
- Color coding by percentile

**Testing:**
- [ ] LPB ranges generated correctly
- [ ] Manual distances work
- [ ] Labels visible
- [ ] Styling correct

### Day 10: Week 2 Integration & Testing

**Goal:** Ensure all Week 2 tools work together

- Integration testing
- Fix bugs
- Polish UI
- Update documentation

---

## 📅 Week 3: Advanced SAR Features

### Day 11-12: Bearing Line Tool

**Goal:** Implement direction-finding bearing lines

**Features:**
- Click origin OR enter coordinates
- Input bearing (0-360°)
- Input distance
- Magnetic declination support (~-4.5° for Ireland)
- Display true and magnetic bearings

**Files:**
- `maptools/bearing_line_tool.py`
- `ui/bearing_line_dialog.py`

### Day 13: Integrate Sector Tool

**Goal:** Integrate existing sector tool (already built!)

**Tasks:**
- Register in tool registry
- Add button handler
- Connect to layers controller
- Test integration

### Day 14: Hazard Marking System

**Goal:** Implement safety-critical hazard markers

**Features:**
- Hazard types (cliff, water, bog, vegetation, wildlife, weather)
- Orange/yellow warning colors
- Distinct icons per type
- Hazard zones (polygons)

**Files:**
- `ui/hazard_dialog.py` (update marker_dialog or create new)
- Update `layers_controller.py`

### Day 15: Enhanced Clue Management

**Goal:** Expand clue system beyond simple casualties

**Features:**
- Clue types (footprint, clothing, equipment, sighting, evidence)
- Confidence levels (confirmed, probable, possible)
- Auto-calculate distance/bearing from IPP
- Time found
- Photo attachment support (placeholder for Phase 4)

**Files:**
- `ui/clue_dialog.py`
- Update `layers_controller.py`

---

## 📅 Week 4: Polish & Completion

### Day 16: Text Annotation Tool

**Goal:** Add text labels to map

**Features:**
- Click to place
- Multi-line text
- Font size options
- Background/halo for visibility
- Rotation

### Day 17: GPX Import

**Goal:** Import GPS tracks from GPX files

**Features:**
- File picker
- Extract track metadata
- Display statistics
- Style differently from live tracking

### Day 18-19: Edit/Delete Features

**Goal:** Allow modification of drawn features

**Features:**
- Context menu on layers
- Identify tool (click to view properties)
- Edit properties dialog
- Delete with confirmation
- Move/reposition

### Day 20: Final Testing & Documentation

**Goal:** Comprehensive testing and documentation

- Integration testing all tools
- Update README.md
- Create user guide
- Record demo video
- Tag release

---

## ✅ Testing Requirements

### Unit Testing

Each tool must be tested for:
- [ ] Activation/deactivation
- [ ] Coordinate transformations
- [ ] Geometry creation
- [ ] Feature attribute setting
- [ ] Layer integration
- [ ] Qt5 and Qt6 compatibility

### Integration Testing

System-wide tests:
- [ ] All tools accessible from SAR Panel
- [ ] Only one tool active at a time
- [ ] Features persist in project saves
- [ ] Auto-save includes new features
- [ ] Layer ordering maintained
- [ ] No conflicts with existing features

### User Testing

Field testing scenarios:
- [ ] Mark IPP with subject category
- [ ] Generate LPB range rings
- [ ] Draw search areas with status
- [ ] Assign teams to areas
- [ ] Add clues and hazards
- [ ] Import GPX track
- [ ] Edit and delete features
- [ ] Save and reload project

### Performance Testing

- [ ] 100+ features render smoothly
- [ ] Drawing tools responsive
- [ ] No memory leaks
- [ ] Canvas refresh efficient

---

## 📊 Success Metrics

Phase 3 complete when:

- ✅ **Terminology**: All SAR terms standardized (IPP, LKP, POA, POD, status values)
- ✅ **LPB Integration**: Subject categories functional, auto-range generation works
- ✅ **7 Drawing Tools**: Line, Polygon, Range Ring, Bearing Line, Sector, Text Label, GPX Import all working
- ✅ **Search Management**: Status tracking and team assignment operational
- ✅ **Enhanced Markers**: IPP/LKP, clues with types, hazards with types
- ✅ **Qt5/Qt6 Compatible**: All new code follows compatibility guidelines
- ✅ **Documentation**: README, user guide, and technical docs updated
- ✅ **User Approval**: Kerry Mountain Rescue team provides positive feedback

---

## 📖 References & Resources

### Research Documents (In Repo)

1. **`research/caltopo_research_report.md`** - CalTopo feature analysis
2. **`research/SAR_REQUIREMENTS_REPORT.md`** - 46-page SAR standards document
3. **`docs/QGIS_DRAWING_CAPABILITIES.md`** - PyQGIS technical guide
4. **`MASTER_IMPLEMENTATION_PLAN.md`** - Original comprehensive plan
5. **`SAR_CRITICAL_FEATURES_CHECKLIST.md`** - Priority checklist

### Working Code Examples (In Repo)

6. **`maptools/range_ring_tool.py`** - Production-ready range ring tool (333 lines)
7. **`maptools/sector_tool.py`** - Production-ready sector tool (428 lines)

### External References

- IAMSAR Manual (International Aeronautical and Maritime SAR)
- "Lost Person Behavior" by Robert Koester
- Mountain Rescue Association guidelines
- CalTopo/SARTopo: https://caltopo.com
- QGIS PyQGIS Cookbook: https://docs.qgis.org/latest/en/docs/pyqgis_developer_cookbook/

---

## 🚀 Getting Started

### For Implementation

1. **Read this spec thoroughly** - Understand the full scope
2. **Review existing code** - Familiarize with current patterns
   - `maptools/marker_tool.py` - Map tool pattern
   - `controllers/layers_controller.py` - Layer management
   - `utils/qt_compat.py` - Qt5/Qt6 compatibility
3. **Follow the phased plan** - Week 1 → Week 2 → Week 3 → Week 4
4. **Test continuously** - Don't wait until end
5. **Maintain Qt5/Qt6 compatibility** - Use checklist for every file

### Quick Start Commands

```bash
# Navigate to plugin directory
cd ~/Documents/Qgis/sartracker

# Check existing structure
ls -la

# Start with Week 1, Day 1
# Edit ui/marker_dialog.py first
```

### Questions or Issues?

- Check research documents in repo
- Review working examples (range_ring_tool.py, sector_tool.py)
- Consult QGIS PyQGIS documentation
- Test frequently on both Qt5 and Qt6 if possible

---

## 📝 Final Notes

### Why This Spec is Complete

This specification is **self-contained and implementation-ready** because:

1. ✅ **Research is comprehensive** - All technical unknowns resolved
2. ✅ **Architecture is clear** - Existing patterns established
3. ✅ **Working examples exist** - Range ring and sector tools ready
4. ✅ **Qt5/Qt6 compatibility documented** - Gotchas identified and solved
5. ✅ **Phased plan provided** - Clear day-by-day breakdown
6. ✅ **Testing requirements defined** - Know when you're done
7. ✅ **Success criteria explicit** - Measurable completion

### Confidence Level: 🟢 Very High

A fresh instance of Claude Code can implement Phase 3 from this spec with high confidence. All blockers removed. Path forward is clear.

**Ready to build!** 🚀

---

**Document Version:** 3.0
**Last Updated:** 2025-10-18
**Status:** ✅ APPROVED FOR IMPLEMENTATION
**Estimated Completion:** 4 weeks from start date
