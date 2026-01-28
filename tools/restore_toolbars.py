"""Restore QGIS to default toolbars only."""
from qgis.utils import iface
from qgis.PyQt.QtWidgets import QToolBar

mw = iface.mainWindow()
default_toolbars = ['mFileToolBar', 'mMapNavToolBar', 'mAttributesToolBar', 'mDigitizeToolBar', 'mAdvancedDigitizeToolBar', 'mLabelToolBar', 'mPluginToolBar', 'mHelpToolBar', 'mProjectToolBar', 'mSelectionToolBar', 'mDataSourceManagerToolBar']
for tb in mw.findChildren(QToolBar):
    tb.setVisible(tb.objectName() in default_toolbars)
print("Default toolbars restored")
