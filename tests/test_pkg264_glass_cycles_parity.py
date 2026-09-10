"""pkg264 — the native 'principled' Glass BSDF must conserve energy (and thus
match Cycles' rough-glass brightness) instead of going dark grey as roughness
rises.

Root cause (measured 2026-09-08, .astroray_plan/docs/pkg264-glass-energy-research.md
§7): the pkg263 render darkening is a ROUGH-TRANSMISSION ENERGY LOSS in the native
'principled' material — NOT a bounce cap, NOT dead-sample redistribution of the
kind pkg179 chased, and NOT the disney glass path (which the pkg263 gate never
touches). In a white furnace (IOR 1.45, clear glass invisible → target 1.0) the
shipped 'principled' transmission lobe measured:

    r     principled   disney
    0.0     0.997       0.997
    0.5     0.909       0.967
    0.85    0.645       0.962
    1.0     0.524       0.957

The 'principled' sampler (principled.cpp chooseAndSampleDir) returns an absorbing
DEAD sample (ds.ok=false → sample() f=0,pdf=0) when a rough microfacet
reflect/refract direction is invalid. On a solid sphere's EXIT interface (dense→
rare, near the critical angle) that dead rate is high and rises with roughness;
the dropped energy compounds over the two interfaces (0.8²≈0.64) to the ~0.5×
render deficit pkg263 saw. 'disney' does NOT lose it because it falls through to a
smooth delta glass event on a dead rough sample (disney.cpp:844-912, whose comment
records that dropping that fallback "collapsed the white-furnace ~0.9→~0.0"). The
fix mirrors that fallback into principled.cpp (+ GPU closure-graph glass).

These furnace gates are the mechanism gate: RED on main (0.645 @ r0.85), GREEN
after. The full pkg263 Blender-harness ROI re-run vs Cycles is the package
acceptance evidence (reported in the PR / results doc), not asserted here because
its absolute scale depends on Blender area-light watt→radiance units.

Provenance of the numbers above: this suite, build_cuda .pyd built 2026-09-08
07:54 from post-#751 main, CPU, 256 spp, seed 7.
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

# roughnesses spanning the pkg263 sweep; r=0 is the delta lobe (already correct).
_ROUGH = [0.2, 0.5, 0.85, 1.0]


def _furnace(kind: str, roughness: float, *, use_gpu: bool = False,
             spp: int = 256, depth: int = 32, ior: float = 1.45) -> float:
    """Clear glass in a uniform white field must render ~1.0 (radiance invariant
    along a bent ray). Mirrors tests/test_disney_rough_glass_furnace._furnace but
    parameterised on the material KIND so it covers the native 'principled' lobe
    the pkg263 gate actually renders."""
    r = astroray.Renderer()
    r.set_background_color([1.0, 1.0, 1.0])
    if kind == "principled":
        params = {"transmission_weight": 1.0, "ior": ior, "roughness": roughness}
    else:  # disney
        params = {"transmission": 1.0, "ior": ior, "roughness": roughness,
                  "metallic": 0.0}
    g = r.create_material(kind, [1.0, 1.0, 1.0], params)
    r.add_sphere([0.0, 0.0, 0.0], 1.0, g)
    r.set_integrator("path_tracer")
    if use_gpu:
        r.set_use_gpu(True)
    r.setup_camera([0, 0, 4], [0, 0, 0], [0, 1, 0], 40.0, 1.0, 0.0, 4.0, 80, 80)
    r.set_seed(7)
    img = np.asarray(r.render(spp, depth, None, False),
                     dtype=np.float32).reshape(80, 80, 3)
    return float(img[28:52, 28:52].mean())


def test_principled_rough_glass_furnace_conserves_cpu():
    """The native 'principled' rough-transmission lobe must conserve energy.
    RED on main (0.909 @ r0.5, 0.645 @ r0.85, 0.524 @ r1.0). pkg265: the lobe is now
    the Heitz-2016 multiple-scattering walk, which conserves energy by construction
    (R+T==1); the band is TIGHTENED to [0.97, 1.02] linear (render applyGamma=False,
    memory gamma-furnace-cannot-detect-energy-gain — a >1.02 upper bound would catch
    a walk that gains energy). Measured after pkg265 (256 spp, seed 7, CPU):
    r0.2/0.5/0.85/1.0 = 0.992/0.996/0.995/0.996. NOT relaxed to accommodate loss."""
    vals = {R: _furnace("principled", R) for R in _ROUGH}
    bad = {R: v for R, v in vals.items() if not (0.97 <= v <= 1.02)}
    assert not bad, (f"principled rough glass furnace not energy-conserving at "
                     f"roughness {bad}; all={vals}")


def test_disney_rough_glass_furnace_still_conserves_cpu():
    """pkg265: the disney glass lobe is now the same Heitz-2016 walk; it must
    conserve in the same [0.97, 1.02] linear band. Measured after pkg265 (256 spp,
    seed 7, CPU): r0.2/0.5/0.85/1.0 = 0.992/0.993/0.986/0.981."""
    vals = {R: _furnace("disney", R) for R in _ROUGH}
    bad = {R: v for R, v in vals.items() if not (0.97 <= v <= 1.02)}
    assert not bad, f"disney rough glass furnace regressed at roughness {bad}; all={vals}"


@pytest.mark.skipif(
    AVAILABLE and not astroray.__features__.get("cuda", False),
    reason="CUDA feature not in this build")
def test_principled_rough_glass_furnace_conserves_gpu():
    """GPU closure-graph glass must conserve too (the fix mirrors into
    gpu_materials.h). RED on main, GREEN after."""
    if not astroray.Renderer().gpu_available:
        pytest.skip("CUDA GPU not available")
    vals = {R: _furnace("principled", R, use_gpu=True, spp=128) for R in _ROUGH}
    bad = {R: v for R, v in vals.items() if not (0.94 <= v <= 1.06)}
    assert not bad, (f"GPU principled rough glass furnace not energy-conserving at "
                     f"roughness {bad}; all={vals}")
