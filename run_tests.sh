#!/bin/bash
# Run pytest with QGIS environment properly configured
# Usage: ./run_tests.sh [pytest args]

QGIS_APP="/Applications/QGIS-LTR.app"
QGIS_MACOS="$QGIS_APP/Contents/MacOS"
QGIS_RESOURCES="$QGIS_APP/Contents/Resources"
QGIS_FRAMEWORKS="$QGIS_APP/Contents/Frameworks"
VENV_SITE="$(pwd)/.venv/lib/python3.9/site-packages"

# Set library paths
export DYLD_LIBRARY_PATH="$QGIS_MACOS/lib:$QGIS_FRAMEWORKS:${DYLD_LIBRARY_PATH:-}"

# Set data paths for PROJ and GDAL
export PROJ_LIB="$QGIS_RESOURCES/proj"
export GDAL_DATA="$QGIS_RESOURCES/gdal"

# Set Python path - venv site-packages FIRST, then QGIS
# This ensures venv packages (pytest 8.x) take precedence over QGIS system packages (pytest 6.x)
export PYTHONPATH="$VENV_SITE:$QGIS_MACOS/lib/python3.9:$QGIS_MACOS/lib/python3.9/site-packages:${PYTHONPATH:-}"

# Use the venv Python (which has --system-site-packages)
PYTHON=".venv/bin/python"

# Run pytest with all arguments passed through
exec "$PYTHON" -m pytest "$@"
