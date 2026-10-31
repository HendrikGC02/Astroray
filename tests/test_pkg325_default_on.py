"""pkg325 default-on (owner 2026-10-31): the addon defaults ``dielectric_bounce_cap`` to
``passthrough``; every Cycles-parity harness that renders Astroray through the addon forces
``terminate`` so parity gates compare like with like. The engine/binding default stays ``terminate``.
"""
import ast
import re
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

# Harnesses that configure scene.custom_raytracer for a Cycles comparison.
PARITY_LEGS = [
    "benchmarks/blender_parity/render_leg.py",  # corpus (mc_tolerance, production, v2), run_parity, gates b/c, pkg119b, showcase/spectral
    "benchmarks/cycles-parity/metal_ab/render_leg.py",
    "benchmarks/cycles-parity/thin_film/render_leg.py",
    "benchmarks/cycles-parity/ies_spot/ies_leg.py",
    "benchmarks/viewport_parity/blender_driver.py",
    "scripts/dev/issue818_render.py",
]


def test_addon_property_default_is_passthrough():
    src = (ROOT / "blender_addon" / "__init__.py").read_text(encoding="utf-8")
    m = re.search(r"dielectric_bounce_cap: EnumProperty\(.*?\n    \)\n", src, re.S)
    assert m, "dielectric_bounce_cap property not found"
    assert re.search(r"default='passthrough'", m.group(0))
    # the fallback used when the property is absent must agree (convert_scene + viewport + exporter)
    for rel in ("blender_addon/__init__.py", "blender_addon/exporter.py"):
        text = (ROOT / rel).read_text(encoding="utf-8")
        fallbacks = re.findall(r'"dielectric_bounce_cap", "(\w+)"\)', text)
        assert fallbacks and set(fallbacks) == {"passthrough"}, (rel, fallbacks)


@pytest.mark.parametrize("rel", PARITY_LEGS)
def test_parity_leg_forces_terminate(rel):
    tree = ast.parse((ROOT / rel).read_text(encoding="utf-8"))
    hits = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Attribute) and t.attr == "dielectric_bounce_cap" for t in node.targets):
            hits.append(ast.unparse(node.value))
    # render_leg takes an opt-out env var for pkg325 evidence runs, defaulting to terminate.
    assert hits and all("'terminate'" in h for h in hits), (rel, hits)


def test_viewport_driver_embedded_scripts_force_terminate():
    text = (ROOT / "benchmarks/viewport_parity/blender_driver.py").read_text(encoding="utf-8")
    assert "dielectric_bounce_cap = 'terminate'" in text and 'dielectric_bounce_cap = "terminate"' in text


def test_convert_scene_falls_back_to_passthrough_when_property_absent(monkeypatch):
    from test_pkg325_bounce_cap_passthrough import _wiring_renderer
    from test_blender_light_sampler_wiring import _load_blender_addon, _make_settings
    calls = []
    R = _wiring_renderer(calls)
    addon = _load_blender_addon(monkeypatch, R)
    engine = addon.CustomRaytracerRenderEngine()
    engine.setup_camera = lambda *a: None
    engine.convert_materials = lambda *a: {}
    engine.convert_objects = lambda *a: None
    engine.convert_lights = lambda *a: None
    engine.setup_world = lambda *a: None
    settings = _make_settings()
    if hasattr(settings, "dielectric_bounce_cap"):
        delattr(settings, "dielectric_bounce_cap")
    scene = types.SimpleNamespace(custom_raytracer=settings, cycles=None, render=None, camera=None)
    engine.convert_scene(types.SimpleNamespace(scene=scene, object_instances=[]), R(), 16, 16)
    assert calls == ["passthrough"]


def test_engine_binding_default_stays_terminate():
    text = (ROOT / "include" / "raytracer.h").read_text(encoding="utf-8", errors="replace")
    assert "false (default) = \"terminate\"" in text
