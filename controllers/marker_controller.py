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
from ..utils.qt_compat import dialog_exec, DialogAccepted
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
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if confirm != QMessageBox.Yes:
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
        """Open attachment relative to mission directory if needed."""
        if not attachment_path:
            warning(self.iface.messageBar(), "Attachments", "No attachment on this record.", duration=3)
            return

        mission_dir = self._get_mission_directory()
        candidate = Path(attachment_path).expanduser()
        if mission_dir and not candidate.is_absolute():
            candidate = mission_dir / candidate

        if not candidate.exists():
            warning(self.iface.messageBar(), "Attachments", f"Attachment not found: {candidate}", duration=4)
            return

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
        marker_type = marker_data['type']
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
        if marker_type == 'clue':
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
        if marker_type == 'casualty':
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

    def _extract_marker_coordinates(self, feature) -> tuple:
        """Return (lat, lon, easting, northing) with fallbacks."""
        lat = feature["lat"]
        lon = feature["lon"]
        easting = feature["irish_grid_e"]
        northing = feature["irish_grid_n"]

        if (lat is None or lon is None) and feature.geometry() and not feature.geometry().isEmpty():
            try:
                point = feature.geometry().asPoint()
                if point:
                    lat = lat or point.y()
                    lon = lon or point.x()
            except Exception:
                pass

        return lat or 0.0, lon or 0.0, easting or 0.0, northing or 0.0

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
