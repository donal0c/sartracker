# SAR Tracker - QGIS Plugin

**Search & Rescue Tracking Console for Kerry Mountain Rescue**

Transform QGIS into a dedicated SAR operations console for real-time tracking of rescue personnel during search missions.

![QGIS 3.0+](https://img.shields.io/badge/QGIS-3.0%2B-blue)
![License](https://img.shields.io/badge/License-GPL--2.0-green)

---

## 🚀 Quick Start

### Prerequisites

- **QGIS 3.0 or later** - Download from https://qgis.org/download/

---

## 📥 Installation

### Step 1: Get the Plugin Files

**Option A: Clone with Git**
```bash
cd ~/Documents
git clone https://github.com/YOUR_USERNAME/sartracker.git
```

**Option B: Download ZIP**
1. Download ZIP from GitHub
2. Extract to your Documents folder

### Step 2: Install in QGIS

**Find your QGIS plugins folder:**
- **Mac**: `~/Library/Application Support/QGIS/QGIS3/profiles/default/python/plugins/`
- **Windows**: `C:\Users\YOUR_USERNAME\AppData\Roaming\QGIS\QGIS3\profiles\default\python\plugins\`
- **Linux**: `~/.local/share/QGIS/QGIS3/profiles/default/python/plugins/`

**Install:**
1. Copy the entire `sartracker` folder into your QGIS plugins folder
2. Restart QGIS
3. Go to **Plugins** → **Manage and Install Plugins**
4. Find **SAR Tracker** in the Installed tab
5. Check the box to enable it

✅ You should now see a mountain icon (⛰️) in the QGIS toolbar!

---

## 🎯 How to Use

### 1. Open SAR Tracker Panel

Click the **mountain icon** in the toolbar.

The SAR Tracking panel will open on the right side of QGIS.

### 2. Start a Mission

1. Enter a **mission name** (e.g., "Glenbeigh Search")
2. Click **"Start Mission"**
3. Timer starts counting elapsed time

**Mission Controls:**
- **Pause** - Temporarily stop tracking
- **Resume** - Continue tracking
- **Finish** - Complete and save mission

### 3. Load Tracking Data

**From CSV Files:**
1. Click **"Load CSV File..."**
2. Select folder with CSV files OR single CSV file
3. Data loads automatically to map

**Supported formats:**
- Traccar CSV exports
- Must have: `latitude`, `longitude`, `time`, `name` columns

### 4. Add Markers

**IPP/LKP (Initial Planning Point / Last Known Position):**
1. Click **"Add IPP/LKP"**
2. Click on map at location
3. Fill in details:
   - Name and description
   - Subject category (Child, Hiker, Elderly, etc.)
   - Notes
4. Blue marker appears

**Clues:**
1. Click **"Add Clue"**
2. Click on map
3. Select clue type (Footprint, Clothing, Equipment, Sighting, Evidence)
4. Set confidence (Confirmed/Probable/Possible)
5. Orange marker appears

**Hazards:**
1. Click **"Add Hazard"**
2. Click on map
3. Select hazard type (Cliff, Water, Bog, Vegetation, Wildlife, Weather, Other)
4. Red warning marker appears

### 5. Drawing Tools

**Lines (Routes/Boundaries):**
1. Click **"Lines"**
2. Click to add points
3. Right-click to finish
4. Shows total distance

**Search Areas (Polygons):**
1. Click **"Search Area"**
2. Click to add vertices
3. Right-click to close polygon
4. Configure:
   - Area name
   - Assigned team
   - Status (Planned/Assigned/InProgress/Completed/Cleared)
   - Priority (High/Medium/Low)
   - POA (Probability of Area)
   - Terrain type and search method
   - Notes

**Range Rings (Probability Circles):**
1. Click **"Range Rings"**
2. Click center point
3. Choose mode:
   - **Manual**: Custom radius + number of rings
   - **LPB (Lost Person Behavior)**: Select subject category for automatic probability rings at 25%, 50%, 75%, 95%
4. Rings appear color-coded

**Bearing Lines (Direction Finding):**
1. Click **"Bearing Line"**
2. Click origin point
3. Configure:
   - Line name
   - Choose **True Bearing** or **Magnetic Bearing**
   - Enter bearing (0-360°)
   - Enter distance (meters or kilometers)
4. Shows both true and magnetic bearings (Ireland declination: -4.5°)
5. Purple line appears

### 6. Measurement & Utilities

**Measure Distance & Bearing:**
1. Click **"Measure Distance & Bearing"**
2. Click first point
3. Click second point
4. Results show distance and bearing (with cardinal direction)

**Coordinate Converter:**
1. Click **"Coordinate Converter"**
2. Choose input type (WGS84 or Irish Grid)
3. Enter coordinates
4. Convert between systems
5. Copy or go to location

**Real-time Coordinates:**
- Look at bottom status bar
- Shows cursor position in both WGS84 and Irish Grid as you move mouse

### 7. Auto-Features

**Auto-Refresh:**
1. Check "Enable auto-refresh"
2. Set interval (default: 30 seconds)
3. Click "Refresh Now" for immediate update

**Auto-Save:**
1. First save your QGIS project manually (Project → Save As)
2. Check "Enable auto-save"
3. Set interval (default: 5 minutes)
4. Project saves automatically

---

## 📂 Understanding the Layers

**"SAR Tracking" group contains:**
- **IPP/LKP** - Blue circles - Initial planning points
- **Clues** - Orange markers - Evidence found
- **Hazards** - Red warnings - Dangerous areas
- **Lines** - Routes and boundaries
- **Search Areas** - Polygons with status tracking
- **Range Rings** - Probability circles
- **Bearing Lines** - Direction-finding lines
- **Current Positions** - Latest position per team member
- **Breadcrumbs** - Full movement trails

**Each device/team member gets a unique color automatically.**

---

## 🔄 Auto-Resume Feature

If you pause a mission and close QGIS:
1. Reopen QGIS
2. Dialog appears: "Found paused mission"
3. Choose **Resume Mission** or **Start Fresh**

---

## 💾 Saving Your Work

**Your QGIS project contains:**
- Map position and zoom
- All loaded tracking data
- All markers (IPP/LKP, Clues, Hazards)
- All drawn features (search areas, bearing lines, range rings, lines)
- Layer styling

**Important:**
- Use auto-save to save regularly
- Save manually before closing (Project → Save)

---

## 🐛 Troubleshooting

**Plugin doesn't appear:**
- Check plugin folder location
- Folder must be named exactly `sartracker`
- Restart QGIS completely
- Enable in Plugins → Manage and Install Plugins

**Can't load CSV files:**
- Check format: needs `latitude`, `longitude`, `time`, `name` columns
- Try single file first before folder

**Auto-save not working:**
- Save project manually first (Project → Save As)
- Then enable auto-save
- Auto-save only works on saved projects

**Layers not showing:**
- Check Layers panel on left
- Expand "SAR Tracking" group
- Tick checkboxes
- Right-click layer → "Zoom to Layer"

---

## ✅ Current Features

### Mission Management
- Start/Pause/Resume/Finish missions
- Real-time elapsed timer
- Auto-resume on restart
- Auto-save at intervals

### Tracking
- Multi-device CSV tracking
- Colored breadcrumb trails
- Current positions
- Auto-refresh
- Device status list

### Map Markers
- IPP/LKP with subject categories
- Clues with confidence levels
- Hazards with severity

### Drawing Tools
- Lines (routes, boundaries)
- Search Areas (polygons with status, team, POA)
- Range Rings (manual or LPB-based)
- Bearing Lines (true/magnetic bearings)

### Utilities
- Distance & bearing measurement
- Coordinate converter (Irish Grid ↔ WGS84)
- Real-time cursor coordinates

### Coordinate Systems
- WGS84 (GPS standard)
- Irish Grid ITM (EPSG:29903)

---

## 🔮 Coming Soon

### Next Features
- Search Sector Tool - Pie-slice search areas
- Text Label Tool - Map annotations
- GPX Import - Load GPS tracks

### Future Enhancements
- Export maps (PDF/PNG with legend, scale, north arrow)
- Mission reports (CSV statistics)
- Mission playback (time-slider)
- Database integration (PostgreSQL/PostGIS)

---

## 🏔️ About

SAR Tracker transforms QGIS into a dedicated Search & Rescue operations console. Simple enough for any team member to use during missions, yet powerful enough for professional SAR operations.

**Design Principles:**
- Simple, focused interface
- Works with current CSV workflow
- Reliable in poor conditions
- Cross-platform compatible

---

## 📜 License

GNU General Public License v2.0

---

## 🎉 Credits

**Generated with Claude Code** - https://claude.com/claude-code

**Built for:** Kerry Mountain Rescue Team, Ireland

---

**Version:** 0.4 (Phase 3 - In Progress)
**Last Updated:** October 19, 2025
**Status:** Production Ready ✅
