# SAR QGIS Plugin - TODO & Roadmap

**Last Updated:** 2025-10-13

## ✅ COMPLETED (Phase 1 & 2 - 100%)

### Phase 1: Core Tracking (COMPLETE ✅)
- [x] Multi-device CSV tracking (single file or folder)
- [x] Beautiful map visualization (colored breadcrumb trails)
- [x] Labeled current positions
- [x] SAR Control Panel (docked widget)
- [x] Mission lifecycle (Start/Pause/Resume/Finish)
- [x] Real-time elapsed timer
- [x] Auto-refresh with configurable interval (5-300s)
- [x] Device status list with indicators
- [x] Folder-based CSV loading
- [x] Layer ordering (POIs on top, then casualties, then tracking data)
- [x] **Auto-save QGIS project** at user-defined intervals (1-60 minutes)
  - Enable/disable checkbox
  - Configurable interval
  - "Save Project Now" button
  - Status indicator with last save time
- [x] **Auto-resume on launch** - Detect paused mission when QGIS starts, prompt to resume
  - Mission state saved to QSettings when paused
  - Dialog on startup if paused mission found
  - "Resume Mission" or "Start Fresh" options

### Phase 2: Operational Tools (COMPLETE ✅)
- [x] Add POI markers (click on map)
- [x] Add Casualty markers (click on map)
- [x] MarkerDialog with WGS84 + Irish Grid coordinates
- [x] Real-time cursor coordinates in status bar
- [x] Coordinate Converter dialog (Irish Grid ↔ WGS84)
- [x] Measure Distance & Bearing tool (click two points)
  - Shows distance in meters/km
  - Shows bearing in degrees + cardinal direction
  - Red line preview while measuring
  - Single-line message banner
- [x] POI and Casualty layers with proper styling
- [x] Fixed layer flickering/shaking issues
- [x] Fixed status bar jitter
- [x] Custom mountain icon

---

## 🚧 NEXT UP (Phase 3)

---

## 📋 PLANNED (Phase 3 & 4)

### Phase 2 Optional Enhancements (Skipped for now)
- [ ] **POI Type-Based Styling** - Different icons for different POI types:
  - Base/Command Post → Flag icon
  - Vehicle → Car icon
  - Landmark → Triangle
  - Hazard → Warning symbol
  - Water Source, Shelter, etc.

**CalTopo Measurement Features (Future):**
- [ ] **Position & Elevation** - Show coordinates + elevation at cursor
- [ ] **Profile Tool** - Elevation profile along a line
- [ ] **Area Measurement** - Calculate polygon area

### Phase 3: Mapping & Areas (No Database Required)

**CalTopo-Inspired Tools** (from team's existing workflow):
- [ ] **Marker Tool** - ✅ Already built (our POI)
- [ ] **Clue Tool** - ✅ Already built (our Casualty)
- [ ] **Line Tool** - Draw simple lines on map
  - Click-to-draw line segments
  - Label with name/description
  - Measure length automatically
- [ ] **Polygon Tool** - Draw search areas (already planned below)
- [ ] **Range Ring Tool** - Draw circles (already planned below)
- [ ] **Bearing Line Tool** - Draw line from point with specific bearing/azimuth
  - Input: starting point, bearing (degrees), distance
  - Show bearing angle on line
  - Support both Irish Grid and WGS84 input
- [ ] **Sector Tool** - Draw wedge/pie-slice shapes
  - Input: center point, start bearing, end bearing, radius
  - Useful for directional search areas
  - Support both Irish Grid and WGS84 input

**Other Phase 3 Tools:**
- [ ] **Import GPX Files** - Load walker routes from GPX files
- [ ] **Draw Search Areas (Polygons)** - Digitize polygon zones
  - Assign to teams
  - Style with team colors
  - Semi-transparent fills
  - Print/export individual areas
- [ ] **Add Text Annotations** - Place text labels anywhere on map
- [ ] **Draw Circles/Arcs** - Draw circles from a point with specified radius
  - Input in both Irish Grid and WGS84
  - Show radius distance
- [ ] **Area Text Labels** - Annotate shaded polygon areas with text

### Phase 4: Analysis & Export
- [ ] **Export Professional Maps (PDF/PNG)**
  - Scale bar (km and miles)
  - North arrow
  - Legend
  - Title block
  - Grid reference
  - Map projection info
- [ ] **Generate Mission Reports (CSV/PDF)**
  - Mission summary (name, duration, participants)
  - Per-participant stats (distance traveled, time active, max/avg speed)
  - Search area coverage
  - List of POIs and casualties
- [ ] **Mission Playback** (needs database)
  - Time slider
  - Replay movement over time
  - Speed controls (0.5x, 1x, 2x, 5x)

---

## 💡 FEATURE ENHANCEMENTS DISCUSSED

### CalTopo Feature Parity Notes
- Team is familiar with CalTopo interface
- **Key requirement:** All coordinate inputs should support BOTH formats:
  - Irish Grid (ITM) - Easting/Northing
  - WGS84 - Latitude/Longitude
- Right-click menu on map for quick access to tools (future enhancement)
- CalTopo reference image: `-5902411506232970001_120.jpg`

### POI/Casualty Management
- [ ] **Identify Tool** - Click on POI/Casualty to see details in popup
  - Show all info (name, type, coordinates, notes, timestamp)
  - Edit button (modify details)
  - Delete button (remove marker)
- [ ] **POI/Casualty List Panel** - Show all markers in a table
  - Sort by name, type, time added
  - Click to zoom to marker
  - Filter by type
  - Bulk delete

### Mission Management
- [ ] **Mission History** - List of past missions
- [ ] **Mission Notes** - Add timestamped notes during mission
- [ ] **Team Assignment** - Assign devices to teams/groups
- [ ] **Device Grouping** - Group devices by team in device list

### Map Improvements
- [ ] **Basemap Selector** - Easy switching between:
  - OpenStreetMap
  - OSi Irish Topographic (if API key available)
  - Bing Aerial
  - Offline/None
- [ ] **Search Location** - Search by placename or grid reference
- [ ] **Quick Zoom Presets** - Save favorite zoom extents
- [ ] **Measurement History** - Keep history of distances measured

### UI Polish
- [ ] **Better color scheme** - Irish Mountain Rescue themed colors
- [ ] **Custom icon** - Replace default plug icon with SAR-appropriate icon
- [ ] **Better button icons** - Add icons to all buttons
- [ ] **Status indicators** - Visual feedback for connection, data loading, etc.
- [ ] **Loading spinners** - Show activity when loading data
- [ ] **Tooltips** - Add helpful tooltips to all controls
- [ ] **Keyboard shortcuts** - Add shortcuts for common actions

### Data Management
- [ ] **Export POIs/Casualties to CSV** - Save markers for later import
- [ ] **Import POIs/Casualties from CSV** - Load pre-defined locations
- [ ] **Backup/Restore** - Save and restore entire mission state

---

## 🔮 FUTURE (Requires Database Setup)

### Database Migration
- [ ] **Install PostgreSQL/PostGIS** on team's laptop
- [ ] **Create database schema** (already designed in spec)
- [ ] **Modify Eamon's Python scripts** to write to database instead of CSV
- [ ] **Create PostGISProvider** in plugin to read from database
- [ ] **Test database connection** over Zerotier VPN
- [ ] **Handle connection drops gracefully** (offline queue)

### Live Tracking (Database-Powered)
- [ ] **Real-time updates** from Traccar database
- [ ] **Live auto-refresh** (10-30 second intervals)
- [ ] **Persistent POIs/Casualties** (saved to database)
- [ ] **Persistent Search Areas** (saved to database)
- [ ] **Mission history playback** from historical data
- [ ] **Multi-operator support** (multiple QGIS instances viewing same mission)

### Offline Mode
- [ ] **Offline write queue** - Queue POI/Casualty/Area saves when connection lost
- [ ] **Auto-sync on reconnect** - Sync queued items when connection restored
- [ ] **Offline indicator** - Show clear status when offline
- [ ] **Last known positions** - Show stale data with timestamp when offline

---

## 🐛 KNOWN ISSUES / LIMITATIONS

### Current Limitations
- POIs and Casualties are **memory-only** (lost when QGIS closes)
  - Will be fixed when database is set up
- No way to edit or delete individual POIs/Casualties once added
  - Need to add Identify tool
- No way to save Search Areas yet (Phase 3 feature)
- CSV loading dialog is confusing (folder first, then file)
  - Could improve UX

### Fixed Issues
- ✅ Layer flickering when dragging layers
- ✅ Status bar coordinate display shaking
- ✅ POIs hidden behind tracking layers
- ✅ Map zoom jumping on every refresh
- ✅ Plugin icon not showing in toolbar

---

## 📝 NOTES

### CSV Workflow (Current)
```
Phones → Traccar Server → Python Script → CSV Files → QGIS Plugin
```

### Database Workflow (Future)
```
Phones → Traccar Server → PostgreSQL/PostGIS ← QGIS Plugin
```

### Testing Notes
- Plugin works with both single CSV files and folders of CSVs
- Tested with 4 devices (Team Alpha, Bravo, Charlie, EOC)
- Coordinate conversion (Irish Grid ↔ WGS84) working correctly
- Mission controls (start/pause/resume/finish) all functional
- Auto-refresh timer working (tested at 10s and 30s intervals)

---

## 🎯 PRIORITY ORDER (Suggested)

1. ✅ ~~**Finish Phase 1 & 2**~~ - COMPLETE!
2. **Phase 3** (CalTopo tools: Lines, Sectors, Search Areas, GPX Import) - Core operational features
3. **UI Polish** - Make it look professional for the team (colors, icons, tooltips)
4. **POI/Casualty Identify Tool** - Make markers interactive (edit/delete)
5. **Phase 4** (Map Export, Reports) - Professional output
6. **Database Setup** - Move from CSV to live database

---

## 📞 CONTACT / QUESTIONS

- Client: Eamon O'Connor & Kerry Mountain Rescue Team
- Traccar Server: http://kmrtsar.eu or 109.76.170.87:8082
- Network: Zerotier VPN (spotty mobile connection from van)

---

**Remember:** Keep features simple and reliable. Non-GIS users need to operate this in stressful SAR situations.
