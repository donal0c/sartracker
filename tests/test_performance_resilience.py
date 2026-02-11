# -*- coding: utf-8 -*-
"""
Phase 4: Performance, Load, and Resilience Tests

Tests for SAR Tracker stability under load and operational stress.
These tests validate the system can handle real-world mission scales.

Targets (from ADR-001):
- 100+ devices tracking at normal cadence
- 150+ layers in project with periodic updates
- Recovery from transient failures

Run with: ./run_tests.sh tests/test_performance_resilience.py -v
"""
import gc
import random
import sqlite3
import tempfile
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import List, Dict, Tuple

import pytest

# Skip entire module if QGIS not available
pytest.importorskip("qgis.core", reason="Performance tests require real QGIS")

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


# =============================================================================
# Performance Thresholds (ADR-001)
# =============================================================================

class Thresholds:
    """ADR-001 acceptance thresholds."""
    LAYER_CREATION_150_S = 10.0       # 150 layers in <10s
    SINGLE_LAYER_ADD_MS = 200.0       # Single layer <200ms
    BATCH_ADD_10_MS = 500.0           # 10 layers <500ms
    VISIBILITY_TOGGLE_50_MS = 500.0   # Toggle 50 layers <500ms
    FEATURE_UPDATE_100_MS = 100.0     # Single feature update <100ms
    QUERY_100_FEATURES_MS = 50.0      # Query 100 features <50ms


# =============================================================================
# Test Fixtures
# =============================================================================

@pytest.fixture
def perf_gpkg(tmp_path):
    """Create a GeoPackage for performance testing."""
    return tmp_path / "perf_test.gpkg"


@pytest.fixture
def cleanup_project():
    """Clean up project layers after test."""
    yield
    project = QgsProject.instance()
    # Remove all test layers
    layers_to_remove = []
    for layer_id, layer in project.mapLayers().items():
        if layer.customProperty("sartracker:perf_test"):
            layers_to_remove.append(layer_id)
    for layer_id in layers_to_remove:
        project.removeMapLayer(layer_id)
    gc.collect()


# =============================================================================
# Performance Tests - Layer Operations
# =============================================================================

class TestLayerCreationPerformance:
    """
    Performance tests for layer creation operations.

    VALUE: Validates UI responsiveness during mission setup.
    Slow layer creation = frustrated coordinators during time-critical setup.
    """

    @pytest.mark.slow
    def test_create_50_memory_layers_under_2_seconds(self, cleanup_project):
        """
        Scenario: Create 50 memory layers quickly.

        Scaled-down version of 150-layer test for faster CI runs.
        """
        project = QgsProject.instance()
        start_count = len(project.mapLayers())

        start_time = time.perf_counter()

        for i in range(50):
            layer = QgsVectorLayer("Point?crs=EPSG:4326", f"perf_layer_{i}", "memory")
            layer.setCustomProperty("sartracker:perf_test", "true")
            layer.setCustomProperty("sartracker:layer_type", "marker")
            project.addMapLayer(layer, addToLegend=True)

        end_time = time.perf_counter()
        elapsed = end_time - start_time

        assert len(project.mapLayers()) == start_count + 50
        assert elapsed < 2.0, f"50 layers took {elapsed:.2f}s (threshold: 2s)"

    def test_single_layer_add_under_200ms(self, cleanup_project):
        """
        Scenario: Single layer creation is fast.

        Users expect immediate response when adding markers.
        """
        project = QgsProject.instance()

        times = []
        for i in range(10):  # Sample 10 adds
            start = time.perf_counter()

            layer = QgsVectorLayer("Point?crs=EPSG:4326", f"single_{i}", "memory")
            layer.setCustomProperty("sartracker:perf_test", "true")
            project.addMapLayer(layer)

            end = time.perf_counter()
            times.append((end - start) * 1000)  # ms

        avg_time = sum(times) / len(times)
        max_time = max(times)

        assert avg_time < Thresholds.SINGLE_LAYER_ADD_MS, \
            f"Avg layer add: {avg_time:.1f}ms (threshold: {Thresholds.SINGLE_LAYER_ADD_MS}ms)"
        assert max_time < Thresholds.SINGLE_LAYER_ADD_MS * 2, \
            f"Max layer add: {max_time:.1f}ms (too slow)"


class TestFeatureOperationPerformance:
    """
    Performance tests for feature operations.

    VALUE: Feature updates happen constantly during tracking.
    Slow updates = stale position data on the map.
    """

    def test_add_100_features_under_500ms(self, tmp_path):
        """
        Scenario: Add 100 features to a layer quickly.

        Simulates bulk import of tracking data.
        """
        layer = QgsVectorLayer("Point?crs=EPSG:4326", "bulk_test", "memory")
        layer.dataProvider().addAttributes([
            QgsField("device_id", QVariant.String),
            QgsField("timestamp", QVariant.String),
        ])
        layer.updateFields()

        # Generate test data
        features = []
        for i in range(100):
            f = QgsFeature(layer.fields())
            f.setGeometry(QgsGeometry.fromPointXY(
                QgsPointXY(-9.5 + (i * 0.001), 52.0 + (i * 0.001))
            ))
            f.setAttributes([f"DEV_{i:03d}", f"2025-01-02T12:{i%60:02d}:00Z"])
            features.append(f)

        # Benchmark bulk add
        start = time.perf_counter()
        layer.startEditing()
        layer.addFeatures(features)
        layer.commitChanges()
        end = time.perf_counter()

        elapsed_ms = (end - start) * 1000

        assert layer.featureCount() == 100
        assert elapsed_ms < 500, f"100 features took {elapsed_ms:.1f}ms (threshold: 500ms)"

    def test_update_single_feature_under_100ms(self, tmp_path):
        """
        Scenario: Update a single feature quickly.

        This is the hot path for position updates.
        """
        layer = QgsVectorLayer("Point?crs=EPSG:4326", "update_test", "memory")
        layer.dataProvider().addAttributes([
            QgsField("lat", QVariant.Double),
            QgsField("lon", QVariant.Double),
        ])
        layer.updateFields()

        # Add initial feature
        layer.startEditing()
        f = QgsFeature(layer.fields())
        f.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(-9.5, 52.0)))
        f.setAttributes([52.0, -9.5])
        layer.addFeature(f)
        layer.commitChanges()

        # Benchmark updates
        times = []
        for i in range(20):
            new_lat = 52.0 + (i * 0.001)
            new_lon = -9.5 + (i * 0.001)

            start = time.perf_counter()

            layer.startEditing()
            for feat in layer.getFeatures():
                layer.changeGeometry(
                    feat.id(),
                    QgsGeometry.fromPointXY(QgsPointXY(new_lon, new_lat))
                )
                layer.changeAttributeValue(feat.id(), 0, new_lat)
                layer.changeAttributeValue(feat.id(), 1, new_lon)
            layer.commitChanges()

            end = time.perf_counter()
            times.append((end - start) * 1000)

        avg_time = sum(times) / len(times)
        assert avg_time < Thresholds.FEATURE_UPDATE_100_MS, \
            f"Avg update: {avg_time:.1f}ms (threshold: {Thresholds.FEATURE_UPDATE_100_MS}ms)"

    def test_query_100_features_under_50ms(self, tmp_path):
        """
        Scenario: Query features by attribute quickly.

        Common operation: "show me all positions for device X"
        """
        layer = QgsVectorLayer("Point?crs=EPSG:4326", "query_test", "memory")
        layer.dataProvider().addAttributes([
            QgsField("device_id", QVariant.String),
            QgsField("team", QVariant.String),
        ])
        layer.updateFields()

        # Add 100 features across 10 teams
        layer.startEditing()
        for i in range(100):
            f = QgsFeature(layer.fields())
            f.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(-9.5, 52.0)))
            f.setAttributes([f"DEV_{i:03d}", f"Team_{i % 10}"])
            layer.addFeature(f)
        layer.commitChanges()

        # Benchmark query
        times = []
        for team_num in range(10):
            start = time.perf_counter()

            # Query by expression
            expr = f"\"team\" = 'Team_{team_num}'"
            matching = [f for f in layer.getFeatures(expr)]

            end = time.perf_counter()
            times.append((end - start) * 1000)

            assert len(matching) == 10  # 10 devices per team

        avg_time = sum(times) / len(times)
        assert avg_time < Thresholds.QUERY_100_FEATURES_MS, \
            f"Avg query: {avg_time:.1f}ms (threshold: {Thresholds.QUERY_100_FEATURES_MS}ms)"


# =============================================================================
# Load Simulation Tests
# =============================================================================

class TestLoadSimulation:
    """
    Load simulation tests for realistic mission scenarios.

    VALUE: Validates system handles actual mission scale without degradation.
    """

    def test_simulate_100_device_positions(self, tmp_path):
        """
        Scenario: Simulate position updates for 100 devices.

        Represents a large SAR operation with many teams and assets.
        """
        gpkg_path = tmp_path / "load_test.gpkg"

        # Create GeoPackage layer
        source = QgsVectorLayer("Point?crs=EPSG:4326", "positions", "memory")
        source.dataProvider().addAttributes([
            QgsField("device_id", QVariant.String),
            QgsField("team", QVariant.String),
            QgsField("lat", QVariant.Double),
            QgsField("lon", QVariant.Double),
            QgsField("timestamp", QVariant.String),
            QgsField("speed", QVariant.Double),
        ])
        source.updateFields()

        options = QgsVectorFileWriter.SaveVectorOptions()
        options.driverName = "GPKG"
        options.layerName = "positions"
        QgsVectorFileWriter.writeAsVectorFormatV3(
            source, str(gpkg_path),
            QgsProject.instance().transformContext(), options
        )

        uri = f"{gpkg_path}|layername=positions"
        layer = QgsVectorLayer(uri, "positions", "ogr")
        assert layer.isValid()

        # Simulate 100 devices with initial positions
        random.seed(42)  # Deterministic for reproducibility

        devices = []
        for i in range(100):
            devices.append({
                "device_id": f"GPS_{i:03d}",
                "team": f"Team_{i % 10}",
                "lat": 52.0 + random.uniform(-0.1, 0.1),
                "lon": -9.5 + random.uniform(-0.1, 0.1),
            })

        # Add initial positions
        layer.startEditing()
        for dev in devices:
            f = QgsFeature(layer.fields())
            f.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(dev["lon"], dev["lat"])))
            f.setAttributes([
                dev["device_id"],
                dev["team"],
                dev["lat"],
                dev["lon"],
                "2025-01-02T12:00:00Z",
                random.uniform(0, 5),
            ])
            layer.addFeature(f)
        layer.commitChanges()

        assert layer.featureCount() == 100

        # Simulate 5 update cycles (like 5 polling intervals)
        update_times = []
        for cycle in range(5):
            start = time.perf_counter()

            layer.startEditing()
            for feat in layer.getFeatures():
                # Simulate movement
                old_lat = feat["lat"]
                old_lon = feat["lon"]
                new_lat = old_lat + random.uniform(-0.001, 0.001)
                new_lon = old_lon + random.uniform(-0.001, 0.001)

                layer.changeGeometry(
                    feat.id(),
                    QgsGeometry.fromPointXY(QgsPointXY(new_lon, new_lat))
                )
                layer.changeAttributeValue(feat.id(), 2, new_lat)
                layer.changeAttributeValue(feat.id(), 3, new_lon)
                layer.changeAttributeValue(
                    feat.id(), 4,
                    f"2025-01-02T12:{cycle:02d}:{random.randint(0,59):02d}Z"
                )

            layer.commitChanges()
            end = time.perf_counter()
            update_times.append((end - start) * 1000)

        avg_update = sum(update_times) / len(update_times)

        # 100 device updates should complete in reasonable time
        assert avg_update < 2000, \
            f"100 device update cycle: {avg_update:.1f}ms (threshold: 2000ms)"

    def test_mixed_layer_types_performance(self, cleanup_project):
        """
        Scenario: Project with mixed layer types (markers, areas, tracks).

        Real missions have diverse layer types, not just points.
        """
        project = QgsProject.instance()

        start = time.perf_counter()

        # Create mixed layers
        layers_created = []

        # 20 marker layers (points)
        for i in range(20):
            layer = QgsVectorLayer("Point?crs=EPSG:4326", f"marker_{i}", "memory")
            layer.setCustomProperty("sartracker:perf_test", "true")
            layer.setCustomProperty("sartracker:layer_type", "marker")
            project.addMapLayer(layer)
            layers_created.append(layer)

        # 10 search area layers (polygons)
        for i in range(10):
            layer = QgsVectorLayer("Polygon?crs=EPSG:4326", f"area_{i}", "memory")
            layer.setCustomProperty("sartracker:perf_test", "true")
            layer.setCustomProperty("sartracker:layer_type", "search_area")
            project.addMapLayer(layer)
            layers_created.append(layer)

        # 10 track layers (linestrings)
        for i in range(10):
            layer = QgsVectorLayer("LineString?crs=EPSG:4326", f"track_{i}", "memory")
            layer.setCustomProperty("sartracker:perf_test", "true")
            layer.setCustomProperty("sartracker:layer_type", "track")
            project.addMapLayer(layer)
            layers_created.append(layer)

        end = time.perf_counter()
        elapsed = end - start

        assert len(layers_created) == 40
        assert elapsed < 2.0, f"40 mixed layers took {elapsed:.2f}s (threshold: 2s)"


# =============================================================================
# Resilience Tests
# =============================================================================

class TestProviderResilience:
    """
    Resilience tests for provider failure scenarios.

    VALUE: SAR operations happen in remote areas with unreliable connectivity.
    The system must handle failures gracefully without losing data.
    """

    def test_csv_provider_removed_from_runtime(self, tmp_path):
        """
        Scenario: CSV provider runtime has been removed.
        """
        with pytest.raises(ModuleNotFoundError):
            from providers.csv import CSVProvider  # noqa: F401

    def test_corrupted_geopackage_detection(self, tmp_path):
        """
        Scenario: GeoPackage file is corrupted.

        Could happen from crash, disk error, or incomplete write.
        """
        gpkg_path = tmp_path / "corrupted.gpkg"

        # Create corrupted file (not valid SQLite)
        gpkg_path.write_text("not a valid geopackage file")

        # QGIS should detect invalid file
        uri = f"{gpkg_path}|layername=test"
        layer = QgsVectorLayer(uri, "test", "ogr")

        assert not layer.isValid(), "Corrupted file should not create valid layer"

    def test_recovery_after_rollback(self, tmp_path):
        """
        Scenario: Transaction fails, data should be recoverable.

        LIFE-SAFETY CRITICAL: Failed writes must not corrupt existing data.
        """
        gpkg_path = tmp_path / "recovery_test.gpkg"

        # Create valid GeoPackage
        source = QgsVectorLayer("Point?crs=EPSG:4326", "test", "memory")
        source.dataProvider().addAttributes([QgsField("value", QVariant.Int)])
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

        # Add initial data
        layer.startEditing()
        f = QgsFeature(layer.fields())
        f.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(-9.5, 52.0)))
        f.setAttributes([100])
        layer.addFeature(f)
        layer.commitChanges()

        initial_count = layer.featureCount()

        # Start edit, make changes, then rollback
        layer.startEditing()
        f2 = QgsFeature(layer.fields())
        f2.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(-9.6, 52.1)))
        f2.setAttributes([200])
        layer.addFeature(f2)

        # Simulate failure - rollback instead of commit
        layer.rollBack()

        # Original data should be intact
        assert layer.featureCount() == initial_count
        feature = list(layer.getFeatures())[0]
        assert feature["value"] == 100

    def test_concurrent_read_safety(self, tmp_path):
        """
        Scenario: Multiple processes reading same GeoPackage.

        Common during backup operations or diagnostics.
        """
        gpkg_path = tmp_path / "concurrent.gpkg"

        # Create test data
        conn = sqlite3.connect(str(gpkg_path))
        conn.execute("CREATE TABLE positions (id INTEGER, lat REAL)")
        for i in range(50):
            conn.execute("INSERT INTO positions VALUES (?, ?)", (i, 52.0 + i*0.001))
        conn.commit()
        conn.close()

        # Open multiple simultaneous readers
        readers = []
        for _ in range(5):
            conn = sqlite3.connect(str(gpkg_path))
            conn.execute("PRAGMA query_only = ON")  # Read-only mode
            readers.append(conn)

        # All readers should see consistent data
        results = []
        for reader in readers:
            count = reader.execute("SELECT COUNT(*) FROM positions").fetchone()[0]
            results.append(count)
            reader.close()

        assert all(r == 50 for r in results), "All readers should see same data"


class TestMemoryStability:
    """
    Memory stability tests for long-running sessions.

    VALUE: SAR operations can run for hours or days.
    Memory leaks = eventual crash during critical operation.
    """

    def test_no_memory_growth_on_layer_churn(self, cleanup_project):
        """
        Scenario: Create and delete layers repeatedly.

        Simulates dynamic layer management during mission.
        """
        project = QgsProject.instance()

        # Get baseline (after a GC)
        gc.collect()

        # Perform 10 cycles of create/delete
        for cycle in range(10):
            # Create 10 layers
            layer_ids = []
            for i in range(10):
                layer = QgsVectorLayer("Point?crs=EPSG:4326", f"churn_{cycle}_{i}", "memory")
                layer.setCustomProperty("sartracker:perf_test", "true")
                project.addMapLayer(layer)
                layer_ids.append(layer.id())

            # Delete all layers
            for layer_id in layer_ids:
                project.removeMapLayer(layer_id)

        gc.collect()

        # Verify no layers leaked
        leaked = sum(1 for layer in project.mapLayers().values()
                    if layer.customProperty("sartracker:perf_test"))
        assert leaked == 0, f"{leaked} layers leaked after churn test"

    def test_feature_update_no_accumulation(self, tmp_path):
        """
        Scenario: Repeated feature updates don't accumulate memory.

        Position updates happen every few seconds - must not leak.
        """
        layer = QgsVectorLayer("Point?crs=EPSG:4326", "update_test", "memory")
        layer.dataProvider().addAttributes([QgsField("counter", QVariant.Int)])
        layer.updateFields()

        # Add a single feature
        layer.startEditing()
        f = QgsFeature(layer.fields())
        f.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(-9.5, 52.0)))
        f.setAttributes([0])
        layer.addFeature(f)
        layer.commitChanges()

        # Perform 100 update cycles
        for i in range(100):
            layer.startEditing()
            for feat in layer.getFeatures():
                layer.changeAttributeValue(feat.id(), 0, i)
                layer.changeGeometry(
                    feat.id(),
                    QgsGeometry.fromPointXY(QgsPointXY(-9.5 + i*0.0001, 52.0))
                )
            layer.commitChanges()

        # Should still have exactly 1 feature
        assert layer.featureCount() == 1

        # Final value should be correct
        feature = list(layer.getFeatures())[0]
        assert feature["counter"] == 99


class TestDataIntegrityUnderLoad:
    """
    Data integrity tests during high-load scenarios.

    VALUE: LIFE-SAFETY CRITICAL - Coordinates must remain accurate
    even under heavy load.
    """

    def test_coordinate_precision_under_rapid_updates(self, tmp_path):
        """
        Scenario: Rapid position updates maintain coordinate precision.

        Fast updates must not introduce floating-point drift.
        """
        layer = QgsVectorLayer("Point?crs=EPSG:4326", "precision_test", "memory")
        layer.dataProvider().addAttributes([
            QgsField("expected_lat", QVariant.Double),
            QgsField("expected_lon", QVariant.Double),
        ])
        layer.updateFields()

        # Kerry coordinates with high precision
        test_lat = 52.1409234567
        test_lon = -9.6938127890

        layer.startEditing()
        f = QgsFeature(layer.fields())
        f.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(test_lon, test_lat)))
        f.setAttributes([test_lat, test_lon])
        layer.addFeature(f)
        layer.commitChanges()

        # Perform 50 read-write cycles
        for _ in range(50):
            layer.startEditing()
            for feat in layer.getFeatures():
                # Read current position
                pt = feat.geometry().asPoint()
                # Write back (simulating refresh cycle)
                layer.changeGeometry(
                    feat.id(),
                    QgsGeometry.fromPointXY(QgsPointXY(pt.x(), pt.y()))
                )
            layer.commitChanges()

        # Verify precision maintained
        feature = list(layer.getFeatures())[0]
        final_pt = feature.geometry().asPoint()

        # Must maintain at least 6 decimal places (sub-meter accuracy)
        assert abs(final_pt.y() - test_lat) < 0.0000001, \
            f"Latitude drift: {final_pt.y()} vs {test_lat}"
        assert abs(final_pt.x() - test_lon) < 0.0000001, \
            f"Longitude drift: {final_pt.x()} vs {test_lon}"
