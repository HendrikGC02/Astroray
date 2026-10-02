"""pkg296 (#833) — mesh-bounded volumes on the CPU: the medium follows the mesh.

Engine level (CI, no Blender). Pure-absorption scenes over an emissive backdrop
have an exact oracle: Tr = exp(-sum_k sigma_k * L_k) with L_k the chord of the
ray inside mesh k, computed here by an independent numpy Moller-Trumbore
ray/mesh intersection (not the engine's watertight Woop test):
  1. #833 regression: the AABB-minus-icosphere corners show the bare backdrop
     (on main the icosphere rendered as its AABB cube: corners ~exp(-6));
  2. icosphere / overlapping / nested media vs the Beer-Lambert oracle;
  3. camera inside a medium, with clip_start 0.001 and 0.5 (Cycles
     camera_sample_perspective moves the ray origin to the clip start, so the
     medium before it is not traversed);
  4. a grid medium with a sphere boundary is clipped to it;
  5. an axis-aligned box mesh volume with and without its boundary agree (3 sigma);
  6. a glass shell (IOR 1.0) whose interior is the medium == the medium alone
     (surface and boundary coincide: the spawn side decides);
  7. cost: the boundary path is <= 1.3x the AABB path at equal spp.

Blender level (opt-in, ASTRORAY_PKG296_BLENDER=1 + Blender 5.2 + a CPU .pyd in
ASTRORAY_PYD_DIR): the volumes_mesh corpus vs the committed Cycles references
(refs_v2/volumes_mesh_cycles.json), per-ROI per-channel at volume_bounces 0/4,
and the icosphere silhouette IoU >= 0.98.
"""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
import time
from pathlib import Path

import numpy as np
import pytest
from runtime_setup import configure_test_imports

configure_test_imports()
astroray = pytest.importorskip("astroray")

REPO = Path(__file__).resolve().parents[1]
W = H = 48
ORTHO = 2.4
SEEDS = (2961, 2962, 2963, 2964, 2965)


# --------------------------------------------------------------------------- #
# Geometry + independent oracle
# --------------------------------------------------------------------------- #
def icosphere(sub=3, r=1.0, c=(0.0, 0.0, 0.0)):
    """Outward-wound (CCW from outside) icosphere, (V, F)."""
    t = (1 + 5 ** 0.5) / 2
    v = [(-1, t, 0), (1, t, 0), (-1, -t, 0), (1, -t, 0), (0, -1, t), (0, 1, t),
         (0, -1, -t), (0, 1, -t), (t, 0, -1), (t, 0, 1), (-t, 0, -1), (-t, 0, 1)]
    f = [(0, 11, 5), (0, 5, 1), (0, 1, 7), (0, 7, 10), (0, 10, 11), (1, 5, 9), (5, 11, 4),
         (11, 10, 2), (10, 7, 6), (7, 1, 8), (3, 9, 4), (3, 4, 2), (3, 2, 6), (3, 6, 8),
         (3, 8, 9), (4, 9, 5), (2, 4, 11), (6, 2, 10), (8, 6, 7), (9, 8, 1)]
    v = [np.array(p, float) / np.linalg.norm(p) for p in v]

    def mid(cache, a, b):
        k = (min(a, b), max(a, b))
        if k not in cache:
            m = v[a] + v[b]
            v.append(m / np.linalg.norm(m))
            cache[k] = len(v) - 1
        return cache[k]
    for _ in range(sub):
        cache, nf = {}, []
        for a, b, cc in f:
            ab, bc, ca = mid(cache, a, b), mid(cache, b, cc), mid(cache, cc, a)
            nf += [(a, ab, ca), (b, bc, ab), (cc, ca, bc), (ab, bc, ca)]
        f = nf
    return (np.array(v) * r + np.array(c)).astype(np.float32), np.array(f, np.int32)


def box(mn, mx):
    x0, y0, z0 = mn
    x1, y1, z1 = mx
    v = np.array([(x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0),
                  (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)], np.float32)
    f = np.array([(0, 2, 1), (0, 3, 2), (4, 5, 6), (4, 6, 7), (0, 1, 5), (0, 5, 4),
                  (2, 3, 7), (2, 7, 6), (1, 2, 6), (1, 6, 5), (0, 4, 7), (0, 7, 3)], np.int32)
    return v, f


def chord(V, F, o, d, t0=0.0):
    """Length of the ray (o, unit d) inside the closed mesh beyond t0
    (Moller-Trumbore, all hits, inside iff the next hit leaves)."""
    p0, p1, p2 = V[F[:, 0]].astype(float), V[F[:, 1]].astype(float), V[F[:, 2]].astype(float)
    e1, e2 = p1 - p0, p2 - p0
    pv = np.cross(d, e2)
    det = (e1 * pv).sum(1)
    ok = np.abs(det) > 1e-12
    inv = np.where(ok, 1.0 / np.where(ok, det, 1.0), 0.0)
    tv = o - p0
    u = (tv * pv).sum(1) * inv
    qv = np.cross(tv, e1)
    w = (qv * d).sum(1) * inv
    t = (qv * e2).sum(1) * inv
    hit = ok & (u >= 0) & (w >= 0) & (u + w <= 1) & (t > t0)
    ts = np.sort(t[hit])
    n = np.cross(e1, e2)
    back = ((n * d).sum(1) > 0)[hit][np.argsort(t[hit])]
    total, cur = 0.0, t0
    for ti, b in zip(ts, back):
        if b:
            total += ti - cur
        cur = ti
    return total


def ortho_tr(meshes, sub=4):
    """Per-pixel oracle transmittance for the ortho camera at +z looking -z:
    meshes = [(V, F, sigma)], supersampled sub x sub per pixel."""
    out = np.zeros((H, W))
    d = np.array([0.0, 0.0, -1.0])
    for j in range(H):
        for i in range(W):
            acc = 0.0
            for sj in range(sub):
                for si in range(sub):
                    x = ((i + (si + 0.5) / sub) / W - 0.5) * ORTHO
                    y = ((j + (sj + 0.5) / sub) / H - 0.5) * ORTHO
                    o = np.array([x, y, 5.0])
                    acc += np.exp(-sum(s * chord(V, F, o, d) for V, F, s in meshes))
            out[j, i] = acc / sub ** 2
    return out


# --------------------------------------------------------------------------- #
# Engine scenes
# --------------------------------------------------------------------------- #
def _renderer(seed, ortho=True, eye=(0.0, 0.0, 5.0), clip=0.001, vfov=40.0):
    r = astroray.Renderer()
    r.set_seed(seed)
    r.set_background_color([0.0, 0.0, 0.0])
    r.set_integrator("path_tracer")
    r.set_use_gpu(False)
    kw = {"orthographic": True, "ortho_width": ORTHO, "ortho_height": ORTHO} if ortho else {}
    look = [eye[0], eye[1], eye[2] - 1.0]
    r.setup_camera(list(eye), look, [0, 1, 0], vfov, W / H, 0.0, 5.0, W, H,
                   clip_near=clip, **kw)
    return r


def _backdrop(r, z=-2.0, a=6.0):
    m = r.create_material("light", [1, 1, 1], {"intensity": 1.0})
    r.add_triangle([-a, -a, z], [a, -a, z], [a, a, z], m)
    r.add_triangle([-a, -a, z], [a, a, z], [-a, a, z], m)


def _absorber(r, V, F, sigma, boundary=True):
    kw = {"boundary_vertices": V, "boundary_indices": F} if boundary else {}
    r.add_homogeneous_medium(V.min(0).tolist(), V.max(0).tolist(), density_scale=sigma,
                             color=[0, 0, 0], absorption_color=[0, 0, 0], **kw)


def _render(r, spp):
    img = np.asarray(r.render(spp, 8, None, False, -1, -1, -1, 0, -1), dtype=np.float64)
    return img.reshape(H, W, 3)


def _lum(img):
    return img.mean(axis=2)


def _ratio_vs_empty(build, spp=256, seed=2961, **cam):
    """(render / empty-backdrop render) luminance, per pixel."""
    r = _renderer(seed, **cam)
    _backdrop(r)
    build(r)
    e = _renderer(seed, **cam)
    _backdrop(e)
    return _lum(_render(r, spp)) / np.maximum(_lum(_render(e, spp)), 1e-6)


def _check(meas, oracle, mask, spp, rel=0.02):
    m, o = meas[mask].mean(), oracle[mask].mean()
    # Analog absorption is Bernoulli per sample: 3 sigma of the ROI mean.
    sig = np.sqrt(max(o * (1 - o), 1e-6) / (spp * mask.sum()))
    tol = max(rel * o, 3 * sig)
    assert abs(m - o) <= tol, f"measured {m:.4f} vs Beer-Lambert {o:.4f} (tol {tol:.4f})"


def _px_xy():
    c = (np.arange(W) + 0.5) / W - 0.5
    x, y = np.meshgrid(c * ORTHO, c * ORTHO)
    return x, y


ICO = icosphere(3, 1.0)


def test_icosphere_aabb_corners_show_the_backdrop():
    """#833 regression: inside the AABB, outside the sphere, there is no medium."""
    x, y = _px_xy()
    corner = (np.abs(x) > 0.78) & (np.abs(x) < 0.95) & (np.abs(y) > 0.78) & (np.abs(y) < 0.95)
    q = _ratio_vs_empty(lambda r: _absorber(r, *ICO, 3.0), spp=64)
    assert corner.sum() >= 16
    assert abs(q[corner].mean() - 1.0) < 0.01, q[corner].mean()   # AABB path: ~exp(-6) = 0.002
    assert q[(x ** 2 + y ** 2) < 0.25].mean() < 0.02                # the sphere still absorbs


def test_icosphere_beer_lambert():
    ora = ortho_tr([(ICO[0], ICO[1], 1.0)], sub=2)
    q = _ratio_vs_empty(lambda r: _absorber(r, *ICO, 1.0), spp=256)
    x, y = _px_xy()
    rr = np.hypot(x, y)
    _check(q, ora, rr < 0.4, 256)                     # centre (chord ~2)
    _check(q, ora, (rr > 0.7) & (rr < 0.85), 256)     # limb ring


def test_overlapping_media_add():
    a = icosphere(3, 0.8, (-0.45, 0.0, 0.0))
    b = icosphere(3, 0.8, (0.45, 0.0, 0.0))
    ora = ortho_tr([(a[0], a[1], 0.8), (b[0], b[1], 0.8)], sub=2)
    q = _ratio_vs_empty(lambda r: (_absorber(r, *a, 0.8), _absorber(r, *b, 0.8)), spp=256)
    x, y = _px_xy()
    _check(q, ora, (np.abs(x) < 0.15) & (np.abs(y) < 0.3), 256)             # overlap lens
    _check(q, ora, (np.abs(np.abs(x) - 0.95) < 0.12) & (np.abs(y) < 0.3), 256)  # single


def test_nested_media_add():
    outer, inner = icosphere(3, 1.1), icosphere(3, 0.5)
    ora = ortho_tr([(outer[0], outer[1], 0.4), (inner[0], inner[1], 1.5)], sub=2)
    q = _ratio_vs_empty(lambda r: (_absorber(r, *outer, 0.4), _absorber(r, *inner, 1.5)),
                        spp=256)
    x, y = _px_xy()
    rr = np.hypot(x, y)
    _check(q, ora, rr < 0.3, 256)
    _check(q, ora, (rr > 0.65) & (rr < 0.95), 256)


@pytest.mark.parametrize("clip", [0.001, 0.5])
def test_camera_inside_medium(clip):
    """Camera at the origin inside an icosphere medium (no init pass): Tr from
    the clip start to the mesh exit, along the view axis."""
    sphere = icosphere(3, 2.0)
    sigma = 0.3
    q = _ratio_vs_empty(lambda r: _absorber(r, *sphere, sigma), spp=256,
                        ortho=False, eye=(0.0, 0.0, 0.0), clip=clip, vfov=10.0)
    # vfov 10 deg: the central 8x8 pixels are within 0.9 deg of the axis.
    c = slice(H // 2 - 4, H // 2 + 4)
    L = chord(sphere[0], sphere[1], np.zeros(3), np.array([0.0, 0.0, -1.0]), t0=clip)
    ora = np.full((H, W), np.exp(-sigma * L))
    mask = np.zeros((H, W), bool)
    mask[c, c] = True
    _check(q, ora, mask, 256, rel=0.015)


def test_grid_medium_clipped_to_sphere_boundary():
    """A uniform grid covering [-1.5, 1.5]^3 with an icosphere boundary: no
    density outside the sphere (oracle = Beer-Lambert on the sphere chord)."""
    n = 8
    vox = 3.0 / n
    i2o = [vox, 0, 0, -1.5, 0, vox, 0, -1.5, 0, 0, vox, -1.5, 0, 0, 0, 1]
    o2w = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]
    dens = np.ones((n, n, n), np.float32)
    V, F = ICO

    def build(r):
        r.set_volume_grid("g", dens, [0, 0, 0], i2o, o2w, density_scale=1.0,
                          color=[0, 0, 0], absorption_color=[0, 0, 0],
                          boundary_vertices=V, boundary_indices=F)
    q = _ratio_vs_empty(build, spp=256)
    ora = ortho_tr([(V, F, 1.0)], sub=2)
    x, y = _px_xy()
    rr = np.hypot(x, y)
    _check(q, ora, rr < 0.4, 256)
    corner = (np.abs(x) > 0.78) & (np.abs(x) < 0.95) & (np.abs(y) > 0.78) & (np.abs(y) < 0.95)
    assert abs(q[corner].mean() - 1.0) < 0.01, q[corner].mean()


def _clip_inside_box(gpu, ortho, clip=1.0, sigma=0.4, spp=64):
    """Camera at the origin inside an absorbing box medium [-3, 3]^3 looking -z
    at an emitter beyond the box (z = -5), near clip `clip`."""
    r = astroray.Renderer()
    if gpu:
        try:
            r.set_use_gpu(True)
        except Exception as e:  # noqa: BLE001 - CPU-only build
            pytest.skip(f"GPU unavailable: {e}")
        if not getattr(r, "gpu_available", False):
            pytest.skip("gpu_available is False")
    else:
        r.set_use_gpu(False)
    r.set_integrator("path_tracer")
    r.set_adaptive_sampling(False)
    r.set_background_color([0.0, 0.0, 0.0])
    r.set_seed(2966)
    _backdrop(r, z=-5.0, a=20.0)
    r.add_homogeneous_medium([-3, -3, -3], [3, 3, 3], density_scale=sigma,
                             color=[0, 0, 0], absorption_color=[0, 0, 0])
    kw = {"orthographic": True, "ortho_width": 1.0, "ortho_height": 1.0} if ortho else {}
    r.setup_camera([0, 0, 0], [0, 0, -1], [0, 1, 0], 10.0, 1.0, 0.0, 5.0, W, H,
                   clip_near=clip, **kw)
    img = np.asarray(r.render(spp, 8, None, False, -1, -1, -1, 0, -1), dtype=np.float64)
    c = slice(H // 2 - 6, H // 2 + 6)
    return img.reshape(H, W, 3)[c, c].reshape(-1, 3).mean(axis=0)


@pytest.mark.gpu
@pytest.mark.parametrize("ortho", [False, True], ids=["persp", "ortho"])
def test_gpu_camera_clip_start_skips_medium(ortho):
    """pkg296: bounded media on a camera ray start at the clip start on CPU and
    GPU alike (Cycles camera.h moves ray->P by nearclip*D): Tr = exp(-sigma *
    (3 - clip)) on the axis, GPU/CPU within 5 % per channel."""
    # #961: 256 spp. At 64 spp one seed's per-channel sigma is 0.005 (1.1 %), so
    # rtol 3 % was a 2.5-sigma single-seed gate; a changed RNG stream read 0.464
    # (8-seed mean 0.448, unbiased) and failed. Same tolerance, 2x less noise.
    cpu, gpu = _clip_inside_box(False, ortho, spp=256), _clip_inside_box(True, ortho, spp=256)
    ref = _clip_inside_box(False, ortho, sigma=0.0, spp=256)
    tr = cpu / ref
    assert np.allclose(tr, np.exp(-0.4 * 2.0), rtol=0.03), tr        # not exp(-0.4 * 3)
    assert (np.abs(gpu / cpu - 1.0) < 0.05).all(), (cpu, gpu)


def _scatter_box(r, boundary):
    mn, mx = (-0.8, -0.8, -0.8), (0.8, 0.8, 0.8)
    V, F = box(mn, mx)
    kw = {"boundary_vertices": V, "boundary_indices": F} if boundary else {}
    r.add_homogeneous_medium(list(mn), list(mx), density_scale=1.2, color=[0.9, 0.7, 0.5],
                             anisotropy=0.3, **kw)


def test_box_mesh_with_and_without_boundary_agree():
    means = {True: [], False: []}
    x, y = _px_xy()
    roi = (np.abs(x) < 0.5) & (np.abs(y) < 0.5)
    for b in (True, False):
        for s in SEEDS:
            r = _renderer(s, ortho=False, eye=(0.3, 0.2, 4.0))
            _backdrop(r)
            lamp = r.create_material("light", [1, 1, 1], {"intensity": 6.0})
            r.add_sphere([-2.0, 2.0, 1.5], 0.4, lamp)
            _scatter_box(r, b)
            means[b].append(_render(r, 64)[roi].mean(axis=0))
    a, c = np.array(means[True]), np.array(means[False])
    se = np.sqrt(a.var(0, ddof=1) / len(SEEDS) + c.var(0, ddof=1) / len(SEEDS))
    assert (np.abs(a.mean(0) - c.mean(0)) <= 3 * se + 1e-4).all(), (a.mean(0), c.mean(0), se)


def test_glass_shell_ior1_equals_bare_medium():
    """A dielectric (IOR 1.0) surface on the boundary mesh: the refracted ray
    starts on the boundary and must count as inside; the result equals the bare
    medium (Beer-Lambert oracle)."""
    V, F = ICO

    def build(r):
        g = r.create_material("glass", [1.0, 1.0, 1.0], {"ior": 1.0})
        for a, b, c in F:
            r.add_triangle(V[a].tolist(), V[b].tolist(), V[c].tolist(), g)
        _absorber(r, V, F, 1.0)
    q = _ratio_vs_empty(build, spp=256)
    ora = ortho_tr([(V, F, 1.0)], sub=2)
    x, y = _px_xy()
    _check(q, ora, np.hypot(x, y) < 0.5, 256, rel=0.03)


def _time_render(boundary, seed):
    # The corpus icosphere (Blender subdivisions=3 = 320 faces = sub 2 here),
    # the medium that main renders as its AABB, default NEE.
    r = _renderer(seed)
    _backdrop(r)
    V, F = icosphere(2, 1.0)
    kw = {"boundary_vertices": V, "boundary_indices": F} if boundary else {}
    r.add_homogeneous_medium([-1, -1, -1], [1, 1, 1], density_scale=1.5,
                             color=[0.9, 0.6, 0.3], **kw)
    t0 = time.perf_counter()
    _render(r, 256)
    return time.perf_counter() - t0


@pytest.mark.skipif(os.environ.get("ASTRORAY_PKG296_PERF") != "1",
                    reason="opt-in wall-time gate (ASTRORAY_PKG296_PERF=1; idle machine, "
                           "OMP_NUM_THREADS=1 for a stable ratio)")
def test_boundary_cost_within_1p3x_of_aabb():
    """Spec cost gate: the icosphere scene at equal spp, boundary vs the AABB
    path, interleaved, min of 5."""
    ta, tm = [], []
    for k in range(5):
        ta.append(_time_render(False, 2961 + k))
        tm.append(_time_render(True, 2961 + k))
    assert min(tm) <= 1.3 * min(ta), (min(tm), min(ta))


# --------------------------------------------------------------------------- #
# Blender level: volumes_mesh corpus vs Cycles (opt-in)
# --------------------------------------------------------------------------- #
BLENDER = Path(os.environ.get("ASTRORAY_BLENDER",
                              r"C:\Program Files\Blender Foundation\Blender 5.2\blender.exe"))
REFS = REPO / "benchmarks" / "reference_corpus" / "refs_v2"
VM_SCENES = ["vm_icosphere", "vm_icosphere_empty", "vm_suzanne", "vm_nested", "vm_overlap",
             "vm_camera_inside", "vm_glass_shell"]
# ROIs whose Astroray/Cycles ratio is NOT set by the boundary: the same
# divergence appears with the boundary code path unused (the mesh swapped for
# an exact-AABB cube, or the volume removed) on main and on this branch
# (pkg296 PR evidence). Tracked as follow-ups; they are reported, not gated.
PRE_EXISTING = {
    ("vm_icosphere", "b4", "centre"): "volume multi-scatter red deficit (cube control 0.955)",
    ("vm_nested", "b4", "centre"): "volume multi-scatter red deficit (cube control 0.955)",
    ("vm_overlap", "b4", "left"): "volume multi-scatter red deficit (cube control 0.955)",
    ("vm_overlap", "b4", "overlap"): "volume multi-scatter deficit (cube control 0.955)",
    ("vm_glass_shell", "b0", "rim"): "glass rim +7.5% with no volume at all",
    ("vm_glass_shell", "b4", "rim"): "glass rim +7.5% with no volume at all",
}


def _blender_ready():
    return (os.environ.get("ASTRORAY_PKG296_BLENDER") == "1" and BLENDER.is_file()
            and os.environ.get("ASTRORAY_PYD_DIR"))


@pytest.fixture(scope="module")
def astroray_bands():
    if not _blender_ready():
        pytest.skip("opt-in: ASTRORAY_PKG296_BLENDER=1, Blender 5.2 and ASTRORAY_PYD_DIR")
    ref = json.loads((REFS / "volumes_mesh_cycles.json").read_text(encoding="utf-8"))["meta"]
    work = Path(tempfile.mkdtemp(prefix="pkg296_"))
    out = work / "astroray_cpu.json"
    cmd = [str(BLENDER), "-b", "--factory-startup", "--threads", "8", "--python",
           str(REPO / "benchmarks" / "reference_corpus" / "volumes_mesh_bands.py"), "--",
           "--engine", "CUSTOM_RAYTRACER", "--device", "cpu", "--scenes", *VM_SCENES,
           "--seeds", *map(str, ref["seeds"]), "--bounces", *map(str, ref["bounces"]),
           "--spp", str(ref["spp"]), "--out-json", str(out), "--npy-dir", str(work)]
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=3600, check=False)
    assert "PKG296_BANDS PASS" in p.stdout, p.stdout[-2000:] + p.stderr[-1000:]
    return json.loads(out.read_text(encoding="utf-8"))["scenes"], work


def _ratio_rows(ours):
    cyc = json.loads((REFS / "volumes_mesh_cycles.json").read_text(encoding="utf-8"))["scenes"]
    for sid, per_b in ours.items():
        if sid.endswith("_empty"):
            continue
        for b, rec in per_b.items():
            for roi, va in rec["rois"].items():
                vc, va = np.array(cyc[sid][b]["rois"][roi]), np.array(va)
                mc, ma = vc.mean(0), va.mean(0)
                sc = vc.std(0, ddof=1) / np.maximum(mc, 1e-9)
                sa = va.std(0, ddof=1) / np.maximum(ma, 1e-9)
                tol = np.maximum(0.03, 3 * np.sqrt(sc ** 2 + sa ** 2) / np.sqrt(len(vc)))
                yield sid, b, roi, ma / np.maximum(mc, 1e-9), tol


def test_volumes_mesh_roi_means_match_cycles(astroray_bands):
    fails = [f"{s} {b} {roi}: ratio {np.round(r, 3)} tol {np.round(t, 3)}"
             for s, b, roi, r, t in _ratio_rows(astroray_bands[0])
             if (s, b, roi) not in PRE_EXISTING and (np.abs(r - 1) > t).any()]
    assert not fails, "\n".join(fails)


def test_icosphere_silhouette_iou_vs_cycles(astroray_bands):
    """Mask = |render - empty| > 0.02 on linear luminance (the Astroray
    backdrop's per-channel spectral noise would otherwise dominate), 5-seed mean."""
    work = astroray_bands[1]
    mask_ref = np.unpackbits(np.load(REFS / "vm_icosphere_mask_cycles.npy"))
    wts = np.array([0.2126, 0.7152, 0.0722])
    for b in ("b0", "b4"):
        a = np.load(work / f"vm_icosphere_{b}_astroray_cpu.npy") @ wts
        e = np.load(work / f"vm_icosphere_empty_{b}_astroray_cpu.npy") @ wts
        ma = (np.abs(a - e) > 0.02).ravel()
        mc = mask_ref[:ma.size].astype(bool)
        iou = (ma & mc).sum() / (ma | mc).sum()
        assert iou >= 0.98, (b, iou)
