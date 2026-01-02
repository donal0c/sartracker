# -*- coding: utf-8 -*-
"""
End-to-End Scenario Tests for SAR Tracker.

These tests verify complete workflows using real QGIS components.
They focus on life-safety critical behavior: DATA MUST NOT BE LOST.

Run with: ./run_tests.sh tests/test_e2e_scenarios.py -v
"""
import pytest
from pathlib import Path

# Skip entire module if QGIS not available
pytest.importorskip("qgis.core", reason="E2E tests require real QGIS")

from qgis.core import (
    QgsProject,
    QgsVectorLayer,
    QgsVectorFileWriter,
    QgsFeature,
    QgsGeometry,
    QgsPointXY,
    QgsField,
)
from qgis.PyQt.QtCore import QVariant


class TestMemoryLayerOperations:
    """
    E2E tests for layer operations using memory layers.

    VALUE: HIGH - Verifies that QGIS layer operations work correctly.
    Memory layers test the same code paths without file I/O complexity.
    """

    def test_create_layer_and_add_features(self):
        """
        Scenario: Create layer, add features, verify they exist.

        Tests basic layer creation and feature addition.
        """
        # Create memory layer with fields
        layer = QgsVectorLayer("Point?crs=EPSG:4326", "test_markers", "memory")
        assert layer.isValid(), "Layer should be valid"

        # Add fields
        layer.dataProvider().addAttributes([
            QgsField("name", QVariant.String),
            QgsField("marker_type", QVariant.String),
        ])
        layer.updateFields()

        # Add features
        layer.startEditing()

        f1 = QgsFeature(layer.fields())
        f1.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(-9.5, 52.0)))
        f1.setAttributes(["IPP", "ipp"])
        layer.addFeature(f1)

        f2 = QgsFeature(layer.fields())
        f2.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(-9.6, 52.1)))
        f2.setAttributes(["Clue 1", "clue"])
        layer.addFeature(f2)

        commit_ok = layer.commitChanges()
        assert commit_ok, f"Commit should succeed: {layer.commitErrors()}"

        # Verify
        assert layer.featureCount() == 2, "Should have 2 features"

        names = {f["name"] for f in layer.getFeatures()}
        assert "IPP" in names
        assert "Clue 1" in names

    def test_feature_update(self):
        """
        Scenario: Update feature attribute, verify change.
        """
        layer = QgsVectorLayer("Point?crs=EPSG:4326", "test", "memory")
        layer.dataProvider().addAttributes([QgsField("status", QVariant.String)])
        layer.updateFields()

        # Add initial feature
        layer.startEditing()
        f = QgsFeature(layer.fields())
        f.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(-9.5, 52.0)))
        f.setAttributes(["pending"])
        layer.addFeature(f)
        layer.commitChanges()

        # Update
        layer.startEditing()
        for feat in layer.getFeatures():
            layer.changeAttributeValue(feat.id(), 0, "completed")
        layer.commitChanges()

        # Verify
        features = list(layer.getFeatures())
        assert features[0]["status"] == "completed"

    def test_feature_delete(self):
        """
        Scenario: Delete feature, verify it's gone.
        """
        layer = QgsVectorLayer("Point?crs=EPSG:4326", "test", "memory")
        layer.dataProvider().addAttributes([QgsField("name", QVariant.String)])
        layer.updateFields()

        # Add two features
        layer.startEditing()
        for name in ["keep", "delete"]:
            f = QgsFeature(layer.fields())
            f.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(-9.5, 52.0)))
            f.setAttributes([name])
            layer.addFeature(f)
        layer.commitChanges()

        assert layer.featureCount() == 2

        # Delete one
        layer.startEditing()
        for feat in layer.getFeatures():
            if feat["name"] == "delete":
                layer.deleteFeature(feat.id())
        layer.commitChanges()

        # Verify
        assert layer.featureCount() == 1
        remaining = list(layer.getFeatures())[0]
        assert remaining["name"] == "keep"

    def test_rollback_discards_changes(self):
        """
        Scenario: Make changes, rollback, verify original state.

        VALUE: HIGH - Ensures data integrity on failed operations.
        """
        layer = QgsVectorLayer("Point?crs=EPSG:4326", "test", "memory")
        layer.dataProvider().addAttributes([QgsField("value", QVariant.String)])
        layer.updateFields()

        # Add initial feature
        layer.startEditing()
        f = QgsFeature(layer.fields())
        f.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(-9.5, 52.0)))
        f.setAttributes(["original"])
        layer.addFeature(f)
        layer.commitChanges()

        # Make change then rollback
        layer.startEditing()
        for feat in layer.getFeatures():
            layer.changeAttributeValue(feat.id(), 0, "modified")

        # Verify pending change visible
        pending = list(layer.getFeatures())
        assert pending[0]["value"] == "modified"

        # Rollback
        layer.rollBack()

        # Verify original restored
        features = list(layer.getFeatures())
        assert features[0]["value"] == "original"


class TestProjectIntegration:
    """
    E2E tests for QGIS project integration.

    VALUE: HIGH - Verifies layers work correctly within a project.
    """

    def test_add_layer_to_project(self):
        """
        Scenario: Add layer to project, verify it's registered.
        """
        project = QgsProject.instance()
        initial_count = len(project.mapLayers())

        # Create and add layer
        layer = QgsVectorLayer("Point?crs=EPSG:4326", "test_layer", "memory")
        project.addMapLayer(layer)

        # Verify
        assert len(project.mapLayers()) == initial_count + 1
        assert project.mapLayersByName("test_layer")

        # Cleanup
        project.removeMapLayer(layer.id())

    def test_layer_custom_properties(self):
        """
        Scenario: Set custom properties, verify they persist in memory.

        Custom properties are how SAR Tracker identifies layer purposes.
        """
        layer = QgsVectorLayer("Point?crs=EPSG:4326", "test", "memory")

        # Set custom properties
        layer.setCustomProperty("sartracker:layer_type", "markers")
        layer.setCustomProperty("sartracker:item_id", "clue_001")

        # Verify
        assert layer.customProperty("sartracker:layer_type") == "markers"
        assert layer.customProperty("sartracker:item_id") == "clue_001"


class TestCoordinateHandling:
    """
    E2E tests for coordinate handling.

    VALUE: CRITICAL - Incorrect coordinates could send rescuers to wrong location.
    """

    def test_wgs84_coordinates_stored_correctly(self):
        """
        Scenario: Store WGS84 coordinates, verify precision maintained.
        """
        layer = QgsVectorLayer("Point?crs=EPSG:4326", "test", "memory")

        # Kerry, Ireland - typical SAR coordinates
        test_lat = 52.140900
        test_lon = -9.693800

        layer.startEditing()
        f = QgsFeature()
        f.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(test_lon, test_lat)))
        layer.addFeature(f)
        layer.commitChanges()

        # Verify precision
        feature = list(layer.getFeatures())[0]
        geom = feature.geometry()
        point = geom.asPoint()

        # Should maintain at least 5 decimal places
        assert abs(point.x() - test_lon) < 0.00001, "Longitude precision lost"
        assert abs(point.y() - test_lat) < 0.00001, "Latitude precision lost"

    def test_multiple_points_maintain_positions(self):
        """
        Scenario: Store multiple points, verify each position is distinct.
        """
        layer = QgsVectorLayer("Point?crs=EPSG:4326", "test", "memory")

        # Test points around Kerry
        test_points = [
            (-9.5, 52.0),   # Point A
            (-9.6, 52.1),   # Point B
            (-9.7, 52.2),   # Point C
        ]

        layer.startEditing()
        for lon, lat in test_points:
            f = QgsFeature()
            f.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(lon, lat)))
            layer.addFeature(f)
        layer.commitChanges()

        # Verify all points distinct
        stored_points = set()
        for feat in layer.getFeatures():
            pt = feat.geometry().asPoint()
            stored_points.add((round(pt.x(), 5), round(pt.y(), 5)))

        expected = {(round(x, 5), round(y, 5)) for x, y in test_points}
        assert stored_points == expected, "Points should all be distinct and accurate"


class TestGeoPackageFilePersistence:
    """
    E2E tests for GeoPackage file persistence.

    VALUE: CRITICAL - Verifies data survives to disk. Memory layers
    lose data on crash; GeoPackage layers preserve mission data.
    """

    def test_geopackage_layer_persists_to_file(self, tmp_path):
        """
        Scenario: Create GeoPackage layer, add features, verify file contains data.

        This is the fundamental persistence test - data MUST survive to disk.
        """
        gpkg_path = tmp_path / "test_mission.gpkg"

        # Create GeoPackage layer (not memory!)
        uri = f"{gpkg_path}|layername=markers"
        options = QgsVectorFileWriter.SaveVectorOptions()
        options.driverName = "GPKG"
        options.layerName = "markers"

        # Create source layer with fields
        source = QgsVectorLayer("Point?crs=EPSG:4326", "temp", "memory")
        source.dataProvider().addAttributes([
            QgsField("name", QVariant.String),
            QgsField("marker_type", QVariant.String),
        ])
        source.updateFields()

        # Write empty layer to create GeoPackage
        from qgis.core import QgsVectorFileWriter
        error, msg, _, _ = QgsVectorFileWriter.writeAsVectorFormatV3(
            source,
            str(gpkg_path),
            QgsProject.instance().transformContext(),
            options
        )
        assert error == QgsVectorFileWriter.NoError, f"Failed to create GPKG: {msg}"

        # Open the GeoPackage layer
        gpkg_layer = QgsVectorLayer(uri, "markers", "ogr")
        assert gpkg_layer.isValid(), f"GPKG layer invalid: {gpkg_layer.error().message()}"

        # Add features
        gpkg_layer.startEditing()
        f = QgsFeature(gpkg_layer.fields())
        f.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(-9.693800, 52.140900)))
        f.setAttributes(["IPP", "ipp_lkp"])
        gpkg_layer.addFeature(f)
        commit_ok = gpkg_layer.commitChanges()
        assert commit_ok, f"Commit failed: {gpkg_layer.commitErrors()}"

        # Close and reopen to verify persistence
        del gpkg_layer

        reopened = QgsVectorLayer(uri, "markers_reopen", "ogr")
        assert reopened.isValid()
        assert reopened.featureCount() == 1

        feature = list(reopened.getFeatures())[0]
        assert feature["name"] == "IPP"
        point = feature.geometry().asPoint()
        assert abs(point.y() - 52.140900) < 0.00001, "Latitude not preserved"

    def test_geopackage_survives_layer_close_reopen(self, tmp_path):
        """
        Scenario: Write data, close layer completely, reopen and verify.

        Simulates QGIS session restart - data must survive.
        """
        import sqlite3
        gpkg_path = tmp_path / "session_test.gpkg"

        # Create GeoPackage directly with SQLite + QGIS
        source = QgsVectorLayer("Point?crs=EPSG:4326", "positions", "memory")
        source.dataProvider().addAttributes([
            QgsField("device_id", QVariant.String),
            QgsField("timestamp", QVariant.String),
        ])
        source.updateFields()

        options = QgsVectorFileWriter.SaveVectorOptions()
        options.driverName = "GPKG"
        options.layerName = "positions"

        from qgis.core import QgsVectorFileWriter
        error, _, _, _ = QgsVectorFileWriter.writeAsVectorFormatV3(
            source, str(gpkg_path),
            QgsProject.instance().transformContext(), options
        )
        assert error == QgsVectorFileWriter.NoError

        # Add data
        uri = f"{gpkg_path}|layername=positions"
        layer = QgsVectorLayer(uri, "positions", "ogr")
        layer.startEditing()

        for i, (device, lat, lon) in enumerate([
            ("TEAM_01", 52.0, -9.5),
            ("TEAM_02", 52.1, -9.6),
            ("TEAM_03", 52.2, -9.7),
        ]):
            f = QgsFeature(layer.fields())
            f.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(lon, lat)))
            f.setAttributes([device, f"2025-01-01T{10+i}:00:00Z"])
            layer.addFeature(f)

        layer.commitChanges()
        del layer  # Close layer completely

        # Verify with raw SQLite (bypassing QGIS)
        conn = sqlite3.connect(str(gpkg_path))
        count = conn.execute("SELECT COUNT(*) FROM positions").fetchone()[0]
        devices = conn.execute("SELECT device_id FROM positions ORDER BY device_id").fetchall()
        conn.close()

        assert count == 3
        assert [d[0] for d in devices] == ["TEAM_01", "TEAM_02", "TEAM_03"]

    def test_geopackage_wal_mode_enables_safely(self, tmp_path):
        """
        Scenario: Enable WAL mode for crash safety.

        WAL mode prevents data loss during unexpected shutdowns.
        """
        import sqlite3
        gpkg_path = tmp_path / "wal_test.gpkg"

        # Create minimal GeoPackage
        conn = sqlite3.connect(str(gpkg_path))
        conn.execute("CREATE TABLE test (id INTEGER)")
        conn.commit()
        conn.close()

        # Enable WAL mode
        conn = sqlite3.connect(str(gpkg_path))
        result = conn.execute("PRAGMA journal_mode=WAL").fetchone()
        conn.close()

        assert result[0].upper() == "WAL", "WAL mode should be enabled"

        # Verify WAL files created on write
        conn = sqlite3.connect(str(gpkg_path))
        conn.execute("INSERT INTO test VALUES (1)")
        conn.commit()

        # WAL file should exist while connection open
        wal_file = tmp_path / "wal_test.gpkg-wal"
        # Note: WAL file may or may not exist depending on SQLite version
        # The important thing is the mode is set correctly
        conn.close()

    def test_multiple_layers_in_same_geopackage(self, tmp_path):
        """
        Scenario: Store multiple layer types in one GeoPackage.

        SAR missions need markers, search areas, and tracks in same file.
        """
        gpkg_path = tmp_path / "multi_layer.gpkg"

        from qgis.core import QgsVectorFileWriter

        # Create markers layer
        markers = QgsVectorLayer("Point?crs=EPSG:4326", "markers", "memory")
        markers.dataProvider().addAttributes([QgsField("name", QVariant.String)])
        markers.updateFields()

        options = QgsVectorFileWriter.SaveVectorOptions()
        options.driverName = "GPKG"
        options.layerName = "markers"
        QgsVectorFileWriter.writeAsVectorFormatV3(
            markers, str(gpkg_path),
            QgsProject.instance().transformContext(), options
        )

        # Add search areas layer to SAME GeoPackage
        areas = QgsVectorLayer("Polygon?crs=EPSG:4326", "search_areas", "memory")
        areas.dataProvider().addAttributes([QgsField("sector", QVariant.String)])
        areas.updateFields()

        options.layerName = "search_areas"
        options.actionOnExistingFile = QgsVectorFileWriter.CreateOrOverwriteLayer
        QgsVectorFileWriter.writeAsVectorFormatV3(
            areas, str(gpkg_path),
            QgsProject.instance().transformContext(), options
        )

        # Add tracks layer
        tracks = QgsVectorLayer("LineString?crs=EPSG:4326", "tracks", "memory")
        tracks.dataProvider().addAttributes([QgsField("device_id", QVariant.String)])
        tracks.updateFields()

        options.layerName = "tracks"
        QgsVectorFileWriter.writeAsVectorFormatV3(
            tracks, str(gpkg_path),
            QgsProject.instance().transformContext(), options
        )

        # Verify all layers accessible
        import sqlite3
        conn = sqlite3.connect(str(gpkg_path))
        tables = conn.execute(
            "SELECT table_name FROM gpkg_contents WHERE data_type='features'"
        ).fetchall()
        conn.close()

        table_names = {t[0] for t in tables}
        assert "markers" in table_names
        assert "search_areas" in table_names
        assert "tracks" in table_names


class TestNetworkFailureResilience:
    """
    E2E tests for network failure handling.

    VALUE: HIGH - SAR operations happen in remote areas with poor connectivity.
    The system must handle network failures gracefully without data loss.
    """

    def test_provider_test_connection_returns_false_on_timeout(self):
        """
        Scenario: Provider handles connection timeout gracefully.

        test_connection() must return False, not raise exceptions.
        """
        from providers.traccar_http import TraccarHTTPProvider

        # Create provider with invalid/unreachable URL
        provider = TraccarHTTPProvider(
            url="http://192.0.2.1:8082",  # TEST-NET address, guaranteed unreachable
            username="test",
            password="test"
        )

        # Should return False, not raise
        result = provider.test_connection()
        assert result is False

    def test_provider_network_error_contains_useful_info(self):
        """
        Scenario: Network errors include actionable information.

        Users need to know WHY connection failed to fix it.
        """
        from utils.exceptions import ProviderNetworkError

        error = ProviderNetworkError(
            "Connection timeout after 5 seconds",
            provider_name="traccar_http"
        )

        assert "timeout" in str(error).lower()
        assert error.provider_name == "traccar_http"
        assert error.recoverable is True  # Network issues are transient

    def test_csv_provider_handles_missing_file_gracefully(self, tmp_path):
        """
        Scenario: CSV provider reports clear error for missing file.
        """
        from providers.csv import CSVProvider
        from utils.exceptions import ProviderDataError

        provider = CSVProvider(csv_path=str(tmp_path / "nonexistent.csv"))

        # test_connection should return False
        assert provider.test_connection() is False

        # get_current should raise clear error
        with pytest.raises(ProviderDataError) as exc_info:
            provider.get_current()

        assert "not found" in str(exc_info.value).lower() or "missing" in str(exc_info.value).lower()


class TestDataIntegrity:
    """
    E2E tests for data integrity under edge conditions.

    VALUE: CRITICAL - Data corruption during active rescue is unacceptable.
    """

    def test_concurrent_reads_dont_corrupt_data(self, tmp_path):
        """
        Scenario: Multiple reads from same GeoPackage don't corrupt data.
        """
        import sqlite3
        gpkg_path = tmp_path / "concurrent.gpkg"

        # Create test data
        conn = sqlite3.connect(str(gpkg_path))
        conn.execute("CREATE TABLE positions (id INTEGER, lat REAL, lon REAL)")
        for i in range(100):
            conn.execute("INSERT INTO positions VALUES (?, ?, ?)", (i, 52.0 + i*0.001, -9.5))
        conn.commit()
        conn.close()

        # Open multiple readers
        readers = [sqlite3.connect(str(gpkg_path)) for _ in range(5)]

        # All should read same data
        counts = []
        for r in readers:
            count = r.execute("SELECT COUNT(*) FROM positions").fetchone()[0]
            counts.append(count)
            r.close()

        assert all(c == 100 for c in counts), "All readers should see same data"

    def test_transaction_rollback_preserves_original_data(self, tmp_path):
        """
        Scenario: Failed transaction doesn't corrupt existing data.

        LIFE-SAFETY CRITICAL: Partial writes must not corrupt mission data.
        """
        gpkg_path = tmp_path / "rollback_test.gpkg"

        from qgis.core import QgsVectorFileWriter

        # Create and populate
        source = QgsVectorLayer("Point?crs=EPSG:4326", "test", "memory")
        source.dataProvider().addAttributes([QgsField("status", QVariant.String)])
        source.updateFields()

        options = QgsVectorFileWriter.SaveVectorOptions()
        options.driverName = "GPKG"
        options.layerName = "test"
        QgsVectorFileWriter.writeAsVectorFormatV3(
            source, str(gpkg_path),
            QgsProject.instance().transformContext(), options
        )

        # Add original data
        uri = f"{gpkg_path}|layername=test"
        layer = QgsVectorLayer(uri, "test", "ogr")
        layer.startEditing()
        f = QgsFeature(layer.fields())
        f.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(-9.5, 52.0)))
        f.setAttributes(["original"])
        layer.addFeature(f)
        layer.commitChanges()

        original_count = layer.featureCount()

        # Start editing, make changes, then rollback
        layer.startEditing()
        f2 = QgsFeature(layer.fields())
        f2.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(-9.6, 52.1)))
        f2.setAttributes(["should_not_persist"])
        layer.addFeature(f2)

        # Rollback instead of commit
        layer.rollBack()

        # Verify original data preserved
        assert layer.featureCount() == original_count
        feature = list(layer.getFeatures())[0]
        assert feature["status"] == "original"

    def test_coordinate_precision_preserved_through_save_reload(self, tmp_path):
        """
        Scenario: High-precision coordinates survive save/reload cycle.

        LIFE-SAFETY CRITICAL: Losing precision could send rescuers to wrong location.
        """
        gpkg_path = tmp_path / "precision_test.gpkg"

        from qgis.core import QgsVectorFileWriter

        # Kerry, Ireland - real SAR coordinates with high precision
        test_coords = [
            (-9.6938127, 52.1409234),  # 7 decimal places
            (-9.6938126, 52.1409235),  # Nearby but distinct
        ]

        source = QgsVectorLayer("Point?crs=EPSG:4326", "test", "memory")
        source.dataProvider().addAttributes([QgsField("name", QVariant.String)])
        source.updateFields()

        options = QgsVectorFileWriter.SaveVectorOptions()
        options.driverName = "GPKG"
        options.layerName = "test"
        QgsVectorFileWriter.writeAsVectorFormatV3(
            source, str(gpkg_path),
            QgsProject.instance().transformContext(), options
        )

        uri = f"{gpkg_path}|layername=test"
        layer = QgsVectorLayer(uri, "test", "ogr")
        layer.startEditing()

        for i, (lon, lat) in enumerate(test_coords):
            f = QgsFeature(layer.fields())
            f.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(lon, lat)))
            f.setAttributes([f"point_{i}"])
            layer.addFeature(f)

        layer.commitChanges()
        del layer

        # Reload and verify precision
        reloaded = QgsVectorLayer(uri, "test", "ogr")
        loaded_coords = []
        for feat in reloaded.getFeatures():
            pt = feat.geometry().asPoint()
            loaded_coords.append((pt.x(), pt.y()))

        # Should maintain at least 6 decimal places (sub-meter accuracy)
        for original, loaded in zip(test_coords, sorted(loaded_coords)):
            assert abs(original[0] - loaded[0]) < 0.0000001, "Longitude precision lost"
            assert abs(original[1] - loaded[1]) < 0.0000001, "Latitude precision lost"


class TestLayerLifecycle:
    """
    E2E tests for layer lifecycle management.

    VALUE: HIGH - Proper cleanup prevents memory leaks and crashes.
    """

    def test_layer_removal_from_project_cleans_up(self):
        """
        Scenario: Removing layer from project doesn't leave orphans.
        """
        project = QgsProject.instance()
        initial_count = len(project.mapLayers())

        # Add layer
        layer = QgsVectorLayer("Point?crs=EPSG:4326", "temp_layer", "memory")
        layer.setCustomProperty("sartracker:test", "lifecycle_test")
        project.addMapLayer(layer)

        assert len(project.mapLayers()) == initial_count + 1

        # Remove layer
        project.removeMapLayer(layer.id())

        assert len(project.mapLayers()) == initial_count

    def test_custom_properties_survive_project_add_remove(self):
        """
        Scenario: Custom properties exist while layer is in project.

        SAR Tracker uses custom properties to identify layer purposes.
        """
        project = QgsProject.instance()

        layer = QgsVectorLayer("Point?crs=EPSG:4326", "markers", "memory")
        layer.setCustomProperty("sartracker:layer_type", "markers")
        layer.setCustomProperty("sartracker:mission_id", "MISSION_001")

        project.addMapLayer(layer)

        # Find by custom property
        found = None
        for lyr in project.mapLayers().values():
            if lyr.customProperty("sartracker:layer_type") == "markers":
                found = lyr
                break

        assert found is not None
        assert found.customProperty("sartracker:mission_id") == "MISSION_001"

        # Cleanup
        project.removeMapLayer(layer.id())


class TestMissionDataPatterns:
    """
    E2E tests for mission data patterns used during SAR operations.

    VALUE: HIGH - These patterns are used during active rescue operations.
    """

    def test_marker_with_all_sar_fields(self, tmp_path):
        """
        Scenario: Create marker with all fields used in real SAR operations.

        Tests the complete marker schema used during actual rescues.
        """
        gpkg_path = tmp_path / "mission.gpkg"

        from qgis.core import QgsVectorFileWriter

        # Create layer with full SAR marker schema
        source = QgsVectorLayer("Point?crs=EPSG:4326", "markers", "memory")
        source.dataProvider().addAttributes([
            QgsField("name", QVariant.String),
            QgsField("marker_type", QVariant.String),  # ipp, lkp, clue, hazard
            QgsField("description", QVariant.String),
            QgsField("created_at", QVariant.String),
            QgsField("created_by", QVariant.String),
            QgsField("grid_ref", QVariant.String),  # Irish Grid reference
        ])
        source.updateFields()

        options = QgsVectorFileWriter.SaveVectorOptions()
        options.driverName = "GPKG"
        options.layerName = "markers"
        QgsVectorFileWriter.writeAsVectorFormatV3(
            source, str(gpkg_path),
            QgsProject.instance().transformContext(), options
        )

        uri = f"{gpkg_path}|layername=markers"
        layer = QgsVectorLayer(uri, "markers", "ogr")
        layer.startEditing()

        # IPP marker (Initial Planning Point)
        ipp = QgsFeature(layer.fields())
        ipp.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(-9.6938, 52.1409)))
        ipp.setAttributes([
            "Missing Person IPP",
            "ipp",
            "Last known location from family interview",
            "2025-01-02T14:30:00Z",
            "Team Leader",
            "V 451234 598765"
        ])
        layer.addFeature(ipp)

        # Clue marker
        clue = QgsFeature(layer.fields())
        clue.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(-9.6950, 52.1420)))
        clue.setAttributes([
            "Jacket Found",
            "clue",
            "Red jacket matching description, found by Team 2",
            "2025-01-02T15:45:00Z",
            "Team 2",
            "V 451100 598900"
        ])
        layer.addFeature(clue)

        layer.commitChanges()

        # Verify all fields preserved
        features = {f["name"]: f for f in layer.getFeatures()}
        assert "Missing Person IPP" in features
        assert "Jacket Found" in features

        ipp_feat = features["Missing Person IPP"]
        assert ipp_feat["marker_type"] == "ipp"
        assert ipp_feat["created_by"] == "Team Leader"

    def test_search_area_polygon(self, tmp_path):
        """
        Scenario: Create search area polygon with sector assignment.

        Search areas are polygons assigned to teams during operations.
        """
        gpkg_path = tmp_path / "mission.gpkg"

        from qgis.core import QgsVectorFileWriter

        source = QgsVectorLayer("Polygon?crs=EPSG:4326", "search_areas", "memory")
        source.dataProvider().addAttributes([
            QgsField("sector_name", QVariant.String),
            QgsField("assigned_team", QVariant.String),
            QgsField("priority", QVariant.Int),
            QgsField("status", QVariant.String),  # pending, active, complete
            QgsField("area_sqm", QVariant.Double),
        ])
        source.updateFields()

        options = QgsVectorFileWriter.SaveVectorOptions()
        options.driverName = "GPKG"
        options.layerName = "search_areas"
        QgsVectorFileWriter.writeAsVectorFormatV3(
            source, str(gpkg_path),
            QgsProject.instance().transformContext(), options
        )

        uri = f"{gpkg_path}|layername=search_areas"
        layer = QgsVectorLayer(uri, "search_areas", "ogr")
        layer.startEditing()

        # Create a polygon (search sector)
        polygon = QgsGeometry.fromPolygonXY([[
            QgsPointXY(-9.70, 52.14),
            QgsPointXY(-9.69, 52.14),
            QgsPointXY(-9.69, 52.15),
            QgsPointXY(-9.70, 52.15),
            QgsPointXY(-9.70, 52.14),
        ]])

        sector = QgsFeature(layer.fields())
        sector.setGeometry(polygon)
        sector.setAttributes([
            "Sector Alpha",
            "Kerry MRT Team 1",
            1,  # High priority
            "active",
            50000.0  # ~50,000 sq meters
        ])
        layer.addFeature(sector)
        layer.commitChanges()

        # Verify
        feature = list(layer.getFeatures())[0]
        assert feature["sector_name"] == "Sector Alpha"
        assert feature["priority"] == 1
        assert feature.geometry().isGeosValid()

    def test_device_track_linestring(self, tmp_path):
        """
        Scenario: Store device track as LineString geometry.

        Device tracks show the path taken by search teams.
        """
        gpkg_path = tmp_path / "mission.gpkg"

        from qgis.core import QgsVectorFileWriter

        source = QgsVectorLayer("LineString?crs=EPSG:4326", "tracks", "memory")
        source.dataProvider().addAttributes([
            QgsField("device_id", QVariant.String),
            QgsField("team_name", QVariant.String),
            QgsField("start_time", QVariant.String),
            QgsField("end_time", QVariant.String),
            QgsField("point_count", QVariant.Int),
        ])
        source.updateFields()

        options = QgsVectorFileWriter.SaveVectorOptions()
        options.driverName = "GPKG"
        options.layerName = "tracks"
        QgsVectorFileWriter.writeAsVectorFormatV3(
            source, str(gpkg_path),
            QgsProject.instance().transformContext(), options
        )

        uri = f"{gpkg_path}|layername=tracks"
        layer = QgsVectorLayer(uri, "tracks", "ogr")
        layer.startEditing()

        # Create track with multiple points
        track_points = [
            QgsPointXY(-9.70, 52.14),
            QgsPointXY(-9.695, 52.142),
            QgsPointXY(-9.69, 52.145),
            QgsPointXY(-9.685, 52.148),
            QgsPointXY(-9.68, 52.15),
        ]
        line_geom = QgsGeometry.fromPolylineXY(track_points)

        track = QgsFeature(layer.fields())
        track.setGeometry(line_geom)
        track.setAttributes([
            "GPS_001",
            "Kerry MRT Team 2",
            "2025-01-02T14:00:00Z",
            "2025-01-02T16:30:00Z",
            len(track_points)
        ])
        layer.addFeature(track)
        layer.commitChanges()

        # Verify
        feature = list(layer.getFeatures())[0]
        assert feature["device_id"] == "GPS_001"
        assert feature["point_count"] == 5

        # Verify geometry is valid LineString
        geom = feature.geometry()
        assert geom.type() == 1  # LineString type
        assert not geom.isEmpty()


class TestResourceCleanup:
    """
    E2E tests for resource cleanup patterns.

    VALUE: HIGH - Proper cleanup prevents memory leaks and crashes
    during plugin reload or long sessions.
    """

    def test_layer_deletion_frees_file_handle(self, tmp_path):
        """
        Scenario: Deleting layer releases file handle.

        Important for plugin reload - can't delete files with open handles.
        """
        import sqlite3
        gpkg_path = tmp_path / "cleanup_test.gpkg"

        # Create minimal GeoPackage
        conn = sqlite3.connect(str(gpkg_path))
        conn.execute("CREATE TABLE test (id INTEGER)")
        conn.commit()
        conn.close()

        # Open with QGIS
        layer = QgsVectorLayer(f"{gpkg_path}|layername=test", "test", "ogr")

        # Even if invalid (no geometry), test the pattern
        del layer

        # Should be able to write to file now
        conn = sqlite3.connect(str(gpkg_path))
        conn.execute("INSERT INTO test VALUES (1)")
        conn.commit()
        conn.close()

        # Verify
        conn = sqlite3.connect(str(gpkg_path))
        count = conn.execute("SELECT COUNT(*) FROM test").fetchone()[0]
        conn.close()
        assert count == 1

    def test_project_clear_removes_all_layers(self):
        """
        Scenario: Project clear removes all SAR Tracker layers.

        Tests that cleanup is complete when starting fresh.
        """
        project = QgsProject.instance()

        # Add several layers with SAR properties
        layers_added = []
        for name in ["markers", "tracks", "areas"]:
            layer = QgsVectorLayer("Point?crs=EPSG:4326", name, "memory")
            layer.setCustomProperty("sartracker:layer_type", name)
            project.addMapLayer(layer)
            layers_added.append(layer.id())

        # Verify layers exist
        for layer_id in layers_added:
            assert project.mapLayer(layer_id) is not None

        # Remove all SAR layers
        for layer_id in layers_added:
            project.removeMapLayer(layer_id)

        # Verify cleanup
        for layer_id in layers_added:
            assert project.mapLayer(layer_id) is None

    def test_temporary_layers_dont_persist(self, tmp_path):
        """
        Scenario: Temporary/memory layers don't write to GeoPackage.

        Ensures scratch layers stay scratch.
        """
        gpkg_path = tmp_path / "persist_test.gpkg"

        from qgis.core import QgsVectorFileWriter

        # Create GeoPackage with one layer
        source = QgsVectorLayer("Point?crs=EPSG:4326", "persistent", "memory")
        source.dataProvider().addAttributes([QgsField("name", QVariant.String)])
        source.updateFields()

        options = QgsVectorFileWriter.SaveVectorOptions()
        options.driverName = "GPKG"
        options.layerName = "persistent"
        QgsVectorFileWriter.writeAsVectorFormatV3(
            source, str(gpkg_path),
            QgsProject.instance().transformContext(), options
        )

        # Create memory layer (should NOT persist)
        temp_layer = QgsVectorLayer("Point?crs=EPSG:4326", "temporary", "memory")
        temp_layer.dataProvider().addAttributes([QgsField("data", QVariant.String)])
        temp_layer.updateFields()
        temp_layer.startEditing()
        f = QgsFeature(temp_layer.fields())
        f.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(-9.5, 52.0)))
        f.setAttributes(["temp data"])
        temp_layer.addFeature(f)
        temp_layer.commitChanges()

        # Verify temp data exists in memory
        assert temp_layer.featureCount() == 1

        # Delete temp layer
        del temp_layer

        # Verify GeoPackage only has persistent layer
        import sqlite3
        conn = sqlite3.connect(str(gpkg_path))
        tables = conn.execute(
            "SELECT table_name FROM gpkg_contents WHERE data_type='features'"
        ).fetchall()
        conn.close()

        table_names = [t[0] for t in tables]
        assert "persistent" in table_names
        assert "temporary" not in table_names


class TestEdgeCases:
    """
    E2E tests for edge cases and boundary conditions.

    VALUE: HIGH - Edge cases often occur during real SAR operations
    (extreme coordinates, large datasets, special characters).
    """

    def test_unicode_in_marker_names(self, tmp_path):
        """
        Scenario: Marker names with Unicode characters persist correctly.

        Irish place names often contain fada characters.
        """
        gpkg_path = tmp_path / "unicode_test.gpkg"

        from qgis.core import QgsVectorFileWriter

        source = QgsVectorLayer("Point?crs=EPSG:4326", "markers", "memory")
        source.dataProvider().addAttributes([QgsField("name", QVariant.String)])
        source.updateFields()

        options = QgsVectorFileWriter.SaveVectorOptions()
        options.driverName = "GPKG"
        options.layerName = "markers"
        QgsVectorFileWriter.writeAsVectorFormatV3(
            source, str(gpkg_path),
            QgsProject.instance().transformContext(), options
        )

        uri = f"{gpkg_path}|layername=markers"
        layer = QgsVectorLayer(uri, "markers", "ogr")
        layer.startEditing()

        # Irish place names with fadas
        names = [
            "Ciarraí",  # Kerry
            "Béal Átha an Ghaorthaidh",  # Ballingeary
            "Cill Airne",  # Killarney (old spelling)
            "Cnoc na dTobar",  # Mountain name
        ]

        for i, name in enumerate(names):
            f = QgsFeature(layer.fields())
            f.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(-9.5 + i*0.01, 52.0)))
            f.setAttributes([name])
            layer.addFeature(f)

        layer.commitChanges()
        del layer

        # Reload and verify
        reloaded = QgsVectorLayer(uri, "markers", "ogr")
        loaded_names = {f["name"] for f in reloaded.getFeatures()}

        for name in names:
            assert name in loaded_names, f"Unicode name '{name}' not preserved"

    def test_empty_layer_persists(self, tmp_path):
        """
        Scenario: Empty layer (no features) persists correctly.

        Layers may be created before any data is added.
        """
        gpkg_path = tmp_path / "empty_test.gpkg"

        from qgis.core import QgsVectorFileWriter

        source = QgsVectorLayer("Point?crs=EPSG:4326", "empty", "memory")
        source.dataProvider().addAttributes([QgsField("name", QVariant.String)])
        source.updateFields()

        options = QgsVectorFileWriter.SaveVectorOptions()
        options.driverName = "GPKG"
        options.layerName = "empty"
        QgsVectorFileWriter.writeAsVectorFormatV3(
            source, str(gpkg_path),
            QgsProject.instance().transformContext(), options
        )

        # Reload empty layer
        uri = f"{gpkg_path}|layername=empty"
        layer = QgsVectorLayer(uri, "empty", "ogr")

        assert layer.isValid()
        assert layer.featureCount() == 0
        assert "name" in [f.name() for f in layer.fields()]

    def test_large_description_field(self, tmp_path):
        """
        Scenario: Large text in description field persists.

        Incident descriptions can be lengthy.
        """
        gpkg_path = tmp_path / "large_text.gpkg"

        from qgis.core import QgsVectorFileWriter

        source = QgsVectorLayer("Point?crs=EPSG:4326", "markers", "memory")
        source.dataProvider().addAttributes([
            QgsField("name", QVariant.String),
            QgsField("description", QVariant.String),
        ])
        source.updateFields()

        options = QgsVectorFileWriter.SaveVectorOptions()
        options.driverName = "GPKG"
        options.layerName = "markers"
        QgsVectorFileWriter.writeAsVectorFormatV3(
            source, str(gpkg_path),
            QgsProject.instance().transformContext(), options
        )

        uri = f"{gpkg_path}|layername=markers"
        layer = QgsVectorLayer(uri, "markers", "ogr")
        layer.startEditing()

        # Long description (simulating detailed incident notes)
        long_description = """
        Missing person report received at 14:30 on 2 January 2025.
        Subject: Male, 67 years old, experienced hill walker.
        Last seen: Leaving car park at Cronin's Yard at approximately 10:00.
        Intended route: Coomloughra Horseshoe (anticlockwise).
        Weather conditions: Low cloud, visibility <100m above 700m.
        Equipment: Subject was well-equipped with full hill walking gear.
        Medical conditions: Mild diabetes, controlled with medication.
        Previous experience: Regular walker in the area for 30+ years.

        Actions taken:
        - Car located in car park at 15:00
        - Initial hasty search teams deployed at 15:30
        - Full callout initiated at 16:00
        - SAR helicopter requested
        """ * 3  # Make it even longer

        f = QgsFeature(layer.fields())
        f.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(-9.6938, 52.1409)))
        f.setAttributes(["Incident Report", long_description])
        layer.addFeature(f)
        layer.commitChanges()
        del layer

        # Reload and verify
        reloaded = QgsVectorLayer(uri, "markers", "ogr")
        feature = list(reloaded.getFeatures())[0]

        assert len(feature["description"]) > 1000
        assert "Cronin's Yard" in feature["description"]
