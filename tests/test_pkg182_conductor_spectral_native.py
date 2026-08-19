"""pkg182 follow-up — CONDUCTOR (metallic) thin-film SPECTRAL leg is per-λ native.

PR-2/PR-3 shipped the conductor thin-film spectral leg as a Jakob-Hanika upsample
of the per-RGB-channel iridescence result (Cycles has no spectral n,k for the F82
conductor, so it was documented APPROXIMATED-equal-to-Cycles). This change makes
the leg per-λ native: at each sampled wavelength it upsamples base_color +
specular_tint, inverts the conductor (n,k) via Gulbrandsen, and runs the analytic
Belcour-Barla Airy summation with the exact single-λ sensitivity phasor — the same
discipline the dielectric spectral leg already uses. See
principled.cpp::thinFilmConductorSpectral / gpu_pr_thinFilmConductorSpectral.

Astroray's `path_tracer` is spectral-first (the legacy RGB integrator was deleted,
spectral-core.md), so a plain `r.render()` on a metallic Principled sphere runs
exactly this per-λ leg.

MEASURED FINDING (this branch, RTX 5070 Ti):
  In Astroray's 4-wavelength hero pipeline the per-λ native leg and the prior
  RGB-upsample leg are near-identical — white-environment hue-sweep saturation
  moved mean 0.0488 -> 0.0499, max 0.1842 -> 0.2045 (i.e. removing the JH round-
  trip recovers ~10% of peak chroma), and the per-λ spectral-reshape signal under
  a saturated colored light is ~0.01. The Airy reflectance is smooth enough to be
  JH-reconstructible at 4 samples, so there is NO dramatic muting to undo here; the
  change's value is exactness (no JH round-trip), consistency with the dielectric
  leg, and being the correct foundation for higher spectral sample counts / spectral
  light sources — at zero <false>/<true> STACK cost. The vs-Blender-5.2 per-channel
  pixel-match is the acceptance gate and remains LEAD-DEFERRED (needs the oracle).

Gates here (CPU). thickness-0 bit-equality, furnace no-gain and chromatic-change on
this same spectral path are already gated by test_thin_film_pr2; GPU/CPU spectral
parity by test_pkg178_thinfilm_gpu_cpu_parity. This file guards the two properties
that must survive on the per-λ leg: it stays chromatic (iridescence not washed out)
and its hue trajectory still sweeps with thickness.
"""
import numpy as np
import pytest
from runtime_setup import configure_test_imports

configure_test_imports()

try:
    import astroray
    AVAILABLE = True
except ImportError:
    AVAILABLE = False

pytestmark = pytest.mark.skipif(not AVAILABLE, reason="astroray not built")

_W = 96
_SEED = 7

# plan §4 conductor hue-trajectory grid (same as conductor_hue_sweep.py).
_THICKNESSES = [100.0, 200.0, 400.0, 800.0, 1500.0, 3000.0]
_FILM_IORS = [1.2, 1.5, 1.8]
_BASE_COLOR = (0.9, 0.9, 0.9)  # neutral metal so iridescence is the dominant chroma

# Washout guard, NOT an improvement claim. Measured on this branch: mean cell
# saturation 0.0499, max 0.2045 over the grid. These floors sit comfortably below
# that so a future change that flattens the per-λ leg (loses the iridescence) fails.
_MEAN_SAT_FLOOR = 0.035
_MAX_SAT_FLOOR = 0.15


def _render(thickness_nm, film_ior, *, res=_W, spp=128):
    r = astroray.Renderer()
    r.set_use_gpu(False)  # CPU leg; GPU/CPU parity is a separate gate
    r.set_background_color([1.0, 1.0, 1.0])
    params = {
        "ior": 1.5, "roughness": 0.08, "metallic": 1.0, "transmission_weight": 0.0,
        "thin_film_thickness": thickness_nm, "thin_film_ior": film_ior,
    }
    mid = r.create_material("principled", list(_BASE_COLOR), params)
    r.add_sphere([0.0, 0.0, 0.0], 1.0, mid)
    r.set_integrator("path_tracer")
    r.setup_camera([0, 0, 4], [0, 0, 0], [0, 1, 0], 40.0, 1.0, 0.0, 4.0, res, res)
    r.set_seed(_SEED)
    # render(spp, depth, denoiser, apply_gamma) — LINEAR.
    return np.asarray(r.render(spp, 16, None, False), dtype=np.float32).reshape(res, res, 3)


def _roi_mean_rgb(img):
    h, w, _ = img.shape
    roi = img[int(h * 0.25):int(h * 0.75), int(w * 0.25):int(w * 0.75)]
    return roi.reshape(-1, 3).mean(axis=0)


def _saturation(mean_rgb):
    mx = float(mean_rgb.max())
    mn = float(mean_rgb.min())
    return (1.0 - mn / mx) if mx > 0 else 0.0


# ---------------------------------------------------------------------------
# the per-λ leg stays chromatic across the sweep (iridescence not washed out)
# ---------------------------------------------------------------------------
def test_conductor_spectral_stays_chromatic():
    sats = []
    for d in _THICKNESSES:
        for fior in _FILM_IORS:
            sats.append(_saturation(_roi_mean_rgb(_render(d, fior))))
    sats = np.asarray(sats)
    mean_sat, max_sat = float(sats.mean()), float(sats.max())
    print(f"\n[pkg182 conductor per-lambda] mean_sat={mean_sat:.4f} max_sat={max_sat:.4f} "
          f"(RGB-upsample baseline: mean 0.0488, max 0.1842)")
    assert mean_sat >= _MEAN_SAT_FLOOR, (
        f"per-λ conductor mean saturation {mean_sat:.4f} < floor {_MEAN_SAT_FLOOR} "
        "— the thin-film iridescence has washed out to gray (leg broken)")
    assert max_sat >= _MAX_SAT_FLOOR, (
        f"per-λ conductor max saturation {max_sat:.4f} < floor {_MAX_SAT_FLOOR} "
        "— the strongest iridescent cell lost its chroma (leg broken)")


# ---------------------------------------------------------------------------
# hue trajectory still present across thickness (iridescence not washed out)
# ---------------------------------------------------------------------------
def test_conductor_spectral_hue_moves_with_thickness():
    # A fixed film IOR, sweep thickness; the ROI-mean channel signature must move.
    fior = 1.8
    means = [_roi_mean_rgb(_render(d, fior)) for d in _THICKNESSES]
    sigs = np.asarray([[m[0] / (m[1] + 1e-6), m[2] / (m[1] + 1e-6)] for m in means])
    spread = float(np.abs(sigs - sigs.mean(axis=0)).max())
    assert spread > 0.05, (
        f"conductor thin-film hue does not move with thickness (max Δsig={spread:.3f})")
