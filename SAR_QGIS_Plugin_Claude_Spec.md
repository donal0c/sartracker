# SAR QGIS Plugin — Claude Code Build Spec (v1)

## Purpose
Build a cross-platform **QGIS plugin** (`sartracker`) in Python (PyQGIS + PyQt) that turns QGIS into a **Search & Rescue (SAR) console**. We will develop entirely in isolation (no access to real Traccar server or PostGIS) using local fixture files and an optional mock HTTP API. Later, we will swap the data provider to the real server/DB with no UI changes.

> Production data flow (for context): Phones (Traccar Client) -> Traccar Server -> PostgreSQL/PostGIS (server = source of truth) -> QGIS Plugin (client).
> Development data flow (now): Fixture JSON/CSV (or mock API) -> QGIS Plugin.

---

## Non-Goals (Important)
- We are not installing/configuring Traccar Server or Postgres/PostGIS right now.
- We are not building a web dashboard.
- We are not writing server-side ingestion code.
Focus strictly on the QGIS plugin with a clean provider abstraction.

---

## Core Capabilities to Build Now (Phases 1–2)
We will deliver two working phases first. Later phases are sketched but not required to start.

### Phase 1 — “Hello SAR” (Fixtures -> Current Points)
**User story:** As an operator, I pick a fixtures folder and click Load / Refresh; I see the latest position of each rescuer plotted as points over a basemap.

**Requirements**
- Add a toolbar button and a docked panel (“SAR Panel”).
- Provide a Settings control (in the panel or a dialog) to choose a fixtures folder on disk.
- Implement a Provider interface and a FileJSONProvider that reads snapshot_current.json from the fixtures folder.
- Create/Update a QgsVectorLayer named "SAR / Current" (type: Point, CRS: EPSG:4326).
- Fields: device_id (str), name (str), ts (ISO 8601 string).
- Add one point per rescuer with geometry from lon/lat (note: X=lon, Y=lat).
- Style: unique color per device_id, label by name.
- If the layer already exists, replace features in place (do not add duplicate layers).

**Acceptance**
- Clicking Load / Refresh (after picking fixtures) renders points on the current map.
- Clicking again after editing the fixture file updates the points (no duplicates).

---

### Phase 2 — Breadcrumbs & Auto-Refresh
**User story:** As an operator, I can see breadcrumb trails and watch current positions auto-refresh on a timer; I can pause and resume the updates.

**Requirements**
- Fixture file: breadcrumbs_15min.json (same schema; multiple time-ordered samples per rescuer).
- Add a QgsVectorLayer "SAR / Breadcrumbs" (LineString/MultiLineString).
  - Group by device_id, sort by ts, construct polylines.
  - If a time gap between consecutive points > N minutes (configurable, default 5), break the line into multiple segments.
- Introduce a QTimer (default 10 seconds) to re-run current positions update in place.
- Panel buttons: Start, Pause. (Start = begin timer; Pause = stop timer.)

**Acceptance**
- Breadcrumb lines appear, ordered by time, no zig-zag from out-of-order points.
- Auto-refresh updates SAR / Current every 10s when running; Pause stops it; Start resumes it.

---

## Data Contracts

### Provider Interface
`providers/base.py`
```python
from typing import List, Dict, Optional

FeatureDict = Dict[str, object]

class Provider:
    def get_current(self) -> List[FeatureDict]:
        """Return latest point per rescuer.
        Each feature has: device_id:str, name:str, lat:float, lon:float, ts:str(ISO8601)."""
        raise NotImplementedError

    def get_breadcrumbs(self, since_iso: Optional[str] = None) -> List[FeatureDict]:
        """Return multiple points per rescuer (time-ordered)."""
        raise NotImplementedError
```

### File JSON Provider
`providers/file_json.py`
```python
import json, os
from .base import Provider

class FileJSONProvider(Provider):
    def __init__(self, folder: str):
        self.folder = folder

    def _load(self, name: str):
        path = os.path.join(self.folder, name)
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def get_current(self):
        return self._load("snapshot_current.json")

    def get_breadcrumbs(self, since_iso=None):
        return self._load("breadcrumbs_15min.json")
```

### Fixture JSON Schema
`snapshot_current.json` (array of latest points; one per rescuer)
```json
[
  {"device_id":"alpha-01","name":"Alpha 01","lat":52.123456,"lon":-9.123456,"ts":"2025-01-01T12:00:00Z"},
  {"device_id":"bravo-02","name":"Bravo 02","lat":52.124000,"lon":-9.122000,"ts":"2025-01-01T12:00:05Z"}
]
```
`breadcrumbs_15min.json` (array of multiple points per rescuer, time-ordered)
```json
[
  {"device_id":"alpha-01","name":"Alpha 01","lat":52.123100,"lon":-9.123900,"ts":"2025-01-01T11:45:00Z"},
  {"device_id":"alpha-01","name":"Alpha 01","lat":52.123300,"lon":-9.123700,"ts":"2025-01-01T11:46:00Z"},
  {"device_id":"bravo-02","name":"Bravo 02","lat":52.124200,"lon":-9.121800,"ts":"2025-01-01T11:45:30Z"}
]
```

> You may also add CSV fixtures; keep headers: device_id,name,lat,lon,ts.

---

## QGIS / UI Details

### Panel & Actions
- Create a dockable panel (“SAR Panel”) with:
  - Fixtures Folder picker (persist to plugin config).
  - Buttons: Load / Refresh, Start, Pause.
  - Read-only status: Provider type, last refresh time, refresh interval.
- Add a toolbar button mirroring Load / Refresh.

### Basemap
- If the project has no layers, auto-add an XYZ OpenStreetMap basemap (no external plugin requirement).

### CRS
- Create geometries in EPSG:4326.
- Ensure on-the-fly reprojection is enabled; recommend setting project CRS to EPSG:29903 (Irish Grid) when the plugin first runs (safe if user agrees).

### Styling
- SAR / Current: categorized/unique renderer by device_id; labels show name.
- SAR / Breadcrumbs: lines with moderate width; optionally a time-based graduated color ramp (older -> lighter).

### Error Handling
- If fixtures folder is unset or missing expected files, show a friendly message.
- If JSON parsing fails, display concise error and skip update (don’t crash the plugin).

---

## Code Integration Points (Minimal)

In `sartracker.py` (or a `controllers/` module):
- Initialize provider once fixtures folder chosen:
  ```python
  from providers.file_json import FileJSONProvider
  self.provider = FileJSONProvider(self.state.fixtures_dir)
  ```
- Load / Refresh handler:
  1. data = self.provider.get_current()
  2. Build/replace features in SAR / Current layer (create if missing).
  3. Apply/keep symbology + labeling.
- Breadcrumbs handler (Phase 2):
  1. pts = self.provider.get_breadcrumbs()
  2. Group by device_id, sort by ts, construct polylines.
  3. Build/replace features in SAR / Breadcrumbs layer.
- Auto-refresh:
  - Create a QTimer (10s). Start/Pause control it. On timeout, call Load / Refresh logic.

---

## File/Folder Additions to Create
```
sartracker/
  providers/
    __init__.py
    base.py
    file_json.py
  controllers/
    __init__.py
    panel_controller.py        # optional: wire UI to provider and map updates
    layers_controller.py       # optional: layer creation/update & styling helpers
  utils/
    __init__.py
    config.py                  # persist fixtures folder path, refresh interval
  fixtures/                    # add sample files here for local tests
    snapshot_current.json
    breadcrumbs_15min.json
```

---

## Future Phases (Do NOT build yet, but structure code to allow them)
- Phase 3 — Mission lifecycle: Start/Pause/Resume/Finish, autosave project, auto-resume on launch.
- Phase 4 — SAR tools: Casualty/POI points (Irish Grid input or map-click), Search Areas (polygon), coord converter, measure shortcut, cursor readout.
- Phase 5 — Playback & exports: time slider, CSV metrics (participants/distance/duration), GeoPackage export, PNG/PDF map export.
- Phase 6 — Provider swap: add HttpProvider (mock API) and PostGISProvider (read-only views); switch via Settings without touching UI logic.

---

## Definition of Done (for Phases 1–2)
- The plugin can be zipped and dropped into a QGIS plugins folder and enabled.
- Operator can pick a fixtures folder and click Load / Refresh to see current points.
- Operator can enable Breadcrumbs and see trails.
- Auto-refresh (10s) runs, and Start/Pause works.
- Errors are handled gracefully with messages, not crashes.
- Code is organized (providers/controllers/utils) and documented inline.

---

## Nice-to-Haves (if time permits)
- Persist panel geometry & last-used folder.
- Simple unit test for provider parsing (using the fixtures).
- Symbology .qml files in layers/styles/ to keep code clean.
- A “Reset demo” button to reload fixtures.

---

## What You (Claude Code) Should Produce Now
1. Create the providers and utils packages and files as specified.
2. Wire the Load / Refresh action to render SAR / Current.
3. Implement Breadcrumbs rendering and the QTimer with Start/Pause controls.
4. Add basic Settings (fixtures folder selection + refresh interval) with persistence.
5. Keep code cross-platform and free of absolute paths.

Provide a concise summary of changes and a quick test guide after each iteration.
