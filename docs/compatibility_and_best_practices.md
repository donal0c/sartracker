# SAR Tracker Compatibility And Best Practices

This note exists so release tooling and contributors have one stable place to
check the current compatibility expectations for SAR Tracker.

## Supported Runtime

- QGIS `3.28+`
- Qt5 and Qt6 builds
- Python versions bundled with supported QGIS releases

## Hard Rules

- import Qt only via `qgis.PyQt`
- prefer helpers from `utils.qt_compat`
- use `dialog_exec()` for dialogs
- use `utils.notify` helpers for message-bar notifications
- use `EPSG:2157` for ITM work
- treat TM65 as a display or operator-input format, not as the persisted
  working CRS for mission geometry

## Pre-Release Checks

Before release:

- run `./tools/check_compatibility.sh`
- run the automated test suite
- smoke-test startup, marker placement, provider refresh, and shutdown on a
  current Qt6 QGIS build

## Field Diagnostics

When a team reports a compatibility issue, capture:

- QGIS version
- Qt version
- Python version
- OS
- whether the failure is startup, rendering, persistence, or provider related

Then reproduce the narrow failure before changing compatibility code.
