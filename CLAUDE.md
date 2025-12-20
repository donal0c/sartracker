# SAR Tracker – CLAUDE.md (Life‑Safety Critical)

> **Note for AI assistants (especially Claude Code):**
> This file defines high‑priority guardrails, workflows, and patterns for working on the SAR Tracker QGIS plugin.
> For general AI instructions and non‑Claude tools, see **AGENTS.md** first, then return here.

---

## 🚨 CRITICAL GUARDRAILS

**Classification:** LIFE‑SAFETY CRITICAL SYSTEM
**Domain:** Mountain Search and Rescue Operations
**Impact:** Failures can result in loss of life during active rescue operations.

Before making **any** change:

1. **Lives > Features** – Never trade safety or reliability for speed, scope, or aesthetics.
2. **Respect existing safety patterns** – Do **not** bypass:

   * `utils.qt_compat` (Qt5/Qt6 compatibility)
   * `utils.dialog_utils.BaseDialog`
   * `utils.task_manager.TaskManager`
3. **Validate everything** – Treat all user input (especially coordinates, file paths, device IDs) as untrusted.
4. **Non‑blocking UI** – Long‑running operations must run in background tasks; the map UI must remain responsive.
5. **Multi‑version compatibility** – All changes must work on **Qt5 and Qt6** (QGIS 3.28 – 3.44+).
6. **No silent failures** – Errors must be handled gracefully and surfaced to the user with actionable messages.
7. **Human review for high‑impact changes** – Any change affecting:

   * Position/coordinate handling
   * Mission timing or status
   * Background task lifecycle
   * Storage of mission or tracking data

   **All such changes require explicit human review before merge.**

If you are unsure about implications of a change: **stop, narrow the scope, and request review.**

8. **GIT COMMIT DISCIPLINE (CRITICAL)** – When committing changes:

   * **ONLY commit files directly related to the current task**
   * **NEVER use `git add -A` or `git commit -a`**
   * **ALWAYS explicitly list files to commit**
   * **ALWAYS ask the user before committing** if there's any uncertainty about what should be included
   * Untracked files (docs/, FUTURE_WORK/, temp files) should NOT be committed unless explicitly requested
   * Check `git status` before committing to verify only relevant files are staged

   **Example - CORRECT:**
   ```bash
   git add sartracker.py controllers/drawing_manager.py
   git commit -m "Fix: specific bug description"
   ```

   **Example - WRONG:**
   ```bash
   git add -A && git commit -m "Fix bug"  # ❌ Commits everything including unrelated files
   ```

---

## PROJECT CONTEXT

**Type:** QGIS Plugin (Python)
**Team:** Kerry Mountain Rescue Team, Ireland
**Version:** 0.3.1
**QGIS:** 3.28+ (Qt5 and Qt6)
**Python:** 3.8+

### Core Purpose

SAR Tracker is a real‑time tracking and tactical mapping console for mountain search and rescue operations. It is used by rescue coordinators to:

* Track personnel positions in near real‑time
* Manage missions and time tracking
* Place tactical markers (IPP/LKP, clues, hazards)
* Draw search areas, bearing lines, range rings
* Coordinate multi‑team operations
* Operate reliably in **offline / poor connectivity** conditions

Use this mental model whenever changing code:

> **This plugin is part of the safety equipment rescuers rely on in bad weather, poor visibility, and limited bandwidth.**

---

## ARCHITECTURE MAP (HIGH‑LEVEL)

```text
sartracker/
├── utils/                    # CRITICAL: Compatibility & safety layer
│   ├── qt_compat.py          # Qt5/Qt6 enum compatibility (MANDATORY)
│   ├── dialog_utils.py       # SafeQDialog base class (fixes blank dialogs)
│   ├── task_manager.py       # Background task lifecycle & safety guards
│   ├── secure_store.py       # Credential security (system keychain)
│   └── notify.py             # User notifications
│
├── controllers/
│   ├── layers_controller.py       # Layer orchestration
│   └── layer_managers/            # Specialized managers
│       ├── tracking_manager.py    # Device tracking
│       ├── marker_manager.py      # Static markers
│       └── drawing_manager.py     # Search areas, lines
│
├── providers/
│   ├── traccar_http.py      # HTTP Traccar provider
│   ├── csv.py               # CSV provider
│   └── tasks.py             # Background processing tasks
│
├── ui/
│   ├── sar_panel.py         # Main control panel
│   ├── marker_dialog.py     # Marker input (CRITICAL)
│   └── diagnostics_panel.py # System diagnostics
│
├── maptools/                # Drawing tools
│   ├── marker_tool.py
│   ├── bearing_tool.py
│   ├── range_ring_tool.py
│   └── polygon_tool.py
│
└── sartracker.py            # Main plugin class (lifecycle)
```

### Critical Dependencies

* **Bundled:** `requests`, `urllib3`, `charset_normalizer` (in `vendor/site-packages`)
* **QGIS Core:** `QgsTask`, `QgsVectorLayer`, `QgsCoordinateTransform`, `QgsProject`
* **Storage:** GeoPackage layers; system keychain for credentials

When editing code, prefer **extending existing controllers/managers/tools** over adding new ad‑hoc scripts or one‑off modules.

---

## STANDARD WORKFLOWS

These workflows are **mandatory** for Claude when making non‑trivial changes.

### 1. Bug Fix Workflow (CRITICAL)

1. **Understand the bug**

   * Read the issue description and any references to `docs/incident_log.md` or `issues_to_address.md`.
   * Locate the relevant modules in `controllers/`, `providers/`, `maptools/`, or `ui/`.
2. **Reproduce safely**

   * Reproduce the bug in a controlled environment if possible (non‑live, test data).
   * Note QGIS version and Qt version if relevant.
3. **Propose a minimal fix**

   * Outline a short plan in bullets: *what to change, why it is safe, and which tests to run*.
   * Highlight any impact on coordinates, mission state, or background tasks.
4. **Implement incrementally**

   * Make small, localized changes following the patterns in `docs/AI_CODE_REFERENCE.md`.
   * Keep safety and compatibility checks in place.
5. **Test**

   * Run the relevant automated checks (see **Testing & Commands** below).
   * Manually confirm no regressions in basic workflows.
6. **Summarize**

   * Provide a concise description of:

     * Root cause
     * Fix implemented
     * Tests run and results

Do **not** perform large refactors as part of a bug fix.

### 2. New Feature / Enhancement Workflow

1. **Clarify requirements**

   * Confirm feature scope, especially around safety, offline use, and performance.
   * Identify which layers, providers, and UI panels are involved.
2. **Consult design docs**

   * Read the relevant sections of `docs/architecture.md` and `docs/AI_CODE_REFERENCE.md`.
3. **Plan first**

   * Draft a short plan: data flow, UI changes, failure modes, tests.
   * Explicitly call out how you will preserve safety and compatibility.
4. **Implement in small steps**

   * Start with data and background tasks.
   * Then wire UI and interaction patterns.
   * Use existing patterns for dialogs, tasks, and validation; do not invent new ones casually.
5. **Test thoroughly**

   * Run automated checks.
   * Exercise the feature under:

     * Poor/no connectivity
     * Plugin reloads
     * Invalid inputs

### 3. Refactor / Cleanup Workflow

1. **Only refactor when necessary** and when there is time to test properly.
2. **Maintain behaviour** – refactors must not change:

   * Coordinate conversions
   * Validation rules
   * Background task lifecycle
3. **Work in small steps**

   * Refactor one module or concern at a time.
   * Run tests between each logical step.
4. **Document why**

   * Add small comments where a refactor clarifies safety or lifecycle logic.

For all workflows: **ask for human review** for changes that might affect field safety.

---

## MANDATORY PATTERNS (SUMMARY)

Details and full examples for all patterns live in **`docs/AI_CODE_REFERENCE.md`**.
Use that document for in‑depth examples. This section is a **high‑level checklist**.

### Qt Imports

* **Never** import `PyQt5` or `PyQt6` directly.
* Always import from `qgis.PyQt`:

  * `from qgis.PyQt.QtCore import Qt, QTimer`
  * `from qgis.PyQt.QtWidgets import QDialog, QPushButton`
* If you find a direct PyQt5/PyQt6 import: treat it as a bug and fix it.

### Qt Enums & Dialog Execution

* Do **not** use raw enums like `Qt.LeftButton` or `Qt.Checked`.
* Always import enums and dialog helpers from `utils.qt_compat`, e.g.:

  * `LeftButton`, `RightButton`
  * `Key_Escape`, `Key_Return`
  * `Checked`, `Unchecked`
  * `CrossCursor`, `ArrowCursor`
  * `dialog_exec`, `DialogAccepted`, `DialogRejected`
* For dialogs, always call `dialog_exec(dialog)`; do not use `.exec()` / `.exec_()` directly.

### Dialog Base Class (CRITICAL)

* All dialogs must inherit from `utils.dialog_utils.BaseDialog`.
* Do **not** create new `QDialog` subclasses directly.
* Reason: Qt 5.15.x on Windows can render dialogs blank; `BaseDialog` includes workarounds.

### Background Tasks & Async Safety (LIFE‑SAFETY CRITICAL)

* Use `utils.task_manager.TaskManager` for all long‑running or background operations.
* Do **not** connect `QgsTask` signals directly to plugin methods.
* In async callbacks:

  * Guard against components being `None` or unloaded.
  * Log and exit early if UI or controllers are missing.
* In plugin `unload()`:

  * Ensure `TaskManager.cancel_all()` is called.

### Input Validation (MANDATORY)

* All user input must be validated before use, especially:

  * Marker names and descriptions
  * Coordinates (lat/lon, eastings/northings)
  * File paths and device IDs
* Example coordinate rules:

  * Latitude: numeric, between **‑90** and **90**
  * Longitude: numeric, between **‑180** and **180**
* Invalid input must raise a clear error and surface an actionable message to the user.

### Coordinate Handling (CRITICAL)

* Treat coordinate transform logic as safety‑critical.
* Use the existing shared pattern in the codebase (see `docs/AI_CODE_REFERENCE.md#coordinate-handling`).
* Typical approach:

  * Validate numeric inputs.
  * Use `QgsCoordinateReferenceSystem`, `QgsCoordinateTransform`, and `QgsProject`.
  * Convert from local CRS (e.g. EPSG:2157 ITM) to WGS84 (EPSG:4326) for lat/lon.
* On any transform failure: raise a clear error; do **not** silently continue with bad data.

### Lifecycle & Resource Cleanup

* Timers must be created with a parent (`QTimer(self)` or similar) to avoid leaks.
* Signals must be disconnected (or their owners destroyed) in `unload()`.
* Background tasks and long‑lived objects must not reference destroyed UI components.

---

## COMMON PITFALLS TO AVOID

1. **Qt Enum Incompatibility** – Using raw Qt enums instead of `utils.qt_compat`.
2. **Blocking UI** – Running heavy I/O or computations on the main thread.
3. **Insecure Storage** – Storing credentials in plain text or QSettings.
4. **Missing Error Handling** – Allowing exceptions to bubble up and crash the plugin.
5. **No Defensive Guards** – Assuming controllers/UI still exist in async callbacks.
6. **Timer & Signal Leaks** – Creating timers or signal connections without lifecycles tied to the plugin.
7. **Ad‑hoc Coordinate Logic** – Implementing custom transforms instead of using the shared pattern.

If you see any of the above in existing code, treat it as **technical debt with safety impact** and flag it.

---

## TESTING & COMMANDS

### Pre‑Commit Checklist

Before considering a change "safe":

* [ ] Run compatibility checks:

  * `./tools/check_compatibility.sh`
* [ ] Confirm no direct PyQt5/PyQt6 imports
* [ ] Confirm no direct Qt enum usage
* [ ] Confirm dialogs use `BaseDialog` and `dialog_exec`
* [ ] Confirm notifications go through `utils.notify`

### Critical Test Scenarios

At minimum, for relevant areas:

* [ ] QGIS Qt5 (e.g. 3.28, 3.34) – plugin loads, main flows work
* [ ] QGIS Qt6 (e.g. 3.40, 3.44+) – same behaviour, no regressions
* [ ] Dialogs render correctly (no blank dialogs)
* [ ] User inputs are validated and rejected safely when invalid
* [ ] Error cases show clear messages (no silent crashes)
* [ ] Coordinate transformations are accurate and consistent
* [ ] Plugin reloads (via `reloadPlugin('sartracker')`) do not crash
* [ ] Background tasks cancel cleanly on unload

### Development Commands (Reference)

```bash
# Run compatibility checks
./tools/check_compatibility.sh

# Run preflight checks
python tools/preflight_check.py

# Update vendor dependencies
python tools/vendor_deps.py --refresh
```

From QGIS Python console, typical operations:

```python
from qgis.utils import plugins, reloadPlugin

# Get plugin instance
sar = plugins.get('sartracker')

# Reload plugin
reloadPlugin('sartracker')

# Show diagnostics
sar._show_diagnostics()
```

---

## AI ASSISTANT GUIDELINES

### When Making Changes

When you, as an AI assistant, are asked to edit this codebase:

1. **Read relevant docs first**

   * Always check `docs/AI_CODE_REFERENCE.md` for patterns related to the area you’re changing.
   * For architecture‑level questions, read `docs/architecture.md`.
2. **Study existing code**

   * Find similar implementations and follow their patterns.
3. **Consider edge cases**

   * Offline mode, network failures, invalid input, plugin reloads.
4. **Add or preserve error handling**

   * Do not remove try/except blocks around external operations.
   * Ensure errors are surfaced via `utils.notify`.
5. **Validate all inputs**

   * Especially coordinates, mission identifiers, device IDs, and user‑supplied text.
6. **Check multi‑version behaviour**

   * Code must run correctly on both Qt5 and Qt6.
7. **Update or add tests where appropriate**

   * Keep tests focused and practical; do not generate huge test suites without being asked.
8. **Document safety‑critical decisions briefly**

   * When making a choice that affects safety, add a short comment or note explaining why.

### Priority Order (Non‑Negotiable)

1. **Safety** – Human life and rescuer safety
2. **Compatibility** – Supported QGIS versions and Qt5/Qt6
3. **Security** – Credentials and sensitive data
4. **Performance & UX** – Responsive UI, appropriate polling intervals
5. **New Features** – Only after the above are satisfied

### Code Review Self‑Check

Before finalizing a change, ask yourself:

* Does this work in both Qt5 and Qt6 environments?
* What happens if the network fails or is slow?
* How is invalid input handled at each entry point?
* What happens if the plugin is reloaded during this operation?
* Could this block the UI thread?
* Are credentials and sensitive values stored securely?
* Have I reused existing patterns instead of inventing new ones?

If any answer is unclear or worrying, **stop and request human review.**

### Documentation Scope

* Do **not** create long design documents, multi‑page reports, or speculative summaries unless explicitly asked.
* Short, focused artefacts **are allowed and encouraged** when they improve safety or future understanding, for example:

  * A brief change summary for a PR
  * A short note added to an incident log entry

---

## KEY PRINCIPLES

1. **Safety First** – Lives depend on this code working correctly under stress.
2. **Validate Everything** – Especially coordinates and mission‑critical inputs.
3. **Handle All Errors** – No unhandled exceptions that can crash the plugin.
4. **Test Thoroughly** – Across Qt5/Qt6, online/offline, and key workflows.
5. **Follow Established Patterns** – Use compatibility and safety helpers as designed.
6. **Defensive Programming** – Assume components may be missing or destroyed.
7. **Clean Lifecycle** – Disconnect signals, stop timers, cancel tasks in `unload()`.
8. **Minimal Surprises** – Prefer small, clear changes over clever or complex ones.
9. **Ask Questions** – When in doubt, consult docs and request review.

---

## REMEMBER

This is not just software. It is part of the equipment rescuers rely on during real missions, often in bad weather, at night, and with limited connectivity.

Every feature you add, every bug you fix, and every refactor you perform has the potential to affect people’s safety.

**Take your time. Follow the guidelines. Test thoroughly. Never compromise on quality.**

**Thank you for contributing to saving lives.**

---

## WORK TRACKING WITH BEADS

This project uses **beads** (`bd`) for persistent work tracking across sessions. Beads survives conversation compaction and provides dependency-aware task management.

### When to Use Beads vs TodoWrite

| Use Beads | Use TodoWrite |
|-----------|---------------|
| Multi-session work | Single-session tasks |
| Complex dependencies | Linear step-by-step work |
| Need to resume after days/weeks | Immediate tactical execution |
| Work that blocks other work | Simple checklists |

### Session Start Protocol

At the start of every session:

```bash
bd ready                           # See what's unblocked and workable
bd list --status in_progress       # Check for work already in progress
bd show SAR-xxx                    # Read notes on active issues
```

### Working on Issues

```bash
bd update SAR-xxx --status in_progress   # Claim work
bd update SAR-xxx --notes "COMPLETED: ... IN PROGRESS: ... NEXT: ..."   # Checkpoint progress
bd close SAR-xxx --reason "Implemented X"   # Complete work
```

### Progress Checkpointing

Update beads notes at these critical points:
- Before conversation compaction (>70% token usage)
- After completing significant milestones
- When hitting blockers
- Before switching tasks

**Note format for session handoff:**
```
COMPLETED: Specific deliverables
IN PROGRESS: Current state + next step
BLOCKERS: What's preventing progress
KEY DECISIONS: Important context
```

### Landing the Plane (Session Completion)

When ending a work session, complete ALL steps:

1. **Update beads** - Close finished issues, update notes on in-progress work
2. **File new issues** - Create issues for discovered work or follow-ups
3. **Run quality gates** (if code changed) - `./tools/check_compatibility.sh`
4. **Sync and push**:
   ```bash
   git pull --rebase
   bd sync
   git push
   git status  # MUST show "up to date with origin"
   ```

**Work is NOT complete until `git push` succeeds.**

### Key Commands Reference

| Command | Purpose |
|---------|---------|
| `bd ready` | Show unblocked work |
| `bd blocked` | Show what's stuck and why |
| `bd show SAR-xxx` | Full issue details |
| `bd update SAR-xxx --status X` | Change status |
| `bd close SAR-xxx` | Mark complete |
| `bd create "Title"` | New issue |
| `bd stats` | Project health overview |

---

**Document Version:** 1.2 (added beads integration)

**Last Updated:** 2025‑12‑18

**For Detailed Patterns & Examples:** See `docs/AI_CODE_REFERENCE.md`.
