"""
Dependency guards for optional third-party modules.

Some Linux QGIS builds omit `chardet` and `charset_normalizer`, which the
`requests` library tries to import at module import time. When both are
missing, importing `requests` raises ModuleNotFoundError before SAR Tracker
has a chance to handle the failure.

This module installs lightweight in-plugin fallbacks so the plugin loads
without requiring users to install extra system packages. The fallback
modules provide the minimal API (`detect`, `from_bytes`, `.best()`, etc.)
that `requests` relies on for charset detection. Responses are treated as
UTF-8 unless decoding fails, in which case we fall back to latin-1.
"""

from __future__ import annotations

import importlib
import sys
import types
from typing import Dict, List, Tuple


def _try_import(module_name: str) -> bool:
    """
    Attempt to import a module, returning True on success.
    """
    try:
        importlib.import_module(module_name)
        return True
    except ModuleNotFoundError:
        return False


def _detect_encoding(sample: object) -> Tuple[str, float]:
    """
    Simple charset detection: prefer UTF-8, fall back to latin-1.

    Args:
        sample: Bytes or string content to inspect.

    Returns:
        Tuple of (encoding, confidence).
    """
    if isinstance(sample, bytes):
        data = sample
    else:
        data = str(sample or "").encode("utf-8", errors="ignore")

    for encoding, confidence in (("utf-8", 0.99), ("latin-1", 0.20)):
        try:
            data.decode(encoding)
            return encoding, confidence
        except UnicodeDecodeError:
            continue

    return "utf-8", 0.0


def _create_charset_module(module_name: str) -> types.ModuleType:
    """
    Create a stub charset detection module compatible with chardet/charset_normalizer.
    """
    module = types.ModuleType(module_name)
    module.__dict__["__version__"] = "0.0-sartracker"

    class CharsetMatch:
        def __init__(self, encoding: str, confidence: float):
            self.encoding = encoding
            self.alphabets: List[str] = []
            self.language = None
            self.encoding_aliases = [encoding]
            self.chaos = 0.0
            self.coherence = confidence

        def best(self) -> "CharsetMatch":
            return self

        def first(self) -> "CharsetMatch":
            return self

        def __iter__(self):
            yield self

    class CharsetMatchSequence(list):
        def best(self):
            return self[0] if self else None

        def first(self):
            return self[0] if self else None

    def detect(data: object) -> Dict[str, object]:
        encoding, confidence = _detect_encoding(data)
        return {"encoding": encoding, "confidence": confidence, "language": None}

    def from_bytes(data: bytes, **_: object) -> CharsetMatchSequence:
        encoding, confidence = _detect_encoding(data)
        return CharsetMatchSequence([CharsetMatch(encoding, confidence)])

    module.detect = detect  # type: ignore[attr-defined]
    module.from_bytes = from_bytes  # type: ignore[attr-defined]
    module.api = types.SimpleNamespace(from_bytes=from_bytes)  # type: ignore[attr-defined]

    return module


def ensure_requests_charset_modules(force_stub: bool = False) -> List[str]:
    """
    Ensure chardet/charset_normalizer modules are importable before importing requests.

    Args:
        force_stub: Force installation of stub modules (used in tests).

    Returns:
        List of module names that were installed as fallbacks.
    """
    installed: List[str] = []

    charset_module = None

    if force_stub or not _try_import("charset_normalizer"):
        charset_module = _create_charset_module("charset_normalizer")
        sys.modules["charset_normalizer"] = charset_module
        installed.append("charset_normalizer")
    else:
        charset_module = sys.modules["charset_normalizer"]

    if force_stub or not _try_import("chardet"):
        # Reuse the charset_normalizer stub to satisfy requests' first import.
        if charset_module is None:
            charset_module = _create_charset_module("charset_normalizer")
            sys.modules["charset_normalizer"] = charset_module
            installed.append("charset_normalizer")

        sys.modules["chardet"] = charset_module
        installed.append("chardet")

    if installed:
        print(
            "[SAR Tracker] Installed fallback charset helpers: "
            + ", ".join(sorted(set(installed)))
        )

    return installed


