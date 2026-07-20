#!/usr/bin/env python
"""pkg89-GPU / GAP 1 — dedicated lights are uploaded to the GPU and sampled by
the megakernel NEE with the SAME pdfs + emission as the CPU sampler.

Before this fix, any GPU render of a scene lit only by dedicated lights (Blender
POINT/SPOT/SUN/AREA lamps routed through astroray::Light) rendered BLACK: the GPU
light arrays carried only emissive-geometry lights, so numLights==0 skipped NEE
entirely (pkg86-B deferred the dedicated-light GPU port). This test is the
acceptance gate: for a gray floor lit by a dedicated light, the GPU image must go
from BLACK to PARITY with the CPU image (mean-ratio ~1, high correlation).

The emission is exact for RGB-mode lights (the device RGBIlluminant upsample
reproduces the CPU RGBIlluminantSpectrum sample-for-sample). We gate on RGB-mode
lights for that reason; blackbody-mode spectral parity is a documented follow-up
(and is entangled with the separate pkg89 CPU energy-scale audit, GAP 2).

GPU-gated: skips when CUDA is absent (CI has no GPU); /verify runs on RTX.
"""

from __future__ import annotations

import numpy as np
import pytest

from runtime_setup import configure_test_imports

configure_test_imports()

try:
    import astroray
    AVAILABLE = True
except ImportError:
    AVAILABLE = False

pytestmark = pytest.mark.skipif(not AVAILABLE, reason="astroray not built")

if AVAILABLE and not astroray.__features__.get("cuda", False):
    pytest.skip("CUDA feature not in this build — pkg89-GPU needs CUDA; "
                "/verify runs this on the RTX box.", allow_module_level=True)

WIDTH = HEIGHT = 96
SPP = 128
MAX_DEPTH = 3
SEED = 7


def _gpu_available() -> bool:
    return astroray.Renderer().gpu_available


def _gray_floor(r):
    m = r.create_material('lambertian', [0.5, 0.5, 0.5], {})
    r.add_triangle([-50, 0, -50], [50, 0, -50], [50, 0, 50], m)
    r.add_triangle([-50, 0, -50], [50, 0, 50], [-50, 0, 50], m)


def _cam_down(r, h=3.0):
    r.set_background_color([0.0, 0.0, 0.0])
    r.setup_camera(look_from=[0, h, 0.0001], look_at=[0, 0, 0], vup=[0, 0, -1],
                   vfov=30.0, aspect_ratio=1.0, aperture=0.0, focus_dist=h,
                   width=WIDTH, height=HEIGHT)


def _render(r, use_gpu):
    r.set_use_gpu(use_gpu)
    r.set_seed(SEED)
    # applyGamma=False -> linear radiance, for a clean radiometric compare.
    return np.asarray(r.render(SPP, MAX_DEPTH, None, False))


def _build_area(use_gpu):
    r = astroray.Renderer()
    _cam_down(r)
    _gray_floor(r)
    r.add_area_light_dedicated([0, 3, 0], [1, 0, 0], [0, 0, 1], 3.0, 3.0,
                               'RECTANGLE', {'mode': 'rgb', 'color': [1, 1, 1]},
                               300.0, 1.57)
    return r


def _build_point(use_gpu):
    r = astroray.Renderer()
    _cam_down(r)
    _gray_floor(r)
    r.add_point_light(position=[0, 3, 0], emission={'mode': 'rgb', 'color': [1, 1, 1]},
                      intensity=800.0, radius=0.0)
    return r


def _parity(builder, label):
    if not _gpu_available():
        pytest.skip("no GPU on this machine")
    gpu = _render(builder(True), True)
    cpu = _render(builder(False), False)
    assert np.all(np.isfinite(gpu)), f"{label}: GPU pixels not finite"

    gpu_mean = float(gpu.mean())
    cpu_mean = float(cpu.mean())
    # (1) black -> parity: the GPU image must be non-trivially lit (pre-fix == 0).
    assert gpu_mean > 0.05, f"{label}: GPU still dark (mean={gpu_mean:.5f}) — dedicated light not uploaded"
    # (2) mean-ratio parity with the CPU sampler (same pdfs + emission).
    ratio = gpu_mean / max(cpu_mean, 1e-9)
    assert 0.9 <= ratio <= 1.1, \
        f"{label}: GPU/CPU mean-ratio {ratio:.3f} outside [0.9,1.1] (gpu={gpu_mean:.4f} cpu={cpu_mean:.4f})"
    # (3) spatial correlation on the lit region (structure matches, not just mean).
    gflat, cflat = gpu.reshape(-1), cpu.reshape(-1)
    lit = cflat > 0.01 * cflat.max()
    if lit.sum() > 100:
        corr = float(np.corrcoef(gflat[lit], cflat[lit])[0, 1])
        assert corr > 0.9, f"{label}: GPU/CPU correlation {corr:.3f} too low"
    print(f"[{label} PASS] gpu_mean={gpu_mean:.4f} cpu_mean={cpu_mean:.4f} ratio={ratio:.3f}")


def test_gpu_dedicated_area_light_parity():
    """Harness config (AREA, size 3, energy 300): GPU goes from black to CPU parity."""
    _parity(_build_area, "AREA")


def test_gpu_dedicated_point_light_parity():
    """POINT light (delta, 1/r^2): GPU goes from black to CPU parity."""
    _parity(_build_point, "POINT")
