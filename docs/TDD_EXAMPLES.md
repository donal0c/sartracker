# TDD by Example: SAR Tracker Patterns

**Practical examples of test-driven development in SAR Tracker**

This document shows **real examples** from the codebase demonstrating TDD patterns. Use these as templates when writing tests for similar scenarios.

---

## Table of Contents

1. [Example 1: Data Validation (Life-Safety Critical)](#example-1-data-validation)
2. [Example 2: Memory Management (Resource Stability)](#example-2-memory-management)
3. [Example 3: Data Integrity (Backup Operations)](#example-3-data-integrity)
4. [Example 4: Domain Logic (SAR Statistics)](#example-4-domain-logic)
5. [Example 5: State Machine (Mission Lifecycle)](#example-5-state-machine)

---

## Example 1: Data Validation

**Context:** Coordinate validation prevents "Null Island" bug where NaN coordinates default to (0,0).

**Life-Safety Impact:** Wrong coordinates → rescuers search wrong location → delayed rescue.

### TDD Process

#### Step 1: RED - Write Failing Test

```python
# tests/test_regression_bugs.py

def test_nan_latitude_rejected():
    """
    NaN latitude must raise ValueError.

    Regression test for SAR-vlr: NaN coordinates caused Null Island bug.
    """
    with pytest.raises(ValueError, match="NaN"):
        validate_latitude(float('nan'))
```

**Run:** `pytest tests/test_regression_bugs.py::test_nan_latitude_rejected -v`
**Result:** FAIL - `validate_latitude` doesn't exist yet

#### Step 2: GREEN - Implement Validation

```python
# utils/exceptions.py

import math

def validate_latitude(lat: float) -> float:
    """
    Validate latitude value.

    Args:
        lat: Latitude value to validate

    Returns:
        Validated latitude value

    Raises:
        ValueError: If latitude is NaN, infinite, or out of range
    """
    if not isinstance(lat, (int, float)):
        raise ValueError(f"Latitude must be numeric, got {type(lat).__name__}")

    if math.isnan(lat):
        raise ValueError("Latitude cannot be NaN")

    if math.isinf(lat):
        raise ValueError("Latitude cannot be infinite")

    if not -90 <= lat <= 90:
        raise ValueError(f"Latitude {lat} out of range [-90, 90]")

    return lat
```

**Run:** `pytest tests/test_regression_bugs.py::test_nan_latitude_rejected -v`
**Result:** PASS ✓

#### Step 3: REFACTOR - Add More Cases

```python
# tests/test_regression_bugs.py

class TestRegressionSARvlr:
    """Coordinate validation regression tests."""

    def test_nan_latitude_rejected(self):
        """NaN latitude raises ValueError."""
        with pytest.raises(ValueError, match="NaN"):
            validate_latitude(float('nan'))

    def test_nan_longitude_rejected(self):
        """NaN longitude raises ValueError."""
        with pytest.raises(ValueError, match="NaN"):
            validate_longitude(float('nan'))

    def test_positive_infinity_rejected(self):
        """Positive infinity raises ValueError."""
        with pytest.raises(ValueError, match="infinite"):
            validate_latitude(float('inf'))

    def test_negative_infinity_rejected(self):
        """Negative infinity raises ValueError."""
        with pytest.raises(ValueError, match="infinite"):
            validate_longitude(float('-inf'))

    def test_valid_coordinates_pass(self):
        """Valid coordinates pass without raising."""
        lat = validate_latitude(52.1)
        lon = validate_longitude(-9.5)

        assert lat == 52.1
        assert lon == -9.5
```

**Run:** `pytest tests/test_regression_bugs.py::TestRegressionSARvlr -v`
**Result:** All PASS ✓

---

## Example 2: Memory Management

**Context:** LRU+TTL cache prevents unbounded memory growth during long missions.

**Life-Safety Impact:** Memory leaks → plugin crashes → loss of tracking data during mission.

### TDD Process

#### Step 1: RED - Define Behavior

```python
# tests/test_cache.py

def test_evicts_oldest_when_full():
    """Cache evicts LRU entry when at capacity - critical for memory bounds."""
    cache = LRUTTLCache(max_size=3)
    cache.set('a', 1)
    cache.set('b', 2)
    cache.set('c', 3)

    # Cache full, adding d should evict 'a' (oldest)
    cache.set('d', 4)

    assert cache.get('a') is None  # Evicted
    assert cache.get('b') == 2
    assert cache.get('c') == 3
    assert cache.get('d') == 4
    assert len(cache) == 3  # Never exceeds max_size
```

**Run:** Test fails - LRU eviction not implemented

#### Step 2: GREEN - Implement LRU

```python
# utils/cache.py

from collections import OrderedDict

class LRUTTLCache:
    def __init__(self, max_size: int = 50):
        self._max_size = max(1, max_size)
        self._cache = OrderedDict()

    def set(self, key, value):
        if key in self._cache:
            self._cache.move_to_end(key)
        else:
            # Evict LRU if at capacity
            while len(self._cache) >= self._max_size:
                self._cache.popitem(last=False)  # Remove oldest

        self._cache[key] = value
```

**Run:** Test passes ✓

#### Step 3: REFACTOR - Add TTL

```python
# tests/test_cache.py

def test_expired_entry_returns_none():
    """Entry returns None after TTL expires - prevents stale data."""
    cache = LRUTTLCache(max_size=10, ttl_seconds=1)
    cache.set('key1', 'value1')

    time.sleep(1.1)  # Wait for expiration

    assert cache.get('key1') is None
```

Now refactor to add TTL support while keeping LRU tests passing.

---

## Example 3: Data Integrity

**Context:** SQLite backup ensures consistent GeoPackage snapshots during active tracking.

**Life-Safety Impact:** Data corruption → loss of position history → incomplete mission records.

### TDD Process

#### Step 1: RED - Test Snapshot Creation

```python
# tests/test_sqlite_backup.py

def test_snapshot_creates_valid_copy():
    """Snapshot creates a valid, independent database copy."""
    with tempfile.TemporaryDirectory() as tmpdir:
        source = Path(tmpdir) / "source.gpkg"
        dest = Path(tmpdir) / "dest.gpkg"

        # Create minimal valid GeoPackage
        conn = sqlite3.connect(str(source))
        conn.execute("CREATE TABLE test_data (id INTEGER, name TEXT)")
        conn.execute("INSERT INTO test_data VALUES (1, 'mission_alpha')")
        conn.commit()
        conn.close()

        # Create snapshot
        result = create_safe_snapshot(source, dest)

        assert result is True
        assert dest.exists()

        # Verify snapshot is valid and independent
        snap_conn = sqlite3.connect(str(dest))
        row = snap_conn.execute("SELECT * FROM test_data").fetchone()
        snap_conn.close()

        assert row == (1, 'mission_alpha')
```

**Run:** Test fails - function doesn't exist

#### Step 2: GREEN - Implement Backup

```python
# utils/mission_storage.py

def create_safe_snapshot(source_path: Path, dest_path: Path) -> bool:
    """
    Create a consistent snapshot of a GeoPackage database.

    Uses VACUUM INTO (SQLite 3.27+) or connection.backup() fallback.
    """
    if not source_path.exists():
        raise FileNotFoundError(f"Source not found: {source_path}")

    if dest_path.exists():
        raise FileExistsError(f"Destination exists: {dest_path}")

    dest_path.parent.mkdir(parents=True, exist_ok=True)

    if _supports_vacuum_into():
        return _backup_with_vacuum_into(source_path, dest_path)
    else:
        return _backup_with_connection_api(source_path, dest_path)
```

**Run:** Test passes ✓

#### Step 3: REFACTOR - Add Edge Cases

```python
def test_snapshot_source_not_found_raises():
    """Missing source file raises FileNotFoundError."""
    with tempfile.TemporaryDirectory() as tmpdir:
        source = Path(tmpdir) / "nonexistent.gpkg"
        dest = Path(tmpdir) / "dest.gpkg"

        with pytest.raises(FileNotFoundError):
            create_safe_snapshot(source, dest)

def test_snapshot_dest_exists_raises():
    """Existing destination file raises FileExistsError."""
    # ... test implementation
```

---

## Example 4: Domain Logic

**Context:** LPB (Lost Person Behavior) statistics determine search area sizes.

**Life-Safety Impact:** Wrong statistics → wrong search areas → inefficient rescue operations.

### TDD Process

#### Step 1: RED - Test Domain Rules

```python
# tests/test_lpb_statistics.py

def test_hiker_distances_are_correct():
    """Verify hiker statistics match Koester data - critical for search area sizing."""
    result = LPBStatistics.get_distances('hiker')

    # These values directly affect search ring generation
    assert result[25] == 800    # 25% found within 800m
    assert result[50] == 2000   # 50% found within 2km
    assert result[75] == 4000   # 75% found within 4km
    assert result[95] == 8000   # 95% found within 8km
```

**Run:** Test fails - data doesn't match

#### Step 2: GREEN - Implement Domain Data

```python
# utils/lpb_statistics.py

class LPBStatistics:
    """Lost Person Behavior statistical data for search planning."""

    STATISTICS = {
        'hiker': {
            'name': 'Hiker',
            25: 800,    # Meters
            50: 2000,
            75: 4000,
            95: 8000,
        },
        # ... other categories
    }

    @classmethod
    def get_distances(cls, category_key, percentiles=None):
        if percentiles is None:
            percentiles = [25, 50, 75, 95]

        if category_key not in cls.STATISTICS:
            return None

        stats = cls.STATISTICS[category_key]
        return {p: stats[p] for p in percentiles if p in stats}
```

**Run:** Test passes ✓

#### Step 3: REFACTOR - Add Data Integrity Tests

```python
def test_distances_are_monotonically_increasing():
    """Higher percentiles must have larger distances."""
    for key in ['hiker', 'dementia', 'child_1_3']:
        info = LPBStatistics.get_category_info(key)

        assert info[25] <= info[50], f"{key}: 25th > 50th percentile"
        assert info[50] <= info[75], f"{key}: 50th > 75th percentile"
        assert info[75] <= info[95], f"{key}: 75th > 95th percentile"
```

This catches data entry errors automatically.

---

## Example 5: State Machine

**Context:** Mission state transitions must follow strict rules.

**Life-Safety Impact:** Invalid state transitions → incorrect mission timing → inaccurate operational records.

### TDD Process

#### Step 1: RED - Test Valid Transitions

```python
# tests/test_mission_timing.py

class TestMissionStateTransitions:
    """Tests for mission state machine."""

    def test_idle_can_become_active(self):
        """Mission can start from idle state."""
        # Arrange
        timing = {'state': 'idle'}

        # Act
        result = transition_state(timing, 'active')

        # Assert
        assert result['state'] == 'active'
        assert result['start_time'] is not None

    def test_idle_cannot_pause(self):
        """Pausing idle mission raises InvalidTransitionError."""
        timing = {'state': 'idle'}

        with pytest.raises(InvalidTransitionError):
            transition_state(timing, 'paused')
```

**Run:** Tests fail - state machine doesn't exist

#### Step 2: GREEN - Implement State Machine

```python
# controllers/mission_lifecycle.py

class InvalidTransitionError(Exception):
    """Raised when state transition is invalid."""
    pass

VALID_TRANSITIONS = {
    'idle': ['active'],
    'active': ['paused', 'finished'],
    'paused': ['active', 'finished'],
    'finished': ['idle'],
}

def transition_state(timing: dict, new_state: str) -> dict:
    """
    Transition mission to new state.

    Args:
        timing: Current timing dict with 'state' key
        new_state: Target state

    Returns:
        Updated timing dict

    Raises:
        InvalidTransitionError: If transition not allowed
    """
    current_state = timing.get('state', 'idle')

    if new_state not in VALID_TRANSITIONS.get(current_state, []):
        raise InvalidTransitionError(
            f"Cannot transition from {current_state} to {new_state}"
        )

    timing['state'] = new_state

    if new_state == 'active' and 'start_time' not in timing:
        timing['start_time'] = datetime.now(timezone.utc)

    return timing
```

**Run:** Tests pass ✓

#### Step 3: REFACTOR - Test All Transitions

```python
@pytest.mark.parametrize("from_state,to_state,should_succeed", [
    ('idle', 'active', True),
    ('idle', 'paused', False),
    ('idle', 'finished', False),
    ('active', 'paused', True),
    ('active', 'finished', True),
    ('active', 'idle', False),
    ('paused', 'active', True),
    ('paused', 'finished', True),
    ('finished', 'idle', True),
])
def test_state_transitions(from_state, to_state, should_succeed):
    """Test all state transitions systematically."""
    timing = {'state': from_state}

    if should_succeed:
        result = transition_state(timing, to_state)
        assert result['state'] == to_state
    else:
        with pytest.raises(InvalidTransitionError):
            transition_state(timing, to_state)
```

---

## Common TDD Scenarios

### Scenario 1: "I don't know what to test"

**Answer:** Start with the happy path, then add edge cases.

```python
# 1. Happy path
def test_cache_get_returns_stored_value():
    cache = Cache()
    cache.set('key', 'value')
    assert cache.get('key') == 'value'

# 2. Missing key
def test_cache_get_missing_returns_none():
    cache = Cache()
    assert cache.get('nonexistent') is None

# 3. Capacity limit
def test_cache_respects_max_size():
    cache = Cache(max_size=2)
    cache.set('a', 1)
    cache.set('b', 2)
    cache.set('c', 3)
    assert len(cache) <= 2
```

### Scenario 2: "My test is too complex"

**Answer:** Break it into smaller tests.

```python
# BAD - One giant test
def test_entire_mission_workflow():
    mission = start_mission()
    add_markers()
    start_tracking()
    pause_mission()
    resume_mission()
    finish_mission()
    # ... 50 more lines

# GOOD - Focused tests
def test_mission_start_creates_gpkg():
    mission = start_mission()
    assert mission.gpkg_path.exists()

def test_mission_pause_stops_polling():
    mission = create_active_mission()
    mission.pause()
    assert mission.polling_active is False
```

### Scenario 3: "I need to refactor but have no tests"

**Answer:** Write tests for current behavior FIRST, then refactor.

```python
# Step 1: Characterization tests (document current behavior)
def test_current_behavior_normal_input():
    result = legacy_function('input')
    assert result == 'expected_output'  # Whatever it currently does

def test_current_behavior_empty_input():
    result = legacy_function('')
    assert result == ''  # Document current edge case handling

# Step 2: Now refactor safely - tests will catch regressions
```

---

## Anti-Pattern Examples

### ❌ Don't: Test Private Implementation

```python
# BAD
def test_cache_uses_ordered_dict():
    cache = Cache()
    assert isinstance(cache._cache, OrderedDict)
```

**Why bad:** Test breaks when refactoring internals, even if behavior unchanged.

### ✅ Do: Test Public Behavior

```python
# GOOD
def test_cache_evicts_least_recently_used():
    cache = Cache(max_size=2)
    cache.set('a', 1)
    cache.set('b', 2)
    cache.get('a')  # Make 'a' recently used
    cache.set('c', 3)  # Should evict 'b'

    assert cache.get('a') == 1
    assert cache.get('b') is None  # Evicted
```

**Why good:** Tests observable behavior. Implementation can change freely.

---

## Quick Reference

### Test Anatomy

```python
def test_feature_scenario_result():
    """One-line description in present tense."""
    # Arrange - Set up test conditions
    input_data = create_test_data()

    # Act - Perform the operation
    result = function_under_test(input_data)

    # Assert - Verify expected outcome
    assert result == expected_value
```

### Running Tests

```bash
# Single test (fastest feedback)
pytest tests/test_file.py::test_function -v

# File
pytest tests/test_file.py -v

# Suite
pytest tests/ -v

# With coverage
pytest tests/ --cov=. --cov-report=html
```

### When Stuck

1. Write the simplest test you can think of
2. Make it pass
3. Write a slightly more complex test
4. Repeat

**Remember:** TDD is a skill. It feels awkward at first but becomes natural with practice.

---

**See Also:**
- `docs/TDD_WORKFLOW.md` - Complete TDD guide
- `CLAUDE.md` - Project workflows
- `tests/` - More real examples

**Document Version:** 1.0
**Last Updated:** 2026-01-01
