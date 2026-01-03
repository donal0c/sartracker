#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CSV time window diagnostic for SAR Tracker.

Prints:
- Provider name
- Mission start time (if active)
- CSV breadcrumb count (unfiltered)
- CSV breadcrumb count after mission-start filter
- CSV timestamp min/max

Run from QGIS Python Console:
    exec(open('/Users/donalocallaghan/Documents/Qgis/sartracker/tools/diagnose_csv_window.py').read())
"""

from datetime import datetime
from qgis.utils import plugins

print("\n" + "=" * 60)
print("SAR TRACKER CSV WINDOW DIAGNOSTIC")
print("=" * 60)

sar = plugins.get("sartracker")
if not sar:
    print("ERROR: SAR Tracker plugin not loaded.")
else:
    provider_controller = getattr(sar, "provider_controller", None)
    if not provider_controller:
        print("ERROR: provider_controller not available.")
    else:
        provider_name = getattr(provider_controller, "provider_name", None)
        print(f"Provider: {provider_name or 'unknown'}")

        provider = getattr(provider_controller, "provider", None)
        if not provider:
            print("ERROR: provider instance not available.")
        else:
            if provider_name != "csv":
                print("WARNING: Active provider is not CSV. Results may not be meaningful.")

            get_mission_start = getattr(sar, "_get_mission_start_iso", None)
            mission_start = None
            if callable(get_mission_start):
                try:
                    mission_start = get_mission_start()
                except Exception as exc:
                    print(f"Warning: failed to read mission start time: {exc}")

            print(f"Mission start ISO: {mission_start}")

            safe_parse = getattr(provider, "_safe_parse_timestamp", None)
            if not callable(safe_parse):
                def safe_parse(value):
                    try:
                        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
                    except Exception:
                        return datetime.min

            try:
                all_points = provider.get_breadcrumbs(since_iso=None)
                print(f"CSV breadcrumbs (unfiltered): {len(all_points)}")
            except Exception as exc:
                print(f"ERROR: provider.get_breadcrumbs(None) failed: {exc}")
                all_points = []

            min_ts = None
            max_ts = None
            for point in all_points:
                ts = safe_parse(point.get("ts"))
                if ts == datetime.min:
                    continue
                min_ts = ts if min_ts is None or ts < min_ts else min_ts
                max_ts = ts if max_ts is None or ts > max_ts else max_ts

            if min_ts and max_ts:
                print(f"CSV time range: {min_ts.isoformat()} -> {max_ts.isoformat()}")
            else:
                print("CSV time range: unavailable (no valid timestamps)")

            filtered_points = []
            if mission_start:
                try:
                    filtered_points = provider.get_breadcrumbs(since_iso=mission_start)
                    print(f"CSV breadcrumbs (filtered to mission start): {len(filtered_points)}")
                except Exception as exc:
                    print(f"ERROR: provider.get_breadcrumbs(mission_start) failed: {exc}")
            else:
                print("CSV breadcrumbs (filtered): skipped (no mission start time)")

            if mission_start and max_ts:
                if safe_parse(mission_start) > max_ts:
                    print("DIAGNOSIS: Mission start is AFTER CSV data; breadcrumbs will be filtered to zero.")
                else:
                    print("DIAGNOSIS: Mission start is within CSV range; filtering should still allow breadcrumbs.")
