"""pkg116 — Exporter/cache refactor: per-domain cache diff() tests.

Phase 1: Tests the architectural structure (Change enum, cache classes with
diff() methods). The diff() implementations are stubs in Phase 1; this test
verifies the interface exists and returns bool as required by the spec.

Future phases will add real diff logic and test that each cache fires for
its update type and not others, and that dispatch order is preserved.
"""

import importlib.util
from pathlib import Path

import pytest


def _load_exporter_module():
    """Load exporter.py as a standalone module (no bpy dependency)."""
    module_path = Path(__file__).parent.parent / "blender_addon" / "exporter.py"
    spec = importlib.util.spec_from_file_location("astroray_exporter", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# 1. Change enum: verify bitflag structure
# ---------------------------------------------------------------------------

def test_change_enum_exists():
    exp = _load_exporter_module()
    assert hasattr(exp, 'Change')
    Change = exp.Change
    assert hasattr(Change, 'NONE')
    assert hasattr(Change, 'ENVIRONMENT')
    assert hasattr(Change, 'MATERIALS')
    assert hasattr(Change, 'LIGHTS')
    assert hasattr(Change, 'GEOMETRY')
    assert hasattr(Change, 'TRANSFORMS')
    assert hasattr(Change, 'BACKEND_CONFIG')
    assert hasattr(Change, 'ACCUMULATION_ONLY')


def test_change_enum_bitflag_or():
    exp = _load_exporter_module()
    Change = exp.Change
    # ORing flags produces the union
    combined = Change.MATERIALS | Change.LIGHTS
    assert combined & Change.MATERIALS
    assert combined & Change.LIGHTS
    assert not (combined & Change.GEOMETRY)


def test_change_enum_none_is_zero():
    exp = _load_exporter_module()
    Change = exp.Change
    assert Change.NONE == 0
    assert not (Change.NONE & Change.MATERIALS)


# ---------------------------------------------------------------------------
# 2. Per-domain cache classes: verify diff() interface
# ---------------------------------------------------------------------------

def test_camera_cache_exists_and_has_diff():
    exp = _load_exporter_module()
    assert hasattr(exp, 'CameraCache')
    cache = exp.CameraCache()
    assert hasattr(cache, 'diff')
    assert callable(cache.diff)


def test_objects_cache_exists_and_has_diff():
    exp = _load_exporter_module()
    assert hasattr(exp, 'ObjectsCache')
    cache = exp.ObjectsCache()
    assert hasattr(cache, 'diff')
    assert callable(cache.diff)


def test_materials_cache_exists_and_has_diff():
    exp = _load_exporter_module()
    assert hasattr(exp, 'MaterialsCache')
    cache = exp.MaterialsCache()
    assert hasattr(cache, 'diff')
    assert callable(cache.diff)


def test_lights_cache_exists_and_has_diff():
    exp = _load_exporter_module()
    assert hasattr(exp, 'LightsCache')
    cache = exp.LightsCache()
    assert hasattr(cache, 'diff')
    assert callable(cache.diff)


def test_world_cache_exists_and_has_diff():
    exp = _load_exporter_module()
    assert hasattr(exp, 'WorldCache')
    cache = exp.WorldCache()
    assert hasattr(cache, 'diff')
    assert callable(cache.diff)


def test_config_cache_exists_and_has_diff():
    exp = _load_exporter_module()
    assert hasattr(exp, 'ConfigCache')
    cache = exp.ConfigCache()
    assert hasattr(cache, 'diff')
    assert callable(cache.diff)


# ---------------------------------------------------------------------------
# 3. diff() returns bool (Phase 1 stub behavior)
# ---------------------------------------------------------------------------

class _StubDepsgraph:
    """Minimal depsgraph stand-in for diff() calls."""
    def __init__(self, updates=None):
        self.updates = updates or []


def test_camera_cache_diff_returns_bool():
    exp = _load_exporter_module()
    cache = exp.CameraCache()
    dg = _StubDepsgraph()
    result = cache.diff(dg)
    assert isinstance(result, bool)


def test_objects_cache_diff_returns_bool():
    exp = _load_exporter_module()
    cache = exp.ObjectsCache()
    dg = _StubDepsgraph()
    result = cache.diff(dg)
    assert isinstance(result, bool)


def test_materials_cache_diff_returns_bool():
    exp = _load_exporter_module()
    cache = exp.MaterialsCache()
    dg = _StubDepsgraph()
    result = cache.diff(dg)
    assert isinstance(result, bool)


def test_lights_cache_diff_returns_bool():
    exp = _load_exporter_module()
    cache = exp.LightsCache()
    dg = _StubDepsgraph()
    result = cache.diff(dg)
    assert isinstance(result, bool)


def test_world_cache_diff_returns_bool():
    exp = _load_exporter_module()
    cache = exp.WorldCache()
    dg = _StubDepsgraph()
    result = cache.diff(dg)
    assert isinstance(result, bool)


def test_config_cache_diff_returns_bool():
    exp = _load_exporter_module()
    cache = exp.ConfigCache()
    dg = _StubDepsgraph()
    result = cache.diff(dg)
    assert isinstance(result, bool)


# ---------------------------------------------------------------------------
# 4. Exporter class: verify it exists and has view_update/view_draw
# ---------------------------------------------------------------------------

def test_exporter_class_exists():
    exp = _load_exporter_module()
    assert hasattr(exp, 'Exporter')


def test_exporter_has_view_update():
    exp = _load_exporter_module()
    # Can't instantiate without a real engine, but we can check the method exists
    assert hasattr(exp.Exporter, 'view_update')
    assert callable(exp.Exporter.view_update)


def test_exporter_has_view_draw():
    exp = _load_exporter_module()
    assert hasattr(exp.Exporter, 'view_draw')
    assert callable(exp.Exporter.view_draw)
