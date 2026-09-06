#!/usr/bin/env python
"""pkg242 Phase 1 — one transformed-coordinate contract for procedural bake
domains (CPU + GPU).

Before pkg242, the HitRecord overloads of ``Texture::value/valueOffset/
sampleSpectral`` mapped only the 2-D image sample coordinate ``(M*p).xy`` and
still fed the UNTRANSFORMED point ``p`` to the procedural evaluator, so a
Mapping node had no effect on Checker/Wave/Noise. The GPU bake likewise
evaluated procedurals in the original bake domain. pkg242 folds the SAME 3-D
Mapping transform into both:

  * CPU: ``value(HitRecord)`` now samples the procedural at ``mp = M*p``.
  * GPU: ``scene_upload.cu`` bakes the field at ``mp`` too, so the device fetch
    stays transform-agnostic (no new per-hit shade state).

The contract, in five lines:
  1. Procedural Checker/Wave/Noise sample at mp = M*p (M = 3x4 affine, row-major)
     — identically in the CPU HitRecord overloads and the folded GPU bake.
  2. Chain = Blender POINT Mapping (location + XYZ rotation + scale; mirror =
     negative scale); the SAME M drives both backends.
  3. hasMapping==false is byte-identical to pre-pkg242 (legacy path untouched).
  4. A singular (det~0) Mapping is reported visibly, not silently flattened.
  5. The GPU procedural-bake dedup key includes the transform, so a Mapping edit
     re-bakes.

Point-wise oracles use ``sample_named_texture_mapped`` (a thin binding that runs
mp = mappedPoint((u,v,0)); value(mp.xy, mp) — exactly the UV-mode HitRecord
overload) so the coordinate contract is asserted against a Python reimpl of the
Cycles procedural math WITHOUT render noise. The gpu-marked render twin then
asserts CPU/GPU spatial parity.
"""

import math

import astroray
import numpy as np
import pytest
from base_helpers import create_renderer, render_image, setup_camera


def _has_cuda_gpu(renderer):
    return bool(astroray.__features__.get("cuda", False)) and \
        bool(getattr(renderer, "gpu_available", False))


# ---------------------------------------------------------------------------
# Affine Mapping matrix builder (Blender POINT: out = loc + Rot @ (scale * in)).
# The SAME matrix is handed to C++ (set_texture_mapping_matrix) and applied in
# Python for the analytic oracle, so the test pins the C++ apply + procedural
# math, independent of any Blender-side composition.
# ---------------------------------------------------------------------------
def _affine(scale=(1, 1, 1), rot_z_deg=0.0, offset=(0, 0, 0)):
    sx, sy, sz = scale
    c, s = math.cos(math.radians(rot_z_deg)), math.sin(math.radians(rot_z_deg))
    # L = Rot_z @ diag(scale)
    L = [[c * sx, -s * sy, 0.0],
         [s * sx,  c * sy, 0.0],
         [0.0,     0.0,    sz]]
    ox, oy, oz = offset
    return [L[0][0], L[0][1], L[0][2], ox,
            L[1][0], L[1][1], L[1][2], oy,
            L[2][0], L[2][1], L[2][2], oz]


def _apply(matrix, p):
    x, y, z = p
    m = matrix
    return (m[0] * x + m[1] * y + m[2] * z + m[3],
            m[4] * x + m[5] * y + m[6] * z + m[7],
            m[8] * x + m[9] * y + m[10] * z + m[11])


# ---- Python reimplementations of the Cycles procedural math (parity oracles) --
def _checker_expected(mp, scale, c1, c2):
    # include/advanced_features.h CheckerTexture::value (Cycles svm_checker).
    sp = [(mp[i] * scale + 1e-6) * 0.999999 for i in range(3)]
    xi = abs(math.floor(sp[0]))
    yi = abs(math.floor(sp[1]))
    zi = abs(math.floor(sp[2]))
    parity = (xi % 2 == yi % 2) == (zi % 2)
    return c1 if parity else c2   # ctor: odd=c1 → parity-true returns c1


def _checker_boundary_dist(mp, scale):
    """Distance (in cell units) from the nearest integer cell boundary in x/y —
    used to skip float32-vs-float64 parity flips right on a Checker edge. Only
    x,y are considered: for a 2-D (UV) transform z stays ~0 (sp.z ~ 1e-6, floor
    always 0), so it never flips and must not disqualify every sample."""
    d = 1.0
    for i in (0, 1):
        sp = (mp[i] * scale + 1e-6) * 0.999999
        d = min(d, abs(sp - round(sp)))
    return d


def _wave_bands_x_sine_expected(mp, scale):
    # include/advanced_features.h WaveTexture::value, wave_type=bands, dir=X,
    # profile=sine, distortion=0 → value = Vec3(t).
    pp = [(mp[i] + 1e-6) * 0.999999 * scale for i in range(3)]
    n = pp[0] * 20.0
    return 0.5 + 0.5 * math.sin(n - math.pi / 2.0)


_GRID = [(u, v)
         for u in np.linspace(0.05, 0.95, 10)
         for v in np.linspace(0.05, 0.95, 10)]

_C1 = (0.02, 0.02, 0.02)
_C2 = (0.98, 0.98, 0.98)
_CHECK_SCALE = 4.0


def _make_checker(name="pkg242_chk"):
    r = create_renderer()
    r.set_use_gpu(False)
    r.create_procedural_texture(
        name, "checker",
        [_C1[0], _C1[1], _C1[2], _C2[0], _C2[1], _C2[2], _CHECK_SCALE], "UV")
    return r, name


# ===========================================================================
# Point-wise analytic oracles — CPU, run everywhere.
# ===========================================================================
@pytest.mark.cpu
@pytest.mark.parametrize("label,matrix", [
    ("identity", _affine()),
    ("offset",   _affine(offset=(0.3, 0.15, 0.0))),
    ("scale",    _affine(scale=(2.0, 3.0, 1.0))),
    ("rotate30", _affine(rot_z_deg=30.0)),
    ("mirror_x", _affine(scale=(-1.0, 1.0, 1.0))),
])
def test_checker_transformed_coordinate_oracle(label, matrix):
    """Checker under rotation/offset/scale/mirror matches the analytic cell
    parity computed from mp = M*(u,v,0)."""
    r, name = _make_checker()
    r.set_texture_mapping_matrix(name, matrix)
    checked = 0
    for (u, v) in _GRID:
        mp = _apply(matrix, (u, v, 0.0))
        if _checker_boundary_dist(mp, _CHECK_SCALE) < 0.02:
            continue  # skip points sitting on a cell edge (float32 flip risk)
        exp = _checker_expected(mp, _CHECK_SCALE, _C1, _C2)
        got = r.sample_named_texture_mapped(name, float(u), float(v))
        assert np.allclose(got, exp, atol=1e-3), (
            f"[{label}] checker @({u:.2f},{v:.2f}) mp={mp}: got {got} exp {exp}")
        checked += 1
    assert checked > 40, f"[{label}] too few off-boundary samples ({checked})"


@pytest.mark.cpu
def test_checker_offset_by_one_cell_inverts():
    """A whole-domain analytic invariant independent of the sampler internals:
    offsetting the checker by ONE cell in x inverts it; by TWO cells restores
    it. (One cell in p-space = 1/scale.)"""
    r, name = _make_checker()
    one_cell = 1.0 / _CHECK_SCALE
    base = _affine()
    r.set_texture_mapping_matrix(name, base)
    pts = [(0.12, 0.37), (0.62, 0.13), (0.88, 0.66), (0.41, 0.91)]
    base_vals = [r.sample_named_texture_mapped(name, u, v)[0] for (u, v) in pts]

    r2, n2 = _make_checker("pkg242_chk_1")
    r2.set_texture_mapping_matrix(n2, _affine(offset=(one_cell, 0.0, 0.0)))
    for (u, v), b in zip(pts, base_vals):
        got = r2.sample_named_texture_mapped(n2, u, v)[0]
        assert abs(got - (1.0 - b)) < 0.05 or abs(b - 0.5) < 0.1, (
            f"one-cell x offset did not invert checker @({u},{v}): {got} vs ~{1-b}")

    r3, n3 = _make_checker("pkg242_chk_2")
    r3.set_texture_mapping_matrix(n3, _affine(offset=(2 * one_cell, 0.0, 0.0)))
    for (u, v), b in zip(pts, base_vals):
        got = r3.sample_named_texture_mapped(n3, u, v)[0]
        assert abs(got - b) < 0.05, (
            f"two-cell x offset did not restore checker @({u},{v}): {got} vs {b}")


@pytest.mark.cpu
def test_wave_under_scale_oracle():
    """Wave (bands-X, sine) under an x-scale mapping matches the analytic
    frequency-scaled profile."""
    r = create_renderer()
    r.set_use_gpu(False)
    name = "pkg242_wave"
    scale = 2.0
    # [wave_type, bands_dir(X=0), rings_dir, profile(sine=0), scale, dist=0, ...]
    r.create_procedural_texture(
        name, "wave",
        [0, 0, 0, 0, scale, 0.0, 2.0, 1.0, 0.5, 0.0,
         0, 0, 0, 1, 1, 1], "UV")
    matrix = _affine(scale=(2.0, 1.0, 1.0))
    r.set_texture_mapping_matrix(name, matrix)
    for (u, v) in _GRID:
        mp = _apply(matrix, (u, v, 0.0))
        exp = _wave_bands_x_sine_expected(mp, scale)
        got = r.sample_named_texture_mapped(name, float(u), float(v))
        assert np.allclose(got, [exp, exp, exp], atol=2e-3), (
            f"wave @({u:.2f},{v:.2f}): got {got} exp {exp}")


@pytest.mark.cpu
def test_noise_identity_invariant_offset_differs():
    """Noise is invariant under an identity Mapping (matches the untransformed
    raw sample) and changes under an offset (the transform reaches p).

    Noise is a hash (frac(sin(.)*43758.5)), so its value amplifies float32-vs-
    float64 rounding; a value-level float64 oracle is not reproducible. The
    contract we CAN assert exactly is invariance under identity (both legs run in
    C++ float32) and that an offset actually perturbs p."""
    r = create_renderer()
    r.set_use_gpu(False)
    name = "pkg242_noise"
    scale = 1.0
    r.create_procedural_texture(name, "noise", [scale], "UV")

    # identity Mapping == no-mapping raw sample (both C++ float32 → exact).
    r.set_texture_mapping_matrix(name, _affine())
    diffs = 0
    for (u, v) in _GRID:
        got_mapped = r.sample_named_texture_mapped(name, float(u), float(v))
        got_raw = r.sample_named_texture(name, float(u), float(v))
        assert np.allclose(got_mapped, got_raw, atol=1e-5), (
            f"identity map changed noise @({u},{v}): {got_mapped} vs {got_raw}")

    # offset Mapping moves p → most samples change.
    r2 = create_renderer()
    r2.set_use_gpu(False)
    r2.create_procedural_texture(name, "noise", [scale], "UV")
    r2.set_texture_mapping_matrix(name, _affine(offset=(0.37, 0.21, 0.0)))
    for (u, v) in _GRID:
        base = r.sample_named_texture(name, float(u), float(v))[0]
        got = r2.sample_named_texture_mapped(name, float(u), float(v))[0]
        if abs(got - base) > 1e-3:
            diffs += 1
    assert diffs > 80, f"offset Mapping barely changed noise ({diffs}/100 differ)"


# ===========================================================================
# Singular / mirror reporting.
# ===========================================================================
@pytest.mark.cpu
def test_singular_mapping_reported_visibly(capfd):
    """A zero-scale (singular) Mapping is reported on stderr, not silently
    flattened."""
    r, name = _make_checker("pkg242_sing")
    r.set_texture_mapping_matrix(name, _affine(scale=(0.0, 0.0, 0.0)))
    err = capfd.readouterr().err
    assert "[pkg242]" in err and "singular" in err.lower(), (
        f"singular Mapping was not reported visibly; stderr={err!r}")
    # It also collapses the field to a constant (all samples equal).
    vals = [r.sample_named_texture_mapped(name, u, v)[0] for (u, v) in _GRID]
    assert np.std(vals) < 1e-4, f"singular map did not flatten checker (std={np.std(vals)})"


# ===========================================================================
# Untransformed baseline — byte-identical regression pin.
# The CPU procedural change lives entirely in the hasMapping_ branch, so a
# render with NO Mapping is unchanged. Pin means+std like the pkg242 uvless
# test (a raw byte hash is not cross-toolchain reproducible for MC renders).
# ===========================================================================
def _luminance(img):
    return 0.2126 * img[..., 0] + 0.7152 * img[..., 1] + 0.0722 * img[..., 2]


def _render_checker(use_gpu, mapping=None, samples=96):
    r = create_renderer()
    if use_gpu:
        if not _has_cuda_gpu(r):
            pytest.skip("No CUDA GPU — pkg242 GPU leg runs on the RTX box.")
        r.set_use_gpu(True)
    else:
        r.set_use_gpu(False)
    r.set_seed(1)
    r.set_background_color([1.0, 1.0, 1.0])
    r.create_procedural_texture(
        "pkg242_r_chk", "checker",
        [_C1[0], _C1[1], _C1[2], _C2[0], _C2[1], _C2[2], _CHECK_SCALE], "UV")
    if mapping is not None:
        r.set_texture_mapping_matrix("pkg242_r_chk", mapping)
    mat = r.create_material("lambertian", [0.5, 0.5, 0.5],
                            {"texture": "pkg242_r_chk"})
    A, B, C, D = [-1, -1, 0], [1, -1, 0], [1, 1, 0], [-1, 1, 0]
    n = [0, 0, 1]
    r.add_triangle_layers(A, B, C, mat, {"UVMap": [[0, 0], [1, 0], [1, 1]]}, n, n, n)
    r.add_triangle_layers(A, C, D, mat, {"UVMap": [[0, 0], [1, 1], [0, 1]]}, n, n, n)
    setup_camera(r, look_from=[0, 0, 3], look_at=[0, 0, 0], vup=[0, 1, 0],
                 vfov=45, width=64, height=64)
    return render_image(r, samples=samples, max_depth=3, apply_gamma=False)


# Pinned on this branch's CPU-only build (seed=1, 96 spp, apply_gamma=False).
# The pkg242 CPU change lives entirely in the hasMapping_ branch, so the
# no-Mapping render is byte-unchanged by construction; these are identical to
# the pkg242 uvless test's authored-UV pin (same scene). atol=1e-2 is a
# structural guard (a dropped-transform regression would flatten the checker
# far outside this band) tolerant of MSVC-vs-GCC MC float drift
# ([[mingw_local_vs_gcc_ci_divergence]]).
_BASELINE_MEANS = np.array([0.685399, 0.687098, 0.674164])
_BASELINE_STD = 0.434213


@pytest.mark.cpu
def test_untransformed_baseline_pinned():
    """The no-Mapping CPU checker render is byte-identical to pre-pkg242 (pinned
    means+std)."""
    cpu = _render_checker(use_gpu=False, mapping=None)
    means = np.array([float(cpu[..., c].mean()) for c in range(3)])
    std = float(_luminance(cpu).std())
    assert np.allclose(means, _BASELINE_MEANS, atol=1e-2), (
        f"untransformed checker means drifted: {means} vs {_BASELINE_MEANS}")
    assert abs(std - _BASELINE_STD) < 1e-2, (
        f"untransformed checker std drifted: {std} vs {_BASELINE_STD}")


# ===========================================================================
# GPU parity twin — the RTX box runs this after the lead's CUDA build.
# ===========================================================================
def _grid_means(lum, cells=8):
    h, w = lum.shape
    ys = np.linspace(0, h, cells + 1).astype(int)
    xs = np.linspace(0, w, cells + 1).astype(int)
    out = np.empty((cells, cells), dtype=np.float64)
    for i in range(cells):
        for j in range(cells):
            out[i, j] = lum[ys[i]:ys[i + 1], xs[j]:xs[j + 1]].mean()
    return out


def _xcorr(a, b):
    a = a.ravel() - a.mean()
    b = b.ravel() - b.mean()
    denom = math.sqrt((a * a).sum() * (b * b).sum())
    return 0.0 if denom < 1e-12 else float((a * b).sum() / denom)


@pytest.mark.gpu
@pytest.mark.parametrize("label,matrix", [
    ("scale",    _affine(scale=(2.0, 2.0, 1.0))),
    ("offset",   _affine(offset=(0.25, 0.125, 0.0))),
    ("rotate30", _affine(rot_z_deg=30.0)),
])
def test_transformed_checker_cpu_gpu_parity(label, matrix):
    """A Mapping-transformed procedural checker renders the same on CPU and GPU:
    8x8 block-mean cross-correlation > 0.9 (the transform reached the folded
    GPU bake, not dropped)."""
    cpu = _render_checker(use_gpu=False, mapping=matrix)
    gpu = _render_checker(use_gpu=True, mapping=matrix)
    cpu_std = float(_luminance(cpu).std())
    assert cpu_std > 0.2, f"[{label}] CPU reference lost its checker (std={cpu_std:.4f})"
    xcorr = _xcorr(_grid_means(_luminance(cpu)), _grid_means(_luminance(gpu)))
    assert xcorr > 0.9, (
        f"[{label}] transformed checker CPU/GPU layout mismatch "
        f"(8x8 cross-correlation {xcorr:.3f} <= 0.9)")
