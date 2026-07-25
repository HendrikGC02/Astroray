"""pkg55-C5 gate: spectral photon-map caustics in the GPU wavefront.

Photons OFF: the wavefront default path is untouched by the C5 code
(run-to-run max_abs_diff <= 1e-5, the GPU atomic-accumulation convention
adjudicated in PR #490).

pkg55-C7 RETIREMENT (2026-07-25): the former second gate here
(`test_wavefront_photon_caustic_parity`, wavefront vs MW-megakernel SSIM)
was RETIRED with the megakernel deletion — after C7 both legs route to the
wavefront, making the comparison a self-comparison. The live photon-caustic
gate is tests/test_gpu_caustic_parity.py (GPU-vs-CPU energy-ratio + peak,
which now exercises the wavefront route). That retirement also disposes of
pkg153 failure class 3 (the SSIM=-0.0 flake was this WF-vs-MW comparison —
windowed SSIM on independent-RNG noisy caustics, memory
ssim-wrong-gate-for-independent-rng); the separate ~24% WF-vs-MW peak
deficit observation is recorded in the pkg153 spec for follow-up against
the CPU reference.

Scene/builders are REUSED from tests/test_gpu_caustic_parity.py — the proven
pkg113 harness — rather than re-declared (the invented-API test failure mode,
see pkg115/pkg55-C3 history).

Spec: .astroray_plan/docs/pkg55-phase-c-plan-2026-07.md Sessions C5 + C7.
"""

import numpy as np
import pytest

from runtime_setup import configure_test_imports
configure_test_imports()

import astroray  # noqa: E402

from test_gpu_caustic_parity import (  # noqa: E402  (proven pkg113 builders)
    _build_glass_sphere, _render,
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


# pkg55-C7: test_wavefront_photon_caustic_parity (WF vs MW megakernel) was
# retired here — see the module docstring. The live gate is
# tests/test_gpu_caustic_parity.py on the wavefront route.
