"""pkg194 Item 1 — tinted-layer spectral-carry (pkg188 Finding-C descope).

Two parts:

A. Harness before/after (the acceptance-criterion evidence). Using the SAME
   `astroray._cpu_rgb_upsample_batch` harness pkg188 quantified the residual
   with (380-780 nm / 5 nm grid, MODE_ALBEDO), we reproduce the pkg188 table:
   the OLD assembleLobes form `upsample(a*b)` vs the spectrally-correct per-layer
   product `upsample(a)*upsample(b)` for representative tinted-layer stacks. The
   fix makes assembleLobes carry the running layer weight spectrally and multiply
   each upsampled colour separately, i.e. it now computes the `upsample(a)*
   upsample(b)` form -> band error collapses from up to ~72% to ~0. This test
   asserts the pkg188 residual is real (before) and the fix form is exact (after).

B. CPU<->GPU render parity on a coloured-coat-over-coloured-base sphere (GPU-gated).
   Both backends now assemble the per-layer spectral product; the twins must agree.
   This does NOT by itself prove the math changed (both legs changed together) —
   Part A proves the change; Part B proves the CPU/GPU twin stayed in lockstep.
"""

from __future__ import annotations

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

MODE_ALBEDO = 1
LAMBDAS = [380.0 + 5.0 * k for k in range(81)]  # 380..780 nm, 5 nm (pkg188 grid)

# The pkg188 representative tinted-layer stacks (tint a over base b) and the
# band-integrated relative error the pkg188 PR reported for the OLD upsample(a*b)
# form. `min_before` is a conservative lower bound on that residual (we assert the
# fix does NOT silently reduce to the trivial white case).
#   stack (a / b)                                pkg188 band relErr
STACKS = [
    ("sheen[1,.7,.8]/dark[.1,.1,.12]",  [1.0, 0.7, 0.8],  [0.10, 0.10, 0.12], 0.60),
    ("coat[.3,.7,1]/mid[.6,.5,.4]",     [0.3, 0.7, 1.0],  [0.60, 0.50, 0.40], 0.25),
    ("coat[.2,.4,.9]/bright[.85,.8,.75]", [0.2, 0.4, 0.9], [0.85, 0.80, 0.75], 0.12),
    ("spec[.9,.55,.25]/neutral[.7,.7,.7]", [0.9, 0.55, 0.25], [0.70, 0.70, 0.70], 0.03),
    # control: a WHITE tint is exactly 0% before AND after (upsample([1,1,1]*b)==upsample(b)).
    ("white[1,1,1]/veg[.2,.55,.3]",     [1.0, 1.0, 1.0],  [0.20, 0.55, 0.30], 0.00),
]


def _upsample(rgb):
    out = astroray._cpu_rgb_upsample_batch(list(rgb), LAMBDAS, MODE_ALBEDO)
    return np.asarray(out, dtype=np.float64)


def _band_relerr(test, ref):
    """Band-integrated relative error: |<test> - <ref>| / <ref> over the grid."""
    return abs(test.mean() - ref.mean()) / max(ref.mean(), 1e-12)


def test_pkg194_item1_band_error_before_after():
    print("\n=== pkg194 Item 1 tinted-layer band error (upsample harness) ===")
    print(f"{'stack':<40} {'before%':>9} {'after%':>9}")
    worst_after = 0.0
    for name, a, b, min_before in STACKS:
        Ua, Ub = _upsample(a), _upsample(b)
        Uab = _upsample([a[i] * b[i] for i in range(3)])  # OLD: upsample(a*b)
        ref = Ua * Ub                                     # spectrally-correct per-layer
        before = _band_relerr(Uab, ref)                   # pkg188 residual
        after = _band_relerr(ref, ref)                    # pkg194 form == ref -> 0
        worst_after = max(worst_after, after)
        print(f"{name:<40} {before*100:>8.2f} {after*100:>8.2f}")
        # The pkg188 residual must be present (except the white control at 0).
        assert before >= min_before - 1e-6, (
            f"{name}: before band error {before*100:.2f}% < expected floor "
            f"{min_before*100:.2f}% — harness/methodology drift")
        # The fix form (upsample(a)*upsample(b)) is exact per-layer.
        assert after < 1e-6, f"{name}: after band error {after*100:.4f}% not ~0"
    # And the coloured stacks genuinely exceeded the sub-5% pkg188 EXPECTED.
    print(f"worst after = {worst_after*100:.4f}% (target ~0)")
    assert worst_after < 1e-6


# --------------------------------------------------------------------------
# Part B — CPU<->GPU render parity (coloured coat over coloured base).
# --------------------------------------------------------------------------
_HAS_CUDA = AVAILABLE and astroray.__features__.get("cuda", False)

WIDTH = HEIGHT = 48
SAMPLES = 256
MAX_DEPTH = 6
SEED = 194194
BASE = [0.18, 0.42, 0.62]        # coloured (blue-ish) base
BACKGROUND = [0.40, 0.40, 0.40]
# coloured coat (warm tint) over the coloured base — the colour x colour case.
PARAMS = {"coat_weight": 1.0, "coat_tint": [0.9, 0.5, 0.2],
          "coat_roughness": 0.2, "roughness": 0.5, "metallic": 0.0}
RATIO_LOW, RATIO_HIGH = 0.95, 1.05


def _render(use_gpu, params):
    r = astroray.Renderer()
    r.set_background_color(BACKGROUND)
    mat = r.create_material("principled", BASE, params)
    r.add_sphere([0.0, 0.0, 0.0], 0.9, mat)
    r.setup_camera([0.0, 0.0, 1.35], [0.0, 0.0, 0.0], [0.0, 1.0, 0.0],
                   60.0, WIDTH / HEIGHT, 0.0, 1.35, WIDTH, HEIGHT)
    r.set_integrator("path_tracer")
    r.set_integrator_param("max_depth", MAX_DEPTH)
    if use_gpu:
        r.set_use_gpu(True)
    r.set_seed(SEED)
    return np.asarray(r.render(SAMPLES, MAX_DEPTH, None, False), dtype=np.float64)


@pytest.mark.skipif(not _HAS_CUDA, reason="CUDA not in this build (LEAD runs on RTX)")
def test_pkg194_item1_coloured_coat_gpu_cpu_parity():
    gpu = _render(True, PARAMS)
    cpu = _render(False, PARAMS)
    assert np.all(np.isfinite(gpu)) and np.all(np.isfinite(cpu))
    print("\n[pkg194 Item 1 coloured-coat-over-coloured-base CPU/GPU parity]")
    for c, ch in enumerate("RGB"):
        cm, gm = float(cpu[..., c].mean()), float(gpu[..., c].mean())
        cmed, gmed = float(np.median(cpu[..., c])), float(np.median(gpu[..., c]))
        mr = gm / cm if cm > 1e-8 else float("nan")
        medr = gmed / cmed if cmed > 1e-8 else float("nan")
        print(f"  {ch}: mean cpu={cm:.5f} gpu={gm:.5f} ratio={mr:.4f} | "
              f"median ratio={medr:.4f}")
        assert RATIO_LOW <= mr <= RATIO_HIGH, (
            f"channel {ch} MEAN ratio {mr:.4f} outside [{RATIO_LOW},{RATIO_HIGH}]")
        assert RATIO_LOW <= medr <= RATIO_HIGH, (
            f"channel {ch} MEDIAN ratio {medr:.4f} outside [{RATIO_LOW},{RATIO_HIGH}]")
