# CSV Provider Regression Test Checklist

**Phase:** 0 – Repository Audit & Guardrails
**Date:** 2025-11-15
**Purpose:** Manual regression test suite for CSV provider to ensure stability before Phase 1 live provider work

---

## Test Environment Setup

### Prerequisites

- [ ] QGIS 3.22+ installed (Qt5) or QGIS 3.34+ (Qt6)
- [ ] SAR Tracker plugin installed
- [ ] Test CSV files available (single file + folder with multiple files)
- [ ] Clean QGIS profile (no conflicting plugins)

### Test Data Preparation

**Single CSV File:**
- [ ] Create test file: `test_device1.csv` (Traccar export format)
- [ ] File contains header metadata (Device: line)
- [ ] File contains valid data rows with timestamps
- [ ] File contains at least 5 position records

**Folder with Multiple CSVs:**
- [ ] Create test folder: `test_data/`
- [ ] Add 3 CSV files: `device1.csv`, `device2.csv`, `device3.csv`
- [ ] Each file has different device name
- [ ] Files have overlapping timestamps

**Rollback Plan:**
- [ ] Backup QGIS profile before testing
- [ ] Note QGIS version and OS for bug reports
- [ ] Document any test failures with screenshots

---

## Test Categories

### 1. Plugin Lifecycle Tests

#### 1.1 Plugin Load/Unload

**Test ID:** LC-001
**Priority:** CRITICAL
**Pattern Coverage:** Patterns 6-9 (Lifecycle management)

**Steps:**
1. [ ] Load plugin via Plugin Manager
2. [ ] Verify SAR Tracker icon appears in toolbar
3. [ ] Verify SAR Tracker panel appears in dock widgets menu
4. [ ] Check Python console for import errors
5. [ ] Unload plugin via Plugin Manager
6. [ ] Reload plugin
7. [ ] Repeat load/unload cycle 5 times

**Expected Results:**
- [ ] Plugin loads without errors
- [ ] No warnings in Python console
- [ ] All UI elements appear correctly
- [ ] Reload cycles complete without crashes
- [ ] No "AttributeError" or "RuntimeError" exceptions

**Pass/Fail:** ___________
**Notes:** _____________________________________________________

---

#### 1.2 Plugin Reload During Active Mission

**Test ID:** LC-002
**Priority:** HIGH
**Pattern Coverage:** Patterns 6-9 (Async lifecycle)

**Steps:**
1. [ ] Load plugin
2. [ ] Load CSV provider (single file)
3. [ ] Start mission: "Test Mission"
4. [ ] Click "Refresh Data" button
5. [ ] IMMEDIATELY reload plugin: Plugins → Plugin Manager → Reload
6. [ ] Check Python console for defensive guard messages
7. [ ] Repeat 3 times

**Expected Results:**
- [ ] No crashes during reload
- [ ] Defensive guards print "completed after unload, ignoring"
- [ ] No AttributeError exceptions
- [ ] TaskManager reports task cancellation
- [ ] Timers stop cleanly

**Pass/Fail:** ___________
**Notes:** _____________________________________________________

---

### 2. CSV Provider Loading

#### 2.1 Load Single CSV File

**Test ID:** CSV-001
**Priority:** CRITICAL
**Pattern Coverage:** Provider interface compliance

**Steps:**
1. [ ] Load plugin
2. [ ] Open SAR Tracker panel
3. [ ] Click "Load CSV" button
4. [ ] Select single test CSV file
5. [ ] Wait for processing to complete

**Expected Results:**
- [ ] File loads without errors
- [ ] Message bar shows success notification (utils.notify)
- [ ] Tracking layers appear in Layers panel
- [ ] Device markers visible on map
- [ ] Breadcrumb trail visible (if historical data)
- [ ] Device count shown in panel

**Pass/Fail:** ___________
**Notes:** _____________________________________________________

---

#### 2.2 Load Folder with Multiple CSV Files

**Test ID:** CSV-002
**Priority:** HIGH
**Pattern Coverage:** Provider multi-file handling

**Steps:**
1. [ ] Load plugin
2. [ ] Open SAR Tracker panel
3. [ ] Click "Load CSV" button
4. [ ] Select folder containing 3 CSV files
5. [ ] Wait for processing to complete

**Expected Results:**
- [ ] All 3 devices loaded
- [ ] Each device has unique marker color (MD5 hash-based)
- [ ] Each device has separate breadcrumb trail
- [ ] Device count = 3
- [ ] No duplicate device entries
- [ ] Latest timestamp used if device appears in multiple files

**Pass/Fail:** ___________
**Notes:** _____________________________________________________

---

#### 2.3 Load Invalid CSV File

**Test ID:** CSV-003
**Priority:** MEDIUM
**Pattern Coverage:** Error handling

**Steps:**
1. [ ] Load plugin
2. [ ] Create invalid CSV file (missing headers, corrupt data)
3. [ ] Attempt to load invalid file
4. [ ] Observe error handling

**Expected Results:**
- [ ] Error notification displayed (utils.notify error)
- [ ] No crash or exception
- [ ] User-friendly error message (not raw exception)
- [ ] Plugin remains functional after error
- [ ] Can load valid file afterward

**Pass/Fail:** ___________
**Notes:** _____________________________________________________

---

### 3. Data Refresh Operations

#### 3.1 Manual Refresh

**Test ID:** REF-001
**Priority:** CRITICAL
**Pattern Coverage:** Pattern 6 (TaskManager)

**Steps:**
1. [ ] Load CSV provider (single file)
2. [ ] Note initial device count
3. [ ] Add new position to CSV file (edit externally)
4. [ ] Click "Refresh Data" button in panel
5. [ ] Wait for refresh to complete

**Expected Results:**
- [ ] Refresh task appears in QGIS task manager
- [ ] Progress shown during refresh
- [ ] Success notification after completion (utils.notify)
- [ ] New position appears on map
- [ ] Breadcrumb trail updated
- [ ] Last refresh time updated in diagnostics

**Pass/Fail:** ___________
**Notes:** _____________________________________________________

---

#### 3.2 Auto-Refresh Timer

**Test ID:** REF-002
**Priority:** HIGH
**Pattern Coverage:** Pattern 7 (Timer lifecycle)

**Steps:**
1. [ ] Load CSV provider
2. [ ] Enable auto-refresh: Set interval to 1 minute
3. [ ] Start mission
4. [ ] Wait 1 minute
5. [ ] Observe auto-refresh trigger
6. [ ] Stop mission
7. [ ] Verify timer stops

**Expected Results:**
- [ ] Auto-refresh triggers after 1 minute
- [ ] Refresh task executes via TaskManager
- [ ] No duplicate refresh operations
- [ ] Timer stops when mission stops
- [ ] Timer doesn't fire after plugin unload

**Pass/Fail:** ___________
**Notes:** _____________________________________________________

---

#### 3.3 Refresh During Active Refresh

**Test ID:** REF-003
**Priority:** MEDIUM
**Pattern Coverage:** Pattern 6 (Task cancellation)

**Steps:**
1. [ ] Load CSV provider (large file or slow disk)
2. [ ] Click "Refresh Data"
3. [ ] Immediately click "Refresh Data" again
4. [ ] Observe behavior

**Expected Results:**
- [ ] First task cancelled or completed
- [ ] Second task starts
- [ ] No concurrent refresh tasks
- [ ] No crashes or deadlocks
- [ ] Clear indication of task state

**Pass/Fail:** ___________
**Notes:** _____________________________________________________

---

### 4. Mission Management

#### 4.1 Start Mission

**Test ID:** MIS-001
**Priority:** CRITICAL
**Pattern Coverage:** Core functionality

**Steps:**
1. [ ] Load CSV provider
2. [ ] Enter mission name: "Test Mission Alpha"
3. [ ] Click "Start Mission" button
4. [ ] Observe UI changes

**Expected Results:**
- [ ] Mission status changes to "Active"
- [ ] Start button becomes "Pause Mission"
- [ ] Mission elapsed timer starts (updates every second)
- [ ] Auto-refresh timer starts (if enabled)
- [ ] Auto-save timer starts (if enabled)
- [ ] Success notification shown

**Pass/Fail:** ___________
**Notes:** _____________________________________________________

---

#### 4.2 Pause/Resume Mission

**Test ID:** MIS-002
**Priority:** HIGH
**Pattern Coverage:** State management

**Steps:**
1. [ ] Start mission (see MIS-001)
2. [ ] Click "Pause Mission" button
3. [ ] Wait 10 seconds
4. [ ] Click "Resume Mission" button
5. [ ] Observe elapsed time

**Expected Results:**
- [ ] Mission status shows "Paused"
- [ ] Elapsed timer stops updating
- [ ] Auto-refresh timer stops
- [ ] Resume restores "Active" status
- [ ] Elapsed time continues from pause point (not reset)
- [ ] Auto-refresh timer resumes

**Pass/Fail:** ___________
**Notes:** _____________________________________________________

---

#### 4.3 Stop Mission

**Test ID:** MIS-003
**Priority:** HIGH
**Pattern Coverage:** State cleanup

**Steps:**
1. [ ] Start mission
2. [ ] Click "Stop Mission" button
3. [ ] Confirm stop dialog (if shown)
4. [ ] Observe cleanup

**Expected Results:**
- [ ] Mission status returns to "Inactive"
- [ ] Start button becomes "Start Mission"
- [ ] Elapsed time resets
- [ ] All timers stop (auto-refresh, ui-update, autosave)
- [ ] Mission state saved (if autosave enabled)

**Pass/Fail:** ___________
**Notes:** _____________________________________________________

---

### 5. Map Tools & Drawing

#### 5.1 Add Marker

**Test ID:** MAP-001
**Priority:** CRITICAL
**Pattern Coverage:** Pattern 5 (BaseDialog), Pattern 3 (dialog_exec)

**Steps:**
1. [ ] Load CSV provider
2. [ ] Click "Add Marker" button in toolbar
3. [ ] Click on map to place marker
4. [ ] MarkerDialog appears
5. [ ] Enter marker name: "Test Point"
6. [ ] Select marker type: "IPP/LKP"
7. [ ] Click OK

**Expected Results:**
- [ ] Dialog renders correctly (not blank) - Pattern 5
- [ ] Marker appears at clicked location
- [ ] Marker has correct icon/color for type
- [ ] Marker label shows name
- [ ] Marker added to "Markers" layer
- [ ] Dialog closes after OK
- [ ] Success notification shown

**Pass/Fail:** ___________
**Notes:** _____________________________________________________

---

#### 5.2 Draw Bearing Line

**Test ID:** MAP-002
**Priority:** HIGH
**Pattern Coverage:** Drawing tools

**Steps:**
1. [ ] Click "Bearing Line" tool
2. [ ] Click start point on map
3. [ ] BearingLineDialog appears
4. [ ] Enter bearing: 045
5. [ ] Enter distance: 500m
6. [ ] Click OK

**Expected Results:**
- [ ] Dialog renders correctly
- [ ] Line drawn from start point at 045° bearing
- [ ] Line length = 500m
- [ ] Line added to "Drawing" layer
- [ ] Tool deactivates after drawing

**Pass/Fail:** ___________
**Notes:** _____________________________________________________

---

#### 5.3 Draw Range Ring

**Test ID:** MAP-003
**Priority:** HIGH
**Pattern Coverage:** Drawing tools

**Steps:**
1. [ ] Click "Range Ring" tool
2. [ ] Click center point on map
3. [ ] RangeRingDialog appears
4. [ ] Enter radius: 1000m
5. [ ] Click OK

**Expected Results:**
- [ ] Dialog renders correctly
- [ ] Circle drawn centered on clicked point
- [ ] Radius = 1000m
- [ ] Circle added to "Drawing" layer
- [ ] Tool deactivates after drawing

**Pass/Fail:** ___________
**Notes:** _____________________________________________________

---

#### 5.4 Draw Search Area Polygon

**Test ID:** MAP-004
**Priority:** HIGH
**Pattern Coverage:** Drawing tools

**Steps:**
1. [ ] Click "Search Area" tool
2. [ ] Click 4 points on map to create polygon
3. [ ] Right-click to finish
4. [ ] SearchAreaDialog appears
5. [ ] Enter area name: "Sector A"
6. [ ] Click OK

**Expected Results:**
- [ ] Dialog renders correctly
- [ ] Polygon drawn with 4 vertices
- [ ] Polygon added to "Search Areas" layer
- [ ] Area labeled with name
- [ ] Tool deactivates after drawing

**Pass/Fail:** ___________
**Notes:** _____________________________________________________

---

### 6. Coordinate Conversion

#### 6.1 Convert Irish Grid to WGS84

**Test ID:** COORD-001
**Priority:** MEDIUM
**Pattern Coverage:** Pattern 5 (BaseDialog)

**Steps:**
1. [ ] Click "Coordinate Converter" button
2. [ ] CoordinateConverterDialog appears
3. [ ] Enter Easting: 700000
4. [ ] Enter Northing: 750000
5. [ ] Click "Convert to WGS84"
6. [ ] Observe latitude/longitude output

**Expected Results:**
- [ ] Dialog renders correctly
- [ ] Conversion completes without error
- [ ] Latitude shown in range -90 to 90
- [ ] Longitude shown in range -180 to 180
- [ ] Values are reasonable for Ireland (~53°N, ~6°W)

**Pass/Fail:** ___________
**Notes:** _____________________________________________________

---

### 7. Diagnostics & Health

#### 7.1 Open Diagnostics Panel

**Test ID:** DIAG-001
**Priority:** MEDIUM
**Pattern Coverage:** Diagnostics API (Pattern 10)

**Steps:**
1. [ ] Load CSV provider
2. [ ] Start mission
3. [ ] Click "Diagnostics" button
4. [ ] DiagnosticsPanel appears
5. [ ] Review displayed information

**Expected Results:**
- [ ] Dialog renders correctly
- [ ] QGIS version shown
- [ ] Qt version shown (Qt5 or Qt6)
- [ ] Plugin version shown
- [ ] Mission status: "Active"
- [ ] Data source: "CSV: filename.csv"
- [ ] Device count shown (e.g., "3 devices")
- [ ] Last refresh time shown (ISO format)
- [ ] Active tasks count shown (e.g., "0 (Idle)")
- [ ] Drawing tools status shown
- [ ] All sections populated

**Pass/Fail:** ___________
**Notes:** _____________________________________________________

---

#### 7.2 Diagnostics During Active Task

**Test ID:** DIAG-002
**Priority:** LOW
**Pattern Coverage:** Health monitoring

**Steps:**
1. [ ] Load CSV provider
2. [ ] Click "Refresh Data"
3. [ ] Immediately open Diagnostics panel
4. [ ] Observe active tasks count

**Expected Results:**
- [ ] Active tasks count = 1 (or "1 task running")
- [ ] After refresh completes, count returns to 0
- [ ] No errors reading task status

**Pass/Fail:** ___________
**Notes:** _____________________________________________________

---

### 8. Autosave & State Persistence

#### 8.1 Auto-Save Mission State

**Test ID:** SAVE-001
**Priority:** MEDIUM
**Pattern Coverage:** Pattern 7 (Autosave timer)

**Steps:**
1. [ ] Enable autosave in settings (interval: 1 minute)
2. [ ] Start mission: "Test Autosave"
3. [ ] Wait 1 minute
4. [ ] Observe autosave trigger

**Expected Results:**
- [ ] Autosave timer fires after 1 minute
- [ ] Mission state saved to QSettings
- [ ] No UI freeze during save
- [ ] Success notification shown (optional)

**Pass/Fail:** ___________
**Notes:** _____________________________________________________

---

#### 8.2 Resume Paused Mission

**Test ID:** SAVE-002
**Priority:** HIGH
**Pattern Coverage:** State persistence

**Steps:**
1. [ ] Start mission: "Test Resume"
2. [ ] Add marker on map
3. [ ] Pause mission
4. [ ] Close QGIS (save project if prompted)
5. [ ] Reopen QGIS
6. [ ] Load plugin
7. [ ] Observe resume prompt

**Expected Results:**
- [ ] MissionResumeDialog appears on plugin load
- [ ] Dialog shows saved mission name and timestamp
- [ ] "Resume Mission" option available
- [ ] "Start Fresh" option available
- [ ] Selecting "Resume" restores mission state
- [ ] Previously added marker still visible

**Pass/Fail:** ___________
**Notes:** _____________________________________________________

---

### 9. Cache Performance

#### 9.1 CSV File-Level Caching

**Test ID:** CACHE-001
**Priority:** LOW
**Pattern Coverage:** CSV provider optimization

**Steps:**
1. [ ] Load CSV provider (large file, 1000+ positions)
2. [ ] Note initial load time
3. [ ] Click "Refresh Data" immediately (file unchanged)
4. [ ] Note refresh time
5. [ ] Compare times

**Expected Results:**
- [ ] Second refresh ~3x faster than initial load
- [ ] Cache hit logged in Python console (if verbose mode)
- [ ] Same device count and positions shown
- [ ] No re-parsing of unchanged file

**Pass/Fail:** ___________
**Notes:** _____________________________________________________

---

### 10. Error Handling & Edge Cases

#### 10.1 Load Non-Existent File

**Test ID:** ERR-001
**Priority:** LOW
**Pattern Coverage:** Error handling

**Steps:**
1. [ ] Load plugin
2. [ ] Manually trigger load with invalid path (via Python console if needed)
3. [ ] Observe error handling

**Expected Results:**
- [ ] Error notification shown
- [ ] User-friendly message (not raw exception)
- [ ] Plugin remains functional
- [ ] Can load valid file afterward

**Pass/Fail:** ___________
**Notes:** _____________________________________________________

---

#### 10.2 Empty CSV File

**Test ID:** ERR-002
**Priority:** LOW
**Pattern Coverage:** Error handling

**Steps:**
1. [ ] Create empty CSV file
2. [ ] Load file with plugin
3. [ ] Observe behavior

**Expected Results:**
- [ ] Warning notification shown
- [ ] Message indicates no data found
- [ ] Device count = 0
- [ ] No crash

**Pass/Fail:** ___________
**Notes:** _____________________________________________________

---

#### 10.3 CSV File with Invalid Coordinates

**Test ID:** ERR-003
**Priority:** MEDIUM
**Pattern Coverage:** Input validation

**Steps:**
1. [ ] Create CSV with invalid coordinates (lat > 90, lon > 180)
2. [ ] Load file with plugin
3. [ ] Observe behavior

**Expected Results:**
- [ ] Invalid rows skipped during parsing
- [ ] Warning notification shown
- [ ] Valid rows still loaded
- [ ] Device count reflects valid rows only

**Pass/Fail:** ___________
**Notes:** _____________________________________________________

---

### 11. Qt5/Qt6 Compatibility

#### 11.1 Dialog Rendering (Qt5)

**Test ID:** COMPAT-001
**Priority:** HIGH (if testing on Qt5)
**Pattern Coverage:** Pattern 5 (BaseDialog)

**Preconditions:**
- [ ] QGIS 3.22-3.32 (Qt5)

**Steps:**
1. [ ] Load plugin
2. [ ] Open each dialog:
   - [ ] MarkerDialog
   - [ ] BearingLineDialog
   - [ ] RangeRingDialog
   - [ ] SearchAreaDialog
   - [ ] CoordinateConverterDialog
   - [ ] DiagnosticsPanel
3. [ ] Verify rendering

**Expected Results:**
- [ ] All dialogs render correctly (not blank)
- [ ] All widgets visible and functional
- [ ] No Windows-specific blank dialog bug

**Pass/Fail:** ___________
**Notes:** _____________________________________________________

---

#### 11.2 Dialog Rendering (Qt6)

**Test ID:** COMPAT-002
**Priority:** HIGH (if testing on Qt6)
**Pattern Coverage:** Pattern 5 (BaseDialog)

**Preconditions:**
- [ ] QGIS 3.34+ (Qt6)

**Steps:**
1. [ ] Same as COMPAT-001
2. [ ] Verify all dialogs render correctly on Qt6

**Expected Results:**
- [ ] All dialogs render correctly
- [ ] No Qt5/Qt6 compatibility issues

**Pass/Fail:** ___________
**Notes:** _____________________________________________________

---

## Test Execution Summary

### Test Run Information

- **Date:** ___________
- **Tester:** ___________
- **QGIS Version:** ___________
- **Qt Version:** Qt5 / Qt6 (circle one)
- **Operating System:** ___________
- **Plugin Version:** ___________

### Test Results Summary

| Category | Total Tests | Passed | Failed | Skipped |
|----------|------------|--------|--------|---------|
| Plugin Lifecycle | 2 | ___ | ___ | ___ |
| CSV Provider Loading | 3 | ___ | ___ | ___ |
| Data Refresh | 3 | ___ | ___ | ___ |
| Mission Management | 3 | ___ | ___ | ___ |
| Map Tools & Drawing | 4 | ___ | ___ | ___ |
| Coordinate Conversion | 1 | ___ | ___ | ___ |
| Diagnostics & Health | 2 | ___ | ___ | ___ |
| Autosave & Persistence | 2 | ___ | ___ | ___ |
| Cache Performance | 1 | ___ | ___ | ___ |
| Error Handling | 3 | ___ | ___ | ___ |
| Qt Compatibility | 2 | ___ | ___ | ___ |
| **TOTAL** | **26** | **___** | **___** | **___** |

### Critical Failures

List any critical test failures that must be fixed before Phase 1:

1. ___________________________________________________________
2. ___________________________________________________________
3. ___________________________________________________________

### Known Issues

List any known issues that are not blocking but should be tracked:

1. ___________________________________________________________
2. ___________________________________________________________
3. ___________________________________________________________

### Recommendations

Based on test results, provide recommendations for Phase 1:

_________________________________________________________________
_________________________________________________________________
_________________________________________________________________

### Approval

- [ ] All critical tests passed
- [ ] All high-priority tests passed
- [ ] Known issues documented and tracked
- [ ] CSV provider stable for production use

**Approved by:** ___________
**Date:** ___________
**Status:** APPROVED / NEEDS REMEDIATION (circle one)

---

## Document Version

**Version:** 1.0
**Date:** 2025-11-15
**Next Review:** After test execution
