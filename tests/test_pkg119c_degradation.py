"""pkg119 Phase C - graceful-degradation policy unit tests.

Pure Python, no Blender / engine / GPU. Two layers:

  1. ``blender_addon/degradation.py`` (the pure policy) loaded standalone - dedup,
     counts, consolidated "N approximated / M ignored" text, emit routing.
  2. ``blender_addon/__init__.py`` (the dispatch wiring) loaded with a stub bpy
     (mirroring tests/test_blender_native_nodes.py) - an unsupported surface
     shader node is REPORTED-IGNORED (never silent), an approximated node is
     recorded APPROXIMATED, a fully-supported node produces NO spurious entry,
     and the three sources (shader fallback / native drop / dropped-silent
     dispatch) all funnel through the ONE policy into one consolidated report.

Acceptance covered (spec Phase C):
  (a) an unsupported/dropped input produces a warning (not silence);
  (b) an approximated input is reported;
  (c) a fully-supported scene produces NO spurious warnings;
  (d) the three sources funnel through one policy / one per-render report.
"""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
_ADDON = REPO_ROOT / "blender_addon"


# --------------------------------------------------------------------------- #
# layer 1: the pure policy, loaded standalone (no bpy)
# --------------------------------------------------------------------------- #

def _load_degradation():
    if str(_ADDON) not in sys.path:
        sys.path.insert(0, str(_ADDON))
    spec = importlib.util.spec_from_file_location(
        "pkg119c_degradation", _ADDON / "degradation.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


deg = _load_degradation()


def test_empty_report_emits_nothing():
    r = deg.DegradationReport()
    assert r.is_empty()
    assert r.text() == ""
    reports = []
    assert r.emit(lambda tag, m: reports.append((tag, m))) == ""
    assert reports == []


def test_approximate_and_ignore_counts_and_dedup():
    r = deg.DegradationReport()
    r.approximate("BSDF_SHEEN", "microfiber sheen -> Disney sheen")
    r.approximate("BSDF_SHEEN", "microfiber sheen -> Disney sheen")  # dup
    r.ignore("shader node 'BSDF_TOON'", "unsupported -> neutral grey")
    r.ignore("shader node 'BSDF_TOON'", "unsupported -> neutral grey")  # dup
    assert len(r.approximated) == 1
    assert len(r.ignored) == 1
    assert r.summary() == "Astroray degradation: 1 approximated / 1 ignored"


def test_ignore_messages_folds_a_list():
    r = deg.DegradationReport()
    r.ignore_messages([
        "camera projection 'ORTHO' (engine renders PERSP only)",
        "light specular_factor on Key (per-light specular ignored)",
    ])
    assert len(r.ignored) == 2
    assert r.approximated == []


def test_emit_produces_one_consolidated_warning():
    r = deg.DegradationReport()
    r.approximate("BSDF_METALLIC", "F82 edge tint -> Disney metallic")
    r.ignore("camera projection 'PANO'")
    reports = []
    text = r.emit(lambda tag, m: reports.append((tag, m)))
    assert len(reports) == 1                          # exactly one report per render
    tag, msg = reports[0]
    assert tag == {'WARNING'}
    assert msg == text
    assert "1 approximated / 1 ignored" in msg
    assert "approximated BSDF_METALLIC" in msg
    assert "ignored camera projection 'PANO'" in msg


def test_emit_falls_back_to_print_without_report(capsys):
    r = deg.DegradationReport()
    r.ignore("shader node 'BSDF_HAIR'")
    r.emit(report=None)
    out = capsys.readouterr().out
    assert "BSDF_HAIR" in out
    assert "0 approximated / 1 ignored" in out


# --------------------------------------------------------------------------- #
# layer 2: dispatch wiring in the addon, loaded with a stub bpy
# --------------------------------------------------------------------------- #

def _load_blender_addon(monkeypatch):
    """Same shape as tests/test_blender_native_nodes.py:_load_blender_addon."""
    bpy_module = types.ModuleType("bpy")
    bpy_types_module = types.ModuleType("bpy.types")
    bpy_props_module = types.ModuleType("bpy.props")

    class _Base:
        pass

    class _RenderEngineBase:
        def report(self, *a, **k):
            return None

        def update_progress(self, *a, **k):
            return None

        def test_break(self):
            return False

    bpy_types_module.Panel = _Base
    bpy_types_module.Operator = _Base
    bpy_types_module.AddonPreferences = _Base
    bpy_types_module.PropertyGroup = _Base
    bpy_types_module.RenderEngine = _RenderEngineBase
    bpy_module.types = bpy_types_module

    for name in ("BoolProperty", "IntProperty", "FloatProperty", "StringProperty",
                 "PointerProperty", "FloatVectorProperty", "EnumProperty"):
        setattr(bpy_props_module, name, lambda **_kwargs: None)
    bpy_module.props = bpy_props_module
    bpy_module.path = types.SimpleNamespace(abspath=lambda p: p)

    shader_blending_module = types.ModuleType("shader_blending")
    shader_blending_module.blend_shader_specs = lambda *a, **k: None
    shader_blending_module.add_shader_specs = lambda *a, **k: None

    mathutils_module = types.ModuleType("mathutils")
    mathutils_module.Vector = lambda values: values

    astroray_module = types.ModuleType("astroray")
    astroray_module.__version__ = "test"
    astroray_module.__features__ = {"cuda": False, "spectral": True}
    astroray_module.__file__ = "/fake/astroray.pyd"
    astroray_module.integrator_registry_names = lambda: ["path_tracer"]
    astroray_module.material_registry_names = lambda: ["lambertian", "disney", "dielectric"]
    astroray_module.pass_registry_names = list

    monkeypatch.setitem(sys.modules, "bpy", bpy_module)
    monkeypatch.setitem(sys.modules, "bpy.types", bpy_types_module)
    monkeypatch.setitem(sys.modules, "bpy.props", bpy_props_module)
    monkeypatch.setitem(sys.modules, "shader_blending", shader_blending_module)
    monkeypatch.setitem(sys.modules, "mathutils", mathutils_module)
    monkeypatch.setitem(sys.modules, "astroray", astroray_module)

    sys.modules.pop("astroray_blender_addon_pkg119c", None)
    module_path = _ADDON / "__init__.py"
    spec = importlib.util.spec_from_file_location(
        "astroray_blender_addon_pkg119c", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class _Socket:
    def __init__(self, default=0.0, linked_to=None, output_name=""):
        self.default_value = default
        self.is_linked = linked_to is not None
        self.links = []
        if linked_to is not None:
            self.links.append(types.SimpleNamespace(
                from_node=linked_to,
                from_socket=types.SimpleNamespace(name=output_name or "BSDF"),
            ))


class _Node:
    def __init__(self, ntype="", bl_idname="", inputs=None, **extra):
        self.type = ntype
        self.bl_idname = bl_idname
        self.inputs = inputs or {}
        for k, v in extra.items():
            setattr(self, k, v)


class _RecordingRenderer:
    def __init__(self):
        self.created_materials = []
        self._next_id = 1

    def create_material(self, mat_type, color, params):
        self.created_materials.append((mat_type, list(color), dict(params)))
        mid = self._next_id
        self._next_id += 1
        return mid


def _engine(addon):
    e = addon.CustomRaytracerRenderEngine()
    e._volume_material_map = {}
    return e


# (a) an unsupported surface shader node is REPORTED-IGNORED, not silent
def test_unsupported_shader_node_is_reported_not_silent(monkeypatch):
    addon = _load_blender_addon(monkeypatch)
    engine = _engine(addon)
    renderer = _RecordingRenderer()

    # BSDF_TOON has no handler in the translation layer -> would fall through to a
    # neutral grey Disney with no trace (the DROPPED-SILENT failure mode).
    toon = _Node(ntype="BSDF_TOON", bl_idname="ShaderNodeBsdfToon",
                 inputs={'Color': _Socket(default=(0.8, 0.1, 0.1, 1.0))})
    mat_id = engine.convert_shader_node(toon, renderer, node_tree=None)

    # still renders (neutral material) ...
    assert mat_id == 1
    assert renderer.created_materials[0][0] == "disney"
    # ... but is NOT silent: recorded as an ignored degradation.
    ignored = engine._degradation_report().ignored
    assert any("BSDF_TOON" in feature for feature, _ in ignored)
    assert engine._degradation_report().approximated == []


# (b) an approximated node is reported (funnels through _warn_shader_fallback)
def test_approximated_shader_node_is_reported(monkeypatch):
    addon = _load_blender_addon(monkeypatch)
    engine = _engine(addon)
    renderer = _RecordingRenderer()

    sheen = _Node(ntype="BSDF_SHEEN", bl_idname="ShaderNodeBsdfSheen",
                  inputs={
                      'Color': _Socket(default=(0.8, 0.8, 0.8, 1.0)),
                      'Roughness': _Socket(default=0.5),
                      'Weight': _Socket(default=1.0),
                  })
    engine.convert_shader_node(sheen, renderer, node_tree=None)

    approximated = engine._degradation_report().approximated
    assert any(feat == "BSDF_SHEEN" for feat, _ in approximated)
    # an approximated node is a recognised translation, NOT an ignored drop.
    assert engine._degradation_report().ignored == []


# (c) a fully-supported node produces NO spurious degradation
def test_supported_shader_node_no_spurious_warning(monkeypatch):
    addon = _load_blender_addon(monkeypatch)
    engine = _engine(addon)
    renderer = _RecordingRenderer()

    glass = _Node(ntype="BSDF_GLASS", bl_idname="ShaderNodeBsdfGlass",
                  inputs={
                      'Color': _Socket(default=(1.0, 1.0, 1.0, 1.0)),
                      'Roughness': _Socket(default=0.0),
                      'IOR': _Socket(default=1.5),
                  })
    engine.convert_shader_node(glass, renderer, node_tree=None)

    assert engine._degradation_report().is_empty(), (
        "a fully-supported node must not record any degradation")


# (d) the three sources funnel through ONE policy / one consolidated report
def test_three_sources_funnel_through_one_policy(monkeypatch):
    addon = _load_blender_addon(monkeypatch)
    engine = _engine(addon)
    renderer = _RecordingRenderer()

    # source 1: shader-node fallback (APPROXIMATED)
    sheen = _Node(ntype="BSDF_SHEEN", bl_idname="ShaderNodeBsdfSheen",
                  inputs={
                      'Color': _Socket(default=(0.8, 0.8, 0.8, 1.0)),
                      'Roughness': _Socket(default=0.5),
                      'Weight': _Socket(default=1.0),
                  })
    engine.convert_shader_node(sheen, renderer, node_tree=None)

    # source 2: dropped-silent dispatch fall-through (IGNORED)
    toon = _Node(ntype="BSDF_TOON", bl_idname="ShaderNodeBsdfToon",
                 inputs={'Color': _Socket(default=(0.1, 0.1, 0.1, 1.0))})
    engine.convert_shader_node(toon, renderer, node_tree=None)

    # source 3: native world/light/camera drops (IGNORED), folded as messages
    engine._degradation_report().ignore_messages(
        ["camera projection 'ORTHO' (engine renders PERSP only)"])

    reports = []
    text = engine._degradation_report().emit(
        lambda tag, m: reports.append((tag, m)))

    assert len(reports) == 1, "all three sources collapse into ONE per-render report"
    assert "1 approximated / 2 ignored" in text
    assert "BSDF_SHEEN" in text            # source 1
    assert "BSDF_TOON" in text             # source 2
    assert "ORTHO" in text                 # source 3


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
