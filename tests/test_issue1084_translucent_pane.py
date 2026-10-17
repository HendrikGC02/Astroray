"""#1084 - a Translucent BSDF pane rendered pure black on the GPU (CPU 0.013) in
the gate-(c) materials_hall corpus scene, while Cycles shows it lit from behind.

Root cause, two layers:
  1. The addon lowered Blender's Translucent BSDF to a rough-transmission
     Principled with ior = 1.0. Cycles' Translucent is a pure back-hemisphere
     Lambert (-N) lobe; the engine already has that lobe (thin-subsurface split,
     g = +1: principled.cpp "Thin subsurface" / gpu_materials.h GPR_TRANSLUCENT).
  2. Rough transmission at eta == 1 EXACTLY has wi = -wo, so the refraction
     half-vector (wi*eta + wo) is the zero vector and the lobe evaluates to 0
     (GPU: exactly 0, CPU: ~0.4 % of the transmitted radiance). eta = 1.0001 is
     within 0.5 % of the delta ior = 1 pass-through.

Scene: a pane at y = 0 (normal -y, toward the camera at y = -5) with a very large
emitter behind it (y = 2). For a white pane the through-radiance of a perfect
Lambert-transmission lobe equals the emitter radiance (cosine-weighted integral
of a ~full-hemisphere emitter), so the reference is the same scene WITHOUT the
pane: no invented constants.
"""

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parent))
from runtime_setup import configure_test_imports  # noqa: E402

configure_test_imports()
astroray = pytest.importorskip("astroray")

import importlib.util  # noqa: E402

from test_issue880_standalone_bsdf_texture import (  # noqa: E402
    _Node, _RecordingRenderer, _Socket, _diffuse_node, _glass_node, _load_blender_addon,
    _translucent_node)

W = 24
SPP = 96


def _has_cuda_gpu():
    r = astroray.Renderer()
    return bool(astroray.__features__.get("cuda", False)) and bool(getattr(r, "gpu_available", False))


def _render(params, gpu, pane=True, color=(1.0, 1.0, 1.0), emitter_half=200.0):
    r = astroray.Renderer()
    r.set_integrator("path_tracer")
    r.set_use_gpu(gpu)
    r.set_background_color([0.0, 0.0, 0.0])
    if pane:
        mid = r.create_material("principled", list(color), params)
        a, b, c, d = [-1, 0, -1], [1, 0, -1], [1, 0, 1], [-1, 0, 1]
        r.add_triangle(a, b, c, mid)
        r.add_triangle(a, c, d, mid)
    lm = r.create_material("light", [1, 1, 1], {"intensity": 4.0})
    e = emitter_half  # 200 >> pane distance: the pane sees ~the full hemisphere
    r.add_triangle([-e, 2, -e], [e, 2, -e], [e, 2, e], lm)
    r.add_triangle([-e, 2, -e], [e, 2, e], [-e, 2, e], lm)
    r.setup_camera([0, -5, 0], [0, 0, 0], [0, 0, 1], 8.0, 1.0, 0.0, 5.0, W, W)
    r.set_seed(7)
    img = np.asarray(r.render(SPP, 8, None, False), dtype=np.float32).reshape(W, W, 3)
    return float(img[W // 4: 3 * W // 4, W // 4: 3 * W // 4].mean())


def _translucent_params(monkeypatch):
    addon = _load_blender_addon(monkeypatch)
    spec = addon.CustomRaytracerRenderEngine()._shader_spec_from_node(
        _translucent_node(), _RecordingRenderer(), node_tree=None)
    assert spec is not None and spec["kind"] == "principled"
    return dict(spec["params"])


def test_translucent_spec_uses_the_back_hemisphere_lobe(monkeypatch):
    p = _translucent_params(monkeypatch)
    assert p.get("thin_wall") == 1.0
    assert p.get("subsurface_weight") == 1.0
    assert p.get("subsurface_anisotropy") == 1.0  # all weight on the translucent lobe
    assert not p.get("transmission") and not p.get("transmission_weight")


def test_translucent_pane_transmits_back_light_cpu(monkeypatch):
    p = _translucent_params(monkeypatch)
    ref = _render(p, gpu=False, pane=False)
    got = _render(p, gpu=False)
    assert ref > 1.0
    assert 0.9 <= got / ref <= 1.05, f"white translucent pane / emitter = {got / ref:.4f}"


def test_rough_transmission_at_eta_one_is_not_black_cpu():
    p = {"transmission": 1.0, "roughness": 1.0, "ior": 1.0}
    # Small emitter (the camera sees it through the pane): only the pass-through
    # direction reaches it, so a zero half-vector shows up as ~0 (CPU 0.4 %, GPU 0).
    ref = _render(p, gpu=False, pane=False, emitter_half=2.0)
    got = _render(p, gpu=False, emitter_half=2.0)
    assert got / ref >= 0.9, f"rough transmission ior=1.0 / emitter = {got / ref:.4f} (black)"


@pytest.mark.gpu
def test_translucent_pane_gpu_matches_cpu(monkeypatch):
    if not _has_cuda_gpu():
        pytest.skip("No CUDA GPU - #1084 GPU leg runs on the RTX box.")
    p = _translucent_params(monkeypatch)
    cpu = _render(p, gpu=False, color=(0.9, 0.75, 0.35))
    gpu = _render(p, gpu=True, color=(0.9, 0.75, 0.35))
    assert cpu > 0.5
    assert abs(gpu / cpu - 1.0) < 0.05, f"cpu={cpu:.4f} gpu={gpu:.4f}"


@pytest.mark.gpu
def test_rough_transmission_at_eta_one_is_not_black_gpu():
    if not _has_cuda_gpu():
        pytest.skip("No CUDA GPU - #1084 GPU leg runs on the RTX box.")
    p = {"transmission": 1.0, "roughness": 1.0, "ior": 1.0}
    ref = _render(p, gpu=True, pane=False, emitter_half=2.0)
    got = _render(p, gpu=True, emitter_half=2.0)
    assert got / ref >= 0.9, f"GPU rough transmission ior=1.0 / emitter = {got / ref:.4f} (black)"


# ---- Opus parity review fixes (C1/M1/M2/N1/N3) ---------------------------------------

def _real_blending():
    path = Path(__file__).parent.parent / "blender_addon" / "shader_blending.py"
    spec = importlib.util.spec_from_file_location("shader_blending_real_1084", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _mix_material(monkeypatch, fac, node_a, node_b):
    """Mix Shader(fac, node_a, node_b) through the addon's real translation + material
    creation (native Principled route). Returns (engine, base_color, params)."""
    addon = _load_blender_addon(monkeypatch)
    addon.blend_shader_specs = _real_blending().blend_shader_specs  # the loader stubs it
    eng = addon.CustomRaytracerRenderEngine()
    mix = _Node("MIX_SHADER", inputs={"Fac": _Socket(default=fac),
                                      "Shader": _Socket(linked_to=node_a),
                                      "Shader_001": _Socket(linked_to=node_b)})
    rr = _RecordingRenderer()
    spec = eng._shader_spec_from_node(mix, rr, node_tree=None)
    eng._create_material_from_shader_spec(spec, rr)
    _typ, color, params = rr.created_materials[-1]
    return eng, color, params


def _white(node):
    node.inputs["Color"].default_value = (1.0, 1.0, 1.0, 1.0)
    return node


def test_translucent_spec_has_no_specular_layer(monkeypatch):  # N1
    assert _translucent_params(monkeypatch).get("specular_ior_level") == 0.0


@pytest.mark.parametrize("fac", [0.3, 0.7])
def test_mix_diffuse_translucent_is_the_cycles_weighting_cpu(monkeypatch, fac):  # M1
    """Mix(Diffuse, Translucent, fac): Translucent carries fac of the light (Cycles
    (1-fac)*Diffuse + fac*Translucent); the pane under a full-hemisphere emitter transmits
    fac * emitter. The generic lerp gave 0 at fac 0.3 and 0.656 at fac 0.7 (thin_wall is
    thresholded at 0.5)."""
    _eng, color, params = _mix_material(
        monkeypatch, fac, _white(_diffuse_node()), _white(_translucent_node()))
    assert params["thin_wall"] == 1.0 and params["subsurface_weight"] == 1.0
    ref = _render(params, gpu=False, pane=False)
    got = _render(params, gpu=False, color=color)
    assert abs(got / ref - fac) < 0.04, f"fac {fac}: pane/emitter = {got / ref:.4f}"


def test_mix_translucent_degradation_is_reported(monkeypatch):  # M1
    eng, _c, _p = _mix_material(monkeypatch, 0.5, _glass_node(), _translucent_node())
    notes = [d for _f, d in eng._degradation_report().approximated if "Translucent" in d]
    assert notes, eng._degradation_report().approximated
    dn = _diffuse_node()   # 0.8 grey vs a white Translucent: colours blended, reported
    eng, _c, _p = _mix_material(monkeypatch, 0.5, dn, _white(_translucent_node()))
    assert any("different colours" in d for _f, d in eng._degradation_report().approximated)
    eng, _c, _p = _mix_material(monkeypatch, 0.5, _white(_diffuse_node()), _white(_translucent_node()))
    assert not any("Translucent" in d for _f, d in eng._degradation_report().approximated)


def _sample_dev(ior, rough, n=2000):
    r = astroray.Renderer()
    wo = np.array([0.3, 0.8, 0.2])
    wo /= np.linalg.norm(wo)
    m = r.create_material("principled", [1, 1, 1],
                          {"transmission": 1.0, "roughness": rough, "ior": ior})
    u = np.random.default_rng(1).random((2, n))
    wi, pdf = r.debug_bsdf_sample_batch(m, list(wo), u)
    wi, pdf = np.asarray(wi), np.asarray(pdf)
    ok = pdf > 0
    # The singular band is a delta pass-through: every sample is valid. A rough
    # dielectric under the Cycles MULTI_GGX default (owner 2026-10-06) LOSES its
    # wrong-side microfacet directions (bsdf_microfacet_sample LABEL_NONE; 1/E restores
    # the energy), so it is checked on its valid samples. The former ok.all() held only
    # for the pkg265 walk, which never loses a sample.
    if abs(ior - 1.0) < 1e-4:
        assert ok.all()
    else:
        assert ok.mean() > 0.8, ok.mean()
    return np.linalg.norm(wi + wo, axis=1)[ok]


@pytest.mark.parametrize("rough", [1.0, 0.5])
def test_rough_transmission_at_eta_one_is_a_delta_passthrough(rough):  # M2
    """Cycles bsdf_microfacet_sample: |eta-1| < 1e-4 is singular (pure pass-through),
    wi = -wo exactly. The old 1.0001 nudge left a peaked lobe (|wi+wo| up to 2e-3)."""
    assert _sample_dev(1.0, rough).max() < 1e-6
    assert _sample_dev(1.00005, rough).max() < 1e-4   # still inside the singular band
    assert _sample_dev(1.2, rough).mean() > 0.05      # a real rough dielectric still scatters


def test_generated_emitter_bake_is_reported(monkeypatch):  # N3
    addon = _load_blender_addon(monkeypatch)
    eng = addon.CustomRaytracerRenderEngine()
    tex = _Node("TEX_NOISE", inputs={"Vector": _Socket(), "Scale": _Socket(default=5.0),
                                      "Detail": _Socket(default=2.0),
                                      "Roughness": _Socket(default=0.5)}, name="Noise")
    emit = _Node("EMISSION", inputs={"Color": _Socket(linked_to=tex),
                                      "Strength": _Socket(default=1.0)})
    eng._shader_spec_from_node(emit, _RecordingRenderer(), node_tree=None)
    assert any("Generated coordinates" in d for _f, d in eng._degradation_report().approximated),         eng._degradation_report().approximated
