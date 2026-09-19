"""#828 — CPU blackbody normaliser: NaN band, continuity, luminance at any T.

CPU-only (no CUDA), so CPU CI covers the fix the GPU parity tests cannot:
  1. NaN BAND — main's normalizedPlanck returned NaN for T ~ 25-140 K (float
     normaliser -> inf, float(planck) -> 0). Every T is now finite; T < 30 K is
     exactly 0 (the shared CPU/GPU table starts at 30 K), T >= 30 K is > 0 at the
     red end.
  2. CONTINUITY — a per-kelvin memo evaluated at lround(T) jumps ~7 % between
     500.49 K and 500.51 K; the shared ln-T table is continuous.
  3. LUMINANCE — Σ normalizedPlanck·ȳ = 1 (times Cycles' intensity) at
     NON-integer temperatures too, re-integrated with the engine's own ȳ
     (self-consistent magnitude pin, as tests/test_pkg270_blackbody_furnace.py).
"""
import math

import numpy as np
import pytest
from runtime_setup import configure_test_imports

configure_test_imports()

astroray = pytest.importorskip("astroray")

LAMS4 = [450.0, 550.0, 650.0, 800.0]


def _cmf(lam):
    # accessor renamed by #837 (CIE 1931 2°); accept either spelling.
    f = getattr(astroray, "cie_cmf_1931_2deg", None) or getattr(astroray, "cie_cmf_1964_10deg")
    return f(float(lam))


def _cycles_intensity(T, I):
    return 5.670373e-8 * 1e-6 / math.pi * ((1.0 - I) + I * T ** 4)


@pytest.mark.parametrize("T", [22.0, 25.0, 28.0, 29.9, 30.0, 35.0, 50.0, 80.0,
                               100.0, 120.0, 140.0, 150.0, 200.0])
def test_low_temperature_is_finite_and_gated_at_30k(T):
    vals = astroray.volume_blackbody_emission(T, 1.0, [1.0, 1.0, 1.0], LAMS4)
    assert all(math.isfinite(v) and v >= 0.0 for v in vals), (T, vals)
    if T < 30.0:
        assert all(v == 0.0 for v in vals), (T, vals)
    else:
        assert vals[3] > 0.0, (T, vals)


def test_normaliser_is_continuous_across_kelvin_bins():
    lo = astroray.volume_blackbody_emission(500.49, 1.0, [1.0, 1.0, 1.0], LAMS4)
    hi = astroray.volume_blackbody_emission(500.51, 1.0, [1.0, 1.0, 1.0], LAMS4)
    for a, b in zip(lo, hi):
        assert b == pytest.approx(a, rel=2e-3), (lo, hi)


@pytest.mark.parametrize("T", [60.5, 500.4, 1234.5, 2718.3, 6543.2])
def test_luminance_normalised_at_non_integer_temperature(T):
    lams = np.arange(360.0, 831.0, 1.0)
    Y = 0.0
    for k in range(0, len(lams), 4):
        chunk = [float(x) for x in lams[k:k + 4]]
        while len(chunk) < 4:
            chunk.append(830.0)
        vals = astroray.volume_blackbody_emission(T, 1.0, [1.0, 1.0, 1.0], chunk)
        for j, lam in enumerate(lams[k:k + 4]):
            Y += vals[j] * _cmf(lam).Y
    ratio = Y / _cycles_intensity(T, 1.0)
    print(f"[#828 lum] T={T}: Y/cycles={ratio:.5f}")
    assert ratio == pytest.approx(1.0, rel=5e-3), ratio
