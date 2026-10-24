"""#1165: bounce caps follow the Cycles convention (max_bounces = N allows N+1 scatters).

Cycles v5.2.0 (Apache-2.0):
- ``intern/cycles/scene/integrator.cpp:222-228`` hands the kernel ``max_bounce + 1`` and
  ``max_{diffuse,glossy,transmission,volume}_bounce + 1`` ("so that a bounce of 0 indicates no global
  illumination, only direct illumination"); ``transparent_max_bounce`` is NOT incremented (:232).
- ``kernel/integrator/path_state.h:143-146`` (total) and ``:177-208`` (per type): the scatter that makes
  the count reach the kernel limit sets ``PATH_RAY_TERMINATE_AFTER_TRANSPARENT``; its continuation ray is
  still traced, and the NEXT surface stores no BSDF closures (``surface_shader.h:1265-1268``) so it adds its
  emission only and ends the path (``shade_surface.h:497-499``).

So with max_bounces = N the camera path scatters at vertices 1..N+1 and takes emission at vertices
1..N+2. Two analytic consequences, both checked below on CPU and GPU:

- Closed box, Lambertian albedo rho + emission Le on every wall, camera inside (white furnace with
  emitting walls): L(N) = Le * sum_{j=0}^{N+1} rho^j. rho = 0.5, Le = 1: 1.5, 1.75, 1.875, 1.9375 for
  N = 0..3, 2.0 uncapped. The same holds for diffuse_bounces = N with an unlimited total (``:183-185``).
  Measured in Blender 5.2 Cycles (Diffuse BSDF 0.5 + Emission 1, 256 spp): 1.5000 / 1.7502 / 1.8752 /
  1.9377 for both the total and the diffuse cap. Before #1165 Astroray rendered 0.0 / 1.18 / 1.58 / 1.79.
- pkg325 glass panes (white world): a camera ray crossing k interfaces reaches the sky iff N >= k-1
  (the k-th scatter's continuation is traced). Same for transmission_bounces with an unlimited total.
  Before #1165 Astroray needed N >= k+1 (total) and N >= k (transmission).
"""
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from benchmarks.showcase.spectral.pkg325 import scene_geometry as G

W, H = 320, 240
DEAD_BELOW = 0.25
PANES = (("stack1", 2), ("stack2", 4), ("stack3", 6))   # ROI, glass interfaces crossed (pkg325)


def _renderer(backend):
    import runtime_setup
    runtime_setup.configure_test_imports()
    import astroray
    r = astroray.Renderer()
    if backend == "gpu":
        try:
            r.set_use_gpu(True)
        except Exception as e:  # noqa: BLE001 - CPU-only build
            pytest.skip(f"GPU unavailable: {e}")
        if not getattr(r, "gpu_available", False):
            pytest.skip("gpu_available is False")
        r.set_use_gpu(False)
    return r


def _cycles_box(n_cap, rho=0.5, le=1.0):
    return le * sum(rho ** j for j in range(n_cap + 2))


# --------------------------------------------------------------------------- #
# closed emitting Lambertian box: the bounce count
# --------------------------------------------------------------------------- #

def _box_mean(backend, total, diffuse=-1, spp=64):
    r = _renderer(backend)
    lam = r.create_material("lambertian", [0.5, 0.5, 0.5], {})
    emit = r.create_material("emissive", [1.0, 1.0, 1.0], {})
    mat = r.create_add_material(lam, emit)
    c = [np.array([x, y, z], float) for x in (-1, 1) for y in (-1, 1) for z in (-1, 1)]
    for a, b, cc, d in ((0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)):
        for tri in ((a, b, cc), (a, cc, d)):
            v0, v1, v2 = (c[i] for i in tri)
            if np.dot(np.cross(v1 - v0, v2 - v0), -(v0 + v1 + v2)) < 0:   # wind inward
                v1, v2 = v2, v1
            r.add_triangle(v0.tolist(), v1.tolist(), v2.tolist(), mat)
    r.set_background_color([0.0, 0.0, 0.0])
    r.setup_camera([0, 0, 0], [0, 0, -1], [0, 1, 0], 60.0, 1.0, 0.0, 6.0, 32, 32)
    r.set_integrator("path_tracer")
    r.set_seed(1165)
    r.set_adaptive_sampling(False)
    r.set_use_gpu(backend == "gpu")
    img = np.asarray(r.render(spp, total, None, False, diffuse, -1, -1, -1, -1), dtype=np.float64)
    return float(img.mean())


@pytest.mark.parametrize("backend", ["cpu", "gpu"])
def test_total_cap_bounce_count_matches_cycles(backend):
    got = {n: _box_mean(backend, n) for n in (0, 1, 2, 3, 64)}
    for n, mean in got.items():
        assert abs(mean - _cycles_box(n)) < 0.01, (backend, n, got)


@pytest.mark.parametrize("backend", ["cpu", "gpu"])
def test_diffuse_cap_bounce_count_matches_cycles(backend):
    got = {n: _box_mean(backend, 64, diffuse=n) for n in (0, 1, 2, 3)}
    for n, mean in got.items():
        assert abs(mean - _cycles_box(n)) < 0.01, (backend, n, got)


# --------------------------------------------------------------------------- #
# pkg325 panes: k interfaces need cap k-1
# --------------------------------------------------------------------------- #

def _pane_rois(backend, total, transmission):
    from benchmarks.showcase.spectral.pkg325 import engine_scene as E
    r = _renderer(backend)
    E.build(r, W, H)
    img = E.render(r, backend, 16, total, seed=1165, diffuse_bounces=-1, glossy_bounces=-1,
                   transmission_bounces=transmission, volume_bounces=-1, transparent_bounces=-1)
    out = {}
    for name, _ in PANES:
        x0, y0, x1, y1 = G.rois(W, H)[name]
        lum = img[y0:y1, x0:x1].mean(-1)
        out[name] = (float((lum < DEAD_BELOW).mean()), float(lum.mean()))
    return out


def _assert_k_minus_1(backend, render):
    stats = {cap: render(cap) for cap in range(0, 6)}
    for name, k in PANES:
        dead, mean = stats[k - 1][name]
        assert dead < 0.005 and mean > 0.85, (backend, name, k, "cap k-1", dead, mean)
        _, mean_below = stats[k - 2][name] if k >= 2 else (None, 0.0)
        assert mean_below < DEAD_BELOW, (backend, name, k, "cap k-2", mean_below)


@pytest.mark.parametrize("backend", ["cpu", "gpu"])
def test_total_cap_k_interfaces_need_k_minus_1(backend):
    _assert_k_minus_1(backend, lambda cap: _pane_rois(backend, cap, -1))


@pytest.mark.parametrize("backend", ["cpu", "gpu"])
def test_transmission_cap_k_interfaces_need_k_minus_1(backend):
    _assert_k_minus_1(backend, lambda cap: _pane_rois(backend, 64, cap))
