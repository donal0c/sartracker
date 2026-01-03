# Incremental Breadcrumb Fetching - Technical Specification

**Issue:** SAR-IBC (Incremental Breadcrumb Collection)
**Status:** Planning
**Created:** 2026-01-03
**Author:** Claude Code

---

## Problem Statement

Currently, every refresh cycle (default 30 seconds) fetches ALL breadcrumb positions from mission start to now. For a 12-hour mission with 15 devices updating every 30 seconds, this means:

- ~21,600 positions fetched every 30 seconds
- ~99% of data is redundant (already fetched previously)
- Wastes bandwidth, server resources, and battery
- Particularly problematic in remote SAR areas with poor connectivity

## Solution Overview

Implement **incremental breadcrumb fetching** that only retrieves positions newer than the last successful fetch, per device.

### Expected Improvement

| Mission Duration | Current (per refresh) | Incremental (per refresh) | Reduction |
|------------------|----------------------|---------------------------|-----------|
| 1 hour | ~1,800 positions | ~30 positions | 98% |
| 6 hours | ~10,800 positions | ~30 positions | 99.7% |
| 12 hours | ~21,600 positions | ~30 positions | 99.9% |

---

## Architecture

### Current Flow (Inefficient)
```
Every 30s:
  Provider.get_breadcrumbs(since=mission_start)
    → Fetch ALL positions from Traccar
    → Preprocess into segments
    → REPLACE all trail features
```

### New Flow (Incremental)
```
Every 30s:
  Provider.get_breadcrumbs_incremental(last_timestamps={device_id: timestamp})
    → Fetch only NEW positions per device
    → Accumulator.add(new_positions)
    → Preprocess accumulated positions into segments
    → Update trail features
```

---

## Component Changes

### 1. State Tracking (ProviderController)

**New State:**
```python
class ProviderController:
    # Per-device tracking of last successfully fetched breadcrumb timestamp
    _breadcrumb_timestamps: Dict[str, datetime]  # {device_id: last_fetch_ts}

    # Accumulated breadcrumb positions (session-scoped)
    _breadcrumb_accumulator: Dict[str, List[Dict]]  # {device_id: [positions]}
```

**Reset Triggers:**
- Mission start (new mission) → Clear all
- Provider change → Clear all
- Plugin reload → Clear all (session-based)
- Device removed → Clear that device only

### 2. Incremental Fetching (TraccarHttpProvider)

**Modified Method Signature:**
```python
def get_breadcrumbs(
    self,
    since_iso: Optional[str] = None,  # Mission start (for new devices)
    device_timestamps: Optional[Dict[str, str]] = None,  # Per-device last fetch
    mission_id: Optional[int] = None,
    session=None,
    cancel_check: Optional[Callable[[], bool]] = None,
) -> List[Dict]:
```

**Logic:**
1. For each device:
   - If device_id in device_timestamps: fetch from that timestamp
   - Else: fetch from since_iso (mission start) - new device
2. Merge all results
3. Return only NEW positions

### 3. Position Accumulator (New Component)

**Location:** `utils/breadcrumb_accumulator.py`

```python
class BreadcrumbAccumulator:
    """Accumulates breadcrumb positions across refresh cycles."""

    def __init__(self, max_positions: int = 100_000):
        self._positions: Dict[str, List[Dict]] = defaultdict(list)
        self._seen_keys: Set[Tuple[str, str]] = set()  # (device_id, timestamp)
        self._max_positions = max_positions

    def add(self, positions: List[Dict]) -> int:
        """Add new positions, deduplicating. Returns count added."""

    def get_all(self) -> List[Dict]:
        """Get all accumulated positions for preprocessing."""

    def get_device_positions(self, device_id: str) -> List[Dict]:
        """Get positions for a specific device."""

    def get_latest_timestamps(self) -> Dict[str, str]:
        """Get latest timestamp per device for next incremental fetch."""

    def clear(self):
        """Clear all accumulated data (mission reset)."""

    def clear_device(self, device_id: str):
        """Clear data for a specific device."""
```

### 4. Integration Points

**ProviderController._on_refresh_task_complete():**
```python
# After receiving new breadcrumbs:
new_count = self._breadcrumb_accumulator.add(new_breadcrumbs)
all_breadcrumbs = self._breadcrumb_accumulator.get_all()
self._breadcrumb_timestamps = self._breadcrumb_accumulator.get_latest_timestamps()

# Send accumulated positions for preprocessing
self._layers_controller.update_breadcrumbs(all_breadcrumbs, ...)
```

---

## Edge Cases & Handling

### 1. Mission Start
- **Trigger:** Mission state changes from IDLE/FINISHED to ACTIVE
- **Action:** `_breadcrumb_accumulator.clear()`, `_breadcrumb_timestamps.clear()`
- **Next fetch:** Full fetch from new mission start time

### 2. Mission Resume
- **Trigger:** Mission state changes from PAUSED to ACTIVE (same mission)
- **Action:** NO reset - continue accumulating
- **Next fetch:** Incremental from last timestamps

### 3. New Device Joins Mid-Mission
- **Detection:** Device in current fetch not in `_breadcrumb_timestamps`
- **Action:** Fetch from mission start for that device only
- **Subsequent fetches:** Incremental for that device

### 4. Fetch Failure for Specific Device
- **Detection:** Device in `breadcrumb_failures` list
- **Action:** Do NOT update that device's timestamp
- **Next fetch:** Retry from previous timestamp (automatic gap recovery)

### 5. Complete Fetch Failure
- **Detection:** All devices failed or network error
- **Action:** Use cached data, do NOT clear accumulator
- **Next fetch:** Retry incremental

### 6. Plugin Reload
- **Action:** Session-based state is lost
- **Next fetch:** Full fetch (rebuilds accumulator from scratch)
- **Future enhancement:** Could persist timestamps to QSettings

### 7. Device Goes Offline (Filtered by FR-6)
- **Action:** Stop fetching for that device, but KEEP accumulated data
- **When device returns:** Resume incremental fetching

---

## Deduplication Strategy

**Key:** `(device_id, timestamp)` tuple

Positions with the same device_id and timestamp are considered duplicates. This handles:
- Boundary overlap when fetching (from <= timestamp <= to)
- Traccar API returning duplicate entries
- Retry scenarios

**Implementation:**
```python
def _make_key(self, pos: Dict) -> Tuple[str, str]:
    return (pos.get('device_id', ''), pos.get('ts', ''))

def add(self, positions: List[Dict]) -> int:
    added = 0
    for pos in positions:
        key = self._make_key(pos)
        if key not in self._seen_keys:
            self._seen_keys.add(key)
            self._positions[pos['device_id']].append(pos)
            added += 1
    return added
```

---

## Memory Management

**Limits:**
- Max 100,000 positions total (existing limit from tasks.py)
- If exceeded: drop oldest positions per device (FIFO)
- Log warning when approaching limit

**Estimation:**
- Each position ~500 bytes in memory (dict with coordinates, timestamp, metadata)
- 100,000 positions ≈ 50MB worst case
- Typical 24-hour mission with 15 devices: ~43,200 positions ≈ 22MB

---

## Testing Strategy

### Unit Tests
1. `test_accumulator_deduplication` - Duplicate positions rejected
2. `test_accumulator_memory_limit` - Oldest dropped when limit exceeded
3. `test_accumulator_clear_on_mission_start` - Reset works correctly
4. `test_incremental_timestamps` - Latest timestamps extracted correctly

### Integration Tests
1. `test_incremental_fetch_reduces_data` - Subsequent fetches smaller
2. `test_new_device_full_fetch` - New devices get full history
3. `test_failure_recovery` - Failed device retried correctly
4. `test_mission_restart_clears_accumulator` - Clean slate on new mission

### Performance Tests
1. Measure data transfer reduction over simulated mission
2. Memory usage over 24-hour mission
3. CPU overhead of deduplication

---

## Rollout Strategy

**Phase 1:** Infrastructure (no behavior change)
- Add accumulator class
- Add state tracking fields
- Add tests

**Phase 2:** Provider changes
- Modify get_breadcrumbs() to accept per-device timestamps
- Implement incremental fetch logic
- Add fallback to full fetch

**Phase 3:** Integration
- Wire accumulator into refresh flow
- Handle mission lifecycle events
- Update logging/diagnostics

**Phase 4:** Testing & Validation
- Run against real Traccar server
- Measure actual bandwidth reduction
- Field testing with Kerry Mountain Rescue team

---

## Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Traccar API doesn't support incremental | Low | High | Verified: `from` parameter works |
| Memory growth in long missions | Medium | Medium | 100K limit, FIFO eviction |
| Deduplication key collisions | Low | Low | (device_id, timestamp) is unique |
| State corruption on crash | Low | Low | Session-based, full fetch recovers |
| Complexity introduces bugs | Medium | Medium | Phased rollout, extensive testing |

---

## Success Metrics

1. **Bandwidth reduction:** >95% reduction in breadcrumb data transfer after initial fetch
2. **Memory stability:** Memory usage stays under 50MB for 24-hour mission
3. **No data loss:** All breadcrumb positions captured (verified against full fetch)
4. **No regressions:** Existing trail visualization unchanged

---

## Files to Modify

| File | Changes |
|------|---------|
| `utils/breadcrumb_accumulator.py` | NEW - Accumulator class |
| `providers/traccar_http.py` | Modify `get_breadcrumbs()` signature and logic |
| `providers/tasks.py` | Pass device timestamps to provider |
| `controllers/provider_controller.py` | Add state tracking, wire accumulator |
| `tests/test_breadcrumb_accumulator.py` | NEW - Unit tests |
| `tests/test_incremental_breadcrumbs.py` | NEW - Integration tests |
