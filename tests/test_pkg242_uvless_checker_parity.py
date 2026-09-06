#!/usr/bin/env python
"""pkg242 Phase 0 — UV-less procedural-texture GPU parity (the "checker
disappears on GPU" bug).

Reproduced baseline (2026-09-06, build f30bc5f, RTX 5070 Ti,
test_results/rebuild-handoff-20260906/checker-binding-*): a default-UV
CheckerTexture on two triangles WITHOUT authored UV layers gives CPU image
luminance std 0.4182 versus GPU 0.0330 — the GPU shades a flat surface.

Root cause (Terra): the CPU Triangle always defines (uv0,uv1,uv2) — the
implicit default domain uv0=(0,0),uv1=(1,0),uv2=(0,1) when no UV layer is
authored (include/astroray/shapes.h ctors) — so shapes.h interpolates a valid
rec.uv for a UV-less triangle and the CPU procedural/image sampler shades
correctly. GPU scene_upload.cu only set GTriangle.hasUV when
tri->hasUVLayers() was true, so a UV-less textured material uploaded no UVs
and the device base-colour fetch (stage_advance.cu, gated on ttri.hasUV) was
skipped.

Contract (pkg242 Phase 0): UV-less primitives use the SAME documented CPU
implicit UV domain; the GPU uploads exactly those fallback UVs. The fixture is
NOT changed to hide the mismatch.

Gates:
  * test_uvless_checker_cpu_has_contrast — CPU render of the UV-less checker
    must show real spatial contrast (luminance std > 0.3). CPU is the oracle;
    runs everywhere.
  * test_uvless_checker_cpu_gpu_parity — GPU-gated (skips without CUDA): the
    GPU/CPU luminance-std ratio must land in [0.8, 1.25] and CPU std must
    stay > 0.3. This is the fix verification the RTX box runs.
  * test_authored_uv_checker_cpu_regression — the authored-UV path is
    unaffected by this GPU-only upload change: the CPU render statistics are
    pinned to the branch-base (main @ 8ff3995) CPU values.
"""

import astroray
import numpy as np
import pytest
from base_helpers import create_renderer, render_image, setup_camera


def _has_cuda_gpu(renderer):
    return bool(astroray.__features__.get("cuda", False)) and \
        bool(getattr(renderer, "gpu_available", False))


# High-contrast black/white checker (mirrors the reproduced baseline, whose CPU
# std was 0.4182). Colours are channel-symmetric so the luminance metric is
# independent of the Rec.709 weighting.
_C1 = (0.02, 0.02, 0.02)   # near-black cell
_C2 = (0.98, 0.98, 0.98)   # near-white cell
_CHECK_SCALE = 4.0         # cells across the [0,1] UV domain


def _luminance(img):
    # Rec.709 luminance; "image luminance std" is the baseline metric.
    return 0.2126 * img[..., 0] + 0.7152 * img[..., 1] + 0.0722 * img[..., 2]


def _grid_means(lum, cells=8):
    """Downsample a luminance image to a cells×cells grid of block means.

    Cheap spatial fingerprint: a v-flipped or phase-shifted GPU checker has the
    same luminance std as the CPU (so the std-ratio gate passes) but a different
    spatial layout, which shows up as a low cross-correlation between the grids.
    """
    h, w = lum.shape
    ys = np.linspace(0, h, cells + 1).astype(int)
    xs = np.linspace(0, w, cells + 1).astype(int)
    out = np.empty((cells, cells), dtype=np.float64)
    for i in range(cells):
        for j in range(cells):
            out[i, j] = lum[ys[i]:ys[i + 1], xs[j]:xs[j + 1]].mean()
    return out


def _normalized_xcorr(a, b):
    """Zero-mean unit-variance (Pearson) cross-correlation of two grids."""
    a = a.ravel() - a.mean()
    b = b.ravel() - b.mean()
    denom = np.sqrt((a * a).sum() * (b * b).sum())
    if denom < 1e-12:
        return 0.0
    return float((a * b).sum() / denom)


def _build_scene(renderer, *, authored_uv):
    """Two triangles forming a quad at z=0 with a UV-mode CheckerTexture.

    authored_uv=False → add_triangle with NO uv args → the Triangle default
    domain uv0=(0,0),uv1=(1,0),uv2=(0,1) with uvLayers EMPTY (the bug repro).
    authored_uv=True  → add_triangle_layers with an explicit UVMap.
    """
    renderer.set_background_color([1.0, 1.0, 1.0])
    renderer.create_procedural_texture(
        "pkg242_checker", "checker",
        [_C1[0], _C1[1], _C1[2], _C2[0], _C2[1], _C2[2], _CHECK_SCALE], "UV")
    mat = renderer.create_material("lambertian", [0.5, 0.5, 0.5],
                                   {"texture": "pkg242_checker"})

    A, B = [-1, -1, 0], [1, -1, 0]
    C, D = [1, 1, 0], [-1, 1, 0]
    n = [0, 0, 1]
    if authored_uv:
        renderer.add_triangle_layers(A, B, C, mat,
                                     {"UVMap": [[0, 0], [1, 0], [1, 1]]}, n, n, n)
        renderer.add_triangle_layers(A, C, D, mat,
                                     {"UVMap": [[0, 0], [1, 1], [0, 1]]}, n, n, n)
    else:
        # No UV args → the implicit fallback-UV triangle (uvLayers empty).
        renderer.add_triangle(A, B, C, mat, n0=n, n1=n, n2=n)
        renderer.add_triangle(A, C, D, mat, n0=n, n1=n, n2=n)

    setup_camera(renderer, look_from=[0, 0, 3], look_at=[0, 0, 0], vup=[0, 1, 0],
                 vfov=45, width=64, height=64)


def _render(*, authored_uv, use_gpu):
    r = create_renderer()
    if use_gpu:
        if not _has_cuda_gpu(r):
            pytest.skip("No CUDA GPU available — pkg242 GPU leg runs on the RTX box.")
        r.set_use_gpu(True)
    else:
        r.set_use_gpu(False)
    r.set_seed(1)  # seed 0 is the random sentinel
    _build_scene(r, authored_uv=authored_uv)
    return render_image(r, samples=96, max_depth=3, apply_gamma=False)


@pytest.mark.cpu
def test_uvless_checker_cpu_has_contrast():
    """CPU oracle: the UV-less checker must actually show a checker (std > 0.3)."""
    cpu = _render(authored_uv=False, use_gpu=False)
    std = float(_luminance(cpu).std())
    assert std > 0.3, (
        f"CPU UV-less checker shows no spatial contrast (luminance std={std:.4f}); "
        "the fixture/oracle is broken — investigate before trusting the GPU gate."
    )


@pytest.mark.gpu
def test_uvless_checker_cpu_gpu_parity():
    """GPU must reproduce the CPU UV-less checker (the pkg242 fix verification)."""
    cpu = _render(authored_uv=False, use_gpu=False)
    gpu = _render(authored_uv=False, use_gpu=True)
    cpu_std = float(_luminance(cpu).std())
    gpu_std = float(_luminance(gpu).std())
    assert cpu_std > 0.3, f"CPU reference lost its checker (std={cpu_std:.4f})"
    ratio = gpu_std / max(cpu_std, 1e-6)
    assert 0.8 <= ratio <= 1.25, (
        f"GPU/CPU luminance-std ratio {ratio:.3f} out of band [0.8,1.25] "
        f"(cpu_std={cpu_std:.4f}, gpu_std={gpu_std:.4f}); UV-less checker still "
        "diverges on GPU."
    )
    # Spatial check: the std ratio alone would pass a v-flipped or phase-shifted
    # GPU checker (same contrast, wrong layout). Compare 8×8 block-mean grids by
    # normalized cross-correlation — a matching checker correlates ~1.0.
    xcorr = _normalized_xcorr(_grid_means(_luminance(cpu)),
                              _grid_means(_luminance(gpu)))
    assert xcorr > 0.9, (
        f"GPU checker layout does not match CPU (8×8 grid cross-correlation "
        f"{xcorr:.3f} <= 0.9); the checker may be v-flipped or phase-shifted "
        "even though its luminance std matches."
    )


# Pinned on the branch base (main @ 8ff3995) with a deterministic (seed=1) CPU
# render — captured with the CPU-only build of this worktree. This fix touches
# ONLY src/gpu/scene_upload.cu (a CUDA translation unit not compiled in a CPU
# build), so the CPU authored-UV render is byte-unchanged by construction. A raw
# float64 byte-hash is deliberately NOT used: CPU MC renders are not bit-
# reproducible across the MSVC-local vs GCC-CI toolchains
# ([[mingw_local_vs_gcc_ci_divergence]]). The atol=1e-2 pin is a structural
# guard — a dropped-UV regression flattens the checker (std→~0.03, means→the
# neutralised base), far outside this band, while cross-toolchain float drift
# stays well inside it. The slight per-channel asymmetry is the deterministic
# spectral RGB round-trip, not MC noise (verified identical across two renders).
_AUTHORED_UV_CPU_MEANS = np.array([0.685399, 0.687098, 0.674164])
_AUTHORED_UV_CPU_STD = 0.434213


@pytest.mark.cpu
def test_authored_uv_checker_cpu_regression():
    """The authored-UV CPU render is unaffected by the GPU-only upload fix."""
    cpu = _render(authored_uv=True, use_gpu=False)
    means = np.array([float(cpu[..., c].mean()) for c in range(3)])
    std = float(_luminance(cpu).std())
    assert np.allclose(means, _AUTHORED_UV_CPU_MEANS, atol=1e-2), (
        f"authored-UV CPU channel means drifted: {means} vs pinned "
        f"{_AUTHORED_UV_CPU_MEANS}"
    )
    assert abs(std - _AUTHORED_UV_CPU_STD) < 1e-2, (
        f"authored-UV CPU luminance std drifted: {std:.6f} vs pinned "
        f"{_AUTHORED_UV_CPU_STD:.6f}"
    )
