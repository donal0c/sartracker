# SAR Critical Features Checklist

**Quick Reference for Implementation Priority**
*Based on SAR Requirements Report - 2025-10-18*

---

## 🚨 CRITICAL - Implement Immediately

### Terminology Updates (Low Effort, High Impact)
- [ ] Rename "POI" to "IPP/LKP" in marker dialog
- [ ] Add "PLS" (Place Last Seen) as marker type
- [ ] Update UI labels to use standard SAR terminology
- [ ] Add tooltip explanations for SAR terms

### Search Area Status Tracking
- [ ] Add status field to polygon features:
  - [ ] Planned
  - [ ] Assigned
  - [ ] In Progress
  - [ ] Completed
  - [ ] Suspended
  - [ ] Cleared
- [ ] Color code polygons by status
- [ ] Add status filter/legend

### Lost Person Behavior (LPB) Basic Implementation
- [ ] Add subject category dropdown to IPP marker:
  - [ ] Child (with age ranges)
  - [ ] Hiker
  - [ ] Elderly
  - [ ] Dementia
  - [ ] Despondent
  - [ ] Autistic
  - [ ] Hunter
  - [ ] Other
- [ ] Generate automatic range rings (25%, 50%, 75%, 95% zones)
- [ ] Display statistical distances in UI

---

## ⚠️ HIGH PRIORITY - Phase 3 Additions

### Search Segment Management
- [ ] Add "Team Assignment" field to search polygons
- [ ] Create team list/dropdown
- [ ] Display team name on polygon labels
- [ ] Track time started/completed per segment

### Clue Enhancement
- [ ] Expand casualty marker to "Clue" marker with types:
  - [ ] Footprint
  - [ ] Clothing
  - [ ] Equipment
  - [ ] Witness sighting
  - [ ] Other evidence
- [ ] Add confidence level (Confirmed/Probable/Possible)
- [ ] Auto-calculate distance/bearing from IPP

### Hazard Marking
- [ ] Create hazard marker tool with icons:
  - [ ] Cliff/Drop
  - [ ] Water
  - [ ] Unstable ground
  - [ ] Dense vegetation
  - [ ] Weather exposure
- [ ] Hazard zone polygons
- [ ] Warning color scheme (orange/yellow)

---

## 📊 MEDIUM PRIORITY - Enhanced Features

### Probability Calculations
- [ ] POA (Probability of Area) field for segments
- [ ] POD (Probability of Detection) tracking
- [ ] Heat map visualization option
- [ ] Automatic POA based on distance from IPP

### Search Patterns
- [ ] Grid search generator
- [ ] Contour search (following elevation)
- [ ] Expanding square from IPP
- [ ] Sound sweep line generator

### Resource Management
- [ ] Helicopter landing zones (HLZ)
- [ ] Staging area markers
- [ ] Command post (CP) location
- [ ] Add resource type icons

---

## 📝 LOWER PRIORITY - Nice to Have

### Reporting
- [ ] Segment assignment sheets export
- [ ] Mission statistics summary
- [ ] ICS-204 form generation
- [ ] Search coverage analysis

### Advanced Analysis
- [ ] Time-distance calculations
- [ ] Terrain difficulty factors
- [ ] Weather impact modeling
- [ ] Historical search data

### Communication
- [ ] Radio channel assignments
- [ ] Dead zone marking
- [ ] Repeater locations
- [ ] Emergency frequencies display

---

## 🌍 Ireland-Specific Considerations

### Coordinate Formats
- [x] Irish Grid (ITM) - Already implemented
- [ ] Traditional grid references (e.g., "O 123 456")
- [ ] Support for older Irish Grid (IG/EPSG:29902)

### Terrain Types
- [ ] Bog/Peatland hazard type
- [ ] Coastal cliff considerations
- [ ] Lough (lake) boundaries
- [ ] Forest plantation density

### Organizations
- [ ] Support Mountain Rescue Ireland protocols
- [ ] Irish Coast Guard compatibility
- [ ] RNLI coordination features
- [ ] Civil Defence integration

---

## 💡 Quick Implementation Wins

**These can be done TODAY with minimal effort:**

1. **Update Marker Dialog Labels:**
   - Change "Add POI" button to "Add IPP/LKP"
   - Add subject category dropdown
   - Add tooltip: "IPP = Initial Planning Point"

2. **Add Status to Search Areas:**
   - Add dropdown in polygon properties
   - Use color coding (Green=Complete, Yellow=In Progress, Red=Priority)

3. **Create Basic LPB Rings:**
   - Hard-code common distances for now
   - Child: 0.5km, 1km, 2km
   - Adult: 1km, 3km, 5km, 10km
   - Elderly: 0.5km, 1km, 2km

4. **Enhance Existing Tools:**
   - Add "Distance from IPP" to all markers
   - Show elapsed time since mission start prominently
   - Add "Priority" field to all features

---

## 📚 Reference Documentation to Create

- [ ] SAR Terminology Guide for users
- [ ] LPB Statistics reference card
- [ ] Search patterns guide
- [ ] Irish Grid reference converter
- [ ] Team assignment workflow

---

## ✅ Already Implemented (Don't Duplicate)

- Real-time GPS tracking
- POI/Casualty markers
- Coordinate conversion
- Distance/bearing measurement
- Mission timer
- Auto-refresh/auto-save
- CSV import

---

## 🎯 Success Metrics

**The plugin will be SAR-ready when:**
1. Uses standard SAR terminology throughout
2. Tracks search area status effectively
3. Supports basic LPB statistics
4. Allows team assignments to segments
5. Provides hazard marking capability
6. Exports useful field documents

---

*Use this checklist during development. Check off items as completed. Priority items should be done before moving to lower priorities.*