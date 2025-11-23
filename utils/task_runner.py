# -*- coding: utf-8 -*-
"""
Lightweight task runner helpers for headless/background work.
"""
from typing import Callable, Any


def run_inline(func: Callable[[], Any]) -> Any:
    """Execute callable inline; wrapper for symmetry with async runs."""
    return func()
