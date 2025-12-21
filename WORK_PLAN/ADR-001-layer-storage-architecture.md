# ADR-001: Layer Storage Architecture for 100+ Items

**Status:** Implemented ✅
**Decision Date:** 2025-12-20
**Implementation Date:** 2025-12-21
**Classification:** LIFE-SAFETY CRITICAL
**Deciders:** Kerry Mountain Rescue Team
**Related Issues:** SAR-yt3, SAR-1d3, SAR-mlw, SAR-qyh
**Implementation Verified:** All Phase 3/4 layer scalability work complete (SAR-bko, SAR-nh9, SAR-33p, SAR-nj0, SAR-0uy, SAR-ddx)

---

## Context and Problem Statement

SAR Tracker needs to support FR-2 (one layer per clue/marker/ring/line/search area) and FR-3 (Map Tools grouping) for missions that may accumulate 100-150+ individual map items over an 8+ hour operation.

The current architecture uses shared GeoPackage tables (e.g., one `markers` table for all markers). This prevents:
- Individual layer visibility toggle per item
- Per-item rename without affecting other items
- Native QGIS layer properties (style, labeling) per item
- Intuitive layer tree organization matching rescue coordinator mental model

**Key Question:** How do we store and represent 100+ individual map items while maintaining:
- Responsive UI (no stalls during pan/zoom/scroll)
- Fast mission open/save times
- Data integrity under crash/power loss
- Qt5 and Qt6 compatibility (QGIS 3.28-3.44+)

---

## Decision Drivers

1. **Team Mental Model** - Coordinators think of each marker/area as an independent object
2. **Native QGIS Behavior** - Per-layer properties (style, labels, visibility) should "just work"
3. **Performance at Scale** - 150+ layers must remain usable without UI freezes
4. **Data Safety** - Crash resilience, backup/restore, migration reversibility
5. **Implementation Complexity** - Build on existing patterns, minimize risk

---

## Considered Options

### Option A: True Per-Item GeoPackage Tables

Each map item (marker, search area, etc.) stored in its own GeoPackage table.

```
mission.gpkg
├── marker_footprint_at_summit (table)
├── marker_backpack_found (table)
├── hazard_cliff_edge (table)
├── ring_search_radius_1 (table)
└── ... (100+ tables)
```

**Pros:**
- True layer independence
- QGIS layer properties work naturally
- Easy show/hide/reorder
- Matches team mental model
- Simple implementation (one table = one layer)

**Cons:**
- More GeoPackage schema entries
- Slightly higher connection overhead
- More complex mission archiving
- Migration from current structure required

### Option B: Shared Tables with Filtered Layers

Single table per type with discriminator columns. QGIS layers use `setSubsetString()` filters.

```
mission.gpkg
├── markers (single table with marker_id column)
├── drawings (single table with drawing_id column)
└── QgsVectorLayer per item with SQL filter
```

**Pros:**
- Fewer GeoPackage tables
- Single spatial index per type
- Better bulk write performance
- Simpler schema

**Cons:**
- Layer rename doesn't update underlying data (confusing)
- More complex implementation (filter management)
- Filter overhead on every query
- Less intuitive for debugging
- Filtering bugs could expose wrong data

---

## Decision Outcome

**Chosen Option: Option A - True Per-Item GeoPackage Tables with Lazy Loading**

This approach:
1. Aligns with how rescue coordinators think about map items
2. Leverages native QGIS layer behavior without workarounds
3. Achieves acceptable performance through lazy loading and batch operations
4. Provides clearer debugging (one table = one item)

### Technical Validation

Research confirmed QGIS 3.28+ handles 100+ layers effectively:
- Legend performance bottleneck fixed in QGIS 3.16 (PR #38891)
- GeoPackage/SQLite handles 100+ tables without issues
- Performance targets achievable with documented patterns

---

## Acceptance Thresholds

| Metric | Threshold | Failure Action |
|--------|-----------|----------------|
| Mission load (150 layers) | < 10 seconds | Revisit lazy loading strategy |
| Single marker add | < 200ms | Profile and optimize |
| Batch add (10 markers) | < 500ms | Review signal blocking |
| Group visibility toggle (50 layers) | < 500ms | Add debouncing |
| Layer tree scroll | 60fps smooth | Enable uniformRowHeights |
| Memory (150 layers, 8hr) | < 500MB | Implement layer release |

**Verification:** Phase 2 prototyping (SAR-rqc, SAR-eqb) will benchmark these metrics. If thresholds are not met, reassess before proceeding to Phase 3.

---

## Migration Strategy

### From Current Missions (v1 shared tables)

1. **Detection** - Check for `markers` table vs `marker_*` tables
2. **Backup** - Create timestamped copy before any modification
3. **User Prompt** - Explicit confirmation required, explain changes
4. **Extract** - Read all features from shared tables
5. **Create** - Create per-item tables with proper schema
6. **Migrate** - Copy features to individual tables
7. **Verify** - Assert feature counts match
8. **Archive** - Rename old tables (e.g., `_archive_markers_20250120`)

### Rollback

- Archived tables retained for 30 days or until user explicit removal
- Rollback = rename archive tables back to original names
- No data loss possible if rollback needed

### New Missions

- New missions created directly with per-item table structure
- No migration needed

---

## Implementation Patterns (Required)

### 1. GeoPackage WAL Mode

```python
def enable_wal_mode(gpkg_path):
    """Enable WAL mode for better concurrent access and crash recovery."""
    conn = sqlite3.connect(gpkg_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.close()
```

**Required for:** All mission GeoPackage files on create/open.

**Caveat:** Checkpoint before backup: `PRAGMA wal_checkpoint(TRUNCATE)`

### 2. Batch Layer Operations

```python
root = QgsProject.instance().layerTreeRoot()
root.blockSignals(True)
try:
    QgsProject.instance().addMapLayers(layer_list, addToLegend=False)
    for layer in layer_list:
        target_group.addLayer(layer)
finally:
    root.blockSignals(False)
    root.updateVisibility()
```

**Required for:** Any operation adding/removing 3+ layers.

### 3. Layer Tree Performance

```python
tree_view.setUniformRowHeights(True)  # CRITICAL: 10-100x scroll improvement
tree_view.setAnimated(False)          # During bulk operations
```

**Required for:** Any custom tree views showing layers.

### 4. Lazy Loading

Layers loaded on-demand, not all at mission open:
- Visible layers loaded immediately
- Collapsed group contents loaded on expand
- Cache invalidated on layer removal

### 5. Update Debouncing

Coalesce rapid updates (e.g., dragging multiple layers) into single refresh:
- 100ms debounce window for layer tree updates
- Prevents UI stutter during bulk operations

---

## Consequences

### Positive

- **Native UX** - Per-layer properties work without custom code
- **Mental Model Alignment** - One layer = one item = one table
- **Debuggability** - Direct table inspection in SQLite
- **Future-Proof** - Standard QGIS patterns, no filter workarounds

### Negative

- **Schema Overhead** - 100+ tables means 400+ schema entries (with spatial indexes)
- **Migration Required** - Existing missions need one-time migration
- **Learning Curve** - Team needs to understand lazy loading behavior

### Neutral

- **Memory** - Similar to Option B with proper layer release
- **Query Performance** - Per-table queries vs filtered queries roughly equivalent

---

## Related Documents

- Research: `WORK_PLAN/REFERENCE/phase2_layer_architecture_research.md`
- Feature Requests: `WORK_PLAN/REFERENCE/FEATURE_REQUESTS_2025.md`
- Phase 3 Epic: SAR-1k6 (Layer Scalability Foundation)
- Phase 4 Epic: SAR-1d3 (Deliver FR-2 + FR-3)

---

## Review Checklist

- [x] Research completed and documented
- [x] Both options analyzed with pros/cons
- [x] Acceptance thresholds defined
- [x] Migration strategy documented
- [x] Rollback approach defined
- [x] Required implementation patterns specified
- [x] Consequences acknowledged

**This ADR is ready for Phase 3 implementation to begin.**
