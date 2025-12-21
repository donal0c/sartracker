# SAR-nh9: Per-Device Tracking Layers - Design Document

**Issue:** SAR-nh9
**Status:** Ready for Implementation
**Created:** 2025-12-21
**Updated:** 2025-12-21 (Research phase complete)
**Author:** Claude Code (Opus investigation)

---

## Executive Summary

Convert tracking layers from shared-layer architecture to per-device layers, giving each tracked device its own Current Position layer and Trail layer. This aligns with the Phase 4 per-item pattern used for markers and drawings.

**Effort Estimate:** 20-28 hours (2-3 days)
**Risk Level:** MEDIUM

---

## 1. Current Architecture

### Shared Layer Pattern

```
SAR Tracker/
├── Current Positions/
│   └── Current – Active     # Point layer with ALL devices
└── Breadcrumbs/
    └── Breadcrumbs          # LineString layer with ALL device trails
```

**Key Characteristics:**
- Single `Current – Active` layer contains one feature per device
- Single `Breadcrumbs` layer contains trail segments for all devices
- `device_id` field identifies which device owns each feature
- `QgsCategorizedSymbolRenderer` styles features by device_id
- Delta update pattern (SAR-lc6) for efficient updates

### TrackingLayerManager Stats
- **~1,688 lines** of code
- **~30 methods** (10 public, 20+ private)
- **12+ bug fixes** referenced (BUG-xxx, SAR-xxx comments)
- **5+ safety-critical** sections marked

### Data Flow (Current)

```
Provider (Traccar/CSV)
    │
    ▼
TraccarRefreshTask.run()  [Background thread]
    │
    ├─► get_devices()      → device list
    ├─► get_current()      → all current positions
    └─► get_breadcrumbs()  → all historical positions
    │
    ▼
task.results = {current, breadcrumbs, devices}
    │
    ▼
_on_refresh_complete()  [Main thread]
    │
    ▼
TrackingLayerManager.update_current_positions(positions)
    │
    ├─► sanitize_current_positions()
    ├─► acquire_layer_edit_lock()
    ├─► _delta_update_current_positions()  # SAR-lc6 pattern
    ├─► _apply_current_positions_style()  [deferred]
    └─► release_layer_edit_lock()
```

---

## 2. Target Architecture

### Per-Device Layer Pattern

```
SAR Tracker/
└── Tracking/
    ├── Alpha Team/           (Device group)
    │   ├── Position          (Point layer - single feature)
    │   └── Trail             (LineString layer - device segments only)
    ├── Bravo Team/
    │   ├── Position
    │   └── Trail
    └── Charlie Team/
        ├── Position
        └── Trail
```

**Key Characteristics:**
- Each device gets its own group under `Tracking/`
- Position layer contains single feature (latest position)
- Trail layer contains segments for that device only
- Simple symbol styling (no categorized renderer needed)
- Device-specific visibility control via layer checkbox
- Uses `PerItemLayerFactory` for layer creation

### Why Device-Centric Grouping?

| Alternative | Pros | Cons | Decision |
|-------------|------|------|----------|
| **Device-centric** | Matches coordinator mental model, one-click device toggle, scales with 30+ devices | Harder to "show all trails only" | **SELECTED** |
| Type-centric | Easy type-based filtering | 30+ entries per group, doesn't match workflow | Rejected |

**Rationale:** Coordinators think "show me Alpha Team" not "show me all positions then find Alpha."

---

## 3. Performance Analysis

### 3.1 Layer Count Impact (Research Finding)

| Metric | Shared (2 layers) | Per-Device (60 layers for 30 devices) |
|--------|-------------------|---------------------------------------|
| Memory overhead | ~20KB | ~600KB |
| Render jobs per refresh | 2 | 60 |
| Layer tree lookup | O(1) | O(n) but still microseconds |
| Project save/load | Fast | ~10-20% slower |

**Conclusion:** Acceptable for 30-50 devices. Consider shared layers if >100 devices.

### 3.2 Canvas Freeze Pattern (CRITICAL)

**Always freeze canvas during batch updates:**

```python
def update_all_device_positions(self, positions: List[Dict]):
    canvas = self.iface.mapCanvas()
    canvas.freeze(True)
    try:
        for pos in positions:
            device_id = pos['device_id']
            layer = self._ensure_device_position_layer(device_id, pos)
            self._update_device_position(layer, pos)
    finally:
        canvas.freeze(False)
        canvas.refresh()
```

### 3.3 Layer Tree Signal Blocking

**Block signals during bulk layer operations:**

```python
root = QgsProject.instance().layerTreeRoot()
root.blockSignals(True)
try:
    # Create/update multiple device layers
    pass
finally:
    root.blockSignals(False)
```

---

## 4. Layer Identification Strategy

### 4.1 The Rename Problem

Users can rename layers in QGIS. Traccar can update device names. We need stable identification.

### 4.2 Solution: Custom Properties

| Property | Purpose | Example |
|----------|---------|---------|
| `sartracker:device_id` | **Stable identifier** from Traccar | `"d1234567"` |
| `sartracker:device_name` | Display name at creation | `"Alpha Team"` |
| `sartracker:item_type` | Layer type | `"device_position"` or `"device_trail"` |
| `sartracker:item_id` | Unique layer UUID | `"550e8400-..."` |
| `sartracker:device_color` | Assigned color (hex) | `"#e41a1c"` |

### 4.3 Lookup Strategy

```python
def get_device_layers(device_id: str) -> Dict[str, QgsVectorLayer]:
    """Find position and trail layers by stable device_id."""
    result = {'position': None, 'trail': None}

    for layer in QgsProject.instance().mapLayers().values():
        if layer.customProperty('sartracker:device_id') != device_id:
            continue
        item_type = layer.customProperty('sartracker:item_type')
        if item_type == 'device_position':
            result['position'] = layer
        elif item_type == 'device_trail':
            result['trail'] = layer

    return result
```

### 4.4 In-Memory Cache

```python
class TrackingLayerManager:
    def __init__(self):
        # device_id -> {'position': layer, 'trail': layer}
        self._device_layer_cache: Dict[str, Dict[str, Optional[QgsVectorLayer]]] = {}
```

Cache invalidation triggers:
- Layer removed from project
- Mission reset (`reset_state()`)
- Cache miss (layer reference stale)

---

## 5. Threading & Async Safety

### 5.1 Current Safety Patterns (MUST PRESERVE)

1. **Mission generation** - Invalidates stale async data
2. **Application closing guards** - Prevents callbacks during shutdown
3. **Global layer edit lock** - Prevents concurrent edits
4. **Double-check pattern** (SAR-hi3) - Re-validates before write

### 5.2 Per-Device Extension

Extend mission generation to per-device:

```python
class TrackingLayerManager:
    def __init__(self):
        self._mission_generation = 0
        self._device_generations: Dict[str, int] = {}  # NEW

    def _get_device_generation(self, device_id: str) -> int:
        return self._device_generations.get(device_id, 0)

    def _increment_device_generation(self, device_id: str):
        """Call when device is removed or reset."""
        self._device_generations[device_id] = self._get_device_generation(device_id) + 1

    def reset_state(self):
        self._mission_generation += 1
        self._device_generations.clear()  # Invalidate all devices
```

### 5.3 Safe Async Callback Pattern

```python
def _on_device_task_complete(self, task: QgsTask):
    # 1. Check shutdown flags FIRST
    if getattr(self.task_manager, '_shutting_down', False):
        return
    if getattr(self.layer_manager, '_application_closing', False):
        return
    if not getattr(self, 'iface', None):
        return

    # 2. Validate mission generation
    task_mission_gen = task.property("sartracker:mission_generation")
    if task_mission_gen != self._mission_generation:
        return

    # 3. Validate device generation
    device_id = task.property("sartracker:device_id")
    task_device_gen = task.property("sartracker:device_generation")
    if task_device_gen != self._get_device_generation(device_id):
        logger.info("Stale task for device %s - discarding", device_id)
        return

    # 4. Fresh layer lookup (NEVER cache across async boundary)
    layer = self._get_device_layer(device_id)
    if not layer or not layer.isValid():
        return

    # 5. Re-validate immediately before write (SAR-hi3 pattern)
    if task_device_gen != self._get_device_generation(device_id):
        return

    # 6. Safe to update
    self._apply_device_trail_update(layer, task)
```

---

## 6. Schema Changes Required

### 6.1 GroupNames (layers/schema.py)

```python
class GroupNames:
    # ... existing ...
    TRACKING = "Tracking"  # Already exists
```

### 6.2 ItemTypes (controllers/per_item_layer_factory.py)

```python
class ItemType:
    # ... existing marker/drawing types ...
    DEVICE_POSITION = "device_position"
    DEVICE_TRAIL = "device_trail"
```

### 6.3 Geometry Types

```python
ITEM_GEOMETRY_TYPES = {
    # ... existing ...
    ItemType.DEVICE_POSITION: "Point",
    ItemType.DEVICE_TRAIL: "LineString",
}
```

### 6.4 Field Definitions

```python
DEVICE_POSITION_FIELDS = [
    {"name": "id", "type": "String", "length": 36},           # Feature UUID
    {"name": "device_id", "type": "String", "length": 50},    # Stable device ID
    {"name": "name", "type": "String", "length": 100},        # Display name
    {"name": "timestamp", "type": "String", "length": 40},    # ISO8601
    {"name": "altitude", "type": "Double"},                   # Meters
    {"name": "speed", "type": "Double"},                      # km/h
    {"name": "battery", "type": "Double"},                    # Percentage
    {"name": "accuracy", "type": "Double"},                   # GPS accuracy (m)
    {"name": "source", "type": "String", "length": 50},       # Data source
]

DEVICE_TRAIL_FIELDS = [
    {"name": "id", "type": "String", "length": 36},           # Segment UUID
    {"name": "device_id", "type": "String", "length": 50},    # Stable device ID
    {"name": "name", "type": "String", "length": 100},        # Display name
    {"name": "segment_index", "type": "Int"},                 # Segment order
    {"name": "start_time", "type": "String", "length": 40},   # First point time
    {"name": "end_time", "type": "String", "length": 40},     # Last point time
    {"name": "point_count", "type": "Int"},                   # Points in segment
    {"name": "distance_m", "type": "Double"},                 # Segment length
]
```

### 6.5 Group Path Function

```python
def get_per_device_group_path(device_name: str) -> List[str]:
    """Get group path for a device's tracking layers."""
    return [GroupNames.ROOT, GroupNames.TRACKING, device_name]
```

---

## 7. Implementation Plan

### Phase 1: Per-Device Current Positions (SAR-33p)

**Effort:** 8-10 hours
**Risk:** LOW (simpler than trails)
**Feature Flag:** `USE_PER_DEVICE_POSITIONS = False`

**Steps:**
1. Add `ItemType.DEVICE_POSITION` to `per_item_layer_factory.py`
2. Add `DEVICE_POSITION_FIELDS` to `schema.py`
3. Add `get_per_device_group_path()` helper
4. Implement in `tracking_manager.py`:
   - `_device_position_layers: Dict[str, QgsVectorLayer]` cache
   - `_ensure_device_group(device_name)` - create/get device group
   - `_ensure_device_position_layer(device_id, position)` - create/get layer
   - `_update_device_position(layer, position)` - single feature update
   - `_apply_device_position_style(layer, device_id)` - simple marker
   - `_update_positions_per_device(positions)` - main entry with canvas freeze
5. Add feature flag routing in `update_current_positions()`
6. Test with 10+ devices
7. Verify rollback works

**Acceptance Criteria:**
- [ ] ItemType.DEVICE_POSITION added to factory
- [ ] Tracking group created on first device
- [ ] Device subgroup created with device name
- [ ] Position layer created under device subgroup
- [ ] Single feature updated (not accumulated)
- [ ] Device color matches existing shared-layer color
- [ ] Feature flag USE_PER_DEVICE_POSITIONS works
- [ ] Rollback to shared layers works
- [ ] 10+ devices tested
- [ ] Plugin reload preserves layers

---

### Phase 2: Per-Device Trails (SAR-nj0)

**Effort:** 8-12 hours
**Risk:** MEDIUM (async complexity)
**Feature Flag:** `USE_PER_DEVICE_TRAILS = False`
**Depends on:** SAR-33p complete

**Additional Complexity:**
- Multiple features per layer (trail segments)
- Async background processing
- Time-based segmentation per device
- Memory caps per device

**Steps:**
1. Add `ItemType.DEVICE_TRAIL` to factory
2. Add `DEVICE_TRAIL_FIELDS` to schema
3. Implement per-device generation tracking
4. Implement in `tracking_manager.py`:
   - `_device_trail_layers: Dict[str, QgsVectorLayer]` cache
   - `_ensure_device_trail_layer(device_id, position)` - create/get layer
   - `_update_device_trail(layer, segments)` - replace segments
   - `_apply_device_trail_style(layer, device_id)` - simple line
   - `_update_trails_per_device(positions, gap_minutes)` - main entry
5. Adapt async breadcrumb processing:
   - Store device_id and device_generation in task properties
   - Group positions by device before segmentation
   - Apply segments to per-device trail layers
6. Update memory caps to per-device limits
7. Test with long trails (1000+ points)

**Acceptance Criteria:**
- [ ] ItemType.DEVICE_TRAIL added to factory
- [ ] Trail layer created under device subgroup
- [ ] Trail segments specific to device only
- [ ] Time-based segmentation works per device
- [ ] Async processing works with per-device layers
- [ ] Memory caps enforced per device
- [ ] Feature flag USE_PER_DEVICE_TRAILS works
- [ ] Rollback to shared breadcrumbs works
- [ ] Long trails (1000+ points) tested
- [ ] Mission generation prevents stale data

---

### Phase 3: Migration (SAR-0uy)

**Effort:** 4-6 hours
**Risk:** LOW (non-destructive)
**Depends on:** SAR-33p and SAR-nj0 complete

**Steps:**
1. Detect shared tracking layers on project load
2. Extract device list from shared layer features
3. For each device:
   - Create device group
   - Create position and trail layers
   - Copy features from shared to per-device
4. Archive shared layers (rename to `_archive_*`, hide)
5. Update schema version to 4

**Migration Strategy:**
- **Non-destructive** - Keep shared layers as backup
- **Gradual** - Migrate one device at a time
- **Reversible** - Feature flag can restore shared behavior

**Acceptance Criteria:**
- [ ] Shared layers detected on project load
- [ ] All devices extracted correctly
- [ ] Per-device layers created for each device
- [ ] Position features copied correctly
- [ ] Trail segments copied correctly
- [ ] Shared layers archived (not deleted)
- [ ] Schema version updated to 4
- [ ] Rollback restores shared layers
- [ ] Migration idempotent (safe to run twice)

---

## 8. Device Lifecycle Handling

### 8.1 New Device Appears

```python
def _ensure_device_layers(self, device_id: str, device_name: str):
    """Create position and trail layers for a new device."""
    # Check cache
    if device_id in self._device_layer_cache:
        cached = self._device_layer_cache[device_id]
        if cached.get('position') and cached['position'].isValid():
            return cached

    # Search by custom property (handles plugin reload)
    existing = self._get_device_layers_by_property(device_id)
    if existing['position']:
        self._device_layer_cache[device_id] = existing
        return existing

    # Create new layers
    device_group = self._ensure_device_group(device_name)

    position_layer = self._create_device_position_layer(device_id, device_name, device_group)
    trail_layer = self._create_device_trail_layer(device_id, device_name, device_group)

    # Apply consistent styling
    color = self._get_device_color(device_id)
    self._apply_device_position_style(position_layer, color)
    self._apply_device_trail_style(trail_layer, color)

    # Cache and return
    self._device_layer_cache[device_id] = {
        'position': position_layer,
        'trail': trail_layer
    }
    return self._device_layer_cache[device_id]
```

### 8.2 Device Name Change

```python
def _handle_device_name_change(self, device_id: str, new_name: str):
    """Update display name when device renamed in Traccar."""
    layers = self._get_device_layers(device_id)
    if not layers['position']:
        return

    old_name = layers['position'].customProperty('sartracker:device_name')
    if old_name == new_name:
        return

    # Update custom property
    for layer in [layers['position'], layers['trail']]:
        if layer:
            layer.setCustomProperty('sartracker:device_name', new_name)

    # Rename group
    device_group = self._find_device_group(old_name)
    if device_group:
        device_group.setName(new_name)
```

### 8.3 Device Removed

```python
def remove_device(self, device_id: str, hard_delete: bool = False):
    """Remove device tracking layers."""
    # Increment generation to invalidate async tasks
    self._increment_device_generation(device_id)

    # Remove from cache
    self._device_layer_cache.pop(device_id, None)

    # Delete layers
    layers = self._get_device_layers_by_property(device_id)
    for layer in [layers['position'], layers['trail']]:
        if layer:
            QgsProject.instance().removeMapLayer(layer.id())

    # Remove empty group
    # ...
```

---

## 9. Risk Assessment

| Risk | Severity | Mitigation |
|------|----------|------------|
| Position data loss during transition | CRITICAL | Feature flag for rollback |
| Stale layer refs in async callbacks | HIGH | Per-device generation tracking |
| Concurrent layer update contention | HIGH | Sequential updates with canvas freeze |
| Memory exhaustion with many devices | MEDIUM | Per-device memory caps |
| QGIS performance 100+ layers | MEDIUM | Test at scale, lazy loading |
| Device name collisions | LOW | Use device_id for identification |

### Life-Safety Implications

- **Position accuracy is critical** - rescuers depend on device locations
- **Must not lose data** during refresh cycles
- **Must handle offline/reconnect** gracefully
- **Rollback capability required** before production use

---

## 10. Testing Requirements

### Unit Tests
- [ ] Layer creation for new device
- [ ] Position update to existing layer
- [ ] Multiple devices simultaneously
- [ ] Device removal handling
- [ ] Name vs ID fallback
- [ ] Device generation tracking

### Integration Tests
- [ ] Provider refresh cycle with per-device layers
- [ ] Plugin reload with existing device layers
- [ ] Mission save/load with device layers
- [ ] Async task cancellation mid-update
- [ ] Mission reset during active tracking

### Performance Tests
- [ ] 10 devices - baseline
- [ ] 20 devices - typical mission
- [ ] 50 devices - large mission
- [ ] 100 devices - stress test

### Manual Tests
- [ ] Layer tree organization correct
- [ ] Device visibility toggles work
- [ ] Color consistency (position + trail same color)
- [ ] Layer rename survives refresh
- [ ] Export individual device track

---

## 11. Files to Modify

| File | Changes |
|------|---------|
| `layers/schema.py` | Add DEVICE_POSITION_FIELDS, DEVICE_TRAIL_FIELDS, get_per_device_group_path() |
| `controllers/per_item_layer_factory.py` | Add ItemType.DEVICE_POSITION, DEVICE_TRAIL |
| `controllers/layer_managers/tracking_manager.py` | Feature flags, per-device methods, device caches, generation tracking |
| `controllers/layers_controller.py` | Update tracking layer retrieval if needed |

---

## 12. Rollback Plan

Each phase has independent feature flag:

```python
class TrackingLayerManager:
    USE_PER_DEVICE_POSITIONS = False  # Phase 1
    USE_PER_DEVICE_TRAILS = False     # Phase 2
```

**Rollback Steps:**
1. Set feature flag to `False`
2. Restart plugin or QGIS
3. Shared layers will be used again
4. Per-device layers remain but are not updated

**Full Rollback (if migration completed):**
1. Unhide archived shared layers
2. Set both feature flags to `False`
3. Remove per-device layers manually or via cleanup script

---

## 13. References

- **ADR-001:** Layer Storage Architecture (`WORK_PLAN/ADR-001-layer-storage-architecture.md`)
- **CLAUDE.md:** Safety patterns and guardrails
- **AI_CODE_REFERENCE.md:** Code patterns and examples
- **Existing per-item implementation:** `controllers/layer_managers/marker_manager.py`
- **Research agents:** 5 Opus agents analyzed web resources, codebase, UX patterns, threading safety, and schema design

---

## Appendix A: Position Data Format

```python
{
    'device_id': str,      # REQUIRED - stable device identifier
    'name': str,           # REQUIRED - device display name
    'lat': float,          # REQUIRED - latitude WGS84
    'lon': float,          # REQUIRED - longitude WGS84
    'ts': str,             # REQUIRED - ISO8601 timestamp
    'altitude': float,     # OPTIONAL
    'speed': float,        # OPTIONAL
    'battery': float,      # OPTIONAL
}
```

## Appendix B: Key TrackingLayerManager Methods

### Methods to Keep (Reusable)
- `_layer_transaction()` - Core safety pattern
- `_safe_close_layer_edit()` - Cleanup safety
- `_clear_layer_features()` - Truncate helper
- `_get_device_color()` - Color consistency
- `reset_state()` - Session management
- `cleanup()` - Resource cleanup

### Methods to Add for Per-Device
- `_ensure_device_group()` - Create/get device group
- `_ensure_device_position_layer()` - Create/get position layer
- `_ensure_device_trail_layer()` - Create/get trail layer
- `_update_device_position()` - Single feature update
- `_update_device_trail()` - Replace trail segments
- `_update_positions_per_device()` - Main entry point
- `_update_trails_per_device()` - Main entry point
- `_get_device_generation()` - Generation tracking
- `_increment_device_generation()` - Generation tracking
