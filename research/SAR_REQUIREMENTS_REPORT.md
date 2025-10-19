# Search & Rescue (SAR) Requirements Report

**Date:** 2025-10-18
**Purpose:** Comprehensive analysis of SAR mapping requirements and standards to ensure critical features are not missing from the SAR Tracker QGIS plugin

---

## Executive Summary

Based on research of international SAR standards, existing SAR software platforms, and analysis of the current SAR Tracker implementation, this report identifies critical requirements for SAR mapping applications. While direct access to some official SAR documentation was limited, sufficient information was gathered from multiple sources including IAMSAR guidelines, ICS standards, CalTopo/SARTopo analysis, and examination of open-source SAR tools.

**Key Findings:**
- The SAR Tracker plugin already implements many core features (device tracking, POI/Casualty markers, coordinate conversion)
- Phase 3 planning shows good alignment with CalTopo-style drawing tools
- Several critical SAR-specific features should be considered for implementation
- Terminology should be standardized to match international SAR conventions
- Lost Person Behavior (LPB) integration would significantly enhance search planning capabilities

---

## 1. SAR Standards Summary

### 1.1 International Standards

#### IAMSAR (International Aeronautical and Maritime Search and Rescue Manual)
- **Publisher:** Joint publication by ICAO and IMO (UN agencies)
- **Structure:** Three volumes covering Organization, Mission Coordination, and Mobile Facilities
- **Relevance:** Provides standardized procedures for SAR coordination
- **Key Requirements:**
  - Standardized terminology across agencies
  - Common operational procedures
  - Defined coordination structures
  - Communication protocols

#### ICS (Incident Command System)
- **Purpose:** Standardized emergency management system
- **Key Concepts for SAR:**
  - Unity of Command
  - Common Terminology
  - Management by Objectives
  - Span of Control (3-7 resources per supervisor)
  - Resource Typing and Status Tracking
  - Incident Action Plans (IAPs)
- **Resource Status Values:**
  - Assigned
  - Available
  - Out-of-Service

### 1.2 Coordinate Systems

**Current Implementation (Good):**
- Irish Grid (ITM/EPSG:29903) - Primary for Ireland
- WGS84 (EPSG:4326) - International standard
- Coordinate conversion tools already implemented

**Additional Considerations:**
- Support for decimal degrees AND degrees/minutes/seconds format
- Grid reference format (e.g., "O 123 456" for Irish Grid)
- Consider adding support for MGRS (Military Grid Reference System) if working with military SAR units

### 1.3 Data Exchange Standards

**SARLOC:**
- UK-based system for sharing casualty locations
- Uses SMS/text messaging for coordinate sharing
- Consider implementing SARLOC-compatible export format

**GPX (GPS Exchange Format):**
- Already planned in Phase 3C
- Standard for sharing GPS tracks
- Essential for importing team tracks and subject routes

---

## 2. Terminology Dictionary

### 2.1 Core SAR Terms (Priority 1)

| Term | Definition | Usage in System |
|------|------------|-----------------|
| **IPP** | Initial Planning Point | Starting point for search planning, often same as LKP |
| **LKP** | Last Known Position | Last confirmed location of missing person |
| **PLS** | Place Last Seen | Location where subject was last visually confirmed |
| **POA** | Probability of Area | Statistical likelihood subject is in specific area |
| **POD** | Probability of Detection | Likelihood of finding subject if present in searched area |
| **ROW** | Rest of World | Areas outside primary search area |

### 2.2 Search Area Terms

| Term | Definition | Current Implementation |
|------|------------|------------------------|
| **Search Area** | Overall area being searched | Planned for Phase 3A |
| **Segment** | Manageable subdivision of search area | Planned for Phase 3A |
| **Sector** | Wedge-shaped search area from central point | Planned for Phase 3B |
| **Grid** | Search area divided into rectangular segments | Consider adding |
| **Hasty Team Area** | High-probability area for initial fast search | Not yet planned |

### 2.3 Status Values

**For Search Areas:**
- **Planned** - Area identified but not yet searched
- **Assigned** - Team assigned but not yet started
- **In Progress** - Active searching
- **Completed** - Area fully searched
- **Suspended** - Search paused (weather, darkness, etc.)
- **Cleared** - Searched with high POD, subject not present

**For Teams:**
- **Available** - Ready for assignment
- **Assigned** - Given task but not yet started
- **En Route** - Traveling to search area
- **On Scene** - At search area
- **Searching** - Actively searching
- **Returning** - Coming back to base
- **Off Duty** - Not available

### 2.4 Resources and Roles

| Term | Definition | Implementation Status |
|------|------------|----------------------|
| **IC** | Incident Commander | Not tracked |
| **OSC** | On-Scene Coordinator | Not tracked |
| **TFL** | Team Field Leader | Not tracked |
| **K9** | Canine unit | Not specifically tracked |
| **UAV/Drone** | Unmanned Aerial Vehicle | Not tracked |

---

## 3. Feature Requirements

### 3.1 Critical Missing Features (Priority 1)

#### Lost Person Behavior (LPB) Integration
**Requirement:** Statistical search radius based on subject category
**Implementation:**
- Add subject category selector when creating IPP/LKP
- Generate automatic range rings based on LPB statistics
- Categories needed:
  - Child (1-3 years): 50% within 0.3km, 95% within 1.9km
  - Child (4-6 years): 50% within 0.5km, 95% within 2.4km
  - Child (7-12 years): 50% within 1.3km, 95% within 3.8km
  - Hiker: 50% within 2km, 95% within 8km
  - Hunter: 50% within 3km, 95% within 10km
  - Elderly: 50% within 0.5km, 95% within 2.5km
  - Dementia: 50% within 0.3km, 95% within 2km
  - Despondent: 50% within 0.5km, 95% within 3km
  - Autistic: 50% within 0.6km, 95% within 2km
  - Mushroom Picker: 50% within 1.5km, 95% within 4km

#### Search Assignment Management
**Requirement:** Assign teams to segments and track progress
**Implementation:**
- Add team field to search area polygons
- Team assignment dialog
- Color coding by team
- Progress tracking per segment

#### Probability Mapping
**Requirement:** Visual representation of search priorities
**Implementation:**
- POA (Probability of Area) values for segments
- Heat map visualization
- Automatic POA calculation based on:
  - Distance from IPP
  - Terrain type
  - Subject category
  - Attractions (water, roads, structures)

### 3.2 Important Features (Priority 2)

#### Clue Management System
**Current:** Basic casualty markers
**Enhancement Needed:**
- Clue types (footprint, clothing, equipment, etc.)
- Clue certainty (confirmed, probable, possible)
- Time found
- Finder information
- Photo attachment capability
- Automatic bearing/distance from IPP

#### Hazard Marking
**Requirement:** Safety-critical information for teams
**Implementation:**
- Predefined hazard types with icons:
  - Cliff/Drop-off
  - Water hazard
  - Unstable ground
  - Dense vegetation
  - Wildlife danger
  - Weather exposure
- Hazard zones (polygons)
- Warning labels

#### Communication Planning
**Requirement:** Radio coverage and dead zones
**Implementation:**
- Repeater locations
- Dead zone marking
- Channel assignments per team
- Emergency frequencies display

### 3.3 Enhanced Features (Priority 3)

#### Time-Based Analysis
- Operational periods tracking
- Time at each status for segments
- Search duration per team
- Time-distance calculations

#### Resource Tracking
- Helicopter landing zones
- Staging areas
- Command post locations
- Medical stations
- Vehicle access points

#### Reporting and Export
- Segment assignment sheets
- Team briefing maps
- ICS forms (ICS-204 Assignment List)
- Mission summary statistics
- Search coverage analysis

---

## 4. Data Models

### 4.1 Search Area/Segment Model

```python
SearchSegment:
  - id: unique identifier
  - name: "Alpha", "Bravo", etc.
  - geometry: polygon
  - status: planned|assigned|in_progress|completed|suspended|cleared
  - team_assigned: team identifier
  - priority: high|medium|low
  - POA: 0-100% probability of area
  - POD: 0-100% probability of detection
  - terrain_type: easy|moderate|difficult|extreme
  - area_size: calculated in hectares/km²
  - search_method: grid|contour|sound_sweep|hasty
  - start_time: timestamp
  - end_time: timestamp
  - notes: text
```

### 4.2 Team Model

```python
Team:
  - id: unique identifier
  - name: "Team 1", "K9-1", etc.
  - type: ground|k9|mounted|aerial|water
  - size: number of members
  - leader: name
  - status: available|assigned|searching|returning
  - current_segment: segment_id
  - equipment: list of special equipment
  - medical_training: none|first_aid|emt|paramedic
  - contact_info: radio channel/phone
```

### 4.3 IPP/LKP Model

```python
InitialPlanningPoint:
  - coordinates: lat/lon and grid
  - timestamp: when last seen
  - subject_category: hiker|child|elderly|etc.
  - subject_name: identifier
  - subject_age: years
  - subject_condition: good|injured|medical_condition
  - weather_at_time: conditions
  - confidence_radius: meters
  - notes: additional information
```

---

## 5. UI/UX Considerations

### 5.1 SAR-Specific UI Patterns

#### Quick Access Tools
- **Emergency Actions:** One-click access to critical functions
- **Common Tasks:** Frequently used tools in main toolbar
- **Status Dashboard:** At-a-glance view of search progress

#### Field-Optimized Design
- **Large Buttons:** Usable with gloves
- **High Contrast:** Visible in bright sunlight
- **Minimal Clicks:** Reduce steps for common tasks
- **Offline First:** Full functionality without internet

### 5.2 Information Hierarchy

**Primary Display (Always Visible):**
- Mission status and elapsed time
- Active teams and locations
- Current operational period
- Next briefing time

**Secondary Display (One Click):**
- Search progress statistics
- Resource availability
- Weather conditions
- Hazard warnings

**Detailed View (On Demand):**
- Individual segment details
- Team assignments history
- Clue analysis
- Communication logs

### 5.3 Color Conventions

**Standard SAR Colors:**
- **Red:** Urgent/Emergency/Casualty
- **Orange:** Hazards/Warnings
- **Yellow:** Caution/Planned
- **Green:** Completed/Safe/Clear
- **Blue:** Information/Water/POI
- **Purple:** Command/Control
- **Black:** Boundaries/Constraints

---

## 6. Gap Analysis

### 6.1 Currently Implemented ✅
- Real-time device tracking
- POI and Casualty markers
- Coordinate conversion (Irish Grid ↔ WGS84)
- Distance and bearing measurement
- Mission timer and status tracking
- Auto-refresh and auto-save
- CSV data import

### 6.2 Planned (Phase 3) 🔨
- Line drawing tool
- Polygon/search area tool
- Range rings
- Bearing lines
- Sectors/wedges
- Text annotations
- GPX import

### 6.3 Critical Gaps to Address 🚨

#### Immediate Needs
1. **Standardized Terminology:** Update UI to use IPP, LKP, POA, POD
2. **Search Status Tracking:** Add status field to search areas
3. **Team Assignment:** Link teams to search segments
4. **LPB Statistics:** Implement subject categories and statistical rings

#### Short-term Needs
1. **Clue Management:** Expand beyond simple casualty markers
2. **Hazard Marking:** Safety-critical information display
3. **Search Patterns:** Grid, contour, sound sweep generation
4. **Progress Tracking:** POD calculation and coverage analysis

#### Long-term Enhancements
1. **Predictive Modeling:** Movement prediction based on terrain
2. **Resource Optimization:** Automatic segment generation
3. **Historical Analysis:** Previous search data integration
4. **Weather Integration:** Real-time weather overlay

---

## 7. Implementation Priorities

### Phase 1: Terminology and Status (Immediate)
**Effort:** Low | **Impact:** High
1. Update marker dialog to use "IPP/LKP" instead of generic "POI"
2. Add status dropdown to search area polygons
3. Implement standard SAR status values
4. Add subject category selector to IPP marker

### Phase 2: LPB Integration (Week 1-2)
**Effort:** Medium | **Impact:** High
1. Create LPB statistics database
2. Add automatic range ring generation from IPP
3. Implement subject category-based search radius
4. Add statistical search area overlay

### Phase 3: Team Management (Week 2-3)
**Effort:** Medium | **Impact:** High
1. Create team management panel
2. Link teams to search segments
3. Add assignment tracking
4. Implement team status updates

### Phase 4: Enhanced Search Planning (Week 3-4)
**Effort:** High | **Impact:** Medium
1. POA/POD calculations
2. Search pattern generation
3. Clue analysis tools
4. Hazard zone creation

### Phase 5: Reporting and Analysis (Week 4-5)
**Effort:** Medium | **Impact:** Medium
1. ICS form generation
2. Mission statistics dashboard
3. Coverage analysis maps
4. Export capabilities

---

## 8. Regional Considerations

### 8.1 Ireland-Specific Requirements

#### Coordinate Systems
- **Primary:** Irish Transverse Mercator (ITM/EPSG:29903) ✅ Already implemented
- **Secondary:** Irish Grid (IG/EPSG:29902) - Consider adding for compatibility with older maps
- **Format:** Support for traditional Irish Grid references (e.g., "O 123 456")

#### Organizations to Consider
- Irish Coast Guard (Maritime/Cliff rescue)
- Mountain Rescue Ireland (MRI)
- Irish Cave Rescue Organisation (ICRO)
- Civil Defence
- Order of Malta Ambulance Corps
- RNLI (Lifeboat operations)

#### Terrain Considerations
- Bog/Peatland (unique Irish hazard)
- Coastal cliffs
- Mountain terrain
- Lakes (Loughs)
- Dense forest plantations

### 8.2 International Compatibility

**Ensure Compatibility With:**
- UK Mountain Rescue (close cooperation with Irish teams)
- SARLOC system (UK SMS location system)
- European Emergency Number (112/999)
- International maritime standards (for coastal SAR)

---

## 9. Security and Safety Considerations

### 9.1 Data Protection
- Personal information of missing persons
- Team member contact details
- Sensitive location data
- Medical information

### 9.2 Operational Security
- Avoid public broadcast of search areas
- Protect active search details
- Secure communication channels
- Access control for different user roles

### 9.3 Safety Features
- Mandatory hazard acknowledgment
- Team check-in requirements
- Emergency evacuation routes
- Weather warning integration

---

## 10. Recommendations

### 10.1 Immediate Actions
1. **Update Terminology:** Align with international SAR standards
2. **Add Status Tracking:** Implement for all search areas
3. **Create LPB Database:** Build statistical model for Ireland
4. **Enhance Clue System:** Expand beyond basic markers

### 10.2 Development Priorities
1. **Focus on Field Usability:** Optimize for stress/emergency use
2. **Maintain Simplicity:** Don't over-engineer features
3. **Ensure Offline Capability:** Full functionality without internet
4. **Build Incrementally:** Release useful features early and often

### 10.3 Collaboration Opportunities
1. **Engage with Mountain Rescue Ireland:** Get direct user feedback
2. **Test with Real Teams:** Field trials with actual SAR units
3. **Share Open Source:** Contribute back to SAR community
4. **Document Thoroughly:** Help other regions adapt the tool

---

## Appendix A: Search Patterns

### Common SAR Search Patterns to Consider

1. **Grid Search**
   - Parallel lines with defined spacing
   - High POD for thorough coverage
   - Used in open terrain

2. **Contour Search**
   - Following elevation contours
   - Efficient for hillside/mountain terrain
   - Natural travel paths

3. **Expanding Square**
   - Outward spiral from IPP
   - Good for limited resources
   - Quick initial coverage

4. **Sound Sweep**
   - Line of searchers with voice/whistle
   - Wide spacing for rapid coverage
   - Lower POD but fast

5. **Hasty Search**
   - High-probability areas first
   - Natural routes and attractions
   - Quick initial search

---

## Appendix B: Lost Person Behavior Statistics

### Statistical Search Distances by Category

| Subject Category | 25% Zone | 50% Zone | 75% Zone | 95% Zone |
|-----------------|----------|----------|----------|----------|
| Child 1-3 yrs | 0.1 km | 0.3 km | 0.7 km | 1.9 km |
| Child 4-6 yrs | 0.2 km | 0.5 km | 1.1 km | 2.4 km |
| Child 7-12 yrs | 0.5 km | 1.3 km | 2.5 km | 3.8 km |
| Hiker | 0.8 km | 2.0 km | 4.0 km | 8.0 km |
| Hunter | 1.2 km | 3.0 km | 5.5 km | 10.0 km |
| Elderly | 0.2 km | 0.5 km | 1.2 km | 2.5 km |
| Dementia | 0.1 km | 0.3 km | 0.8 km | 2.0 km |
| Despondent | 0.2 km | 0.5 km | 1.5 km | 3.0 km |
| Autistic | 0.2 km | 0.6 km | 1.2 km | 2.0 km |

*Note: These are general statistics. Actual distances vary based on terrain, weather, and individual factors.*

---

## Appendix C: Resource Links

### Further Reading
- IAMSAR Manual (IMO/ICAO publication)
- "Lost Person Behavior" by Robert Koester
- Mountain Rescue Association guidelines
- National Association for Search and Rescue (NASAR) resources
- Irish Mountain Rescue training materials

### Software References
- CalTopo/SARTopo (caltopo.com)
- SARLOC (UK system)
- FIND (Swiss rescue app)
- what3words (location reference system)

---

## Document History

- **2025-10-18:** Initial report created based on research and analysis
- **Author:** SAR Tracker Development Team
- **Review Status:** Ready for team review

---

*This report is based on publicly available information and best practices in search and rescue operations. Specific procedures should always follow local protocols and official training.*