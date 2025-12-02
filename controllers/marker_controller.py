# -*- coding: utf-8 -*-
"""
Marker Interaction Controller

Handles marker CRUD workflows and attachment handling outside the main plugin
class for better testability and separation of concerns.
"""

from pathlib import Path
from typing import Callable, Dict, Optional

from qgis.PyQt.QtCore import QUrl
from qgis.PyQt.QtWidgets import QMessageBox
from qgis.PyQt.QtGui import QDesktopServices

from ..ui.marker_dialog import MarkerDialog
from ..ui.marker_log_widget import MarkerLogWidget
from ..utils.notify import success, warning, error
from ..utils.qt_compat import dialog_exec, DialogAccepted, MessageBoxYes, MessageBoxNo
from ..utils.exceptions import LayerTransactionError


class MarkerController:
    """Encapsulates marker add/edit/delete flows and attachment handling."""

    def __init__(
        self,
        iface,
        layers_controller,
        ingest_attachment: Callable[[Optional[str]], Optional[str]],
        refresh_log: Optional[Callable[[], None]] = None,
        get_mission_directory: Optional[Callable[[], Optional[Path]]] = None
    ):
        self.iface = iface
        self.layers_controller = layers_controller
        self._ingest_attachment = ingest_attachment
        self._refresh_log = refresh_log or (lambda: None)
        self._get_mission_directory = get_mission_directory or (lambda: None)

    # ------------------------------------------------------------------#
    # Public API
    # ------------------------------------------------------------------#
    def handle_new_marker(self, marker_type: str, lat: float, lon: float, easting: float, northing: float):
        """Show dialog and create marker."""
        dialog = MarkerDialog(lat, lon, easting, northing, self.iface.mainWindow())
        self._preselect_type(dialog, marker_type)

        if dialog_exec(dialog) != DialogAccepted:
            return

        marker_data = dialog.get_marker_data()
        marker_data['attachment_path'] = self._ingest_attachment(marker_data.get('attachment_path'))

        try:
            marker_id, marker_label = self._create_marker(marker_data)
            success(
                self.iface.messageBar(),
                "SAR Tracker",
                f"{marker_label} '{marker_data['name']}' added successfully",
                duration=3
            )
            self._refresh_log()
            return marker_id
        except LayerTransactionError as exc:
            error(self.iface.messageBar(), exc.title, exc.message, duration=6)
        except Exception as exc:
            error(self.iface.messageBar(), "Error Adding Marker", str(exc), duration=6)

    def handle_edit(self, marker_type: str, marker_id: str):
        """Edit marker by type/id."""
        try:
            feature = self.layers_controller.get_marker_feature(marker_type, marker_id)
            if not feature:
                warning(self.iface.messageBar(), "Markers", "Selected marker no longer exists.", duration=4)
                return

            lat, lon, easting, northing = self._extract_marker_coordinates(feature)
            existing_data = self._build_marker_dialog_payload(feature, marker_type)
            dialog = MarkerDialog(lat, lon, easting, northing, self.iface.mainWindow(), existing_data=existing_data)

            if dialog_exec(dialog) != DialogAccepted:
                return

            marker_data = dialog.get_marker_data()
            marker_data['attachment_path'] = self._ingest_attachment(marker_data.get('attachment_path'))
            updates = self._build_marker_update_payload(marker_type, marker_data)
            self.layers_controller.update_marker(
                marker_type,
                marker_id,
                updates,
                updated_by=marker_data.get('updated_by')
            )
            success(self.iface.messageBar(), "Markers", f"{marker_data['name']} updated successfully", duration=3)
            self._refresh_log()
        except LayerTransactionError as exc:
            error(self.iface.messageBar(), exc.title, exc.message, duration=6)
        except Exception as exc:
            error(self.iface.messageBar(), "Markers", f"Failed to update marker: {exc}", duration=5)

    def handle_delete(self, marker_type: str, marker_id: str):
        """Delete marker with confirmation."""
        confirm = QMessageBox.question(
            self.iface.mainWindow(),
            "Delete Marker",
            "Are you sure you want to delete this marker?\nThis action cannot be undone.",
            MessageBoxYes | MessageBoxNo,
            MessageBoxNo
        )
        if confirm != MessageBoxYes:
            return

        try:
            self.layers_controller.delete_marker(marker_type, marker_id)
            success(self.iface.messageBar(), "Markers", "Marker deleted.", duration=2)
            self._refresh_log()
        except LayerTransactionError as exc:
            error(self.iface.messageBar(), exc.title, exc.message, duration=6)
        except Exception as exc:
            error(self.iface.messageBar(), "Markers", f"Failed to delete marker: {exc}", duration=5)

    def zoom_to_marker(self, lat: float, lon: float):
        """Zoom to marker location."""
        try:
            from qgis.core import QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsPointXY, QgsProject
            dest_crs = self.iface.mapCanvas().mapSettings().destinationCrs()
            source_crs = QgsCoordinateReferenceSystem(4326)
            transform = QgsCoordinateTransform(source_crs, dest_crs, QgsProject.instance())
            point = transform.transform(QgsPointXY(lon, lat))
            canvas = self.iface.mapCanvas()
            canvas.setCenter(point)
            canvas.zoomScale(2500)
            canvas.refresh()
        except Exception as exc:
            warning(self.iface.messageBar(), "Markers", f"Could not zoom to marker: {exc}", duration=4)

    def open_attachment(self, attachment_path: str):
        """
        Open attachment relative to mission directory if needed.

        BUG-074 FIX: Enhanced path validation to prevent path traversal attacks.
        LIFE-SAFETY CRITICAL: Malicious attachments could compromise system security.
        """
        import logging
        logger = logging.getLogger(__name__)

        if not attachment_path:
            warning(self.iface.messageBar(), "Attachments", "No attachment on this record.", duration=3)
            return

        # BUG-074 FIX: Validate attachment path for security
        # Strip dangerous characters and sequences
        attachment_path = attachment_path.strip()

        # BUG-074 FIX: Reject paths with path traversal attempts
        dangerous_patterns = ['..', '~/', '~\\']
        for pattern in dangerous_patterns:
            if pattern in attachment_path:
                logger.error(
                    "BUG-074: Rejected attachment path with dangerous pattern '%s': %s",
                    pattern, attachment_path
                )
                error(
                    self.iface.messageBar(),
                    "Security Error",
                    f"Invalid attachment path: path traversal not allowed",
                    duration=5
                )
                return

        # BUG-074 FIX: Do NOT use expanduser() - it could access user home directory
        # Only use Path() for basic parsing
        candidate = Path(attachment_path)

        mission_dir = self._get_mission_directory()

        # BUG-074 FIX: If path is not absolute, it must be relative to mission directory
        if not candidate.is_absolute():
            if not mission_dir:
                logger.error(
                    "BUG-074: Cannot resolve relative attachment path without mission directory: %s",
                    attachment_path
                )
                warning(
                    self.iface.messageBar(),
                    "Attachments",
                    "Cannot open relative attachment: no active mission directory",
                    duration=4
                )
                return

            candidate = mission_dir / candidate

        # BUG-074 FIX: Resolve path and verify it's within mission directory (if set)
        try:
            candidate = candidate.resolve(strict=False)
        except (ValueError, RuntimeError) as e:
            logger.error("BUG-074: Failed to resolve attachment path %s: %s", attachment_path, str(e))
            error(
                self.iface.messageBar(),
                "Path Error",
                f"Invalid attachment path: {str(e)}",
                duration=5
            )
            return

        # BUG-074 FIX: If mission directory is set, verify candidate is within it
        if mission_dir:
            try:
                mission_dir_resolved = mission_dir.resolve(strict=True)
                # Check if candidate is within mission directory tree
                try:
                    candidate.relative_to(mission_dir_resolved)
                except ValueError:
                    # candidate is outside mission directory - reject
                    logger.error(
                        "BUG-074: Attachment path outside mission directory: %s (mission: %s)",
                        candidate, mission_dir_resolved
                    )
                    error(
                        self.iface.messageBar(),
                        "Security Error",
                        "Attachment path must be within mission directory",
                        duration=5
                    )
                    return
            except Exception as e:
                logger.error("BUG-074: Failed to validate mission directory: %s", str(e))

        # Check file exists
        if not candidate.exists():
            logger.warning("BUG-074: Attachment file not found: %s", candidate)
            warning(
                self.iface.messageBar(),
                "Attachments",
                f"Attachment not found: {candidate.name}",
                duration=4
            )
            return

        # BUG-074 FIX: Verify it's a regular file, not a directory or special file
        if not candidate.is_file():
            logger.error("BUG-074: Attachment path is not a regular file: %s", candidate)
            error(
                self.iface.messageBar(),
                "Security Error",
                "Attachment must be a regular file",
                duration=5
            )
            return

        # Safe to open
        logger.info("BUG-074: Opening validated attachment: %s", candidate)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(candidate)))

    # ------------------------------------------------------------------#
    # Internal helpers
    # ------------------------------------------------------------------#
    def _preselect_type(self, dialog: MarkerDialog, marker_type: str):
        if marker_type == 'clue':
            dialog.clue_radio.setChecked(True)
        elif marker_type == 'hazard':
            dialog.hazard_radio.setChecked(True)
        elif marker_type == 'casualty':
            dialog.casualty_radio.setChecked(True)
        else:
            dialog.ipp_lkp_radio.setChecked(True)

    def _create_marker(self, marker_data: Dict[str, object]):
        """
        Create marker of specified type.

        BUG-076 FIX: Explicit marker type validation instead of implicit fallback.
        LIFE-SAFETY CRITICAL: Wrong marker type could cause operational confusion.

        Raises:
            ValueError: If marker type is invalid
        """
        import logging
        logger = logging.getLogger(__name__)

        marker_type = marker_data.get('type')

        # BUG-076 FIX: Validate marker type explicitly
        VALID_MARKER_TYPES = {'ipp_lkp', 'clue', 'hazard', 'casualty'}
        if marker_type not in VALID_MARKER_TYPES:
            logger.error(
                "BUG-076: Invalid marker type '%s', expected one of: %s",
                marker_type, VALID_MARKER_TYPES
            )
            raise ValueError(
                f"Invalid marker type: '{marker_type}'. "
                f"Must be one of: {', '.join(sorted(VALID_MARKER_TYPES))}"
            )

        if marker_type == 'ipp_lkp':
            marker_id = self.layers_controller.add_ipp_lkp(
                name=marker_data['name'],
                lat=marker_data['lat'],
                lon=marker_data['lon'],
                subject_category=marker_data.get('subject_category', ''),
                description=marker_data['description'],
                irish_grid_e=marker_data['easting'],
                irish_grid_n=marker_data['northing'],
                coordinator_ids=marker_data.get('coordinator_ids'),
                updated_by=marker_data.get('updated_by'),
                attachment_path=marker_data.get('attachment_path')
            )
            return marker_id, "IPP/LKP"
        elif marker_type == 'clue':
            marker_id = self.layers_controller.add_clue(
                name=marker_data['name'],
                lat=marker_data['lat'],
                lon=marker_data['lon'],
                clue_type=marker_data.get('clue_type', ''),
                confidence=marker_data.get('confidence', 'Possible'),
                description=marker_data['description'],
                irish_grid_e=marker_data['easting'],
                irish_grid_n=marker_data['northing'],
                coordinator_ids=marker_data.get('coordinator_ids'),
                updated_by=marker_data.get('updated_by'),
                attachment_path=marker_data.get('attachment_path')
            )
            return marker_id, "Clue"
        elif marker_type == 'casualty':
            marker_id = self.layers_controller.add_casualty(
                name=marker_data['name'],
                lat=marker_data['lat'],
                lon=marker_data['lon'],
                condition=marker_data.get('condition', ''),
                treatment=marker_data.get('treatment', ''),
                evacuation_priority=marker_data.get('evacuation_priority', ''),
                description=marker_data['description'],
                found_by=marker_data.get('found_by', ''),
                irish_grid_e=marker_data['easting'],
                irish_grid_n=marker_data['northing'],
                coordinator_ids=marker_data.get('coordinator_ids'),
                updated_by=marker_data.get('updated_by'),
                attachment_path=marker_data.get('attachment_path')
            )
            return marker_id, "Casualty"
        elif marker_type == 'hazard':
            # BUG-076 FIX: Explicit hazard case instead of implicit fallback
            marker_id = self.layers_controller.add_hazard(
                name=marker_data['name'],
                lat=marker_data['lat'],
                lon=marker_data['lon'],
                hazard_type=marker_data.get('hazard_type', ''),
                severity=marker_data.get('severity', 'Medium'),
                description=marker_data['description'],
                irish_grid_e=marker_data['easting'],
                irish_grid_n=marker_data['northing'],
                coordinator_ids=marker_data.get('coordinator_ids'),
                updated_by=marker_data.get('updated_by'),
                attachment_path=marker_data.get('attachment_path')
            )
            return marker_id, "Hazard"
        else:
            # BUG-076 FIX: This should never be reached due to validation above,
            # but included for defensive programming
            raise ValueError(f"Unhandled marker type: {marker_type}")

    def _extract_marker_coordinates(self, feature) -> tuple:
        """
        Return (lat, lon, easting, northing) with safe fallbacks.

        BUG-073 & BUG-077 FIX: Enhanced coordinate extraction with proper validation
        and logging. LIFE-SAFETY CRITICAL: Never silently return zero coordinates.

        Returns:
            tuple: (lat, lon, easting, northing) - raises ValueError if invalid

        Raises:
            ValueError: If coordinates cannot be extracted or are invalid
        """
        import logging
        logger = logging.getLogger(__name__)

        lat = feature["lat"]
        lon = feature["lon"]
        easting = feature["irish_grid_e"]
        northing = feature["irish_grid_n"]

        # BUG-073 FIX: Try to extract from geometry if lat/lon not in attributes
        if (lat is None or lon is None) and feature.geometry() and not feature.geometry().isEmpty():
            try:
                point = feature.geometry().asPoint()
                if point:
                    # BUG-077 FIX: Validate extracted coordinates before using
                    extracted_lon = point.x()
                    extracted_lat = point.y()

                    # Validate reasonable coordinate ranges (WGS84)
                    if -180 <= extracted_lon <= 180 and -90 <= extracted_lat <= 90:
                        lat = lat if lat is not None else extracted_lat
                        lon = lon if lon is not None else extracted_lon
                        logger.info(
                            "BUG-073: Extracted coordinates from geometry: lat=%.6f, lon=%.6f",
                            lat, lon
                        )
                    else:
                        logger.error(
                            "BUG-073: Geometry has out-of-range coordinates: lat=%.6f, lon=%.6f",
                            extracted_lat, extracted_lon
                        )
            except Exception as e:
                # BUG-073 FIX: Log extraction failures instead of silent pass
                logger.error(
                    "BUG-073: Failed to extract coordinates from geometry: %s", str(e)
                )

        # BUG-073 & BUG-077 FIX: NEVER return zero coordinates silently
        # This is LIFE-SAFETY CRITICAL - zero coordinates could send rescuers to wrong location
        if lat is None or lon is None or lat == 0.0 or lon == 0.0:
            # Only allow (0, 0) if it's an explicit value in both fields
            if not (lat == 0.0 and lon == 0.0 and
                    feature["lat"] is not None and feature["lon"] is not None):
                raise ValueError(
                    f"Invalid or missing coordinates: lat={lat}, lon={lon}. "
                    f"Cannot load marker with invalid location data."
                )

        # Validate coordinate ranges
        if not (-90 <= lat <= 90):
            raise ValueError(f"Latitude {lat} out of valid range [-90, 90]")
        if not (-180 <= lon <= 180):
            raise ValueError(f"Longitude {lon} out of valid range [-180, 180]")

        # Irish Grid coordinates can be None (optional), but not zero unless explicitly set
        # Return None instead of 0.0 for unset Irish Grid values
        easting = easting if easting is not None and easting != 0.0 else None
        northing = northing if northing is not None and northing != 0.0 else None

        return lat, lon, easting, northing

    def _build_marker_dialog_payload(self, feature, marker_type: str) -> Dict[str, object]:
        payload: Dict[str, object] = {}
        for field in feature.fields():
            payload[field.name()] = feature[field.name()]
        payload["type"] = marker_type
        return payload

    def _build_marker_update_payload(self, marker_type: str, marker_data: Dict[str, object]) -> Dict[str, object]:
        updates: Dict[str, object] = {
            "name": marker_data.get("name", ""),
            "description": marker_data.get("description", ""),
            "updated_by": marker_data.get("updated_by", ""),
            "coordinator_ids": marker_data.get("coordinator_ids", ""),
            "attachment_path": marker_data.get("attachment_path", "")
        }

        if marker_type == "ipp_lkp":
            updates["subject_category"] = marker_data.get("subject_category", "")
        elif marker_type == "clue":
            updates["clue_type"] = marker_data.get("clue_type", "")
            updates["confidence"] = marker_data.get("confidence", "")
        elif marker_type == "hazard":
            updates["hazard_type"] = marker_data.get("hazard_type", "")
            updates["severity"] = marker_data.get("severity", "")
        elif marker_type == "casualty":
            updates["condition"] = marker_data.get("condition", "")
            updates["treatment"] = marker_data.get("treatment", "")
            updates["evacuation_priority"] = marker_data.get("evacuation_priority", "")
            updates["found_by"] = marker_data.get("found_by", "")

        return updates
