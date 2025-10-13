# SAR QGIS Plugin — Complete Technical Specification v2.2

**Project**: Kerry Mountain Rescue Team SAR Tracking System
**Client**: Eamon O'Connor & KMRT Team
**Target Platform**: QGIS 3.40+ (Cross-platform: Windows, Mac, Linux)
**Last Updated**: 2025-10-13
**Current Status**: Phase 1 & 2 Complete (100%)

---

## 📋 IMPLEMENTATION STATUS (as of 2025-10-13)

### ✅ PHASE 1: COMPLETE (100%)

**What's Working:**
- ✅ **Multi-device CSV tracking** - Loads single CSV or entire folder of CSV files
- ✅ **Beautiful map visualization** - Colored breadcrumb trails + labeled current positions
- ✅ **SAR Control Panel** - Docked widget with mission controls, device list, auto-refresh
- ✅ **Mission lifecycle** - Start/pause/resume/finish with real-time elapsed timer
- ✅ **Auto-refresh** - Configurable interval (5-300s), works with/without active mission
- ✅ **Device status** - Shows all devices with green indicators and last update times
- ✅ **Folder-based loading** - Can load all team CSV files at once (4 devices tested successfully)
- ✅ **Auto-save QGIS project** - Configurable interval (1-60 min), manual save button, status indicator
- ✅ **Auto-resume on launch** - Detects paused missions on startup, prompts user to resume or start fresh

**File Structure Created:**
```
sartracker/
├── providers/
│   ├── base.py              ✅ Provider ABC with all required methods
│   └── csv.py               ✅ FileCSVProvider - reads Traccar CSV exports
├── controllers/
│   └── layers_controller.py ✅ Creates/updates breadcrumbs, current positions, POIs, casualties
├── ui/
│   └── sar_panel.py         ✅ SAR control panel with mission controls + device list
├── utils/
│   └── coordinates.py       ✅ Irish Grid (ITM) ↔ WGS84 conversion
├── maptools/
│   └── marker_tool.py       ✅ Click-to-add map tool with coordinate transformation
├── dev_tools/
│   └── generate_mock_csv.py ✅ Mock CSV generator (3 search patterns)
├── From_Eamon/
│   ├── Glenagenty.csv              ✅ Real data (343 points, eoc device)
│   ├── mock_team_alpha.csv         ✅ Mock grid search (60 points)
│   ├── mock_team_bravo.csv         ✅ Mock spiral search (70 points)
│   └── mock_team_charlie.csv       ✅ Mock linear search (50 points)
└── sartracker.py            ✅ Main plugin with all SAR Panel integration
```

**Testing Results:**
- ✅ Single CSV loading works perfectly
- ✅ Folder CSV loading works perfectly (4 devices, different colors)
- ✅ Mission start/pause/resume/finish all functional
- ✅ Timer updates every second when mission active
- ✅ Auto-refresh works correctly (tested at 10s interval)
- ✅ Device list populates correctly
- ✅ Layers panel shows organized SAR Tracking group
- ✅ Map zooms to data extent on load
- ✅ Different colored trails per device (yellow, pink, cyan, etc.)

**Key Technical Decisions:**
1. **CSV Provider first** - Team currently uses CSV workflow, database not ready
2. **Folder support** - Can load entire mission (multiple team CSVs) at once
3. **Memory layers** - Using QGIS memory layers for now, will migrate to PostGIS in Phase 3
4. **Symlink setup** - Created symlink from QGIS plugins dir to dev directory for easy development
5. **QGIS version compatibility** - Fixed label placement enum for QGIS 3.40 (LTR)

---

### ✅ PHASE 2: COMPLETE (100%)

**Completed:**
- ✅ POI/Casualty marker layers added to LayersController
- ✅ MarkerMapTool created - click-to-add with coordinate transformation
- ✅ MarkerDialog created - shows WGS84 + Irish Grid coordinates
- ✅ Layer methods: `add_poi()` and `add_casualty()` implemented
- ✅ MapTool wired to SAR Panel ("Add POI" / "Add Casualty" buttons)
- ✅ MarkerDialog connected to MapTool click event
- ✅ Complete workflow tested: click map → dialog opens → marker added → appears on map
- ✅ Casualty styling (red star markers)
- ✅ POI styling (blue circle markers)
- ✅ Layer ordering fixed (POIs/Casualties on top of tracking data)
- ✅ Real-time cursor coordinates display in status bar
- ✅ Coordinate Converter dialog (Irish Grid ↔ WGS84)
  - Convert between coordinate systems
  - Copy to clipboard
  - Go to location on map
- ✅ Measure Distance & Bearing tool
  - Click two points on map
  - Shows distance in meters/km
  - Shows bearing in degrees + cardinal direction (N, NE, E, etc.)
  - Red line preview while measuring
- ✅ Custom mountain icon for plugin

**Skipped (optional enhancements for later):**
- ⏸️ POI icon styling by type (base=flag, vehicle=car, landmark=triangle, etc.)
- ⏸️ Elevation display at cursor
- ⏸️ Elevation profile tool
- ⏸️ Area measurement tool

---

### 📅 PHASE 3 & 4: PENDING

**Phase 3 (Database Integration)** - 0% complete
- Design PostGIS schema (already spec'd)
- Create migration scripts
- Implement PostGISProvider
- Test database persistence

**Phase 4 (Advanced Features)** - 0% complete
- Time slider/replay
- Export/report generation
- Search history view
- Offline mode support

---

### 🎯 NEXT UP (Priority Order)

**Phase 3 - CalTopo-Inspired Tools:**
1. **Line Tool** - Draw simple lines on map
2. **Bearing Line Tool** - Line from point with specific bearing/azimuth
3. **Sector Tool** - Draw wedge/pie-slice shapes for search directions
4. **Draw Search Areas (Polygons)** - Team assignment, colors
5. **Range Ring Tool** - Circles with specified radius
6. **Import GPX Files** - Load walker routes
7. **Text Annotations** - Labels on map

**Phase 4 - Professional Output:**
8. **Export Maps (PDF/PNG)** - Scale bar, legend, north arrow
9. **Generate Mission Reports (CSV)** - Stats, distances, participants

---

## Table of Contents

1. [Executive Summary](#executive-summary)
2. [System Architecture](#system-architecture)
3. [Complete Feature List (20 Requirements)](#complete-feature-list)
4. [Database Schema](#database-schema)
5. [User Interface Design](#user-interface-design)
6. [Implementation Phases](#implementation-phases)
7. [Technical Implementation Details](#technical-implementation-details)
8. [Development Strategy](#development-strategy)
9. [Testing & Quality Assurance](#testing--quality-assurance)
10. [Deployment & Handoff](#deployment--handoff)

---

## Executive Summary

### Purpose

Build a production-ready QGIS plugin that transforms QGIS into a dedicated **Search & Rescue (SAR) Operations Console** for the Kerry Mountain Rescue Team. The plugin will provide real-time tracking of rescue personnel, mission management, map annotation tools, and professional cartographic output—all in a simplified interface that hides QGIS complexity.

### Current vs. Proposed System

**Current System (Manual Workflow):**
```
Phones (Traccar Client)
  ↓
Traccar Server
  ↓
Python Script (traccar_api_to_csv.py)
  ↓
CSV Files
  ↓
Manual Import to QGIS
  ↓
Generic QGIS UI (complex, GIS-analyst focused)
```

**Proposed System (Automated SAR Console):**
```
Phones (Traccar Client)
  ↓
Traccar Server
  ↓
PostgreSQL/PostGIS Database (server-side, fixed location)
  ↓
QGIS Plugin (mobile van, Zerotier network, spotty comms)
  ↓
SAR Operations Console (simplified UI, mission-focused)
```

### Key Constraints

- **Network**: Server at fixed location, QGIS operator in mobile van with **spotty communications** via Zerotier VPN
- **Users**: Non-GIS experts; needs to be simple enough for any team member
- **Reliability**: Must handle connection drops gracefully, show last known positions
- **Cross-Platform**: Windows, Mac, Linux support required
- **Production Ready**: Replace existing proof-of-concept completely

---

## System Architecture

### Data Flow

```
┌─────────────────┐
│ Traccar Client  │  (Phones - rescue team members)
│  (iOS/Android)  │
└────────┬────────┘
         │ GPS positions every N seconds
         ↓
┌─────────────────┐
│ Traccar Server  │  (Fixed location - EOC/Base)
│  Port: 8082     │  http://kmrtsar.eu or 109.76.170.87:8082
└────────┬────────┘
         │ Writes positions to database
         ↓
┌─────────────────────────────────────┐
│ PostgreSQL/PostGIS Database         │
│                                     │
│ Tables:                             │
│  - devices                          │
│  - positions (geometry points)      │
│  - missions                         │
│  - casualties, pois                 │
│  - search_areas (geometry polygons) │
│  - gpx_tracks, text_annotations     │
└──────────────┬──────────────────────┘
               │ Read-only queries via Zerotier VPN
               │ (Handle connection drops!)
               ↓
      ┌────────────────────┐
      │ QGIS Plugin        │  (Mobile van - SAR operator)
      │                    │
      │ - PostGISProvider  │  Queries database
      │ - SAR Panel UI     │  Simplified controls
      │ - Auto-refresh     │  QTimer (10s default)
      │ - Map Tools        │  Digitizing, measurement
      │ - Report Generator │  Mission metrics
      └────────────────────┘
```

### Provider Architecture

```python
┌──────────────────────────┐
│  Provider (ABC)          │  Abstract base class
│  - get_current()         │
│  - get_breadcrumbs()     │
│  - get_devices()         │
│  - save_casualty()       │
│  - save_poi()            │
│  - save_search_area()    │
└────────┬─────────────────┘
         │
    ┌────┴─────────────────────────────┐
    │                                  │
┌───┴────────────────────┐  ┌──────────┴──────────────┐
│ PostGISProvider        │  │ SpatiaLiteProvider      │
│ (Production)           │  │ (Development Mock)      │
│                        │  │                         │
│ - Connects to remote   │  │ - Local SQLite DB       │
│   PostgreSQL database  │  │ - No network required   │
│ - Handles network      │  │ - Testing/dev only      │
│   failures gracefully  │  │                         │
└────────────────────────┘  └─────────────────────────┘
```

---

## Complete Feature List

All 20 requirements from the client, organized by importance and phase:

### Phase 1: Core Tracking & Mission Lifecycle (MVP)

| # | Feature | Description | Priority |
|---|---------|-------------|----------|
| **01** | **Breadcrumb Trails** | Display time-ordered GPS trail for each rescuer as colored lines | Critical |
| **02** | **Current Locations** | Display latest position for each rescuer as labeled points | Critical |
| **03** | **Start Search** | Begin new mission with specified date/time, activate tracking | Critical |
| **04** | **Pause Search** | Pause mission, stop auto-refresh, record pause time | Critical |
| **05** | **Resume Search** | Resume paused mission, restart tracking from pause point | Critical |
| **06** | **Finish/Save Search** | Complete mission, save final state, mark as finished | Critical |
| **07** | **Auto-Resume on Launch** | On QGIS startup, detect paused mission and prompt to resume | Critical |
| **08** | **Auto-Save Project** | Automatically save QGIS project at user-defined intervals (1-60 min) | Critical |

### Phase 2: Operational Tools

| # | Feature | Description | Priority |
|---|---------|-------------|----------|
| **09** | **Add Casualty** | Place casualty marker via Irish Grid coordinates OR map click | High |
| **10** | **Add POI** | Place point of interest via Irish Grid coordinates OR map click | High |
| **11** | **Coordinate Converter** | Convert between Irish Grid (E/N) and Lat/Lon (WGS84) | High |
| **14** | **Cursor Coordinates** | Display cursor position in both Irish Grid and Lat/Lon in real-time | High |
| **15** | **Measure Distance/Bearing** | Measure straight-line distance and bearing between two points | High |

### Phase 3: Mapping & Areas

| # | Feature | Description | Priority |
|---|---------|-------------|----------|
| **12** | **Import GPX Files** | Load GPX tracks (walker routes) and display on map | Medium |
| **13** | **Draw Search Areas** | Digitize polygon search zones, assign to teams, print/export | High |
| **16** | **Add Text to Areas** | Annotate shaded polygon areas with text labels | Medium |
| **17** | **Draw Circles/Arcs** | Draw circles or arcs from a point with specified diameter/radius | Medium |
| **18** | **Add Text to Map** | Place text annotations anywhere on map | Medium |

### Phase 4: Analysis & Export

| # | Feature | Description | Priority |
|---|---------|-------------|----------|
| **19** | **Playback Saved Search** | Time-slider replay of past missions showing movement over time | Medium |
| **20** | **Generate Reports** | Export mission summary: participants, duration, areas, distances per person | High |
| **--** | **Professional Map Export** | Export print-quality maps (PDF/PNG) with scale, north arrow, legend | High |

### Additional Requirement (from client notes)

| # | Feature | Description | Priority |
|---|---------|-------------|----------|
| **21** | **Simplify QGIS UI** | Hide/disable unnecessary QGIS toolbars and menus when SAR Mode active | High |

---

## Database Schema

### PostgreSQL/PostGIS Schema

This schema will be deployed on the team's server. The plugin connects read-only (except for casualties, POIs, search areas which it writes).

```sql
-- Enable PostGIS extension
CREATE EXTENSION IF NOT EXISTS postgis;

-- ========================================
-- DEVICES TABLE
-- ========================================
CREATE TABLE devices (
    id SERIAL PRIMARY KEY,
    device_id VARCHAR(50) UNIQUE NOT NULL,
    name VARCHAR(100) NOT NULL,
    status VARCHAR(20),  -- 'online', 'offline', 'unknown'
    last_update TIMESTAMP WITH TIME ZONE,
    battery_level FLOAT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX idx_devices_device_id ON devices(device_id);
CREATE INDEX idx_devices_status ON devices(status);

-- ========================================
-- POSITIONS TABLE (GPS breadcrumbs)
-- ========================================
CREATE TABLE positions (
    id BIGSERIAL PRIMARY KEY,
    device_id VARCHAR(50) NOT NULL REFERENCES devices(device_id) ON DELETE CASCADE,
    timestamp TIMESTAMP WITH TIME ZONE NOT NULL,
    geom GEOMETRY(Point, 4326) NOT NULL,  -- WGS84 coordinates
    altitude FLOAT,  -- meters
    speed FLOAT,  -- knots
    battery_level FLOAT,  -- percentage
    motion BOOLEAN,
    distance FLOAT,  -- meters from last point
    total_distance FLOAT,  -- cumulative meters
    attributes JSONB,  -- Additional Traccar attributes
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX idx_positions_geom ON positions USING GIST(geom);
CREATE INDEX idx_positions_device_time ON positions(device_id, timestamp DESC);
CREATE INDEX idx_positions_timestamp ON positions(timestamp DESC);

-- ========================================
-- MISSIONS TABLE
-- ========================================
CREATE TABLE missions (
    id SERIAL PRIMARY KEY,
    name VARCHAR(200) NOT NULL,
    start_time TIMESTAMP WITH TIME ZONE NOT NULL,
    end_time TIMESTAMP WITH TIME ZONE,
    status VARCHAR(20) NOT NULL DEFAULT 'active',  -- 'active', 'paused', 'completed'
    pause_time TIMESTAMP WITH TIME ZONE,
    resume_time TIMESTAMP WITH TIME ZONE,
    autosave_interval INTEGER DEFAULT 5,  -- minutes
    last_autosave TIMESTAMP WITH TIME ZONE,
    project_file_path TEXT,
    notes TEXT,
    created_by VARCHAR(100),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX idx_missions_status ON missions(status);
CREATE INDEX idx_missions_start_time ON missions(start_time DESC);

-- ========================================
-- MISSION_PARTICIPANTS TABLE
-- ========================================
CREATE TABLE mission_participants (
    id SERIAL PRIMARY KEY,
    mission_id INTEGER NOT NULL REFERENCES missions(id) ON DELETE CASCADE,
    device_id VARCHAR(50) NOT NULL REFERENCES devices(device_id) ON DELETE CASCADE,
    role VARCHAR(50),  -- 'searcher', 'team_leader', 'medic', etc.
    joined_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    left_at TIMESTAMP WITH TIME ZONE,
    UNIQUE(mission_id, device_id)
);

CREATE INDEX idx_mission_participants_mission ON mission_participants(mission_id);

-- ========================================
-- CASUALTIES TABLE
-- ========================================
CREATE TABLE casualties (
    id SERIAL PRIMARY KEY,
    mission_id INTEGER REFERENCES missions(id) ON DELETE CASCADE,
    name VARCHAR(100),
    geom GEOMETRY(Point, 4326) NOT NULL,
    irish_grid_e FLOAT,  -- Easting (ITM)
    irish_grid_n FLOAT,  -- Northing (ITM)
    description TEXT,
    status VARCHAR(50),  -- 'missing', 'found', 'evacuated', etc.
    priority INTEGER DEFAULT 1,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX idx_casualties_geom ON casualties USING GIST(geom);
CREATE INDEX idx_casualties_mission ON casualties(mission_id);

-- ========================================
-- POIS TABLE (Points of Interest)
-- ========================================
CREATE TABLE pois (
    id SERIAL PRIMARY KEY,
    mission_id INTEGER REFERENCES missions(id) ON DELETE CASCADE,
    name VARCHAR(100) NOT NULL,
    geom GEOMETRY(Point, 4326) NOT NULL,
    irish_grid_e FLOAT,
    irish_grid_n FLOAT,
    poi_type VARCHAR(50),  -- 'base', 'vehicle', 'landmark', 'hazard', etc.
    description TEXT,
    color VARCHAR(7),  -- Hex color #RRGGBB
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX idx_pois_geom ON pois USING GIST(geom);
CREATE INDEX idx_pois_mission ON pois(mission_id);

-- ========================================
-- SEARCH_AREAS TABLE
-- ========================================
CREATE TABLE search_areas (
    id SERIAL PRIMARY KEY,
    mission_id INTEGER REFERENCES missions(id) ON DELETE CASCADE,
    name VARCHAR(100) NOT NULL,
    geom GEOMETRY(Polygon, 4326) NOT NULL,
    team_assigned VARCHAR(100),  -- 'Team 1', 'Team 2', 'Reserves', etc.
    color VARCHAR(7),  -- Hex color for polygon fill
    fill_opacity FLOAT DEFAULT 0.3,  -- 0.0 to 1.0
    priority INTEGER DEFAULT 1,
    status VARCHAR(50),  -- 'assigned', 'in_progress', 'completed'
    notes TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX idx_search_areas_geom ON search_areas USING GIST(geom);
CREATE INDEX idx_search_areas_mission ON search_areas(mission_id);

-- ========================================
-- GPX_TRACKS TABLE
-- ========================================
CREATE TABLE gpx_tracks (
    id SERIAL PRIMARY KEY,
    mission_id INTEGER REFERENCES missions(id) ON DELETE CASCADE,
    name VARCHAR(200) NOT NULL,
    geom GEOMETRY(LineString, 4326) NOT NULL,
    source_file VARCHAR(255),
    description TEXT,
    color VARCHAR(7),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX idx_gpx_tracks_geom ON gpx_tracks USING GIST(geom);
CREATE INDEX idx_gpx_tracks_mission ON gpx_tracks(mission_id);

-- ========================================
-- TEXT_ANNOTATIONS TABLE
-- ========================================
CREATE TABLE text_annotations (
    id SERIAL PRIMARY KEY,
    mission_id INTEGER REFERENCES missions(id) ON DELETE CASCADE,
    text TEXT NOT NULL,
    geom GEOMETRY(Point, 4326) NOT NULL,  -- Anchor point for text
    font_family VARCHAR(50) DEFAULT 'Arial',
    font_size INTEGER DEFAULT 12,
    font_color VARCHAR(7) DEFAULT '#000000',
    font_bold BOOLEAN DEFAULT FALSE,
    rotation FLOAT DEFAULT 0.0,  -- degrees
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX idx_text_annotations_geom ON text_annotations USING GIST(geom);
CREATE INDEX idx_text_annotations_mission ON text_annotations(mission_id);

-- ========================================
-- HELPER VIEWS
-- ========================================

-- View: Current positions (latest per device)
CREATE OR REPLACE VIEW current_positions AS
SELECT DISTINCT ON (device_id)
    id,
    device_id,
    timestamp,
    geom,
    altitude,
    speed,
    battery_level,
    motion
FROM positions
ORDER BY device_id, timestamp DESC;

-- View: Active mission (if any)
CREATE OR REPLACE VIEW active_mission AS
SELECT *
FROM missions
WHERE status IN ('active', 'paused')
ORDER BY start_time DESC
LIMIT 1;
```

### SpatiaLite Schema (Development Mock)

For local development, a simplified SpatiaLite schema will mirror the PostGIS structure. See `database/schema_spatialite.sql` for the conversion script.

---

## User Interface Design

### "SAR Mode" UI Philosophy

The plugin transforms QGIS into a dedicated SAR console by:

1. **Simplifying**: Hide standard QGIS toolbars (unnecessary for SAR operations)
2. **Focusing**: Prominent SAR control panel with mission-specific buttons
3. **Guiding**: Clear visual hierarchy and workflow (Start → Track → Annotate → Finish)
4. **Informing**: Real-time status indicators (connection, active rescuers, duration)

### Layout

```
┌─────────────────────────────────────────────────────────────────────────┐
│  [QGIS Menu Bar - minimal]                                              │
├─────────────────────────────────────────────────────────────────────────┤
│  [SAR Toolbar]  🔴 SAR Mode  |  🔌 Connected  |  ⏱ 02:34:15           │
├──────────────┬──────────────────────────────────────────────────────────┤
│              │                                                          │
│  SAR PANEL   │                    MAP CANVAS                            │
│  (Docked     │                                                          │
│   Left)      │                  [Interactive Map]                       │
│              │                                                          │
│  ┌─────────┐ │                  - Basemap (OSM/Topo)                   │
│  │Mission  │ │                  - Breadcrumb trails                     │
│  │Control  │ │                  - Current positions                     │
│  └─────────┘ │                  - Search areas                          │
│              │                  - Casualties/POIs                       │
│  ┌─────────┐ │                  - Text annotations                      │
│  │Tracking │ │                                                          │
│  └─────────┘ │                                                          │
│              │                                                          │
│  ┌─────────┐ │                                                          │
│  │Map Tools│ │                                                          │
│  └─────────┘ │                                                          │
│              │                                                          │
│  ┌─────────┐ │                                                          │
│  │Coords   │ │                                                          │
│  └─────────┘ │                                                          │
│              │                                                          │
│  ┌─────────┐ │                                                          │
│  │Analysis │ │                                                          │
│  └─────────┘ │                                                          │
│              │                                                          │
├──────────────┴──────────────────────────────────────────────────────────┤
│  Status Bar: E: 123456  N: 234567  |  52.2345°N, -9.1234°W  | ITM      │
└──────────────────────────────────────────────────────────────────────────┘
```

### SAR Control Panel (Detailed)

```
╔═══════════════════════════════════════════════════════════╗
║               SAR OPERATIONS CONSOLE                      ║
╠═══════════════════════════════════════════════════════════╣
║                                                           ║
║  Mission: Glenagenty Search          [⚙ Settings ▼]     ║
║  Status:  ● Active    Duration: 02:34:15                 ║
║  Rescuers: 12 active  Last Update: 5 sec ago             ║
║                                                           ║
╠═══════════════════════════════════════════════════════════╣
║  ┌─ MISSION CONTROL ───────────────────────────────┐     ║
║  │                                                  │     ║
║  │  [▶ Start New Search]      [⏸ Pause Mission]   │     ║
║  │                                                  │     ║
║  │  [▶ Resume Mission]        [⏹ Finish & Save]   │     ║
║  │                                                  │     ║
║  │  Auto-save: [5] min        Last saved: 02:31    │     ║
║  │                                                  │     ║
║  └──────────────────────────────────────────────────┘     ║
╠═══════════════════════════════════════════════════════════╣
║  ┌─ TRACKING ──────────────────────────────────────┐     ║
║  │                                                  │     ║
║  │  ☑ Show Breadcrumbs       [⚙ Style]  [🔄]      │     ║
║  │  ☑ Show Current Positions [⚙ Style]  [🔄]      │     ║
║  │                                                  │     ║
║  │  Refresh interval: [10] sec                      │     ║
║  │  Connection: ● Connected  [Test]                │     ║
║  │                                                  │     ║
║  │  [📋 View Rescuer List]                         │     ║
║  │                                                  │     ║
║  └──────────────────────────────────────────────────┘     ║
╠═══════════════════════════════════════════════════════════╣
║  ┌─ MAP TOOLS ─────────────────────────────────────┐     ║
║  │                                                  │     ║
║  │  [📍 Add Casualty Location]                     │     ║
║  │  [📌 Add Point of Interest]                     │     ║
║  │  [▭ Draw Search Area]                           │     ║
║  │  [○ Draw Circle/Arc]                            │     ║
║  │  [📏 Measure Distance & Bearing]                │     ║
║  │  [T Add Text Label]                             │     ║
║  │  [📁 Import GPX File]                           │     ║
║  │                                                  │     ║
║  └──────────────────────────────────────────────────┘     ║
╠═══════════════════════════════════════════════════════════╣
║  ┌─ COORDINATES ───────────────────────────────────┐     ║
║  │                                                  │     ║
║  │  Cursor Position:                               │     ║
║  │    Lat/Lon: 52.2345°N, -9.1234°W               │     ║
║  │    Irish Grid: E 123456  N 234567               │     ║
║  │                                                  │     ║
║  │  [⇄ Coordinate Converter Tool]                 │     ║
║  │                                                  │     ║
║  └──────────────────────────────────────────────────┘     ║
╠═══════════════════════════════════════════════════════════╣
║  ┌─ ANALYSIS & EXPORT ─────────────────────────────┐     ║
║  │                                                  │     ║
║  │  [⏮ Mission Playback]                           │     ║
║  │  [📊 Generate Report]                           │     ║
║  │  [🗺 Export Map (PDF/PNG)]                      │     ║
║  │                                                  │     ║
║  └──────────────────────────────────────────────────┘     ║
╠═══════════════════════════════════════════════════════════╣
║                                                           ║
║  [🔌 Database: Connected]            [ℹ Help]  [✕]      ║
║                                                           ║
╚═══════════════════════════════════════════════════════════╝
```

### Color Scheme & Branding

**Irish Mountain Rescue Theme:**
- **Primary**: Orange/Red (`#FF6B35`) - High visibility, emergency services
- **Secondary**: Navy Blue (`#004E89`) - Professional, trustworthy
- **Accent**: Green (`#2A9D8F`) - Irish identity
- **Neutral**: Light grey background (`#F7F7F7`), dark grey text (`#2B2B2B`)

**Status Colors:**
- Active Mission: Green (`#28A745`)
- Paused Mission: Orange (`#FFC107`)
- Completed Mission: Grey (`#6C757D`)
- Error/Disconnected: Red (`#DC3545`)
- Connected: Green (`#28A745`)

**Map Layer Colors:**
- Breadcrumbs: Categorized by device (rainbow spectrum)
- Current Positions: Match breadcrumb colors, larger symbols
- Casualty: Red marker (`#DC3545`)
- POI: Blue marker (`#007BFF`)
- Search Areas: Semi-transparent team colors (red, blue, purple, green)
- Base: Orange marker (`#FF6B35`)

### Dialogs & Secondary Windows

**1. Settings Dialog**
- Database connection settings (host, port, username, password, database name)
- Auto-refresh interval (1-60 seconds)
- Auto-save interval (1-60 minutes)
- Default CRS (ITM/TM65/WGS84)
- UI theme/colors
- Test connection button

**2. Start Mission Dialog**
- Mission name (text input)
- Start date/time (defaults to now, editable)
- Notes (text area)
- Participants selection (checkbox list from devices table)

**3. Coordinate Converter Dialog**
- Input: Irish Grid E/N OR Lat/Lon
- Output: Both formats displayed
- [Convert] button
- [Copy to Clipboard] buttons
- [Go to Location on Map] button

**4. Mission Playback Dialog**
- Time slider (scrub through mission timeline)
- Play/Pause/Stop controls
- Speed control (0.5x, 1x, 2x, 5x)
- Time display (current playback time)
- Toggle layers on/off during playback

**5. Report Generation Dialog**
- Mission summary (name, duration, participants count)
- Participants table (name, total distance, time active, max speed, avg speed)
- Search area coverage (list of areas with assigned teams)
- Export format: CSV, PDF
- [Generate Report] button

**6. Add Casualty/POI Dialog**
- Name (text input)
- Input method:
  - ○ Irish Grid Coordinates (E/N numeric inputs)
  - ○ Lat/Lon Coordinates (decimal degree inputs)
  - ○ Click on Map (activates map tool)
- Description (text area)
- [Add to Map] button

**7. Draw Search Area Dialog**
- Area name (text input)
- Team assigned (dropdown or text)
- Color picker
- Digitize on map (polygon tool)
- [Save Area] button

---

## Implementation Phases

### Phase 1: Core Tracking & Mission Lifecycle (Weeks 1-2)

**Goals**: Implement MVP features that allow operators to track rescuers in real-time and manage mission lifecycle.

**Features**:
- ✅ 01: Breadcrumb trails
- ✅ 02: Current locations
- ✅ 03: Start search
- ✅ 04: Pause search
- ✅ 05: Resume search
- ✅ 06: Finish/save search
- ✅ 07: Auto-resume on launch
- ✅ 08: Auto-save project

**Deliverables**:
- PostGISProvider class (connects to database)
- SpatiaLiteProvider class (local dev mock)
- LayersController (creates/updates tracking layers)
- MissionController (handles mission lifecycle)
- PanelController (wires UI to logic)
- SAR Panel UI (basic mission controls + tracking section)
- Database schema scripts (PostGIS + SpatiaLite)
- Auto-refresh QTimer
- Auto-save QTimer

**Acceptance Criteria**:
- Can connect to PostGIS database (or local SpatiaLite mock)
- Can start new mission, pause, resume, finish
- Breadcrumb trails display correctly (time-ordered, color-coded per rescuer)
- Current positions update every 10 seconds
- Auto-save works at defined interval
- On QGIS launch, detects paused mission and prompts to resume

---

### Phase 2: Operational Tools (Weeks 3-4)

**Goals**: Add essential SAR tools for marking casualties, points of interest, and coordinate conversion.

**Features**:
- ✅ 09: Add casualty
- ✅ 10: Add POI
- ✅ 11: Coordinate converter
- ✅ 14: Cursor coordinates
- ✅ 15: Measure distance/bearing

**Deliverables**:
- CasualtyMapTool (click-to-place or input Irish Grid)
- POIMapTool (click-to-place or input Irish Grid)
- CoordinateConverter dialog
- MeasureTool (distance and bearing between 2 points)
- Real-time cursor coordinate display in status bar
- Coordinate conversion utilities (Irish Grid ↔ WGS84)
- Add Casualty/POI dialogs

**Acceptance Criteria**:
- Can add casualty by clicking map or entering Irish Grid coords
- Can add POI by clicking map or entering Irish Grid coords
- Casualty and POI markers save to database
- Coordinate converter accurately converts between ITM and WGS84
- Cursor position displays in both coordinate systems
- Measure tool shows distance (meters/km) and bearing (degrees)

---

### Phase 3: Mapping & Areas (Weeks 5-6)

**Goals**: Implement polygon search areas, text annotations, circles/arcs, and GPX import.

**Features**:
- ✅ 12: Import GPX files
- ✅ 13: Draw search areas
- ✅ 16: Add text to shaded areas
- ✅ 17: Draw circles/arcs
- ✅ 18: Add text to map

**Deliverables**:
- DigitizePolygonTool (draw search areas)
- CircleArcTool (draw circles from center point)
- TextAnnotationTool (place text on map)
- GPX import functionality (parse GPX, load as LineString layer)
- Search area styling (team colors, semi-transparent fills)
- Text annotation styling (fonts, colors, rotation)

**Acceptance Criteria**:
- Can draw polygon search areas and assign to teams
- Search areas save to database with colors/teams
- Can draw circles from a point with specified radius
- Can place text annotations anywhere on map
- Can import GPX files and display as tracks
- GPX tracks save to database

---

### Phase 4: Analysis & Export (Weeks 7-8)

**Goals**: Implement mission playback, report generation, and professional map exports.

**Features**:
- ✅ 19: Mission playback
- ✅ 20: Generate reports
- ✅ Professional map export

**Deliverables**:
- PlaybackController (time-slider, animation)
- ReportGenerator (mission metrics, participant stats)
- MapExporter (uses QGIS Print Composer / Layout Manager)
- Playback dialog
- Report generation dialog
- Professional map templates (scale bar, north arrow, legend, QR code)

**Acceptance Criteria**:
- Can replay past missions with time slider
- Playback shows rescuer movement over time
- Can generate mission report (participants, distances, durations)
- Report exports to CSV/PDF
- Can export professional maps (PDF/PNG) with all cartographic elements
- Maps match quality of client's example PDFs

---

## Technical Implementation Details

### Key PyQGIS APIs

**Layer Management:**
- `QgsVectorLayer` - Create memory layers or database-backed layers
- `QgsProject.instance()` - Project singleton for layer tree access
- `QgsLayerTreeNode` / `QgsLayerTreeGroup` - Organize layers in groups
- `QgsFeature` / `QgsGeometry` - Feature and geometry creation

**Database:**
- `QgsDataSourceUri` - Build connection strings for PostGIS
- `QgsVectorLayer("Polygon?crs=EPSG:4326", "LayerName", "postgres")` - PostGIS layer

**Coordinate Systems:**
- `QgsCoordinateReferenceSystem("EPSG:4326")` - WGS84
- `QgsCoordinateReferenceSystem("EPSG:29903")` - ITM (Irish Transverse Mercator)
- `QgsCoordinateTransform` - Transform coordinates between CRS

**Styling:**
- `QgsCategorizedSymbolRenderer` - Color by device_id
- `QgsMarkerSymbol` - Point symbol configuration
- `QgsLineSymbol` - Line symbol configuration
- `QgsFillSymbol` - Polygon fill configuration
- `QgsPalLayerSettings` - Label configuration

**UI:**
- `QgsDockWidget` - Dockable panel
- `QgsMapTool` - Custom map tools (click, digitize, measure)
- `QgsMessageBar` - User notifications
- `QTimer` - Auto-refresh and auto-save timers
- `QgsSettings` - Plugin configuration persistence

**Map Composer:**
- `QgsLayoutManager` - Manage print layouts
- `QgsLayout` - Print layout definition
- `QgsLayoutItemMap` - Map item in layout
- `QgsLayoutItemScaleBar` - Scale bar
- `QgsLayoutItemPicture` - North arrow, logos
- `QgsLayoutItemLabel` - Text labels
- `QgsLayoutItemLegend` - Legend
- `QgsLayoutExporter` - Export to PDF/PNG

### Provider Implementation

**PostGISProvider (Production):**

```python
import psycopg2
from psycopg2.extras import RealDictCursor
from qgis.core import QgsGeometry, QgsPointXY, QgsCoordinateReferenceSystem
from typing import List, Dict, Optional
from .base import Provider, FeatureDict

class PostGISProvider(Provider):
    def __init__(self, host: str, port: int, database: str,
                 user: str, password: str):
        self.host = host
        self.port = port
        self.database = database
        self.user = user
        self.password = password
        self.conn = None
        self.last_connection_attempt = None
        self.connection_failed = False

    def connect(self):
        """Establish database connection"""
        try:
            self.conn = psycopg2.connect(
                host=self.host,
                port=self.port,
                database=self.database,
                user=self.user,
                password=self.password,
                connect_timeout=5
            )
            self.connection_failed = False
            return True
        except Exception as e:
            self.connection_failed = True
            raise RuntimeError(f"Database connection failed: {str(e)}")

    def get_current(self) -> List[FeatureDict]:
        """Get latest position per device from current_positions view"""
        if not self.conn or self.conn.closed:
            self.connect()

        try:
            with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT
                        p.device_id,
                        d.name,
                        p.timestamp,
                        ST_X(p.geom) as lon,
                        ST_Y(p.geom) as lat,
                        p.altitude,
                        p.speed,
                        p.battery_level
                    FROM current_positions p
                    JOIN devices d ON p.device_id = d.device_id
                    WHERE d.status = 'online'
                    ORDER BY p.timestamp DESC
                """)

                results = []
                for row in cur.fetchall():
                    results.append({
                        'device_id': row['device_id'],
                        'name': row['name'],
                        'lat': row['lat'],
                        'lon': row['lon'],
                        'ts': row['timestamp'].isoformat(),
                        'altitude': row['altitude'],
                        'speed': row['speed'],
                        'battery': row['battery_level']
                    })
                return results
        except Exception as e:
            raise RuntimeError(f"Failed to fetch current positions: {str(e)}")

    def get_breadcrumbs(self, since_iso: Optional[str] = None,
                        mission_id: Optional[int] = None) -> List[FeatureDict]:
        """Get breadcrumb trail for all devices"""
        if not self.conn or self.conn.closed:
            self.connect()

        # Build time filter
        time_filter = ""
        params = []
        if since_iso:
            time_filter = "AND p.timestamp >= %s"
            params.append(since_iso)
        elif mission_id:
            # Get breadcrumbs for specific mission timeframe
            time_filter = """
                AND p.timestamp >= (SELECT start_time FROM missions WHERE id = %s)
                AND (p.timestamp <= (SELECT end_time FROM missions WHERE id = %s)
                     OR (SELECT end_time FROM missions WHERE id = %s) IS NULL)
            """
            params.extend([mission_id, mission_id, mission_id])
        else:
            # Default: last 3 hours
            time_filter = "AND p.timestamp >= NOW() - INTERVAL '3 hours'"

        try:
            with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
                query = f"""
                    SELECT
                        p.device_id,
                        d.name,
                        p.timestamp,
                        ST_X(p.geom) as lon,
                        ST_Y(p.geom) as lat,
                        p.altitude,
                        p.speed,
                        p.battery_level
                    FROM positions p
                    JOIN devices d ON p.device_id = d.device_id
                    WHERE 1=1 {time_filter}
                    ORDER BY p.device_id, p.timestamp ASC
                """
                cur.execute(query, params)

                results = []
                for row in cur.fetchall():
                    results.append({
                        'device_id': row['device_id'],
                        'name': row['name'],
                        'lat': row['lat'],
                        'lon': row['lon'],
                        'ts': row['timestamp'].isoformat(),
                        'altitude': row['altitude'],
                        'speed': row['speed'],
                        'battery': row['battery_level']
                    })
                return results
        except Exception as e:
            raise RuntimeError(f"Failed to fetch breadcrumbs: {str(e)}")

    def save_casualty(self, mission_id: int, name: str,
                     lat: float, lon: float,
                     irish_grid_e: float, irish_grid_n: float,
                     description: str) -> int:
        """Save casualty location to database"""
        if not self.conn or self.conn.closed:
            self.connect()

        try:
            with self.conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO casualties
                        (mission_id, name, geom, irish_grid_e, irish_grid_n, description)
                    VALUES
                        (%s, %s, ST_SetSRID(ST_MakePoint(%s, %s), 4326), %s, %s, %s)
                    RETURNING id
                """, (mission_id, name, lon, lat, irish_grid_e, irish_grid_n, description))
                casualty_id = cur.fetchone()[0]
                self.conn.commit()
                return casualty_id
        except Exception as e:
            self.conn.rollback()
            raise RuntimeError(f"Failed to save casualty: {str(e)}")

    # ... additional methods for save_poi, save_search_area, etc.
```

### Layer Management

**LayersController:**

```python
from qgis.core import (
    QgsVectorLayer, QgsProject, QgsFeature, QgsGeometry,
    QgsPointXY, QgsField, QgsCategorizedSymbolRenderer,
    QgsRendererCategory, QgsMarkerSymbol, QgsLineSymbol,
    QgsPalLayerSettings, QgsVectorLayerSimpleLabeling
)
from qgis.PyQt.QtCore import QVariant
from qgis.PyQt.QtGui import QColor
from typing import List, Dict
import random

class LayersController:
    LAYER_GROUP_NAME = "SAR Tracking"
    CURRENT_LAYER_NAME = "Current Positions"
    BREADCRUMBS_LAYER_NAME = "Breadcrumbs"

    def __init__(self, iface):
        self.iface = iface
        self.project = QgsProject.instance()

    def get_or_create_layer_group(self) -> QgsLayerTreeGroup:
        """Get or create SAR Tracking layer group"""
        root = self.project.layerTreeRoot()
        group = root.findGroup(self.LAYER_GROUP_NAME)
        if not group:
            group = root.insertGroup(0, self.LAYER_GROUP_NAME)
        return group

    def update_current_positions(self, positions: List[Dict]):
        """Update current positions layer"""
        # Get or create layer
        layer = self._get_or_create_current_layer()

        # Clear existing features
        layer.startEditing()
        layer.deleteFeatures([f.id() for f in layer.getFeatures()])

        # Add new features
        for pos in positions:
            feature = QgsFeature(layer.fields())
            feature.setGeometry(
                QgsGeometry.fromPointXY(
                    QgsPointXY(pos['lon'], pos['lat'])
                )
            )
            feature.setAttributes([
                pos['device_id'],
                pos['name'],
                pos['ts'],
                pos.get('altitude'),
                pos.get('speed'),
                pos.get('battery')
            ])
            layer.addFeature(feature)

        layer.commitChanges()

        # Apply styling
        self._apply_current_positions_style(layer)

        # Refresh
        layer.triggerRepaint()

    def _get_or_create_current_layer(self) -> QgsVectorLayer:
        """Get or create current positions layer"""
        # Check if exists
        layers = self.project.mapLayersByName(self.CURRENT_LAYER_NAME)
        if layers:
            return layers[0]

        # Create new memory layer
        layer = QgsVectorLayer(
            "Point?crs=EPSG:4326",
            self.CURRENT_LAYER_NAME,
            "memory"
        )

        # Add fields
        provider = layer.dataProvider()
        provider.addAttributes([
            QgsField("device_id", QVariant.String),
            QgsField("name", QVariant.String),
            QgsField("timestamp", QVariant.String),
            QgsField("altitude", QVariant.Double),
            QgsField("speed", QVariant.Double),
            QgsField("battery", QVariant.Double)
        ])
        layer.updateFields()

        # Add to project in SAR group
        group = self.get_or_create_layer_group()
        self.project.addMapLayer(layer, False)
        group.insertLayer(0, layer)

        return layer

    def _apply_current_positions_style(self, layer: QgsVectorLayer):
        """Apply categorized style to current positions"""
        # Get unique device IDs
        device_ids = layer.uniqueValues(
            layer.fields().indexOf('device_id')
        )

        # Create categories with random colors
        categories = []
        for device_id in device_ids:
            color = QColor(
                random.randint(100, 255),
                random.randint(100, 255),
                random.randint(100, 255)
            )
            symbol = QgsMarkerSymbol.createSimple({
                'name': 'circle',
                'color': color.name(),
                'size': '4',
                'outline_color': 'black',
                'outline_width': '0.5'
            })
            category = QgsRendererCategory(device_id, symbol, str(device_id))
            categories.append(category)

        renderer = QgsCategorizedSymbolRenderer('device_id', categories)
        layer.setRenderer(renderer)

        # Apply labels
        label_settings = QgsPalLayerSettings()
        label_settings.fieldName = 'name'
        label_settings.enabled = True

        text_format = QgsTextFormat()
        text_format.setSize(10)
        text_format.setColor(QColor('black'))
        text_format.buffer().setEnabled(True)
        text_format.buffer().setColor(QColor('white'))
        text_format.buffer().setSize(1)
        label_settings.setFormat(text_format)

        labeling = QgsVectorLayerSimpleLabeling(label_settings)
        layer.setLabeling(labeling)
        layer.setLabelsEnabled(True)

    def update_breadcrumbs(self, positions: List[Dict],
                          time_gap_minutes: int = 5):
        """Update breadcrumb trails layer"""
        # Get or create layer
        layer = self._get_or_create_breadcrumbs_layer()

        # Clear existing features
        layer.startEditing()
        layer.deleteFeatures([f.id() for f in layer.getFeatures()])

        # Group positions by device_id
        from collections import defaultdict
        from datetime import datetime, timedelta

        device_positions = defaultdict(list)
        for pos in positions:
            device_positions[pos['device_id']].append(pos)

        # Create line segments per device
        for device_id, device_pts in device_positions.items():
            # Sort by timestamp
            device_pts.sort(key=lambda p: p['ts'])

            # Break into segments on time gaps
            segments = []
            current_segment = []

            for i, pos in enumerate(device_pts):
                if i == 0:
                    current_segment.append(pos)
                else:
                    prev_time = datetime.fromisoformat(
                        device_pts[i-1]['ts'].replace('Z', '+00:00')
                    )
                    curr_time = datetime.fromisoformat(
                        pos['ts'].replace('Z', '+00:00')
                    )
                    time_diff = (curr_time - prev_time).total_seconds() / 60

                    if time_diff > time_gap_minutes:
                        # Save current segment, start new
                        if len(current_segment) > 1:
                            segments.append(current_segment)
                        current_segment = [pos]
                    else:
                        current_segment.append(pos)

            # Add final segment
            if len(current_segment) > 1:
                segments.append(current_segment)

            # Create features for each segment
            device_name = device_pts[0]['name']
            for segment in segments:
                points = [
                    QgsPointXY(p['lon'], p['lat']) for p in segment
                ]
                geom = QgsGeometry.fromPolylineXY(points)

                feature = QgsFeature(layer.fields())
                feature.setGeometry(geom)
                feature.setAttributes([device_id, device_name])
                layer.addFeature(feature)

        layer.commitChanges()

        # Apply styling
        self._apply_breadcrumbs_style(layer)

        # Refresh
        layer.triggerRepaint()

    def _get_or_create_breadcrumbs_layer(self) -> QgsVectorLayer:
        """Get or create breadcrumbs layer"""
        layers = self.project.mapLayersByName(self.BREADCRUMBS_LAYER_NAME)
        if layers:
            return layers[0]

        layer = QgsVectorLayer(
            "LineString?crs=EPSG:4326",
            self.BREADCRUMBS_LAYER_NAME,
            "memory"
        )

        provider = layer.dataProvider()
        provider.addAttributes([
            QgsField("device_id", QVariant.String),
            QgsField("name", QVariant.String)
        ])
        layer.updateFields()

        group = self.get_or_create_layer_group()
        self.project.addMapLayer(layer, False)
        group.insertLayer(1, layer)

        return layer

    def _apply_breadcrumbs_style(self, layer: QgsVectorLayer):
        """Apply categorized style to breadcrumbs"""
        device_ids = layer.uniqueValues(
            layer.fields().indexOf('device_id')
        )

        categories = []
        for device_id in device_ids:
            color = QColor(
                random.randint(100, 255),
                random.randint(100, 255),
                random.randint(100, 255)
            )
            symbol = QgsLineSymbol.createSimple({
                'color': color.name(),
                'width': '2',
                'line_style': 'solid',
                'joinstyle': 'round',
                'capstyle': 'round'
            })
            category = QgsRendererCategory(device_id, symbol, str(device_id))
            categories.append(category)

        renderer = QgsCategorizedSymbolRenderer('device_id', categories)
        layer.setRenderer(renderer)
```

### Auto-Refresh Implementation

```python
from qgis.PyQt.QtCore import QTimer

class AutoRefreshController:
    def __init__(self, provider, layers_controller, interval_seconds=10):
        self.provider = provider
        self.layers_controller = layers_controller
        self.interval_seconds = interval_seconds
        self.timer = QTimer()
        self.timer.timeout.connect(self.refresh)
        self.is_running = False

    def start(self):
        """Start auto-refresh timer"""
        if not self.is_running:
            self.timer.start(self.interval_seconds * 1000)
            self.is_running = True
            self.refresh()  # Immediate refresh

    def stop(self):
        """Stop auto-refresh timer"""
        if self.is_running:
            self.timer.stop()
            self.is_running = False

    def set_interval(self, seconds: int):
        """Change refresh interval"""
        self.interval_seconds = seconds
        if self.is_running:
            self.timer.setInterval(seconds * 1000)

    def refresh(self):
        """Refresh current positions and breadcrumbs"""
        try:
            # Get current positions
            current = self.provider.get_current()
            self.layers_controller.update_current_positions(current)

            # Get breadcrumbs (last 3 hours)
            breadcrumbs = self.provider.get_breadcrumbs()
            self.layers_controller.update_breadcrumbs(breadcrumbs)

        except Exception as e:
            # Log error but don't crash
            print(f"Auto-refresh error: {str(e)}")
```

### Coordinate Conversion Utilities

```python
from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsPointXY,
    QgsProject
)

class CoordinateConverter:
    """Convert between Irish Grid (ITM) and WGS84"""

    def __init__(self):
        self.wgs84 = QgsCoordinateReferenceSystem("EPSG:4326")
        self.itm = QgsCoordinateReferenceSystem("EPSG:29903")
        self.project = QgsProject.instance()

    def irish_grid_to_wgs84(self, easting: float, northing: float):
        """Convert Irish Grid (ITM) to WGS84 Lat/Lon"""
        transform = QgsCoordinateTransform(
            self.itm,
            self.wgs84,
            self.project
        )
        point = QgsPointXY(easting, northing)
        transformed = transform.transform(point)
        return transformed.y(), transformed.x()  # lat, lon

    def wgs84_to_irish_grid(self, lat: float, lon: float):
        """Convert WGS84 Lat/Lon to Irish Grid (ITM)"""
        transform = QgsCoordinateTransform(
            self.wgs84,
            self.itm,
            self.project
        )
        point = QgsPointXY(lon, lat)
        transformed = transform.transform(point)
        return transformed.x(), transformed.y()  # easting, northing
```

---

## Development Strategy

### Local Development Environment

**Mock Database Setup:**

1. Create SpatiaLite database with same schema as PostGIS
2. Populate with sample data from Glenagenty.csv
3. Use SpatiaLiteProvider for local testing
4. Provides `dev_tools/create_mock_db.py` script

**Testing Without Server:**

- SpatiaLite database: `sartracker_dev.sqlite`
- Sample missions with realistic data
- All CRUD operations work locally
- Easy to reset/recreate for testing

### Project Structure

```
sartracker/
├── __init__.py                    # Plugin bootstrap
├── sartracker.py                  # Main plugin class
├── metadata.txt                   # QGIS plugin metadata
├── icon.png                       # Plugin icon (SAR orange/red)
│
├── providers/
│   ├── __init__.py
│   ├── base.py                    # Provider ABC
│   ├── postgis.py                 # PostGIS provider (production)
│   └── spatialite.py              # SpatiaLite provider (dev)
│
├── controllers/
│   ├── __init__.py
│   ├── layers_controller.py       # Layer creation & styling
│   ├── panel_controller.py        # SAR Panel UI logic
│   ├── mission_controller.py      # Mission lifecycle
│   ├── autorefresh_controller.py  # Auto-refresh timer
│   ├── autosave_controller.py     # Auto-save timer
│   └── maptools_controller.py     # Map tool coordinator
│
├── ui/
│   ├── __init__.py
│   ├── sar_panel.py               # Main SAR control panel
│   ├── settings_dialog.py         # Settings dialog
│   ├── start_mission_dialog.py    # Start mission dialog
│   ├── coordinate_converter.py    # Coordinate converter dialog
│   ├── add_casualty_dialog.py     # Add casualty dialog
│   ├── add_poi_dialog.py          # Add POI dialog
│   ├── draw_area_dialog.py        # Draw search area dialog
│   ├── playback_dialog.py         # Mission playback dialog
│   └── report_dialog.py           # Report generation dialog
│
├── maptools/
│   ├── __init__.py
│   ├── casualty_tool.py           # Click-to-place casualty
│   ├── poi_tool.py                # Click-to-place POI
│   ├── measure_tool.py            # Measure distance/bearing
│   ├── digitize_polygon_tool.py   # Draw search areas
│   ├── circle_tool.py             # Draw circles/arcs
│   └── text_tool.py               # Place text annotations
│
├── utils/
│   ├── __init__.py
│   ├── config.py                  # QgsSettings wrapper
│   ├── coordinates.py             # Coordinate conversion
│   ├── styling.py                 # Layer styling helpers
│   ├── export.py                  # Map export utilities
│   └── network.py                 # Connection status checker
│
├── resources/
│   ├── icons/                     # UI icons (SVG/PNG)
│   ├── styles/                    # QML style templates
│   └── templates/                 # Print layout templates
│
├── database/
│   ├── schema_postgis.sql         # Production database schema
│   ├── schema_spatialite.sql      # Development mock schema
│   ├── views.sql                  # Database views
│   └── sample_data.sql            # Sample data for testing
│
├── dev_tools/
│   ├── create_mock_db.py          # Create SpatiaLite mock DB
│   ├── populate_glenagenty.py     # Import Glenagenty.csv data
│   ├── test_connection.py         # Test PostGIS connection
│   └── generate_sample_mission.py # Generate realistic test data
│
├── tests/
│   ├── test_providers.py
│   ├── test_coordinates.py
│   ├── test_layers.py
│   └── test_mission_lifecycle.py
│
└── docs/
    ├── SETUP.md                   # Installation & setup
    ├── DATABASE_SETUP.md          # Database configuration
    ├── USER_GUIDE.md              # User guide
    ├── DEVELOPER_GUIDE.md         # Developer documentation
    └── ARCHITECTURE.md            # Architecture overview
```

### Plugin Metadata

**metadata.txt:**

```ini
[general]
name=SAR Tracker
qgisMinimumVersion=3.40
qgisMaximumVersion=3.99
description=Search & Rescue operations console for real-time tracking and mission management
version=1.0.0
author=Your Name / Claude Code
email=contact@example.com

about=SAR Tracker transforms QGIS into a dedicated Search & Rescue operations console.
    Designed for Kerry Mountain Rescue Team, it provides real-time tracking of rescue
    personnel, mission lifecycle management, map annotation tools, and professional
    cartographic output—all in a simplified interface that hides QGIS complexity.

    Features:
    - Real-time GPS tracking with breadcrumb trails
    - Mission start/pause/resume/finish workflow
    - Add casualties and points of interest
    - Draw and assign search areas
    - Measure distance and bearing
    - Import GPX files
    - Mission playback and reporting
    - Professional map exports

    Connects to PostgreSQL/PostGIS database for live data.

tracker=https://github.com/yourusername/sar-tracker/issues
repository=https://github.com/yourusername/sar-tracker
tags=search and rescue,SAR,emergency,tracking,GPS,mountain rescue,PostGIS

homepage=https://github.com/yourusername/sar-tracker
category=Web
icon=icon.png
experimental=False
deprecated=False

hasProcessingProvider=no
server=False
```

---

## Testing & Quality Assurance

### Unit Tests

**Test Coordinate Conversion:**
```python
def test_irish_grid_to_wgs84():
    converter = CoordinateConverter()
    # Known point: GPO Dublin
    easting = 715830
    northing = 734697
    lat, lon = converter.irish_grid_to_wgs84(easting, northing)
    assert abs(lat - 53.3498) < 0.001
    assert abs(lon - (-6.2603)) < 0.001
```

**Test Provider Queries:**
```python
def test_postgis_provider_get_current():
    provider = PostGISProvider(...)
    current = provider.get_current()
    assert isinstance(current, list)
    assert all('device_id' in pos for pos in current)
    assert all('lat' in pos and 'lon' in pos for pos in current)
```

**Test Mission Lifecycle:**
```python
def test_mission_start_pause_resume():
    controller = MissionController(...)
    mission_id = controller.start_mission("Test Mission")
    assert controller.get_active_mission() == mission_id

    controller.pause_mission()
    assert controller.get_mission_status() == 'paused'

    controller.resume_mission()
    assert controller.get_mission_status() == 'active'
```

### Integration Tests

**Test Full Tracking Workflow:**
1. Connect to mock SpatiaLite database
2. Start new mission
3. Fetch current positions (should show sample data)
4. Update layers (should create SAR / Current layer)
5. Fetch breadcrumbs
6. Update layers (should create SAR / Breadcrumbs layer)
7. Verify layer styling applied
8. Verify labels displayed

**Test Database Operations:**
1. Add casualty via dialog
2. Verify saved to database
3. Verify appears on map
4. Add POI
5. Draw search area
6. Verify all saved to database

### User Acceptance Testing

**Test Scenarios:**

1. **New Mission Start**
   - User starts QGIS
   - Plugin loads
   - User clicks "Start New Search"
   - Enters mission name
   - Selects participants
   - Map shows tracking layers

2. **Real-Time Tracking**
   - Breadcrumb trails update
   - Current positions update every 10 sec
   - Colors are unique per rescuer
   - Labels show names

3. **Add Casualty**
   - User clicks "Add Casualty"
   - Clicks on map
   - Casualty marker appears
   - Red icon displayed
   - Saved to database

4. **Mission Pause/Resume**
   - User clicks "Pause"
   - Tracking stops
   - User closes QGIS
   - Reopens QGIS
   - Plugin prompts to resume
   - User clicks "Resume"
   - Tracking resumes from pause point

5. **Export Map**
   - User clicks "Export Map"
   - Selects PDF
   - Map exports with scale bar, north arrow, legend
   - Quality matches example PDFs

---

## Deployment & Handoff

### Server Setup (Team Responsibility)

**PostgreSQL/PostGIS Installation:**
1. Install PostgreSQL 14+ and PostGIS 3+
2. Create database: `CREATE DATABASE sartracker;`
3. Enable PostGIS: `CREATE EXTENSION postgis;`
4. Run schema script: `psql -d sartracker -f database/schema_postgis.sql`
5. Create user: `CREATE USER sar_operator WITH PASSWORD 'secure_password';`
6. Grant permissions: `GRANT SELECT ON ALL TABLES TO sar_operator;`
7. Grant write on specific tables: `GRANT INSERT, UPDATE ON casualties, pois, search_areas, text_annotations, gpx_tracks TO sar_operator;`

**Traccar → PostGIS Integration:**

Option A: Traccar writes directly to PostGIS (configure in Traccar settings)

Option B: Modified Python script (replace CSV export):

```python
# traccar_to_postgis.py
import psycopg2
import requests
from datetime import datetime

# Database connection
conn = psycopg2.connect(
    host='localhost',
    database='sartracker',
    user='traccar_writer',
    password='...'
)

# Traccar API
TRACCAR_URL = 'http://localhost:8082/api'
USERNAME = 'apiuser'
PASSWORD = '...'

# Fetch devices
devices = requests.get(
    f'{TRACCAR_URL}/devices',
    auth=(USERNAME, PASSWORD)
).json()

# Upsert devices
with conn.cursor() as cur:
    for device in devices:
        cur.execute("""
            INSERT INTO devices (device_id, name, status, last_update)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (device_id) DO UPDATE SET
                name = EXCLUDED.name,
                status = EXCLUDED.status,
                last_update = EXCLUDED.last_update
        """, (device['id'], device['name'], device['status'], datetime.now()))

# Fetch and insert positions
from_time = (datetime.now() - timedelta(minutes=5)).isoformat() + 'Z'
to_time = datetime.now().isoformat() + 'Z'

for device in devices:
    positions = requests.get(
        f'{TRACCAR_URL}/reports/route',
        auth=(USERNAME, PASSWORD),
        params={'deviceId': device['id'], 'from': from_time, 'to': to_time}
    ).json()

    with conn.cursor() as cur:
        for pos in positions:
            cur.execute("""
                INSERT INTO positions
                    (device_id, timestamp, geom, altitude, speed, battery_level)
                VALUES
                    (%s, %s, ST_SetSRID(ST_MakePoint(%s, %s), 4326), %s, %s, %s)
                ON CONFLICT DO NOTHING
            """, (
                device['id'],
                pos['fixTime'],
                pos['longitude'],
                pos['latitude'],
                pos.get('altitude'),
                pos.get('speed'),
                pos.get('attributes', {}).get('batteryLevel')
            ))

conn.commit()
conn.close()
```

Run this script every 10-30 seconds via cron/systemd timer.

### Plugin Installation (Operator Workstation)

**Method 1: QGIS Plugin Manager (Future)**
1. Open QGIS
2. Go to Plugins → Manage and Install Plugins
3. Search "SAR Tracker"
4. Click Install

**Method 2: Manual Installation (Now)**
1. Download `sartracker.zip`
2. Extract to QGIS plugins folder:
   - Windows: `C:\Users\USERNAME\AppData\Roaming\QGIS\QGIS3\profiles\default\python\plugins\`
   - Mac: `~/Library/Application Support/QGIS/QGIS3/profiles/default/python/plugins/`
   - Linux: `~/.local/share/QGIS/QGIS3/profiles/default/python/plugins/`
3. Restart QGIS
4. Go to Plugins → Manage and Install Plugins → Installed
5. Enable "SAR Tracker"

### Configuration

**First Launch:**
1. Plugin loads
2. Shows settings dialog (no database configured)
3. User enters:
   - Database host (server IP or domain)
   - Port (5432)
   - Database name (sartracker)
   - Username (sar_operator)
   - Password
4. Click "Test Connection"
5. If successful, click "Save"
6. SAR Panel appears

**Recommended QGIS Settings:**
- Project CRS: EPSG:29903 (ITM - Irish Grid)
- Enable "on the fly" CRS transformation
- Basemap: OpenStreetMap or Irish OSi tiles (if available)

### Documentation Deliverables

1. **SETUP.md**
   - Installation instructions
   - Database setup guide
   - Traccar integration guide
   - Troubleshooting

2. **USER_GUIDE.md**
   - Complete feature walkthrough
   - Mission workflow
   - Map tools guide
   - Export and reporting
   - Screenshots

3. **DEVELOPER_GUIDE.md**
   - Architecture overview
   - Provider implementation
   - Adding new features
   - Testing guide

4. **VIDEO_TUTORIAL.mp4**
   - 10-minute screencast showing:
     - Plugin installation
     - Starting a mission
     - Real-time tracking
     - Adding casualties/POIs
     - Drawing search areas
     - Exporting maps
     - Finishing mission

---

## Success Criteria

### Phase 1 Success Criteria

✅ Plugin installs without errors
✅ Connects to PostGIS database (or local SpatiaLite mock)
✅ Can start new mission with name and start time
✅ Breadcrumb trails display correctly (time-ordered, color-coded)
✅ Current positions update every 10 seconds
✅ Can pause mission (stops tracking)
✅ Can resume mission (restarts tracking)
✅ Can finish mission (saves final state)
✅ Auto-save works at defined interval
✅ On QGIS relaunch, detects paused mission and prompts to resume

### Phase 2 Success Criteria

✅ Can add casualty by clicking map or entering Irish Grid coordinates
✅ Can add POI by clicking map or entering Irish Grid coordinates
✅ Casualty and POI markers save to database and persist
✅ Coordinate converter accurately converts ITM ↔ WGS84
✅ Cursor position displays in both coordinate systems in real-time
✅ Measure tool shows distance (meters/km) and bearing (degrees)

### Phase 3 Success Criteria

✅ Can draw polygon search areas on map
✅ Can assign search areas to teams with colors
✅ Search areas save to database
✅ Can draw circles from a point with specified radius
✅ Can place text annotations on map
✅ Can import GPX files and display as tracks
✅ GPX tracks save to database

### Phase 4 Success Criteria

✅ Mission playback works with time slider
✅ Playback shows rescuer movement over time
✅ Can generate mission report with participant stats
✅ Report includes: names, distances traveled, durations
✅ Can export professional maps (PDF/PNG)
✅ Exported maps include: scale bar, north arrow, legend, title, projection info
✅ Map quality matches client's example PDFs

### Overall Success Criteria

✅ Plugin is cross-platform (Windows, Mac, Linux)
✅ Handles spotty network gracefully (shows last known positions, reconnects automatically)
✅ Simple enough for non-GIS users (SAR team members)
✅ Professional appearance (impresses the team)
✅ Completely replaces existing proof-of-concept CSV workflow
✅ Documentation is complete and clear
✅ Team can deploy and use independently

---

## Appendix

### Glossary

- **SAR**: Search and Rescue
- **KMRT**: Kerry Mountain Rescue Team
- **EOC**: Emergency Operations Center
- **ITM**: Irish Transverse Mercator (EPSG:29903) - Irish Grid coordinate system
- **WGS84**: World Geodetic System 1984 (EPSG:4326) - GPS coordinate system
- **PostGIS**: Spatial database extension for PostgreSQL
- **Traccar**: Open-source GPS tracking platform
- **QGIS**: Quantum GIS - open-source geographic information system
- **PyQGIS**: Python API for QGIS
- **CRS**: Coordinate Reference System
- **GPX**: GPS Exchange Format (XML-based GPS data format)

### Reference Links

- QGIS Python API Documentation: https://qgis.org/pyqgis/
- PostGIS Documentation: https://postgis.net/docs/
- Traccar Documentation: https://www.traccar.org/documentation/
- Irish Grid (ITM) Information: https://www.osi.ie/
- Kerry Mountain Rescue Team: (client website)

### Contact Information

- Project Lead: Eamon O'Connor (KMRT)
- Developer: [Your Name/Team]
- Support: [Email/Forum]

---

## Revision History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2025-10-11 | Claude Code | Initial specification based on client requirements |
| 2.0 | 2025-10-11 | Claude Code | Complete rewrite with all 20 features, PostGIS architecture, professional UI design |
| **2.2** | **2025-10-13** | **Claude Code** | **Phase 1 & 2 complete (100%) - Added auto-save and auto-resume features** |

---

---

## Addendum: Additional Requirements & Clarifications

**Date**: 2025-10-11 (Post-Review Updates)

### A1. CSV Import Support (Transitional Feature)

**Rationale**: Team currently uses CSV workflow. Plugin must support CSV import while database is being set up.

**Implementation**:

**FileCSVProvider** (providers/csv.py):
```python
import csv
from typing import List, Dict, Optional
from datetime import datetime
from .base import Provider, FeatureDict

class FileCSVProvider(Provider):
    """
    CSV provider for transitional period.
    Reads from Traccar CSV exports (team's current workflow).
    """
    def __init__(self, csv_folder: str):
        self.csv_folder = csv_folder

    def get_current(self) -> List[FeatureDict]:
        """Read latest position per device from CSV files"""
        import os
        import glob

        current_positions = {}

        # Find all CSV files in folder (format: deviceid_name.csv)
        csv_files = glob.glob(os.path.join(self.csv_folder, '*.csv'))

        for csv_file in csv_files:
            with open(csv_file, 'r') as f:
                reader = csv.DictReader(f)
                rows = list(reader)
                if rows:
                    # Get most recent row (last in file)
                    latest = rows[-1]
                    device_id = os.path.basename(csv_file).split('_')[0]

                    current_positions[device_id] = {
                        'device_id': device_id,
                        'name': latest.get('name', device_id),
                        'lat': float(latest['latitude']),
                        'lon': float(latest['longitude']),
                        'ts': latest['time'],
                        'altitude': None,
                        'speed': None,
                        'battery': None
                    }

        return list(current_positions.values())

    def get_breadcrumbs(self, since_iso: Optional[str] = None) -> List[FeatureDict]:
        """Read all positions from CSV files"""
        import os
        import glob

        all_positions = []
        csv_files = glob.glob(os.path.join(self.csv_folder, '*.csv'))

        for csv_file in csv_files:
            with open(csv_file, 'r') as f:
                reader = csv.DictReader(f)
                device_id = os.path.basename(csv_file).split('_')[0]

                for row in reader:
                    # Filter by time if specified
                    if since_iso:
                        row_time = datetime.fromisoformat(row['time'].replace('Z', '+00:00'))
                        since_time = datetime.fromisoformat(since_iso.replace('Z', '+00:00'))
                        if row_time < since_time:
                            continue

                    all_positions.append({
                        'device_id': device_id,
                        'name': row.get('name', device_id),
                        'lat': float(row['latitude']),
                        'lon': float(row['longitude']),
                        'ts': row['time'],
                        'altitude': None,
                        'speed': None,
                        'battery': None
                    })

        # Sort by device then time
        all_positions.sort(key=lambda x: (x['device_id'], x['ts']))
        return all_positions
```

**Settings Dialog Update**:
- Add "Data Source" dropdown: "PostGIS Database" | "CSV Files"
- If CSV selected, show folder picker instead of database settings
- Easy switch: CSV → PostGIS when ready

**Acceptance Criteria**:
- Can load positions from team's existing CSV files
- Same UI, same layers, just different data source
- Easy migration path to PostGIS

---

### A2. Offline Write Queue & Sync

**Rationale**: Van loses signal frequently. Must not lose casualty/POI/search area data.

**Implementation**:

**Write Queue** (utils/offline_queue.py):
```python
import json
import os
from datetime import datetime
from typing import Dict, List

class OfflineWriteQueue:
    """
    Queue for write operations when database connection is lost.
    Syncs automatically when connection restored.
    """
    def __init__(self, queue_dir: str):
        self.queue_dir = queue_dir
        os.makedirs(queue_dir, exist_ok=True)

    def enqueue_casualty(self, casualty_data: Dict):
        """Add casualty to offline queue"""
        self._enqueue('casualty', casualty_data)

    def enqueue_poi(self, poi_data: Dict):
        """Add POI to offline queue"""
        self._enqueue('poi', poi_data)

    def enqueue_search_area(self, area_data: Dict):
        """Add search area to offline queue"""
        self._enqueue('search_area', area_data)

    def _enqueue(self, item_type: str, data: Dict):
        """Write item to queue file"""
        timestamp = datetime.now().isoformat()
        filename = f"{timestamp}_{item_type}.json"
        filepath = os.path.join(self.queue_dir, filename)

        with open(filepath, 'w') as f:
            json.dump({'type': item_type, 'data': data, 'queued_at': timestamp}, f)

    def get_queued_items(self) -> List[Dict]:
        """Get all queued items (oldest first)"""
        import glob
        queue_files = sorted(glob.glob(os.path.join(self.queue_dir, '*.json')))
        items = []

        for filepath in queue_files:
            with open(filepath, 'r') as f:
                items.append(json.load(f))

        return items

    def sync_to_database(self, provider):
        """Sync all queued items to database"""
        items = self.get_queued_items()
        synced = []
        failed = []

        for item in items:
            try:
                if item['type'] == 'casualty':
                    provider.save_casualty(**item['data'])
                elif item['type'] == 'poi':
                    provider.save_poi(**item['data'])
                elif item['type'] == 'search_area':
                    provider.save_search_area(**item['data'])

                # Success - remove from queue
                self._dequeue(item)
                synced.append(item)

            except Exception as e:
                failed.append((item, str(e)))

        return synced, failed

    def _dequeue(self, item):
        """Remove item from queue"""
        # Find and delete the file
        import glob
        pattern = f"{item['queued_at']}_{item['type']}.json"
        filepath = os.path.join(self.queue_dir, pattern)
        if os.path.exists(filepath):
            os.remove(filepath)
```

**Provider Integration**:
- PostGISProvider attempts write
- On failure, enqueues to OfflineWriteQueue
- On successful reconnection, auto-syncs queue
- UI shows "X items queued for sync" indicator

**User Feedback**:
- "Connection lost - casualty saved locally (will sync when reconnected)"
- "Reconnected - syncing 3 queued items..."
- "Sync complete - all data saved to server"

---

### A3. Basemap Support (OSM + Irish OSi)

**Basemap Options**:
1. **OpenStreetMap** (default, always available)
2. **OSi Irish Topographic** (if team has access/subscription)
3. **Bing Aerial** (optional)
4. **None** (offline mode)

**Implementation** (controllers/basemap_controller.py):
```python
from qgis.core import QgsRasterLayer, QgsProject

class BasemapController:
    BASEMAPS = {
        'osm': {
            'name': 'OpenStreetMap',
            'url': 'type=xyz&url=https://tile.openstreetmap.org/{z}/{x}/{y}.png',
            'attribution': '© OpenStreetMap contributors'
        },
        'osi_topo': {
            'name': 'OSi Topographic',
            'url': 'type=xyz&url=https://api.osi.ie/tiles/topographic/{z}/{x}/{y}.png?api_key={API_KEY}',
            'attribution': '© Ordnance Survey Ireland',
            'requires_key': True
        },
        'bing_aerial': {
            'name': 'Bing Aerial',
            'url': 'type=xyz&url=http://ecn.t3.tiles.virtualearth.net/tiles/a{q}.jpeg?g=1',
            'attribution': '© Microsoft Bing'
        }
    }

    def add_basemap(self, basemap_type='osm', api_key=None):
        """Add basemap to project"""
        config = self.BASEMAPS[basemap_type]
        url = config['url']

        if config.get('requires_key') and api_key:
            url = url.replace('{API_KEY}', api_key)

        layer = QgsRasterLayer(url, config['name'], 'wms')

        if layer.isValid():
            QgsProject.instance().addMapLayer(layer, False)
            # Add to bottom of layer tree
            root = QgsProject.instance().layerTreeRoot()
            root.insertLayer(len(root.children()), layer)
            return True
        return False
```

**Settings**:
- Basemap dropdown in settings
- OSi API key field (if OSi selected)
- Auto-add basemap on first mission start

---

### A4. Configurable Time Gap for Breadcrumbs

**Issue**: Spec hardcodes 5-minute gap for breaking breadcrumb segments.

**Solution**: Make it user-configurable in settings.

**Settings Dialog Addition**:
- "Breadcrumb Time Gap" spinner (1-60 minutes, default 5)
- Help text: "Break trail into segments when GPS gap exceeds this duration"

**LayersController Update**:
```python
def update_breadcrumbs(self, positions: List[Dict], time_gap_minutes: int = None):
    """Update breadcrumb trails layer"""
    if time_gap_minutes is None:
        # Get from settings
        time_gap_minutes = QgsSettings().value('SAR Tracker/breadcrumb_time_gap', 5, int)

    # ... rest of implementation
```

---

### A5. Feature Clarifications

**5.1 Display of Saved Features**

All saved features automatically become map layers:

- **casualties** table → "SAR / Casualties" point layer (red markers)
- **pois** table → "SAR / POIs" point layer (blue markers)
- **search_areas** table → "SAR / Search Areas" polygon layer (team colors)
- **gpx_tracks** table → "SAR / GPX Tracks" line layer
- **text_annotations** table → Labels displayed on map

Each layer grouped under "SAR Tracking" layer group.

**5.2 Search Area Export - Start with Option A**

**Phase 4** will implement:
- Export full map to PDF/PNG (whole mission overview)
- Professional cartography (scale bar, north arrow, legend, title)

**Future Enhancement** (Phase 5+):
- Export individual team areas (focused PDFs per team)
- Batch export all areas

**5.3 Empty Database Handling**

If database has no active rescuers:
- Show friendly message: "No active rescuers. Start a mission and devices will appear when tracking begins."
- Don't error or crash
- Allow mission creation anyway (rescuers join later)

**5.4 Irish Basemap Priority**

Settings priority:
1. Try OSi Irish Topographic (if API key provided)
2. Fall back to OpenStreetMap (always works)
3. Allow "None" for offline mode

**5.5 Scale Bar - Dual Units**

Map export template includes:
- Scale bar with **both km and miles** (matches client's examples)
- Configured in QgsLayoutItemScaleBar

---

### A6. Provider Architecture (Updated)

```
Provider (ABC)
 ├─ PostGISProvider (production - database connection)
 ├─ FileCSVProvider (transitional - CSV files)
 └─ SpatiaLiteProvider (development - local mock DB)
```

**Settings Dialog**:
- **Data Source** dropdown:
  - "PostgreSQL/PostGIS Database" → show db settings
  - "CSV Files (Transitional)" → show folder picker
  - "SpatiaLite (Development)" → show file picker
- Easy switching between modes

---

### A7. Updated Project Structure

Add to `providers/`:
```
providers/
├── __init__.py
├── base.py
├── postgis.py
├── csv.py          # NEW: CSV provider
└── spatialite.py
```

Add to `utils/`:
```
utils/
├── __init__.py
├── config.py
├── coordinates.py
├── styling.py
├── export.py
├── network.py
├── offline_queue.py  # NEW: Write queue for offline mode
```

Add to `controllers/`:
```
controllers/
├── basemap_controller.py  # NEW: Basemap management
```

---

### A8. Updated Phase 1 Deliverables

Add to Phase 1:
- ✅ FileCSVProvider (CSV import support)
- ✅ OfflineWriteQueue (offline write resilience)
- ✅ BasemapController (OSM + OSi support)
- ✅ Configurable breadcrumb time gap (settings)

---

### A9. Revision History (Updated)

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2025-10-11 | Claude Code | Initial specification |
| 2.0 | 2025-10-11 | Claude Code | Complete rewrite with all 20 features, PostGIS architecture |
| **2.1** | **2025-10-11** | **Claude Code** | **Added: CSV import, offline write queue, OSi basemap, configurable time gap, clarifications** |

---

**END OF SPECIFICATION (v2.1)**
