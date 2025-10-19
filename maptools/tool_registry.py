# -*- coding: utf-8 -*-
"""
Tool Registry

Manages activation and deactivation of SAR drawing tools.
Ensures only one tool is active at a time.

Qt5/Qt6 Compatible: Uses qgis.PyQt for all Qt imports.
"""

from qgis.PyQt.QtCore import QObject, pyqtSignal


class ToolRegistry(QObject):
    """
    Central registry for managing SAR drawing tools.

    Ensures:
    - Only one tool active at a time
    - Proper cleanup when switching tools
    - Tool state tracking
    - UI updates via signals

    Signals:
        tool_activated: Emitted when a tool is activated (tool_name: str)
        tool_deactivated: Emitted when a tool is deactivated (tool_name: str)
    """

    tool_activated = pyqtSignal(str)  # tool_name
    tool_deactivated = pyqtSignal(str)  # tool_name

    def __init__(self, canvas):
        """
        Initialize tool registry.

        Args:
            canvas: QGIS map canvas
        """
        super().__init__()
        self.canvas = canvas
        self.tools = {}  # Dict of {tool_name: tool_instance}
        self.active_tool_name = None
        self.active_tool = None

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
        if name not in self.tools:
            return False

        # Deactivate current tool if one is active
        if self.active_tool:
            try:
                # Explicitly deactivate the tool to ensure cleanup
                if hasattr(self.active_tool, 'deactivate'):
                    self.active_tool.deactivate()
                self.canvas.unsetMapTool(self.active_tool)
                self.tool_deactivated.emit(self.active_tool_name)
            except Exception as e:
                print(f"Error deactivating tool {self.active_tool_name}: {e}")

        # Activate new tool
        self.active_tool = self.tools[name]
        self.active_tool_name = name
        try:
            self.canvas.setMapTool(self.active_tool)
            self.tool_activated.emit(name)
            return True
        except Exception as e:
            print(f"Error activating tool {name}: {e}")
            self.active_tool = None
            self.active_tool_name = None
            return False

    def deactivate_current(self):
        """Deactivate the currently active tool."""
        if self.active_tool:
            try:
                # Explicitly deactivate the tool to ensure cleanup
                if hasattr(self.active_tool, 'deactivate'):
                    self.active_tool.deactivate()
                self.canvas.unsetMapTool(self.active_tool)
                self.tool_deactivated.emit(self.active_tool_name)
            except Exception as e:
                print(f"Error deactivating current tool: {e}")
            finally:
                self.active_tool = None
                self.active_tool_name = None

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
