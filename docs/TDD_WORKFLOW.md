# Test-Driven Development Workflow for SAR Tracker

**Classification:** LIFE-SAFETY CRITICAL SYSTEM
**Status:** MANDATORY for all new development (2026-01-01)

---

## Overview

SAR Tracker has adopted Test-Driven Development (TDD) as the **mandatory** approach for all new features, bug fixes, and refactoring. This document provides practical guidance for contributors (human and AI).

### Why TDD for Life-Safety Critical Systems

**Lives depend on this code.** TDD provides:

1. **Safety Net** - Tests catch regressions before they reach rescuers in the field
2. **Living Documentation** - Tests document expected behavior better than comments
3. **Design Feedback** - Hard-to-test code is usually poorly designed code
4. **Confidence** - Make changes knowing tests will catch breakage
5. **Reduced Debugging** - Find bugs when writing code, not during missions

---

## The TDD Cycle

```
┌─────────────────────────────────────────────┐
│                                             │
│  1. RED    → Write a failing test          │
│  2. GREEN  → Write minimal code to pass    │
│  3. REFACTOR → Clean up while tests pass   │
│                                             │
└─────────────────────────────────────────────┘
```

### 1. RED - Write a Failing Test

**Before writing any production code**, write a test that:
- Defines the expected behavior clearly
- Fails for the right reason (feature not implemented yet)
- Is focused on ONE specific behavior

**Example:**
```python
def test_validate_latitude_rejects_nan():
    """NaN latitude must raise ValueError to prevent Null Island."""
    with pytest.raises(ValueError, match="NaN"):
        validate_latitude(float('nan'))
```

Run the test: `pytest tests/test_validation.py::test_validate_latitude_rejects_nan -v`

**Expected:** Test FAILS (feature doesn't exist yet)

### 2. GREEN - Write Minimal Code to Pass

Write the **simplest code** that makes the test pass. Don't solve future problems.

**Example:**
```python
def validate_latitude(lat: float) -> float:
    """Validate latitude is numeric and in valid range."""
    if math.isnan(lat):
        raise ValueError("Latitude cannot be NaN")
    if not -90 <= lat <= 90:
        raise ValueError(f"Latitude {lat} out of range [-90, 90]")
    return lat
```

Run the test: `pytest tests/test_validation.py::test_validate_latitude_rejects_nan -v`

**Expected:** Test PASSES

### 3. REFACTOR - Clean Up While Green

Improve code quality while keeping tests green:
- Extract helper functions
- Remove duplication
- Clarify variable names
- Add docstrings

**Key Rule:** Tests must stay GREEN throughout refactoring.

---

## When TDD is MANDATORY

### 1. Bug Fixes

**Process:**
1. Write a test that reproduces the bug (it MUST fail)
2. Fix the bug
3. Verify the test passes
4. Test becomes permanent regression test

**Example:**
```python
def test_regression_BUG_081_null_island_rejected():
    """
    Regression test for BUG-081: NaN coordinates caused 'Null Island' bug.

    Root cause: validate_latitude/longitude didn't check for NaN.
    Fixed: 2025-12-15 in utils/exceptions.py
    """
    with pytest.raises(ValueError):
        validate_latitude(float('nan'))
```

### 2. New Features

**Process:**
1. Write acceptance tests defining feature behavior (RED)
2. Implement feature incrementally, one test at a time (GREEN)
3. Refactor when complete (REFACTOR)

**Example - Adding LRU Cache:**
```python
# Test 1: Basic get/set
def test_cache_set_and_get():
    cache = LRUTTLCache(max_size=10)
    cache.set('key', 'value')
    assert cache.get('key') == 'value'

# Test 2: LRU eviction
def test_cache_evicts_lru_when_full():
    cache = LRUTTLCache(max_size=3)
    cache.set('a', 1)
    cache.set('b', 2)
    cache.set('c', 3)
    cache.set('d', 4)  # Should evict 'a'

    assert cache.get('a') is None  # Evicted
    assert cache.get('d') == 4
```

### 3. Refactoring

**Process:**
1. **Before refactoring:** Ensure tests exist and pass
2. Refactor code
3. **After refactoring:** Verify tests still pass

**Rule:** If no tests exist for code being refactored, write them FIRST.

---

## When TDD Can Be Skipped

TDD is **optional** for:

1. **Pure documentation changes** (README, CLAUDE.md updates)
2. **Configuration-only changes** (settings, metadata)
3. **Exploratory spikes** (throwaway prototypes)
   - BUT: Delete spike code and rewrite with TDD before merging

TDD is **always required** for:
- Coordinate handling
- Mission state management
- Background task lifecycle
- Data persistence
- Input validation

---

## Test Organization

### Test File Structure

```python
# tests/test_module_name.py
"""
Tests for module_name.py

Value: Brief explanation of why these tests matter
"""

import pytest
from module_name import function_to_test


class TestFeatureName:
    """Tests for specific feature or class."""

    def test_happy_path_behavior(self):
        """Test description in present tense."""
        # Arrange
        input_data = prepare_test_data()

        # Act
        result = function_to_test(input_data)

        # Assert
        assert result == expected_value

    def test_edge_case_handles_empty_input(self):
        """Empty input returns default value."""
        result = function_to_test([])
        assert result == default_value

    def test_error_case_invalid_input_raises(self):
        """Invalid input raises ValueError with clear message."""
        with pytest.raises(ValueError, match="invalid"):
            function_to_test(invalid_input)
```

### Test Naming Convention

**Format:** `test_<unit>_<scenario>_<expected_result>`

**Examples:**
```python
# Good
def test_validate_latitude_with_nan_raises_value_error():
def test_cache_evicts_oldest_when_full():
def test_mission_start_from_idle_succeeds():

# Bad (too vague)
def test_validation():
def test_cache():
def test_mission():
```

---

## Running Tests

### Quick Feedback Loop (TDD)

Run tests continuously while developing:

```bash
# Single test (fastest)
pytest tests/test_cache.py::TestLRUEviction::test_evicts_oldest_when_full -v

# Single test file
pytest tests/test_cache.py -v

# Watch mode (re-run on file changes)
ptw tests/test_cache.py -- -v
```

**Target:** <1s for single test, <10s for file

### Full Unit Suite

Before committing:

```bash
# All unit tests (no QGIS required)
pytest tests/test_lpb_statistics.py tests/test_cache.py \
       tests/test_sqlite_backup.py tests/test_regression_bugs.py \
       tests/test_path_security.py tests/test_mission_timing.py -v

# Expected: 93 passed in ~3.6s
```

### Integration Tests (requires QGIS)

```bash
# All tests including QGIS-dependent
pytest tests/ -v

# Skip slow tests
pytest tests/ -m "not slow" -v
```

---

## Common Patterns

### Pattern 1: Testing Validation Functions

```python
class TestValidateCoordinates:
    """Tests for coordinate validation - LIFE-SAFETY CRITICAL."""

    def test_valid_coordinates_pass(self):
        """Valid lat/lon pass without raising."""
        lat = validate_latitude(52.1)
        lon = validate_longitude(-9.5)

        assert lat == 52.1
        assert lon == -9.5

    def test_nan_latitude_rejected(self):
        """NaN latitude raises ValueError."""
        with pytest.raises(ValueError, match="NaN"):
            validate_latitude(float('nan'))

    def test_out_of_range_latitude_rejected(self):
        """Latitude outside [-90, 90] raises ValueError."""
        with pytest.raises(ValueError, match="out of range"):
            validate_latitude(91.0)

    @pytest.mark.parametrize("invalid_lat", [
        float('nan'),
        float('inf'),
        float('-inf'),
        91.0,
        -91.0,
    ])
    def test_invalid_latitudes_rejected(self, invalid_lat):
        """Parametrized test for multiple invalid values."""
        with pytest.raises(ValueError):
            validate_latitude(invalid_lat)
```

### Pattern 2: Testing State Machines

```python
class TestMissionStateMachine:
    """Tests for mission state transitions."""

    def test_idle_can_transition_to_active(self):
        """Mission can start from idle state."""
        mission = MissionController()
        mission.set_state('idle')

        mission.start()

        assert mission.state == 'active'

    def test_idle_cannot_pause(self):
        """Pausing idle mission raises InvalidTransition."""
        mission = MissionController()
        mission.set_state('idle')

        with pytest.raises(InvalidTransitionError):
            mission.pause()
```

### Pattern 3: Testing with Fixtures

```python
@pytest.fixture
def sample_cache():
    """Provide pre-populated cache for tests."""
    cache = LRUTTLCache(max_size=10)
    cache.set('item1', 'value1')
    cache.set('item2', 'value2')
    return cache

def test_cache_delete_removes_entry(sample_cache):
    """Delete removes entry from cache."""
    result = sample_cache.delete('item1')

    assert result is True
    assert sample_cache.get('item1') is None
```

### Pattern 4: Testing Exceptions

```python
def test_missing_file_raises_file_not_found():
    """Opening nonexistent file raises FileNotFoundError."""
    with pytest.raises(FileNotFoundError) as exc_info:
        open_mission('/nonexistent/path.gpkg')

    # Optionally check error message
    assert 'not found' in str(exc_info.value).lower()
```

---

## TDD Anti-Patterns (Avoid These)

### ❌ Anti-Pattern 1: Writing Tests After Code

```python
# BAD: Code written first, test added later
def calculate_distance(lat1, lon1, lat2, lon2):
    # Complex implementation...
    return distance

# Test written afterwards to "check coverage"
def test_calculate_distance():
    assert calculate_distance(0, 0, 0, 1) > 0  # Weak test
```

**Problem:** Test just confirms what code already does, doesn't define requirements.

### ❌ Anti-Pattern 2: Testing Implementation, Not Behavior

```python
# BAD: Testing internal details
def test_cache_uses_ordered_dict():
    cache = LRUTTLCache()
    assert isinstance(cache._cache, OrderedDict)  # Testing internals
```

**Problem:** Test breaks when refactoring internals, even if behavior unchanged.

**GOOD:** Test observable behavior instead:
```python
def test_cache_evicts_least_recently_used():
    cache = LRUTTLCache(max_size=2)
    cache.set('a', 1)
    cache.set('b', 2)
    cache.get('a')  # Make 'a' most recent
    cache.set('c', 3)  # Should evict 'b', not 'a'

    assert cache.get('a') == 1
    assert cache.get('b') is None
```

### ❌ Anti-Pattern 3: Overly Complex Tests

```python
# BAD: Test doing too much
def test_entire_mission_lifecycle():
    # 100 lines testing start, pause, resume, markers, tracking, finish...
    # Hard to debug when it fails
```

**GOOD:** One test per behavior:
```python
def test_mission_start_from_idle_succeeds():
    # Focused on ONE transition

def test_mission_pause_from_active_succeeds():
    # Focused on ONE transition
```

---

## Integration with Workflow

### For Bug Fixes

See `CLAUDE.md` Bug Fix Workflow:

1. Understand the bug
2. **Write a failing test FIRST (TDD Red Phase)**
   - Test must reproduce the bug
   - Confirm test fails
3. **Implement the fix (TDD Green Phase)**
   - Make the test pass
4. **Refactor if needed (TDD Refactor Phase)**
5. Verify all tests pass
6. Commit test + fix together

### For New Features

See `CLAUDE.md` New Feature Workflow:

1. Clarify requirements
2. Consult design docs
3. **Write acceptance tests FIRST (TDD Red Phase)**
   - Define expected behavior
   - Confirm tests fail (feature doesn't exist)
4. **Implement incrementally (TDD Green Phase)**
   - One test at a time
5. **Refactor (TDD Refactor Phase)**
6. Test thoroughly across environments

---

## Measuring Success

### Team Metrics

- **100%** of new PRs include tests
- **<10s** unit test suite runtime
- **Zero** bugs in tested code reach production
- **<5min** from code change to test feedback

### Individual Metrics

Ask yourself:
- Did I write the test first? (RED)
- Did the test fail for the right reason? (RED)
- Did I write minimal code to pass? (GREEN)
- Did I refactor while keeping tests green? (REFACTOR)
- Would this test catch the bug if I broke the code?

---

## Getting Help

### Resources

- **CLAUDE.md** - Project guidelines and workflows
- **docs/AI_CODE_REFERENCE.md** - Code patterns and examples
- **tests/** - Existing tests as examples
- **pytest documentation** - https://docs.pytest.org/

### Common Questions

**Q: How do I test QGIS-dependent code?**
A: Use pytest-qgis for real QGIS runtime tests. See Phase 1 in testing strategy.

**Q: My test is slow (>1s). What do I do?**
A: Mark it as slow: `@pytest.mark.slow`. Keep unit tests fast.

**Q: How do I test private methods?**
A: Don't. Test public interface. Private methods are tested indirectly.

**Q: Should I mock dependencies?**
A: Minimize mocking. Test real code when possible. Mock only external services (HTTP, etc).

---

## Summary: TDD in 5 Rules

1. **Red First** - Write failing test before code
2. **Green Fast** - Write simplest code to pass
3. **Refactor Safe** - Clean up while tests pass
4. **Test Behavior** - Not implementation details
5. **Run Often** - Get feedback in seconds, not hours

**Remember:** TDD feels slower at first but saves massive time debugging later. In life-safety systems, that time savings can save lives.

---

**Document Version:** 1.0
**Last Updated:** 2026-01-01
**Status:** ACTIVE - Mandatory for all new development
