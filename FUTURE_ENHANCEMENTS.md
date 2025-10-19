# SAR Tracker - Future Enhancements

## Priority 1: Feature Management (Edit/Delete)

### Problem
Currently, users can CREATE features (lines, markers, search areas, etc.) but cannot easily edit or delete them after creation. The only way to delete is through QGIS's native editing workflow (right-click layer → Toggle Editing → Select → Delete), which is cumbersome.

### Impact
**High** - This significantly impacts usability. Users will create test features, make mistakes, or need to update information, and need a simple way to manage them.

### Proposed Solutions

#### **Option A: Quick Delete Button** (30 minutes - RECOMMENDED FOR IMMEDIATE IMPLEMENTATION)

**What it does:**
- Add "Delete Selected Feature" button to SAR Panel (in Drawing Tools or Utilities section)
- User selects a feature on the map (click it)
- Click "Delete Selected Feature" button
- Confirmation dialog: "Delete [feature name]?"
- Feature removed from layer

**Pros:**
- Quick to implement
- Solves immediate pain point
- Standard workflow (select then delete)

**Cons:**
- Only handles deletion, not editing
- Requires selection first (users must click feature on map)

**Implementation:**
- Add button to SAR Panel
- Use `iface.activeLayer()` and `iface.mapCanvas().currentLayer()` to get selected features
- Delete from layer using `layer.deleteFeature(feature_id)`

---

#### **Option B: Properties Dialog** (1-2 hours)

**What it does:**
- Right-click feature on map → "Feature Properties" menu item
- Dialog shows all attributes (name, description, color, etc.)
- Edit fields and click Save
- Changes written back to layer

**Pros:**
- Full editing capability
- Contextual (right-click on feature)
- Can view without editing

**Cons:**
- Requires QGIS right-click menu integration
- More complex implementation
- Doesn't show list of all features

**Implementation:**
- Register custom action for layers
- Create properties dialog (similar to marker dialog)
- Update feature attributes on save

---

#### **Option C: Feature Management Panel** (2-3 hours)

**What it does:**
- New collapsible section in SAR Panel: "Feature Management"
- List all features grouped by type:
  - IPP/LKP Markers (3)
  - Clues (5)
  - Hazards (2)
  - Lines (4)
  - Search Areas (1)
- Each feature shows: name, type, created date
- Buttons: [Zoom To] [Properties] [Delete]
- Click feature in list to select on map

**Pros:**
- Complete feature overview
- Easy batch operations
- No need to hunt for features on map
- Professional SAR workflow

**Cons:**
- Most complex to implement
- Takes up panel space
- Needs to update dynamically as features added/removed

**Implementation:**
- Add QTreeWidget or QListWidget to SAR Panel
- Query all layers for features
- Connect to layer signals for updates
- Implement zoom, edit, delete actions

---

### Recommended Implementation Order

**Phase 1: Quick Delete (Do First - This Week)**
- Implement Option A
- Gives users immediate delete capability
- ~30 minutes work

**Phase 2: Properties Dialog (Do Next - Next Week)**
- Implement Option B
- Allows full editing of existing features
- ~1-2 hours work

**Phase 3: Feature Management Panel (Do Later - After Phase 3 complete)**
- Implement Option C
- Professional feature overview
- ~2-3 hours work

---

## Priority 2: Data Export/Import System

### Problem
Currently, all SAR data (markers, lines, search areas, etc.) lives in QGIS memory layers and is only saved when the user saves the QGIS project file. Users could lose data if they forget to save.

### Proposed Solution
Add mission-specific export/import functionality:

1. **Export Mission Data**
   - Button in SAR panel: "Export Mission Data"
   - Export all layers to GeoPackage (`.gpkg`) or GeoJSON
   - Filename: `mission_[name]_[date].gpkg`
   - Includes: IPP/LKP, clues, hazards, lines, search areas, range rings, bearing lines, sectors, labels

2. **Import Mission Data**
   - Button: "Load Mission Data"
   - Import from previously exported GeoPackage/GeoJSON
   - Reconstruct all layers and features
   - Preserve attributes (status, team assignments, POA/POD, etc.)

3. **Auto-Export Option**
   - Checkbox: "Auto-export mission data"
   - Periodically export to backup file
   - Safety net in case project file not saved

### Benefits
- Mission data portable/shareable
- Better backup/recovery
- Can load mission data into different QGIS projects
- Team collaboration easier

### Implementation Notes
- Add `export_mission()` method to layers_controller
- Add `import_mission()` method to layers_controller
- UI buttons in SAR panel Data Source section
- File format: GeoPackage (recommended) - single file, preserves all attributes
- Qt5/Qt6 compatible: Use QFileDialog, standard QGIS export methods

### Priority
Medium - Nice to have, but current QGIS project save works fine for most use cases

---

## Other Future Enhancements

### Plugin Reloader Recommendation
- Document in README that developers should install "Plugin Reloader" plugin
- Makes development much faster (F5 to reload vs restarting QGIS)

### Focus Mode Refinement
- Currently hides panels by name
- Could be more intelligent about which panels to hide
- Add to user preferences which panels to hide
- Consider hiding toolbars as well

---
