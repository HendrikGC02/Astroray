"""pkg299 — OptiX hardware traversal for the GPU wavefront intersect/shadow stages.

Gates (spec .astroray_plan/packages/pkg299-optix-hardware-traversal.md):

* Fixed-ray A/B: the same rays through the software BVH (gpu_tlas_hit /
  gpu_tlas_occluded) and through OptiX + the intersect stage's hit
  reconstruction agree on >= 99.99 % of rays (closest hit: hit/miss + prim id;
  shadow: occluded flag). Residual mismatches are edge watertightness (RT cores
  are watertight, Moller-Trumbore is not); they are listed on failure.
* Agreeing hits carry the same record: t, point, normal, front face, material.
* GPU renders use OptiX by default on triangle-only scenes, fall back to the
  software BVH on scenes with spheres, and produce
  the same image as the software path up to the rare edge-ray mismatches.
* ASTRORAY_GPU_TRAVERSAL=software is the unchanged software path.

Skipped when the engine lacks CUDA / the OptiX traversal build, or no GPU.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT))

import runtime_setup  # noqa: E402

runtime_setup.configure_test_imports()

import astroray  # noqa: E402

pytestmark = [
    pytest.mark.gpu,
    pytest.mark.skipif(not getattr(astroray, "__features__", {}).get("cuda", False),
                       reason="astroray built without CUDA"),
    pytest.mark.skipif(not hasattr(astroray, "_gpu_optix_ray_ab"),
                       reason="astroray built without OptiX traversal (ASTRORAY_OPTIX_TRAVERSAL)"),
]

_ENV = "ASTRORAY_GPU_TRAVERSAL"


def _quad(a, b, c, d):
    return [[a, b, c], [a, c, d]]


def _displaced_sphere(center, radius, n):
    """UV sphere with a bumpy radius (the pkg298 heavy-Cornell mesh generator)."""
    th = np.linspace(0.0, np.pi, n + 1)
    ph = np.linspace(0.0, 2.0 * np.pi, 2 * n + 1)
    T, P = np.meshgrid(th, ph, indexing="ij")
    r = radius * (1.0 + 0.06 * np.sin(9 * T) * np.sin(11 * P)
                  + 0.03 * np.sin(23 * T) * np.cos(17 * P))
    xyz = np.stack([r * np.sin(T) * np.cos(P), r * np.cos(T),
                    r * np.sin(T) * np.sin(P)], axis=-1) + np.asarray(center)
    a, b = xyz[:-1, :-1], xyz[1:, :-1]
    c, d = xyz[1:, 1:], xyz[:-1, 1:]
    t0 = np.stack([a, b, c], axis=2).reshape(-1, 3, 3)
    t1 = np.stack([a, c, d], axis=2).reshape(-1, 3, 3)
    return np.concatenate([t0, t1], axis=0).astype(np.float32)


def _renderer(res=64):
    r = astroray.Renderer()
    if not getattr(r, "gpu_available", False):
        pytest.skip("CUDA GPU not available")
    r.setup_camera(look_from=[0.0, 0.0, 6.8], look_at=[0.0, 0.0, 0.0], vup=[0.0, 1.0, 0.0],
                   vfov=39.6, aspect_ratio=1.0, aperture=0.0, focus_dist=6.8,
                   width=res, height=res)
    r.set_background_color([0.0, 0.0, 0.0])
    r.set_seed(1234)
    r.set_adaptive_sampling(False)
    return r


def _cornell_mesh_scene(r, sphere_n=40):
    """Triangle-only Cornell box + a bumpy sphere mesh (shared edges everywhere)."""
    white = r.create_material("lambertian", [0.74, 0.74, 0.72], {})
    red = r.create_material("lambertian", [0.72, 0.08, 0.06], {})
    green = r.create_material("lambertian", [0.10, 0.50, 0.16], {})
    light = r.create_material("light", [1.0, 1.0, 1.0], {"intensity": 18.0})
    tris, mids = [], []
    for q, m in ((_quad([-2, -2, -2], [2, -2, -2], [2, -2, 2], [-2, -2, 2]), white),
                 (_quad([-2, 2, -2], [-2, 2, 2], [2, 2, 2], [2, 2, -2]), white),
                 (_quad([-2, -2, -2], [-2, 2, -2], [2, 2, -2], [2, -2, -2]), white),
                 (_quad([-2, -2, -2], [-2, -2, 2], [-2, 2, 2], [-2, 2, -2]), red),
                 (_quad([2, -2, -2], [2, 2, -2], [2, 2, 2], [2, -2, 2]), green),
                 (_quad([-0.5, 1.98, -0.5], [0.5, 1.98, -0.5], [0.5, 1.98, 0.5],
                        [-0.5, 1.98, 0.5]), light)):
        tris += q
        mids += [m] * len(q)
    sph = _displaced_sphere([-0.4, -1.1, 0.2], 0.8, sphere_n)
    pos = np.concatenate([np.asarray(tris, np.float32), sph])
    mid = np.asarray(mids + [white] * len(sph), np.int32)
    n = len(pos)
    r.add_triangles_bulk(pos, mid, np.zeros(n, np.int32), 0,
                         np.zeros((0, n, 3, 2), np.float32), [],
                         np.zeros((0, 3, 3), np.float32))
    return pos


def _random_rays(n, seed=7):
    rng = np.random.default_rng(seed)
    o = rng.uniform(-1.9, 1.9, size=(n, 3)).astype(np.float32)
    d = rng.normal(size=(n, 3))
    d /= np.linalg.norm(d, axis=1, keepdims=True)
    return o, d.astype(np.float32)


def _agreement_report(ab):
    sw_hit, hw_hit = ab["sw_hit"].astype(bool), ab["hw_hit"].astype(bool)
    same = (sw_hit == hw_hit) & (~sw_hit | (ab["sw_prim"] == ab["hw_prim"]))
    bad = np.nonzero(~same)[0]
    lines = [f"ray {i}: sw hit={int(sw_hit[i])} prim={ab['sw_prim'][i]} t={ab['sw_t'][i]:.6g} | "
             f"hw hit={int(hw_hit[i])} prim={ab['hw_prim'][i]} t={ab['hw_t'][i]:.6g}"
             for i in bad[:20]]
    return same, "\n".join(lines)


def test_fixed_ray_closest_hit_ab():
    r = _renderer()
    _cornell_mesh_scene(r)
    o, d = _random_rays(200_000)
    ab = astroray._gpu_optix_ray_ab(r, o, d, np.full(len(o), 1e30, np.float32), False)
    same, report = _agreement_report(ab)
    frac = same.mean()
    assert frac >= 0.9999, f"closest-hit agreement {frac:.6f} < 0.9999\n{report}"
    both = same & ab["sw_hit"].astype(bool)
    assert both.sum() > 150_000   # the rays start inside a closed box
    # Same triangle -> the record must match: identical helper code, only t/u/v
    # come from different intersection tests.
    t_rel = np.abs(ab["sw_t"][both] - ab["hw_t"][both]) / np.maximum(ab["sw_t"][both], 1e-3)
    assert t_rel.max() < 1e-4, f"max relative t delta {t_rel.max():.3e}"
    assert ab["point_delta"][both].max() < 1e-3
    assert ab["normal_delta"][both].max() < 1e-3
    assert ab["same_front_face"][both].all()
    assert ab["same_material"][both].all()


def test_fixed_ray_shadow_ab():
    r = _renderer()
    pos = _cornell_mesh_scene(r)
    o, _ = _random_rays(200_000, seed=11)
    # Shadow rays toward random points on random triangles (the NEE pattern:
    # tMax = distance - 0.001, the gpu_nee_sample triangle convention).
    rng = np.random.default_rng(3)
    tri = pos[rng.integers(0, len(pos), len(o))]
    b = rng.uniform(size=(len(o), 2))
    flip = b.sum(axis=1) > 1.0
    b[flip] = 1.0 - b[flip]
    p = tri[:, 0] + (tri[:, 1] - tri[:, 0]) * b[:, :1] + (tri[:, 2] - tri[:, 0]) * b[:, 1:]
    v = p - o
    dist = np.linalg.norm(v, axis=1)
    d = (v / dist[:, None]).astype(np.float32)
    ab = astroray._gpu_optix_ray_ab(r, o, d, (dist - 0.001).astype(np.float32), True)
    same = ab["sw_occluded"] == ab["hw_occluded"]
    bad = np.nonzero(~same)[0][:20]
    assert same.mean() >= 0.9999, (
        f"shadow agreement {same.mean():.6f} < 0.9999: "
        + "; ".join(f"ray {i} sw={ab['sw_occluded'][i]} hw={ab['hw_occluded'][i]} "
                    f"dist={dist[i]:.4g}" for i in bad))
    occ = ab["sw_occluded"].mean()
    assert 0.05 < occ < 0.95, f"degenerate shadow test (occluded fraction {occ:.3f})"


def test_fixed_ray_ab_instanced():
    """pkg114 instancing -> OptiX IAS over per-BLAS GAS, transforms applied."""
    r = _renderer()
    floor = r.create_material("lambertian", [0.8, 0.8, 0.8], {})
    red = r.create_material("lambertian", [0.8, 0.2, 0.2], {})
    for q in (_quad([-3, -1, -3], [3, -1, -3], [3, -1, 3], [-3, -1, 3]),):
        for t in q:
            r.add_triangle(t[0], t[1], t[2], floor)
    sph = _displaced_sphere([0.0, 0.0, 0.0], 0.5, 16)
    mesh = r.register_mesh_triangles([list(t.reshape(-1)) for t in sph], red)
    for x, s in ((-1.5, 1.0), (0.0, 0.6), (1.4, 1.3)):
        M = np.array([[s, 0, 0, x], [0, s, 0, 0.0], [0, 0, s, 0.3 * x], [0, 0, 0, 1]],
                     np.float32)
        r.add_instance(mesh, list(M.reshape(-1)))
    rng = np.random.default_rng(5)
    n = 100_000
    o = np.stack([rng.uniform(-3, 3, n), np.full(n, 3.0), rng.uniform(-3, 3, n)], 1)
    tgt = np.stack([rng.uniform(-2.5, 2.5, n), rng.uniform(-1, 0.5, n),
                    rng.uniform(-2, 2, n)], 1)
    d = tgt - o
    d /= np.linalg.norm(d, axis=1, keepdims=True)
    ab = astroray._gpu_optix_ray_ab(r, o.astype(np.float32), d.astype(np.float32),
                                    np.full(n, 1e30, np.float32), False)
    same, report = _agreement_report(ab)
    assert same.mean() >= 0.9999, f"instanced agreement {same.mean():.6f}\n{report}"
    both = same & ab["sw_hit"].astype(bool)
    hit_prims = set(ab["sw_prim"][both].tolist())
    assert len(hit_prims) > 100, "rays should hit many instanced triangles"
    assert ab["point_delta"][both].max() < 1e-3
    assert ab["normal_delta"][both].max() < 1e-3
    assert ab["same_front_face"][both].all()


def _render(r, spp=16):
    r.set_use_gpu(True)
    img = np.asarray(r.render(spp, 6, None, False), dtype=np.float32)
    return img, r.last_render_info().get("gpu_traversal")


def test_render_uses_optix_and_matches_software(monkeypatch):
    monkeypatch.setenv(_ENV, "software")
    r = _renderer()
    _cornell_mesh_scene(r)
    sw, mode_sw = _render(r)
    monkeypatch.setenv(_ENV, "optix")
    r2 = _renderer()
    _cornell_mesh_scene(r2)
    hw, mode_hw = _render(r2)
    assert mode_sw == "software"
    assert mode_hw == "optix"
    assert np.isfinite(hw).all()
    # Same seed and RNG streams. Where both traversals hit the same triangle the
    # only difference is the hardware t / barycentrics (~1e-5 relative), so the
    # pixel stays within 1e-4. A ray through a shared edge can pick the other
    # triangle (watertight vs Moller-Trumbore); that path then decorrelates and
    # its pixel moves by an MC-noise amount. Measured: 2026-09-30 no such pixel;
    # after pkg305's stratified camera, 1 of 4096 (4e-2). Bound the count, and
    # the image mean, instead of the per-pixel max.
    rel = np.abs(hw - sw).max(axis=-1) / np.maximum(sw.max(axis=-1), 1e-3)
    outliers = int((rel > 1e-4).sum())
    assert outliers <= 0.002 * rel.size, f"{outliers} pixels differ by > 1e-4 (max {rel.max():.3e})"
    assert abs(hw.mean() - sw.mean()) <= 1e-4 * max(sw.mean(), 1e-6)


def test_sphere_scene_falls_back_to_software(monkeypatch):
    monkeypatch.setenv(_ENV, "optix")
    r = _renderer(32)
    _cornell_mesh_scene(r, sphere_n=8)
    r.add_sphere([0.8, -1.4, 0.8], 0.4, r.create_material("lambertian", [0.5, 0.5, 0.5], {}))
    _, mode = _render(r, spp=4)
    assert mode == "software"


def test_default_is_optix_on_triangle_scenes(monkeypatch):
    """Owner 2026-09-29: default on for triangle-only scenes after Phase 1."""
    monkeypatch.delenv(_ENV, raising=False)
    r = _renderer(32)
    _cornell_mesh_scene(r, sphere_n=8)
    _, mode = _render(r, spp=4)
    assert mode == "optix"


def test_first_bounded_media_render_after_optix(monkeypatch):
    """The hetero-medium queue counter was read before its first reset. Fresh
    cudaMalloc memory hid it; after an OptiX render recycled device memory the
    first bounded-media render faulted (illegal address in the intersect stage)."""
    import test_873_877_clip_medium_nee as clip
    monkeypatch.setenv(_ENV, "optix")
    r = clip._clip_scene(True, medium=None, emissive_clipped=False)
    r.render(4, 8, None, False)
    assert r.last_render_info().get("gpu_traversal") == "optix"
    for mode in ("software", "optix"):
        monkeypatch.setenv(_ENV, mode)
        r = clip._clip_scene(True, medium="box", emissive_clipped=False)
        img = np.asarray(r.render(4, 8, None, False), dtype=np.float32)
        assert np.isfinite(img).all()


def _instanced_scene(r):
    floor = r.create_material("lambertian", [0.8, 0.8, 0.8], {})
    red = r.create_material("lambertian", [0.8, 0.2, 0.2], {})
    for t in _quad([-3, -1, -3], [3, -1, -3], [3, -1, 3], [-3, -1, 3]):
        r.add_triangle(t[0], t[1], t[2], floor)
    sph = _displaced_sphere([0.0, 0.0, 0.0], 0.5, 16)
    mesh = r.register_mesh_triangles([list(t.reshape(-1)) for t in sph], red)
    for x, s in ((-1.5, 1.0), (0.0, 0.6), (1.4, 1.3)):
        M = np.array([[s, 0, 0, x], [0, s, 0, 0.0], [0, 0, s, 0.3 * x], [0, 0, 0, 1]],
                     np.float32)
        r.add_instance(mesh, list(M.reshape(-1)))
    r.set_background_color([0.6, 0.6, 0.6])


def test_instanced_render_matches_software(monkeypatch):
    imgs = {}
    for mode in ("software", "optix"):
        monkeypatch.setenv(_ENV, mode)
        r = _renderer()
        _instanced_scene(r)
        imgs[mode], used = _render(r, spp=8)
        assert used == mode
    sw, hw = imgs["software"], imgs["optix"]
    assert sw.mean() > 0.05
    rel = np.abs(hw - sw).max(axis=-1) / np.maximum(sw.max(axis=-1), 1e-3)
    outliers = int((rel > 1e-4).sum())   # edge rays, see the test above
    assert outliers <= 0.002 * rel.size, f"{outliers} pixels differ by > 1e-4 (max {rel.max():.3e})"
    assert abs(hw.mean() - sw.mean()) <= 1e-4 * max(sw.mean(), 1e-6)
