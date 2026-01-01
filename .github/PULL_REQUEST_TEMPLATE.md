# Pull Request

## Description

<!-- Provide a clear description of the changes in this PR -->

## Type of Change

<!-- Mark relevant options with [x] -->

- [ ] Bug fix (non-breaking change which fixes an issue)
- [ ] New feature (non-breaking change which adds functionality)
- [ ] Breaking change (fix or feature that would cause existing functionality to not work as expected)
- [ ] Refactoring (no functional changes, code improvement)
- [ ] Documentation update
- [ ] Configuration/infrastructure change

## Related Issues

<!-- Link to related issues using #issue_number -->

Closes #
Relates to #

## Test Coverage (MANDATORY)

<!-- All code changes MUST include tests. Mark all that apply. -->

### Test Requirements Checklist

- [ ] **Tests included** - This PR includes tests for all new/changed code
- [ ] **Tests follow TDD** - Tests were written BEFORE implementation (for new features/bugs)
- [ ] **All tests pass** - `pytest` runs successfully
- [ ] **Test coverage** - New code is covered by tests (aim for 100%)

### Test Details

**Test files added/modified:**
<!-- List test files, e.g., tests/test_cache.py -->
-

**Test types:**
<!-- Mark all that apply -->
- [ ] Unit tests (no QGIS required)
- [ ] Integration tests (requires QGIS)
- [ ] Regression test (reproduces bug from issue)

**If bug fix, regression test added?**
- [ ] Yes - Test reproduces the bug and now passes
- [ ] No - ⚠️ **JUSTIFICATION REQUIRED** (explain below)
- [ ] N/A - Not a bug fix

**If no tests included:**

⚠️ **STOP** - Tests are MANDATORY for all code changes.

If you believe this PR is exempt (documentation-only, config-only), explain:
<!-- Provide justification for why tests are not included -->



## Life-Safety Critical Checklist

<!-- SAR Tracker is a LIFE-SAFETY CRITICAL system. -->
<!-- If your changes affect any of these areas, additional scrutiny is required. -->

Does this PR modify any of the following? (Mark with [x])

- [ ] Coordinate handling or transformations
- [ ] Mission state management (start/pause/resume/finish)
- [ ] Background task lifecycle
- [ ] Data persistence (GeoPackage, SQLite)
- [ ] Input validation (user input, coordinates, paths)
- [ ] Provider data fetching or polling
- [ ] Layer creation or modification

**If ANY are checked, confirm:**
- [ ] Tests cover all edge cases
- [ ] Error handling is comprehensive
- [ ] Changes work in both Qt5 and Qt6
- [ ] Changes work offline/poor connectivity
- [ ] Human review requested for safety-critical code

## Testing Performed

<!-- Describe testing beyond automated tests -->

### Manual Testing

**Environment:**
- QGIS Version:
- Qt Version (5 or 6):
- Operating System:

**Test Scenarios:**
<!-- Describe what you tested manually -->
1.
2.
3.

**Results:**
<!-- Summary of manual test results -->


### Compatibility Testing

- [ ] Tested on QGIS 3.28+ (Qt5)
- [ ] Tested on QGIS 3.40+ (Qt6)
- [ ] Tested offline/poor connectivity (if relevant)
- [ ] Tested plugin reload (`reloadPlugin('sartracker')`)

## Code Quality Checklist

- [ ] Code follows project style and conventions
- [ ] No direct PyQt5/PyQt6 imports (use `qgis.PyQt`)
- [ ] No raw Qt enums (use `utils.qt_compat`)
- [ ] Dialogs inherit from `BaseDialog`
- [ ] Background operations use `TaskManager`
- [ ] Input validation in place
- [ ] Error handling comprehensive
- [ ] No hardcoded paths or credentials
- [ ] Logging added for important operations
- [ ] Comments added for complex logic

## Documentation

- [ ] Code comments updated (if needed)
- [ ] CLAUDE.md updated (if workflow/pattern changes)
- [ ] AI_CODE_REFERENCE.md updated (if new patterns added)
- [ ] User-facing documentation updated (if UI/feature changes)

## Pre-Merge Checklist

<!-- Verify these before marking ready for review -->

- [ ] All tests pass locally
- [ ] No merge conflicts
- [ ] Commit messages are clear and descriptive
- [ ] Branch is up to date with master
- [ ] Self-review completed
- [ ] Ready for human review

## Additional Notes

<!-- Any additional context, screenshots, or notes for reviewers -->


---

**For Reviewers:**

- Review `docs/TDD_WORKFLOW.md` for TDD expectations
- Verify tests were written BEFORE code (for new features)
- Check test quality: Do they test behavior, not implementation?
- Verify life-safety critical changes have comprehensive error handling
- Confirm compatibility across Qt5/Qt6 if relevant
