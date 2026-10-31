"""#1038 - smooth (delta) glass must carry the SAME spectral tint as rough glass.

The Principled/Glass delta branch of sampleSpectral (CPU) and gpu_material_sample_spectral
(GPU) upsampled tint x eta^2 (1-F) (or tint x F) as one RGB. Jakob-Hanika upsampling is
nonlinear in magnitude (upsample(k c) != k upsample(c)), so the material's spectrum changed
with the entry (k ~ 0.46) / exit (k ~ 2.0) magnitude, and a smooth sphere disagreed with the
rough (MULTI_GGX) sphere of the same Color by -3.4 % (R, Color (0.9, 1, 0.95)) to -6 %
(coloured light): a jump at the 0.03 delta-roughness threshold. The rough path is the
consistent one: the spectral product of a fixed material spectrum, proj(up(c)^2) (a direct
JH projection gives 0.843 for R, the rough render 0.844). Fixed by upsampling the tint and
applying the scalars linearly (memory: spectral-upsample-nonlinearity-scaled-bsdf).

Observable: centre of a smooth (r 0) vs a just-rough (r 0.035) glass sphere in a coloured
furnace, ratio per channel within 1 %. Before the fix: R 0.966 (white), 0.939 (blue-ish light).
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

_NEEDS_CUDA = pytest.mark.skipif(
    AVAILABLE and not astroray.__features__.get("cuda", False),
    reason="CUDA feature not in this build - GPU probe runs on the RTX box",
)

IOR = 1.45
CASES = [  # (furnace colour, Glass Color)
    ((1.0, 1.0, 1.0), (0.9, 1.0, 0.95)),       # the prod_light_path ball
    ((0.2, 0.45, 1.0), (0.9, 1.0, 0.95)),
    ((1.0, 0.45, 0.2), (0.6, 0.8, 0.7)),
]


def _centre(rough, bg, color, use_gpu):
    r = astroray.Renderer()
    r.set_background_color(list(bg))
    r.set_integrator("path_tracer")
    if use_gpu:
        r.set_use_gpu(True)
    # Glass BSDF encoding (addon _standalone_bsdf_spec): base_color = Color^2, specular_tint = Color.
    params = {"transmission_weight": 1.0, "ior": IOR, "roughness": rough,
              "specular_tint": list(color)}
    mid = r.create_material("principled", [c * c for c in color], params)
    r.add_sphere([0.0, 0.0, 0.0], 1.0, mid)
    r.setup_camera([0, 0, 4], [0, 0, 0], [0, 1, 0], 40.0, 1.0, 0.0, 4.0, 64, 64)
    r.set_seed(11)
    img = np.asarray(r.render(256, 32, None, False), dtype=np.float32).reshape(64, 64, 3)
    return img[28:36, 28:36].reshape(-1, 3).mean(axis=0)


def _assert_delta_matches_rough(use_gpu):
    bad = []
    for bg, color in CASES:
        delta = _centre(0.0, bg, color, use_gpu)      # roughness <= 0.03: delta glass branch
        rough = _centre(0.035, bg, color, use_gpu)    # MULTI_GGX rough glass branch
        ratio = delta / rough
        if np.any(np.abs(ratio - 1.0) > 0.01):
            bad.append((bg, color, np.round(delta, 4), np.round(rough, 4), np.round(ratio, 4)))
    assert not bad, f"smooth vs rough glass tint mismatch: {bad}"


def test_delta_glass_tint_matches_rough_glass_cpu():
    _assert_delta_matches_rough(use_gpu=False)


@pytest.mark.gpu
@_NEEDS_CUDA
def test_delta_glass_tint_matches_rough_glass_gpu():
    _assert_delta_matches_rough(use_gpu=True)


@pytest.mark.gpu
@_NEEDS_CUDA
def test_delta_glass_tint_gpu_matches_cpu():
    for bg, color in CASES:
        cpu = _centre(0.0, bg, color, use_gpu=False)
        gpu = _centre(0.0, bg, color, use_gpu=True)
        assert np.all(np.abs(gpu / cpu - 1.0) < 0.01), (bg, color, cpu, gpu)
