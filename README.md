# SAR Tracker - QGIS Plugin

**Search & Rescue Tracking Console for Kerry Mountain Rescue Team**

Transform QGIS into a dedicated SAR operations console for real-time tracking of rescue personnel during search missions.

![Phase 1 & 2 Complete](https://img.shields.io/badge/Phase%201%20%26%202-Complete-success)
![QGIS 3.40+](https://img.shields.io/badge/QGIS-3.40%2B-blue)
![License](https://img.shields.io/badge/License-GPL--2.0-green)

---

## 🚀 Quick Start

### Prerequisites

- **QGIS 3.40 or later** installed on your computer
  - Download from: https://qgis.org/download/
  - Works on Windows, Mac, and Linux

---

## 📥 Installation

### Step 1: Get the Plugin Files

**Option A: Clone with Git** (if you have git installed)
```bash
cd ~/Documents
git clone https://github.com/YOUR_USERNAME/sartracker.git
```

**Option B: Download ZIP**
1. Go to: https://github.com/YOUR_USERNAME/sartracker
2. Click the green "Code" button
3. Click "Download ZIP"
4. Extract the ZIP file to your Documents folder

### Step 2: Install in QGIS

**Find your QGIS plugins folder:**

- **Mac**: `~/Library/Application Support/QGIS/QGIS3/profiles/default/python/plugins/`
- **Windows**: `C:\Users\YOUR_USERNAME\AppData\Roaming\QGIS\QGIS3\profiles\default\python\plugins\`
- **Linux**: `~/.local/share/QGIS/QGIS3/profiles/default/python/plugins/`

**Install the plugin:**

1. **Copy** the entire `sartracker` folder into your QGIS plugins folder
2. **Restart QGIS**
3. Go to **Plugins** → **Manage and Install Plugins**
4. Click the **Installed** tab
5. Find **SAR Tracker** in the list
6. **Check the box** to enable it

✅ You should now see a mountain icon (⛰️) in the QGIS toolbar!

---

## 🎯 How to Use

### 1. Open SAR Tracker Panel

Click the **mountain icon** in the toolbar (or go to **Plugins** → **SAR Tracker Panel**)

The SAR Tracking panel will open on the right side of QGIS.

### 2. Load Your Tracking Data

**From CSV Files:**
1. Click **"Load CSV File..."**
2. **First dialog:** Select the **folder** containing your CSV files (or cancel to select a single file)
3. **Second dialog:** If you cancelled, select a single CSV file

**Supported formats:**
- Traccar CSV exports (one file per device)
- Folder with multiple CSV files (all devices at once)

### 3. Start a Mission

1. Enter a **mission name** (e.g., "Glenagenty Search")
2. Click **"Start Mission"**
3. Timer starts counting elapsed time
4. Status shows "Active" in green

### 4. Control the Mission

**Pause:** Click **"Pause"** to temporarily stop tracking
- Status changes to orange "Paused"
- Timer continues showing total elapsed time

**Resume:** Click **"Resume"** to continue
- Status returns to green "Active"

**Finish:** Click **"Finish"** when mission complete
- Saves final state
- Clears mission status

### 5. Auto-Refresh (Keep Data Updated)

1. Check **"Enable auto-refresh"**
2. Set interval (default: 30 seconds)
3. Click **"Refresh Now"** for immediate update

### 6. Auto-Save Your Work

1. **First time:** Save your QGIS project (Project → Save As)
2. In SAR Panel, check **"Enable auto-save"**
3. Set interval (default: 5 minutes)
4. Your project will save automatically!

**Status shows:**
- ✓ Last save: 14:23:15 (green = success)
- ✗ Last save: 14:23:15 Failed (red = error)

### 7. Add Markers to the Map

**Add a Point of Interest (POI):**
1. Click **"Add Point of Interest (POI)"**
2. **Click on the map** where you want the marker
3. Dialog opens showing coordinates in both formats:
   - WGS84 (GPS): Latitude/Longitude
   - Irish Grid (ITM): Easting/Northing
4. Enter name and description
5. Click **"Add POI"**
6. Blue marker appears on map

**Add a Casualty:**
1. Click **"Add Casualty"**
2. **Click on the map** at casualty location
3. Enter name, description, condition
4. Click **"Add Casualty"**
5. Red marker appears on map

### 8. Coordinate Tools

**Convert Coordinates:**
1. Click **"Coordinate Converter"**
2. Choose input type (WGS84 or Irish Grid)
3. Enter coordinates
4. Click **"Convert"**
5. Results show both formats
6. Click **"Copy to Clipboard"** or **"Go to Location"**

**Measure Distance & Bearing:**
1. Click **"Measure Distance & Bearing"**
2. **Click first point** on map
3. **Click second point** on map
4. Green banner shows:
   - Distance: 2.5 km
   - Bearing: 45.3° (NE)

### 9. Real-Time Coordinate Display

Look at the **bottom status bar** - as you move your mouse over the map, you'll see:

```
WGS84: 52.234567°N, -9.123456°E  |  Irish Grid: E:123456  N:234567
```

Both coordinate systems update in real-time!

---

## 🔄 Auto-Resume Feature

**If you pause a mission and close QGIS:**

1. **Reopen QGIS**
2. A dialog appears: "Found paused mission"
3. Shows mission name and start time
4. Choose:
   - **"Resume Mission"** - Continue where you left off
   - **"Start Fresh"** - Clear old mission and start new

---

## 📂 Understanding the Layers

When you load data, you'll see a **"SAR Tracking"** group in the Layers panel:

- **POIs** (top) - Blue circles - Points of interest
- **Casualties** - Red stars - Casualty locations
- **Current Positions** - Colored markers - Latest position per team member
- **Breadcrumbs** (bottom) - Colored lines - Full trail of movement

**Layers are automatically colored per device/team member.**

---

## 💾 Saving Your Mission

Your QGIS project contains:
- Map position and zoom level
- All loaded CSV data
- All POIs and Casualties you added
- Layer styling and visibility

**Important Notes:**
- POIs and Casualties are **memory-only** (lost when QGIS closes)
- Use **auto-save** to save your project regularly
- Future version will use a database for persistent storage

---

## 🐛 Troubleshooting

### Plugin doesn't appear in QGIS

1. Check the plugin folder location is correct
2. Make sure the folder is named exactly `sartracker`
3. Restart QGIS completely
4. Go to Plugins → Manage and Install Plugins → Installed
5. Look for "SAR Tracker" and check the box

### Can't load CSV files

- Check CSV format matches Traccar export format
- Columns required: `latitude`, `longitude`, `time`, `name`
- Try loading a single file first before loading a folder

### Auto-save not working

1. **First save your project manually:** Project → Save As
2. Give it a name and location
3. **Then** enable auto-save in SAR Panel
4. Auto-save only works on already-saved projects

### Layers not showing on map

1. Check the **Layers** panel on the left
2. Expand the "SAR Tracking" group
3. Make sure layers have checkboxes ticked
4. Right-click layer → "Zoom to Layer"
5. Check that you loaded data successfully

### Status bar coordinates not updating

- This is normal - coordinates update as you move your mouse
- If stuck, try clicking on the map canvas first

---

## 📋 Current Features (Phase 1 & 2 Complete)

### ✅ Mission Management
- Start/Pause/Resume/Finish missions
- Real-time elapsed timer
- Auto-resume paused missions on launch
- Auto-save QGIS project at intervals

### ✅ Tracking Visualization
- Multi-device CSV tracking (single file or folder)
- Colored breadcrumb trails per team member
- Labeled current positions
- Auto-refresh at configurable intervals
- Device status list

### ✅ Map Tools
- Add POI markers (click on map)
- Add Casualty markers (click on map)
- Measure distance and bearing between points
- Coordinate converter (Irish Grid ↔ WGS84)
- Real-time cursor coordinates in status bar

### ✅ Coordinate Support
- WGS84 (GPS standard)
- Irish Grid ITM (EPSG:29903)
- Real-time conversion between systems

---

## 🔮 Coming Soon (Phase 3 & 4)

### Phase 3: CalTopo-Inspired Tools
- Line Tool - Draw simple lines
- Bearing Line Tool - Line from point with bearing
- Sector Tool - Draw wedge/pie shapes
- Draw Search Areas - Polygons with team colors
- Range Ring Tool - Circles with radius
- Import GPX Files - Load walker routes
- Text Annotations - Labels on map

### Phase 4: Professional Output
- Export Maps (PDF/PNG with scale bar, legend, north arrow)
- Generate Mission Reports (CSV with participant stats)
- Mission Playback - Time-slider replay

### Future: Database Integration
- PostgreSQL/PostGIS database connection
- Persistent storage for POIs, Casualties, Search Areas
- Live tracking from Traccar database
- Multi-operator support
- Offline write queue with auto-sync

---

## 📖 Documentation

- **TODO.md** - Detailed roadmap and feature list
- **SAR_QGIS_Plugin_Technical_Specification.md** - Complete technical specification
- **SAR_QGIS_Plugin_Claude_Spec.md** - Simplified build specification

---

## 🏔️ About SAR Tracker

This plugin transforms QGIS into a dedicated Search & Rescue operations console. It's designed to be simple enough for any team member to use during stressful SAR situations while providing professional-grade mapping and tracking capabilities.

**Key Design Principles:**
- Simple, focused interface (not a full GIS tool)
- Works with current CSV workflow (database coming later)
- Reliable in poor network conditions
- Cross-platform (Windows, Mac, Linux)

---

## 📜 License

GNU General Public License v2.0

This program is free software; you can redistribute it and/or modify it under the terms of the GNU General Public License as published by the Free Software Foundation; either version 2 of the License, or (at your option) any later version.

---

## 🎉 Credits

**Generated with Claude Code**
https://claude.com/claude-code

**Built with:**
- QGIS 3.40+
- PyQGIS API
- Python 3.9+

---

**Version:** 1.0 (Phase 1 & 2 Complete)
**Last Updated:** October 13, 2025
**Status:** Production Ready ✅
