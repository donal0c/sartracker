# SAR Tracker Demo Hardening Checklist

Use this checklist before coordinator demos or training sessions.

## 1. Environment Check (2 minutes)

- Confirm QGIS launches and SAR Tracker loads without import errors.
- Open `Plugins > SAR Tracker > Diagnostics`.
- Verify:
  - Dependency bundle is active.
  - Charset guard is active.
  - SSL/TLS check is green.
  - Provider list includes Traccar HTTP.

## 2. Mission Flow Smoke Test (5-8 minutes)

- Start a new mission.
- Pause and resume mission once.
- Confirm elapsed and active timers are updating correctly.
- Trigger manual refresh and confirm current positions update.
- Import one GPX file and verify track appears.

## 3. Auto-Save / Persistence Check (2-3 minutes)

- Wait for one auto-save cycle or click `Save Project Now`.
- If warning appears:
  - `Persistence: X layer(s) still in memory ...`
  - record the layer names shown in the warning and share with dev team.
- Confirm mission files are being written in mission directory:
  - `.gpkg`
  - `.gpkg-wal`
  - `.gpkg-shm`

## 4. Marker and Logs Verification (3-4 minutes)

- Add one clue marker and one casualty marker.
- Open `Mission Logs > Marker Log`.
- Confirm details pane shows:
  - common fields (name, type, description, coordinates)
  - casualty fields (condition, treatment, evacuation priority, found by)
  - clue fields (clue type, confidence)

## 5. Operator Notes for Known Messages

- `Mission Store Required ...`:
  - means a persistent mission store is not yet configured for per-device trail writes.
  - current positions may still update.
- `Auto Save ... Failed`:
  - check whether the project write failed or whether it is a persistence warning.
  - capture exact warning text for troubleshooting.

## 6. Demo Runbook (recommended order)

1. Start mission.
2. Show live refresh.
3. Add clue and casualty markers.
4. Show Mission Logs details.
5. Import GPX.
6. Show measurement tool output.
7. Pause/resume mission.
8. Show auto-save status.

## 7. If Something Fails

- Capture screenshot of SAR panel and warning banner.
- Export Diagnostics report text.
- Note exact time and action that triggered the issue.
- Continue with fallback workflow (manual refresh + marker logging) if live tracking is degraded.
