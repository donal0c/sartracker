# LayersController Restructuring Plan

**Created:** 2025-10-19
**Status:** Ready for implementation
**Estimated Time:** 2-3 hours
**Priority:** HIGH - Do before implementing next tools

---

## 🎯 OBJECTIVE

Split the monolithic `controllers/layers_controller.py` (1350 lines) into manageable, focused layer manager classes following Single Responsibility Principle.

**Goals:**
- Each layer manager handles 1-2 related layer types
- ~150-200 lines per manager
- Easy to test individually
- Non-breaking change for existing code
- Maintains all Qt5/Qt6 compatibility
- Preserves all bug fixes and improvements

---

## 📊 CURRENT STATE

### File Size Issues:
```
controllers/layers_controller.py: 1350 lines
├── 11 different layer types
├── 18+ public methods
├── Mix of concerns (creation, styling, updating)
└── Growing with each new feature
```

### Layer Types Currently Managed:
1. Current Positions (tracking)
2. Breadcrumbs (tracking)
3. IPP/LKP markers
4. Clues markers
5. Hazards markers
6. Lines
7. Search Areas
8. Range Rings
9. Bearing Lines
10. Search Sectors
11. Text Labels

---

## 🏗️ PROPOSED STRUCTURE

### New Directory Layout:
```
controllers/
├── __init__.py
├── layers_controller.py (orchestrator - ~200 lines)
└── layer_managers/
    ├── __init__.py
    ├── base_manager.py (abstract base class)
    ├── tracking_manager.py (positions, breadcrumbs)
    ├── marker_manager.py (IPP/LKP, clues, hazards)
    └── drawing_manager.py (lines, rings, areas, bearing lines, sectors, labels)
```

### Why This Structure:
- **3 managers** instead of 6-8 (keeps it simple)
- Groups related functionality
- Easy to split DrawingManager later if needed
- Minimal changes to existing code

---

## 📋 IMPLEMENTATION STEPS

### **STEP 1: Create Base Manager (30 mins)**

**File:** `controllers/layer_managers/base_manager.py`

```python
# -*- coding: utf-8 -*-
"""
Base Layer Manager

Abstract base class for all layer managers.
Provides common functionality for layer management.

Qt5/Qt6 Compatible: Uses qgis.PyQt for all imports.
"""

from abc import ABC, abstractmethod
from qgis.core import QgsProject, QgsVectorLayer
from qgis.PyQt.QtGui import QColor
import random


class BaseLayerManager(ABC):
    """
    Abstract base class for layer managers.

    Each manager handles creation and management of one or more related layer types.
    """

    # Layer group name - all layers belong to this group
    LAYER_GROUP_NAME = "SAR Tracking"

    def __init__(self, iface):
        """
        Initialize base manager.

        Args:
            iface: QGIS interface
        """
        self.iface = iface
        self.project = QgsProject.instance()

        # Color management for devices (shared across managers)
        self.device_colors = {}

    def get_or_create_layer_group(self):
        """
        Get or create SAR Tracking layer group.

        Returns:
            QgsLayerTreeGroup
        """
        root = self.project.layerTreeRoot()
        group = root.findGroup(self.LAYER_GROUP_NAME)
        if not group:
            group = root.insertGroup(0, self.LAYER_GROUP_NAME)
        return group

    def _get_device_color(self, device_id: str) -> QColor:
        """
        Get consistent color for a device.

        Args:
            device_id: Device identifier

        Returns:
            QColor for this device
        """
        if device_id not in self.device_colors:
            # Generate a distinct color (avoid very dark colors)
            self.device_colors[device_id] = QColor(
                random.randint(50, 255),
                random.randint(50, 255),
                random.randint(50, 255)
            )
        return self.device_colors[device_id]

    def _add_layer_to_group(self, layer: QgsVectorLayer):
        """
        Add layer to SAR Tracking group.

        Args:
            layer: Layer to add
        """
        self.project.addMapLayer(layer, False)
        group = self.get_or_create_layer_group()
        group.addLayer(layer)

    @abstractmethod
    def get_managed_layer_names(self):
        """
        Return list of layer names this manager handles.

        Returns:
            List[str]: Layer names
        """
        pass
```

**Checklist:**
- [ ] Create `controllers/layer_managers/` directory
- [ ] Create `__init__.py` in layer_managers/
- [ ] Create base_manager.py with above code
- [ ] Test imports: `from controllers.layer_managers.base_manager import BaseLayerManager`

---

### **STEP 2: Create Tracking Manager (45 mins)**

**File:** `controllers/layer_managers/tracking_manager.py`

**What to Extract:**
- `_get_or_create_current_layer()`
- `_get_or_create_breadcrumbs_layer()`
- `update_current_positions()`
- `update_breadcrumbs()`
- `_apply_current_positions_style()`
- `_apply_breadcrumbs_style()`

**Template:**
```python
# -*- coding: utf-8 -*-
"""
Tracking Layer Manager

Manages real-time tracking layers: current positions and breadcrumb trails.

Qt5/Qt6 Compatible: Uses qgis.PyQt for all imports.
"""

from typing import List, Dict
from datetime import datetime
from collections import defaultdict

from qgis.core import (
    QgsVectorLayer, QgsField, QgsFeature, QgsGeometry,
    QgsPointXY, QgsCategorizedSymbolRenderer, QgsRendererCategory,
    QgsMarkerSymbol, QgsLineSymbol
)

from .base_manager import BaseLayerManager


class TrackingLayerManager(BaseLayerManager):
    """Manages tracking layers for live device positions and trails."""

    def __init__(self, iface):
        super().__init__(iface)
        self.first_load = True

    def get_managed_layer_names(self):
        return ["Current Positions", "Breadcrumbs"]

    # Copy methods from layers_controller.py:
    # - _get_or_create_current_layer()
    # - _get_or_create_breadcrumbs_layer()
    # - update_current_positions()
    # - update_breadcrumbs()
    # - _apply_current_positions_style()
    # - _apply_breadcrumbs_style()
```

**Checklist:**
- [ ] Create tracking_manager.py
- [ ] Copy methods from layers_controller.py (lines ~95-350)
- [ ] Update `self.project` references (already available from base)
- [ ] Update `self.iface` references (already available from base)
- [ ] Keep all Qt5/Qt6 compatible code (integer type codes)
- [ ] Test: Load CSV and verify positions/breadcrumbs still work

---

### **STEP 3: Create Marker Manager (45 mins)**

**File:** `controllers/layer_managers/marker_manager.py`

**What to Extract:**
- `_get_or_create_ipp_lkp_layer()`
- `_get_or_create_clues_layer()`
- `_get_or_create_hazards_layer()`
- `add_ipp_lkp()`
- `add_clue()`
- `add_hazard()`

**Template:**
```python
# -*- coding: utf-8 -*-
"""
Marker Layer Manager

Manages point marker layers: IPP/LKP, Clues, and Hazards.

Qt5/Qt6 Compatible: Uses qgis.PyQt for all imports.
"""

from qgis.core import (
    QgsVectorLayer, QgsField, QgsFeature, QgsGeometry,
    QgsPointXY
)

from .base_manager import BaseLayerManager


class MarkerLayerManager(BaseLayerManager):
    """Manages marker layers for SAR operations."""

    def get_managed_layer_names(self):
        return ["IPP/LKP", "Clues", "Hazards"]

    # Copy methods from layers_controller.py:
    # - _get_or_create_ipp_lkp_layer()
    # - _get_or_create_clues_layer()
    # - _get_or_create_hazards_layer()
    # - add_ipp_lkp()
    # - add_clue()
    # - add_hazard()
```

**Checklist:**
- [ ] Create marker_manager.py
- [ ] Copy methods from layers_controller.py (lines ~351-629)
- [ ] Maintain all field definitions with integer type codes
- [ ] Test: Add IPP/LKP, Clue, and Hazard markers

---

### **STEP 4: Create Drawing Manager (60 mins)**

**File:** `controllers/layer_managers/drawing_manager.py`

**What to Extract:**
- All `_get_or_create_*` methods for drawing layers
- All `add_*` methods for drawing features
- Lines, Search Areas, Range Rings, Bearing Lines, Sectors, Text Labels

**Template:**
```python
# -*- coding: utf-8 -*-
"""
Drawing Layer Manager

Manages all drawing/annotation layers: lines, areas, rings, sectors, labels.

Qt5/Qt6 Compatible: Uses qgis.PyQt for all imports.
"""

from typing import List
import math
import uuid
from datetime import datetime

from qgis.core import (
    QgsVectorLayer, QgsField, QgsFeature, QgsGeometry,
    QgsPointXY, QgsDistanceArea, QgsProject
)

from .base_manager import BaseLayerManager


class DrawingLayerManager(BaseLayerManager):
    """Manages all drawing and annotation layers."""

    def get_managed_layer_names(self):
        return [
            "Lines",
            "Search Areas",
            "Range Rings",
            "Bearing Lines",
            "Search Sectors",
            "Text Labels"
        ]

    # Copy all methods from layers_controller.py:
    # Lines: ~630-737
    # Search Areas: ~738-856
    # Range Rings: ~857-1050 (includes geodesic calculations!)
    # Bearing Lines: ~990-1100 (includes geodesic calculations!)
    # Search Sectors: ~1101-1200
    # Text Labels: ~1201-1300
```

**CRITICAL:** Preserve the geodesic calculation fixes in:
- `add_range_ring()` - WGS84 ellipsoid parameters
- `add_bearing_line()` - WGS84 ellipsoid parameters

**Checklist:**
- [ ] Create drawing_manager.py
- [ ] Copy all drawing layer methods
- [ ] **VERIFY geodesic calculations preserved correctly**
- [ ] Test each tool: Lines, Range Rings
- [ ] Test future tools will work: Search Areas, Bearing Lines, Sectors, Labels

---

### **STEP 5: Update LayersController Orchestrator (30 mins)**

**File:** `controllers/layers_controller.py`

**New Implementation:**
```python
# -*- coding: utf-8 -*-
"""
Layers Controller

Orchestrates all layer managers. Provides unified interface for layer operations.

Qt5/Qt6 Compatible: Uses qgis.PyQt for all imports.
"""

from qgis.core import QgsProject
from .layer_managers.tracking_manager import TrackingLayerManager
from .layer_managers.marker_manager import MarkerLayerManager
from .layer_managers.drawing_manager import DrawingLayerManager


class LayersController:
    """
    Main controller for SAR layer management.

    Delegates to specialized managers for different layer types.
    """

    def __init__(self, iface):
        """
        Initialize layers controller.

        Args:
            iface: QGIS interface
        """
        self.iface = iface
        self.project = QgsProject.instance()

        # Initialize managers
        self.tracking = TrackingLayerManager(iface)
        self.markers = MarkerLayerManager(iface)
        self.drawings = DrawingLayerManager(iface)

    # ===== Tracking Methods (delegate to tracking manager) =====

    def update_current_positions(self, positions):
        """Update current positions layer."""
        return self.tracking.update_current_positions(positions)

    def update_breadcrumbs(self, positions, time_gap_minutes=5):
        """Update breadcrumb trails layer."""
        return self.tracking.update_breadcrumbs(positions, time_gap_minutes)

    # ===== Marker Methods (delegate to marker manager) =====

    def add_ipp_lkp(self, name, lat, lon, subject_category, description=""):
        """Add IPP/LKP marker."""
        return self.markers.add_ipp_lkp(name, lat, lon, subject_category, description)

    def add_clue(self, name, lat, lon, clue_type, confidence, description=""):
        """Add clue marker."""
        return self.markers.add_clue(name, lat, lon, clue_type, confidence, description)

    def add_hazard(self, name, lat, lon, hazard_type, severity, description=""):
        """Add hazard marker."""
        return self.markers.add_hazard(name, lat, lon, hazard_type, severity, description)

    # ===== Drawing Methods (delegate to drawing manager) =====

    def add_line(self, name, points_wgs84, description="", color="#FF0000", width=2):
        """Add line feature."""
        return self.drawings.add_line(name, points_wgs84, description, color, width)

    def add_search_area(self, name, polygon_wgs84, team="Unassigned", status="Planned",
                       priority="Medium", POA=50.0, terrain="", search_method="",
                       color="#0064FF", notes=""):
        """Add search area polygon."""
        return self.drawings.add_search_area(
            name, polygon_wgs84, team, status, priority, POA,
            terrain, search_method, color, notes
        )

    def add_range_ring(self, name, center_wgs84, radius_m, label="",
                      color="#FFA500", lpb_category="", percentile=0):
        """Add range ring (circle)."""
        return self.drawings.add_range_ring(
            name, center_wgs84, radius_m, label, color, lpb_category, percentile
        )

    def add_bearing_line(self, name, origin_wgs84, bearing, distance_m,
                        label="", color="#800080"):
        """Add bearing line."""
        return self.drawings.add_bearing_line(
            name, origin_wgs84, bearing, distance_m, label, color
        )

    def add_search_sector(self, name, center_wgs84, radius_m, start_bearing,
                         end_bearing, label="", color="#FF00FF"):
        """Add search sector (pie slice)."""
        return self.drawings.add_search_sector(
            name, center_wgs84, radius_m, start_bearing, end_bearing, label, color
        )

    def add_text_label(self, name, point_wgs84, text, font_size=12,
                      rotation=0, color="#000000"):
        """Add text label."""
        return self.drawings.add_text_label(
            name, point_wgs84, text, font_size, rotation, color
        )

    def get_or_create_layer_group(self):
        """Get or create SAR Tracking layer group."""
        return self.tracking.get_or_create_layer_group()
```

**Checklist:**
- [ ] Replace old layers_controller.py with orchestrator
- [ ] Verify all public methods still available
- [ ] Check all imports in sartracker.py still work
- [ ] Check all imports in drawing tools still work

---

### **STEP 6: Update Imports (15 mins)**

**No changes needed!** The public API remains the same:
```python
from .controllers.layers_controller import LayersController

# All these still work:
layers_controller.add_line(...)
layers_controller.add_range_ring(...)
layers_controller.update_current_positions(...)
```

**Checklist:**
- [ ] Verify sartracker.py imports work
- [ ] Verify all drawing tools work
- [ ] Verify marker dialog works
- [ ] No code changes needed outside controllers/

---

## ✅ TESTING CHECKLIST

After each step, verify:

### Basic Functionality:
- [ ] Plugin loads without errors
- [ ] SAR Panel displays correctly
- [ ] All buttons work

### Tracking Features:
- [ ] Load CSV file
- [ ] Current positions display
- [ ] Breadcrumb trails display
- [ ] Device colors consistent
- [ ] Refresh works

### Marker Features:
- [ ] Add IPP/LKP marker (all subject categories)
- [ ] Add Clue marker (all clue types)
- [ ] Add Hazard marker (all hazard types)
- [ ] Markers appear on map
- [ ] Markers saved to layers

### Drawing Tools:
- [ ] Lines Tool works (click points, right-click finish)
- [ ] Range Rings Tool works (manual mode)
- [ ] Range Rings Tool works (LPB mode)
- [ ] Distance calculations correct
- [ ] Geodesic calculations accurate

### Plugin Lifecycle:
- [ ] Plugin reloads cleanly (F5)
- [ ] Plugin unloads without errors
- [ ] QGIS doesn't crash on plugin reload

---

## 🚨 CRITICAL REQUIREMENTS

### Must Preserve:
1. ✅ **All Qt5/Qt6 compatibility**
   - Integer type codes for QgsField (10=String, 2=Int, 6=Double)
   - No Qt.Enum usage
   - No QVariant usage
   - Use qgis.PyQt for all imports

2. ✅ **All bug fixes from audit**
   - Geodesic calculations with WGS84 ellipsoid
   - Coordinate rounding (not truncation)
   - Timestamp parsing error handling
   - Memory efficient layer clearing
   - Error handling in transformations

3. ✅ **Public API unchanged**
   - All existing calls to LayersController work
   - No changes to sartracker.py needed
   - No changes to drawing tools needed

4. ✅ **Layer group management**
   - All layers still in "SAR Tracking" group
   - Layer order preserved
   - Styling preserved

---

## 📦 ROLLBACK PLAN

If anything breaks:

1. **Git commit before starting:**
   ```bash
   git add -A
   git commit -m "Before LayersController refactor"
   ```

2. **Keep backup:**
   ```bash
   cp controllers/layers_controller.py controllers/layers_controller.BACKUP.py
   ```

3. **Rollback command:**
   ```bash
   git checkout HEAD -- controllers/
   ```

---

## 📈 BENEFITS

### Immediate:
- Easier to find layer-specific code
- Each manager ~200 lines (manageable)
- Better code organization
- Easier to test

### Long-term:
- Easy to add new layer types
- Clear separation of concerns
- Better for team development
- Reduces merge conflicts
- Easier to maintain

### Future:
- Can split DrawingManager if it grows too large
- Can add more managers (export_manager, style_manager, etc.)
- Easy to add unit tests for each manager
- Better error isolation

---

## 🎯 SUCCESS CRITERIA

Refactoring is successful when:
- ✅ All existing functionality works
- ✅ No new bugs introduced
- ✅ Plugin reloads cleanly
- ✅ All tests pass
- ✅ Code is more maintainable
- ✅ Public API unchanged
- ✅ Git history clean with good commits

---

## 📝 COMMIT STRATEGY

Suggested git commits:

1. `feat: Add base layer manager abstract class`
2. `refactor: Extract tracking layers to TrackingLayerManager`
3. `refactor: Extract marker layers to MarkerLayerManager`
4. `refactor: Extract drawing layers to DrawingLayerManager`
5. `refactor: Update LayersController to orchestrator pattern`
6. `test: Verify all functionality after refactor`
7. `docs: Update architecture documentation`

---

## 💡 TIPS FOR IMPLEMENTATION

1. **Work incrementally** - One manager at a time
2. **Test after each step** - Don't continue if tests fail
3. **Use Plugin Reloader (F5)** - Fast iteration
4. **Keep backup** - Easy rollback if needed
5. **Check imports** - Make sure qgis.PyQt everywhere
6. **Preserve comments** - Copy all documentation
7. **Watch for self.** references** - Update to use managers

---

## 🔗 REFERENCES

- Original file: `controllers/layers_controller.py`
- Base tool pattern: `maptools/base_drawing_tool.py`
- Qt5/Qt6 guide: `docs/QT5_QT6_COMPATIBILITY.md`
- Audit findings: `PHASE3_PROGRESS.md` (Day 7 section)

---

**Ready to implement? Follow steps 1-6 carefully and test thoroughly!**
