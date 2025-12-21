# SAR-nh9: Per-Device Tracking Layers - Design Document

**Issue:** SAR-nh9
**Status:** Design Complete
**Created:** 2025-12-21
**Author:** Claude Code (Opus investigation)

---

## Executive Summary

Convert tracking layers from shared-layer architecture to per-device layers, giving each tracked device its own Current Position layer and Trail layer. This aligns with the Phase 4 per-item pattern used for markers and drawings.

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
- Full replacement on every refresh (clear all, re-add all)

### TrackingLayerManager Stats
- **1,435 lines** of code
- **~30 methods** (10 public, 20+ private)
- **12+ bug fixes** referenced (BUG-xxx comments)
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
    ├─► _layer_transaction():
    │       ├─► truncate/clear all features
    │       └─► add features for each device
    ├─► _apply_current_positions_style()  [deferred]
    └─► release_layer_edit_lock()
```

---

## 2. Proposed Architecture

### Per-Device Layer Pattern

```
SAR Tracker/
└── Tracking/
    ├── Alpha Team/
    │   ├── Position        # Point layer (single feature)
    │   └── Trail           # LineString layer (trail segments)
    ├── Bravo Team/
    │   ├── Position
    │   └── Trail
    ├── Drone 1/
    │   ├── Position
    │   └── Trail
    └── [Additional devices...]
```

**Key Characteristics:**
- Each device gets its own group under `Tracking/`
- Position layer contains single feature (latest position)
- Trail layer contains segments for that device only
- Simple symbol styling (no categorized renderer needed)
- Device-specific visibility control via layer checkbox
- Uses `PerItemLayerFactory` for layer creation

### Proposed Data Flow

```
Provider (Traccar/CSV)
    │
    ▼
TraccarRefreshTask.run()  [Background thread]
    │ (unchanged)
    ▼
task.results = {current, breadcrumbs, devices}
    │
    ▼
_on_refresh_complete()  [Main thread]
    │
    ▼
TrackingDeviceManager.update_current_positions(positions)
    │
    ├─► Group positions by device_id
    │
    └─► FOR EACH device_id:
            ├─► _ensure_device_position_layer(device_id)
            │       └─► Create layer if not exists
            └─► _update_device_position(layer, position)
                    ├─► _layer_transaction():
                    │       ├─► clear single feature
                    │       └─► add new position
                    └─► _apply_device_style()
```

---

## 3. Schema Changes Required

### 3.1 GroupNames (layers/schema.py)

```python
class GroupNames:
    # ... existing ...

    # Per-device tracking (SAR-nh9)
    TRACKING = "Tracking"  # Already exists, unused
```

### 3.2 ItemTypes (controllers/per_item_layer_factory.py)

```python
class ItemType:
    # ... existing marker/drawing types ...

    # Tracking item types (SAR-nh9)
    DEVICE_POSITION = "device_position"
    DEVICE_TRAIL = "device_trail"
```

### 3.3 Geometry Types

```python
ITEM_GEOMETRY_TYPES = {
    # ... existing ...
    ItemType.DEVICE_POSITION: "Point",
    ItemType.DEVICE_TRAIL: "LineString",
}
```

### 3.4 Group Path Function

```python
def get_per_device_group_path(device_name: str) -> List[str]:
    """Get group path for a device's tracking layers."""
    return [GroupNames.ROOT, GroupNames.TRACKING, device_name]
```

### 3.5 Field Definitions

```python
# Per-device position fields
DEVICE_POSITION_FIELDS = [
    {"name": "device_id", "type": "String", "length": 50},
    {"name": "name", "type": "String", "length": 100},
    {"name": "timestamp", "type": "String", "length": 40},
    {"name": "altitude", "type": "Double"},
    {"name": "speed", "type": "Double"},
    {"name": "battery", "type": "Double"},
]

# Per-device trail fields
DEVICE_TRAIL_FIELDS = [
    {"name": "device_id", "type": "String", "length": 50},
    {"name": "name", "type": "String", "length": 100},
    {"name": "timestamp", "type": "String", "length": 40},
    {"name": "segment_start", "type": "String", "length": 40},
    {"name": "segment_end", "type": "String", "length": 40},
    {"name": "point_count", "type": "Int"},
]
```

---

## 4. Implementation Approach

### Recommended: Incremental Migration

**Phase 1: Current Positions Only** (SAR-nh9a)
- Lower risk, simpler implementation
- Validate pattern before breadcrumbs
- ~8-10 hours effort

**Phase 2: Breadcrumbs/Trails** (SAR-nh9b)
- More complex (async processing, segmentation)
- Build on Phase 1 learnings
- ~8-12 hours effort

### Feature Flag Strategy

```python
class TrackingLayerManager:
    # Feature flag for gradual rollout
    USE_PER_DEVICE_POSITIONS = False  # Phase 1
    USE_PER_DEVICE_TRAILS = False     # Phase 2

    def update_current_positions(self, positions):
        if self.USE_PER_DEVICE_POSITIONS:
            return self._update_positions_per_device(positions)
        return self._update_positions_shared(positions)  # Existing code
```

---

## 5. Key Design Decisions

### 5.1 Layer Naming

**Decision:** Use device NAME (from Traccar) as group/layer name

```python
device_name = position.get('name') or f"Device {device_id}"
# Group: "Tracking / Alpha Team"
# Layers: "Position", "Trail"
```

**Rationale:**
- User-friendly in layer tree
- Matches what coordinators call teams
- device_id stored in custom property for stable identification

### 5.2 Device Identification

**Decision:** Store device_id as custom property, not layer name

```python
layer.setCustomProperty("sartracker:device_id", device_id)
layer.setCustomProperty("sartracker:item_type", "device_position")
```

**Rationale:**
- Layer names can be renamed by users
- device_id is stable across renames
- Matches existing per-item pattern

### 5.3 Device Lifecycle

**New Device Appears:**
1. Create device group under Tracking/
2. Create Position layer in group
3. Create Trail layer in group (if Phase 2)
4. Apply device-specific color

**Device Disappears:**
- Keep layer (preserves user customization)
- Mark as "stale" via custom property after N cycles
- Optional: Hide layer automatically after timeout

### 5.4 Color Consistency

**Decision:** Reuse existing `_get_device_color(device_id)` from BaseLayerManager

```python
def _apply_device_position_style(self, layer, device_id):
    color = self._get_device_color(device_id)  # MD5-based, deterministic
    symbol = QgsMarkerSymbol.createSimple({
        'name': 'circle',
        'color': color.name(),
        'size': '5',
    })
    layer.renderer().setSymbol(symbol)
```

---

## 6. Risk Assessment

| Risk | Severity | Mitigation |
|------|----------|------------|
| Position data loss during transition | CRITICAL | Feature flag for rollback |
| Stale layer refs in async callbacks | HIGH | Use mission_generation pattern |
| Memory exhaustion with many devices | MEDIUM | Reuse existing memory caps |
| Layer creation blocking UI | MEDIUM | Batch operations, defer styling |
| QGIS performance 100+ layers | MEDIUM | Test at scale, lazy loading |
| Device name collisions | LOW | Use device_id for identification |

### Life-Safety Implications

- **Position accuracy is critical** - rescuers depend on device locations
- **Must not lose data** during refresh cycles
- **Must handle offline/reconnect** gracefully
- **Rollback capability required** before production use

---

## 7. Testing Requirements

### Unit Tests
- [ ] Layer creation for new device
- [ ] Position update to existing layer
- [ ] Multiple devices simultaneously
- [ ] Device removal handling
- [ ] Name vs ID fallback

### Integration Tests
- [ ] Provider refresh cycle with per-device layers
- [ ] Plugin reload with existing device layers
- [ ] Mission save/load with device layers
- [ ] Traccar provider end-to-end
- [ ] CSV provider end-to-end

### Performance Tests
- [ ] 10 devices - baseline
- [ ] 20 devices - typical mission
- [ ] 50 devices - large mission
- [ ] 100 devices - stress test

### Manual Tests
- [ ] Layer tree organization correct
- [ ] Device visibility toggles work
- [ ] Zoom to device works
- [ ] Styling persists across refresh
- [ ] User can rename layers

---

## 8. Migration Strategy

### Existing Projects

**Option A: Auto-migrate (Recommended)**
1. Detect shared tracking layers on project load
2. Extract devices from existing features
3. Create per-device layers
4. Copy features to new layers
5. Hide/archive shared layers

**Option B: Manual migration**
- Document migration steps
- User triggers via menu action

### Schema Version

Bump `SAR_LAYER_SCHEMA_VERSION` from 3 to 4 when per-device tracking ships.

---

## 9. Files to Modify

| File | Changes |
|------|---------|
| `layers/schema.py` | Add DEVICE_POSITION_FIELDS, DEVICE_TRAIL_FIELDS, update paths |
| `controllers/per_item_layer_factory.py` | Add ItemType.DEVICE_POSITION, DEVICE_TRAIL |
| `controllers/layer_managers/tracking_manager.py` | Add per-device methods, feature flags |
| `controllers/layers_controller.py` | Update tracking layer retrieval |
| `sartracker.py` | Update initialization if needed |

---

## 10. References

- **Pattern to follow:** `controllers/layer_managers/marker_manager.py` - `_add_clue_per_item()`
- **Factory usage:** `controllers/per_item_layer_factory.py` - `create_item_layer()`
- **Group structure:** `layers/schema.py` - `get_per_item_group_path()`
- **Existing tracking:** `controllers/layer_managers/tracking_manager.py`

---

## Appendix A: Current TrackingLayerManager Methods

### Public API
| Method | Purpose |
|--------|---------|
| `update_current_positions(positions)` | Update all current positions |
| `update_breadcrumbs(positions, time_gap, processed)` | Update all breadcrumbs |
| `delete_device_positions(device_ids)` | Delete positions for devices |
| `delete_device_breadcrumbs(device_ids)` | Delete breadcrumbs for devices |
| `prune_old_breadcrumbs(older_than_hours)` | Delete old breadcrumbs |
| `export_device_track(device_id, format)` | Export device track |

### Key Private Methods
| Method | Purpose |
|--------|---------|
| `_get_or_create_current_layer()` | Ensure shared position layer |
| `_get_or_create_breadcrumbs_layer()` | Ensure shared breadcrumb layer |
| `_apply_current_positions_style(layer)` | Apply categorized renderer |
| `_apply_breadcrumbs_style(layer)` | Apply categorized renderer |
| `_layer_transaction(layer, name, op)` | Safe edit transaction |
| `_start_breadcrumb_task(positions, gap, total)` | Background processing |

---

## Appendix B: Position Data Format

```python
{
    'device_id': str,      # REQUIRED - unique device identifier
    'name': str,           # REQUIRED - device display name
    'lat': float,          # REQUIRED - latitude WGS84
    'lon': float,          # REQUIRED - longitude WGS84
    'ts': str,             # REQUIRED - ISO8601 timestamp
    'altitude': float,     # OPTIONAL
    'speed': float,        # OPTIONAL
    'battery': float,      # OPTIONAL
}
```
