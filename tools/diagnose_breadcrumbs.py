#!/usr/bin/env python3
"""
Breadcrumb Diagnostic Script for SAR Tracker
Run from QGIS Python Console with:
    exec(open('/Users/donalocallaghan/Documents/Qgis/sartracker/tools/diagnose_breadcrumbs.py').read())

This patches the tracking manager to trace breadcrumb updates.
Run BEFORE loading CSV, then load CSV to see the trace.
"""

print("\n" + "="*60)
print("BREADCRUMB DIAGNOSTIC - INSTALLING TRACE")
print("="*60 + "\n")

from qgis.utils import plugins

sar = plugins.get('sartracker')
if not sar:
    print("ERROR: SAR Tracker plugin not loaded!")
else:
    # Get the tracking manager
    tm = None
    if hasattr(sar, 'layers_controller') and sar.layers_controller:
        tm = getattr(sar.layers_controller, 'tracking', None)

    if not tm:
        print("ERROR: Could not find TrackingLayerManager!")
    else:
        # Store original method
        original_update_breadcrumbs = tm.update_breadcrumbs
        original_update_per_device = tm._update_breadcrumbs_per_device

        def traced_update_breadcrumbs(positions, time_gap_minutes=5, processed_segments=None):
            print("\n" + "-"*50)
            print("[TRACE] update_breadcrumbs called!")
            print(f"  positions count: {len(positions) if positions else 0}")
            print(f"  time_gap_minutes: {time_gap_minutes}")
            print(f"  processed_segments: {type(processed_segments)}")
            if processed_segments and isinstance(processed_segments, dict):
                segs = processed_segments.get('segments', [])
                print(f"    -> segments count: {len(segs)}")
                if segs:
                    print(f"    -> first segment device: {segs[0].get('device_id')}")
            print("-"*50)
            try:
                result = original_update_breadcrumbs(positions, time_gap_minutes, processed_segments)
                print("[TRACE] update_breadcrumbs completed successfully")
                return result
            except Exception as e:
                print(f"[TRACE] update_breadcrumbs FAILED: {e}")
                import traceback
                traceback.print_exc()
                raise

        def traced_update_per_device(positions, gap_minutes, processed_segments=None):
            print("\n" + "-"*50)
            print("[TRACE] _update_breadcrumbs_per_device called!")
            print(f"  positions count: {len(positions) if positions else 0}")
            print(f"  gap_minutes: {gap_minutes}")
            print(f"  processed_segments: {type(processed_segments)}")
            if processed_segments and isinstance(processed_segments, dict):
                segs = processed_segments.get('segments', [])
                print(f"    -> segments count: {len(segs)}")
                # Count by device
                from collections import Counter
                devices = Counter(s.get('device_id') for s in segs if s.get('device_id'))
                print(f"    -> devices: {dict(devices)}")
            print("-"*50)
            try:
                result = original_update_per_device(positions, gap_minutes, processed_segments)
                print("[TRACE] _update_breadcrumbs_per_device completed successfully")
                return result
            except Exception as e:
                print(f"[TRACE] _update_breadcrumbs_per_device FAILED: {e}")
                import traceback
                traceback.print_exc()
                raise

        # Install traced versions
        tm.update_breadcrumbs = traced_update_breadcrumbs
        tm._update_breadcrumbs_per_device = traced_update_per_device

        print("SUCCESS: Breadcrumb tracing installed!")
        print("Now load your CSV and watch the console for [TRACE] messages.")
        print("\nTo remove tracing, reload the plugin or run:")
        print("  tm.update_breadcrumbs = original_update_breadcrumbs")
        print("  tm._update_breadcrumbs_per_device = original_update_per_device")
