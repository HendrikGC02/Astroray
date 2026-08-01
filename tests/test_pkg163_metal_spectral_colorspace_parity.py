"""pkg163 — GPU/CPU metal colour-space parity: the neutral-vs-chromatic control.

Why this file exists
--------------------
pkg160 gave plain `metal` its energy-compensation term but left a CPU/GPU
colour-space seam: the CPU (MetalPlugin::evalSpectral) built the metal spectral
response PER WAVELENGTH, while the GPU (gpu_metal_eval) built it PER RGB CHANNEL
and upsampled the sum ONCE through the nonlinear Jakob-Hanika LUT. The two agree
only for a flat (achromatic) albedo; a chromatic albedo diverged, worst at high
roughness + grazing framing (r=0.9, channel B measured GPU/CPU = 1.0722).

pkg163 made the GPU per-wavelength too (gpu_metal_eval_spectral, the device
mirror of MetalPlugin::evalSpectral, routed through gpu_material_eval_spectral /
gpu_material_sample_spectral). This test locks in the DECISIVE isolation that
pins the mechanism as spectral-upsampling and nothing else (pkg160 HW gate,
isolations 2 & 3):

  * NEUTRAL albedo [0.35, 0.35, 0.35] barely diverges (channel spread of the
    GPU/CPU mean ratios measured 0.0023 on the pkg160 HW run) because a flat
    spectrum is the one case where RGB-then-upsample equals per-wavelength.
  * CHROMATIC albedo [0.92, 0.78, 0.35] diverged 25x more pre-fix (spread
    0.0589). Post-fix it must collapse back toward the neutral case.

The scene, framing, sampling, and linear (apply_gamma=False) rendering mirror
tests/test_pkg160_plain_metal_gpu_cpu_parity.py so the two gates measure the
same quantity; this one fixes roughness at 0.9 (the seam's worst case) and adds
the channel-spread bound the per-roughness band gate cannot express.
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

if AVAILABLE and not astroray.__features__.get("cuda", False):
    pytest.skip(
        "CUDA feature not in this build -- pkg163 metal colour-space parity "
        "needs the RTX box.",
        allow_module_level=True,
    )

WIDTH = HEIGHT = 48
# 2560 spp (not 256): the HW gate proved the channel-spread statistic at 256 spp
# is pure MC noise, not signal. On this same scene the single-seed 256-spp spread
# ranged 0.0059-0.0133 across seeds (draw-dependent), the worst channel flipped
# G<->B by seed, and chromatic-minus-neutral even flipped SIGN (seed 314159:
# chromatic 0.0083 < neutral 0.0100). At 2560 spp it converges (seed 160160:
# neutral == chromatic == 0.0006), so we measure the seed-AVERAGED spread here.
SAMPLES = 2560
MAX_DEPTH = 4
SEED = 163163

# Four fixed seeds, averaged for the spread statistic. 163163 is included
# deliberately -- it was the anomalously-noisy 256-spp draw (0.0133); averaging
# over multiple seeds at 2560 spp keeps it from pinning the gate on noise. Two
# of these seeds were measured at 2560 spp (160160 -> 0.0006, 163163 -> 0.0051);
# the 4-seed average is estimated ~0.003 (comfortably under the 0.01 bound). The
# full 4-seed run executes for the first time at the HW re-gate.
SEEDS = [160160, 163163, 271828, 314159]

ROUGHNESS = 0.9  # the seam's worst case (compensation-dominated + grazing)

CHROMATIC = [0.92, 0.78, 0.35]
NEUTRAL = [0.35, 0.35, 0.35]
BACKGROUND = [0.35, 0.45, 0.60]

# Standard parity band, uniform across channels (matches the pkg160 gate that
# pkg163 un-widened). Ratios are GPU/CPU linear per-channel means.
RATIO_LOW = 0.95
RATIO_HIGH = 1.05

# Post-fix chromatic channel spread bound. Pre-fix the chromatic spread was
# 0.0589 (25x the neutral 0.0023); the fix must collapse it well under 0.01.
# The bound sits above the converged floor (~0.0006-0.005 at 2560 spp) and is
# asserted on the seed-AVERAGED spread, not any single noisy draw.
MAX_CHROMATIC_SPREAD = 0.01


def _make_metal_scene(use_gpu: bool, albedo):
    r = astroray.Renderer()
    r.set_background_color(BACKGROUND)
    metal = r.create_material("metal", albedo, {"roughness": ROUGHNESS})
    r.add_sphere([0.0, 0.0, 0.0], 0.9, metal)
    # Close 60-degree framing: the sphere fills every pixel (grazing-dominated,
    # where the two upsampling orders diverge most). Identical to the pkg160 gate.
    r.setup_camera([0.0, 0.0, 1.35], [0.0, 0.0, 0.0], [0.0, 1.0, 0.0],
                   60.0, WIDTH / HEIGHT, 0.0, 1.35, WIDTH, HEIGHT)
    r.set_integrator("path_tracer")
    r.set_integrator_param("max_depth", MAX_DEPTH)
    if use_gpu:
        r.set_use_gpu(True)
    return r


def _render(use_gpu: bool, albedo, seed: int) -> np.ndarray:
    r = _make_metal_scene(use_gpu=use_gpu, albedo=albedo)
    r.set_seed(seed)
    # 4th positional arg is applyGamma -- False keeps both sides linear
    # (memory gamma-vs-linear-comparison-artifact); a gamma render would clamp
    # to [0,1] and could never detect an energy gain.
    return np.asarray(r.render(SAMPLES, MAX_DEPTH, None, False), dtype=np.float64)


def _mean_ratios(albedo, seed: int) -> list[float]:
    gpu = _render(use_gpu=True, albedo=albedo, seed=seed)
    cpu = _render(use_gpu=False, albedo=albedo, seed=seed)
    assert gpu.shape == (HEIGHT, WIDTH, 3)
    assert cpu.shape == (HEIGHT, WIDTH, 3)
    assert np.all(np.isfinite(gpu)), "GPU render produced NaN/Inf"
    assert np.all(np.isfinite(cpu)), "CPU render produced NaN/Inf"
    # Full-coverage guard (see pkg160 gate): background pixels would drag every
    # ratio toward 1.0 and silently weaken the gate.
    missed = int(np.sum(np.all(np.isclose(cpu, np.array(BACKGROUND), atol=1e-6),
                               axis=-1)))
    assert missed == 0, (
        f"{missed} pixels missed the metal sphere; re-check the camera framing"
    )
    return [float(gpu[..., c].mean()) / float(cpu[..., c].mean()) for c in range(3)]


def test_neutral_metal_parity_in_band():
    ratios = _mean_ratios(NEUTRAL, SEED)
    print(f"\n[pkg163 neutral metal r={ROUGHNESS}] GPU/CPU mean ratios "
          f"R/G/B = {ratios[0]:.4f}/{ratios[1]:.4f}/{ratios[2]:.4f} "
          f"spread={max(ratios) - min(ratios):.4f}")
    for c, ch in enumerate("RGB"):
        assert RATIO_LOW <= ratios[c] <= RATIO_HIGH, (
            f"neutral metal channel {ch} ratio {ratios[c]:.4f} outside "
            f"[{RATIO_LOW}, {RATIO_HIGH}]"
        )


def test_chromatic_metal_parity_in_band_and_spread_bounded():
    # Per-seed: assert the mean ratios are in-band (the seam-closed check, which
    # is NOT noise-sensitive). Collect each seed's spread and assert the
    # SEED-AVERAGED spread against the bound -- a single 256-spp draw's spread is
    # pure MC noise (HW gate: 0.0059-0.0133 across these four seeds, worst channel
    # flips G<->B by seed, chromatic-minus-neutral flips sign; at 2560 spp it
    # converges to ~0.0006-0.005). Averaging over four fixed seeds at 2560 spp
    # measures the converged floor, not the draw.
    spreads = []
    for seed in SEEDS:
        ratios = _mean_ratios(CHROMATIC, seed)
        spread = max(ratios) - min(ratios)
        spreads.append(spread)
        print(f"\n[pkg163 chromatic metal r={ROUGHNESS} seed={seed}] "
              f"GPU/CPU mean ratios "
              f"R/G/B = {ratios[0]:.4f}/{ratios[1]:.4f}/{ratios[2]:.4f} "
              f"spread={spread:.4f}")
        # Both floor AND ceiling: the seam divergence was one-directional (GPU
        # brighter, B=1.0722 pre-fix), so 1.05 is the load-bearing bound.
        for c, ch in enumerate("RGB"):
            assert RATIO_LOW <= ratios[c] <= RATIO_HIGH, (
                f"chromatic metal channel {ch} ratio {ratios[c]:.4f} outside "
                f"[{RATIO_LOW}, {RATIO_HIGH}] at seed={seed} -- the colour-space "
                f"seam is not closed"
            )

    avg_spread = sum(spreads) / len(spreads)
    print(f"\n[pkg163 chromatic metal r={ROUGHNESS}] seed-averaged spread="
          f"{avg_spread:.4f} over seeds {SEEDS} (per-seed {[f'{s:.4f}' for s in spreads]})")
    # The decisive control: with the seam closed, the seed-averaged chromatic
    # spread must collapse toward the neutral case (pre-fix 0.0589 -> assert <= 0.01).
    assert avg_spread <= MAX_CHROMATIC_SPREAD, (
        f"seed-averaged chromatic channel spread {avg_spread:.4f} exceeds "
        f"{MAX_CHROMATIC_SPREAD}; the per-wavelength/per-RGB colour-space "
        f"divergence has not collapsed (per-seed spreads {[f'{s:.4f}' for s in spreads]})"
    )
