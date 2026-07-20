"""pkg55-C5 gates: spectral photon-map caustics in the GPU wavefront.

1. Photons OFF: the wavefront default path is untouched by the C5 code
   (run-to-run max_abs_diff <= 1e-5, the GPU atomic-accumulation convention
   adjudicated in PR #490).
2. Photons ON: wavefront (cuda_wavefront_render route) vs the MW megakernel
   photon-caustic baseline on the pkg113 glass-sphere scene, SSIM >= 0.80
   (pkg113 Phase-3 parity threshold class).

Scene/builders are REUSED from tests/test_gpu_caustic_parity.py — the proven
pkg113 harness — rather than re-declared (the invented-API test failure mode,
see pkg115/pkg55-C3 history).

Spec: .astroray_plan/docs/pkg55-phase-c-plan-2026-07.md Session C5.
"""

import numpy as np
import pytest

from runtime_setup import configure_test_imports
configure_test_imports()

import astroray  # noqa: E402

from test_gpu_caustic_parity import (  # noqa: E402  (proven pkg113 builders)
    _build_glass_sphere, _render, _ssim, _luminance,
)


def _gpu_wavefront_available():
    r = astroray.Renderer()
    return (bool(getattr(r, "gpu_available", False))
            and hasattr(astroray, "cuda_wavefront_render"))


pytestmark = pytest.mark.skipif(
    not _gpu_wavefront_available(),
    reason="CUDA wavefront not available")


def _to_wavefront(r):
    """Switch a GPU-configured pkg113 scene onto the wavefront route."""
    r.set_integrator("wavefront_path_tracer")
    return r


def test_wavefront_photons_off_identity():
    """C5 gate 1: photons OFF -> default wavefront path untouched.

    Two renders of the same scene WITHOUT the photon opt-in must agree to the
    GPU fp-noise floor (1e-5; exact equality is impossible under atomic float
    accumulation — PR #490 adjudication). Any RNG-stream perturbation from the
    C5 threading would diverge at O(1e-2), which this catches.
    """
    r = _build_glass_sphere(use_gpu=True)
    r.set_use_photon_caustics(False)   # explicit: photons OFF
    _to_wavefront(r)
    img1 = _render(r, samples=16, seed=42)
    img2 = _render(r, samples=16, seed=42)
    diff = float(np.abs(img1 - img2).max())
    assert diff <= 1e-5, (
        f"Photons-off wavefront identity failed: max_abs_diff={diff:.2e} > 1e-5 "
        f"(C5 must leave the default path untouched)")


def test_wavefront_photon_caustic_parity(test_results_dir):
    """C5 primary gate: wavefront photon gather vs MW-kernel baseline.

    Both legs render the pkg113 glass-sphere caustic scene on the GPU with the
    photon pre-pass opted in; only the integrator route differs (wavefront vs
    MW megakernel). SSIM >= 0.80 per the pkg113 Phase-3 threshold class.
    """
    # MW megakernel baseline (the exact pkg113 GPU wiring)
    r_mw = _build_glass_sphere(use_gpu=True)
    img_mw = _render(r_mw, samples=64, seed=42)

    # Wavefront route, same scene + photon opt-in
    r_wf = _build_glass_sphere(use_gpu=True)
    _to_wavefront(r_wf)
    img_wf = _render(r_wf, samples=64, seed=42)

    ssim = _ssim(img_wf, img_mw)
    peak_wf = float(_luminance(img_wf).max())
    peak_mw = float(_luminance(img_mw).max())

    if test_results_dir:
        import os
        from PIL import Image

        def save_png(img, path):
            clipped = np.clip(img ** (1 / 2.2), 0, 1)
            Image.fromarray((clipped * 255).astype(np.uint8)).save(path)

        save_png(img_wf, os.path.join(test_results_dir, "pkg55_c5_wavefront_photons.png"))
        save_png(img_mw, os.path.join(test_results_dir, "pkg55_c5_mw_baseline_photons.png"))
        print(f"\n[pkg55-C5] SSIM={ssim:.4f} (gate >=0.80)  "
              f"peak WF={peak_wf:.3f} MW={peak_mw:.3f}")

    assert ssim >= 0.80, (
        f"Photon caustic parity failed: SSIM={ssim:.4f} < 0.80 "
        f"(peak WF={peak_wf:.3f} MW={peak_mw:.3f})")
