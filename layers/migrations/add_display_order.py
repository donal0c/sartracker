# -*- coding: utf-8 -*-
"""
Migration: Add display_order field to layers

Adds display_order INTEGER field to layers that support manual ordering.
Backfills display_order = feature.id() for deterministic initial order.

Phase 2 - Layer Operations API (CalTopo Console Support)
LIFE-SAFETY CRITICAL: Handle all errors gracefully, never corrupt existing data.

Qt5/Qt6 Compatible: Uses QGIS API only.
"""

from qgis.core import QgsField, QgsVectorLayer, QgsFeatureRequest
from qgis.PyQt.QtCore import QVariant
from typing import List
from ..schema import LayerIds


# Layers that need display_order field for manual ordering
LAYERS_TO_MIGRATE = [
    LayerIds.SEARCH_AREAS,
    LayerIds.SEARCH_SECTORS,
    LayerIds.MARKERS_IPP_LKP,
    LayerIds.MARKERS_CLUES,
    LayerIds.MARKERS_HAZARDS,
    LayerIds.MARKERS_CASUALTIES,
    LayerIds.LINES,
    LayerIds.RANGE_RINGS,
    LayerIds.BEARING_LINES,
    LayerIds.TEXT_LABELS,
]


def migrate_layer(layer: QgsVectorLayer, layer_id: str) -> bool:
    """
    Add display_order field to layer and backfill with feature IDs.

    CRITICAL: Transaction-safe pattern for life-safety system.
    Rollback on any error to prevent data corruption.

    Args:
        layer: QGIS vector layer to migrate
        layer_id: Layer identifier from LayerIds

    Returns:
        True if migration successful
        False if already migrated or migration failed

    Raises:
        RuntimeError: If critical error occurs (caller should handle)
    """
    # ========================================================================
    # STEP 1: VALIDATE LAYER
    # ========================================================================

    if not layer or not layer.isValid():
        print(f"[Migration] ERROR: Layer {layer_id} is invalid or not available")
        return False

    # ========================================================================
    # STEP 2: CHECK IF ALREADY MIGRATED
    # ========================================================================

    # Check if field already exists
    if layer.fields().indexFromName('display_order') != -1:
        print(f"[Migration] Layer {layer_id} already has display_order field")
        return False

    print(f"[Migration] Adding display_order field to {layer_id}...")

    # ========================================================================
    # STEP 3: START TRANSACTION
    # ========================================================================

    # Check if layer is already being edited (safety check)
    if layer.isEditable():
        print(f"[Migration] WARNING: Layer {layer_id} is already in edit mode, skipping")
        return False

    # Start editing
    if not layer.startEditing():
        print(f"[Migration] ERROR: Failed to start editing {layer_id}")
        return False

    try:
        # ====================================================================
        # STEP 4: ADD FIELD
        # ====================================================================

        # Create field (nullable integer, no default value for now)
        field = QgsField('display_order', QVariant.Int)

        if not layer.addAttribute(field):
            raise RuntimeError("Failed to add display_order attribute")

        # Verify field was added
        field_index = layer.fields().indexFromName('display_order')
        if field_index == -1:
            raise RuntimeError("display_order field not found after add")

        print(f"[Migration] Added display_order field to {layer_id} at index {field_index}")

        # ====================================================================
        # STEP 5: BACKFILL VALUES
        # ====================================================================

        # Backfill: display_order = feature.id()
        # This ensures deterministic order based on creation order
        updated_count = 0
        features = list(layer.getFeatures(QgsFeatureRequest()))

        print(f"[Migration] Backfilling {len(features)} features...")

        for feature in features:
            feature_id = feature.id()

            # Set display_order to feature ID for initial deterministic order
            success = layer.changeAttributeValue(feature_id, field_index, feature_id)

            if not success:
                raise RuntimeError(f"Failed to update display_order for feature {feature_id}")

            updated_count += 1

            # Progress indicator for large layers
            if updated_count % 100 == 0:
                print(f"[Migration] Backfilled {updated_count}/{len(features)} features...")

        # ====================================================================
        # STEP 6: COMMIT CHANGES
        # ====================================================================

        if not layer.commitChanges():
            # Get commit errors for better error message
            errors = layer.commitErrors()
            raise RuntimeError(f"Commit failed: {', '.join(errors)}")

        print(f"[Migration] ✓ Added display_order to {layer_id}, backfilled {updated_count} features")
        return True

    except Exception as e:
        # ====================================================================
        # STEP 7: ROLLBACK ON ERROR
        # ====================================================================

        print(f"[Migration] ERROR: Migration failed for {layer_id}: {e}")

        # Rollback to prevent partial migration
        layer.rollBack()

        # Log full error for diagnostics
        import traceback
        traceback.print_exc()

        return False

    finally:
        # ====================================================================
        # STEP 8: ENSURE CLEAN STATE
        # ====================================================================

        # Safety net: Ensure layer NEVER left in edit mode
        # This is CRITICAL for life-safety system stability
        if layer and layer.isValid() and layer.isEditable():
            try:
                layer.rollBack()
            except RuntimeError:
                pass  # Layer already rolled back


def run_migration(layer_manager) -> dict:
    """
    Run migration on all layers that need display_order.

    Args:
        layer_manager: LayerManager instance with get_layer() method

    Returns:
        Dict with migration results:
        {
            'migrated': [layer_ids],  # Successfully migrated
            'skipped': [layer_ids],   # Already had field or not found
            'failed': [layer_ids]     # Migration failed
        }
    """
    # ========================================================================
    # VALIDATE INPUT
    # ========================================================================

    if not layer_manager:
        raise ValueError("layer_manager is required")

    if not hasattr(layer_manager, 'get_layer'):
        raise ValueError("layer_manager must have get_layer() method")

    # ========================================================================
    # INITIALIZE RESULTS
    # ========================================================================

    results = {
        'migrated': [],
        'skipped': [],
        'failed': []
    }

    print("[Migration] Starting display_order migration...")
    print(f"[Migration] Layers to migrate: {len(LAYERS_TO_MIGRATE)}")

    # ========================================================================
    # MIGRATE EACH LAYER
    # ========================================================================

    for layer_id in LAYERS_TO_MIGRATE:
        # Get layer from manager
        try:
            layer = layer_manager.get_layer(layer_id)
        except Exception as e:
            print(f"[Migration] WARNING: Failed to get layer {layer_id}: {e}")
            results['skipped'].append(layer_id)
            continue

        # Check if layer exists
        if not layer or not layer.isValid():
            print(f"[Migration] WARNING: Layer {layer_id} not found or invalid, skipping")
            results['skipped'].append(layer_id)
            continue

        # Run migration for this layer
        success = migrate_layer(layer, layer_id)

        if success:
            results['migrated'].append(layer_id)
        elif layer.fields().indexFromName('display_order') != -1:
            # Already had the field
            results['skipped'].append(layer_id)
        else:
            # Migration failed
            results['failed'].append(layer_id)

    # ========================================================================
    # REPORT RESULTS
    # ========================================================================

    print("\n[Migration] ===== Migration Complete =====")
    print(f"[Migration] Migrated: {len(results['migrated'])} layers")
    if results['migrated']:
        print(f"[Migration]   - {', '.join(results['migrated'])}")

    print(f"[Migration] Skipped: {len(results['skipped'])} layers")
    if results['skipped']:
        print(f"[Migration]   - {', '.join(results['skipped'])}")

    print(f"[Migration] Failed: {len(results['failed'])} layers")
    if results['failed']:
        print(f"[Migration]   - {', '.join(results['failed'])}")
        print("[Migration] WARNING: Some migrations failed. Check logs above for details.")

    return results


# Example usage from QGIS Python console:
"""
from qgis.utils import plugins
from layers.migrations.add_display_order import run_migration

sar = plugins['sartracker']
results = run_migration(sar.layers_controller.layer_manager)
print(results)
"""
