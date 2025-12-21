# SAR Tracker Roadmap (Work Plan)
Classification: **LIFE‑SAFETY CRITICAL**

**Status:** Phases 0-4 COMPLETE ✅ | Phase 5 IN PROGRESS (FR-6 blocked on definition)

This is the single prioritized, linear plan for upcoming work, balancing hardening/performance with team‑requested features.

**Source documents (archived):**
- `WORK_PLAN/REFERENCE/Deep_research.md`
- `WORK_PLAN/REFERENCE/recommendations.md`
- `WORK_PLAN/REFERENCE/hardening_todo.md`
- `WORK_PLAN/REFERENCE/FEATURE_REQUESTS_2025.md`

**Implementation History:**
- Phase 0-4: Completed 2025-12-21 (82 of 84 issues closed)
- Phase 5: 2 open issues remain (SAR-qvn, SAR-5c6)

## Captured Decisions (So We Don’t Rely on Chat History)

- Mission state is defined by opening the **mission folder** (the QGIS project `.qgz` + mission `.gpkg` together), not by opening the GeoPackage alone.
- For “one layer per item”, each item must behave like a real independent layer in QGIS and persist across mission reopen:
  - layer rename (Layer Panel),
  - layer metadata notes (Layer Properties → Metadata),
  - per-layer styling overrides.

## Open Questions / Inputs Needed (Explicit)

These must be answered/confirmed during Phase 2 to avoid rework:

- Performance acceptance thresholds for the 100–150+ layer mission case:
  - target mission open/save time,
  - acceptable layer tree expand/collapse latency,
  - acceptable map pan/zoom responsiveness,
  - acceptable finalize/backup time.
- Exact scope of “one layer per item”:
  - confirm which types are included beyond the current list (clues/markers/rings/lines/search areas),
  - confirm whether bearing lines, search sectors, and text labels are included.
- Naming and safety guardrails:
  - how to handle duplicate item names (layer display names) safely,
  - whether to enforce or warn on maximum layer count per mission.
- FR‑6 definition of “active member” (blocked until defined): time threshold vs roster toggle vs Traccar grouping/attributes, including offline behavior.

## Working Agreements (Non‑Negotiable)

- Maintain compatibility with **QGIS 3.28+** and **Qt5 + Qt6** (use `qgis.PyQt` imports only).
- All mission‑critical operations must be **crash‑resilient**, **offline‑safe**, and **non‑blocking** (use tasks for >100ms work).
- Any new architecture affecting mission storage/layers must ship with:
  - a migration strategy (or explicit non‑support), and
  - a repeatable verification checklist (Qt5 + Qt6, shutdown, offline, long‑run).

## Phase 0 — Stability & Predictability (P0 Hardening Gate) ✅ COMPLETE

Goal: reduce crash likelihood, "Not Initialized" incidents, and cross‑machine persistence failures before expanding scope.

0.1 **Release/Install discipline (Ops + UI)**
- Publish and distribute only Release ZIPs (built with `tools/make_release.py`).
- Add/strengthen “Install Doctor” checks:
  - plugin folder name must be exactly `sartracker`,
  - detect nested installs (e.g. `sartracker-main/sartracker/...`),
  - detect missing vendor assets / dependency variance,
  - detect unwritable mission store path.

0.2 **Startup resilience (providers/deps cannot brick offline use)**
- Provider/vendor/HTTP import failures must be **non‑fatal**:
  - disable only the failing provider,
  - keep missions/layers/map tools usable offline.
- Load/register providers **lazily** and granularly.
- Improve Diagnostics to show real dependency state (`ssl.OPENSSL_VERSION`, module paths/versions).

0.3 **Shutdown + lifecycle crash hardening**
- Establish a single “app closing/unloading” guard checked by:
  - providers, tasks, timers, and async callbacks.
- Stop polling, cancel tasks, disconnect signals/timers before teardown.
- Prevent delayed callbacks/cache rebuilds/renderer mutations during shutdown.

0.4 **Thread‑safety cleanup**
- Remove all `print()` and any UI/log side effects from any `QgsTask.run()` path.
- Standardize task error capture (in task) and reporting (main thread).

0.5 **Persistence correctness across machines**
- Eliminate positional `feature.setAttributes([...])` writes to persistent layers.
- Set attributes by field name/index to avoid GeoPackage/provider‑managed field variance (“wrong field count”).

0.6 **Observability baseline**
- Route Python logging to QGIS Log panel (`QgsMessageLog`) under a consistent category.
- Add a debug verbosity flag (settings + optional env var) to gate noisy output.
- Operator‑facing feedback remains non‑blocking via `utils.notify`.

**Phase 0 Exit Criteria**
- Fresh install from Release ZIP on at least one Qt5 QGIS and one Qt6 QGIS passes:
  - plugin initializes reliably,
  - smoke test indicates “initialized” and reports any safe‑mode/provider disablement clearly,
  - mission creation/resume/finalize works,
  - shutdown while tasks/polling active does not crash.

## Phase 1 — High‑Value Team Features (Parallel once Phase 0 is safe) ✅ COMPLETE

1.1 **FR‑5 Device names/initials throughout UI**
- Show device names everywhere (UI + Current Positions + Breadcrumbs), with device‑ID fallback.

1.2 **FR‑1 Mission Logs Window**
- Non‑modal “Mission Logs” window for end‑of‑mission review (Layer Console + Marker Log + Details).

1.3 **FR‑4 GPX Import**
- File/folder import, folder watch for new GPX, one layer per GPX track.
- Add layers to “GPX Tracks” group; defensive handling for invalid/large GPX.

1.4 **Tracking refresh clarity + easy win**
- Default Traccar breadcrumbs filtering to **mission start time** (unless overridden).
- Document refresh semantics (what is cumulative, what is incremental) in operator‑facing help.

## Phase 2 — 100+ Layer Scalability: Architecture Spike (Decision Gate) ✅ COMPLETE

Goal: validate that the chosen "one layer per item" approach remains responsive at 100–150+ layers.

2.1 **Prototype per‑item layers backed by shared tables**
- Persist features in a small set of GeoPackage tables (by type), and represent each item as a separate QGIS layer filtered by a stable `item_id`.
- Never key logic off layer names (users can rename freely); use `item_id` + custom layer properties.
- Validate that per‑item rename/metadata/style remains independent and persistent (project is the mission truth).

2.2 **Benchmarks (must be measured, not guessed)**
- With 150+ item layers:
  - mission open/save time,
  - layer tree responsiveness,
  - pan/zoom/render responsiveness,
  - finalize/backup time,
  - crash‑free shutdown under load.

**Phase 2 Output**
- A short Architecture Decision Record (ADR) committed in `WORK_PLAN/` stating:
  - chosen storage model,
  - acceptance thresholds,
  - migration strategy from current missions.

## Phase 3 — Layer Scalability Foundation (Enablers for FR‑2/FR‑3) ✅ COMPLETE

3.1 **Item registry + layer catalog**
- Introduce a stable registry (`item_id`, type, geometry, created_at, deleted flag, etc.).
- Implement a layer factory/catalog that can:
  - discover existing item layers in the project even if renamed/moved,
  - rebuild missing layers safely,
  - avoid heavy work at startup (lazy creation/loading).

3.2 **Bulk usability + safety**
- Add safe bulk operations by group/type (show/hide/collapse, optional “lock” conventions).
- Guardrails for accidental overload (optional warnings above a configurable layer count).

3.3 **Performance foundations**
- Create spatial indexes for mission GeoPackage layers where supported.
- Add optional “Performance Mode” presets (scale-based visibility, reduced expensive labeling/symbology).

## Phase 4 — Deliver the Layer Program (FR‑2 + FR‑3) ✅ COMPLETE

4.1 **FR‑2 One layer per clue/marker/ring/line/search area**
- Implement per‑item layer creation/edit/delete with correct persistence.
- Migration path for existing missions (one‑time, with backups).
- Stress‑test interrupted operations (crash mid‑add/delete) for corruption resilience.

4.2 **FR‑3 Map Tools grouping**
- Enforce the agreed layer tree structure under “Map Tools” with consistent ordering.

**Phase 4 Exit Criteria**
- Large mission (150+ layers) is usable by coordinators without UI stalls.
- Migration is reliable and reversible (backup + clear operator prompts).
- Qt5 + Qt6 verification completed.

## Phase 5 — Blocked / Clarifications / Follow‑ons ⚠️ IN PROGRESS

**Open Issues:**
- SAR-qvn: FR-6 definition question (blocking)
- SAR-5c6: FR-6 Active members filter implementation (blocked by SAR-qvn)

5.1 **FR‑6 Active members filter (blocked on definition)**
- Implement only once "active" is defined (time threshold vs roster toggle vs Traccar groups/attributes) including offline behavior.
- **Status:** Blocked pending user clarification on "active member" criteria

5.2 **Medium‑term resilience**
- Consider replacing `requests` with QGIS networking APIs (`QgsNetworkAccessManager`) to reduce dependency variance.
- Add one‑click “Export Support Bundle” (diagnostics + smoke test + sanitized config + logs).
