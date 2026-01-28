# SAR Tracker - AI Assistant Documentation

> **For Claude Users**: Please use [CLAUDE.md](./CLAUDE.md) which contains comprehensive Claude-specific patterns and mandatory guidelines.

## Critical Safety Context

**Classification:** LIFE-SAFETY CRITICAL SYSTEM
**Domain:** Mountain Search and Rescue Operations
**Impact:** Failures can result in loss of life during active rescue operations

This software is used by rescue coordinators during active search and rescue operations where lives are at stake. Code quality, reliability, and thorough testing are non-negotiable requirements.

## Project Overview

**Type:** QGIS Plugin (Python)
**Version:** 0.3.1
**Team:** Kerry Mountain Rescue Team, Ireland
**QGIS Compatibility:** 3.28+ (Qt5 and Qt6)
**Python:** 3.8+

### Core Purpose
Real-time tracking and tactical mapping console for Search and Rescue operations. Enables rescue coordinators to:
- Track rescue personnel positions in real-time
- Manage missions with precise time tracking
- Place tactical markers (IPP/LKP, clues, hazards)
- Draw search areas, bearing lines, range rings
- Coordinate multi-team operations
- Work reliably in offline/poor connectivity scenarios

## Documentation Structure

This project maintains multiple documentation files for different audiences:

- **AGENTS.md** (this file): General instructions for AI coding assistants
- **CLAUDE.md**: Comprehensive Claude-specific patterns and guidelines
- **docs/AI_CODE_REFERENCE.md**: Detailed implementation patterns (1300+ lines)
- **docs/architecture.md**: System architecture and hardening features
- **README.md**: User documentation and setup instructions

## Issue Tracking (beads / bd)

This project uses **bd** (beads) for issue tracking and planning. Prefer filing work as beads and keeping them updated during a session.

Quick commands:
```bash
bd ready              # Find available work
bd show <id>          # View issue details
bd update <id> --status in_progress  # Claim work
bd close <id>         # Complete work
bd sync               # Sync issues with git
```

Tip: Run `bd onboard` for the latest workflow snippet. Keep bead notes up to date at major milestones.

## Quick Architecture Reference

```
sartracker/
├── utils/                    # Core utilities and compatibility layer
│   ├── qt_compat.py         # CRITICAL: Qt5/Qt6 compatibility
│   ├── dialog_utils.py      # Dialog base classes
│   ├── task_manager.py      # Background task management
│   └── secure_store.py      # Credential security
├── controllers/             # Application logic
│   └── layer_managers/      # Specialized layer management
├── providers/               # Data providers (Traccar, CSV)
├── ui/                      # User interface components
├── maptools/                # QGIS map interaction tools
└── sartracker.py           # Main plugin entry point
```

## Critical Development Guidelines

> **TDD IS THE STANDARD**: This project uses Test-Driven Development for all production code.
> All changes MUST follow: **Write failing test → Implement → Refactor**. No exceptions.

### 0. Test-Driven Development (MANDATORY)

**All production code changes require TDD.** The test suite includes:
- **Unit tests**: Fast, no QGIS required
- **Integration tests**: Require real QGIS (`@pytest.mark.qgis_required`)
- **E2E tests**: End-to-end scenarios in `test_e2e_scenarios.py`
- **Performance tests**: Load and resilience in `test_performance_resilience.py`

```python
# 1. RED: Write a failing test first
def test_validate_latitude_rejects_nan():
    with pytest.raises(ValueError):
        validate_latitude(float('nan'))

# 2. GREEN: Write minimal code to pass
# 3. REFACTOR: Clean up while tests stay green
```

**Bug fixes**: Write test that reproduces the bug BEFORE fixing it.
**New features**: Write acceptance tests BEFORE implementing.
**Safety-critical code**: Extra scrutiny on coordinates, mission state, data persistence.

### 1. Qt Compatibility (MANDATORY)
This plugin MUST work with both Qt5 (QGIS 3.28-3.38) and Qt6 (QGIS 3.40+).

**Always use:**
```python
from qgis.PyQt.QtCore import Qt, QTimer  # ✓ Correct
```

**Never use:**
```python
from PyQt5.QtCore import Qt  # ✗ Breaks in Qt6
from PyQt6.QtCore import Qt  # ✗ Breaks in Qt5
```

### 2. Input Validation (LIFE-CRITICAL)
All user inputs, especially coordinates, MUST be validated:

```python
def validate_coordinates(lat, lon):
    if not isinstance(lat, (int, float)) or not (-90 <= lat <= 90):
        raise ValueError(f"Invalid latitude: {lat}")
    if not isinstance(lon, (int, float)) or not (-180 <= lon <= 180):
        raise ValueError(f"Invalid longitude: {lon}")
```

### 3. Error Handling
Every operation that could fail MUST have error handling:

```python
try:
    result = risky_operation()
except Exception as e:
    # Log error
    print(f"[ERROR] Operation failed: {e}")
    # Notify user
    from utils.notify import error
    error(self.iface.messageBar(), "Operation Failed", str(e))
    # Handle gracefully
    return safe_default
```

### 4. Background Operations
UI-blocking operations (>100ms) MUST use background tasks:

```python
from utils.task_manager import TaskManager

task = self.provider.create_refresh_task()
self.task_manager.start_task(
    task=task,
    on_complete=self._on_complete,
    on_error=self._on_error
)
```

## Key Patterns and Anti-Patterns

### DO:
- ✓ Validate all inputs
- ✓ Use try/except for external operations
- ✓ Test with both Qt5 and Qt6
- ✓ Use background tasks for long operations
- ✓ Store credentials securely (keychain)
- ✓ Check component existence in async callbacks
- ✓ Follow existing code patterns

### DON'T:
- ✗ Import PyQt5/PyQt6 directly
- ✗ Block the UI thread
- ✗ Store credentials in plain text
- ✗ Skip input validation
- ✗ Assume network connectivity
- ✗ Ignore error cases
- ✗ Make changes without understanding context

## Testing Requirements

Before committing any changes:

1. **TDD Compliance**
   - Did you write failing tests BEFORE implementing? (mandatory)
   - Do all tests pass? `python -m pytest tests/`
   - Is there a regression test for bug fixes?

2. **Compatibility Testing**
   - Test in QGIS 3.28 (Qt5)
   - Test in QGIS 3.40+ (Qt6)

3. **Functional Testing**
   - Test all modified features
   - Test error conditions
   - Test offline mode

4. **Safety Testing**
   - Verify coordinate accuracy
   - Confirm error messages are clear
   - Ensure no data loss on errors

### Test Execution Notes
- Preferred runner (QGIS env configured): `./run_tests.sh`
- For unit tests without QGIS/pytest-qgis autoload:
  `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 SARTRACKER_FORCE_MOCK_QGIS=1 .venv/bin/python -m pytest <tests>`

## Common Tasks

### Adding a New Feature (TDD Required)
1. Review existing similar features
2. **Write acceptance tests FIRST that define expected behavior**
3. Implement incrementally, making one test pass at a time
4. Follow established patterns
5. Add comprehensive error handling
6. Validate all inputs
7. Test in both Qt versions
8. Update documentation

### Fixing a Bug (TDD Required)
1. Understand root cause
2. **Write a failing test that reproduces the bug FIRST**
3. Implement the minimal fix to make the test pass
4. Check for similar issues elsewhere
5. Verify fix in both Qt versions
6. Document the fix (include test name in summary)

### Refactoring Code
1. Understand current behavior completely
2. Maintain backward compatibility
3. Keep Qt5/Qt6 compatibility
4. Test thoroughly
5. Update affected documentation

## Tool-Specific Notes

### For Cursor/Windsurf Users
- Enable Python language server
- Configure QGIS Python interpreter if possible
- Use inline documentation for QGIS API

### For Cline Users
- Include relevant documentation sections in context
- Reference specific files when asking questions
- Test generated code before committing

### For Aider Users
- Use `/add` to include relevant files
- Run tests with `/test` command
- Use `/undo` if changes break compatibility

## Getting Help

1. **Primary Reference**: See [CLAUDE.md](./CLAUDE.md) for comprehensive patterns
2. **Detailed Patterns**: Check `docs/AI_CODE_REFERENCE.md`
3. **Architecture**: Review `docs/architecture.md`
4. **Examples**: Look at existing implementations in codebase

## Important Reminders

- **Lives depend on this code**: Every feature matters for rescuer safety
- **Test thoroughly**: Both Qt versions, online and offline
- **When in doubt, ask**: Better to clarify than introduce bugs
- **Follow patterns**: Consistency improves maintainability
- **Document changes**: Others will maintain this in emergencies

## Quick Commands

```bash
# Run tests (RECOMMENDED - sets up QGIS environment)
./run_tests.sh

# Run tests with verbose output
./run_tests.sh -v

# Run specific test file
./run_tests.sh tests/test_e2e_scenarios.py -v

# Run only fast tests (no QGIS)
./run_tests.sh -m 'not qgis_required'

# Check compatibility
./tools/check_compatibility.sh

# Create local venv + pytest (if missing)
python3 -m venv .venv --system-site-packages
.venv/bin/pip install pytest pytest-qgis

# Reload plugin (in QGIS Python console)
from qgis.utils import reloadPlugin
reloadPlugin('sartracker')
```

---

**Document Version:** 1.1 (TDD fully adopted)
**Last Updated:** 2026-01-02
**For Claude-specific patterns:** See [CLAUDE.md](./CLAUDE.md)

## Landing the Plane (Session Completion)

**When ending a work session**, you MUST complete ALL steps below. Work is NOT complete until `git push` succeeds.

**MANDATORY WORKFLOW:**

1. **File issues for remaining work** - Create issues for anything that needs follow-up
2. **Run quality gates** (if code changed) - Tests, linters, builds
3. **Update issue status** - Close finished work, update in-progress items
4. **PUSH TO REMOTE** - This is MANDATORY:
   ```bash
   git pull --rebase
   bd sync
   git push
   git status  # MUST show "up to date with origin"
   ```
5. **Clean up** - Clear stashes, prune remote branches
6. **Verify** - All changes committed AND pushed
7. **Hand off** - Provide context for next session

**CRITICAL RULES:**
- Work is NOT complete until `git push` succeeds
- NEVER stop before pushing - that leaves work stranded locally
- NEVER say "ready to push when you are" - YOU must push
- If push fails, resolve and retry until it succeeds
