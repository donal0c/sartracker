# Manual QGIS Logging Runbook

This runbook is for exploratory sessions where Donal or the rescue team uses
SAR Tracker manually inside QGIS while Codex reviews logs, tracebacks, and
diagnostics afterwards.

The goal is not "click around and hope."
The goal is to capture enough evidence that we can turn surprises into tests.

## Preferred Setup

### 1. Launch QGIS from a terminal

Launching from a shell makes Python tracebacks, plugin prints, and some QGIS
warnings visible immediately.

Typical pattern on macOS:

```bash
/Applications/QGIS-LTR.app/Contents/MacOS/QGIS
```

If you want to keep a session log:

```bash
/Applications/QGIS-LTR.app/Contents/MacOS/QGIS 2>&1 | tee /tmp/sartracker-qgis-session.log
```

### 2. Open the QGIS Log Messages panel

In QGIS:

- `View`
- `Panels`
- `Log Messages`

Then watch the `SAR Tracker` category during the workflow.

### 3. Enable SAR Tracker debug logging when needed

Use:

- `SAR Tracker`
- `Diagnostics`
- `Debug Logging`

This should only be enabled while investigating a workflow, because it makes
the logs much noisier.

## Best Workflows To Exercise

These are the highest-value exploratory flows right now:

- start QGIS and explicitly activate SAR Tracker
- choose `Resume` vs `Start Fresh`
- confirm the expected startup layer tree appears without `Repair`
- save manually
- wait for or trigger auto-save
- finalize and unlock a mission
- close QGIS and relaunch
- switch between a normal non-SAR project and a SAR mission project

## What To Record During A Session

For each issue, try to capture:

- what you clicked, in order
- what you expected to happen
- what actually happened
- whether the issue was visual only, data-related, or state-related
- any message-bar warnings or dialogs
- the relevant `SAR Tracker` log lines
- any terminal traceback or crash output

Short, exact notes are much more useful than a long impressionistic summary.

## What To Send Back To Codex

The most useful evidence is:

- the last 100 to 200 terminal log lines before the problem
- any traceback or `Fatal Python error`
- the relevant `SAR Tracker` log lines from the QGIS Log Messages panel
- screenshots of the panel/layer state if the issue is visual
- the exact workflow you followed

## How Codex Should Use The Evidence

1. classify the problem:
   - startup/lifecycle
   - persistence/autosave
   - provider/tracking
   - layer tree / rendering
   - shutdown/crash
2. connect the observation to the current code path
3. reproduce it in a failing unit, integration, or real-QGIS test when possible
4. only then make the production change

## Notes

- Team feedback about "this feels wrong" is valuable even before there is a clean traceback.
- Manual exploratory testing should feed the automated test suite, not replace it.
- If a session crashes QGIS or Python, save the crash output immediately before rerunning anything.
