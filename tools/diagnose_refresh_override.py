#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
One-shot helper to print mission start time + provider info, then trigger a refresh
with an optional since_iso override (useful to bypass mission-start filtering).

Run from QGIS Python Console:
    exec(open('/Users/donalocallaghan/Documents/Qgis/sartracker/tools/diagnose_refresh_override.py').read())
"""

from qgis.utils import plugins

# Set to None to use normal mission-start filtering.
SINCE_OVERRIDE = "1970-01-01T00:00:00Z"

print("\n" + "=" * 60)
print("SAR TRACKER REFRESH OVERRIDE")
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

        mission_start = None
        get_mission_start = getattr(sar, "_get_mission_start_iso", None)
        if callable(get_mission_start):
            try:
                mission_start = get_mission_start()
            except Exception as exc:
                print(f"Warning: failed to read mission start time: {exc}")

        print(f"Mission start ISO: {mission_start}")
        print(f"since_iso override: {SINCE_OVERRIDE}")

        try:
            started = provider_controller.start_refresh(since_iso=SINCE_OVERRIDE)
            print(f"Refresh started: {started}")
            print("Watch the QGIS Python console for:")
            print("  [PROVIDER_CONTROLLER] Refresh payload -> current:X breadcrumbs:Y devices:Z")
        except Exception as exc:
            print(f"ERROR: start_refresh failed: {exc}")
