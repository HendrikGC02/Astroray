"""#1201: a Thin Film Thickness / IOR socket linked to a non-foldable node (Noise) must be reported,
not silently read as the 0 nm default. Constant and Math/Value-folded sockets stay honoured and quiet."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_pkg119c_degradation import _Node, _Socket, _engine, _load_blender_addon  # noqa: E402


def _texts(engine):
    r = engine._degradation_report()
    return [f"{f}: {d}" for f, d in r.approximated] + [f"{f}: {d}" for f, d in r.ignored]


def _noise_linked():
    return _Socket(0.0, linked_to=_Node(ntype="TEX_NOISE"), output_name="Fac")


def _value_linked(v):
    src = _Node(ntype="VALUE")
    src.outputs = [_Socket(v)]
    return _Socket(0.0, linked_to=src, output_name="Value")


def _node(kind, film):
    table = {"glass": ("BSDF_GLASS", "ShaderNodeBsdfGlass"),
             "metallic": ("BSDF_METALLIC", "ShaderNodeBsdfMetallic"),
             "principled": ("BSDF_PRINCIPLED", "ShaderNodeBsdfPrincipled")}
    nt, bl = table[kind]
    return _Node(nt, bl, {"Thin Film Thickness": film, "Thin Film IOR": _Socket(1.33),
                          "Normal": _Socket((0, 0, 0))}, distribution="MULTI_GGX",
                 subsurface_method="RANDOM_WALK")


def _run(engine, kind, node):
    if kind == "principled":
        for msg in engine._native_principled_gaps(node, {}):
            engine._warn_shader_fallback("BSDF_PRINCIPLED", msg)
    else:
        engine._report_unhonoured_bsdf_props(node)


@pytest.mark.parametrize("kind", ["glass", "metallic", "principled"])
@pytest.mark.parametrize("native", [True, False])
def test_noise_linked_film_thickness_is_reported(monkeypatch, kind, native):
    engine = _engine(_load_blender_addon(monkeypatch))
    engine._use_native_principled_flag = native
    _run(engine, kind, _node(kind, _noise_linked()))
    assert any("Thin Film Thickness linked to a non-constant node" in t for t in _texts(engine)), _texts(engine)


@pytest.mark.parametrize("kind", ["glass", "metallic", "principled"])
@pytest.mark.parametrize("film", [lambda: _Socket(600.0), lambda: _value_linked(600.0)])
def test_constant_or_folded_film_thickness_is_quiet_and_honoured(monkeypatch, kind, film):
    engine = _engine(_load_blender_addon(monkeypatch))
    node = _node(kind, film())
    _run(engine, kind, node)
    assert not [t for t in _texts(engine) if "Thin Film" in t], _texts(engine)
    assert engine.get_float_input(node, "Thin Film Thickness", 0.0) == 600.0
