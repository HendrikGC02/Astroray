"""pkg271 — heterogeneous-volume light passes + `volume_bounces`.

Gates (spec acceptance, CPU + GPU; GPU legs skip without CUDA):
  1. PASS SPLIT — a NanoVDB smoke lit by a mesh emitter populates BOTH
     PASS_VOLUME_DIRECT (first-scatter medium NEE) and PASS_VOLUME_INDIRECT.
  2. SUM-TO-BEAUTY — Σ(all light-path passes) == beauty (rel_L1 ~ 0); the
     emitter is out of frame and the background black, so volume_direct +
     volume_indirect carry (almost) the whole image.
  3. volume_bounces OUTPUT EFFECT — the Cycles `volume_bounces` limit changes
     the image (0 < 2 < unlimited) on grids AND world fog, CPU and GPU.
  4. TERMINATE-AFTER — with volume_bounces = 0 a smoke lit ONLY by the fire in
     the same grid (density-free hot core) is not black: Cycles' terminate-after
     continuation collects the volume emission no NEE samples
     (batchq-volumes-3-research.md §4).
  5. GPU/CPU parity of the volume_bounces = 0 render (±5 %, per-channel mean).
Linear renders (`apply_gamma=False`), per-channel means, pinned seeds.
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

SEED = 271271
ALL_PASSES = [
    "diffuse_direct", "diffuse_indirect",
    "glossy_direct", "glossy_indirect",
    "transmission_direct", "transmission_indirect",
    "volume_direct", "volume_indirect",
    "emission", "environment",
]
BACKENDS = ["cpu", "gpu"]


def _gpu_available() -> bool:
    return AVAILABLE and astroray.__features__.get("cuda", False) \
        and astroray.Renderer().gpu_available


def _skip_backend(backend):
    if backend == "gpu" and not _gpu_available():
        pytest.skip("CUDA GPU not available on this machine")


def _base(backend):
    r = astroray.Renderer()
    r.set_seed(SEED)
    r.set_background_color([0.0, 0.0, 0.0])
    r.set_integrator("path_tracer")
    if backend == "gpu":
        r.set_use_gpu(True)
        r.set_gpu_light_path_passes(True)
        r.set_wavelength_range(380.0, 780.0)
        r.set_output_mode("srgb")
    else:
        r.set_use_gpu(False)
    return r


def _render(r, spp, depth, w, h, volume_bounces=-1):
    img = np.asarray(r.render(spp, depth, None, False, -1, -1, -1, volume_bounces, -1),
                     dtype=np.float64)
    return img.reshape(h, w, 3) if img.ndim == 1 else img


def _smoke_density(n=24):
    z, y, x = np.mgrid[0:n, 0:n, 0:n].astype(np.float32)
    c = (n - 1) / 2.0
    r2 = ((x - c) ** 2 + (y - c) ** 2 + (z - c) ** 2) / (c * c)
    dens = np.clip(1.0 - r2, 0.0, 1.0) * (0.6 + 0.4 * np.sin(x * 0.8) * np.cos(y * 0.6))
    return np.ascontiguousarray(dens.astype(np.float32))


def _grid_xform(n, size=2.0):
    vox = size / n
    h = size / 2.0
    i2o = [vox, 0, 0, -h, 0, vox, 0, -h, 0, 0, vox, -h, 0, 0, 0, 1]
    o2w = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]
    return i2o, o2w


def _smoke_scene(backend, w=40, h=40, density_scale=6.0):
    """Scattering smoke, emitter above-right OUT of frame, black background, no
    surfaces: every visible photon went through the medium."""
    r = _base(backend)
    lamp = r.create_material("light", [1.0, 1.0, 1.0], {"intensity": 30.0})
    r.add_sphere([2.5, 3.5, 2.0], 0.6, lamp)
    n = 24
    i2o, o2w = _grid_xform(n)
    r.set_volume_grid("smoke", _smoke_density(n), [0, 0, 0], i2o, o2w,
                      density_scale=density_scale, color=[0.9, 0.75, 0.6],
                      absorption_color=[1.0, 1.0, 1.0], anisotropy=0.2)
    r.setup_camera([0.0, 0.0, 5.0], [0.0, 0.0, 0.0], [0.0, 1.0, 0.0],
                   30.0, w / h, 0.0, 5.0, w, h)
    return r


def _pass(r, name, shape):
    return np.asarray(r.get_render_pass_buffer(name), dtype=np.float64).reshape(shape)


def _mean3(a):
    return a.reshape(-1, 3).mean(axis=0)


@pytest.mark.parametrize("backend", BACKENDS)
def test_grid_volume_pass_split_and_sum_to_beauty(backend):
    _skip_backend(backend)
    w = h = 40
    r = _smoke_scene(backend, w, h)
    beauty = _render(r, 128, 8, w, h)
    total = np.zeros_like(beauty)
    for name in ALL_PASSES:
        total += _pass(r, name, beauty.shape)
    vd = _mean3(_pass(r, "volume_direct", beauty.shape))
    vi = _mean3(_pass(r, "volume_indirect", beauty.shape))
    bm = _mean3(beauty)
    rel_l1 = float(np.abs(total - beauty).sum() / max(np.abs(beauty).sum(), 1e-9))
    share = float((vd + vi).sum() / max(bm.sum(), 1e-9))
    print(f"\n[pkg271 passes {backend}] beauty={bm.round(5)} vol_direct={vd.round(5)} "
          f"vol_indirect={vi.round(5)} (direct+indirect)/beauty={share:.4f} rel_L1={rel_l1:.6f}")
    assert bm.max() > 1e-3, "smoke renders black -- fixture broken"
    assert vd.sum() > 1e-5, f"PASS_VOLUME_DIRECT empty on {backend}: {vd}"
    assert vi.sum() > 1e-5, f"PASS_VOLUME_INDIRECT empty on {backend}: {vi}"
    # CPU passes are built from the same per-sample contributions (exact up to
    # float order); the GPU accumulates per-pixel XYZ atomics (pkg198 band).
    assert rel_l1 < (1e-3 if backend == "cpu" else 0.03), rel_l1
    assert share > 0.97, f"volume passes carry only {share:.3f} of a volume-only image"


@pytest.mark.parametrize("backend", BACKENDS)
def test_volume_bounces_changes_grid_image(backend):
    _skip_backend(backend)
    w = h = 32
    means = {}
    for vb in (0, 2, -1):
        means[vb] = float(_mean3(_render(_smoke_scene(backend, w, h, 10.0), 256, 16, w, h,
                                         volume_bounces=vb)).sum())
    print(f"\n[pkg271 volume_bounces grid {backend}] 0={means[0]:.5f} 2={means[2]:.5f} "
          f"unlimited={means[-1]:.5f}")
    assert means[0] > 0.0
    assert means[0] < 0.97 * means[2], means       # multiple scattering adds light
    assert means[2] <= 1.02 * means[-1], means     # unlimited >= 2 (MC band)


def _fog_scene(backend, w=32, h=32):
    r = _base(backend)
    r.set_world_volume(0.14, [1.0, 1.0, 1.0], 0.3, 0.8)
    lamp = r.create_material("light", [1.0, 1.0, 1.0], {"intensity": 40.0})
    r.add_sphere([0.0, 0.0, -3.0], 0.3, lamp)
    floor = r.create_material("lambertian", [0.6, 0.6, 0.6], {})
    r.add_sphere([0.0, -1001.0, -3.0], 1000.0, floor)
    r.setup_camera([0.0, 0.6, 6.0], [0.0, 0.0, -3.0], [0.0, 1.0, 0.0],
                   40.0, w / h, 0.0, 9.0, w, h)
    return r


@pytest.mark.parametrize("backend", BACKENDS)
def test_volume_bounces_changes_world_fog_image(backend):
    _skip_backend(backend)
    w = h = 32
    m0 = float(_mean3(_render(_fog_scene(backend), 256, 12, w, h, volume_bounces=0)).sum())
    m4 = float(_mean3(_render(_fog_scene(backend), 256, 12, w, h, volume_bounces=4)).sum())
    print(f"\n[pkg271 volume_bounces fog {backend}] 0={m0:.5f} 4={m4:.5f}")
    assert m0 > 0.0 and m0 < 0.97 * m4, (m0, m4)


def _fire_core_scene(backend, w=24, h=24, n=32):
    """ONE grid medium: a density-free hot core (x < -0.4, temperature only) and
    a scattering smoke block (x > 0.2, density only). The camera looks straight
    down -z at the smoke block; no camera ray crosses the core, so every pixel
    is smoke lit by the fire's volume emission (no lamps, black background)."""
    r = _base(backend)
    z, y, x = np.mgrid[0:n, 0:n, 0:n].astype(np.float32)
    xw = (x + 0.5) / n * 4.0 - 2.0          # world x of the voxel centre
    dens = np.where(xw > 0.2, 1.0, 0.0).astype(np.float32)
    temp = np.where(xw < -0.4, 1.0, 0.0).astype(np.float32)
    i2o, o2w = _grid_xform(n, 4.0)
    r.set_volume_grid("firecore", np.ascontiguousarray(dens), [0, 0, 0], i2o, o2w,
                      density_scale=3.0, color=[0.9, 0.9, 0.9],
                      absorption_color=[1.0, 1.0, 1.0], anisotropy=0.0,
                      temperature=np.ascontiguousarray(temp),
                      blackbody_intensity=1.0, blackbody_temperature=1500.0)
    # Look down -z at x in [0.6, 1.4] (inside the smoke block, far from the core).
    r.setup_camera([1.0, 0.0, 8.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0],
                   5.0, w / h, 0.0, 8.0, w, h)
    return r


@pytest.mark.parametrize("backend", BACKENDS)
def test_volume_bounces_zero_keeps_fire_lit_smoke(backend):
    _skip_backend(backend)
    w = h = 24
    m0 = _mean3(_render(_fire_core_scene(backend), 512, 16, w, h, volume_bounces=0))
    mu = _mean3(_render(_fire_core_scene(backend), 512, 16, w, h, volume_bounces=-1))
    print(f"\n[pkg271 fire-lit smoke {backend}] bounces0={m0.round(5)} unlimited={mu.round(5)}")
    assert np.all(np.isfinite(m0)) and np.all(np.isfinite(mu))
    assert m0.sum() > 0.05 * mu.sum(), (
        f"volume_bounces=0 blacked out fire-lit smoke ({m0} vs {mu}): the continuation "
        f"after the last allowed scatter must still collect volume emission")
    assert m0.sum() < mu.sum(), (m0, mu)


def test_gpu_cpu_parity_volume_bounces_zero():
    if not _gpu_available():
        pytest.skip("CUDA GPU not available on this machine")
    w = h = 32
    cpu = _mean3(_render(_smoke_scene("cpu", w, h, 10.0), 512, 16, w, h, volume_bounces=0))
    gpu = _mean3(_render(_smoke_scene("gpu", w, h, 10.0), 512, 16, w, h, volume_bounces=0))
    ratio = gpu / np.maximum(cpu, 1e-9)
    print(f"\n[pkg271 parity vb=0] CPU={cpu.round(5)} GPU={gpu.round(5)} GPU/CPU={ratio.round(4)}")
    for c in range(3):
        assert 0.95 <= ratio[c] <= 1.05, (c, ratio, cpu, gpu)
    fc = _mean3(_render(_fire_core_scene("cpu"), 1024, 16, 24, 24, volume_bounces=0))
    fg = _mean3(_render(_fire_core_scene("gpu"), 1024, 16, 24, 24, volume_bounces=0))
    fr = fg / np.maximum(fc, 1e-9)
    print(f"[pkg271 parity fire-lit vb=0] CPU={fc.round(5)} GPU={fg.round(5)} GPU/CPU={fr.round(4)}")
    lit = [c for c in range(3) if fc[c] > 1e-3]    # 1500 K has ~no blue
    assert lit, fc
    for c in lit:
        assert 0.95 <= fr[c] <= 1.05, (c, fr, fc, fg)
