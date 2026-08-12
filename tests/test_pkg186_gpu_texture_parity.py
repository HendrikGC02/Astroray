#!/usr/bin/env python
"""pkg186 — GPU image-texture rendering: not-flat + CPU/GPU parity.

Before pkg186 the GPU render path had NO texture support: it uploaded one flat
`getAlbedo()` per material, so any textured (TexturedLambertian / image) material
silently rendered as flat 0.5 albedo on GPU. pkg186 adds a baked-buffer image
sampler (nearest, mirrors CPU ImageTexture::value) wired through the wavefront
shade path behind a `HasTexture` template so untextured scenes are unchanged.

These are the acceptance gates:
  * test_gpu_texture_is_not_flat — a GPU render of an image-textured quad must
    differ substantially from the same quad rendered as flat 0.5 albedo (proves
    the texture is actually sampled on GPU, not dropped).
  * test_cpu_gpu_texture_parity — per-channel MEAN-RATIO of the CPU vs GPU
    textured render within band (NOT SSIM: independent RNG streams make windowed
    SSIM unreachable at modest spp — see [[ssim-wrong-gate-for-independent-rng]]).

GPU-gated: skips when no CUDA device (CI has none); this is an RTX-box leg.
"""

import astroray
import numpy as np
import pytest
from base_helpers import create_renderer, render_image, setup_camera


def _has_cuda_gpu(renderer):
    return bool(astroray.__features__.get("cuda", False)) and \
        bool(getattr(renderer, "gpu_available", False))


# 2x2 image, four saturated colors so flat-0.5 albedo is unmistakably different
# and spatial variation is strong. Row-major (row 0 = top after the v-flip that
# both the CPU sampler and the GPU twin apply).
def _test_image():
    img = np.zeros((2, 2, 3), dtype=np.float32)
    img[0, 0] = (0.9, 0.05, 0.05)   # top-left  red
    img[0, 1] = (0.05, 0.9, 0.05)   # top-right green
    img[1, 0] = (0.05, 0.05, 0.9)   # bot-left  blue
    img[1, 1] = (0.9, 0.9, 0.05)    # bot-right yellow
    return img


def _build_scene(renderer, textured):
    """A UV-mapped quad at z=0 facing the camera, lit by a bright uniform world.
    `textured` True → TexturedLambertian(image); False → flat 0.5 lambertian."""
    renderer.set_background_color([0.8, 0.8, 0.8])
    if textured:
        img = _test_image()
        renderer.load_texture("pkg186_tex", img, 2, 2, "UV")
        mat = renderer.create_material("lambertian", [0.5, 0.5, 0.5],
                                       {"texture": "pkg186_tex"})
    else:
        mat = renderer.create_material("lambertian", [0.5, 0.5, 0.5], {})

    # Quad corners (CCW, normal +z) with UVs spanning [0,1]^2.
    A, B = [-1, -1, 0], [1, -1, 0]
    C, D = [1, 1, 0], [-1, 1, 0]
    n = [0, 0, 1]
    renderer.add_triangle_layers(A, B, C, mat, {"UVMap": [[0, 0], [1, 0], [1, 1]]},
                                 n, n, n)
    renderer.add_triangle_layers(A, C, D, mat, {"UVMap": [[0, 0], [1, 1], [0, 1]]},
                                 n, n, n)
    setup_camera(renderer, look_from=[0, 0, 3], look_at=[0, 0, 0], vup=[0, 1, 0],
                 vfov=45, width=64, height=64)


def _render(textured, use_gpu, samples=96):
    r = create_renderer()
    if use_gpu:
        if not _has_cuda_gpu(r):
            pytest.skip("No CUDA GPU available — pkg186 texture gate runs on the RTX box.")
        r.set_use_gpu(True)
    _build_scene(r, textured)
    # Linear (apply_gamma=False) so the comparison is on radiance, not tone-mapped.
    return render_image(r, samples=samples, max_depth=3, apply_gamma=False)


def _channel_means(img):
    return np.array([float(img[..., c].mean()) for c in range(3)])


def test_gpu_texture_is_not_flat():
    """The GPU textured render must differ from the GPU flat-0.5 render — proof
    the image is sampled on the device rather than collapsed to base albedo."""
    tex = _render(textured=True, use_gpu=True)
    flat = _render(textured=False, use_gpu=True)
    mean_abs_diff = float(np.abs(tex - flat).mean())
    assert mean_abs_diff > 0.05, (
        f"GPU textured render is too close to flat albedo (mean|diff|="
        f"{mean_abs_diff:.4f}); the texture was likely dropped on GPU."
    )
    # And the textured image must carry the color contrast the flat one cannot:
    # red channel should dominate somewhere (the red/yellow texels) and be near
    # zero elsewhere (blue/green texels).
    red = tex[..., 0]
    assert red.max() - red.min() > 0.1, (
        "GPU textured render shows no red-channel spatial contrast — texture not applied."
    )


def test_cpu_gpu_texture_parity():
    """Per-channel mean-ratio of CPU vs GPU textured render within band."""
    gpu = _render(textured=True, use_gpu=True)
    cpu = _render(textured=True, use_gpu=False)
    gm = _channel_means(gpu)
    cm = _channel_means(cpu)
    # Guard against a degenerate (all-black) render masking a real drop.
    assert cm.mean() > 0.02, f"CPU reference too dark to gate: {cm}"
    assert gm.mean() > 0.02, f"GPU render too dark to gate: {gm}"
    ratio = gm / np.maximum(cm, 1e-6)
    # Band mirrors the pkg119-B CPU/GPU parity-band tolerance (~0.88 dimness plus
    # MC noise); identical-engine CPU-vs-GPU is expected well inside it.
    for c, rc in enumerate(ratio):
        assert 0.80 <= rc <= 1.25, (
            f"channel {c} CPU/GPU mean-ratio {rc:.3f} out of band "
            f"[0.80,1.25]; cpu={cm}, gpu={gm}"
        )
