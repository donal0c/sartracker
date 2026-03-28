# Runtime Warning Triage

This note captures the field warning bundle from `Sartracker_updates.odt` and
classifies each item based on what we could reproduce in the current codebase.

Date: `2026-03-28`

## Summary

The warning bundle is a mix of:

- real plugin-side noise that should be reduced
- expected informational messages that looked more alarming than intended
- likely Qt/QGIS platform warnings outside core SAR logic
- a previously stale compatibility guard that was failing for repository/tooling
  reasons rather than a confirmed runtime incompatibility

## Fixed In This Pass

### 1. Casualty placement prompt no longer looks like a runtime critical error

- Field signal:
  `SAR Tracker - CRITICAL: Click on map to add Casualty location`
- Outcome:
  normal casualty placement now uses the standard `SAR Tracker` title instead
  of `SAR Tracker - CRITICAL`
- Rationale:
  this is a normal operator prompt, not a system failure

### 2. Marker cursor rendering now bails out cleanly if Qt gives an inactive painter

- Field signal:
  painter-related warnings in Qt6/Linux environments
- Outcome:
  custom cursor rendering now returns `None` immediately when `QPainter`
  is inactive, falling back to the default crosshair instead of continuing
  down a noisy painter path

### 3. Compatibility guard now reflects the current repository correctly

- Field signal:
  broad claim that the plugin is not compatible with the current QGIS release
- Outcome:
  `./tools/check_compatibility.sh` now passes on the current repository after:
  - excluding tests from the deprecated-EPSG scan
  - restoring the compatibility reference document expected by the guard
- Additional evidence:
  `python3 tools/smoketest.py` exited cleanly on the current codebase

## Triaged As Likely Harmless Or External Noise

### QImage allocation-limit warning

- Signal:
  `QImageIOHandler: Rejecting image as it exceeds the current allocation limit`
- Assessment:
  likely a large-image or platform memory-guard issue, not a SAR mission-state
  bug by itself
- Action:
  monitor unless paired with a concrete broken workflow

### QMetaEnum empty-keys warning

- Signal:
  `QMetaEnum::keysToValue: empty keys string`
- Assessment:
  likely Qt/QGIS framework noise unless we can tie it to a broken control path
- Action:
  no code change in this pass

## Triaged As Expected Informational Messages

### Start Fresh cancelled

- Signal:
  `Start Fresh cancelled; continuing with existing mission store`
- Assessment:
  expected outcome message, not a defect by itself

### Pre-Mission Trails

- Signal:
  repeated `Pre-Mission Trails` messages
- Assessment:
  current code already latches this warning once per session and suppresses it
  when mission state is active
- Action:
  keep monitoring for a concrete reproduction if the team still sees repeats

## Still Worth Watching

### Focus-mode picture/painter warnings

- Signal:
  `QPicture::play` / `QPainter` warnings around focus mode
- Assessment:
  may be partly reduced by the cursor-rendering guard above, but we do not yet
  have a narrow reproduction tied specifically to focus mode
- Action:
  keep as watch-item, not yet a confirmed product bug

### Layer-tree invalid-index warning

- Signal:
  `QAbstractItemModel::endRemoveRows: Invalid index`
- Assessment:
  this may already have been improved by the earlier Qt6 layer-tree visibility
  hardening, but we do not have a fresh field reproduction yet
- Action:
  monitor and spin a narrower bug if it reappears with a reproducible workflow

### Mission-store migration warnings for helicopter layers

- Assessment:
  likely tied to migration/repair paths rather than a broad compatibility fault
- Action:
  treat as a narrower migration concern if it reappears

## Current Recommendation

- treat the field warning bundle as mostly triaged
- keep `SAR-iscf` focused on concrete compatibility failures rather than
  general warning noise
- use future field logs to create narrow reproductions for any warning that
  still appears after this pass
