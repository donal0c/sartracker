# -*- coding: utf-8 -*-
"""
Configuration module for SAR Tracker.

Provides centralized configuration management through QSettings,
plus operational parameters for tunable settings.
"""

from .keys import SETTINGS_KEYS, ConfigStore
from .settings import ACTIVE_DEVICE_STALE_THRESHOLD_SECONDS

__all__ = ['SETTINGS_KEYS', 'ConfigStore', 'ACTIVE_DEVICE_STALE_THRESHOLD_SECONDS']
