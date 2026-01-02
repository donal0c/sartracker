# -*- coding: utf-8 -*-
"""
QGIS integration tests using pytest-qgis.

These tests require a real QGIS environment and will be skipped
when QGIS is not available.

To run these tests:
    1. Ensure QGIS is installed
    2. Install pytest-qgis: pip install pytest-qgis
    3. Run: pytest -m qgis_required

The qgis_required marker is automatically applied to tests in this file.
"""

import pytest

# Mark entire module as requiring QGIS
pytestmark = pytest.mark.qgis_required


class TestQGISAvailability:
    """Basic tests to verify QGIS integration is working."""

    def test_qgis_core_import(self):
        """Verify qgis.core can be imported."""
        from qgis.core import QgsProject
        assert QgsProject is not None

    def test_qgis_project_instance(self):
        """Verify QgsProject.instance() works."""
        from qgis.core import QgsProject
        project = QgsProject.instance()
        assert project is not None

    def test_qgis_coordinate_reference_system(self):
        """Verify CRS operations work."""
        from qgis.core import QgsCoordinateReferenceSystem
        wgs84 = QgsCoordinateReferenceSystem("EPSG:4326")
        assert wgs84.isValid()
        assert wgs84.authid() == "EPSG:4326"

    def test_qgis_itm_crs(self):
        """Verify Irish Transverse Mercator CRS is available."""
        from qgis.core import QgsCoordinateReferenceSystem
        itm = QgsCoordinateReferenceSystem("EPSG:2157")
        assert itm.isValid()
        assert itm.authid() == "EPSG:2157"


class TestQGISProjectFixture:
    """Tests using pytest-qgis fixtures."""

    def test_new_project_is_empty(self, qgis_new_project):
        """Verify new project fixture provides clean project."""
        from qgis.core import QgsProject
        project = QgsProject.instance()
        # New project should have no layers
        assert project.mapLayers() == {}

    def test_can_add_memory_layer(self, qgis_new_project):
        """Verify we can add a memory layer to the project."""
        from qgis.core import QgsProject, QgsVectorLayer

        layer = QgsVectorLayer("Point?crs=EPSG:4326", "test_layer", "memory")
        assert layer.isValid()

        QgsProject.instance().addMapLayer(layer)
        assert "test_layer" in [l.name() for l in QgsProject.instance().mapLayers().values()]


class TestCoordinateTransforms:
    """Tests for coordinate transformations - critical for SAR operations."""

    def test_wgs84_to_itm_transform(self):
        """Test WGS84 to Irish Transverse Mercator transformation."""
        from qgis.core import (
            QgsCoordinateReferenceSystem,
            QgsCoordinateTransform,
            QgsPointXY,
            QgsProject,
        )

        wgs84 = QgsCoordinateReferenceSystem("EPSG:4326")
        itm = QgsCoordinateReferenceSystem("EPSG:2157")

        transform = QgsCoordinateTransform(wgs84, itm, QgsProject.instance())

        # Kerry, Ireland (approximate)
        point_wgs84 = QgsPointXY(-9.6938, 52.1409)  # lon, lat order
        point_itm = transform.transform(point_wgs84)

        # ITM coordinates should be roughly in the expected range for Kerry
        assert 400000 < point_itm.x() < 550000  # Easting
        assert 500000 < point_itm.y() < 700000  # Northing

    def test_itm_to_wgs84_transform(self):
        """Test Irish Transverse Mercator to WGS84 transformation."""
        from qgis.core import (
            QgsCoordinateReferenceSystem,
            QgsCoordinateTransform,
            QgsPointXY,
            QgsProject,
        )

        wgs84 = QgsCoordinateReferenceSystem("EPSG:4326")
        itm = QgsCoordinateReferenceSystem("EPSG:2157")

        transform = QgsCoordinateTransform(itm, wgs84, QgsProject.instance())

        # Kerry, Ireland (approximate ITM)
        point_itm = QgsPointXY(451234, 598765)
        point_wgs84 = transform.transform(point_itm)

        # Should be somewhere in western Ireland
        assert -11 < point_wgs84.x() < -9  # Longitude
        assert 51 < point_wgs84.y() < 53   # Latitude

    def test_roundtrip_transform_accuracy(self):
        """Test that roundtrip transformations are accurate."""
        from qgis.core import (
            QgsCoordinateReferenceSystem,
            QgsCoordinateTransform,
            QgsPointXY,
            QgsProject,
        )

        wgs84 = QgsCoordinateReferenceSystem("EPSG:4326")
        itm = QgsCoordinateReferenceSystem("EPSG:2157")

        to_itm = QgsCoordinateTransform(wgs84, itm, QgsProject.instance())
        to_wgs84 = QgsCoordinateTransform(itm, wgs84, QgsProject.instance())

        original = QgsPointXY(-9.6938, 52.1409)
        itm_point = to_itm.transform(original)
        roundtrip = to_wgs84.transform(itm_point)

        # Should be within 0.0001 degrees (about 10 meters)
        assert abs(roundtrip.x() - original.x()) < 0.0001
        assert abs(roundtrip.y() - original.y()) < 0.0001


class TestMemoryLayers:
    """Tests for memory layer operations."""

    def test_create_point_memory_layer(self, qgis_new_project):
        """Test creating a point memory layer."""
        from qgis.core import QgsVectorLayer, QgsFeature, QgsGeometry, QgsPointXY

        layer = QgsVectorLayer(
            "Point?crs=EPSG:4326&field=name:string&field=type:string",
            "test_points",
            "memory"
        )
        assert layer.isValid()

        # Add a feature
        feature = QgsFeature()
        feature.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(-9.6938, 52.1409)))
        feature.setAttributes(["IPP", "person"])

        layer.dataProvider().addFeature(feature)
        assert layer.featureCount() == 1

    def test_create_polygon_memory_layer(self, qgis_new_project):
        """Test creating a polygon memory layer (for search areas)."""
        from qgis.core import QgsVectorLayer, QgsFeature, QgsGeometry, QgsPointXY

        layer = QgsVectorLayer(
            "Polygon?crs=EPSG:4326&field=name:string&field=status:string",
            "search_areas",
            "memory"
        )
        assert layer.isValid()

        # Create a simple square polygon
        points = [
            QgsPointXY(-9.7, 52.1),
            QgsPointXY(-9.6, 52.1),
            QgsPointXY(-9.6, 52.2),
            QgsPointXY(-9.7, 52.2),
            QgsPointXY(-9.7, 52.1),  # Close the polygon
        ]

        feature = QgsFeature()
        feature.setGeometry(QgsGeometry.fromPolygonXY([points]))
        feature.setAttributes(["Area 1", "active"])

        layer.dataProvider().addFeature(feature)
        assert layer.featureCount() == 1

    def test_create_line_memory_layer(self, qgis_new_project):
        """Test creating a line memory layer (for tracks, bearings)."""
        from qgis.core import QgsVectorLayer, QgsFeature, QgsGeometry, QgsPointXY

        layer = QgsVectorLayer(
            "LineString?crs=EPSG:4326&field=device_id:string&field=timestamp:string",
            "tracks",
            "memory"
        )
        assert layer.isValid()

        # Create a simple track
        points = [
            QgsPointXY(-9.7, 52.1),
            QgsPointXY(-9.65, 52.12),
            QgsPointXY(-9.6, 52.15),
        ]

        feature = QgsFeature()
        feature.setGeometry(QgsGeometry.fromPolylineXY(points))
        feature.setAttributes(["device001", "2025-01-01T10:00:00"])

        layer.dataProvider().addFeature(feature)
        assert layer.featureCount() == 1
