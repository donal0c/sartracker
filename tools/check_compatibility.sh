#!/bin/bash
# -*- coding: utf-8 -*-
#
# SAR Tracker - Qt5/Qt6 Compatibility Guard
#
# This script checks for common Qt5/Qt6 compatibility violations.
# Run this before committing code to ensure compatibility patterns are followed.
#
# Usage:
#   ./tools/check_compatibility.sh
#
# Exit codes:
#   0 - All checks passed
#   1 - One or more checks failed

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Get the script directory and project root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# Change to project root
cd "$PROJECT_ROOT"

# Track if any checks failed
FAILED=0

echo "=================================================="
echo "SAR Tracker - Qt5/Qt6 Compatibility Guard"
echo "=================================================="
echo ""

# ============================================================================
# Check 1: Direct PyQt5/PyQt6 imports
# ============================================================================
echo "Check 1: Direct PyQt5/PyQt6 imports..."
echo "  Searching for: 'from PyQt5' or 'from PyQt6' or 'import PyQt5' or 'import PyQt6'"
echo ""

PYQT_IMPORTS=$(grep -r "from PyQt[56]" . --include="*.py" \
    --exclude-dir=".git" \
    --exclude-dir="__pycache__" \
    --exclude-dir=".pytest_cache" \
    --exclude-dir="archive" \
    --exclude-dir="From_Eamon" \
    2>/dev/null || true)

PYQT_IMPORTS2=$(grep -r "import PyQt[56]" . --include="*.py" \
    --exclude-dir=".git" \
    --exclude-dir="__pycache__" \
    --exclude-dir=".pytest_cache" \
    --exclude-dir="archive" \
    --exclude-dir="From_Eamon" \
    2>/dev/null || true)

if [ -z "$PYQT_IMPORTS" ] && [ -z "$PYQT_IMPORTS2" ]; then
    echo -e "  ${GREEN}✅ PASS${NC} - No direct PyQt5/PyQt6 imports found"
else
    echo -e "  ${RED}❌ FAIL${NC} - Direct PyQt5/PyQt6 imports found:"
    echo ""
    echo "$PYQT_IMPORTS"
    echo "$PYQT_IMPORTS2"
    echo ""
    echo "  ⚠️  All Qt imports must use 'from qgis.PyQt.*' instead"
    echo "  Example: from qgis.PyQt.QtCore import Qt"
    FAILED=1
fi

echo ""

# ============================================================================
# Check 2: Direct Qt enum usage (outside utils/qt_compat.py)
# ============================================================================
echo "Check 2: Direct Qt enum usage..."
echo "  Searching for: 'Qt.EnumName' (outside utils/qt_compat.py)"
echo ""

# Look for actual Qt enum usage patterns:
# - Qt.LeftButton, Qt.Checked, Qt.AlignCenter, etc.
# Pattern matches: space/tab/=/==/!=/(/,/[ followed by Qt. followed by uppercase letter
QT_ENUMS=$(grep -rE "([ \t=!(,\[]|^)Qt\.[A-Z]" . --include="*.py" \
    --exclude-dir=".git" \
    --exclude-dir="__pycache__" \
    --exclude-dir=".pytest_cache" \
    --exclude-dir="archive" \
    --exclude-dir="From_Eamon" \
    2>/dev/null | grep -v "utils/qt_compat.py" | grep -v "from qgis.PyQt" | grep -v "import" | grep -v "^[[:space:]]*#" | grep -v "    - " || true)

if [ -z "$QT_ENUMS" ]; then
    echo -e "  ${GREEN}✅ PASS${NC} - No direct Qt enum usage found outside qt_compat.py"
else
    echo -e "  ${RED}❌ FAIL${NC} - Direct Qt enum usage found:"
    echo ""
    echo "$QT_ENUMS"
    echo ""
    echo "  ⚠️  Import constants from utils/qt_compat instead"
    echo "  Example: from utils.qt_compat import LeftButton, Checked"
    FAILED=1
fi

echo ""

# ============================================================================
# Check 3: QDialog subclasses (should warn, not fail)
# ============================================================================
echo "Check 3: QDialog subclasses..."
echo "  Searching for: 'class Name(QDialog)' (should use SafeQDialog)"
echo ""

# Exclude the known base classes
QDIALOG_SUBCLASSES=$(grep -r "class.*QDialog)" . --include="*.py" \
    --exclude-dir=".git" \
    --exclude-dir="__pycache__" \
    --exclude-dir=".pytest_cache" \
    --exclude-dir="archive" \
    --exclude-dir="From_Eamon" \
    2>/dev/null | grep -v "utils/dialog_utils.py" | grep -v "class SafeQDialog" | grep -v "class DelayedShowDialog" || true)

if [ -z "$QDIALOG_SUBCLASSES" ]; then
    echo -e "  ${GREEN}✅ PASS${NC} - All dialogs use SafeQDialog"
else
    echo -e "  ${YELLOW}⚠️  WARNING${NC} - QDialog subclasses found (should use SafeQDialog):"
    echo ""
    echo "$QDIALOG_SUBCLASSES"
    echo ""
    echo "  ℹ️  These dialogs should inherit from SafeQDialog for rendering fixes"
    echo "  Example: from utils.dialog_utils import SafeQDialog"
    echo "           class MyDialog(SafeQDialog): ..."
    echo ""
    echo "  This is a WARNING, not a failure (Phase 3 migration in progress)"
fi

echo ""

# ============================================================================
# Check 4: Direct dialog.exec() or dialog.exec_() calls (outside utils/)
# ============================================================================
echo "Check 4: Direct dialog execution..."
echo "  Searching for: '.exec()' or '.exec_()' (outside utils/)"
echo ""

DIRECT_EXEC=$(grep -r "\.exec_\?()" . --include="*.py" \
    --exclude-dir=".git" \
    --exclude-dir="__pycache__" \
    --exclude-dir=".pytest_cache" \
    --exclude-dir="archive" \
    --exclude-dir="From_Eamon" \
    2>/dev/null | grep -v "utils/qt_compat.py" | grep -v "utils/dialog_utils.py" | grep -v "def dialog_exec" | grep -v "# " || true)

if [ -z "$DIRECT_EXEC" ]; then
    echo -e "  ${GREEN}✅ PASS${NC} - All dialog execution uses dialog_exec() wrapper"
else
    echo -e "  ${RED}❌ FAIL${NC} - Direct exec() calls found:"
    echo ""
    echo "$DIRECT_EXEC"
    echo ""
    echo "  ⚠️  Use dialog_exec() wrapper instead"
    echo "  Example: from utils.qt_compat import dialog_exec"
    echo "           result = dialog_exec(my_dialog)"
    FAILED=1
fi

echo ""

# ============================================================================
# Check 5: Direct notification calls (should use utils.notify)
# ============================================================================
echo "Check 5: Notification consistency..."
echo "  Searching for: '.pushMessage()' (outside utils/notify.py)"
echo ""

DIRECT_NOTIFY=$(grep -r "\.pushMessage\(" . --include="*.py" \
    --exclude-dir=".git" \
    --exclude-dir="__pycache__" \
    --exclude-dir=".pytest_cache" \
    --exclude-dir="archive" \
    --exclude-dir="From_Eamon" \
    2>/dev/null | grep -v "utils/notify.py" | grep -v "utils/qt_compat.py" | grep -v "^[[:space:]]*#" || true)

if [ -z "$DIRECT_NOTIFY" ]; then
    echo -e "  ${GREEN}✅ PASS${NC} - All notifications use utils.notify helpers"
else
    echo -e "  ${YELLOW}⚠️  WARNING${NC} - Direct pushMessage() calls found:"
    echo ""
    echo "$DIRECT_NOTIFY"
    echo ""
    echo "  ℹ️  Use utils.notify helpers for consistency:"
    echo "  from utils.notify import info, warning, error, success"
    echo "  info(iface.messageBar(), 'Title', 'Message')"
    echo ""
    echo "  This is a WARNING, not a failure"
fi

echo ""

# ============================================================================
# Summary
# ============================================================================
echo "=================================================="
echo "Summary"
echo "=================================================="
echo ""

if [ $FAILED -eq 0 ]; then
    echo -e "${GREEN}✅ ALL CHECKS PASSED${NC}"
    echo ""
    echo "Your code is Qt5/Qt6 compatible! 🎉"
    echo ""
    exit 0
else
    echo -e "${RED}❌ SOME CHECKS FAILED${NC}"
    echo ""
    echo "Please fix the compatibility issues above before committing."
    echo "See compatibility_and_best_practices_doc.md for guidance."
    echo ""
    exit 1
fi
