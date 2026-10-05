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

from test_issue880_standalone_bsdf_texture import (  # noqa: E402
    _RecordingRenderer, _load_blender_addon, _translucent_node)

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
