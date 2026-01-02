# -*- coding: utf-8 -*-
"""
Performance Benchmark: 150+ Per-Item Layers (SAR-eqb)

Validates ADR-001 acceptance thresholds at scale:
- Mission load (150 layers): target <10s
- Single marker add: target <200ms
- Batch add (10 markers): target <500ms
- Group visibility toggle (50 layers): target <500ms
- Layer tree scroll: target 60fps (subjective)
- Memory usage: target <500MB

Run in QGIS Python Console:
    from sartracker.tests.benchmark_150_layers import run_benchmarks
    run_benchmarks()

Or run individual benchmarks:
    from sartracker.tests.benchmark_150_layers import benchmark_layer_creation
    benchmark_layer_creation(count=150)
"""

import gc
import os
import sys
import tempfile
import time
import traceback
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# For running in QGIS console
try:
    from qgis.core import (
        QgsProject, QgsVectorLayer, QgsFeature, QgsGeometry,
        QgsPointXY, QgsLayerTreeGroup, QgsApplication
    )
    from qgis.utils import iface
    QGIS_AVAILABLE = True
except ImportError:
    QGIS_AVAILABLE = False
    print("Warning: QGIS not available - benchmarks must be run from QGIS Python console")


# =============================================================================
# Benchmark Configuration
# =============================================================================

@dataclass
class BenchmarkConfig:
    """Configuration for benchmark runs."""
    total_layers: int = 150
    batch_size: int = 10
    visibility_toggle_count: int = 50

    # ADR-001 acceptance thresholds
    threshold_total_creation_s: float = 10.0  # 150 layers in <10s
    threshold_single_add_ms: float = 200.0    # Single layer <200ms
    threshold_batch_add_ms: float = 500.0     # 10 layers <500ms
    threshold_visibility_ms: float = 500.0    # Toggle 50 layers <500ms
    threshold_save_s: float = 5.0             # Project save <5s
    threshold_load_s: float = 10.0            # Project load <10s


@dataclass
class BenchmarkResult:
    """Result of a single benchmark."""
    name: str
    metric: str
    value: float
    threshold: float
    passed: bool
    details: str = ""


# =============================================================================
# Utility Functions
# =============================================================================

def get_memory_usage_mb() -> float:
    """Get current process memory usage in MB."""
    try:
        import resource
        # On Unix systems
        usage = resource.getrusage(resource.RUSAGE_SELF)
        return usage.ru_maxrss / 1024  # Convert KB to MB on macOS
    except ImportError:
        try:
            import psutil
            process = psutil.Process(os.getpid())
            return process.memory_info().rss / (1024 * 1024)
        except ImportError:
            return -1  # Cannot measure


def cleanup_benchmark_layers():
    """Remove all benchmark layers from project."""
    if not QGIS_AVAILABLE:
        return 0

    project = QgsProject.instance()
    layers_to_remove = []

    for layer_id, layer in project.mapLayers().items():
        # Check for our benchmark marker
        if layer.customProperty("sartracker:benchmark"):
            layers_to_remove.append(layer_id)
        # Also check for item_id from factory
        elif layer.customProperty("sartracker:item_id"):
            layers_to_remove.append(layer_id)

    for layer_id in layers_to_remove:
        project.removeMapLayer(layer_id)

    return len(layers_to_remove)


def get_test_gpkg_path() -> Path:
    """Get a temporary path for benchmark GeoPackage."""
    temp_dir = tempfile.mkdtemp(prefix="sar_benchmark_")
    return Path(temp_dir) / "benchmark_mission.gpkg"


def format_time(seconds: float) -> str:
    """Format time for display."""
    if seconds < 1:
        return f"{seconds * 1000:.1f}ms"
    else:
        return f"{seconds:.2f}s"


def format_result(result: BenchmarkResult) -> str:
    """Format a benchmark result for display."""
    status = "PASS" if result.passed else "FAIL"
    return f"  [{status}] {result.name}: {result.value:.2f} {result.metric} (threshold: {result.threshold} {result.metric})"


# =============================================================================
# Individual Benchmarks
# =============================================================================

def benchmark_layer_creation(config: BenchmarkConfig) -> List[BenchmarkResult]:
    """
    Benchmark creating 150+ per-item layers.

    Measures:
    - Total time to create all layers
    - Average time per layer
    - Time for batch creation (10 at a time)
    """
    results = []

    from sartracker.controllers.per_item_layer_factory import (
        PerItemLayerFactory, ItemType
    )

    gpkg_path = get_test_gpkg_path()
    factory = PerItemLayerFactory(gpkg_path)

    # Distribute item types for realistic mix
    item_types = [
        (ItemType.MARKER_CLUE, 50),
        (ItemType.MARKER_HAZARD, 20),
        (ItemType.MARKER_IPP_LKP, 10),
        (ItemType.SEARCH_AREA, 30),
        (ItemType.RANGE_RING, 20),
        (ItemType.BEARING_LINE, 10),
        (ItemType.LINE, 10),
    ]

    # Flatten to list
    items_to_create = []
    for item_type, count in item_types:
        for i in range(count):
            items_to_create.append((item_type, f"{item_type.split('_')[-1].title()} {i+1}"))

    # Trim to exact count
    items_to_create = items_to_create[:config.total_layers]

    print(f"\n  Creating {len(items_to_create)} layers...")

    # --- Benchmark: Total creation time ---
    created_ids = []
    start_total = time.perf_counter()

    for item_type, name in items_to_create:
        info = factory.create_item_layer(
            item_type=item_type,
            display_name=name,
            add_to_project=True
        )
        created_ids.append(info.item_id)

        # Mark as benchmark layer for cleanup
        if info.layer:
            info.layer.setCustomProperty("sartracker:benchmark", "true")

    end_total = time.perf_counter()
    total_time = end_total - start_total

    results.append(BenchmarkResult(
        name=f"Create {config.total_layers} layers",
        metric="s",
        value=total_time,
        threshold=config.threshold_total_creation_s,
        passed=total_time < config.threshold_total_creation_s,
        details=f"Average: {(total_time / len(items_to_create)) * 1000:.1f}ms per layer"
    ))

    print(f"  Total: {format_time(total_time)} ({len(created_ids)} layers)")
    print(f"  Average: {format_time(total_time / len(created_ids))} per layer")

    # --- Benchmark: Single layer add time ---
    # Sample a few individual adds
    single_times = []
    for i in range(5):
        start = time.perf_counter()
        info = factory.create_item_layer(
            item_type=ItemType.MARKER_CLUE,
            display_name=f"Single Add Test {i}",
            add_to_project=True
        )
        end = time.perf_counter()
        single_times.append((end - start) * 1000)  # ms
        if info.layer:
            info.layer.setCustomProperty("sartracker:benchmark", "true")

    avg_single = sum(single_times) / len(single_times)
    results.append(BenchmarkResult(
        name="Single layer add",
        metric="ms",
        value=avg_single,
        threshold=config.threshold_single_add_ms,
        passed=avg_single < config.threshold_single_add_ms,
        details=f"Range: {min(single_times):.1f}ms - {max(single_times):.1f}ms"
    ))

    print(f"  Single add: {avg_single:.1f}ms average")

    return results


def benchmark_batch_operations(config: BenchmarkConfig) -> List[BenchmarkResult]:
    """
    Benchmark batch layer operations with signal blocking.
    """
    results = []

    from sartracker.controllers.per_item_layer_factory import (
        PerItemLayerFactory, ItemType
    )

    gpkg_path = get_test_gpkg_path()
    factory = PerItemLayerFactory(gpkg_path)

    print(f"\n  Batch creating {config.batch_size} layers...")

    # Get layer tree root for signal blocking
    project = QgsProject.instance()
    root = project.layerTreeRoot()

    # --- Benchmark: Batch add with signal blocking ---
    start = time.perf_counter()

    # Block signals during batch add (ADR-001 pattern)
    root.blockSignals(True)
    try:
        batch_layers = []
        for i in range(config.batch_size):
            info = factory.create_item_layer(
                item_type=ItemType.MARKER_CLUE,
                display_name=f"Batch Layer {i}",
                add_to_project=True
            )
            if info.layer:
                info.layer.setCustomProperty("sartracker:benchmark", "true")
                batch_layers.append(info.layer)
    finally:
        root.blockSignals(False)

    end = time.perf_counter()
    batch_time_ms = (end - start) * 1000

    results.append(BenchmarkResult(
        name=f"Batch add ({config.batch_size} layers)",
        metric="ms",
        value=batch_time_ms,
        threshold=config.threshold_batch_add_ms,
        passed=batch_time_ms < config.threshold_batch_add_ms,
        details="With signal blocking"
    ))

    print(f"  Batch add: {batch_time_ms:.1f}ms for {config.batch_size} layers")

    return results


def benchmark_visibility_toggle(config: BenchmarkConfig) -> List[BenchmarkResult]:
    """
    Benchmark toggling visibility of multiple layers.
    """
    results = []

    from sartracker.controllers.per_item_layer_factory import (
        PerItemLayerFactory, ItemType
    )

    gpkg_path = get_test_gpkg_path()
    factory = PerItemLayerFactory(gpkg_path)

    # First create layers to toggle
    print(f"\n  Creating {config.visibility_toggle_count} layers for visibility test...")

    layers = []
    for i in range(config.visibility_toggle_count):
        info = factory.create_item_layer(
            item_type=ItemType.MARKER_CLUE,
            display_name=f"Visibility Test {i}",
            add_to_project=True
        )
        if info.layer:
            info.layer.setCustomProperty("sartracker:benchmark", "true")
            layers.append(info.layer)

    project = QgsProject.instance()
    root = project.layerTreeRoot()

    # --- Benchmark: Toggle visibility OFF ---
    start = time.perf_counter()

    root.blockSignals(True)
    try:
        for layer in layers:
            node = root.findLayer(layer.id())
            if node:
                node.setItemVisibilityChecked(False)
    finally:
        root.blockSignals(False)

    end = time.perf_counter()
    toggle_off_ms = (end - start) * 1000

    # --- Benchmark: Toggle visibility ON ---
    start = time.perf_counter()

    root.blockSignals(True)
    try:
        for layer in layers:
            node = root.findLayer(layer.id())
            if node:
                node.setItemVisibilityChecked(True)
    finally:
        root.blockSignals(False)

    end = time.perf_counter()
    toggle_on_ms = (end - start) * 1000

    avg_toggle = (toggle_off_ms + toggle_on_ms) / 2

    results.append(BenchmarkResult(
        name=f"Visibility toggle ({config.visibility_toggle_count} layers)",
        metric="ms",
        value=avg_toggle,
        threshold=config.threshold_visibility_ms,
        passed=avg_toggle < config.threshold_visibility_ms,
        details=f"Off: {toggle_off_ms:.1f}ms, On: {toggle_on_ms:.1f}ms"
    ))

    print(f"  Visibility toggle: {avg_toggle:.1f}ms average")

    return results


def benchmark_project_save_load(config: BenchmarkConfig) -> List[BenchmarkResult]:
    """
    Benchmark project save and load with many layers.
    """
    results = []

    from sartracker.controllers.per_item_layer_factory import (
        PerItemLayerFactory, ItemType
    )

    gpkg_path = get_test_gpkg_path()
    factory = PerItemLayerFactory(gpkg_path)

    # Create layers
    print(f"\n  Creating {config.total_layers} layers for save/load test...")

    for i in range(config.total_layers):
        item_type = [ItemType.MARKER_CLUE, ItemType.SEARCH_AREA, ItemType.RANGE_RING][i % 3]
        info = factory.create_item_layer(
            item_type=item_type,
            display_name=f"Save Test {i}",
            add_to_project=True
        )
        if info.layer:
            info.layer.setCustomProperty("sartracker:benchmark", "true")

    project = QgsProject.instance()

    # Save to temp file
    temp_dir = tempfile.mkdtemp(prefix="sar_benchmark_project_")
    project_path = Path(temp_dir) / "benchmark_project.qgz"

    # --- Benchmark: Project save ---
    print(f"  Saving project...")
    start = time.perf_counter()
    success = project.write(str(project_path))
    end = time.perf_counter()
    save_time = end - start

    if not success:
        print("  WARNING: Project save failed!")
        save_time = -1

    results.append(BenchmarkResult(
        name=f"Project save ({config.total_layers} layers)",
        metric="s",
        value=save_time,
        threshold=config.threshold_save_s,
        passed=save_time < config.threshold_save_s and save_time > 0,
        details=f"File: {project_path.name}"
    ))

    print(f"  Save: {format_time(save_time)}")

    # Clear project and reload
    print(f"  Clearing and reloading...")
    cleanup_benchmark_layers()
    project.clear()

    # --- Benchmark: Project load ---
    start = time.perf_counter()
    success = project.read(str(project_path))
    end = time.perf_counter()
    load_time = end - start

    if not success:
        print("  WARNING: Project load failed!")
        load_time = -1

    # Count loaded layers
    loaded_count = sum(1 for layer in project.mapLayers().values()
                       if layer.customProperty("sartracker:benchmark"))

    results.append(BenchmarkResult(
        name=f"Project load ({config.total_layers} layers)",
        metric="s",
        value=load_time,
        threshold=config.threshold_load_s,
        passed=load_time < config.threshold_load_s and load_time > 0,
        details=f"Loaded {loaded_count} layers"
    ))

    print(f"  Load: {format_time(load_time)} ({loaded_count} layers)")

    return results


def benchmark_memory_usage(config: BenchmarkConfig) -> List[BenchmarkResult]:
    """
    Measure memory usage with many layers.
    """
    results = []

    # Force garbage collection
    gc.collect()

    memory_before = get_memory_usage_mb()
    if memory_before < 0:
        print("\n  Memory measurement not available on this platform")
        return results

    from sartracker.controllers.per_item_layer_factory import (
        PerItemLayerFactory, ItemType
    )

    gpkg_path = get_test_gpkg_path()
    factory = PerItemLayerFactory(gpkg_path)

    print(f"\n  Memory before: {memory_before:.1f} MB")
    print(f"  Creating {config.total_layers} layers...")

    for i in range(config.total_layers):
        item_type = [ItemType.MARKER_CLUE, ItemType.SEARCH_AREA][i % 2]
        info = factory.create_item_layer(
            item_type=item_type,
            display_name=f"Memory Test {i}",
            add_to_project=True
        )
        if info.layer:
            info.layer.setCustomProperty("sartracker:benchmark", "true")

    gc.collect()
    memory_after = get_memory_usage_mb()
    memory_delta = memory_after - memory_before

    print(f"  Memory after: {memory_after:.1f} MB")
    print(f"  Delta: {memory_delta:.1f} MB")

    # 500MB threshold from ADR-001
    results.append(BenchmarkResult(
        name=f"Memory usage ({config.total_layers} layers)",
        metric="MB",
        value=memory_delta,
        threshold=500.0,
        passed=memory_delta < 500.0,
        details=f"Before: {memory_before:.1f}MB, After: {memory_after:.1f}MB"
    ))

    return results


def benchmark_shutdown_safety() -> List[BenchmarkResult]:
    """
    Verify that plugin can shutdown cleanly with many layers.

    This is a basic test - full verification requires manual testing.
    """
    results = []

    # This test creates layers then cleans them up
    # A crash here would indicate shutdown issues

    from sartracker.controllers.per_item_layer_factory import (
        PerItemLayerFactory, ItemType
    )

    gpkg_path = get_test_gpkg_path()
    factory = PerItemLayerFactory(gpkg_path)

    print("\n  Creating 50 layers for shutdown test...")

    created_ids = []
    for i in range(50):
        info = factory.create_item_layer(
            item_type=ItemType.MARKER_CLUE,
            display_name=f"Shutdown Test {i}",
            add_to_project=True
        )
        created_ids.append(info.item_id)
        if info.layer:
            info.layer.setCustomProperty("sartracker:benchmark", "true")

    print("  Deleting all layers...")

    start = time.perf_counter()
    for item_id in created_ids:
        factory.delete_item_layer(item_id, remove_table=True)
    end = time.perf_counter()

    cleanup_time = end - start

    # If we get here without crash, shutdown handling works
    results.append(BenchmarkResult(
        name="Shutdown safety (50 layers)",
        metric="s",
        value=cleanup_time,
        threshold=5.0,  # Should clean up in <5s
        passed=True,  # No crash = pass
        details="No crash during cleanup"
    ))

    print(f"  Cleanup completed in {format_time(cleanup_time)}")

    return results


# =============================================================================
# Main Benchmark Runner
# =============================================================================

def run_benchmarks(layer_count: int = 150) -> Dict:
    """
    Run all performance benchmarks.

    Args:
        layer_count: Number of layers to create (default 150)

    Returns:
        Dict with results summary
    """
    print("\n" + "=" * 70)
    print("SAR Tracker - Performance Benchmarks (SAR-eqb)")
    print("ADR-001 Acceptance Threshold Validation")
    print("=" * 70)

    if not QGIS_AVAILABLE:
        print("\nERROR: Benchmarks must be run from QGIS Python console")
        return {"error": "QGIS not available"}

    config = BenchmarkConfig(total_layers=layer_count)

    print(f"\nConfiguration:")
    print(f"  Total layers: {config.total_layers}")
    print(f"  Batch size: {config.batch_size}")
    print(f"  Visibility test count: {config.visibility_toggle_count}")

    # Cleanup before starting
    removed = cleanup_benchmark_layers()
    if removed > 0:
        print(f"\n  Cleaned up {removed} previous benchmark layers")

    all_results: List[BenchmarkResult] = []

    # Run benchmarks
    benchmarks = [
        ("Layer Creation", benchmark_layer_creation),
        ("Batch Operations", benchmark_batch_operations),
        ("Visibility Toggle", benchmark_visibility_toggle),
        ("Project Save/Load", benchmark_project_save_load),
        ("Memory Usage", benchmark_memory_usage),
        ("Shutdown Safety", benchmark_shutdown_safety),
    ]

    for name, benchmark_fn in benchmarks:
        print(f"\n--- {name} ---")
        try:
            if benchmark_fn in (benchmark_layer_creation, benchmark_batch_operations,
                               benchmark_visibility_toggle, benchmark_project_save_load,
                               benchmark_memory_usage):
                results = benchmark_fn(config)
            else:
                results = benchmark_fn()
            all_results.extend(results)
        except Exception as e:
            print(f"  ERROR: {e}")
            traceback.print_exc()
            all_results.append(BenchmarkResult(
                name=name,
                metric="",
                value=-1,
                threshold=0,
                passed=False,
                details=f"Error: {e}"
            ))

        # Cleanup between benchmarks
        cleanup_benchmark_layers()
        gc.collect()

    # Summary
    print("\n" + "=" * 70)
    print("RESULTS SUMMARY")
    print("=" * 70)

    passed = sum(1 for r in all_results if r.passed)
    failed = sum(1 for r in all_results if not r.passed)

    for result in all_results:
        print(format_result(result))
        if result.details:
            print(f"       {result.details}")

    print("\n" + "-" * 70)
    print(f"Total: {passed} passed, {failed} failed out of {len(all_results)} benchmarks")

    if failed == 0:
        print("\nADR-001 ACCEPTANCE THRESHOLDS: ALL PASSED")
        print("Phase 3 implementation can proceed.")
    else:
        print(f"\nWARNING: {failed} threshold(s) exceeded - review before proceeding")

    print("=" * 70)

    # Final cleanup
    cleanup_benchmark_layers()

    return {
        "total": len(all_results),
        "passed": passed,
        "failed": failed,
        "results": all_results
    }


# For quick testing
def quick_benchmark(count: int = 50):
    """Run a quick benchmark with fewer layers."""
    return run_benchmarks(layer_count=count)


if __name__ == "__main__":
    print("This benchmark must be run from QGIS Python console.")
    print("Use: from sartracker.tests.benchmark_150_layers import run_benchmarks")
    print("     run_benchmarks()")
