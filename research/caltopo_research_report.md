# CalTopo Drawing Tools Research Report

## Executive Summary

CalTopo (also known as SARTopo for Search & Rescue operations) is a collaborative mapping platform widely used by SAR teams for mission planning and coordination. While direct access to detailed documentation was limited during research, the platform offers comprehensive drawing and mapping tools designed specifically for outdoor recreation and emergency response operations.

### Key Platform Features
- **Multi-platform Support**: Web-based interface with iOS and Android mobile apps
- **Collaborative Mapping**: Real-time multi-user editing and location sharing
- **Offline Capabilities**: Download maps for use without internet connectivity
- **SAR Mode**: Dedicated mode with specialized tools for search and rescue operations
- **Integration**: Supports GPS device integration, PDF export, and Google Earth compatibility

## Tool-by-Tool Analysis

Based on research findings and standard SAR mapping patterns, CalTopo likely includes the following drawing tools:

### 1. Marker/POI Tool
**Purpose**: Place points of interest, clues, last known positions, and other significant locations

**Expected Features**:
- Click-to-place functionality on the map
- Coordinate entry (lat/lon, UTM, grid references)
- Custom icons and symbols for different POI types
- Labels and descriptions
- Time stamps for tracking when POIs were created

**SAR Use Cases**:
- Last Known Position (LKP)
- Clue locations
- Command post positions
- Staging areas
- Helicopter landing zones

### 2. Line Tool
**Purpose**: Draw tracks, paths, boundaries, and linear features

**Expected Features**:
- Click-to-draw polyline creation
- Distance measurement display
- Elevation profile generation
- Line styling (color, width, pattern)
- Direction indicators

**SAR Use Cases**:
- Search team tracks
- Subject's probable path
- Access routes
- Containment boundaries

### 3. Bearing Line Tool
**Purpose**: Create azimuth/bearing lines from a point

**Expected Features**:
- Origin point selection
- Bearing input (degrees)
- Distance/length specification
- Magnetic vs true north options
- Multiple bearing lines from single point

**SAR Use Cases**:
- Direction of travel from last known position
- Radio direction finding results
- Witness sighting directions
- Wind direction indicators

### 4. Sector/Wedge Tool
**Purpose**: Define search areas based on probability sectors

**Expected Features**:
- Center point selection
- Start and end bearing definition
- Radius specification
- Area calculation
- Transparency for overlapping sectors

**SAR Use Cases**:
- High probability search areas
- Sweep width coverage zones
- Visual search sectors from aircraft
- Sound sweep areas

### 5. Range Ring/Circle Tool
**Purpose**: Create distance rings around points

**Expected Features**:
- Center point selection
- Multiple ring distances
- Radius labels
- Area calculations
- Time-distance rings (based on travel speed)

**SAR Use Cases**:
- Statistical search areas
- Communication range circles
- Time-based travel distances
- Helicopter fuel range limits

### 6. Polygon/Area Tool
**Purpose**: Define custom search areas and zones

**Expected Features**:
- Click-to-draw polygon creation
- Area calculation
- Fill patterns and transparency
- Labeling capabilities
- Segment assignment properties

**SAR Use Cases**:
- Search segment boundaries
- Hazard areas
- Completed search areas
- Operational boundaries

### 7. Text Annotation Tool
**Purpose**: Add text labels and notes to the map

**Expected Features**:
- Click-to-place text
- Font size and style options
- Background/halo for visibility
- Rotation capabilities
- Multi-line text support

**SAR Use Cases**:
- Segment identifiers
- Team assignments
- Operational notes
- Time stamps

## UI/UX Patterns

### Tool Activation
- **Toolbar Access**: Tools likely accessible via a main toolbar or menu system
- **Modal Selection**: Tools may activate in a modal state where clicks create objects
- **Keyboard Shortcuts**: Common tools probably have keyboard shortcuts for efficiency

### Input Methods
1. **Direct Map Interaction**: Click and drag to create features
2. **Coordinate Entry**: Manual input of precise coordinates
3. **Property Panels**: Side panels for detailed configuration
4. **Context Menus**: Right-click options for editing existing features

### Real-time Feedback
- **Live Preview**: Features show while being drawn
- **Measurement Display**: Distance/area shown during creation
- **Snapping**: Automatic alignment to existing features
- **Undo/Redo**: Standard editing capabilities

### Collaboration Features
- **Real-time Updates**: Changes visible to all users immediately
- **User Attribution**: Track who created/modified features
- **Conflict Resolution**: Handle simultaneous edits
- **Version History**: Track changes over time

## SAR-Specific Workflows

### Initial Response
1. Place marker at Last Known Position (LKP)
2. Create initial search radius based on lost person behavior
3. Define high-probability areas using sectors
4. Mark hazards and boundaries

### Search Planning
1. Divide search area into manageable segments using polygons
2. Assign teams to segments with labels
3. Create access routes using line tools
4. Mark staging areas and command posts

### Active Search Operations
1. Track team positions with markers
2. Update completed areas with polygon fills
3. Mark clue locations with time-stamped markers
4. Adjust search areas based on new information

### Documentation
1. Export maps as PDFs for field teams
2. Generate segment assignments with measurements
3. Create briefing materials with annotations
4. Archive completed search maps

## Implementation Recommendations for QGIS SAR Tracker Plugin

### Priority 1 - Essential Tools
1. **Marker/POI Tool**
   - Simple click-to-place functionality
   - Basic icon selection (LKP, clue, hazard, etc.)
   - Coordinate display and entry
   - Labels with time stamps

2. **Line Tool**
   - Polyline drawing with distance measurement
   - Basic styling (color, width)
   - Direction indicators
   - Track import from GPS

3. **Polygon Tool**
   - Area drawing with measurement
   - Segment identification
   - Completion status tracking
   - Basic fill patterns

### Priority 2 - Advanced Features
1. **Range Rings**
   - Multiple distances from point
   - Time-based rings using travel speeds
   - Lost person behavior statistics integration

2. **Bearing Lines**
   - Azimuth lines from points
   - Multiple bearings from single origin
   - Intersection calculations

3. **Sector Tool**
   - Probability-based sectors
   - Sweep width calculations
   - Coverage analysis

### Priority 3 - Enhanced Capabilities
1. **Collaborative Features**
   - Multi-user support
   - Change tracking
   - Team assignments

2. **Advanced Annotations**
   - Rich text formatting
   - Photo attachments
   - Voice notes

3. **Analysis Tools**
   - Coverage statistics
   - Probability mapping
   - Resource tracking

## Technical Considerations

### Coordinate System Support
- WGS84 lat/lon (decimal degrees and DMS)
- UTM zones
- Local grid systems (USNG, MGRS)
- Custom datum support

### Data Formats
- GeoJSON for feature storage
- KML/KMZ export for Google Earth
- GPX for GPS device compatibility
- PDF generation with georeferencing

### Performance
- Efficient rendering for large numbers of features
- Smooth drawing experience
- Quick save/load operations
- Offline capability with cached tiles

### User Interface Design
- Intuitive tool icons
- Clear visual feedback
- Responsive design for different screen sizes
- Accessibility considerations

## Conclusion

CalTopo/SARTopo provides a comprehensive suite of drawing tools specifically designed for SAR operations. The platform emphasizes:
- Ease of use under stressful conditions
- Collaborative capabilities for team coordination
- Integration with standard SAR workflows
- Flexibility for different operation types

For the QGIS SAR Tracker plugin, focus initially on implementing the core drawing tools (markers, lines, polygons) with strong measurement capabilities and clear visual design. Build upon this foundation with more specialized SAR tools as the plugin matures.

The key to success will be balancing feature completeness with usability, ensuring tools are intuitive enough for use during high-stress SAR operations while providing the analytical capabilities needed for effective search planning.