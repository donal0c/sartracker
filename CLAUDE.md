# SAR Tracker - Project Knowledge for AI Assistants

> **Note**: This is the Claude-specific documentation file with comprehensive patterns.
> For general AI assistant instructions, see [AGENTS.md](./AGENTS.md).
> Other AI assistants should refer to AGENTS.md first, then consult this file for detailed patterns.

## 🚨 CRITICAL SAFETY CONTEXT

**Classification:** LIFE-SAFETY CRITICAL SYSTEM
**Domain:** Mountain Search and Rescue Operations
**Impact:** Failures can result in loss of life during active rescue operations

**Before making ANY changes:**
- Understand that rescue coordinators depend on this software in life-or-death situations
- Test thoroughly across Qt5 and Qt6 (QGIS 3.28 - 3.44+)
- Never skip error handling or input validation
- Follow all mandatory patterns documented below
- When uncertain, consult detailed documentation and ask for review

---

## PROJECT OVERVIEW

**Type:** QGIS Plugin (Python)
**Version:** 0.3.1
**Team:** Kerry Mountain Rescue Team, Ireland
**QGIS Compatibility:** 3.28+ (Qt5 and Qt6)
**Python:** 3.8+

### Core Purpose
Real-time tracking and tactical mapping console for Search and Rescue operations. Enables rescue coordinators to:
- Track rescue personnel positions in real-time
- Manage missions with precise time tracking
- Place tactical markers (IPP/LKP, clues, hazards)
- Draw search areas, bearing lines, range rings
- Coordinate multi-team operations
- Work reliably in offline/poor connectivity scenarios

---

## ARCHITECTURE QUICK REFERENCE

### Module Structure
```
sartracker/
├── utils/                    # ⚠️ CRITICAL: Compatibility & safety layer
│   ├── qt_compat.py         # Qt5/Qt6 enum compatibility (MANDATORY)
│   ├── dialog_utils.py      # SafeQDialog base class (fixes blank dialogs)
│   ├── task_manager.py      # Background task lifecycle
│   ├── secure_store.py      # Credential security (system keychain)
│   └── notify.py            # User notifications
│
├── controllers/
│   ├── layers_controller.py       # Layer orchestration
│   └── layer_managers/            # Specialized managers
│       ├── tracking_manager.py    # Device tracking
│       ├── marker_manager.py      # Static markers
│       └── drawing_manager.py     # Search areas, lines
│
├── providers/
│   ├── traccar_http.py      # HTTP Traccar provider
│   ├── csv.py               # CSV provider
│   └── tasks.py             # Background processing tasks
│
├── ui/
│   ├── sar_panel.py         # Main control panel
│   ├── marker_dialog.py     # Marker input (CRITICAL)
│   └── diagnostics_panel.py # System diagnostics
│
├── maptools/                # Drawing tools
│   ├── marker_tool.py
│   ├── bearing_tool.py
│   ├── range_ring_tool.py
│   └── polygon_tool.py
│
└── sartracker.py            # Main plugin class (lifecycle)
```

### Critical Dependencies
- **Bundled:** requests, urllib3, charset_normalizer (in `vendor/site-packages`)
- **QGIS Core:** QgsTask, QgsVectorLayer, QgsCoordinateTransform
- **Storage:** GeoPackage layers, system keychain for credentials

---

## MANDATORY CODING PATTERNS

### Pattern 1: Qt Imports (100% Compliance Required)
```python
# ✅ CORRECT - Always use qgis.PyQt
from qgis.PyQt.QtCore import Qt, QTimer
from qgis.PyQt.QtWidgets import QDialog, QPushButton
from qgis.PyQt.QtGui import QIcon, QColor

# ❌ WRONG - NEVER import PyQt5/PyQt6 directly
from PyQt5.QtCore import Qt      # Breaks in Qt6
from PyQt6.QtWidgets import QDialog  # Breaks in Qt5
```

### Pattern 2: Qt Enums (100% Compliance Required)
```python
# ✅ CORRECT - Import from utils.qt_compat
from utils.qt_compat import (
    LeftButton, RightButton,
    Key_Escape, Key_Return,
    Checked, Unchecked,
    CrossCursor, ArrowCursor,
    dialog_exec, DialogAccepted, DialogRejected
)

if event.button() == LeftButton:
    self.handle_click()

# ❌ WRONG - Direct Qt enum usage
from qgis.PyQt.QtCore import Qt
if event.button() == Qt.LeftButton:  # Breaks in Qt6
    pass
```

**Why:** Qt6 moved enums to scoped namespaces (Qt.MouseButton.LeftButton vs Qt.LeftButton). Our compatibility layer handles both versions.

### Pattern 3: Dialog Base Classes (CRITICAL)
```python
# ✅ CORRECT - Prevents blank dialog bug
from utils.dialog_utils import BaseDialog
from utils.qt_compat import dialog_exec, DialogAccepted

class MyDialog(BaseDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("My Dialog")
        # ... setup UI

# Usage
dialog = MyDialog(parent=iface.mainWindow())
if dialog_exec(dialog) == DialogAccepted:
    process_data()

# ❌ WRONG - Direct QDialog inheritance
from qgis.PyQt.QtWidgets import QDialog
class MyDialog(QDialog):  # May render blank on Windows Qt 5.15
    pass
```

**Why:** Qt 5.15.x has blank dialog rendering bugs on Windows. BaseDialog applies automatic workarounds.

### Pattern 4: Background Tasks (LIFE-SAFETY CRITICAL)
```python
# ✅ CORRECT - Use TaskManager
from utils.task_manager import TaskManager

class MyPlugin:
    def __init__(self):
        self.task_manager = TaskManager()

    def start_work(self):
        task = self.provider.create_refresh_task("Loading")
        self.task_manager.start_task(
            task=task,
            on_complete=self._on_complete,
            on_error=self._on_error,
            task_id="refresh"
        )

    def _on_complete(self, task):
        # CRITICAL: Check components exist before processing
        if not self.layers_controller or not self.sar_panel:
            print("[PLUGIN] Task completed after unload, ignoring")
            return

        result = task.get_result()
        self.update_ui(result)

    def unload(self):
        if self.task_manager:
            self.task_manager.cancel_all()

# ❌ WRONG - Direct signal connection
task.taskCompleted.connect(self._on_complete)  # Signal leak!
QgsApplication.taskManager().addTask(task)
# Problem: Signals remain connected after plugin unload → crash
```

**Why:** TaskManager automatically manages signal lifecycle, preventing handlers from firing after plugin unload.

### Pattern 5: Input Validation (MANDATORY)
```python
# ✅ CORRECT - Always validate user input
def add_marker(self, name, lat, lon, marker_type="ipp_lkp"):
    """Add marker with comprehensive validation."""
    # Validate name
    if not name or not name.strip():
        raise ValueError("Marker name cannot be empty")

    # Validate latitude
    if not isinstance(lat, (int, float)) or not (-90 <= lat <= 90):
        raise ValueError(f"Invalid latitude: {lat}. Must be -90 to 90")

    # Validate longitude
    if not isinstance(lon, (int, float)) or not (-180 <= lon <= 180):
        raise ValueError(f"Invalid longitude: {lon}. Must be -180 to 180")

    # Validate marker type
    valid_types = ["ipp_lkp", "clue", "hazard"]
    if marker_type not in valid_types:
        raise ValueError(f"Invalid marker type: {marker_type}")

    # Now safe to proceed
    # ...

# ❌ WRONG - No validation
def add_marker(self, name, lat, lon):
    self.create_marker(name, lat, lon)  # What if lat=999?
```

**Why:** Invalid coordinates can endanger rescuers. Life-safety system requires bulletproof validation.

---

## COMMON PITFALLS TO AVOID

1. **Qt Enum Incompatibility** → Always use `utils.qt_compat`
2. **Blocking UI** → Use QgsTask for operations >100ms
3. **Insecure Storage** → Never store credentials in QSettings/config files
4. **Missing Error Handling** → Every external operation needs try/except
5. **No Defensive Guards** → Async handlers must check component existence
6. **Timer Leaks** → Always create timers with parent: `QTimer(self)`
7. **Signal Leaks** → Track connections, disconnect in `unload()`
8. **Direct Dialog Exec** → Use `dialog_exec()` wrapper, not `.exec()` or `.exec_()`

---

## TESTING REQUIREMENTS

### Pre-Commit Checklist
```bash
# Run automated compatibility checks
./tools/check_compatibility.sh

# Expected output:
# ✅ PASS - No direct PyQt5/PyQt6 imports
# ✅ PASS - No direct Qt enum usage
# ✅ PASS - All dialogs use BaseDialog
# ✅ PASS - All dialog execution uses wrapper
# ✅ PASS - All notifications use utils.notify
```

### Critical Test Scenarios
- [ ] Works in Qt5 (QGIS 3.28, 3.34)
- [ ] Works in Qt6 (QGIS 3.40, 3.44+)
- [ ] Dialogs render correctly (not blank)
- [ ] All user inputs validated
- [ ] Error cases handled gracefully
- [ ] Coordinate transformations accurate
- [ ] Plugin reload doesn't crash
- [ ] Background tasks cancel cleanly on unload

### Async Operations Testing (CRITICAL)
```python
# Test reload during background operation
from qgis.utils import plugins, reloadPlugin

for i in range(10):
    plugin = plugins.get('sartracker')
    plugin._on_refresh_data()  # Start async operation
    reloadPlugin('sartracker')  # Immediate reload
    print(f"Reload cycle {i+1} complete")
# Expected: No crashes, no AttributeError
```

---

## DOCUMENTATION REFERENCES

### Primary Documentation
- **`docs/AI_CODE_REFERENCE.md`** - Comprehensive coding patterns and rules (1300+ lines)
- **`docs/architecture.md`** - System architecture and hardening features
- **`FUTURE_WORK/Server/post_audit_recommendations.md`** - Recent Traccar HTTP audit findings

### Development Guides
- **`FUTURE_WORK/ROADMAP.md`** - Planned features and priorities
- **`FUTURE_WORK/testing_and_qa.md`** - QA procedures
- **`tests/csv_regression_checklist.md`** - Known regression tests

### Field Incidents
- **`docs/incident_log.md`** - Field failures and mitigations (if exists)
- **`issues_to_address.md`** - Active backlog (if exists)

---

## QUICK COMMAND REFERENCE

### Development Commands
```bash
# Run compatibility checks
./tools/check_compatibility.sh

# Run preflight checks
python tools/preflight_check.py

# Update vendor dependencies
python tools/vendor_deps.py --refresh

# Run smoke test (from QGIS Python console)
from sartracker.tools.smoketest import run_smoke_test
from qgis.utils import iface
run_smoke_test(iface)
```

### Common Operations
```python
# Get plugin instance (from QGIS Python console)
from qgis.utils import plugins
sar = plugins.get('sartracker')

# Reload plugin
from qgis.utils import reloadPlugin
reloadPlugin('sartracker')

# Show diagnostics
sar._show_diagnostics()
```

---

## ERROR HANDLING PATTERN

```python
# Standard error handling for layer operations
def commit_feature_changes(self, layer, feature):
    """Commit feature changes with proper error handling."""
    try:
        if not layer.isEditable():
            if not layer.startEditing():
                raise RuntimeError(f"Failed to start editing: {layer.name()}")

        if not layer.addFeature(feature):
            raise RuntimeError(f"Failed to add feature: {layer.name()}")

        if not layer.commitChanges():
            errors = layer.commitErrors()
            raise RuntimeError(f"Commit failed: {', '.join(errors)}")

        return True

    except Exception as e:
        # Rollback on any error
        if layer.isEditable():
            layer.rollBack()

        # Notify user with actionable message
        from utils.notify import error
        error(self.iface.messageBar(), "Layer Error", str(e))

        # Re-raise for caller
        raise
```

---

## COORDINATE HANDLING (CRITICAL)

```python
# Always validate and document coordinate systems
def convert_to_wgs84(self, easting, northing, source_crs_id=2157):
    """Convert coordinates to WGS84.

    Args:
        easting: Easting in source CRS
        northing: Northing in source CRS
        source_crs_id: Source CRS EPSG code (default: 2157 = Irish Grid ITM)

    Returns:
        Tuple of (latitude, longitude) in WGS84 decimal degrees

    Raises:
        ValueError: If coordinates invalid
        RuntimeError: If transformation fails
    """
    # Validate inputs
    if not isinstance(easting, (int, float)) or not isinstance(northing, (int, float)):
        raise ValueError("Coordinates must be numeric")

    try:
        from qgis.core import QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsProject, QgsPointXY

        source_crs = QgsCoordinateReferenceSystem(source_crs_id)
        wgs84_crs = QgsCoordinateReferenceSystem(4326)  # WGS84 EPSG

        if not source_crs.isValid():
            raise RuntimeError(f"Invalid source CRS: {source_crs_id}")

        transform = QgsCoordinateTransform(source_crs, wgs84_crs, QgsProject.instance())
        point = QgsPointXY(easting, northing)
        transformed = transform.transform(point)

        return (transformed.y(), transformed.x())  # (lat, lon)

    except Exception as e:
        raise RuntimeError(f"Coordinate transformation failed: {e}")
```

---

## AI ASSISTANT GUIDELINES

### When Making Changes
1. **Read Documentation First** - Check `docs/AI_CODE_REFERENCE.md` for detailed patterns
2. **Check Existing Code** - Find similar implementations for consistency
3. **Consider Edge Cases** - Offline mode, network failures, invalid input
4. **Add Error Handling** - Never let exceptions crash the plugin
5. **Validate All Input** - Especially coordinates, user text, file paths
6. **Test Both Qt Versions** - Must work in Qt5 and Qt6
7. **Update Tests** - Add test coverage for new functionality
8. **Document Safety Decisions** - Explain why for life-safety code

### Priority Order (Non-Negotiable)
1. **Safety** - Lives depend on reliability
2. **Compatibility** - Must work on all supported QGIS versions (Qt5/Qt6)
3. **Security** - Protect credentials, validate input
4. **Performance** - UI must remain responsive (use background tasks)
5. **Features** - New capabilities

### Code Review Questions to Ask Yourself
- Does this work in both Qt5 and Qt6?
- What happens if the network fails?
- What happens if the user enters invalid data?
- What happens if the plugin is reloaded during this operation?
- Will this block the UI thread?
- Are credentials stored securely?
- Is coordinate validation comprehensive?
- Does this follow existing patterns?

---

## KEY PRINCIPLES

1. **Safety First** - Lives depend on this code working correctly
2. **Validate Everything** - Trust no input, especially coordinates
3. **Handle All Errors** - Never let exceptions crash the plugin silently
4. **Test Thoroughly** - Both Qt5 and Qt6, online and offline
5. **Document Clearly** - Others will maintain this code in emergencies
6. **Follow Patterns** - Use established compatibility patterns
7. **Ask Questions** - When in doubt, consult docs and ask for review
8. **Defensive Guards** - All async handlers check component existence
9. **Clean Lifecycle** - Disconnect signals, stop timers, cancel tasks in `unload()`
10. **No Assumptions** - Components may be deleted at any time
11. **No Extra Docs** - Do not create extra documentation unless specifically asked to do so. This includes summaries, reports, etc.

---

## REMEMBER

This is not just software. This is a tool that rescue coordinators depend on when lives are at stake. Every feature you add, every line you write, every bug you fix—it all matters.

A rescue volunteer's safety may depend on this plugin working correctly in the field, in poor conditions, with unreliable connectivity.

**Take your time. Follow the guidelines. Test thoroughly. Never compromise on quality.**

**Thank you for contributing to saving lives.**

---

**Document Version:** 1.0
**Last Updated:** 2025-11-22
**For Questions:** See `docs/AI_CODE_REFERENCE.md` for comprehensive patterns and examples
