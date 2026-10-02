"""#1012 -- Jakob-Hanika scale-search (bisection) + hoisted coefficient lookup
must be BIT-IDENTICAL to the former linear scan, on CPU and GPU.

tests/data/jh_upsample_golden.npz holds spectra produced by the pre-#1012
build (linear scan, one lookup per wavelength) over a dense RGB grid. Equal
coefficients => equal spectra, so exact equality of the spectra proves the same
(k, tz) and the same trilinear coefficients. Regenerate ONLY from a build that
predates a deliberate LUT/algorithm change:
    python tests/test_jh_lookup_equality.py --regen
"""
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(__file__))
from runtime_setup import configure_test_imports

configure_test_imports()

try:
    import astroray
    AVAILABLE = True
except ImportError:
    AVAILABLE = False

pytestmark = pytest.mark.skipif(not AVAILABLE, reason="astroray module not available")

GOLDEN = os.path.join(os.path.dirname(__file__), "data", "jh_upsample_golden.npz")
# 11 lambdas: not a multiple of G_SPECTRUM_SAMPLES (4), exercises the group padding.
LAMBDAS = [380.0 + 40.0 * k for k in range(11)]


def _grid():
    ax = np.linspace(0.0, 1.0, 9)
    g = np.stack(np.meshgrid(ax, ax, ax, indexing="ij"), -1).reshape(-1, 3)
    rng = np.random.default_rng(1012)
    rnd = rng.random((256, 3)) ** 2                   # biased to dark: dense in low-z scale cells
    edge = np.array([[1.2, 0.3, 0.0], [-0.1, 0.5, 0.5], [1e-9, 0, 0], [0, 0, 0],
                     [1, 1, 1], [0.999999, 1, 0.5]])  # clamp / black / z==1 edges
    return np.concatenate([g, rnd, edge]).astype(np.float32).ravel().tolist()


def _cpu(mode):
    return np.array(astroray._cpu_rgb_upsample_batch(_grid(), LAMBDAS, mode), np.float32)


def _gpu(mode):
    return np.array(astroray.Renderer()._gpu_rgb_upsample_batch(_grid(), LAMBDAS, mode), np.float32)


def _has_gpu():
    r = astroray.Renderer()
    return bool(astroray.__features__.get("cuda", False)) and bool(getattr(r, "gpu_available", False))


@pytest.mark.parametrize("mode", [1, 2])
def test_cpu_lookup_bit_identical_to_linear_scan(mode):
    g = np.load(GOLDEN)
    # The golden was captured on the MSVC build. Another libm evaluates the sigmoid differently
    # (GCC CI: <=1.7e-5 on values <=1; even MSVC CPU vs GPU differ ~4e-6), so exact equality holds
    # only on the capturing toolchain; the exact Windows leg is the index-equality proof.
    if sys.platform == "win32":
        assert np.array_equal(_cpu(mode), g[f"cpu{mode}"])
    else:
        np.testing.assert_allclose(_cpu(mode), g[f"cpu{mode}"], rtol=0, atol=5e-5)


@pytest.mark.parametrize("mode", [1, 2])
def test_gpu_lookup_bit_identical_to_linear_scan(mode):
    if not _has_gpu():
        pytest.skip("CUDA GPU not available")
    g = np.load(GOLDEN)
    assert np.array_equal(_gpu(mode), g[f"gpu{mode}"])


if __name__ == "__main__" and "--regen" in sys.argv:
    out = {f"cpu{m}": _cpu(m) for m in (1, 2)}
    if _has_gpu():
        out.update({f"gpu{m}": _gpu(m) for m in (1, 2)})
    np.savez_compressed(GOLDEN, **out)
    print("wrote", GOLDEN, {k: v.shape for k, v in out.items()})
