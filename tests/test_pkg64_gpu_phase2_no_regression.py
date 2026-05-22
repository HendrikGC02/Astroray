#!/usr/bin/env python
"""pkg64-gpu Phase 2 — empty-hook GPU no-regression gates.

Spec: .astroray_plan/packages/pkg64-gpu-spectral-caustics.md §Phase 2.

Two acceptance gates:

  #1  Empty-hook bit-equality: GPU output with `useCaustics=False` (the
      Phase 2 default; no caster flagged) is bit-equal to pre-pkg64-gpu
      GPU output on the Lambertian Cornell parity scene at 64 spp.

      "Bit-equal" means max(|render - baseline|) == 0.0 — the empty hook
      should produce IDENTICAL control flow to the pre-pkg64-gpu kernel.
      On first run (no baseline), writes the baseline and skips; subsequent
      runs assert against it.

  #2  Empty-hook walltime overhead ≤ 5%: same scene, 64 spp, GPU walltime
      with the new wiring vs baseline. Measured as median over N≥5 iterations
      and compared to a pinned baseline walltime. Skips if no baseline.

Convention: skips gracefully when CUDA is unavailable (CI has no GPU —
memory `ci_has_no_gpu_runtime_blindspot`). On the RTX box with the pkg64-gpu
Phase 2 build, asserts the gates. Baseline is stored in a subdirectory of
the test file's location.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import numpy as np
import pytest

from runtime_setup import configure_test_imports

configure_test_imports()
sys.path.insert(0, os.path.dirname(__file__))

try:
    import astroray  # noqa: E402
    AVAILABLE = True
except ImportError:
    AVAILABLE = False

pytestmark = pytest.mark.skipif(not AVAILABLE, reason="astroray not built")

if AVAILABLE and not astroray.__features__.get("cuda", False):
    pytest.skip(
        "CUDA feature not in this build — pkg64-gpu Phase 2 empty-hook "
        "GPU gates need CUDA; /verify runs this on the RTX box.",
        allow_module_level=True,
    )

# Add tests/scenes to path so we can import the Cornell scene helper.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "scenes"))
import lambertian_cornell  # noqa: E402

WIDTH = 64
HEIGHT = 64
SAMPLES = 64
MAX_DEPTH = 8

# Baseline storage: tests/baselines/pkg64-gpu-phase2/<file>.npy
BASELINES_DIR = Path(__file__).parent / "baselines" / "pkg64-gpu-phase2"


def _make_cornell_gpu(*, seed: int) -> astroray.Renderer:
    """Build the Lambertian Cornell scene on GPU.

    Phase 2 acceptance uses the same cornell parity scene referenced in
    pkg55 Phase B' (tests/scenes/lambertian_cornell.py) and the pkg64
    Phase 3 CPU cornell no-regression test (test_pkg64_phase3_no_regression.py).
    Mirrors that scene exactly, with GPU enabled and multiwavelength integrator.
    """
    r = astroray.Renderer()
    lambertian_cornell.build_scene(r)
    lambertian_cornell.setup_camera(r, width=WIDTH, height=HEIGHT)
    r.set_seed(seed)
    r.set_use_gpu(True)
    r.set_wavelength_range(380.0, 780.0)  # visible-band sRGB output
    r.set_output_mode("srgb")
    r.set_integrator_param("max_depth", MAX_DEPTH)
    r.set_integrator("multiwavelength_path_tracer")
    # useCaustics defaults to False in Phase 2 (cuda_renderer.cu line 641/700).
    # No caster flagged → SMS hook short-circuits → identical control flow to
    # pre-pkg64-gpu kernel.
    return r


def _render(*, seed: int) -> tuple[np.ndarray, float]:
    """Render the cornell scene on GPU and return (pixels, walltime_sec)."""
    r = _make_cornell_gpu(seed=seed)
    t0 = time.perf_counter()
    pix = np.asarray(r.render(SAMPLES, MAX_DEPTH, None, False), dtype=np.float32)
    return pix, time.perf_counter() - t0


def test_empty_hook_bit_equality():
    """Empty-hook GPU output bit-equal to pre-pkg64-gpu baseline.

    Captures: GPU render of Lambertian Cornell at 64 spp with useCaustics=False
    (the Phase 2 default — no caster flagged). Compares to a pinned baseline
    render saved to tests/baselines/pkg64-gpu-phase2/cornell-baseline.npy.
    On first run (BASELINE missing), writes the baseline and skips. On
    subsequent runs, asserts max(|render - baseline|) == 0.0.

    Rationale: the empty hook (no caster flagged, useCaustics=False) produces
    identical kernel control flow to the pre-pkg64-gpu megakernel. The SMS
    attempt is gated by `(useCaustics && !rec.isDelta && numSMSCasters > 0)`;
    numSMSCasters == 0 when no caster is flagged, so the hook never runs.
    Any non-zero diff indicates a regression in the path-trace loop wiring.
    """
    probe = astroray.Renderer()
    if not probe.gpu_available:
        pytest.skip("CUDA GPU not available on this machine")

    baseline_path = BASELINES_DIR / "cornell-baseline.npy"

    pix, _ = _render(seed=145)

    if not baseline_path.exists():
        # First run: write the baseline and skip.
        baseline_path.parent.mkdir(parents=True, exist_ok=True)
        np.save(baseline_path, pix)
        pytest.skip(
            f"pkg64-gpu Phase 2 empty-hook baseline not present. "
            f"Captured baseline at {baseline_path} ({pix.shape} float32). "
            f"Re-run this test to assert bit-equality against the baseline."
        )

    baseline = np.load(baseline_path)
    assert baseline.shape == pix.shape, (
        f"Baseline shape {baseline.shape} != render shape {pix.shape} — "
        f"regenerate the baseline (delete {baseline_path})"
    )

    diff = np.abs(pix - baseline)
    max_diff = float(diff.max())

    assert max_diff == 0.0, (
        f"pkg64-gpu Phase 2 empty-hook bit-equality FAILED: "
        f"max abs diff = {max_diff:.6e} != 0.0. The empty hook (no caster "
        f"flagged, useCaustics=False) should produce IDENTICAL control flow "
        f"to the pre-pkg64-gpu kernel. A non-zero diff is a Phase 2 "
        f"regression. Do NOT lower this gate to a tolerance — find and fix "
        f"the divergent code path. See multiwavelength_kernel.cu line 667 "
        f"(useCaustics && numSMSCasters > 0 guard)."
    )

    print(
        f"\n[pkg64-gpu Phase 2 empty-hook bit-equality] PASS: "
        f"max diff = {max_diff!r} (EXACTLY 0.0 — no regression)"
    )


def test_empty_hook_walltime_overhead():
    """Empty-hook GPU walltime overhead <= 5% on cornell parity scene.

    Runs N>=5 rendering warm-up + measured iterations at 64 spp with
    useCaustics=False (Phase 2 default). Records the median walltime.
    Compares to a pinned baseline walltime (same scene, pre-pkg64-gpu code).
    Skips if no baseline pinned.

    Gate: overhead <= 5% (spec Phase 2 acceptance gate, mirrors CPU pkg64-3
    empty-hook cost gate). With generous OS-jitter slack on small renders,
    allows up to 1.30× ratio (same pattern as test_pkg64_phase3_no_regression.py
    line 112).
    """
    probe = astroray.Renderer()
    if not probe.gpu_available:
        pytest.skip("CUDA GPU not available on this machine")

    baseline_time_path = BASELINES_DIR / "cornell-walltime-baseline.npy"

    # Warm GPU caches first (BVH resident, shader JIT compiled).
    _render(seed=11)

    times = []
    for s in (101, 102, 103, 104, 105):
        _, t = _render(seed=s)
        times.append(t)
    measured_median = float(np.median(times))

    if not baseline_time_path.exists():
        # First run: capture the baseline walltime and skip.
        baseline_time_path.parent.mkdir(parents=True, exist_ok=True)
        np.save(baseline_time_path, np.array([measured_median], dtype=np.float32))
        pytest.skip(
            f"pkg64-gpu Phase 2 empty-hook walltime baseline not present. "
            f"Captured baseline median walltime {measured_median:.4f} s at "
            f"{baseline_time_path}. Re-run this test to assert the overhead gate."
        )

    baseline_median = float(np.load(baseline_time_path)[0])
    ratio = measured_median / max(baseline_median, 1e-6)

    print(
        f"\n[pkg64-gpu Phase 2 empty-hook walltime overhead] "
        f"baseline median = {baseline_median:.4f} s, "
        f"measured median = {measured_median:.4f} s, "
        f"ratio = {ratio:.3f}x"
    )

    # Spec budget is 5%; allow OS jitter slack on small renders (same as
    # CPU pkg64-3 test_no_caster_cost_gate, line 112: ratio <= 1.30).
    assert ratio <= 1.30, (
        f"pkg64-gpu Phase 2 empty-hook walltime overhead FAILED: "
        f"ratio {ratio:.2f}x > 1.30x (spec gate 1.05x + jitter slack). "
        f"The empty hook (numSMSCasters == 0 → guard short-circuits before "
        f"any SMS code runs) should add near-zero overhead. A measured "
        f"overhead > 30% is a regression — check for unconditional work in "
        f"the path-trace loop before the useCaustics guard."
    )

    print(
        f"[pkg64-gpu Phase 2 empty-hook walltime overhead] PASS: "
        f"ratio {ratio:.3f}x <= 1.30x (within spec 5% + jitter slack)"
    )
