#!/usr/bin/env python
"""pkg190 — GPU procedural-texture rendering: not-flat + CPU/GPU parity.

pkg186 added GPU sampling for IMAGE textures but collapsed every PROCEDURAL
texture node (checker / brick / wave / magic / …) to the material's flat
`getAlbedo()` on the GPU wavefront path. pkg190 bakes the CPU procedural
evaluator into a device buffer at scene-upload time and samples it on the GPU:
  * Generated coord mode → a res^3 VOXEL bake in [0,1]^3, sampled by the
    normalized Generated coordinate (gpu_sampleProcedural3D). This mirrors how
    the pkg119-B parity scenes drive procedurals (no TexCoord node → Blender
    default Generated) — the (a)-set the re-baseline convicted.
  * UV coord mode → a res^2 bake reusing the pkg186 2D UV image path.
  * Any OTHER coord mode (Object/Camera/Normal/Reflection/Window) → UNBAKED
    (PR #612 follow-up): the GPU shades the flat baseColor; see the
    Object-mode tests at the bottom of this file.

Acceptance gates (mirror test_pkg186_gpu_texture_parity):
  * test_gpu_procedural_is_not_flat — a GPU render of a Generated-coord checker
    must differ substantially from the same geometry rendered as flat albedo
    (proves the procedural is evaluated on the device, not dropped). Metrics on
    garbage pass, so we also assert real spatial colour contrast.
  * test_cpu_gpu_procedural_parity — per-channel MEAN-RATIO of CPU vs GPU within
    band (NOT SSIM: independent RNG streams — [[ssim-wrong-gate-for-independent-rng]]).
  * test_saturated_base_is_neutralised — the fold-guard (advisory #1, PR #590):
    a textured material's render is independent of its flat base-colour chroma
    (base is upload-neutralised so the albedo swap is an exact, unbiased texUp).

GPU-gated: skips when no CUDA device (CI has none); this is an RTX-box leg.
"""

import astroray
import numpy as np
import pytest
from base_helpers import create_renderer, render_image, setup_camera


def _has_cuda_gpu(renderer):
    return bool(astroray.__features__.get("cuda", False)) and \
        bool(getattr(renderer, "gpu_available", False))


# Generated-coord bbox for a quad spanning x,y in [-1,1]; z padded so the checker
# samples a fixed z-slice (a flat quad only intersects one plane of the 3D field).
_BBOX_MIN = [-1.0, -1.0, -1.0]
_BBOX_SIZE = [2.0, 2.0, 2.0]

# Checker cell colours: two saturated, contrasting colours so a flat-albedo drop
# is unmistakable and there is strong spatial variation to gate on.
_C1 = (0.9, 0.1, 0.1)   # red
_C2 = (0.1, 0.1, 0.9)   # blue
_CHECK_SCALE = 4.0      # cells across the normalized [0,1] bbox


def _add_checker_material(renderer, c1, c2, scale, base_color, name,
                          coord_mode="GENERATED"):
    # params: [c1.r,g,b, c2.r,g,b, scale] (module/blender_module.cpp checker path)
    renderer.create_procedural_texture(
        name, "checker",
        [c1[0], c1[1], c1[2], c2[0], c2[1], c2[2], scale], coord_mode)
    renderer.set_texture_generated_bbox(name, _BBOX_MIN, _BBOX_SIZE)
    return renderer.create_material("lambertian", list(base_color),
                                    {"texture": name})


def _build_scene(renderer, *, textured=True, base_color=(0.8, 0.8, 0.8),
                 c1=_C1, c2=_C2, coord_mode="GENERATED"):
    renderer.set_background_color([0.8, 0.8, 0.8])
    if textured:
        mat = _add_checker_material(renderer, c1, c2, _CHECK_SCALE, base_color,
                                    "pkg190_checker", coord_mode)
    else:
        mat = renderer.create_material("lambertian", list(base_color), {})

    # UV-mapped quad at z=0 facing the camera. UVs unused by the 3D Generated
    # path but kept so the geometry matches the pkg186 quad exactly.
    A, B = [-1, -1, 0], [1, -1, 0]
    C, D = [1, 1, 0], [-1, 1, 0]
    n = [0, 0, 1]
    renderer.add_triangle_layers(A, B, C, mat, {"UVMap": [[0, 0], [1, 0], [1, 1]]},
                                 n, n, n)
    renderer.add_triangle_layers(A, C, D, mat, {"UVMap": [[0, 0], [1, 1], [0, 1]]},
                                 n, n, n)
    setup_camera(renderer, look_from=[0, 0, 3], look_at=[0, 0, 0], vup=[0, 1, 0],
                 vfov=45, width=64, height=64)


def _render(*, textured=True, use_gpu=True, base_color=(0.8, 0.8, 0.8),
            c1=_C1, c2=_C2, samples=96, seed=1, coord_mode="GENERATED"):
    r = create_renderer()
    if use_gpu:
        if not _has_cuda_gpu(r):
            pytest.skip("No CUDA GPU available — pkg190 procedural gate runs on the RTX box.")
        r.set_use_gpu(True)
    # Pin the RNG so same-engine A/B renders (base-neutralisation) differ ONLY in
    # the variable under test, not MC noise (seed 0 is the random sentinel —
    # [[seed-zero-is-random-sentinel]]).
    r.set_seed(seed)
    _build_scene(r, textured=textured, base_color=base_color, c1=c1, c2=c2,
                 coord_mode=coord_mode)
    return render_image(r, samples=samples, max_depth=3, apply_gamma=False)


def _channel_means(img):
    return np.array([float(img[..., c].mean()) for c in range(3)])


def test_gpu_procedural_is_not_flat():
    """GPU checker render must differ from a flat render AND carry real spatial
    colour contrast (metrics pass on garbage — [[general-photon-loop-needs-solid-glass]])."""
    tex = _render(textured=True, use_gpu=True)
    flat = _render(textured=False, use_gpu=True)
    mean_abs_diff = float(np.abs(tex - flat).mean())
    assert mean_abs_diff > 0.05, (
        f"GPU procedural render too close to flat albedo (mean|diff|="
        f"{mean_abs_diff:.4f}); the checker was likely dropped on GPU."
    )
    # Red/blue checker → red channel must vary spatially (red cells vs blue cells).
    red = tex[..., 0]
    assert red.max() - red.min() > 0.1, (
        "GPU procedural render shows no red-channel spatial contrast — checker not applied."
    )


def test_cpu_gpu_procedural_parity():
    """Per-channel mean-ratio of CPU vs GPU checker render within band."""
    gpu = _render(textured=True, use_gpu=True)
    cpu = _render(textured=True, use_gpu=False)
    gm = _channel_means(gpu)
    cm = _channel_means(cpu)
    assert cm.mean() > 0.02, f"CPU reference too dark to gate: {cm}"
    assert gm.mean() > 0.02, f"GPU render too dark to gate: {gm}"
    ratio = gm / np.maximum(cm, 1e-6)
    for c, rc in enumerate(ratio):
        assert 0.80 <= rc <= 1.25, (
            f"channel {c} CPU/GPU mean-ratio {rc:.3f} out of band "
            f"[0.80,1.25]; cpu={cm}, gpu={gm}"
        )


def test_saturated_base_is_neutralised():
    """Fold-guard exactness: the textured render is INDEPENDENT of the material's
    flat base-colour chroma (base is upload-neutralised to (1,1,1), so the albedo
    swap divides by a fixed neutral reference — an exact, unbiased texUp). A
    saturated red base and a neutral base must render the same checker."""
    sat = _render(textured=True, use_gpu=True, base_color=(1.0, 0.0, 0.0))
    neu = _render(textured=True, use_gpu=True, base_color=(1.0, 1.0, 1.0))
    # Same RNG path/seed and identical geometry → the only difference would be a
    # base-chroma leak. Allow a hair of float noise.
    mean_abs_diff = float(np.abs(sat - neu).mean())
    assert mean_abs_diff < 0.01, (
        f"Textured render depends on base-colour chroma (mean|diff|="
        f"{mean_abs_diff:.4f}); the fold-guard is not neutralising the base."
    )


def _luminance_render(textured):
    """A direct GPU wavefront render with use_luminance_output=True (the
    non-visible / luminance-only band). render() first to build the BVH (no
    standalone build_acceleration binding), then the luminance-band render."""
    r = create_renderer()
    if not _has_cuda_gpu(r):
        pytest.skip("No CUDA GPU available — pkg190 luminance-band leg runs on the RTX box.")
    r.set_use_gpu(True)
    r.set_seed(1)
    _build_scene(r, textured=textured)
    render_image(r, samples=1, max_depth=2, apply_gamma=False)
    return np.asarray(
        astroray.cuda_wavefront_render(r, 96, 3, 1, 380.0, 780.0, True, True),
        dtype=np.float32)


def test_rgb_texture_luminance_band_covered():
    """Advisory #2 (PR #590): the RGB-texture × use_luminance_output (non-visible
    / luminance-only band) combination was untested. use_luminance_output is a
    SPECIALIST non-visible-band mode (luminance-avg RR + Rayleigh sky), so RGB
    textures are only meaningful in the visible band — the production wavefront
    render path runs use_luminance_output=False (see cuda_wavefront_render
    default and gpu_wavefront_snapshot.cu). This leg asserts the combination is
    DEFINED (finite, no NaN/inf) and that the texture is still APPLIED under the
    luminance band (textured != flat) — i.e. the per-λ fold is not silently
    dropped or undefined; it is not, however, a visible-band parity claim."""
    tex = _luminance_render(textured=True)
    flat = _luminance_render(textured=False)
    assert np.all(np.isfinite(tex)), "luminance-band textured render has non-finite pixels"
    assert np.all(np.isfinite(flat)), "luminance-band flat render has non-finite pixels"
    # The RGB texture must still influence the luminance-band result (red/blue
    # checker cells carry different luminance than the flat 0.8 base).
    mean_abs_diff = float(np.abs(tex - flat).mean())
    assert mean_abs_diff > 1e-4, (
        f"luminance-band render ignores the RGB texture (mean|tex-flat|="
        f"{mean_abs_diff:.2e}); the fold was dropped under use_luminance_output."
    )


# --- pkg190 follow-up (PR #612 review): Object-coord-mode convention ---------
# The 3D voxel bake stores the procedural field over the NORMALIZED Generated
# domain ([0,1]^3 over genMin/genSize). CPU CoordMode::Object passes the RAW
# unnormalized objectPoint (include/advanced_features.h CoordMode::Object) —
# no bbox normalization — so an Object-mode bake would diverge CPU<->GPU by
# construction. Convention pinned in src/gpu/scene_upload.cu: only Generated
# (3D) and UV (2D) coord modes are baked; Object-mode (and Camera/Normal/
# Reflection/Window) procedurals stay UNBAKED — the GPU shades the flat
# baseColor. DOCUMENTED DEGRADATION: Object-mode procedural detail is CPU-only
# until the CPU path gains the identical bbox normalization in lockstep.


def test_object_mode_procedural_cpu_evaluates():
    """CI-runnable CPU leg: CoordMode::Object procedurals still evaluate on the
    CPU (raw-objectPoint checker != flat albedo). CPU remains the reference for
    Object-mode procedurals under the degradation convention above."""
    cpu_tex = _render(textured=True, use_gpu=False, coord_mode="OBJECT")
    cpu_flat = _render(textured=False, use_gpu=False)
    mean_abs_diff = float(np.abs(cpu_tex - cpu_flat).mean())
    assert mean_abs_diff > 0.05, (
        f"CPU Object-mode procedural render too close to flat albedo "
        f"(mean|diff|={mean_abs_diff:.4f}); CPU stopped evaluating Object-mode "
        f"procedurals — the pinned degradation assumes it is the reference."
    )


def test_object_mode_procedural_gpu_guarded_fallback():
    """RTX leg: the GPU must NOT bake an Object-mode procedural into the
    normalized-domain voxel grid (that field is wrong by construction). The
    guarded fallback is the flat albedo: an unbaked TexturedLambertian uploads
    getAlbedo() == Vec3(0.5) (advanced_features.h — the documented pre-pkg190
    flatten), so with the same pinned seed the GPU Object-mode render must
    match a plain 0.5-gray lambertian render."""
    tex = _render(textured=True, use_gpu=True, coord_mode="OBJECT")
    flat = _render(textured=False, use_gpu=True, base_color=(0.5, 0.5, 0.5))
    mean_abs_diff = float(np.abs(tex - flat).mean())
    assert mean_abs_diff < 0.01, (
        f"GPU Object-mode render differs from flat albedo (mean|diff|="
        f"{mean_abs_diff:.4f}); an Object-mode procedural was baked/sampled on "
        f"the GPU despite the CPU passing raw unnormalized objectPoint — "
        f"CPU<->GPU divergence by construction (PR #612 review)."
    )
