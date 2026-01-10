# -*- coding: utf-8 -*-
"""
Tests for Qt5/Qt6 compatible dialog button enums.
"""

import importlib
import sys


def _load_qt_compat():
    """Load real qt_compat module even when conftest installs a mock."""
    sys.modules.pop("utils.qt_compat", None)
    sys.modules.pop("sartracker.utils.qt_compat", None)
    return importlib.import_module("utils.qt_compat")


def test_dialog_buttons_importable():
    """Dialog button enums should be importable from qt_compat."""
    qt_compat = _load_qt_compat()
    assert qt_compat.DialogButtonOk is not None
    assert qt_compat.DialogButtonCancel is not None


def test_dialog_buttons_in_all():
    """Dialog button enums should be exported in __all__."""
    qt_compat = _load_qt_compat()
    assert 'DialogButtonOk' in qt_compat.__all__
    assert 'DialogButtonCancel' in qt_compat.__all__
