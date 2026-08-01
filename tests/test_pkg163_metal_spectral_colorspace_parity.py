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
SAMPLES = 256
MAX_DEPTH = 4
SEED = 163163

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


def _render(use_gpu: bool, albedo) -> np.ndarray:
    r = _make_metal_scene(use_gpu=use_gpu, albedo=albedo)
    r.set_seed(SEED)
    # 4th positional arg is applyGamma -- False keeps both sides linear
    # (memory gamma-vs-linear-comparison-artifact); a gamma render would clamp
    # to [0,1] and could never detect an energy gain.
    return np.asarray(r.render(SAMPLES, MAX_DEPTH, None, False), dtype=np.float64)


def _mean_ratios(albedo) -> list[float]:
    gpu = _render(use_gpu=True, albedo=albedo)
    cpu = _render(use_gpu=False, albedo=albedo)
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
    ratios = _mean_ratios(NEUTRAL)
    print(f"\n[pkg163 neutral metal r={ROUGHNESS}] GPU/CPU mean ratios "
          f"R/G/B = {ratios[0]:.4f}/{ratios[1]:.4f}/{ratios[2]:.4f} "
          f"spread={max(ratios) - min(ratios):.4f}")
    for c, ch in enumerate("RGB"):
        assert RATIO_LOW <= ratios[c] <= RATIO_HIGH, (
            f"neutral metal channel {ch} ratio {ratios[c]:.4f} outside "
            f"[{RATIO_LOW}, {RATIO_HIGH}]"
        )


def test_chromatic_metal_parity_in_band_and_spread_bounded():
    ratios = _mean_ratios(CHROMATIC)
    spread = max(ratios) - min(ratios)
    print(f"\n[pkg163 chromatic metal r={ROUGHNESS}] GPU/CPU mean ratios "
          f"R/G/B = {ratios[0]:.4f}/{ratios[1]:.4f}/{ratios[2]:.4f} "
          f"spread={spread:.4f}")
    # Both floor AND ceiling: the seam divergence was one-directional (GPU
    # brighter, B=1.0722 pre-fix), so the 1.05 ceiling is the load-bearing bound.
    for c, ch in enumerate("RGB"):
        assert RATIO_LOW <= ratios[c] <= RATIO_HIGH, (
            f"chromatic metal channel {ch} ratio {ratios[c]:.4f} outside "
            f"[{RATIO_LOW}, {RATIO_HIGH}] -- the colour-space seam is not closed"
        )
    # The decisive control: with the seam closed, the chromatic spread must
    # collapse toward the neutral case (pre-fix 0.0589 -> assert <= 0.01).
    assert spread <= MAX_CHROMATIC_SPREAD, (
        f"chromatic channel spread {spread:.4f} exceeds {MAX_CHROMATIC_SPREAD}; "
        f"the per-wavelength/per-RGB colour-space divergence has not collapsed "
        f"(ratios R/G/B = {ratios[0]:.4f}/{ratios[1]:.4f}/{ratios[2]:.4f})"
    )
