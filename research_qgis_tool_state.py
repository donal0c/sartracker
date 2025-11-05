"""
Research script for QGIS map tool state management.
This script investigates what happens after unsetMapTool() is called.
"""

from qgis.gui import QgsMapToolPan, QgsMapTool
from qgis.core import QgsProject
from qgis.PyQt.QtCore import QObject, pyqtSignal


def investigate_tool_state(iface):
    """
    Investigation of QGIS map tool state management.

    Key Questions:
    1. What happens when canvas.mapTool() is None?
    2. Should we explicitly set a pan tool after deactivation?
    3. How does QGIS handle mouse events with no active tool?
    """

    canvas = iface.mapCanvas()

    print("=" * 80)
    print("QGIS MAP TOOL STATE INVESTIGATION")
    print("=" * 80)

    # Check current tool state
    current_tool = canvas.mapTool()
    print(f"\n1. Current map tool: {current_tool}")
    print(f"   Tool type: {type(current_tool).__name__ if current_tool else 'None'}")

    # Test unsetMapTool behavior
    if current_tool:
        print("\n2. Testing unsetMapTool()...")
        canvas.unsetMapTool(current_tool)

        after_unset = canvas.mapTool()
        print(f"   After unset - Tool: {after_unset}")
        print(f"   Tool is None: {after_unset is None}")

    # Try to create and set a pan tool
    print("\n3. Creating and setting QgsMapToolPan...")
    pan_tool = QgsMapToolPan(canvas)
    canvas.setMapTool(pan_tool)

    new_tool = canvas.mapTool()
    print(f"   After setting pan tool: {new_tool}")
    print(f"   Is it the pan tool? {new_tool is pan_tool}")

    # Check if iface provides access to default tools
    print("\n4. Checking iface for default tools...")

    # Look for action-based tools
    if hasattr(iface, 'actionPan'):
        print("   iface.actionPan() exists!")
        action = iface.actionPan()
        print(f"   Pan action: {action}")
        print(f"   Is checked: {action.isChecked() if action else 'N/A'}")

        # Try to trigger the pan action
        if action:
            action.trigger()
            print(f"   Triggered pan action")
            print(f"   Current tool after trigger: {canvas.mapTool()}")

    # Check for other standard tools
    standard_tools = ['actionPan', 'actionZoomIn', 'actionZoomOut',
                     'actionZoomToFullExtent', 'actionSelect']

    print("\n5. Available standard tool actions in iface:")
    for tool_name in standard_tools:
        if hasattr(iface, tool_name):
            print(f"   - {tool_name}: Available")

    # Monitor tool changes
    print("\n6. Setting up tool change monitoring...")

    def on_tool_set(tool, old_tool):
        print(f"   Tool changed: {type(old_tool).__name__ if old_tool else 'None'} -> "
              f"{type(tool).__name__ if tool else 'None'}")

    # Note: mapToolSet signal might have different signatures in different QGIS versions
    try:
        canvas.mapToolSet.connect(lambda tool: on_tool_set(tool, None))
        print("   Connected to mapToolSet signal")
    except:
        print("   Could not connect to mapToolSet signal")

    print("\n" + "=" * 80)
    print("RECOMMENDATIONS BASED ON INVESTIGATION:")
    print("=" * 80)

    print("""
1. After unsetMapTool(), the canvas.mapTool() becomes None
2. QGIS does NOT automatically set a default tool
3. Mouse events are not processed when tool is None
4. Best practice: Explicitly set a pan tool after deactivation

SOLUTION:
---------
After calling canvas.unsetMapTool(tool), immediately set the pan tool:

    # Option 1: Use iface action (if available)
    if hasattr(iface, 'actionPan'):
        iface.actionPan().trigger()

    # Option 2: Create and set a pan tool directly
    else:
        pan_tool = QgsMapToolPan(canvas)
        canvas.setMapTool(pan_tool)

This ensures the canvas remains responsive and the cursor behaves correctly.
""")

    return {
        'has_none_state': after_unset is None if 'after_unset' in locals() else None,
        'has_pan_action': hasattr(iface, 'actionPan'),
        'pan_tool_works': new_tool is pan_tool if 'new_tool' in locals() else False
    }


# Example usage in plugin
class ImprovedToolRegistry:
    """Example of improved tool deactivation handling."""

    def __init__(self, iface):
        self.iface = iface
        self.canvas = iface.mapCanvas()
        self.pan_tool = None

    def deactivate_current(self):
        """Improved deactivation that sets pan tool."""
        if self.active_tool:
            # Deactivate current tool
            if hasattr(self.active_tool, 'deactivate'):
                self.active_tool.deactivate()

            # Unset the tool
            self.canvas.unsetMapTool(self.active_tool)

            # IMPORTANT: Set pan tool to keep canvas responsive
            self._set_default_tool()

            self.active_tool = None

    def _set_default_tool(self):
        """Set the default pan tool after deactivation."""
        # Try to use iface action first (preserves toolbar state)
        if hasattr(self.iface, 'actionPan'):
            self.iface.actionPan().trigger()
        else:
            # Fallback: Create pan tool if needed
            if not self.pan_tool:
                self.pan_tool = QgsMapToolPan(self.canvas)
            self.canvas.setMapTool(self.pan_tool)


if __name__ == "__console__":
    # Run investigation when executed in QGIS Python console
    import qgis.utils
    results = investigate_tool_state(qgis.utils.iface)
    print(f"\nInvestigation complete. Results: {results}")