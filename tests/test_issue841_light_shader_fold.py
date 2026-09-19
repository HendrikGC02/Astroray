"""#841 — the light node tree's constant factors reach the lamp.

Cycles multiplies the light shader emission (Emission Color x Strength) into the
lamp strength (kernel/light/sample.h). The pkg259 lighting_studio spot wires
TexIES -> Math(MULTIPLY, 180) -> Emission Strength with Emission Color
(0.95, 0.87, 0.72); the addon used to drop both (~180x dark, wrong tint).
_resolve_light_shader folds a constant Emission Color and the Strength chain
(TexIES Strength, Math x / ÷ constants, Value) and reports anything else.
"""

import math
import types

import pytest

from _batch_a_stub import load_addon


def _sock(name, value=None, src=None):
    s = types.SimpleNamespace(name=name, identifier=name, default_value=value,
                              is_linked=src is not None, links=[])
    if src is not None:
        s.links = [types.SimpleNamespace(from_node=src)]
    return s


def _node(ntype, inputs=(), outputs=None, **kw):
    n = types.SimpleNamespace(type=ntype, inputs=list(inputs), **kw)
    n.outputs = outputs if outputs is not None else [types.SimpleNamespace(is_linked=True, default_value=0.0)]
    return n


def _studio_tree(factor=180.0, op="MULTIPLY", color=(0.95, 0.87, 0.72, 1.0), ies_strength=1.0,
                 clamp=False):
    ies = _node("TEX_IES", [_sock("Vector"), _sock("Strength", ies_strength)],
                mode="INTERNAL", filepath="", ies=None)
    math_node = _node("MATH", [_sock("Value", 0.5, ies), _sock("Value", factor), _sock("Value", 0.0)],
                      operation=op, use_clamp=clamp)
    em = _node("EMISSION", [_sock("Color", color), _sock("Strength", 1.0, math_node), _sock("Weight", 0.0)])
    out = _node("OUTPUT_LIGHT", [_sock("Surface", None, em)], outputs=[], is_active_output=True)
    return types.SimpleNamespace(nodes=[ies, math_node, em, out])


@pytest.fixture
def engine(monkeypatch):
    addon = load_addon(monkeypatch, "issue841")
    eng = addon.CustomRaytracerRenderEngine()
    eng.warnings = []
    eng._warn_shader_fallback = lambda t, m: eng.warnings.append((t, m))
    return addon, eng


def test_studio_spot_multiply_and_color_folded(engine):
    _addon, eng = engine
    light = types.SimpleNamespace(node_tree=_studio_tree(), use_nodes=True)
    strength, color = eng._resolve_light_shader(light)
    assert strength == pytest.approx(180.0)
    assert color == pytest.approx([0.95, 0.87, 0.72])
    assert eng.warnings == []


def test_divide_value_and_ies_strength_fold(engine):
    _addon, eng = engine
    light = types.SimpleNamespace(node_tree=_studio_tree(factor=4.0, op="DIVIDE", ies_strength=3.0),
                                  use_nodes=True)
    strength, _ = eng._resolve_light_shader(light)
    assert strength == pytest.approx(3.0 / 4.0)


@pytest.mark.parametrize("op,clamp", [("POWER", False), ("MULTIPLY", True)])
def test_unfoldable_node_is_reported_and_neutral(engine, op, clamp):
    _addon, eng = engine
    light = types.SimpleNamespace(node_tree=_studio_tree(op=op, clamp=clamp), use_nodes=True)
    strength, _ = eng._resolve_light_shader(light)
    assert strength == pytest.approx(1.0)
    assert eng.warnings, "a dropped light-shader node must reach the degradation report"


def test_no_tree_is_neutral(engine):
    _addon, eng = engine
    assert eng._resolve_light_shader(types.SimpleNamespace(node_tree=None)) == (1.0, [1.0, 1.0, 1.0])


def test_tint_emission_dict_modes(engine):
    addon, _eng = engine
    tint = [0.5, 1.0, 2.0]
    assert addon._tint_emission_dict({"mode": "rgb", "color": [1, 1, 1]}, tint)["color"] == tint
    bb = addon._tint_emission_dict({"mode": "blackbody", "temperature_K": 3000, "tint_rgb": [1, 1, 1]}, tint)
    assert bb["tint_rgb"] == tint and bb["temperature_K"] == 3000
    sp = addon._tint_emission_dict({"mode": "measured_spd", "profile_name": "x"}, tint)
    assert sp["mode"] == "composite" and sp["filter_rgb"] == tint


def test_convert_lights_applies_fold_to_spot(engine):
    """End to end through convert_lights: energy x 180, tinted RGB emission."""
    import numpy as np
    _addon, eng = engine
    tree = _studio_tree()
    tree.nodes[0].ies = types.SimpleNamespace(name="studio", as_string=lambda: (
        "IESNA:LM-63-2002\nTILT=NONE\n1 -1 1.0 3 1 1 2 0 0 0\n1 1 1\n0 90 180\n0\n1 1 1\n"))
    light = types.SimpleNamespace(type="SPOT", color=(1.0, 1.0, 1.0), energy=550.0,
                                  shadow_soft_size=0.0, spot_size=math.radians(75.0),
                                  spot_blend=0.55, node_tree=tree, use_nodes=True)
    obj = types.SimpleNamespace(type="LIGHT", data=light, pass_index=0)

    class _M3:
        def __getitem__(self, r):
            return np.eye(3)[r]

        def __matmul__(self, v):
            return types.SimpleNamespace(x=v.x, y=v.y, z=v.z, normalized=lambda: v)

    matrix = types.SimpleNamespace(translation=[0.0, 0.0, 2.0], to_3x3=lambda: _M3())
    calls = []

    class _Rec:
        def add_spot_light_dedicated(self, *a, **k):
            calls.append((a, k))

    eng.convert_lights(types.SimpleNamespace(object_instances=[
        types.SimpleNamespace(object=obj, matrix_world=matrix, is_instance=False)]), _Rec())
    (args, kw), = calls
    emission, intensity = args[4], args[5]
    assert intensity == pytest.approx(550.0 * 180.0)
    assert emission["color"] == pytest.approx([0.95, 0.87, 0.72])
    assert len(kw["light_frame"]) == 9
