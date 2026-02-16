# SAR Tracker Post-Incident Handoff (2026-02-16)

## Scope
This handoff covers all commits after the known-good baseline `ec4c25c` (2026-02-08) through `fd620bf` (2026-02-14), plus a hardening pass completed on 2026-02-16.

Commits reviewed:
- `4429725` (Batch A)
- `69e0222` (tests)
- `673e82d` (Batch B1/B2)
- `29ac07d` (autosave semantics fix)
- `7a5b3b6` (memory->store migration)
- `266508d` (Irish coordinates change)
- `fade5a9` (cursor + schema fallback fix)
- `fd620bf` (breadcrumbs geometry fix)

## Incident Root Causes (Confirmed)
1. Marker activation cursor crash (critical)
- Introduced in `673e82d` by calling `self.cursor()` in `MarkerMapTool.activate()`.
- On some QGIS/Qt bindings this method is unavailable, producing `AttributeError`.
- Fixed in `fade5a9` by tracking explicit active cursor state.

2. Tracking fallback schema mismatch (critical)
- Shared fallback path called `_ensure_schema_layer()` for IDs not present in schema tree (`sar_current_positions_active`, `sar_breadcrumbs`).
- Produced `Unknown layer id` errors during refresh.
- Fixed in `fade5a9` by restoring layer definitions.

3. Breadcrumb geometry mismatch in first hotfix (critical)
- `fade5a9` restored breadcrumbs with wrong geometry (`Point`).
- Runtime writes `LineString` segments (`QgsGeometry.fromPolylineXY`), causing commit failures.
- Fixed in `fd620bf` by switching schema type to `LineString`.

## Additional Defects Fixed in Hardening Pass (2026-02-16)
4. Pre-mission warning lifecycle bug
- Warning latch persisted and could remain misleading after mission start.
- Fixes:
  - warning suppressed when mission is already active
  - latch reset on mission transition `idle/finished -> active`
- Files:
  - `controllers/layer_managers/tracking_manager.py`
  - `sartracker.py`

5. Cache-path migration bypass
- `LayerManager.ensure_vector_layer()` returned cached layer directly, bypassing memory->store migration logic.
- Fix: cache-hit path now runs `_migrate_existing_layer_if_needed(...)` and updates cache.
- File:
  - `layers/manager.py`

## Tests Added for Regression Prevention
- `tests/test_tracking_per_device_fallback.py`
  - `test_breadcrumb_pre_mission_warning_suppressed_when_mission_active`
  - `test_mission_start_clears_pre_mission_warning_latch`
- `tests/test_layer_manager_resilience.py`
  - `test_ensure_vector_layer_migrates_cached_memory_layer_when_store_enabled`

## Validation Evidence
Focused suites run after fixes:
- `tests/test_cursor_and_layer_id_regressions.py`
- `tests/test_tracking_per_device_fallback.py`
- `tests/test_layer_manager_resilience.py`
- `tests/test_autosave_guard.py`
- `tests/test_provider_controller_refresh.py`
- `tests/test_breadcrumb_accumulator_wiring.py`

Result: passing in mock-QGIS environment for incident-relevant paths.

Coordinate change validation (`266508d`) run separately:
- `tests/test_coordinate_converter_tm65_mode_source.py`
- `tests/test_coordinate_display_mode_config.py`
- `tests/test_tm65_grid_reference_parser.py`
- `tests/test_wgs84_direction_labels.py`
- `tests/test_documentation_epsg_references.py`
- `tests/test_dialog_baselines.py`

Result: passing/skipped as expected in mock environment.

## Comparison Against Baseline (`ec4c25c`)
A broad non-QGIS run was executed on both current branch and a temporary worktree at `ec4c25c`.

Outcome:
- Both runs show substantial pre-existing environment/test instability unrelated to this incident (notably mock-QGIS limitations and local GEOS/QGIS import issues).
- No evidence from this comparison that recent commits introduced a new broad test collapse beyond the incident-specific regressions already identified and fixed.

## Remaining Risks / Unknowns
1. Intermittent "SAR Tracker - Not Initialized" startup report
- Existing behavior is triggered when `self.sar_panel` is unavailable during startup.
- No deterministic reproduction from available local artifacts.
- Requires field startup diagnostics to classify as environment/transient vs code defect.

2. Startup warning noise around missing layers / gpkg open timing
- Observed in field report (`Cannot open ...gpkg`, `Cannot find layer sar_helicopter_2/3/4`).
- Likely sequencing/timing related and may be benign if subsequent initialization recovers.
- Needs field timeline + logs to prove harmlessness.

3. CI-style certainty gap
- Current local environment has known qgis/shapely/geos loading limitations for full integration suite.
- Full certainty requires execution in production-like QGIS runtime matrix.

## Release Gate Recommendation (Required Before Team Rollout)
1. Run plugin in real QGIS with production-like setup:
- QGIS 3.28 (Qt5)
- QGIS 3.44+ (Qt6)

2. Execute scripted operator flows:
- cold start with auto-connect enabled
- start mission before/after provider connect
- marker placement (clue/casualty/hazard)
- live current positions + breadcrumbs
- autosave cycles + persistence diagnostics
- plugin disable/enable cycle and project reload

3. Capture and archive:
- SAR diagnostics bundle
- QGIS log panel export
- exact startup sequence timestamps

## Data Needed From Field Team for Final Closure
To close all uncertainty around startup/import warnings, collect from at least one affected machine:
- exact plugin ZIP/commit hash installed
- QGIS version, Qt version, OS build
- full QGIS message log export covering startup through first refresh
- SAR diagnostics bundle created immediately after warning appears
- steps/timestamps to reproduce (cold launch vs plugin reload vs project open)
- sample project/mission path where gpkg warnings occurred

## Final Status
- Incident-causing regressions are identified and fixed.
- Two additional latent defects were fixed and covered with regression tests.
- Remaining uncertainty is confined to startup-sequencing behavior that requires field diagnostics for deterministic closure.
