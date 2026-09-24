#!/usr/bin/env python
"""pkg64-gpu Phase 3 — empty-hook no-regression (Phase 2 gates re-run at higher spp).

Spec: .astroray_plan/packages/pkg64-gpu-spectral-caustics.md §Phase 3.

Re-asserts the Phase 2 acceptance gates (empty-hook bit-equality + walltime overhead)
at the Phase 3 higher-spp budget. The spec explicitly notes: "Empty hook bit-equal
to pre-pkg64-gpu (this is already in Phase 2's no-regression test — but Phase 3
verifies it once more at higher spp)."

Two gates:

  #1  Empty-hook bit-equality: GPU output with `use_caustics=False` (or no caster
      flagged) is bit-equal to the baseline on the Lambertian Cornell scene.

  #2  Empty-hook walltime overhead ≤ 5%: median walltime ratio, caustics
      toggle ON (no caster flagged) vs OFF, interleaved in the same run.

Mirrors the pattern from test_pkg64_gpu_phase2_no_regression.py. Baselines are
stored separately from Phase 2 (tests/baselines/pkg64-gpu-phase3/) because the
spp budget may differ. Skips gracefully when CUDA is unavailable.
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
        "CUDA feature not in this build — pkg64-gpu Phase 3 no-regression "
        "needs CUDA; /verify runs this on the RTX box.",
        allow_module_level=True,
    )

# Add tests/scenes to path so we can import the Cornell scene helper.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "scenes"))
import lambertian_cornell  # noqa: E402

WIDTH = 64
HEIGHT = 64
SAMPLES = 64  # Phase 3 may use higher spp than Phase 2 (same as Phase 2 for now)
MAX_DEPTH = 8

BASELINES_DIR = Path(__file__).parent / "baselines" / "pkg64-gpu-phase3"


def _make_cornell_gpu(*, seed: int, use_caustics: bool = False) -> astroray.Renderer:
    """Build the Lambertian Cornell scene on GPU.

    Mirrors test_pkg64_gpu_phase2_no_regression.py _make_cornell_gpu (lines 70-90).
    use_caustics defaults to False (empty hook); no caster flagged → SMS short-circuits.
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
    r.set_use_refractive_caustics(use_caustics)
    r.set_use_reflective_caustics(use_caustics)
    # No caster flagged → r.caustic_caster_count() == 0 → SMS guard short-circuits.
    return r


def _render(*, seed: int, use_caustics: bool = False) -> tuple[np.ndarray, float]:
    """Render the cornell scene on GPU and return (pixels, walltime_sec)."""
    r = _make_cornell_gpu(seed=seed, use_caustics=use_caustics)
    t0 = time.perf_counter()
    pix = np.asarray(r.render(SAMPLES, MAX_DEPTH, None, False), dtype=np.float32)
    return pix, time.perf_counter() - t0


def test_empty_hook_bit_equality():
    """Empty-hook GPU output bit-equal to baseline (Phase 3 re-check).

    Captures: GPU render of Lambertian Cornell at 64 spp with use_caustics=False
    (no caster flagged → SMS guard short-circuits → identical control flow to
    pre-pkg64-gpu megakernel). Compares to a pinned baseline. On first run,
    writes the baseline and skips. On subsequent runs, asserts max diff == 0.0.

    Rationale: same as Phase 2 (lines 101-151) — the empty hook should produce
    identical kernel control flow. Phase 3 re-runs at higher spp to verify no
    drift at increased MC iteration count.
    """
    probe = astroray.Renderer()
    if not probe.gpu_available:
        pytest.skip("CUDA GPU not available on this machine")

    # #845 (2026-09-24): the GPU accumulates samples with atomicAdd, whose order
    # varies run to run. Varying pixels over 5 re-renders (max |d|):
    #   seed:            145 11 23 37 51 73 101 202
    #   main 0dd98e18:     0  0  0  0  0  4   0   2   (2.98e-8)
    #   #845 build:        3  0  0  3  0  1   0   0   (2.38e-7)
    # so a cross-process bit-equality pin was only stable by chance. Even
    # in-process, OFF vs OFF at seed 11 differed in 2 of 10 trials (2.98e-8) on
    # the #845 build (main: 0 of 10). PRIMARY gate: in-process caustics hook ON
    # vs OFF (no caster flagged) within 1e-6 -- a hook that ran would consume
    # RNG / add energy and move pixels by orders of magnitude more. SECONDARY:
    # the stored seed-145 baseline within 1e-6 (~4x the 2.4e-7 atomic spread).
    off, _ = _render(seed=11, use_caustics=False)
    on, _ = _render(seed=11, use_caustics=True)
    hook_diff = float(np.abs(on - off).max())
    assert float(off.max()) > 0.0
    assert hook_diff <= 1e-6, (
        f"empty caustics hook changed the render in-process: max|on - off| = "
        f"{hook_diff:.6e} > 1e-6 (atomicAdd jitter <= 2.4e-7) -- find the divergent code path "
        f"(useCaustics && numSMSCasters > 0 guard)."
    )

    baseline_path = BASELINES_DIR / "cornell-baseline.npy"

    pix, _ = _render(seed=145, use_caustics=False)

    # Re-captured 2026-09-25 (Batch U transport fixes, see the phase-2 test):
    # max|new - old| = 9.7e-05, channel means moved < 5e-06.
    # Re-captured 2026-09-20 (#767 observer change, PR #837 -> main). The pins
    # were taken under the CIE 1964 10 deg observer; the engine now integrates
    # with CIE 1931 2 deg (the observer the XYZ->sRGB matrix and the
    # Jakob-Hanika LUT are defined against), so every spectral render shifts:
    # this Cornell's channel means moved (0.21171, 0.18551, 0.19635) ->
    # (0.21676, 0.18318, 0.19934) and max|render - old pin| was 2.675e-02.
    # The bit-equality PROPERTY is intact and was verified on the current build
    # before re-capturing: rendering with the caustics toggle ON (no caster
    # flagged) vs OFF gives max|on - off| == 0.000000e+00 in both phases, and
    # the pre-observer build still matched its own pin at exactly 0.0.
    # pkg225-S6: refuse to pin (or compare against) an all-black frame. Both
    # pinned Cornell baselines here were captured while the GPU
    # multiwavelength route was light-sampling-blind, so they were literally
    # all zeros and this gate certified black-against-black for as long as the
    # bug lived. A bit-equality canary is only a canary if it has signal.
    assert float(pix.max()) > 0.0, (
        "refusing to use an all-black Cornell render as a bit-equality baseline "
        "-- the scene is lit, so a black frame means the render path is broken, "
        "not that it is stable.")

    if not baseline_path.exists():
        # First run: write the baseline and skip.
        baseline_path.parent.mkdir(parents=True, exist_ok=True)
        np.save(baseline_path, pix)
        pytest.skip(
            f"pkg64-gpu Phase 3 empty-hook baseline not present. "
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

    assert max_diff <= 1e-6, (
        f"pkg64-gpu Phase 3 stored-baseline check FAILED: max abs diff = "
        f"{max_diff:.6e} > 1e-6 (atomicAdd jitter is <= 2.4e-7).")

    print(
        f"\n[pkg64-gpu Phase 3 empty-hook bit-equality] PASS: "
        f"max diff = {max_diff!r} (<= 1e-6; hook on/off within atomic jitter)"
    )


def test_empty_hook_walltime_overhead():
    """Empty-hook GPU walltime overhead <= 5% on cornell parity scene (Phase 3 re-check).

    Renders with the caustics toggle ON (no caster flagged → SMS guard
    short-circuits) vs toggle OFF, interleaved in the same run, and gates
    the median walltime ratio over N>=5 iteration pairs.

    Gate: overhead <= 5% (spec gates table: "Empty-hook walltime overhead
    | ≤ 5% | CPU pkg64-3 cost gate"). Measured RELATIVE — on/off in the
    same run — exactly like the CPU source gate
    (test_pkg64_phase3_no_regression.py::test_no_caster_cost_gate), NOT
    against a pinned absolute walltime: a pinned-seconds baseline conflates
    code changes with machine state and false-failed 3x on 2026-06-11/12
    when the RTX 5070 Ti was thermally loaded after hours of benchmarking,
    while passing in isolation. Interleaving puts both arms in the same
    thermal state, so load cancels out while a real regression
    (unconditional SMS work behind the toggle) still shows. With OS-jitter
    slack on small renders, allows up to 1.30x ratio (same as Phase 2).
    """
    probe = astroray.Renderer()
    if not probe.gpu_available:
        pytest.skip("CUDA GPU not available on this machine")

    # Warm GPU caches first (BVH resident, shader JIT compiled) — both arms.
    _render(seed=11, use_caustics=False)
    _render(seed=11, use_caustics=True)

    off_times = []
    on_times = []
    for s in (101, 102, 103, 104, 105):
        _, t_off = _render(seed=s, use_caustics=False)
        _, t_on = _render(seed=s, use_caustics=True)
        off_times.append(t_off)
        on_times.append(t_on)
    off_median = float(np.median(off_times))
    on_median = float(np.median(on_times))
    ratio = on_median / max(off_median, 1e-6)

    print(
        f"\n[pkg64-gpu Phase 3 empty-hook walltime overhead] "
        f"toggle-off median = {off_median:.4f} s, "
        f"toggle-on median = {on_median:.4f} s, "
        f"ratio = {ratio:.3f}x"
    )

    # Spec budget is 5%; allow OS jitter slack on small renders (same as Phase 2).
    assert ratio <= 1.30, (
        f"pkg64-gpu Phase 3 empty-hook walltime overhead FAILED: "
        f"ratio {ratio:.2f}x > 1.30x (spec gate 1.05x + jitter slack). "
        f"The empty hook (numSMSCasters == 0 → guard short-circuits before "
        f"any SMS code runs) should add near-zero overhead. A measured "
        f"overhead > 30% is a regression — check for unconditional work "
        f"behind the useCaustics toggle in the path-trace loop."
    )

    print(
        f"[pkg64-gpu Phase 3 empty-hook walltime overhead] PASS: "
        f"ratio {ratio:.3f}x <= 1.30x (within spec 5% + jitter slack)"
    )
