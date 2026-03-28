# PRE_LAUNCH Stabilization Phases

## Purpose

This document is the working roadmap for getting SAR Tracker into a safer, more stable pre-launch state before broader team adoption.

This is not a feature roadmap.
It is a stabilization and confidence-building roadmap focused on:

- mission correctness
- persistence and data safety
- startup/shutdown reliability
- operator clarity
- test trust
- field resilience

## Current Checkpoint

As of 2026-03-28:

- `Phase 0` is complete enough to use as a reliable development gate
- `Phase 1A` is largely complete and has produced a working lifecycle spec suite
- `Phase 1` startup/resume hardening has already delivered:
  - clean startup with explicit SAR activation
  - duplicate resume/start-fresh prompt fix
  - startup layer restoration repair
- `Phase 2` has now delivered:
  - truthful autosave status semantics for async backup completion
  - clean start-fresh workspace reset when mission names collide
- `Phase 3` is now underway with early hardening already landed:
  - empty provider refreshes preserve existing tracking layers and no longer claim they were cleared
  - outage/cached-data controller behavior is covered by new regression tests
  - previously skipped provider-controller tests have been revived and are passing
  - active-device layer filtering now has direct controller-level regression coverage
    for online, offline, stale-unknown, and recent-unknown device states
- the remaining known intentional red is now outside this lifecycle slice and
  lives in the diagnostics area

The rest of the mission lifecycle findings uncovered so far have either been
converted into passing regressions or explicitly deferred.

Manual QGIS exploratory testing is now also part of the planned workflow,
paired with log capture and diagnostics review rather than treated as an
informal afterthought. See
[manual_qgis_logging_runbook.md](/Users/donalocallaghan/Documents/Qgis/sartracker/PRE_LAUNCH/manual_qgis_logging_runbook.md).

---

## Guiding Principles

- Lives may depend on this plugin behaving correctly.
- Every production change should be driven by tests first.
- We work by operational slice, not file-by-file.
- We reduce duplicate state and duplicate code paths wherever possible.
- We prefer explicit failure over silent fallback in safety-critical flows.

---

## Phase 0: Restore Test Trust

### Goal
Make the test suite trustworthy enough to guide hardening work.

### Why this comes first
Right now, part of the suite appears to blur the line between mocked QGIS and real QGIS. That creates noisy failures and makes it harder to know which red tests represent real product risk.

### Focus

- fix the real-QGIS vs mock-QGIS boundary in the test harness
- ensure tests that require real QGIS only run in a real QGIS environment
- ensure mock-mode tests use controlled stubs instead of accidental `MagicMock` behavior
- identify flaky tests and quarantine or repair them
- establish a reliable focused test command for each stabilization slice

### Exit Criteria

- test environment behavior is predictable
- red tests are meaningful
- core non-QGIS unit suite is usable as a development gate
- real-QGIS integration suite can be run intentionally, not accidentally

---

## Phase 1: Mission Lifecycle Hardening

### Goal
Make mission startup, resume, pause, finish, finalize, unlock, and restart behavior correct and predictable.

### Why this is highest priority
This is the area with the highest operational risk and the one already showing signs of weirdness in the field.

### Phase 1A: Specification By Test

Before changing production lifecycle code, we first define how the plugin is expected to behave using unit and integration tests.

This is a discovery phase as much as a hardening phase:

- specification tests describe how startup, resume, autosave, cleanup, and start-fresh should behave
- characterization tests document how the current code behaves today
- gaps between those two become the bug inventory for later production changes

This lets us uncover hidden lifecycle problems without needing immediate manual QA in QGIS and without refactoring blind.

#### Focus

- write controller-level tests for mission startup, pause/resume, finish, and cleanup invariants
- write storage/helper tests for:
  - new mission preparation
  - resume with existing mission store
  - start fresh from dirty or partially initialized state
  - replay/live storage isolation
- write autosave expectation tests for:
  - missing UI components
  - persistence warnings
  - truthful success/failure signaling
- add lightweight real-QGIS integration tests only where QGIS/project behavior matters
- record failing tests as explicit pre-fix findings

#### Exit Criteria

- critical lifecycle expectations are expressed as executable tests
- failing tests identify real bugs or ambiguous behavior instead of test harness noise
- we can prioritize production fixes from a clear test matrix

### Focus

- map the full lifecycle from plugin startup to mission completion
- define expected behavior for:
  - clean startup
  - startup with existing mission store
  - start fresh
  - resume existing mission
  - paused mission resume
  - finish mission
  - finalize mission
  - unlock finalized mission
- reduce duplicate lifecycle ownership between `sartracker.py` and mission controllers
- make one component the clear owner of mission session state
- tighten state-machine rules, especially around paused missions and starting new missions

### Exit Criteria

- one clear mission lifecycle owner
- no ambiguous start/resume behavior
- no dirty mission state carried unexpectedly between sessions
- regression tests cover the main lifecycle transitions

---

## Phase 2: Save, Backup, and Persistence Correctness

### Goal
Ensure that saved mission state is actually persisted, recoverable, and truthfully reported to operators.

### Focus

- review project save flow
- review auto-save flow
- review backup sync flow
- review GeoPackage persistence guarantees
- distinguish:
  - save succeeded
  - backup started
  - backup completed
  - backup failed
- harden mission store validation and persistence diagnostics
- ensure layers are not silently left in memory when persistence is expected

### Exit Criteria

- UI status reflects real persistence state
- backup and archive operations are trustworthy
- persistence warnings are actionable and accurate
- tests cover failed save, failed backup, and partial-success cases

### Manual-QGIS Companion Track

Phase 2 and Phase 5 both benefit from deliberate exploratory testing in a real
QGIS session, especially when the team notices something that "feels wrong"
before we have a clean reproduction.

For this project, manual exploratory work should be treated as structured
evidence gathering:

- launch QGIS from a terminal when possible so Python/QGIS output is captured
- enable SAR Tracker debug logging when investigating a specific workflow
- note the exact click path and operator expectation
- capture the QGIS Log Messages output for the `SAR Tracker` category
- convert suspicious behavior into tests before making production changes

This keeps field observations, logs, and TDD working together instead of
competing with one another.

---

## Phase 3: Provider and Tracking Resilience

### Goal
Make live tracking refresh behavior resilient to outages, stale data, replay mode, and partial provider failures.

### Focus

- review refresh lifecycle end to end
- review cached/offline behavior
- review breadcrumb accumulation and reset behavior
- verify live mode and replay mode remain isolated
- verify empty provider responses do not wipe critical last-known positions
- tighten user-facing messaging around cached data, outages, and restored connectivity

### Exit Criteria

- refresh behavior is predictable during outages
- stale data is clearly identified
- replay cannot contaminate live mission data
- last-known positions are preserved safely during transient failures

---

## Phase 4: Shutdown, Reload, and Task Safety

### Goal
Prevent crashes, race conditions, and inconsistent state during unload, project switching, and QGIS shutdown.

### Focus

- review plugin unload flow
- review `aboutToQuit` behavior
- review timer shutdown ordering
- review task cancellation and callback suppression
- review deleted-Qt-object guards
- ensure project switching does not leave stale mission state behind

### Exit Criteria

- clean unload without late callbacks mutating torn-down UI
- reduced risk of shutdown crashes
- project switching behaves cleanly
- shutdown ordering is documented and tested

---

## Phase 5: Operator-Facing Safety and UX Clarity

### Goal
Make the UI communicate the true system state clearly and consistently during live operations.

### Focus

- tighten status labels and warning text
- review replay mode messaging
- review finalize/unlock messaging
- review auto-save and refresh indicators
- make dangerous or unavailable actions explicit
- review disabled tools and known-problem UI paths

### Exit Criteria

- operators can tell whether they are in live mode, replay mode, paused mode, or finalized mode
- save/backup state is not overstated
- warnings are specific and useful
- confusing or misleading labels are removed

---

## Phase 6: Performance and Scale Validation

### Goal
Confirm the plugin remains responsive and correct under realistic operational load.

### Focus

- high device counts
- long breadcrumb histories
- many layers in project
- repeated refresh cycles
- long-running mission sessions
- backup/archive behavior under realistic data volume

### Exit Criteria

- acceptable responsiveness under representative load
- no obvious memory growth or degradation patterns
- long-session behavior is stable

---

## Phase 7: Documentation Refresh and Launch Readiness

### Goal
Replace outdated docs with a smaller set of accurate pre-launch documents.

### Focus

- update architecture and lifecycle docs after refactors settle
- document operator-critical workflows
- document recovery workflows for save/backup/restart issues
- document known limitations honestly
- create a launch checklist

### Exit Criteria

- docs match the code
- pre-launch checklist exists
- team can test, deploy, and support the plugin using current documentation

---

## Suggested Execution Order

1. Phase 0: Restore Test Trust
2. Phase 1: Mission Lifecycle Hardening
3. Phase 2: Save, Backup, and Persistence Correctness
4. Phase 3: Provider and Tracking Resilience
5. Phase 4: Shutdown, Reload, and Task Safety
6. Phase 5: Operator-Facing Safety and UX Clarity
7. Phase 6: Performance and Scale Validation
8. Phase 7: Documentation Refresh and Launch Readiness

---

## Immediate Next Step

Current recommended execution order from here:

1. continue Phase 3 provider/tracking resilience work
2. keep the manual-QGIS logging runbook current as new field workflows are exercised
3. use field reports plus logs to drive the next spec/tests before any broader UI or workflow changes
