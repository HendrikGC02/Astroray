"""#955: Add Shader(A, B) must sum both closures (Cycles svm_node_add_closure:
weights add, are not normalised). It used to keep only the first shader for every
pair except principled+emission / emission+emission, and the principled+emission
pair halved the emission colour.

Reference: a flat wall under a uniform white sky of radiance 1 returns
L = integral f cos dwi = the wall's albedo, so Add(A, B) must render sum of the
two albedos (Diffuse red + Diffuse blue = (0.6+0.1, 0.1+0.1, 0.1+0.6)).
Engine tests run on the CPU path-tracer; addon tests use the real
shader_blending / spec lowering with a recording renderer.
"""
import sys
from pathlib import Path

import numpy as np
import pytest

from runtime_setup import configure_test_imports

configure_test_imports()

try:
    import astroray
    HAVE_ENGINE = True
except ImportError:
    HAVE_ENGINE = False

needs_engine = pytest.mark.skipif(not HAVE_ENGINE, reason="astroray module not available")

N = 24
DIFFUSE = {"roughness": 1.0, "specular_ior_level": 0.0}


def _wall_radiance(make_material, spp=128):
    r = astroray.Renderer()
    r.set_integrator("path_tracer")
    r.set_background_color([1.0, 1.0, 1.0])
    r.set_seed(5)
    r.set_adaptive_sampling(False)
    r.setup_camera([0, 0, 3], [0, 0, 0], [0, 1, 0], 20.0, 1.0, 0.0, 3.0, N, N)
    mat = make_material(r)
    r.add_triangle([-20, -20, 0], [20, -20, 0], [0, 20, 0], mat)
    img = np.asarray(r.render(spp, 4, None, False), dtype=np.float32)
    c = N // 2
    return img[c - 3:c + 3, c - 3:c + 3].reshape(-1, 3).mean(axis=0)


@needs_engine
def test_add_two_diffuse_sums_albedos():
    red, blue = [0.6, 0.1, 0.1], [0.1, 0.1, 0.6]

    def make(r):
        a = r.create_material("principled", red, DIFFUSE)
        b = r.create_material("principled", blue, DIFFUSE)
        return r.create_add_material(a, b)

    got = _wall_radiance(make)
    np.testing.assert_allclose(got, [0.7, 0.2, 0.7], rtol=0.06)


@needs_engine
def test_add_diffuse_and_mirror_sums_delta_lobe():
    # Diffuse 0.3 + mirror (f = 1): L = 0.3 + 1 under a unit sky. Exercises the
    # delta-child branch of the one-sample mixture.
    def make(r):
        a = r.create_material("principled", [0.3, 0.3, 0.3], DIFFUSE)
        b = r.create_material("mirror", [1.0, 1.0, 1.0], {})
        return r.create_add_material(a, b)

    got = _wall_radiance(make, spp=256)
    np.testing.assert_allclose(got, [1.3, 1.3, 1.3], rtol=0.06)
    # Order must not matter (child A is the GPU-upload child, not the CPU one).
    def make_swapped(r):
        a = r.create_material("principled", [0.3, 0.3, 0.3], DIFFUSE)
        b = r.create_material("mirror", [1.0, 1.0, 1.0], {})
        return r.create_add_material(b, a)

    np.testing.assert_allclose(_wall_radiance(make_swapped, spp=256), got, rtol=0.08)


@needs_engine
def test_add_is_not_first_shader_only():
    def first_only(r):
        return r.create_material("principled", [0.6, 0.1, 0.1], DIFFUSE)

    def added(r):
        a = r.create_material("principled", [0.6, 0.1, 0.1], DIFFUSE)
        b = r.create_material("principled", [0.1, 0.1, 0.6], DIFFUSE)
        return r.create_add_material(a, b)

    assert _wall_radiance(added)[2] > 3.0 * _wall_radiance(first_only)[2]


# ---- addon spec lowering ---------------------------------------------------------
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "blender_addon"))
import shader_blending as sb  # noqa: E402


def _diffuse(color):
    return {"kind": "principled", "base_color": color,
            "params": {"metallic": 0.0, "roughness": 0.0, "specular_ior_level": 0.0, "specular": 0.0}}


def _glossy(color):
    return {"kind": "principled", "base_color": color, "params": {"metallic": 1.0, "roughness": 0.3}}


def test_spec_add_diffuse_diffuse_folds_to_summed_albedo():
    out = sb.add_shader_specs(_diffuse([0.6, 0.1, 0.1]), _diffuse([0.1, 0.1, 0.6]))
    assert out["kind"] == "principled"
    np.testing.assert_allclose(out["base_color"], [0.7, 0.2, 0.7])


def test_spec_add_diffuse_glossy_is_an_add_node_not_first_only():
    a, b = _diffuse([0.6, 0.1, 0.1]), _glossy([0.9, 0.9, 0.9])
    out = sb.add_shader_specs(a, b)
    assert out["kind"] == "add" and out["a"] == a and out["b"] == b


def test_spec_add_emission_keeps_full_emission_colour():
    # Cycles: Principled + Emission = surface + color * strength. The old fold
    # lerped the emission colour 50% towards black, halving it.
    out = sb.add_shader_specs(
        _diffuse([0.5, 0.5, 0.5]),
        {"kind": "emission", "base_color": [1.0, 0.5, 0.0], "emission_strength": 4.0})
    e = np.asarray(out["emission_color"]) * out["emission_strength"]
    np.testing.assert_allclose(e, [4.0, 2.0, 0.0], rtol=1e-6)
    out2 = sb.add_shader_specs(
        {"kind": "emission", "base_color": [1.0, 0.5, 0.0], "emission_strength": 4.0},
        _diffuse([0.5, 0.5, 0.5]))
    np.testing.assert_allclose(np.asarray(out2["emission_color"]) * out2["emission_strength"],
                               [4.0, 2.0, 0.0], rtol=1e-6)


def test_spec_add_emission_onto_emissive_principled_sums_radiance():
    p = _diffuse([0.5, 0.5, 0.5])
    p["emission_color"], p["emission_strength"] = [0.0, 1.0, 0.0], 2.0
    out = sb.add_shader_specs(p, {"kind": "emission", "base_color": [1.0, 0.0, 0.0],
                                  "emission_strength": 3.0})
    e = np.asarray(out["emission_color"]) * out["emission_strength"]
    np.testing.assert_allclose(e, [3.0, 2.0, 0.0], rtol=1e-6)


def test_spec_add_textured_emission_is_not_folded_into_principled():
    # The Principled emission term has no texture slot: keep the textured Emission child.
    tex = {"kind": "emission", "base_color": [1, 1, 1], "emission_strength": 2.0,
           "emission_color_texture": "chk"}
    for a, b in ((_diffuse([0.5] * 3), tex), (tex, _diffuse([0.5] * 3))):
        out = sb.add_shader_specs(a, b)
        assert out["kind"] == "add"
        assert any(c.get("emission_color_texture") == "chk" for c in (out["a"], out["b"]))


def test_spec_add_diffuse_sum_above_one_is_not_folded():
    # Albedo > 1 would be clamped by the spectral upsampler; keep two closures.
    out = sb.add_shader_specs(_diffuse([0.8, 0.8, 0.8]), _diffuse([0.8, 0.8, 0.8]))
    assert out["kind"] == "add"


# ---- addon lowering end to end (real engine, recording nodes) --------------------
def _addon_wall(monkeypatch, out_node, spp=128):
    from test_pkg293_gpu_lobe_programs import _addon_engine, _Recorder
    holder = {}

    def make(r):
        eng = _addon_engine(monkeypatch, True)
        spec = eng._shader_spec_from_node(out_node, _Recorder(r), None)
        holder["lines"] = eng._degradation_report().messages()
        holder["kind"] = spec["kind"]
        return eng._create_material_from_shader_spec(spec, r)

    return _wall_radiance(make, spp=spp), holder


def _bsdf(ntype, color, **extra):
    from test_pkg293_gpu_lobe_programs import _node
    from test_issue818_procedural_opvm import Sock
    socks = [Sock('Color', list(color) + [1.0]), Sock('Roughness', extra.pop('roughness', 0.0))]
    return _node(ntype, ntype, socks)


def _add(a, b):
    from test_pkg293_gpu_lobe_programs import _node
    from test_issue818_procedural_opvm import Sock, Link
    return _node('ADD_SHADER', 'Add', [Sock('Shader', None, Link(a, 'BSDF')),
                                       Sock('Shader_001', None, Link(b, 'BSDF'))])


def test_addon_add_diffuse_red_plus_diffuse_blue_matches_sum(monkeypatch):
    node = _add(_bsdf('BSDF_DIFFUSE', [0.6, 0.1, 0.1]), _bsdf('BSDF_DIFFUSE', [0.1, 0.1, 0.6]))
    got, info = _addon_wall(monkeypatch, node)
    assert info["kind"] == "principled", "pure diffuse pair should fold exactly"
    assert not any("ADD_SHADER" in m for m in info["lines"]), info["lines"]
    np.testing.assert_allclose(got, [0.7, 0.2, 0.7], rtol=0.06)


def test_addon_add_diffuse_plus_glossy_sums_on_cpu_and_reports_gpu(monkeypatch):
    diffuse = _bsdf('BSDF_DIFFUSE', [0.3, 0.3, 0.3])
    glossy = _bsdf('BSDF_GLOSSY', [0.9, 0.9, 0.9], roughness=0.2)
    got_add, info = _addon_wall(monkeypatch, _add(diffuse, glossy))
    got_diffuse, _ = _addon_wall(monkeypatch, diffuse)
    got_glossy, _ = _addon_wall(monkeypatch, glossy)
    assert info["kind"] == "add"
    assert any("ADD_SHADER" in m and "GPU" in m for m in info["lines"]), info["lines"]
    np.testing.assert_allclose(got_add, got_diffuse + got_glossy, rtol=0.08)
    assert (got_add > got_diffuse * 1.5).all() and (got_add > got_glossy * 1.2).all()


def test_addon_mix_shader_unsupported_pair_is_reported(monkeypatch):
    from test_pkg293_gpu_lobe_programs import _node
    from test_issue818_procedural_opvm import Sock, Link

    def emission(c):
        return _node('EMISSION', 'Emission', [Sock('Color', c + [1.0]), Sock('Strength', 1.0)])

    mix = _node('MIX_SHADER', 'Mix', [Sock('Fac', 0.3),
                                      Sock('Shader', None, Link(emission([1.0, 0.0, 0.0]), 'Emission')),
                                      Sock('Shader_001', None, Link(emission([0.0, 0.0, 1.0]), 'Emission'))])
    from test_pkg293_gpu_lobe_programs import _addon_engine, _Recorder
    eng = _addon_engine(monkeypatch, True)
    eng._shader_spec_from_node(mix, _Recorder(astroray.Renderer()), None)
    lines = eng._degradation_report().messages()
    assert any("MIX_SHADER" in m and "dominant shader" in m for m in lines), lines


# ---- transparent shadows: Cycles sums the closure weights ------------------------
def _shadowed_floor(make_blocker, spp=64):
    """Top-down view of a lit floor; a 2x2 blocker 5 above sits outside the frame but its
    sun shadow (45 deg) lands on the view centre."""
    r = astroray.Renderer()
    r.set_integrator("path_tracer")
    r.set_background_color([0.0, 0.0, 0.0])
    r.set_seed(3)
    r.set_adaptive_sampling(False)
    r.setup_camera([0, 10, 0], [0, 0, 0], [0, 0, -1], 10.0, 1.0, 0.0, 10.0, N, N)
    floor = r.create_material("principled", [0.8] * 3, DIFFUSE)
    e = 30.0
    r.add_triangle([-e, 0, -e], [e, 0, e], [e, 0, -e], floor)
    r.add_triangle([-e, 0, -e], [-e, 0, e], [e, 0, e], floor)
    r.add_sun_light_dedicated([0.7071, -0.7071, 0.0], 0.01, {"mode": "rgb", "color": [1, 1, 1]}, 5.0)
    if make_blocker is not None:
        m = make_blocker(r)
        a, b, c, d = [-6, 5, -1], [-4, 5, -1], [-4, 5, 1], [-6, 5, 1]
        r.add_triangle(a, b, c, m)
        r.add_triangle(a, c, d, m)
    img = np.asarray(r.render(spp, 4, None, False), dtype=np.float32)
    c0 = N // 2
    return float(img[c0 - 4:c0 + 4, c0 - 4:c0 + 4].mean())


def test_add_shader_transparent_shadow_sums_alpha():
    lit = _shadowed_floor(None)
    assert lit > 0.05
    opaque = _shadowed_floor(lambda r: r.create_material("principled", [0.5] * 3, DIFFUSE))
    assert opaque < 0.1 * lit, "geometry check: an opaque blocker must shadow the view centre"

    def add_clear_plus_emission(r):
        clear = r.create_material("principled", [0.5] * 3, dict(DIFFUSE, alpha=0.0))
        glow = r.create_material("light", [1.0, 1.0, 1.0], {"intensity": 0.0})
        return r.create_add_material(clear, glow)

    # alpha_A + alpha_B - 1 = 0: fully transparent; the old max(alpha) = 1 blocked the sun.
    assert _shadowed_floor(add_clear_plus_emission) > 0.9 * lit
