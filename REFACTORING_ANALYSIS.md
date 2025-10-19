# LayersController Refactoring Analysis

**Date:** 2025-10-19
**Status:** Pre-implementation analysis
**Decision:** Option B - Fix architecture + Refactor

---

## CURRENT STATE

### Existing Layer Structure (INCORRECT)
```
1. Current Positions (tracking)
2. Breadcrumbs (tracking)
3. Points of Interest (POI) → stores IPP/LKP markers
4. Casualties → stores BOTH Clues AND Hazards (mixed!)
5. Lines (drawing)
6. Search Areas (drawing)
7. Range Rings (drawing)
8. Bearing Lines (drawing - layer exists)
9. Search Sectors (drawing - layer exists)
10. Text Labels (drawing - layer exists)
```

### Current Method Mapping (BROKEN)
- IPP/LKP button → `add_poi()` → POI layer
- Clue button → `add_casualty()` → Casualties layer (condition field = clue type)
- Hazard button → `add_casualty()` → Casualties layer (condition field = hazard type)

**Problem:** Clues and Hazards are conceptually different in SAR operations and should be separate layers.

---

## TARGET STATE

### New Layer Structure (CORRECT)
```
Tracking Layers:
1. Current Positions
2. Breadcrumbs

Marker Layers:
3. IPP/LKP (Initial Planning Point / Last Known Position)
4. Clues (Evidence found during search)
5. Hazards (Safety warnings)

Drawing Layers:
6. Lines
7. Search Areas
8. Range Rings
9. Bearing Lines
10. Search Sectors
11. Text Labels
```

### New Method Mapping (CORRECT)
- IPP/LKP button → `add_ipp_lkp()` → IPP/LKP layer
- Clue button → `add_clue()` → Clues layer
- Hazard button → `add_hazard()` → Hazards layer

---

## MARKER FIELDS ANALYSIS

### IPP/LKP Fields (from MarkerDialog):
```python
- id (String/UUID)
- name (String)
- subject_category (String) - "Child (1-3)", "Hiker", "Elderly", etc.
- description (String)
- lat (Double)
- lon (Double)
- irish_grid_e (Double)
- irish_grid_n (Double)
- created (String/ISO timestamp)
```

### Clues Fields (from MarkerDialog):
```python
- id (String/UUID)
- name (String)
- clue_type (String) - "Footprint", "Clothing", "Witness Sighting", etc.
- confidence (String) - "Confirmed", "Probable", "Possible"
- description (String)
- lat (Double)
- lon (Double)
- irish_grid_e (Double)
- irish_grid_n (Double)
- created (String/ISO timestamp)
```

### Hazards Fields (from MarkerDialog):
```python
- id (String/UUID)
- name (String)
- hazard_type (String) - "Cliff/Drop-off", "Water Hazard", "Bog", etc.
- severity (String) - "Critical", "High", "Medium", "Low"
- description (String)
- lat (Double)
- lon (Double)
- irish_grid_e (Double)
- irish_grid_n (Double)
- created (String/ISO timestamp)
```

**Note:** Severity field not in current dialog, will add as optional parameter with default "Medium"

---

## REFACTORING STRATEGY

### Phase 1: Create Manager Infrastructure
1. Create `controllers/layer_managers/` directory
2. Create `base_manager.py` with common functionality
3. Create empty manager files

### Phase 2: Build Marker Manager (CRITICAL - NEW ARCHITECTURE)
1. Create `_get_or_create_ipp_lkp_layer()` method
2. Create `add_ipp_lkp()` method
3. Create `_get_or_create_clues_layer()` method
4. Create `add_clue()` method
5. Create `_get_or_create_hazards_layer()` method
6. Create `add_hazard()` method
7. Apply appropriate styling to each layer

### Phase 3: Build Tracking Manager
1. Extract tracking layer methods from current controller
2. Preserve all bug fixes (truncate, timestamp parsing, etc.)
3. No changes to logic, just move code

### Phase 4: Build Drawing Manager
1. Extract all drawing layer methods
2. **CRITICAL:** Preserve WGS84 geodesic calculations in:
   - `add_range_ring()` lines 882-986
   - `add_bearing_line()` lines 1032-1120
3. No changes to geodesic math

### Phase 5: Create New Orchestrator
1. Create new slim `layers_controller.py`
2. Instantiate all three managers
3. Delegate all method calls to appropriate manager
4. Maintain same public API

### Phase 6: Update Integration Points
1. Update `sartracker.py` lines 684-716:
   - Change `add_poi()` → `add_ipp_lkp()`
   - Change `add_casualty()` → `add_clue()` or `add_hazard()`
2. Update method signatures to match new architecture
3. Verify all signal connections

---

## CRITICAL REQUIREMENTS TO MAINTAIN

### 1. Qt5/Qt6 Compatibility
✅ Use `qgis.PyQt` for ALL imports
✅ Use integer type codes for QgsField:
   - `10` = String
   - `2` = Integer
   - `6` = Double
✅ NO `Qt.Enum` usage
✅ NO `QVariant` usage

### 2. WGS84 Geodesic Accuracy
✅ Preserve WGS84 ellipsoid parameters:
```python
a = 6378137.0  # Semi-major axis
f = 1 / 298.257223563  # Flattening
b = a * (1 - f)  # Semi-minor axis
```
✅ Preserve radius of curvature calculation
✅ Preserve haversine formula implementation
✅ Accuracy requirement: <1m error

### 3. All Bug Fixes from Day 7 Audit
✅ Memory efficient layer clearing (truncate)
✅ Timestamp parsing with error handling
✅ Coordinate formatting (:.0f not int())
✅ Error handling in transformations
✅ Null checks

### 4. Layer Organization
✅ All layers in "SAR Tracking" group
✅ Layer ordering preserved
✅ Consistent styling
✅ Proper labeling

---

## VERIFICATION CHECKLIST

After each manager is created:
- [ ] Plugin loads without errors
- [ ] No import errors
- [ ] Layer methods work correctly
- [ ] Data saved with correct attributes
- [ ] Styling applied correctly
- [ ] Plugin reloads cleanly (F5)

Final integration test:
- [ ] Load CSV → positions and breadcrumbs display
- [ ] Add IPP/LKP marker → appears on map in IPP/LKP layer
- [ ] Add Clue marker → appears on map in Clues layer
- [ ] Add Hazard marker → appears on map in Hazards layer
- [ ] Lines tool works
- [ ] Range Rings tool works (both manual and LPB modes)
- [ ] Geodesic calculations accurate
- [ ] Plugin reload works multiple times
- [ ] No memory leaks
- [ ] All Qt5/Qt6 compatible

---

## FILES TO MODIFY

### New Files to Create:
1. `controllers/layer_managers/__init__.py`
2. `controllers/layer_managers/base_manager.py`
3. `controllers/layer_managers/tracking_manager.py`
4. `controllers/layer_managers/marker_manager.py`
5. `controllers/layer_managers/drawing_manager.py`

### Files to Replace:
1. `controllers/layers_controller.py` - replace with orchestrator

### Files to Update:
1. `sartracker.py` - update marker method calls (lines 684-716)

### Backup Files:
- `controllers/layers_controller.BACKUP.py` - already created ✅

---

## LAYER STYLING SPECIFICATIONS

### IPP/LKP Layer:
- Symbol: Star or target icon
- Color: Blue (#0066FF)
- Size: 7 points
- Outline: Black, 0.5 width
- Labels: Name field, black text, white halo

### Clues Layer:
- Symbol: Triangle or flag
- Color: Yellow (#FFD700)
- Size: 6 points
- Outline: Black, 0.5 width
- Labels: Name field, black text, white halo

### Hazards Layer:
- Symbol: Warning triangle or exclamation
- Color: Red (#FF0000)
- Size: 7 points
- Outline: Black, 0.5 width
- Labels: Name field, dark red text, white halo

---

## ROLLBACK PLAN

If anything breaks:
1. Git restore: `git checkout HEAD -- controllers/`
2. Physical backup exists: `controllers/layers_controller.BACKUP.py`
3. Current commit is tagged: commit 57bf494

---

## ESTIMATED TIME

- Phase 1 (Infrastructure): 30 minutes
- Phase 2 (Marker Manager): 90 minutes ⭐ CRITICAL
- Phase 3 (Tracking Manager): 45 minutes
- Phase 4 (Drawing Manager): 60 minutes (careful geodesic preservation)
- Phase 5 (Orchestrator): 30 minutes
- Phase 6 (Integration): 30 minutes
- Testing: 45 minutes

**Total: ~5-6 hours**

---

## SUCCESS CRITERIA

✅ All 3 marker types in separate layers
✅ Public API unchanged (except marker methods)
✅ All geodesic calculations preserved
✅ All bug fixes preserved
✅ Qt5/Qt6 compatible
✅ Plugin reloads cleanly
✅ No memory leaks
✅ Code well-organized (~200 lines per manager)
✅ Clear separation of concerns

---

**Analysis Complete. Ready to implement.**
