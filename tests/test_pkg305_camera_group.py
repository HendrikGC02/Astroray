"""pkg305 -- stratified camera group (pixel filter, lens, hero wavelength).

Unit gates on the shared __host__ __device__ sources:
  * include/astroray/sampling/sobol_burley.h -- bit-exact vs a Python port of
    Cycles kernel/sample/sobol_burley.h (Burley 2020, JCGT 9(4)), table, mask,
    2D / 1D stratification.
  * include/astroray/sampling/filter_table.h -- the tabulated-CDF filter sampler
    matches the analytic Gaussian / Blackman-Harris profile (chi2).
Render gates (CPU; GPU legs skip without CUDA): sky chroma floor, variance
slope, means unchanged, determinism, and progressive-chunk continuation.
"""
import os
import subprocess
import sys
import textwrap

import numpy as np
import pytest

th = pytest.importorskip("astroray_test_helpers")
import base_helpers as bh

# --------------------------------------------------------------------------- #
# Python port of Cycles (Apache-2.0) src/kernel/sample/sobol_burley.h,
# src/kernel/sample/util.h reversed_bit_owen, src/util/hash.h hash_hp_uint,
# src/kernel/tables.h sobol_burley_table.
# --------------------------------------------------------------------------- #
M32 = 0xFFFFFFFF

CYCLES_TABLE = [
    [1 << j for j in range(32)],
    [0x00000001, 0x00000003, 0x00000005, 0x0000000f, 0x00000011, 0x00000033,
     0x00000055, 0x000000ff, 0x00000101, 0x00000303, 0x00000505, 0x00000f0f,
     0x00001111, 0x00003333, 0x00005555, 0x0000ffff, 0x00010001, 0x00030003,
     0x00050005, 0x000f000f, 0x00110011, 0x00330033, 0x00550055, 0x00ff00ff,
     0x01010101, 0x03030303, 0x05050505, 0x0f0f0f0f, 0x11111111, 0x33333333,
     0x55555555, 0xffffffff],
    [0x00000001, 0x00000003, 0x00000006, 0x00000009, 0x00000017, 0x0000003a,
     0x00000071, 0x000000a3, 0x00000116, 0x00000339, 0x00000677, 0x000009aa,
     0x00001601, 0x00003903, 0x00007706, 0x0000aa09, 0x00010117, 0x0003033a,
     0x00060671, 0x000909a3, 0x00171616, 0x003a3939, 0x00717777, 0x00a3aaaa,
     0x01170001, 0x033a0003, 0x06710006, 0x09a30009, 0x16160017, 0x3939003a,
     0x77770071, 0xaaaa00a3],
    [0x00000001, 0x00000003, 0x00000004, 0x0000000a, 0x0000001f, 0x0000002e,
     0x00000045, 0x000000c9, 0x0000011b, 0x000002a4, 0x0000079a, 0x00000b67,
     0x0000101e, 0x0000302d, 0x00004041, 0x0000a0c3, 0x0001f104, 0x0002e28a,
     0x000457df, 0x000c9bae, 0x0011a105, 0x002a7289, 0x0079e7db, 0x00b6dba4,
     0x0100011a, 0x030002a7, 0x0400079e, 0x0a000b6d, 0x1f001001, 0x2e003003,
     0x45004004, 0xc900a00a],
]


def _rev(x):
    return int(f"{x & M32:032b}"[::-1], 2)


def _hash_hp(i):
    i &= M32
    i ^= i >> 16
    i = (i * 0x21F0AAAD) & M32
    i ^= i >> 15
    i = (i * 0xD35A2D97) & M32
    i ^= i >> 15
    return i ^ 0xE6FE3BEB


def _rbo(n, seed):
    n &= M32
    n ^= (n * 0x3D20ADEA) & M32
    n = (n + seed) & M32
    n = (n * ((seed >> 16) | 1)) & M32
    n ^= (n * 0x05526C56) & M32
    n ^= (n * 0x53A22864) & M32
    return n


def _to_float(n):
    return float(np.float32(n) * np.float32(1.0 / 4294967808.0))


def _sobol_burley(rev_index, dim, seed):
    result = 0
    if dim == 0:
        result = _rev(rev_index)
    else:
        i = 0
        while rev_index != 0:
            j = 32 - rev_index.bit_length()  # count_leading_zeros
            result ^= CYCLES_TABLE[dim][i + j]
            i += j + 1
            rev_index = (rev_index << (j + 1)) & M32
    return _to_float(_rev(_rbo(result, seed)))


def cy_1d(index, dim, seed, mask):
    seed ^= _hash_hp(dim)
    index = _rbo(_rev(index), seed ^ 0xBFF95BFE) & mask
    return _sobol_burley(index, 0, seed ^ 0x635C77BD)


def cy_2d(index, dim, seed, mask):
    seed ^= _hash_hp(dim)
    index = _rbo(_rev(index), seed ^ 0xF8ADE99A) & mask
    return (_sobol_burley(index, 0, seed ^ 0xE0AAAF76),
            _sobol_burley(index, 1, seed ^ 0x94964D4E))


def cy_mask(n):
    x = n - 1
    np2 = 1 if x == 0 else (1 << (32 - (32 - x.bit_length())))
    return _rev((np2 - 1) & M32)


# --------------------------------------------------------------------------- #
# Sampler unit gates
# --------------------------------------------------------------------------- #
def test_table_is_cycles_and_joe_kuo():
    got = list(th.sobol_burley_table())
    assert got == [v for row in CYCLES_TABLE for v in row]
    # First 30 entries == bit-reversed pkg224 Joe-Kuo direction numbers.
    for d in range(4):
        for j in range(30):
            assert CYCLES_TABLE[d][j] == _rev(th.sobol_direct(1 << j, d)), (d, j)


@pytest.mark.parametrize("n", [1, 2, 3, 16, 64, 65, 1000, 1 << 20])
def test_index_mask_matches_cycles(n):
    assert th.sobol_burley_index_mask(n) == cy_mask(n)
    assert th.sobol_burley_index_mask(0) == M32


def test_bit_exact_vs_cycles_port():
    rng = np.random.default_rng(305)
    for _ in range(400):
        idx = int(rng.integers(0, 1 << 32))
        dim = int(rng.integers(0, 64))
        seed = int(rng.integers(0, 1 << 32))
        mask = [M32, cy_mask(64), cy_mask(4096)][int(rng.integers(0, 3))]
        assert th.sobol_burley_1d(idx, dim, seed, mask) == cy_1d(idx, dim, seed, mask)
        a, b = th.sobol_burley_2d(idx, dim, seed, mask)
        ca, cb = cy_2d(idx, dim, seed, mask)
        assert (a, b) == (ca, cb), (idx, dim, seed, mask)


@pytest.mark.parametrize("dim_set", [0, 1, 2])
def test_2d_set_is_a_0m2_net(dim_set):
    n, m = 256, 8
    seed = th.sobol_burley_pixel_seed(1234, 99)
    mask = th.sobol_burley_index_mask(n)
    pts = np.array([th.sobol_burley_2d(i, dim_set, seed, mask) for i in range(n)])
    assert pts.min() >= 0.0 and pts.max() < 1.0
    for k in range(m + 1):  # every elementary interval of area 1/n holds one point
        gx, gy = 1 << k, 1 << (m - k)
        cells = np.floor(pts[:, 0] * gx).astype(int) * gy + np.floor(pts[:, 1] * gy).astype(int)
        assert np.bincount(cells, minlength=n).max() == 1, (dim_set, k)


def test_consecutive_seeds_are_independent():
    """Seeds 278..282 (corpus MC seeds) must not render the same set of
    per-pixel sequences (an unhashed seed XOR only permutes pixels)."""
    npx = 256 * 256
    a = {th.sobol_burley_pixel_seed(p, 278) for p in range(npx)}
    b = {th.sobol_burley_pixel_seed(p, 279) for p in range(npx)}
    assert len(a & b) < 0.01 * npx


def test_1d_hero_prefix_stratified():
    seed = th.sobol_burley_pixel_seed(7, 305)
    for n in (4, 16, 64):
        mask = th.sobol_burley_index_mask(n)
        u = np.array([th.sobol_burley_1d(i, 2, seed, mask) for i in range(n)])
        assert np.bincount(np.floor(u * n).astype(int), minlength=n).max() == 1


# --------------------------------------------------------------------------- #
# Filter table vs analytic profile (pkg203 width semantics)
# --------------------------------------------------------------------------- #
def _analytic_pdf(ftype, x, w):
    if ftype == 1:  # Gaussian sigma = w/4, truncated at +-1.5w
        return np.exp(-8.0 * x * x / (w * w))
    t = x / (2.0 * w) + 0.5  # Blackman-Harris over +-w
    p = 2.0 * np.pi * t
    return 0.35875 - 0.48829 * np.cos(p) + 0.14128 * np.cos(2 * p) - 0.01168 * np.cos(3 * p)


@pytest.mark.parametrize("ftype,width", [(1, 1.5), (1, 1.0), (2, 1.5), (2, 1.0)])
def test_filter_table_chi2(ftype, width):
    stats = pytest.importorskip("scipy.stats")
    half = (1.5 if ftype == 1 else 1.0) * width
    u = np.random.default_rng(ftype * 10 + int(width * 10)).random(400000)
    off = np.asarray(th.filter_table_sample(ftype, width, u.tolist()))
    assert off.min() >= -half - 1e-5 and off.max() <= half + 1e-5
    bins = np.linspace(-half, half, 41)
    obs, _ = np.histogram(off, bins)
    fine = np.linspace(-half, half, 40 * 400 + 1)
    dens = _analytic_pdf(ftype, 0.5 * (fine[1:] + fine[:-1]), width)
    exp = dens.reshape(40, 400).sum(1)
    exp = exp / exp.sum() * len(u)
    chi2 = float(((obs - exp) ** 2 / exp).sum())
    p = float(stats.chi2.sf(chi2, df=39))
    assert p > 1e-3, f"chi2={chi2:.1f} p={p:.2e}"


def test_filter_box_is_unit_uniform():
    u = np.linspace(0.0, 0.999, 1000)
    off = np.asarray(th.filter_table_sample(0, 3.0, u.tolist()))
    assert np.allclose(off, u - 0.5, atol=1e-7)  # width ignored (pkg203)


# --------------------------------------------------------------------------- #
# Render gates
# --------------------------------------------------------------------------- #
SKY = [0.25, 0.45, 0.9]


def _sky_renderer(seed, stratified, gpu=False, filt=None):
    r = bh.create_renderer()
    if gpu:
        try:
            r.set_use_gpu(True)
        except Exception as e:  # noqa: BLE001
            pytest.skip(f"GPU unavailable: {e}")
        if not getattr(r, "gpu_available", False):
            pytest.skip("gpu_available is False")
    elif hasattr(r, "set_use_gpu"):
        r.set_use_gpu(False)
    r.set_stratified_camera(stratified)
    r.set_seed(seed)
    if filt is not None:
        r.set_pixel_filter(*filt)
    r.set_background_color(SKY)
    grey = r.create_material("lambertian", [0.5, 0.5, 0.5], {})
    r.add_sphere([0.0, 0.0, -1000.0], 1.0, grey)  # out of view; non-empty BVH
    bh.setup_camera(r, look_from=[0, 0, 0], look_at=[0, 0, 1], vup=[0, 1, 0],
                    vfov=30, width=24, height=24)
    return r


def _render(r, spp):
    return np.asarray(r.render(spp, 4, None, False), dtype=np.float64)


def _rel_var(imgs):
    m = imgs.mean(0)
    v = imgs.var(0, ddof=1)
    return (v / np.maximum(m * m, 1e-12)).reshape(-1, 3).mean(0), m


# Seeds spaced apart: the CPU tile stream is mt19937(seed + tile), so seeds 1 and
# 2 would share streams across tiles and fake a low across-seed variance.
SEEDS = [1000 * k + 7 for k in range(1, 6)]


def _frame_mean_and_se(imgs):
    """Frame-mean colour and its standard error from per-pixel variances
    (pixels are independent: distinct per-pixel / per-tile streams)."""
    n, h, w, _ = imgs.shape
    var_p = imgs.var(0, ddof=1).reshape(-1, 3)
    return imgs.reshape(n, -1, 3).mean((0, 1)), np.sqrt(var_p.sum(0) / (h * w) ** 2 / n)


@pytest.mark.parametrize("gpu", [False, pytest.param(True, marks=pytest.mark.gpu)])
def test_sky_chroma_floor(gpu):
    """Directly seen sky: R/B relVar at 64 spp <= 2.4e-4 and >= 10x below the
    white-noise camera; luminance not worse; frame means within MC bands."""
    res = {}
    for stratified in (False, True):
        imgs = np.stack([_render(_sky_renderer(s, stratified, gpu), 64) for s in SEEDS])
        rv, _ = _rel_var(imgs)
        lum = imgs @ np.array([0.2126, 0.7152, 0.0722])
        lv = float((lum.var(0, ddof=1) / lum.mean(0) ** 2).mean())
        res[stratified] = (rv, lv) + _frame_mean_and_se(imgs)
    rv_off, lv_off, m_off, se_off = res[False]
    rv_on, lv_on, m_on, se_on = res[True]
    assert rv_on[0] <= 2.4e-4 and rv_on[2] <= 2.4e-4, rv_on
    assert rv_off[0] / rv_on[0] >= 10 and rv_off[2] / rv_on[2] >= 10, (rv_off, rv_on)
    assert lv_on <= lv_off, (lv_on, lv_off)
    z = (m_on - m_off) / np.sqrt(se_on ** 2 + se_off ** 2)
    assert np.all(np.abs(z) <= 3), (m_on, m_off, z)


def test_sky_variance_slope():
    """N x relVar falls with N (stratified), unlike white noise (flat)."""
    def nrv(spp):
        imgs = np.stack([_render(_sky_renderer(1000 * s + 3, True), spp) for s in range(1, 9)])
        return spp * _rel_var(imgs)[0][[0, 2]].mean()
    assert nrv(64) / nrv(4) <= 0.5


def test_progressive_chunks_continue_the_sequence():
    """Four 16-spp chunks at offsets 0/16/32/48 equal one 64-spp progressive
    render (background-only scene: radiance depends only on the camera group,
    and both use the full index mask and the same session seed)."""
    one = _sky_renderer(305, True)
    one.set_progressive_sample_offset(0)
    full = _render(one, 64)
    r = _sky_renderer(305, True)
    acc = np.zeros_like(full)
    for k in range(4):
        r.set_progressive_sample_offset(16 * k)
        acc += _render(r, 16)
    assert np.allclose(acc / 4.0, full, rtol=1e-5, atol=1e-7)
    # Without continuation (offset 0 replayed) the chunks repeat each other.
    r.set_progressive_sample_offset(0)
    first = _render(r, 16)
    r.set_progressive_sample_offset(0)
    assert np.array_equal(first, _render(r, 16))


def _edge_scene(seed, stratified):
    """Emitter disc on a dark background: edge pixels see only pixel-filter
    (anti-aliasing) variance plus the hero-wavelength chroma."""
    r = bh.create_renderer()
    if hasattr(r, "set_use_gpu"):
        r.set_use_gpu(False)
    r.set_stratified_camera(stratified)
    r.set_seed(seed)
    r.set_background_color([0.02, 0.02, 0.02])
    lamp = r.create_material("light", [1.0, 1.0, 1.0], {"intensity": 1.0})
    r.add_sphere([0.0, 0.0, 0.0], 1.0, lamp)
    bh.setup_camera(r, look_from=[0, 0, 5], look_at=[0, 0, 0], vup=[0, 1, 0],
                    vfov=30, width=32, height=32)
    return r


def test_edge_aa_variance():
    """Anti-aliased edges: N x relVar of the edge pixels' luminance at 16 spp
    is <= 0.8x the white-noise camera (pkg305 edge-AA gate)."""
    lum = np.array([0.2126, 0.7152, 0.0722])
    seeds = [7919 * k + 5 for k in range(1, 13)]
    rv = {}
    for stratified in (False, True):
        imgs = np.stack([_render(_edge_scene(s, stratified), 16) @ lum for s in seeds])
        rv[stratified] = imgs.var(0, ddof=1) / np.maximum(imgs.mean(0) ** 2, 1e-12)
        mean = imgs.mean(0)
    edge = (mean > 0.2 * mean.max()) & (mean < 0.8 * mean.max())
    assert edge.sum() >= 20
    ratio = float(rv[True][edge].mean() / rv[False][edge].mean())
    assert ratio <= 0.8, ratio


@pytest.mark.gpu
def test_gpu_camera_group_samples_match_cpu():
    """CPU and GPU draw the same camera-group tuple per (pixel, sample): with a
    defocused emitter disc, BH filter and aperture, GPU vs CPU at one seed differ
    far less than CPU vs CPU at two seeds (filter, lens and hero conventions)."""
    def rend(seed, gpu):
        r = _edge_scene(seed, True)
        if gpu:
            try:
                r.set_use_gpu(True)
            except Exception as e:  # noqa: BLE001
                pytest.skip(f"GPU unavailable: {e}")
            if not getattr(r, "gpu_available", False):
                pytest.skip("gpu_available is False")
        r.set_pixel_filter(2, 1.5)
        bh.setup_camera(r, look_from=[0, 0, 5], look_at=[0, 0, 0], vup=[0, 1, 0],
                        vfov=30, width=32, height=32, aperture=0.3, focus_dist=3.5)
        return _render(r, 16)
    cpu_a, cpu_b, gpu_a = rend(305, False), rend(306, False), rend(305, True)
    edge = np.abs(cpu_a - cpu_b).max(-1) > 0.0
    d_gc = float(np.abs(gpu_a - cpu_a)[edge].mean())
    d_cc = float(np.abs(cpu_b - cpu_a)[edge].mean())
    assert edge.sum() >= 20
    # Measured: d_gc 0.21x d_cc (residual = float/lens-model differences); the
    # legacy GPU camera gives 1.5x, an independent stream 1.0x.
    assert d_gc < 0.35 * d_cc, (d_gc, d_cc)


def _lit_scene(seed, stratified):
    r = bh.create_renderer()
    if hasattr(r, "set_use_gpu"):
        r.set_use_gpu(False)
    r.set_stratified_camera(stratified)
    r.set_seed(seed)
    r.set_pixel_filter(2, 1.5)
    r.set_background_color([0.05, 0.05, 0.08])
    red = r.create_material("lambertian", [0.8, 0.2, 0.2], {})
    lamp = r.create_material("light", [1.0, 0.9, 0.8], {"intensity": 6.0})
    r.add_sphere([0.0, 0.0, 0.0], 1.0, red)
    r.add_sphere([2.0, 3.0, 2.0], 0.6, lamp)
    bh.setup_camera(r, look_from=[0, 0, 5], look_at=[0, 0, 0], vup=[0, 1, 0],
                    vfov=35, width=32, height=32)
    return r


def test_lit_scene_means_unchanged():
    seeds = [7919 * k + 13 for k in range(1, 25)]
    rois = {}
    for stratified in (False, True):
        imgs = np.stack([_render(_lit_scene(s, stratified), 16) for s in seeds])
        rois[stratified] = imgs[:, 8:24, 8:24].reshape(len(seeds), -1, 3).mean(1)
    d = rois[True].mean(0) - rois[False].mean(0)
    se = np.sqrt((rois[True].var(0, ddof=1) + rois[False].var(0, ddof=1)) / len(seeds))
    assert np.all(np.abs(d) <= 3 * se), (d, se)


def test_fixed_seed_deterministic_and_seed0_random():
    a = _render(_lit_scene(42, True), 8)
    b = _render(_lit_scene(42, True), 8)
    assert np.array_equal(a, b)
    c = _render(_lit_scene(0, True), 8)
    d = _render(_lit_scene(0, True), 8)
    assert not np.array_equal(c, d)


def test_deterministic_across_thread_counts():
    here = os.path.dirname(os.path.abspath(__file__))
    code = textwrap.dedent(f"""
        import sys, hashlib
        sys.path.insert(0, {here!r})
        import runtime_setup; runtime_setup.configure_test_imports()
        import numpy as np
        import test_pkg305_camera_group as t
        img = t._render(t._lit_scene(42, True), 8)
        print(hashlib.sha256(np.ascontiguousarray(img).tobytes()).hexdigest())
    """)
    digests = []
    for n in ("1", "8"):
        env = dict(os.environ, OMP_NUM_THREADS=n)
        out = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True,
                             text=True, timeout=300, cwd=here, check=False)
        assert out.returncode == 0, out.stderr[-2000:]
        digests.append(out.stdout.strip().splitlines()[-1])
    assert digests[0] == digests[1]
