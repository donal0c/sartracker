# Mission Lifecycle Spec Findings

This document tracks lifecycle and persistence issues uncovered by the
specification-by-test phase.

These findings are intentionally tied to executable tests so they stay honest.

## Current Status

As of 2026-03-27, the lifecycle spec suite in
[tests/test_mission_lifecycle_spec.py](/Users/donalocallaghan/Documents/Qgis/sartracker/tests/test_mission_lifecycle_spec.py)
contains:

- 52 passing specification tests
- 2 strict `xfail` tests documenting suspected bugs
- focused lifecycle verification:
  `103 passed, 2 xfailed`
- full-suite verification:
  `1035 passed, 157 skipped, 3 xfailed`

## Remaining Open Findings From Spec Tests

### 1. Autosave reports success before async backup completion is known

- Spec test: `test_spec_autosave_waits_for_backup_completion_before_reporting_success`
- Risk:
  operators may get a green autosave indication when backup only started, not
  when backup actually completed successfully.

### 2. “Start fresh” with the same mission name does not produce a clean workspace

- Spec test: `test_spec_start_fresh_with_same_name_removes_stale_attachment_files`
- Risk:
  stale attachments and possibly stale mission artifacts remain in place when a
  supposedly fresh mission reuses an existing folder name.

## What This Phase Established

This phase is no longer just bug discovery. A number of lifecycle defects found
by spec tests have now been fixed under TDD and locked down by passing
regressions.

Notable lifecycle behaviors now covered by passing tests include:

- starting a new mission from `PAUSED` is rejected
- clean reset when no mission store is configured
- clean reset when a configured mission store is missing
- failed Start Fresh clears stale controller session state
- start-fresh clearing saved mission-controller state
- start-fresh cancellation leaving existing mission storage untouched
- successful metadata collection persisting coordinator state
- failed metadata persistence no longer claiming success on controller path
- legacy metadata collection success path
- failed metadata persistence no longer claiming success on legacy path
- legacy Start Fresh failure clearing runtime mission paths
- legacy resume fallback failure clearing runtime mission state
- legacy no-store startup clearing cached coordinator metadata
- missing resumed-storage file clearing stale session state
- resumed mission finalization state refreshing from project state
- malformed paused-mission payloads clearing saved state
- failed paused restore clearing saved state even without exception
- controller and legacy sync paths retrying after transient load exceptions
- legacy missing-store startup clearing runtime state instead of rebuilding around a dead path
- unload-time freeze of lifecycle state
- duplicate project-sync suppression
- legacy finalize flow keeping the in-progress guard raised until archive callback
- extracted finalization flow keeping its in-progress guard raised when archive
  start succeeds
- archive-complete validation before finalized state flips
- archive-failure cleanup of finalization guard
- admin unlock rejection and acceptance behavior

## What We Can Still Do Before Manual QA

- expand spec coverage around:
  - startup with missing or invalid mission stores
  - start-fresh cancellation behavior
  - paused mission restore flows
  - finalize/unlock lifecycle behavior
  - project-switch and cleanup invariants
- add carefully targeted real-QGIS integration tests only where QGIS project
  behavior matters

## Directional Signal So Far

The newer `MissionLifecycleController` path is already looking safer than the
legacy orchestration still living in `sartracker.py`.

We also now have real-QGIS integration confirmation for two important project
sync behaviors:

- unsaved non-SAR projects are left clean by `sync_project_state()`
- configured mission-store projects trigger SAR structure creation during sync

During this work, a broader real-QGIS sync test initially hung until the test
was narrowed to isolate structure creation from storage loading. That suggests
the project-sync structure path is healthy, while the storage-loading path may
deserve separate targeted integration coverage later.

That suggests the highest-risk production fixes are likely to be in:

- legacy mission/finalize/autosave flow in `sartracker.py`
- mission storage “start fresh” cleanliness when folder names collide
- edge-case bridging between persisted state and runtime state

## What Likely Needs Human Involvement Later

- validating exact operator expectations for “resume” vs “start fresh”
- checking whether some currently tolerated behaviors are intentionally relied on
- confirming the UX wording and operational ergonomics during live workflows
