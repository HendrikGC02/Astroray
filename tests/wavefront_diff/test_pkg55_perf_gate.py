"""pkg55 Phase-B performance gate — wavefront vs megakernel on the
balanced 7-material Disney contact sheet (tests/scenes/disney_contact_sheet).

Spec: pkg55-wavefront-soa-refactor.md Phase B acceptance — ">= 1.5x faster
than the megakernel ... 7 material types, 512 SPP, end-to-end frame time on
RTX 5070 Ti". Reference: Laine, Karras, Aila 2013 (2x+ in material-diverse
scenes); Cycles X Koro 2.2x.

Two tiers (the repo's established aspirational-gate pattern):
- HARD floor: speedup >= 1.15x — regression protection at the N+7 part-4
  measured level (1.27x @ 64spp, 1.38x @ 512spp on RTX 5070 Ti,
  2026-06-11) with headroom for machine variance.
- TARGET >= 1.5x: xfail(strict=False) until the shadow-stage split lands.
  Profile (n7p5): stage_shade_bucketed dominates at 254 regs/thread --
  the inline NEE BVH shadow traversal is the register hog; the Laine
  shadow-stage split (factoring sampleDirectSpectralMW into sample +
  occlusion halves shared with the megakernel) is the named next step.

Both legs render linear output (applyGamma=False) -- memory:
render-probe-applygamma-footgun.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from runtime_setup import configure_test_imports  # noqa: E402

configure_test_imports()

try:
    import astroray  # noqa: E402
    AVAILABLE = True
except ImportError:
    AVAILABLE = False

pytestmark = pytest.mark.skipif(not AVAILABLE, reason="astroray not built")

if AVAILABLE and not hasattr(astroray, "cuda_wavefront_render"):
    pytest.skip(
        "cuda_wavefront_render not in this build — needs "
        "-DASTRORAY_WAVEFRONT_CUDA_N3=ON + CUDA (RTX box).",
        allow_module_level=True,
    )

WIDTH = HEIGHT = 256
SPP = 512
MAX_DEPTH = 8
SEED = 424242


def _build(gpu: bool):
    scenes_dir = Path(__file__).resolve().parent.parent / "scenes"
    sys.path.insert(0, str(scenes_dir))
    import disney_contact_sheet as scene_mod  # noqa: E402

    r = astroray.Renderer()
    scene_mod.build_scene(r)
    scene_mod.setup_camera(r, width=WIDTH, height=HEIGHT)
    r.set_seed(SEED)
    r.set_integrator_param("max_depth", MAX_DEPTH)
    r.set_integrator("path_tracer")
    if gpu:
        r.set_use_gpu(True)
    _ = r.render(1, 1, None, False)  # warmup / BVH build
    return r


def _measure():
    r_mk = _build(gpu=True)
    _ = r_mk.render(64, MAX_DEPTH, None, False)  # warm
    t0 = time.perf_counter()
    mk = np.asarray(r_mk.render(SPP, MAX_DEPTH, None, False),
                    dtype=np.float32).reshape(HEIGHT, WIDTH, 3)
    t_mk = time.perf_counter() - t0

    r_wf = _build(gpu=False)
    _ = astroray.cuda_wavefront_render(r_wf, 64, MAX_DEPTH, SEED)  # warm
    t0 = time.perf_counter()
    wf = np.asarray(astroray.cuda_wavefront_render(r_wf, SPP, MAX_DEPTH, SEED),
                    dtype=np.float32).reshape(HEIGHT, WIDTH, 3)
    t_wf = time.perf_counter() - t0
    return t_mk, t_wf, mk, wf


_RESULT = None


def _result():
    global _RESULT
    if _RESULT is None:
        _RESULT = _measure()
    return _RESULT


def test_wavefront_contact_sheet_floor():
    """HARD floor: wavefront >= 1.15x faster than the megakernel, and the
    two GPU pipelines agree (same BSDFs) within 3% per channel."""
    t_mk, t_wf, mk, wf = _result()
    speedup = t_mk / t_wf
    ratio = wf.mean(axis=(0, 1)) / np.maximum(mk.mean(axis=(0, 1)), 1e-6)
    print(f"[perf-gate] MK {t_mk:.3f}s WF {t_wf:.3f}s speedup {speedup:.2f}x "
          f"ratio {np.round(ratio, 4)}")
    assert np.all(np.abs(ratio - 1.0) <= 0.03), (
        f"WF/MK image ratio out of bounds: {ratio}"
    )
    assert speedup >= 1.15, (
        f"Wavefront perf floor REGRESSED: {speedup:.2f}x < 1.15x "
        f"(MK {t_mk:.3f}s, WF {t_wf:.3f}s)"
    )


@pytest.mark.xfail(
    strict=False,
    reason="Phase-B target gate: >= 1.5x needs the shadow-stage split "
    "(stage_shade_bucketed at 254 regs/thread; the inline NEE BVH "
    "traversal is the register hog — see spec N+7 part-4/5 plan).",
)
def test_wavefront_contact_sheet_target():
    t_mk, t_wf, _, _ = _result()
    assert t_mk / t_wf >= 1.5
