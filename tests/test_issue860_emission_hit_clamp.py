"""#860 — an emission hit reached from the FIRST vertex is direct light for the
firefly clamp (Cycles film_write_{surface,volume}_emission / film_write_background
clamp with `bounce - 1`, kernel/film/light_passes.h).

Astroray clamped the BSDF/phase-sampled lamp-hit leg with sample_clamp_indirect
(Blender default 10), so a bright, close area light dimmed first-vertex direct
light — the geometry_zoo backlit volume cubes rendered 0.55-0.8 of Cycles.

Gate: with no genuine indirect light in the scene (black background, one
surface or one medium, volume_bounces 0), sample_clamp_indirect = 10 must leave
the image unchanged vs clamp off (±5 % per-channel mean), CPU and GPU.
"""

from __future__ import annotations

import os
import sys

import numpy as np
import pytest
from runtime_setup import configure_test_imports

configure_test_imports()
sys.path.insert(0, os.path.dirname(__file__))

try:
    import astroray
    AVAILABLE = True
except ImportError:
    AVAILABLE = False

pytestmark = pytest.mark.skipif(not AVAILABLE, reason="astroray not built")

BACKENDS = ["cpu", "gpu"]
W = H = 24
EM = {"mode": "rgb", "color": [1.0, 1.0, 1.0]}


def _gpu_available() -> bool:
    return AVAILABLE and astroray.__features__.get("cuda", False) \
        and astroray.Renderer().gpu_available


def _base(backend, clamp_indirect):
    if backend == "gpu" and not _gpu_available():
        pytest.skip("CUDA GPU not available on this machine")
    r = astroray.Renderer()
    r.set_seed(8600)
    r.set_background_color([0.0, 0.0, 0.0])
    r.set_integrator("path_tracer")
    if backend == "gpu":
        r.set_use_gpu(True)
        r.set_wavelength_range(380.0, 780.0)
        r.set_output_mode("srgb")
    else:
        r.set_use_gpu(False)
    r.set_clamp_direct(0.0)
    r.set_clamp_indirect(clamp_indirect)
    r.setup_camera([0.0, 0.0, 5.0], [0.0, 0.0, 0.0], [0.0, 1.0, 0.0],
                   8.0, 1.0, 0.0, 5.0, W, H)
    return r


def _render(r, spp=256):
    img = np.asarray(r.render(spp, 8, None, False, -1, -1, -1, 0, -1), dtype=np.float64)
    return img.reshape(-1, 3).mean(axis=0)


def _plane(backend, clamp):
    # Rough metal plane at 45 deg reflecting the camera ray up (+y) into a bright
    # lamp overhead: the glossy BSDF leg carries most of the MIS weight.
    r = _base(backend, clamp)
    m = r.create_material("metal", [0.9, 0.9, 0.9], {"roughness": 0.2})
    a, b = 3.0, 3.0 / 2 ** 0.5
    r.add_triangle([-a, -b, b], [a, -b, b], [a, b, -b], m)
    r.add_triangle([-a, -b, b], [a, b, -b], [-a, b, -b], m)
    r.add_area_light_dedicated([0.0, 2.0, 0.0], [1, 0, 0], [0, 0, 1], 2.0, 2.0,
                               "rect", EM, 4000.0)
    return _render(r)


def _backlit_medium(backend, clamp):
    # geometry_zoo-like: forward-scattering cube backlit by a big close lamp.
    r = _base(backend, clamp)
    h = 0.275
    r.add_homogeneous_medium([-h, -h, -h], [h, h, h], density_scale=4.0,
                             color=[0.95, 0.96, 1.0], absorption_color=[1, 1, 1],
                             anisotropy=0.55)
    r.add_area_light_dedicated([0.0, 0.0, -1.25], [1, 0, 0], [0, 1, 0], 3.2, 3.2,
                               "rect", EM, 900.0)
    return _render(r)


@pytest.mark.parametrize("backend", BACKENDS)
@pytest.mark.parametrize("scene", ["plane", "backlit_medium"])
def test_indirect_clamp_leaves_direct_emission_hits_alone(backend, scene):
    fn = _plane if scene == "plane" else _backlit_medium
    off = fn(backend, 0.0)
    on = fn(backend, 10.0)
    ratio = on / np.maximum(off, 1e-9)
    print(f"\n[#860 {scene} {backend}] clamp_off={off.round(5)} clamp_ind10={on.round(5)} "
          f"ratio={ratio.round(4)}")
    assert off.max() > 1e-3, "fixture renders black"
    for c in range(3):
        assert 0.95 <= ratio[c] <= 1.05, (c, ratio, off, on)
