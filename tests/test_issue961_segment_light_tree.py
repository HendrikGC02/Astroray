"""#961 / #1019 — the light tree picks ONE light per medium segment.

Before: the segment direct light (#925 / #929) picked its equiangular anchor
with a POINT pick at the segment midpoint and connected an independent point
pick at P. When the midpoint was outside a spot cone the pick failed, so there
was no anchor and the exponential at the media hull's global majorant could not
reach the lit part of the ray. v2_media's spot shaft behind the smoke VDB read
0.67-0.71 of Cycles (rising with spp: a heavy tail).

Now (Cycles light_sample_from_volume_segment / light_tree_sample<true>,
kernel/light/tree.h, Apache-2.0): one pick with the segment importance, the
same light re-sampled at the anchor and at P, and the lamp/emitter hit after a
medium scatter MIS-weighted with the same segment pdf.

Gates (CPU and GPU):
  * spot above a fog box, single scatter: power and tree within 2 % of a
    numerical quadrature of the single-scatter integral;
  * the same with a grid medium in front whose majorant is set by one hot
    voxel: tree == power (was 0 with the tree);
  * several lights in a medium (box and world fog), light tree: NEE on equals
    NEE off within 4 standard errors (segment-pdf forward MIS is consistent).
"""
from __future__ import annotations

import math

import numpy as np
import pytest
from runtime_setup import configure_test_imports

configure_test_imports()
astroray = pytest.importorskip("astroray")

W, H = 32, 24
VFOV = 40.0
CAM = np.array([0.0, -10.0, 2.0])
LOOK = np.array([0.0, 0.0, 2.0])
BOX = (np.array([-3.0, -2.0, 0.0]), np.array([3.0, 2.0, 4.0]))
DENS, COLOR, G = 0.08, 0.5, 0.5
SPOT = np.array([1.0, 1.5, 7.0])
TGT = np.array([-0.5, 0.0, 0.0])
HALF, BLEND, POWER = math.radians(11.0), 0.3, 12000.0


def _renderer(backend):
    r = astroray.Renderer()
    if backend == "gpu":
        if not (astroray.__features__.get("cuda", False) and r.gpu_available):
            pytest.skip("CUDA GPU not available on this machine")
        r.set_use_gpu(True)
        r.set_wavelength_range(380.0, 780.0)
        r.set_output_mode("srgb")
    else:
        r.set_use_gpu(False)
    r.set_integrator("path_tracer")
    r.set_adaptive_sampling(False)
    r.set_background_color([0.0, 0.0, 0.0])
    return r


def _spot_fog(backend, sampler, seed, grid=False, spp=128):
    r = _renderer(backend)
    r.set_light_sampler(sampler)
    cos_o = math.cos(HALF)
    cos_i = min(1.0, cos_o + (1.0 - cos_o) * BLEND)
    ax = (TGT - SPOT) / np.linalg.norm(TGT - SPOT)
    r.add_spot_light_dedicated(SPOT.tolist(), ax.tolist(), math.acos(cos_i), HALF,
                               {"mode": "rgb", "color": [1.0, 1.0, 1.0]}, POWER, 0.0)
    # Principled defaults: absorption = (1 - colour) * density, as the addon exports.
    r.add_homogeneous_medium(BOX[0].tolist(), BOX[1].tolist(), DENS, [COLOR] * 3,
                             [0.0] * 3, G)
    if grid:
        # A grid medium between the camera and the fog: density 0.3 with one hot
        # corner voxel (100), so the hull's majorant rate is ~30x the real density.
        g = np.full((8, 2, 12), 0.3, np.float32)
        g[0, 0, 0] = 100.0
        i2o = [0.5, 0, 0, -3.0, 0, 0.5, 0, -6.0, 0, 0, 0.5, 0.0, 0, 0, 0, 1]
        o2w = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]
        r.set_volume_grid("g", g, [0, 0, 0], i2o, o2w, density_scale=1.0,
                          color=[COLOR] * 3, absorption_color=[0.0] * 3, anisotropy=0.0)
    r.setup_camera(CAM.tolist(), LOOK.tolist(), [0, 0, 1], VFOV, W / H, 0.0, 10.0, W, H)
    r.set_seed(seed)
    img = np.asarray(r.render(spp, 8, None, False, volume_bounces=0), dtype=np.float64)
    return img.reshape(H, W, 3).mean()


def _ray_box(o, d, lo, hi):
    with np.errstate(divide="ignore", invalid="ignore"):
        a, b = (lo - o) / d, (hi - o) / d
    t0 = np.nanmax(np.minimum(a, b)); t1 = np.nanmin(np.maximum(a, b))
    t0 = max(t0, 0.0)
    return (t0, t1) if t1 > t0 else None


def _analytic():
    """Single scatter: Tr_cam * sigma_s * HG * I * smoothstep cone / d^2 * Tr_light."""
    sig_s, sig_t = COLOR * DENS, DENS
    intensity = POWER / (4.0 * math.pi)
    ax = (TGT - SPOT) / np.linalg.norm(TGT - SPOT)
    cos_o = math.cos(HALF)
    cos_i = min(1.0, cos_o + (1.0 - cos_o) * BLEND)
    fwd = (LOOK - CAM) / np.linalg.norm(LOOK - CAM)
    right = np.cross(fwd, [0, 0, 1]); right /= np.linalg.norm(right)
    up = np.cross(right, fwd)
    th = math.tan(math.radians(VFOV) / 2); tw = th * W / H
    total = 0.0
    n = 300
    for j in range(H):
        for i in range(W):
            for sj in (0.25, 0.75):
                for si in (0.25, 0.75):
                    d = fwd + (2 * (i + si) / W - 1) * tw * right + (1 - 2 * (j + sj) / H) * th * up
                    d /= np.linalg.norm(d)
                    seg = _ray_box(CAM, d, *BOX)
                    if seg is None:
                        continue
                    dt = (seg[1] - seg[0]) / n
                    ts = seg[0] + (np.arange(n) + 0.5) * dt
                    P = CAM[None] + d[None] * ts[:, None]
                    L = SPOT[None] - P
                    dist = np.linalg.norm(L, axis=1)
                    wi = L / dist[:, None]
                    x = np.clip((-(wi @ ax) - cos_o) / (cos_i - cos_o), 0, 1)
                    tl = np.array([0.0 if s is None else max(min(s[1], dd) - s[0], 0.0)
                                   for s, dd in ((_ray_box(p, w, *BOX), dd)
                                                 for p, w, dd in zip(P, wi, dist))])
                    cc = -(wi @ d)
                    hg = (1 - G * G) / (4 * np.pi * (1 + G * G + 2 * G * cc) ** 1.5)
                    total += np.sum(np.exp(-sig_t * (ts - seg[0])) * sig_s * hg * intensity
                                    * x * x * (3 - 2 * x) / dist ** 2
                                    * np.exp(-sig_t * tl)) * dt / 4
    return total / (W * H)


@pytest.mark.parametrize("backend", ["cpu", "gpu"])
def test_961_spot_fog_matches_single_scatter_quadrature(backend):
    ref = _analytic()
    for sampler in ("power", "tree"):
        m = np.mean([_spot_fog(backend, sampler, s) for s in (1, 2)])
        assert abs(m / ref - 1.0) < 0.02, (backend, sampler, m, ref, m / ref)


@pytest.mark.parametrize("backend", ["cpu", "gpu"])
def test_961_tree_reaches_fog_behind_high_majorant_grid(backend):
    power = np.mean([_spot_fog(backend, "power", s, grid=True) for s in (1, 2)])
    tree = np.mean([_spot_fog(backend, "tree", s, grid=True) for s in (1, 2)])
    assert power > 0.0
    assert abs(tree / power - 1.0) < 0.03, (backend, tree, power)


def _multi(backend, nee, seed, fog):
    r = _renderer(backend)
    r.set_light_sampler("tree")
    r.set_light_nee(nee)
    floor = r.create_material("lambertian", [0.3, 0.3, 0.3], {})
    r.add_triangle([-6, -6, -0.5], [6, -6, -0.5], [6, 6, -0.5], floor)
    r.add_triangle([-6, -6, -0.5], [6, 6, -0.5], [-6, 6, -0.5], floor)
    r.add_area_light_dedicated([1.5, 0, 3.5], [0, 1, 0], [1, 0, 0], 1.0, 1.0, "RECTANGLE",
                               {"mode": "rgb", "color": [1.0, 0.9, 0.7]}, 30.0)
    r.add_area_light_dedicated([-2.5, 1, 2.0], [0, 1, 0], [0, 0, 1], 0.6, 0.6, "RECTANGLE",
                               {"mode": "rgb", "color": [0.6, 0.8, 1.0]}, 20.0)
    lm = r.create_material("light", [1.0, 0.5, 0.3], {"intensity": 6.0})
    r.add_triangle([0.5, 1.0, 0.5], [1.0, 1.0, 0.5], [1.0, 1.0, 1.0], lm)
    r.add_triangle([0.5, 1.0, 0.5], [1.0, 1.0, 1.0], [0.5, 1.0, 1.0], lm)
    if fog:
        r.set_world_volume(0.25, [0.8, 0.8, 0.8], 0.3, 0.8)
    else:
        r.add_homogeneous_medium([-3, -3, -1], [3, 3, 4], 0.25, [0.8, 0.8, 0.8],
                                 [0.0, 0.0, 0.0], 0.3)
    r.setup_camera([0, -8, 1.5], [0, 0, 1.5], [0, 0, 1], 40.0, 1.0, 0.0, 8.0, 24, 24)
    r.set_seed(seed)
    img = np.asarray(r.render(256, 8, None, False), dtype=np.float64)
    return img.reshape(24, 24, 3).mean(axis=(0, 1))


@pytest.mark.parametrize("backend", ["cpu", "gpu"])
@pytest.mark.parametrize("fog", [False, True], ids=["box", "fog"])
def test_961_tree_segment_mis_nee_on_matches_off(backend, fog):
    seeds = range(1, 9)
    on = np.stack([_multi(backend, True, s, fog) for s in seeds])
    off = np.stack([_multi(backend, False, s, fog) for s in seeds])
    se = np.hypot(on.std(0, ddof=1), off.std(0, ddof=1)) / math.sqrt(len(seeds))
    tol = 4.0 * se + 0.005 * off.mean(0)
    assert np.all(np.abs(on.mean(0) - off.mean(0)) <= tol), (on.mean(0), off.mean(0), tol)
