import sys
from types import ModuleType

import pytest

from utils import dependency_guard


@pytest.fixture
def restore_modules():
    saved = {}
    for name in ("charset_normalizer", "chardet"):
        saved[name] = sys.modules.get(name)
        sys.modules.pop(name, None)
    try:
        yield
    finally:
        for name, module in saved.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module


def test_installs_fallback_modules_when_missing(monkeypatch, restore_modules):
    monkeypatch.setattr(dependency_guard, "_try_import", lambda name: False)

    installed = dependency_guard.ensure_requests_charset_modules()

    assert set(installed) == {"chardet", "charset_normalizer"}

    stub = sys.modules.get("charset_normalizer")
    assert isinstance(stub, ModuleType)
    probe = stub.detect(b"example payload")  # type: ignore[attr-defined]
    assert probe["encoding"] == "utf-8"


def test_noop_when_dependencies_present(monkeypatch, restore_modules):
    def fake_import(name):
        module = ModuleType(name)
        module.detect = lambda data: {"encoding": "utf-8", "confidence": 1.0}
        sys.modules[name] = module
        return True

    monkeypatch.setattr(dependency_guard, "_try_import", lambda name: fake_import(name))

    installed = dependency_guard.ensure_requests_charset_modules()

    assert installed == []

