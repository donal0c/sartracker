# -*- coding: utf-8 -*-
"""
Migration: Add display_order field to layers

Adds display_order INTEGER field to layers that support manual ordering.
Backfills display_order = feature.id() for deterministic initial order.

Phase 2 - Layer Operations API (CalTopo Console Support)
LIFE-SAFETY CRITICAL: Handle all errors gracefully, never corrupt existing data.

Qt5/Qt6 Compatible: Uses QGIS API only.
"""

import logging
from qgis.core import QgsField, QgsVectorLayer, QgsFeatureRequest
from qgis.PyQt.QtCore import QVariant
from typing import List
from ..schema import LayerIds, migration_tracker

logger = logging.getLogger(__name__)


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
        logger.error("BUG-053: Layer %s is invalid or not available", layer_id)
        return False

    # ========================================================================
    # STEP 2: CHECK IF ALREADY MIGRATED
    # ========================================================================

    # Check if field already exists
    if layer.fields().indexFromName('display_order') != -1:
        logger.debug("Layer %s already has display_order field", layer_id)
        return False

    logger.info("Adding display_order field to %s...", layer_id)

    # BUG-053 FIX: Track migration status for recovery from partial migrations
    migration_id = f"display_order_{layer_id}"
    migration_tracker.start_migration(
        migration_id=migration_id,
        from_version=2,
        to_version=3,
        affected_layers=[layer_id]
    )

    # ========================================================================
    # STEP 3: START TRANSACTION
    # ========================================================================

    # Check if layer is already being edited (safety check)
    if layer.isEditable():
        logger.warning("BUG-053: Layer %s is already in edit mode, skipping migration", layer_id)
        return False

    # Start editing
    if not layer.startEditing():
        logger.error("BUG-053: Failed to start editing %s", layer_id)
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

        logger.info("Added display_order field to %s at index %d", layer_id, field_index)

        # ====================================================================
        # STEP 5: BACKFILL VALUES
        # ====================================================================

        # Backfill: display_order = feature.id()
        # This ensures deterministic order based on creation order
        updated_count = 0
        features = list(layer.getFeatures(QgsFeatureRequest()))

        # BUG-068 FIX: Warn about large layer migrations
        feature_count = len(features)
        if feature_count > 10000:
            logger.warning(
                "BUG-068: Large layer migration for %s with %d features - this may take time",
                layer_id, feature_count
            )
        # BUG-068 FIX: Safety limit for very large layers
        MAX_MIGRATION_FEATURES = 500000
        if feature_count > MAX_MIGRATION_FEATURES:
            logger.error(
                "BUG-068: Layer %s has %d features, exceeds safe migration limit of %d",
                layer_id, feature_count, MAX_MIGRATION_FEATURES
            )
            raise RuntimeError(
                f"Layer too large for migration: {feature_count} features exceeds limit of {MAX_MIGRATION_FEATURES}"
            )

        logger.info("Backfilling %d features...", feature_count)

        for feature in features:
            feature_id = feature.id()

            # Set display_order to feature ID for initial deterministic order
            success = layer.changeAttributeValue(feature_id, field_index, feature_id)

            if not success:
                raise RuntimeError(f"Failed to update display_order for feature {feature_id}")

            updated_count += 1

            # Progress indicator for large layers
            if updated_count % 100 == 0:
                logger.debug("Backfilled %d/%d features...", updated_count, len(features))

        # ====================================================================
        # STEP 6: COMMIT CHANGES
        # ====================================================================

        if not layer.commitChanges():
            # Get commit errors for better error message
            errors = layer.commitErrors()
            raise RuntimeError(f"Commit failed: {', '.join(errors)}")

        # BUG-053 FIX: Mark migration as completed
        migration_tracker.complete_migration(migration_id, rollback_available=False)

        logger.info("Migration complete: Added display_order to %s, backfilled %d features", layer_id, updated_count)
        return True

    except Exception as e:
        # ====================================================================
        # STEP 7: ROLLBACK ON ERROR
        # ====================================================================

        logger.error("BUG-053: Migration failed for %s: %s", layer_id, e, exc_info=True)

        # Rollback to prevent partial migration
        layer.rollBack()

        # BUG-053 FIX: Mark migration as failed with error details
        migration_tracker.fail_migration(migration_id, str(e))

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

    logger.info("Starting display_order migration...")
    logger.info("Layers to migrate: %d", len(LAYERS_TO_MIGRATE))

    # ========================================================================
    # MIGRATE EACH LAYER
    # ========================================================================

    for layer_id in LAYERS_TO_MIGRATE:
        # Get layer from manager
        try:
            layer = layer_manager.get_layer(layer_id)
        except Exception as e:
            logger.warning("Failed to get layer %s: %s", layer_id, e)
            results['skipped'].append(layer_id)
            continue

        # Check if layer exists
        if not layer or not layer.isValid():
            logger.warning("Layer %s not found or invalid, skipping", layer_id)
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

    logger.info("===== Migration Complete =====")
    logger.info("Migrated: %d layers", len(results['migrated']))
    if results['migrated']:
        logger.info("  Migrated: %s", ', '.join(results['migrated']))

    logger.info("Skipped: %d layers", len(results['skipped']))
    if results['skipped']:
        logger.debug("  Skipped: %s", ', '.join(results['skipped']))

    if results['failed']:
        logger.warning("Failed: %d layers - %s", len(results['failed']), ', '.join(results['failed']))
    else:
        logger.info("Failed: 0 layers")

    return results


# Example usage from QGIS Python console:
"""
from qgis.utils import plugins
from layers.migrations.add_display_order import run_migration

sar = plugins['sartracker']
results = run_migration(sar.layers_controller.layer_manager)
print(results)
"""
