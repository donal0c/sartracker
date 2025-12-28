#!/usr/bin/env python3
"""
Phase 2 Validation Helper Script for SAR Tracker
================================================

Run this script in QGIS Python Console to validate Phase 2 mission lifecycle flows.

Usage in QGIS Console:
    exec(open('/path/to/sartracker/tools/validate_phase2.py').read())

Or import directly:
    from sartracker.tools.validate_phase2 import Phase2Validator
    validator = Phase2Validator()
    validator.run_all_checks()
"""

from qgis.utils import plugins


class Phase2Validator:
    """Validation helper for Phase 2: MissionLifecycleController integration."""

    def __init__(self):
        self.sar = plugins.get('sartracker')
        self.errors = []
        self.warnings = []
        self.passed = []

    def check(self, name, condition, error_msg=None):
        """Record a check result."""
        if condition:
            self.passed.append(name)
            print(f"  [PASS] {name}")
            return True
        else:
            msg = error_msg or f"{name} failed"
            self.errors.append(msg)
            print(f"  [FAIL] {name}: {msg}")
            return False

    def warn(self, name, condition, warn_msg=None):
        """Record a warning check result."""
        if condition:
            self.passed.append(name)
            print(f"  [PASS] {name}")
            return True
        else:
            msg = warn_msg or f"{name} warning"
            self.warnings.append(msg)
            print(f"  [WARN] {name}: {msg}")
            return False

    # =========================================================================
    # Controller Initialization Checks
    # =========================================================================
    def check_controller_exists(self):
        """Verify MissionLifecycleController was created."""
        print("\n[1] Controller Initialization Checks")
        print("-" * 40)

        self.check(
            "Plugin loaded",
            self.sar is not None,
            "SAR Tracker plugin not found"
        )
        if not self.sar:
            return False

        self.check(
            "MissionLifecycleController created",
            hasattr(self.sar, 'mission_lifecycle_controller') and
            self.sar.mission_lifecycle_controller is not None,
            "Controller not initialized - check console for import errors"
        )

        if self.sar.mission_lifecycle_controller:
            ctrl = self.sar.mission_lifecycle_controller
            self.check(
                "Controller has layer_manager",
                ctrl._layer_manager is not None,
                "layer_manager dependency missing"
            )
            self.check(
                "Controller has task_manager",
                ctrl._task_manager is not None,
                "task_manager dependency missing"
            )
            self.check(
                "Controller has mission_storage_controller",
                ctrl._mission_storage_controller is not None,
                "mission_storage_controller dependency missing"
            )
            return True
        return False

    # =========================================================================
    # Signal Connection Checks
    # =========================================================================
    def check_signal_connections(self):
        """Verify signal connections are in place."""
        print("\n[2] Signal Connection Checks")
        print("-" * 40)

        if not self.sar or not self.sar.mission_lifecycle_controller:
            print("  [SKIP] Controller not available")
            return False

        ctrl = self.sar.mission_lifecycle_controller

        # Check controller signals have receivers
        self.check(
            "structure_ensured signal connected",
            ctrl.structure_ensured.receivers() > 0,
            "No receivers for structure_ensured"
        )
        self.check(
            "storage_prepared signal connected",
            ctrl.storage_prepared.receivers() > 0,
            "No receivers for storage_prepared"
        )
        self.check(
            "storage_loaded signal connected",
            ctrl.storage_loaded.receivers() > 0,
            "No receivers for storage_loaded"
        )
        self.check(
            "session_state_changed signal connected",
            ctrl.session_state_changed.receivers() > 0,
            "No receivers for session_state_changed"
        )
        self.check(
            "finalization_state_changed signal connected",
            ctrl.finalization_state_changed.receivers() > 0,
            "No receivers for finalization_state_changed"
        )

        # Check archive signal connections from storage controller
        if self.sar.mission_storage_controller:
            msc = self.sar.mission_storage_controller
            self.check(
                "archive_succeeded connected to lifecycle controller",
                msc.archive_succeeded.receivers() > 0,
                "CRITICAL: archive_succeeded not connected - _is_finalizing won't reset!"
            )
            self.check(
                "archive_failed connected to lifecycle controller",
                msc.archive_failed.receivers() > 0,
                "CRITICAL: archive_failed not connected - _is_finalizing won't reset!"
            )

        return len(self.errors) == 0

    # =========================================================================
    # Status Snapshot Check
    # =========================================================================
    def check_status_snapshot(self):
        """Verify status_snapshot returns valid data."""
        print("\n[3] Status Snapshot Check")
        print("-" * 40)

        if not self.sar or not self.sar.mission_lifecycle_controller:
            print("  [SKIP] Controller not available")
            return False

        try:
            snapshot = self.sar.mission_lifecycle_controller.status_snapshot()
            self.check(
                "status_snapshot returns dict",
                isinstance(snapshot, dict),
                f"Expected dict, got {type(snapshot)}"
            )

            required_keys = [
                'controller_active', 'is_finalizing', 'is_finalized',
                'mission_name', 'gpkg_path', 'backup_dir'
            ]
            for key in required_keys:
                self.check(
                    f"Snapshot has '{key}' key",
                    key in snapshot,
                    f"Missing key: {key}"
                )

            print(f"\n  Current state: {snapshot}")
            return True

        except Exception as e:
            self.errors.append(f"status_snapshot failed: {e}")
            print(f"  [FAIL] status_snapshot exception: {e}")
            return False

    # =========================================================================
    # Session State Check
    # =========================================================================
    def check_session_state(self):
        """Verify get_session_state returns valid dataclass."""
        print("\n[4] Session State Check")
        print("-" * 40)

        if not self.sar or not self.sar.mission_lifecycle_controller:
            print("  [SKIP] Controller not available")
            return False

        try:
            state = self.sar.mission_lifecycle_controller.get_session_state()
            self.check(
                "get_session_state returns object",
                state is not None,
                "Returned None"
            )

            # Check required attributes
            attrs = [
                'mission_name', 'mission_dir', 'gpkg_path',
                'backup_dir', 'attachments_dir', 'is_active',
                'is_finalized', 'coordinators', 'metadata_collected'
            ]
            for attr in attrs:
                self.check(
                    f"Session state has '{attr}'",
                    hasattr(state, attr),
                    f"Missing attribute: {attr}"
                )

            print(f"\n  Mission name: {state.mission_name}")
            print(f"  Active: {state.is_active}")
            print(f"  Finalized: {state.is_finalized}")
            return True

        except Exception as e:
            self.errors.append(f"get_session_state failed: {e}")
            print(f"  [FAIL] get_session_state exception: {e}")
            return False

    # =========================================================================
    # Diagnostics Integration Check
    # =========================================================================
    def check_diagnostics(self):
        """Verify get_plugin_status includes lifecycle data."""
        print("\n[5] Diagnostics Integration Check")
        print("-" * 40)

        if not self.sar:
            print("  [SKIP] Plugin not available")
            return False

        try:
            status = self.sar.get_plugin_status()
            self.check(
                "get_plugin_status returns dict",
                isinstance(status, dict),
                f"Expected dict, got {type(status)}"
            )

            # Check lifecycle-related keys
            lifecycle_keys = [
                'mission_storage_path', 'mission_backup_path',
                'mission_finalized', 'mission_coordinators'
            ]
            for key in lifecycle_keys:
                self.check(
                    f"Plugin status has '{key}'",
                    key in status,
                    f"Missing lifecycle key: {key}"
                )

            # Check if mission_lifecycle dict is present (when controller active)
            if self.sar.mission_lifecycle_controller:
                self.check(
                    "Plugin status has 'mission_lifecycle' dict",
                    'mission_lifecycle' in status,
                    "Lifecycle controller active but no lifecycle status"
                )

            return True

        except Exception as e:
            self.errors.append(f"get_plugin_status failed: {e}")
            print(f"  [FAIL] get_plugin_status exception: {e}")
            return False

    # =========================================================================
    # Run All Checks
    # =========================================================================
    def run_all_checks(self):
        """Run all validation checks and print summary."""
        print("=" * 60)
        print("Phase 2 Validation: MissionLifecycleController Integration")
        print("=" * 60)

        self.check_controller_exists()
        self.check_signal_connections()
        self.check_status_snapshot()
        self.check_session_state()
        self.check_diagnostics()

        # Summary
        print("\n" + "=" * 60)
        print("VALIDATION SUMMARY")
        print("=" * 60)
        print(f"  Passed:   {len(self.passed)}")
        print(f"  Warnings: {len(self.warnings)}")
        print(f"  Errors:   {len(self.errors)}")

        if self.errors:
            print("\nERRORS:")
            for err in self.errors:
                print(f"  - {err}")

        if self.warnings:
            print("\nWARNINGS:")
            for warn in self.warnings:
                print(f"  - {warn}")

        if not self.errors:
            print("\n[SUCCESS] Phase 2 validation passed!")
            print("\nNext: Run manual workflow tests:")
            print("  1. Start new mission")
            print("  2. Pause/resume mission")
            print("  3. Finalize mission")
            print("  4. Verify archive created")
            print("  5. Unlock and modify")
            print("  6. Open/close projects with missions")
            return True
        else:
            print("\n[FAILED] Phase 2 validation found issues!")
            return False


# =========================================================================
# Direct execution in QGIS Console
# =========================================================================
if __name__ == '__main__' or 'sartracker' in str(plugins.keys()):
    validator = Phase2Validator()
    validator.run_all_checks()
