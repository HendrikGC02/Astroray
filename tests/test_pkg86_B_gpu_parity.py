"""pkg86-B Phase 2 gate: GPU light-tree traversal parity vs CPU.

The device traversal (src/gpu/light_tree_device.cuh) is a 1:1 float32 mirror
of the CPU LightTree::pick (src/light_tree.cpp; both mirror Cycles
kernel/light/tree.h, Apache-2.0, commit e52e5eb0). This gate runs the SAME
(point, normal, u) queries through both implementations via the
debug_light_tree_pick / debug_light_tree_pick_gpu bindings and requires:

- identical light pick for >= 99.5% of queries (the 0.5% slack absorbs FP
  branch flips at near-50/50 importance ratios — spec section "Phase 2 gate"),
- pdf relative error < 1e-4 on matching picks.

Also covers the spec's upload-cost gate (<= 10 ms tree upload on a 10k-light
synthetic; Cycles upstream PR #105862 reports < 5 ms) and the SAOH split
correctness probe (two well-separated clusters: picks from a point near
cluster A overwhelmingly come from cluster A).
"""

from __future__ import annotations

import numpy as np
import pytest

from runtime_setup import configure_test_imports

configure_test_imports()

try:
    import astroray  # noqa: E402
    AVAILABLE = True
except ImportError:
    AVAILABLE = False

pytestmark = pytest.mark.skipif(not AVAILABLE, reason="astroray not built")

if AVAILABLE and not astroray.__features__.get("cuda", False):
    pytest.skip(
        "CUDA feature not in this build — pkg86-B GPU light tree parity "
        "needs the RTX box.",
        allow_module_level=True,
    )

WIDTH = HEIGHT = 32  # camera size is irrelevant; upload_scene needs one


def _grid_light_scene(n_side=8, spacing=1.0, intensity=5.0, seed=7):
    """n_side x n_side grid of emissive spheres above a floor (the pkg86
    variance-scene shape) with the tree sampler active and GPU enabled."""
    r = astroray.Renderer()
    r.set_use_gpu(True)
    r.set_light_sampler("tree")
    r.set_background_color([0.0, 0.0, 0.0])
    r.set_seed(seed)

    floor = r.create_material("lambertian", [0.7, 0.7, 0.7], {})
    r.add_triangle([-20, 0, -20], [20, 0, -20], [20, 0, 20], floor)
    r.add_triangle([-20, 0, -20], [20, 0, 20], [-20, 0, 20], floor)

    rng = np.random.default_rng(seed)
    light = r.create_material("light", [1.0, 0.9, 0.8], {"intensity": intensity})
    for i in range(n_side):
        for j in range(n_side):
            x = (i - n_side / 2 + 0.5) * spacing
            z = (j - n_side / 2 + 0.5) * spacing
            y = 3.0 + float(rng.uniform(-0.5, 0.5))
            r.add_sphere([x, y, z], 0.08, light)

    r.setup_camera([0, 2.0, 9.0], [0, 1.0, 0], [0, 1, 0], 40.0,
                   WIDTH / HEIGHT, 0.0, 9.0, WIDTH, HEIGHT)
    r.upload_scene()
    return r


def _random_queries(n, seed=3):
    rng = np.random.default_rng(seed)
    pts = np.column_stack([
        rng.uniform(-8, 8, n),     # x on/above the floor
        rng.uniform(0.02, 2.5, n),  # y
        rng.uniform(-8, 8, n),
    ]).astype(np.float32)
    nrms = np.tile(np.array([0.0, 1.0, 0.0], dtype=np.float32), (n, 1))
    us = rng.uniform(0.0, 1.0, n).astype(np.float32)
    return pts, nrms, us


def test_pick_parity_10k_queries():
    """>= 99.5% identical picks + pdf rel-err < 1e-4 on 10k uniform queries."""
    r = _grid_light_scene(n_side=8)  # 64 lights
    n = 10_000
    pts, nrms, us = _random_queries(n)
    p, m, u = pts.ravel().tolist(), nrms.ravel().tolist(), us.tolist()

    cpu_idx, cpu_pdf = r.debug_light_tree_pick(p, m, u)
    gpu_idx, gpu_pdf = r.debug_light_tree_pick_gpu(p, m, u)

    cpu_idx = np.asarray(cpu_idx)
    gpu_idx = np.asarray(gpu_idx)
    cpu_pdf = np.asarray(cpu_pdf, dtype=np.float64)
    gpu_pdf = np.asarray(gpu_pdf, dtype=np.float64)

    assert (cpu_idx >= 0).all(), "CPU tree returned empty picks"
    same = cpu_idx == gpu_idx
    match_rate = float(same.mean())
    assert match_rate >= 0.995, (
        f"GPU/CPU light pick parity {match_rate:.4%} < 99.5% "
        f"({int((~same).sum())} of {n} queries diverged)"
    )

    matching = same & (cpu_pdf > 0)
    rel_err = np.abs(gpu_pdf[matching] - cpu_pdf[matching]) / cpu_pdf[matching]
    max_rel = float(rel_err.max()) if matching.any() else 0.0
    assert max_rel < 1e-4, f"pdf relative error {max_rel:.2e} >= 1e-4"


def test_saoh_split_routes_to_near_cluster():
    """Two well-separated 4-light clusters: picks from a point right under
    cluster A must overwhelmingly select cluster-A lights (SAOH split +
    Conty importance; a centroid-blind split fails this)."""
    r = astroray.Renderer()
    r.set_use_gpu(True)
    r.set_light_sampler("tree")
    r.set_background_color([0.0, 0.0, 0.0])

    floor = r.create_material("lambertian", [0.7, 0.7, 0.7], {})
    r.add_triangle([-40, 0, -40], [40, 0, -40], [40, 0, 40], floor)
    r.add_triangle([-40, 0, -40], [40, 0, 40], [-40, 0, 40], floor)

    light = r.create_material("light", [1.0, 1.0, 1.0], {"intensity": 5.0})
    cluster_a = []  # near x = -20
    for k in range(4):
        r.add_sphere([-20.0 + 0.3 * k, 2.0, 0.0], 0.08, light)
        cluster_a.append(r.scene_object_count() - 1)
    for k in range(4):  # cluster B near x = +20
        r.add_sphere([20.0 + 0.3 * k, 2.0, 0.0], 0.08, light)

    r.setup_camera([0, 2, 8], [0, 0, 0], [0, 1, 0], 40.0, 1.0, 0.0, 8.0,
                   WIDTH, HEIGHT)
    r.upload_scene()

    n = 2000
    rng = np.random.default_rng(11)
    pts = np.column_stack([
        rng.uniform(-20.5, -19.0, n),  # directly under cluster A
        np.full(n, 0.05),
        rng.uniform(-0.5, 0.5, n),
    ]).astype(np.float32)
    nrms = np.tile(np.array([0.0, 1.0, 0.0], dtype=np.float32), (n, 1))
    us = rng.uniform(0, 1, n).astype(np.float32)

    for picker in (r.debug_light_tree_pick, r.debug_light_tree_pick_gpu):
        idx, _ = picker(pts.ravel().tolist(), nrms.ravel().tolist(), us.tolist())
        idx = np.asarray(idx)
        near_rate = float(np.isin(idx, np.arange(0, 4)).mean()) if idx.min() >= 0 else 0.0
        # Light indices follow add order within the LightList; the first 4
        # emissive spheres are cluster A. d² importance ratio is (40/0.75)²
        # ≈ 2800:1, so even with cone slack the near cluster dominates.
        assert near_rate > 0.95, (
            f"{picker.__name__}: only {near_rate:.1%} of picks from under "
            f"cluster A selected cluster-A lights"
        )


def test_tree_upload_cost_10k_lights():
    """One-time tree upload <= 10 ms on a 10k-light synthetic scene."""
    r = astroray.Renderer()
    r.set_use_gpu(True)
    r.set_light_sampler("tree")
    floor = r.create_material("lambertian", [0.7, 0.7, 0.7], {})
    r.add_triangle([-200, 0, -200], [200, 0, -200], [200, 0, 200], floor)
    light = r.create_material("light", [1.0, 1.0, 1.0], {"intensity": 2.0})
    rng = np.random.default_rng(5)
    for _ in range(10_000):
        x, z = rng.uniform(-100, 100, 2)
        r.add_sphere([float(x), float(rng.uniform(2, 8)), float(z)], 0.05, light)
    r.setup_camera([0, 5, 20], [0, 0, 0], [0, 1, 0], 40.0, 1.0, 0.0, 20.0,
                   WIDTH, HEIGHT)
    r.upload_scene()

    ms = r.get_light_tree_upload_ms()
    assert ms > 0.0, "tree was not uploaded (get_light_tree_upload_ms == 0)"
    assert ms <= 10.0, f"light tree upload took {ms:.2f} ms > 10 ms gate"


def test_power_mode_uploads_no_tree():
    """Power sampler mode must not upload a tree (enabled stays off)."""
    r = _grid_light_scene(n_side=3)
    # rebuild with power sampler
    r2 = astroray.Renderer()
    r2.set_use_gpu(True)
    r2.set_light_sampler("power")
    floor = r2.create_material("lambertian", [0.7, 0.7, 0.7], {})
    r2.add_triangle([-20, 0, -20], [20, 0, -20], [20, 0, 20], floor)
    light = r2.create_material("light", [1.0, 1.0, 1.0], {"intensity": 5.0})
    r2.add_sphere([0, 3, 0], 0.1, light)
    r2.setup_camera([0, 2, 8], [0, 0, 0], [0, 1, 0], 40.0, 1.0, 0.0, 8.0,
                    WIDTH, HEIGHT)
    r2.upload_scene()
    assert r2.get_light_tree_upload_ms() == 0.0
    with pytest.raises(RuntimeError):
        r2.debug_light_tree_pick_gpu([0.0, 0.5, 0.0], [0.0, 1.0, 0.0], [0.5])
