"""pkg55-B' Session N+6 — GPU wavefront FINAL-IMAGE gate.

The per-stage threshold gates (N+3..N+5) compare only deterministic-given-
stage fields; per spec §4.2 design decision #2 the CPU (mt19937-seeded) and
GPU (PCG-direct) BSDF/NEE draws are independent MC samples, so sampling
correctness is owned by THIS gate: the end-to-end GPU wavefront image vs the
CPU wavefront oracle.

Gate: per-channel mean ratio |GPU/CPU - 1| <= 0.12 at 64 spp on the
session_n1_envmap_cornell scene (the Session N+1 acceptance form — SSIM is
the wrong gate for independent-RNG MC streams at modest spp; memory:
ssim-wrong-gate-for-independent-rng). SSIM is logged informationally.

Why 0.12 and not 0.05: the GPU wavefront calls the megakernel's device BSDFs
(gpu_material_sample_spectral — design decision #9 applied to the GPU side),
which carry KNOWN documented divergences from the CPU plugins (e.g. GPU
disney lacks diffuseFurnaceScale + Kulla-Conty compensation; GPU metal's GGX
form differs — pkg108 review notes). Measured on RTX 5070 Ti 2026-06-11,
stable across seeds and 64->256 spp (i.e. systematic, inherited — not an
N+6 pipeline defect): per-channel ratio [1.089, 0.991, 1.045]. Tightening
to 0.05 is the per-material GPU/CPU parity work, tracked in the spec.
Reference point: the MEGAKERNEL itself diverges ~1.85x from CPU on this
open-top env scene (never previously gated here) — filed as a separate
follow-up; the wavefront at <=9% is the closest GPU/CPU agreement this
scene has had.
"""

from __future__ import annotations

import sys
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

WIDTH = HEIGHT = 64
SPP = 64
MAX_DEPTH = 8
SEED = 424242


def _build_renderer():
    """Session N+1 env-map Cornell (7 materials + env-miss paths) — the same
    construction the per-stage gate test uses."""
    scenes_dir = Path(__file__).resolve().parent.parent / "scenes"
    sys.path.insert(0, str(scenes_dir))
    import session_n1_envmap_cornell as scene_mod  # noqa: E402

    r = astroray.Renderer()
    scene_mod.build_scene(r)
    scene_mod.setup_camera(r, width=WIDTH, height=HEIGHT)
    r.set_seed(SEED)
    r.set_integrator_param("max_depth", MAX_DEPTH)
    r.set_integrator("path_tracer")
    _ = r.render(1, 1, None, False)  # warmup: triggers BVH build
    return r


def test_gpu_wavefront_final_image_mean_ratio():
    """End-to-end GPU wavefront vs CPU wavefront oracle: per-channel mean
    ratio within 12% at 64 spp (independent RNG streams; same algorithm —
    see module docstring for the measured-bound justification)."""
    r = _build_renderer()

    cpu = astroray.reference_pt_wavefront_render(r, SPP, MAX_DEPTH, SEED, False)
    cpu_img = np.asarray(cpu, dtype=np.float32).reshape(HEIGHT, WIDTH, 3)

    gpu_img = np.asarray(
        astroray.cuda_wavefront_render(r, SPP, MAX_DEPTH, SEED),
        dtype=np.float32,
    ).reshape(HEIGHT, WIDTH, 3)

    assert np.all(np.isfinite(gpu_img)), "GPU wavefront produced non-finite pixels"
    assert float(gpu_img.mean()) > 1e-4, "GPU wavefront produced a black frame"

    cpu_mean = cpu_img.mean(axis=(0, 1))
    gpu_mean = gpu_img.mean(axis=(0, 1))
    ratio = gpu_mean / np.maximum(cpu_mean, 1e-6)

    # Informational SSIM (not gated — independent-RNG MC).
    try:
        from skimage.metrics import structural_similarity as ssim
        s = ssim(cpu_img, gpu_img, channel_axis=2,
                 data_range=float(max(cpu_img.max(), gpu_img.max(), 1e-6)))
        print(f"[N+6] informational SSIM: {s:.4f}")
    except ImportError:
        pass
    print(f"[N+6] per-channel mean ratio GPU/CPU: {ratio}")

    assert np.all(np.abs(ratio - 1.0) <= 0.12), (
        f"GPU wavefront final-image mean ratio out of gate: {ratio} "
        f"(CPU mean {cpu_mean}, GPU mean {gpu_mean})"
    )
