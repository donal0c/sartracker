# -*- coding: utf-8 -*-
"""
GPX Import Utilities

Provides validation and import functions for GPX track files.

LIFE-SAFETY CRITICAL: All validation and error handling follows SAR Tracker
defensive programming patterns. Invalid GPX files are rejected with clear
error messages.

Qt5/Qt6 Compatible: Uses qgis.PyQt imports and QGIS core APIs only.
"""

import os
import re
import logging
from typing import Optional, Tuple, Dict, Any

from qgis.core import (
    QgsVectorLayer,
    QgsProject,
    QgsLayerTreeGroup,
    QgsCoordinateReferenceSystem,
)

logger = logging.getLogger(__name__)

# GPX files are always WGS84 (EPSG:4326)
GPX_CRS = QgsCoordinateReferenceSystem("EPSG:4326")

# Defensive limits
MAX_GPX_FILE_SIZE_MB = 100
MAX_GPX_FILE_SIZE_BYTES = MAX_GPX_FILE_SIZE_MB * 1024 * 1024


def validate_gpx_file(gpx_path: str) -> Tuple[bool, str, Dict[str, Any]]:
    """
    Validate a GPX file without fully importing it.

    LIFE-SAFETY CRITICAL: Validates all inputs before attempting import.

    Args:
        gpx_path: Absolute path to GPX file

    Returns:
        Tuple of (is_valid, error_message, metadata_dict)

        metadata_dict contains:
            - tracks: int (number of tracks, 0 if validation failed)
            - waypoints: int (number of waypoints)
            - routes: int (number of routes)
            - creator: str or None (creator name if found)
            - file_size_kb: float

    Qt5/Qt6 Compatible: Uses QGIS core APIs only.
    """
    metadata = {
        'tracks': 0,
        'waypoints': 0,
        'routes': 0,
        'creator': None,
        'file_size_kb': 0.0
    }

    # Validate path is provided
    if not gpx_path:
        return False, "GPX path is empty", metadata

    # Validate path is absolute
    if not os.path.isabs(gpx_path):
        return False, f"GPX path must be absolute: {gpx_path}", metadata

    # Check file exists
    if not os.path.exists(gpx_path):
        return False, f"GPX file not found: {gpx_path}", metadata

    # Check is file (not directory)
    if not os.path.isfile(gpx_path):
        return False, f"Path is not a file: {gpx_path}", metadata

    # Check .gpx extension
    if not gpx_path.lower().endswith('.gpx'):
        return False, f"File does not have .gpx extension: {gpx_path}", metadata

    # Check file is readable and get size
    try:
        file_size = os.path.getsize(gpx_path)
        metadata['file_size_kb'] = file_size / 1024.0

        if file_size == 0:
            return False, f"GPX file is empty: {gpx_path}", metadata

        if file_size > MAX_GPX_FILE_SIZE_BYTES:
            logger.warning(
                f"Large GPX file ({file_size / 1024 / 1024:.1f}MB): {gpx_path}"
            )
            # Don't reject, just warn - some missions have large tracks

    except OSError as e:
        return False, f"Cannot access GPX file: {e}", metadata

    # Extract creator metadata (lightweight - just reads header)
    try:
        metadata['creator'] = _extract_gpx_creator(gpx_path)
    except Exception as e:
        logger.debug(f"Could not extract GPX creator from {gpx_path}: {e}")

    # Count features in each layer type using QGIS
    # This validates the GPX is parseable
    for layer_type in ['tracks', 'waypoints', 'routes']:
        uri = f"{gpx_path}|layername={layer_type}"
        temp_layer = QgsVectorLayer(uri, "temp", "ogr")

        if temp_layer.isValid():
            metadata[layer_type] = temp_layer.featureCount()

    # Check if file contains any geographic data
    if metadata['tracks'] == 0 and metadata['waypoints'] == 0 and metadata['routes'] == 0:
        return False, "GPX file contains no tracks, waypoints, or routes", metadata

    return True, "", metadata


def import_gpx_track(
    gpx_path: str,
    layer_name: Optional[str] = None,
    parent_group: Optional[QgsLayerTreeGroup] = None
) -> Tuple[Optional[QgsVectorLayer], str]:
    """
    Import GPX tracks as a QGIS vector layer.

    LIFE-SAFETY CRITICAL: Validates all inputs and provides detailed error messages.

    Strategy: One layer per GPX file (all tracks in file consolidated).

    Args:
        gpx_path: Absolute path to GPX file
        layer_name: Optional custom layer name (defaults to filename or GPX metadata)
        parent_group: Optional layer tree group to add layer to

    Returns:
        Tuple of (layer, error_message). Layer is None if import failed.

    Qt5/Qt6 Compatible: Uses QGIS core APIs only.
    """
    # Validate the GPX file first
    is_valid, error_msg, metadata = validate_gpx_file(gpx_path)

    if not is_valid:
        logger.warning(f"GPX validation failed: {error_msg}")
        return None, error_msg

    # Check if file contains tracks
    if metadata['tracks'] == 0:
        return None, f"GPX file contains no tracks: {gpx_path}"

    # Determine layer name
    if not layer_name:
        # Try to use creator/metadata name, fallback to filename
        if metadata.get('creator'):
            layer_name = metadata['creator']
        else:
            # Use filename without extension
            layer_name = os.path.splitext(os.path.basename(gpx_path))[0]

    # Sanitize layer name (remove problematic characters)
    layer_name = _sanitize_layer_name(layer_name)

    # Load tracks using OGR driver (recommended for production)
    # This loads ALL tracks in the GPX file as a single layer
    uri = f"{gpx_path}|layername=tracks"
    layer = QgsVectorLayer(uri, layer_name, "ogr")

    if not layer.isValid():
        # Fallback: try native GPX provider
        logger.debug(f"OGR driver failed for {gpx_path}, trying native GPX provider")
        uri_native = f"{gpx_path}?type=track"
        layer = QgsVectorLayer(uri_native, layer_name, "gpx")

        if not layer.isValid():
            error_detail = layer.error().message() if layer.error() else "unknown error"
            return None, f"Failed to parse GPX file: {error_detail}"

    # Double-check layer has features (should not happen after validation, but defensive)
    if layer.featureCount() == 0:
        return None, f"GPX file contains no track features: {gpx_path}"

    # Add to project
    if parent_group:
        # Add to specified group
        QgsProject.instance().addMapLayer(layer, False)
        parent_group.addLayer(layer)
    else:
        # Add to root
        QgsProject.instance().addMapLayer(layer)

    logger.info(
        f"Imported GPX track: {layer_name} "
        f"({layer.featureCount()} features, {metadata['file_size_kb']:.1f}KB)"
    )

    return layer, ""


def _extract_gpx_creator(gpx_path: str) -> Optional[str]:
    """
    Extract creator/name from GPX metadata.

    Parses first 4KB of file to find creator attribute or name element
    without loading entire file into memory.

    Args:
        gpx_path: Path to GPX file

    Returns:
        Creator name or None if not found

    Note: This is a best-effort extraction. Failures are logged but not fatal.
    """
    try:
        # Try multiple encodings (GPX spec requires UTF-8 but devices vary)
        encodings = ['utf-8', 'utf-8-sig', 'latin-1', 'windows-1252']

        header = None
        for encoding in encodings:
            try:
                with open(gpx_path, 'r', encoding=encoding, errors='replace') as f:
                    # Read just the header (first 4KB should contain metadata)
                    header = f.read(4096)
                    break
            except (UnicodeDecodeError, OSError):
                continue

        if not header:
            return None

        # Look for creator attribute: creator="..." or creator='...'
        match = re.search(r'creator=["\']([^"\']+)["\']', header)
        if match:
            creator = match.group(1).strip()
            if creator and len(creator) < 100:  # Sanity check
                return creator

        # Alternative: look for <name> in GPX header
        match = re.search(r'<name>([^<]+)</name>', header)
        if match:
            name = match.group(1).strip()
            if name and len(name) < 100:
                return name

    except Exception as e:
        logger.debug(f"Could not extract GPX creator from {gpx_path}: {e}")

    return None


def _sanitize_layer_name(name: str) -> str:
    """
    Sanitize a string for use as a QGIS layer name.

    Removes characters that could cause issues in layer names or file systems.

    Args:
        name: Raw name string

    Returns:
        Sanitized name suitable for QGIS layer
    """
    if not name:
        return "GPX_Track"

    # Replace problematic characters with underscore
    # These can cause issues in QGIS layer tree or file systems
    sanitized = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', name)

    # Collapse multiple underscores
    sanitized = re.sub(r'_+', '_', sanitized)

    # Strip leading/trailing whitespace and underscores
    sanitized = sanitized.strip().strip('_')

    # Limit length (QGIS layer names can be long, but be reasonable)
    if len(sanitized) > 100:
        sanitized = sanitized[:100]

    # Fallback if sanitization resulted in empty string
    if not sanitized:
        return "GPX_Track"

    return sanitized
