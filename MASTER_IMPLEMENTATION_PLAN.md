# SAR Tracker - Master Implementation Plan
**Version:** 2.0
**Date:** 2025-10-18
**Status:** Research Complete - Ready to Build

---

## Executive Summary

After comprehensive research into:
- CalTopo/SARTopo mapping tools
- QGIS PyQGIS drawing capabilities
- International SAR standards (IAMSAR, ICS)
- Lost Person Behavior (LPB) statistics

**We are ready to build Phase 3 with confidence.**

### Key Insights

✅ **QGIS provides 80% of infrastructure** - Focus on SAR-specific features
✅ **Sample code already created** - Range rings and sectors ready to integrate
✅ **SAR terminology must be standardized** - Update UI to match international standards
✅ **LPB integration is critical** - Automatic search radius generation
✅ **No wheel-reinventing needed** - Leverage PyQGIS APIs directly

---

## Phase 3: Revised Implementation Strategy

### Phase 3A - Foundation & Quick Wins (Week 1)
**Goal:** Update terminology + implement core drawing infrastructure

#### 1. Terminology Updates (Day 1-2)
**Effort:** 4 hours | **Impact:** High
- [ ] Update marker dialog: "POI" → "IPP/LKP"
- [ ] Add marker type selector: IPP, LKP, PLS, Clue, Hazard
- [ ] Add tooltips explaining SAR terms
- [ ] Update button labels throughout UI
- [ ] Add subject category dropdown (for LPB)

**Files to modify:**
- `ui/marker_dialog.py`
- `ui/sar_panel.py`
- `controllers/layers_controller.py`

#### 2. Subject Category & LPB Integration (Day 2-3)
**Effort:** 6 hours | **Impact:** Very High
- [ ] Create LPB statistics module (`utils/lpb_statistics.py`)
- [ ] Add subject categories:
  - Child (1-3, 4-6, 7-12 years)
  - Hiker
  - Hunter
  - Elderly
  - Dementia
  - Despondent
  - Autistic
- [ ] Automatic range ring generation from IPP with LPB distances
- [ ] Show 25%, 50%, 75%, 95% probability rings

**Files to create:**
- `utils/lpb_statistics.py` - LPB data and calculations
- `ui/lpb_range_dialog.py` - Dialog for LPB ring generation

#### 3. Core Drawing Infrastructure (Day 4-5)
**Effort:** 8 hours | **Impact:** High
- [ ] Create base drawing tool class (`maptools/base_drawing_tool.py`)
- [ ] Set up drawing tool registry
- [ ] Add tool activation/deactivation logic
- [ ] Integrate with SAR panel UI
- [ ] Add status bar messages for drawing feedback

**Files to create:**
- `maptools/base_drawing_tool.py`
- `maptools/tool_registry.py`

---

### Phase 3B - Core Drawing Tools (Week 2)
**Goal:** Implement essential drawing tools leveraging QGIS APIs

#### 4. Line Tool (Day 1-2)
**Effort:** 6 hours | **Impact:** Medium
- [ ] Polyline drawing with click-to-draw
- [ ] Automatic distance calculation
- [ ] Properties dialog:
  - Name/description
  - Color picker
  - Line width
  - Show/hide distance labels
- [ ] Right-click or double-click to finish

**Reference:** Use QgsMapTool + QgsRubberBand pattern

#### 5. Search Area/Polygon Tool (Day 2-4)
**Effort:** 8 hours | **Impact:** Very High
- [ ] Polygon drawing with click-to-draw
- [ ] Auto-calculate area (km², hectares)
- [ ] Properties dialog:
  - Segment name (Alpha, Bravo, etc.)
  - **Team assignment dropdown**
  - **Status dropdown** (Planned/Assigned/In Progress/Completed/Cleared)
  - Priority (High/Medium/Low)
  - Color picker
  - Fill transparency
  - Notes field
- [ ] Color coding by status:
  - Yellow = Planned
  - Orange = Assigned
  - Blue = In Progress
  - Green = Completed
  - Light green = Cleared
- [ ] POA/POD fields for future use

**Critical SAR Features:**
- Status tracking (this is essential!)
- Team assignment
- Visual distinction by status

#### 6. Range Ring Tool - INTEGRATION (Day 4-5)
**Effort:** 4 hours | **Impact:** High
- [ ] Integrate existing `maptools/range_ring_tool.py` (already created by research!)
- [ ] Dialog for:
  - Click center OR coordinate entry
  - Distance input (single or multiple)
  - **Link to LPB statistics** (auto-fill based on subject category)
  - Manual override option
  - Color and transparency
- [ ] Display radius labels on rings
- [ ] Preview while adjusting values

**Note:** Range ring tool already implemented - just needs integration!

---

### Phase 3C - Advanced SAR Tools (Week 3)
**Goal:** Implement direction-finding and probability tools

#### 7. Search Sector Tool - INTEGRATION (Day 1-2)
**Effort:** 4 hours | **Impact:** Medium
- [ ] Integrate existing `maptools/sector_tool.py` (already created!)
- [ ] Three-click workflow: center → radius → angle
- [ ] Properties:
  - Start/end bearing
  - Sector name
  - Priority level
  - Color/transparency
- [ ] Calculate and display area

**Note:** Sector tool already implemented - just needs integration!

#### 8. Bearing Line Tool (Day 2-3)
**Effort:** 6 hours | **Impact:** Medium
- [ ] Origin point (click or coordinate entry)
- [ ] Dialog with:
  - Starting coordinates
  - Bearing (0-360°)
  - Distance/length
  - Magnetic declination correction (~-4.5° for Ireland)
  - Label text
- [ ] Display bearing on line (true and magnetic)
- [ ] Support multiple bearings from same origin

**Use Case:** RDF (Radio Direction Finding), witness sightings

#### 9. Hazard Marker Tool (Day 4-5)
**Effort:** 4 hours | **Impact:** High (Safety Critical!)
- [ ] Extend marker tool with hazard types:
  - Cliff/Drop-off
  - Water hazard
  - Unstable ground (bog/peatland)
  - Dense vegetation
  - Wildlife danger
  - Weather exposure
- [ ] Orange/yellow warning colors
- [ ] Hazard zone polygons
- [ ] Warning labels

---

### Phase 3D - Enhancement & Polish (Week 4)
**Goal:** Complete Phase 3 with refinements

#### 10. Text Annotation Tool (Day 1-2)
**Effort:** 4 hours | **Impact:** Medium
- [ ] Click-to-place text labels
- [ ] Multi-line text support
- [ ] Font size options
- [ ] Background/halo for visibility
- [ ] Rotation capability

**Use Case:** Segment labels, team assignments, notes

#### 11. Enhanced Clue Management (Day 2-3)
**Effort:** 4 hours | **Impact:** High
- [ ] Expand casualty marker to "Clue" with types:
  - Footprint
  - Clothing
  - Equipment
  - Witness sighting
  - Physical evidence
- [ ] Confidence level (Confirmed/Probable/Possible)
- [ ] Auto-calculate distance/bearing from IPP
- [ ] Time found
- [ ] Photo attachment (future)

#### 12. GPX Import (Day 3-4)
**Effort:** 6 hours | **Impact:** Medium
- [ ] File picker for .gpx files
- [ ] Import as line layer
- [ ] Extract track metadata (name, time, distance)
- [ ] Display track statistics
- [ ] Style differently from live tracking
- [ ] Option to convert to search area polygon

#### 13. Edit/Delete Tools (Day 4-5)
**Effort:** 6 hours | **Impact:** High
- [ ] Context menu on all annotation layers
- [ ] Identify tool (click to view properties)
- [ ] Edit properties dialog
- [ ] Move/reposition features
- [ ] Delete with confirmation
- [ ] Undo/redo support

---

## Layer Organization

```
SAR Tracking (group)
├── 📍 IPP/LKP (renamed from POIs - star icon)
├── 🔍 Clues (enhanced casualty markers)
├── ⚠️ Hazards (new - warning icons)
├── 📝 Labels (new - text annotations)
├── 🥧 Search Sectors (new - wedge shapes)
├── 🔷 Search Areas (new - polygons with status)
├── ⭕ Range Rings (new - circles, semi-transparent)
├── ➡️ Bearing Lines (new - directional lines)
├── 📏 Lines (new - polylines)
├── 📂 Imported Tracks (new - GPX imports)
├── 📍 Current Positions (existing)
└── 🥾 Breadcrumbs (existing)
```

**Layer Ordering Logic:**
- Labels/text on top (always visible)
- Markers next (IPP, clues, hazards)
- Search areas and sectors (semi-transparent)
- Lines and bearing lines
- Range rings (most transparent)
- Tracks
- Current positions and breadcrumbs at bottom

---

## Data Models

### IPP/LKP Marker
```python
fields = [
    QgsField("id", 10),              # String
    QgsField("type", 10),            # IPP|LKP|PLS
    QgsField("name", 10),            # Subject name/identifier
    QgsField("subject_category", 10), # Child_1_3|Hiker|Elderly|etc
    QgsField("subject_age", 2),      # Integer
    QgsField("timestamp", 10),       # When last seen
    QgsField("description", 10),     # Notes
    QgsField("lat", 6),              # Double
    QgsField("lon", 6),              # Double
    QgsField("irish_e", 6),          # Double
    QgsField("irish_n", 6),          # Double
    QgsField("created", 10),         # Timestamp
]
```

### Search Area
```python
fields = [
    QgsField("id", 10),              # String
    QgsField("name", 10),            # Segment name (Alpha, Bravo, etc.)
    QgsField("team", 10),            # Assigned team
    QgsField("status", 10),          # Planned|Assigned|InProgress|Completed|Cleared
    QgsField("priority", 10),        # High|Medium|Low
    QgsField("area_sqkm", 6),        # Double
    QgsField("POA", 6),              # Probability of Area (0-100)
    QgsField("POD", 6),              # Probability of Detection (0-100)
    QgsField("terrain", 10),         # Easy|Moderate|Difficult|Extreme
    QgsField("search_method", 10),   # Grid|Contour|SoundSweep|Hasty
    QgsField("color", 10),           # Hex color
    QgsField("start_time", 10),      # Timestamp
    QgsField("end_time", 10),        # Timestamp
    QgsField("notes", 10),           # Text
    QgsField("created", 10),         # Timestamp
]
```

### Clue Marker
```python
fields = [
    QgsField("id", 10),              # String
    QgsField("type", 10),            # Footprint|Clothing|Equipment|Sighting|Evidence
    QgsField("confidence", 10),      # Confirmed|Probable|Possible
    QgsField("description", 10),     # Details
    QgsField("found_by", 10),        # Team/person
    QgsField("time_found", 10),      # Timestamp
    QgsField("distance_from_ipp", 6),# Double (meters)
    QgsField("bearing_from_ipp", 6), # Double (degrees)
    QgsField("lat", 6),              # Double
    QgsField("lon", 6),              # Double
    QgsField("photo_path", 10),      # String (future)
    QgsField("created", 10),         # Timestamp
]
```

### Hazard Marker
```python
fields = [
    QgsField("id", 10),              # String
    QgsField("type", 10),            # Cliff|Water|Bog|Vegetation|Wildlife|Weather
    QgsField("severity", 10),        # High|Medium|Low
    QgsField("description", 10),     # Details
    QgsField("lat", 6),              # Double
    QgsField("lon", 6),              # Double
    QgsField("created", 10),         # Timestamp
]
```

---

## UI Updates

### SAR Panel - Drawing Tools Section

```
╔════════════════════════════════════════╗
║ Drawing Tools                    ▼     ║
╠════════════════════════════════════════╣
║ 📍 Add IPP/LKP    🔍 Add Clue         ║
║ ⚠️ Add Hazard     📝 Add Label         ║
║ 📏 Draw Line      🔷 Search Area       ║
║ ⭕ Range Rings     ➡️ Bearing Line      ║
║ 🥧 Search Sector  📂 Import GPX        ║
╠════════════════════════════════════════╣
║ Active Tool: [None]                    ║
║ ❌ Cancel Drawing                       ║
╚════════════════════════════════════════╝
```

### Status Colors (Standardized)

**Search Areas:**
- 🟡 Yellow = Planned
- 🟠 Orange = Assigned
- 🔵 Blue = In Progress
- 🟢 Green = Completed
- 🟢 Light Green = Cleared (high POD)

**Markers:**
- 🔴 Red = Casualties/Urgent
- 🟠 Orange = Hazards
- 🔵 Blue = IPP/LKP
- 🟣 Purple = Clues
- 🟢 Green = Safe locations

---

## Implementation Checklist

### Week 1: Foundation ✅
- [ ] Update terminology (IPP/LKP/PLS)
- [ ] Create LPB statistics module
- [ ] Add subject category to markers
- [ ] Implement LPB range ring generation
- [ ] Create base drawing tool infrastructure

### Week 2: Core Tools ✅
- [ ] Line drawing tool
- [ ] Search area/polygon tool with status
- [ ] Integrate range ring tool (already built!)
- [ ] Team assignment dropdown
- [ ] Status tracking system

### Week 3: Advanced Tools ✅
- [ ] Integrate sector tool (already built!)
- [ ] Bearing line tool
- [ ] Hazard marker tool
- [ ] Enhanced clue management

### Week 4: Polish & Complete ✅
- [ ] Text annotation tool
- [ ] GPX import
- [ ] Edit/delete features
- [ ] Context menus
- [ ] Comprehensive testing

---

## Testing Plan

### Unit Tests
- [ ] LPB statistics calculations
- [ ] Coordinate transformations
- [ ] Geometry creation
- [ ] Distance/bearing calculations
- [ ] Area calculations

### Integration Tests
- [ ] Tool activation/deactivation
- [ ] Feature creation in layers
- [ ] Feature editing
- [ ] Feature deletion
- [ ] QGIS project save/load
- [ ] Auto-save with new features

### Field Tests
- [ ] Test with Kerry Mountain Rescue team
- [ ] Real-world coordinate entry
- [ ] Stress testing under time pressure
- [ ] Usability with gloves
- [ ] Visibility in bright sunlight

---

## Qt5/Qt6 Compatibility

**For ALL new code:**
- ✅ Import from `utils/qt_compat.py` for Qt enums
- ✅ Use integer constants for QgsField types
- ✅ Explicit type conversion for QSettings values
- ✅ All imports use `qgis.PyQt` (not PyQt5/PyQt6)

---

## Documentation Updates

### User Documentation
- [ ] SAR Terminology Guide
- [ ] LPB Statistics Reference
- [ ] Drawing Tools Tutorial
- [ ] Search Planning Workflow
- [ ] Team Assignment Guide

### Developer Documentation
- [ ] PyQGIS Drawing API Guide
- [ ] Tool Development Pattern
- [ ] Adding New Marker Types
- [ ] LPB Statistics Format

### README Updates
- [ ] Add Phase 3 features
- [ ] Update screenshots
- [ ] Add LPB section
- [ ] Add team management section

---

## Success Criteria

Phase 3 complete when:
- ✅ All 7 core drawing tools implemented
- ✅ SAR terminology standardized throughout
- ✅ LPB integration working
- ✅ Search area status tracking functional
- ✅ Team assignment system operational
- ✅ Hazard marking capability added
- ✅ Features can be created, edited, deleted
- ✅ Qt5/Qt6 compatibility maintained
- ✅ Documentation complete
- ✅ Kerry Mountain Rescue team approves

---

## Risk Mitigation

### Technical Risks
| Risk | Mitigation |
|------|------------|
| Complex geometry creation | Leverage QgsGeometry APIs, use working examples |
| CRS transformation errors | Use existing coordinate converter patterns |
| Performance with many features | Batch operations, optimize rendering |
| Qt5/Qt6 compatibility issues | Follow established patterns from Phase 1 & 2 |

### User Experience Risks
| Risk | Mitigation |
|------|------------|
| Tool complexity | Start simple, add features incrementally |
| Terminology confusion | Add tooltips, create glossary |
| Status tracking too complex | Use clear color coding, simple workflow |
| Too many clicks | Optimize common workflows |

---

## Open Questions for Discussion

1. **Team Management:** Should teams be managed in a separate panel, or just as dropdown selections?
2. **LPB Statistics:** Use global statistics or create Ireland-specific data?
3. **POA/POD:** Implement full probability calculations now, or placeholder fields for Phase 4?
4. **Database:** Continue with memory layers for Phase 3, or start database migration now?
5. **Search Patterns:** Auto-generate search grids, or manual polygon drawing only?
6. **Export Formats:** What formats needed? (PDF, KML, GeoJSON, ICS forms?)

---

## Next Steps

1. ✅ **Review this master plan** with team
2. ✅ **Clarify open questions** above
3. ✅ **Approve implementation approach**
4. 🚀 **Begin Week 1: Foundation work**

---

## Resources

### Research Documents
- `research/caltopo_research_report.md`
- `research/SAR_REQUIREMENTS_REPORT.md`
- `docs/QGIS_DRAWING_CAPABILITIES.md`
- `SAR_CRITICAL_FEATURES_CHECKLIST.md`

### Code Examples (Already Created!)
- `maptools/range_ring_tool.py` - Complete range ring implementation
- `maptools/sector_tool.py` - Complete sector tool implementation

### Reference Materials
- IAMSAR Manual (International SAR guidelines)
- "Lost Person Behavior" by Robert Koester
- Mountain Rescue Association standards
- CalTopo/SARTopo platform

---

**Version History:**
- v1.0 (2025-10-13): Initial Phase 3 plan
- v2.0 (2025-10-18): Comprehensive revision after research phase

**Status:** ✅ READY TO BUILD - All planning complete, research done, approach validated
