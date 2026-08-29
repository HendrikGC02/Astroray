#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""pkg223b — Bump node (height-texture surface-gradient normal perturbation).

The Blender Bump node was a silent no-op; pkg223b wires a height texture through
Cycles' svm_node_set_bump surface-gradient formula (Mikkelsen 2010) on the
UV-aligned tangent frame, CPU + GPU wavefront at parity, sharing pkg223's
HasNormalPerturb axis. A material with a `bump_map_texture` param is a
NormalMappedPlugin carrying a height texture (blender_module create_material).

Gates: bump render differs from flat (relief applied, not dropped), Strength
scales it monotonically (0 ~= flat), and CPU/GPU agree.
"""
import math
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(__file__))
from base_helpers import create_renderer, setup_camera, render_image  # noqa: E402
import astroray  # noqa: E402


def _has_cuda(r):
    return bool(astroray.__features__.get("cuda", False)) and bool(getattr(r, "gpu_available", False))


def _norm(v):
    v = np.asarray(v, np.float32)
    return (v / np.linalg.norm(v)).tolist()


def _ramp_height(n=32):
    """A smooth horizontal height ramp (height increases along +U): grayscale
    column/n. dHeight/dU is constant, so the bump tilts the normal uniformly
    toward -U — a clean, MC-robust relief signal."""
    col = (np.arange(n, dtype=np.float32) / (n - 1))
    img = np.repeat(col[None, :, None], n, axis=0)      # (n,n,1)
    return np.repeat(img, 3, axis=2).astype(np.float32)  # (n,n,3)


def _build(r, distance=0.0, strength=1.0):
    r.set_background_color([0.0, 0.0, 0.0])
    params = {}
    if distance > 0.0:
        r.load_texture("pkg223b_h", _ramp_height(32), 32, 32, "UV")
        params["bump_map_texture"] = "pkg223b_h"
        params["bump_distance"] = float(distance)
        params["bump_strength"] = float(strength)
    mat = r.create_material("lambertian", [0.8, 0.8, 0.8], params)
    A, B = [-1, -1, 0], [1, -1, 0]
    C, D = [1, 1, 0], [-1, 1, 0]
    n = [0, 0, 1]
    r.add_triangle_layers(A, B, C, mat, {"UVMap": [[0, 0], [1, 0], [1, 1]]}, n, n, n)
    r.add_triangle_layers(A, C, D, mat, {"UVMap": [[0, 0], [1, 1], [0, 1]]}, n, n, n)
    # Grazing sun from +x (maps to +U), so a bump tilt along U swings N.L hard.
    ang = 0.02
    r.add_sun_light_dedicated(_norm([-1.0, 0.0, -0.4]), ang,
                              {"mode": "rgb", "color": [1.0, 1.0, 1.0]}, 3.0)
    setup_camera(r, look_from=[0, 0, 3], look_at=[0, 0, 0], vup=[0, 1, 0],
                 vfov=45, width=64, height=64)


def _render(distance=0.0, strength=1.0, use_gpu=False, samples=96):
    r = create_renderer()
    if use_gpu:
        if not _has_cuda(r):
            pytest.skip("No CUDA GPU")
        r.set_use_gpu(True)
    _build(r, distance=distance, strength=strength)
    return np.asarray(render_image(r, samples=samples, max_depth=2, apply_gamma=False),
                      dtype=np.float32)


def _mean(img):
    return float(img.mean())


def test_cpu_bump_visible_relief():
    """Bump at Strength 1 must differ substantially from Strength 0 (which is a
    flat shading normal). Both are the SAME wrapped material with matched RNG —
    perturbNormal draws no RNG — so the difference is purely the applied relief,
    not independent MC noise."""
    s1 = _render(distance=0.5, strength=1.0, use_gpu=False)
    s0 = _render(distance=0.5, strength=0.0, use_gpu=False)
    assert _mean(s0) > 0.02, f"unbumped too dark to gate ({_mean(s0):.4f})"
    d = float(np.abs(s1 - s0).mean())
    assert d > 0.02, f"bump produced no visible relief on CPU (mean|d|={d:.4f})"


def test_cpu_bump_strength_monotone():
    """Departure from the flat (Strength 0) normal grows with Strength."""
    s0 = _render(distance=0.5, strength=0.0)
    sh = _render(distance=0.5, strength=0.5)
    s1 = _render(distance=0.5, strength=1.0)
    d_half = float(np.abs(sh - s0).mean())
    d_full = float(np.abs(s1 - s0).mean())
    assert d_full > d_half > 1e-3, \
        f"Strength not monotone: half={d_half:.4g} full={d_full:.4g}"


@pytest.mark.skipif(not bool(astroray.__features__.get("cuda", False)),
                    reason="needs CUDA build")
def test_gpu_bump_visible_relief():
    s1 = _render(distance=0.5, strength=1.0, use_gpu=True)
    s0 = _render(distance=0.5, strength=0.0, use_gpu=True)
    assert _mean(s0) > 0.02, f"unbumped too dark ({_mean(s0):.4f})"
    d = float(np.abs(s1 - s0).mean())
    assert d > 0.02, f"bump produced no visible relief on GPU (mean|d|={d:.4f})"


@pytest.mark.skipif(not bool(astroray.__features__.get("cuda", False)),
                    reason="needs CUDA build")
def test_cpu_gpu_bump_parity():
    """CPU and GPU bump renders agree within a per-channel mean-ratio band. A
    gentle Distance keeps the tilted quad from turning fully away from the grazing
    sun (which would darken it below a useful gate level)."""
    cpu = _render(distance=0.2, strength=1.0, use_gpu=False, samples=128)
    gpu = _render(distance=0.2, strength=1.0, use_gpu=True, samples=128)
    cm, gm = _mean(cpu), _mean(gpu)
    assert gm > 0.01 and cm > 0.01, f"renders too dark (cpu={cm:.4f} gpu={gm:.4f})"
    ratio = gm / cm
    assert 0.9 < ratio < 1.1, f"CPU/GPU bump mean ratio out of band: {ratio:.4f}"
