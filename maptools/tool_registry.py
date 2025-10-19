# -*- coding: utf-8 -*-
"""
Tool Registry

Manages activation and deactivation of SAR drawing tools.
Ensures only one tool is active at a time.

Qt5/Qt6 Compatible: Uses qgis.PyQt for all Qt imports.
"""

from qgis.PyQt.QtCore import QObject, pyqtSignal
from qgis.gui import QgsMapToolPan


class ToolRegistry(QObject):
    """
    Central registry for managing SAR drawing tools.

    Ensures:
    - Only one tool active at a time
    - Proper cleanup when switching tools
    - Tool state tracking
    - UI updates via signals
    - Canvas remains responsive after tool deactivation

    Signals:
        tool_activated: Emitted when a tool is activated (tool_name: str)
        tool_deactivated: Emitted when a tool is deactivated (tool_name: str)
    """

    tool_activated = pyqtSignal(str)  # tool_name
    tool_deactivated = pyqtSignal(str)  # tool_name

    def __init__(self, canvas, iface=None):
        """
        Initialize tool registry.

        Args:
            canvas: QGIS map canvas
            iface: QGIS interface (optional, for accessing toolbar actions)
        """
        super().__init__()
        self.canvas = canvas
        self.iface = iface
        self.tools = {}  # Dict of {tool_name: tool_instance}
        self.active_tool_name = None
        self.active_tool = None
        self._pan_tool = None  # Cached pan tool for fallback

    def register_tool(self, name, tool_instance):
        """
        Register a drawing tool.

        Args:
            name: Unique tool name (e.g., 'line', 'polygon', 'range_ring')
            tool_instance: Instance of a map tool (QgsMapTool or subclass)
        """
        self.tools[name] = tool_instance

    def activate_tool(self, name):
        """
        Activate a drawing tool by name.

        Args:
            name: Tool name to activate

        Returns:
            bool: True if activated successfully, False if tool not found
        """
        print(f"[REGISTRY] activate_tool('{name}') called")
        print(f"[REGISTRY] Currently active tool: {self.active_tool_name}")
        print(f"[REGISTRY] Canvas current tool: {self.canvas.mapTool()}")

        if name not in self.tools:
            print(f"[REGISTRY] ERROR: Tool '{name}' not registered!")
            return False

        # Deactivate current tool if one is active
        if self.active_tool:
            print(f"[REGISTRY] Deactivating current tool '{self.active_tool_name}'...")
            try:
                # Explicitly deactivate the tool to ensure cleanup
                if hasattr(self.active_tool, 'deactivate'):
                    self.active_tool.deactivate()
                self.canvas.unsetMapTool(self.active_tool)
                # Don't set pan tool here - we're about to set a new tool
                self.tool_deactivated.emit(self.active_tool_name)
                print(f"[REGISTRY] Previous tool deactivated")
            except Exception as e:
                print(f"[REGISTRY] ERROR deactivating tool {self.active_tool_name}: {e}")
                import traceback
                traceback.print_exc()

        # Activate new tool
        print(f"[REGISTRY] Activating new tool '{name}'...")
        self.active_tool = self.tools[name]
        self.active_tool_name = name
        try:
            print(f"[REGISTRY] Calling canvas.setMapTool()...")
            self.canvas.setMapTool(self.active_tool)
            print(f"[REGISTRY] canvas.setMapTool() complete")
            print(f"[REGISTRY] Canvas current tool after set: {self.canvas.mapTool()}")
            print(f"[REGISTRY] Emitting tool_activated signal...")
            self.tool_activated.emit(name)
            print(f"[REGISTRY] Tool '{name}' activated successfully")
            return True
        except Exception as e:
            print(f"[REGISTRY] ERROR activating tool {name}: {e}")
            import traceback
            traceback.print_exc()
            self.active_tool = None
            self.active_tool_name = None
            return False

    def deactivate_current(self):
        """Deactivate the currently active tool and set default pan tool."""
        print(f"[REGISTRY] deactivate_current() called")
        print(f"[REGISTRY] Active tool: {self.active_tool}")
        print(f"[REGISTRY] Active tool name: {self.active_tool_name}")
        print(f"[REGISTRY] Canvas current tool: {self.canvas.mapTool()}")

        if self.active_tool:
            try:
                # Explicitly deactivate the tool to ensure cleanup
                if hasattr(self.active_tool, 'deactivate'):
                    print(f"[REGISTRY] Calling tool.deactivate()...")
                    self.active_tool.deactivate()
                    print(f"[REGISTRY] tool.deactivate() complete")

                print(f"[REGISTRY] Calling canvas.unsetMapTool()...")
                self.canvas.unsetMapTool(self.active_tool)
                print(f"[REGISTRY] canvas.unsetMapTool() complete")
                print(f"[REGISTRY] Canvas current tool after unset: {self.canvas.mapTool()}")

                # CRITICAL: Set pan tool to keep canvas responsive
                print(f"[REGISTRY] Setting default pan tool...")
                self._set_default_tool()
                print(f"[REGISTRY] Canvas tool after setting default: {self.canvas.mapTool()}")

                print(f"[REGISTRY] Emitting tool_deactivated signal...")
                self.tool_deactivated.emit(self.active_tool_name)
                print(f"[REGISTRY] Signal emitted")
            except Exception as e:
                print(f"[REGISTRY] ERROR deactivating current tool: {e}")
                import traceback
                traceback.print_exc()
            finally:
                print(f"[REGISTRY] Clearing active_tool references...")
                self.active_tool = None
                self.active_tool_name = None
                print(f"[REGISTRY] deactivate_current() complete")
        else:
            print(f"[REGISTRY] No active tool to deactivate")

    def _set_default_tool(self):
        """
        Set the default pan tool to keep canvas interactive.

        After unsetMapTool(), the canvas has no active tool (None) which makes it
        unresponsive to mouse events. This method ensures a pan tool is always active.
        """
        try:
            # Option 1: Use iface action if available (preserves toolbar state)
            if self.iface and hasattr(self.iface, 'actionPan'):
                self.iface.actionPan().trigger()
                print("[REGISTRY] Set default tool via iface.actionPan()")
            else:
                # Option 2: Create and set pan tool directly
                if not self._pan_tool:
                    self._pan_tool = QgsMapToolPan(self.canvas)
                self.canvas.setMapTool(self._pan_tool)
                print("[REGISTRY] Set default tool via QgsMapToolPan")
        except Exception as e:
            print(f"[REGISTRY] ERROR setting default tool: {e}")
            # Even if setting pan tool fails, we've at least unset the previous tool

    def get_active_tool_name(self):
        """
        Get name of currently active tool.

        Returns:
            str: Tool name or None if no tool is active
        """
        return self.active_tool_name

    def is_tool_active(self, name):
        """
        Check if a specific tool is active.

        Args:
            name: Tool name to check

        Returns:
            bool: True if the specified tool is active
        """
        return self.active_tool_name == name

    def get_registered_tools(self):
        """
        Get list of all registered tool names.

        Returns:
            list: List of registered tool names
        """
        return list(self.tools.keys())
