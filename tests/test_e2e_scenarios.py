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
