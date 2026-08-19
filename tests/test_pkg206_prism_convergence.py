"""pkg206 — render-level convergence + unbiasedness gate for luminance-weighted
hero-wavelength importance sampling, on the dispersive BK7 prism.

Two acceptance criteria (spec pkg206 §Acceptance), measured not assumed:

  A. CONVERGENCE WIN — at a FIXED low sample count, the importance-sampled
     render has lower per-channel error-vs-reference (less chromatic noise) than
     the uniform-sampled render. Seed-pinned, linear.

  B. UNBIASEDNESS — a high-spp importance render and a high-spp uniform render
     agree to within MC noise (per-channel mean-ratio band). Importance sampling
     changes only the proposal density; the estimator divides by it, so the
     converged image is unchanged.

The uniform baseline is reached with set_integrator_param("hero_importance", 0)
(internal knob, not a UI control). Renders are LINEAR (apply_gamma=False) so an
energy change cannot hide under gamma clamping
(memory: gamma-furnace-cannot-detect-energy-gain).
"""

from __future__ import annotations

import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "build"))
sys.path.insert(0, os.path.dirname(__file__))

try:
    import astroray
    AVAILABLE = True
except ImportError:
    AVAILABLE = False

pytestmark = pytest.mark.skipif(not AVAILABLE, reason="astroray module not available")

from scenes.prism_reference import make_prism_scene, MAX_DEPTH, HEIGHT, WIDTH  # noqa: E402


def _render(*, importance: bool, spp: int, seed: int) -> np.ndarray:
    r = make_prism_scene(astroray, dispersive=True)
    r.set_integrator_param("hero_importance", 1 if importance else 0)
    r.set_seed(seed)
    # LINEAR output (apply_gamma=False) so energy is measured honestly.
    return np.asarray(r.render(spp, MAX_DEPTH, None, False), dtype=np.float64)


def _channel_mse(img: np.ndarray, ref: np.ndarray) -> np.ndarray:
    return np.mean((img - ref) ** 2, axis=(0, 1))


@pytest.mark.slow
def test_importance_beats_uniform_chromatic_noise():
    # High-spp reference (importance is unbiased -> this is the true image).
    ref = _render(importance=True, spp=512, seed=1)

    low_spp = 16
    seeds = [11, 23, 37, 51]

    mse_imp = np.zeros(3)
    mse_uni = np.zeros(3)
    for s in seeds:
        mse_imp += _channel_mse(_render(importance=True, spp=low_spp, seed=s), ref)
        mse_uni += _channel_mse(_render(importance=False, spp=low_spp, seed=s), ref)
    mse_imp /= len(seeds)
    mse_uni /= len(seeds)

    total_imp = float(mse_imp.sum())
    total_uni = float(mse_uni.sum())
    ratio = total_imp / total_uni

    print(f"\n  per-channel MSE-vs-ref @ {low_spp}spp (mean over {len(seeds)} seeds):")
    print(f"    importance R/G/B = {mse_imp}")
    print(f"    uniform    R/G/B = {mse_uni}")
    print(f"    total importance = {total_imp:.6e}")
    print(f"    total uniform    = {total_uni:.6e}")
    print(f"    ratio (imp/uni)  = {ratio:.3f}  (want < 1.0)")

    assert ratio < 1.0, f"importance sampling did not reduce chromatic noise: ratio={ratio:.3f}"


@pytest.mark.slow
def test_converged_importance_matches_uniform_unbiased():
    # Both unbiased -> converged means agree within MC noise (per-channel ratio).
    hi = 384
    img_imp = _render(importance=True, spp=hi, seed=7)
    img_uni = _render(importance=False, spp=hi, seed=7)

    # Compare on the illuminated region only (avoid 0/0 in the black margins).
    mask = (img_uni.mean(axis=2) > 0.02)
    for c in range(3):
        a = img_imp[..., c][mask]
        b = img_uni[..., c][mask]
        ratio = a.sum() / b.sum()
        print(f"  channel {c} converged mean-ratio imp/uni = {ratio:.4f}")
        assert 0.95 <= ratio <= 1.05, f"channel {c} biased: ratio={ratio:.4f}"
