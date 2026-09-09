"""pkg265 — LIT white furnace: rough glass under a uniform field that includes a
dedicated area light exercises the NEE leg the lightless furnace cannot see (the
cycles-parity-reviewer's regression request for PR #778).

A lossless dielectric is invisible in a UNIFORM radiance field: with the world
background AND the area light both emitting radiance ~1.0, the whole hemisphere
above the glass reads 1.0, so the sphere must render ~1.0 for every roughness —
regardless of whether NEE, BSDF sampling, or emitter-hit MIS carries the light.

pkg265 routes rough-glass vertices through the Heitz walk, and (Phase 10) NEE
now fires there against the paper's stochastic evaluation (§8.1, Eq 42) with the
§9 proxy pdf — isDelta is false again. This test proves the pair is consistent:
an eval that is not an unbiased estimate of the walk's f, a mis-scaled eval, or
broken eta/energy accounting pulls the lit furnace out of [0.97, 1.02].
tests/test_pkg265_nee_invariance.py additionally renders this same furnace with
NEE OFF and requires the two means to agree.

Measured after Phase 10 (CPU, 256 spp, seed 7, adaptive off): principled
0.9936-0.9964, disney 0.9819-0.9934 — all in band; NOT relaxed to pass.
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

_ROUGH = [0.2, 0.5, 0.85, 1.0]


def _lit_furnace(kind: str, roughness: float, *, use_gpu: bool = False,
                 spp: int = 256, depth: int = 32, ior: float = 1.45) -> float:
    """Clear/rough glass in a UNIFORM white field (world bg + a large area light
    both at radiance 1.0) must render ~1.0. The area light makes the NEE leg fire;
    the uniform field keeps the known answer 1.0."""
    r = astroray.Renderer()
    r.set_background_color([1.0, 1.0, 1.0])
    if kind == "principled":
        params = {"transmission_weight": 1.0, "ior": ior, "roughness": roughness}
    else:
        params = {"transmission": 1.0, "ior": ior, "roughness": roughness,
                  "metallic": 0.0}
    g = r.create_material(kind, [1.0, 1.0, 1.0], params)
    r.add_sphere([0.0, 0.0, 0.0], 1.0, g)
    # A large area light at radiance 1.0, well above the sphere, facing down. The
    # world background (also 1.0) fills the rest of the hemisphere, so the field
    # the sphere sees is uniform 1.0 — glass stays invisible.
    r.add_area_light_dedicated(
        [0.0, 0.0, 8.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0], 10.0, 10.0,
        "RECTANGLE", {"mode": "rgb", "color": [1.0, 1.0, 1.0]}, 1.0)
    r.set_integrator("path_tracer")
    # pkg237: the adaptive stop metric is colour-blind and spp-dependent; a
    # furnace band must be measured on the full sample budget.
    r.set_adaptive_sampling(False)
    if use_gpu:
        r.set_use_gpu(True)
    r.setup_camera([0, 0, 4], [0, 0, 0], [0, 1, 0], 40.0, 1.0, 0.0, 4.0, 80, 80)
    r.set_seed(7)
    img = np.asarray(r.render(spp, depth, None, False),
                     dtype=np.float32).reshape(80, 80, 3)
    return float(img[28:52, 28:52].mean())


def test_principled_lit_furnace_conserves_cpu():
    vals = {R: _lit_furnace("principled", R) for R in _ROUGH}
    bad = {R: v for R, v in vals.items() if not (0.97 <= v <= 1.02)}
    assert not bad, (f"principled rough glass LIT furnace not in band at {bad}; "
                     f"all={vals} — NEE/eval or eta accounting regressed (pkg265)")


def test_disney_lit_furnace_conserves_cpu():
    vals = {R: _lit_furnace("disney", R) for R in _ROUGH}
    bad = {R: v for R, v in vals.items() if not (0.97 <= v <= 1.02)}
    assert not bad, (f"disney rough glass LIT furnace not in band at {bad}; "
                     f"all={vals} — NEE/eval or eta accounting regressed (pkg265)")


@pytest.mark.gpu
def test_principled_lit_furnace_conserves_gpu():
    vals = {R: _lit_furnace("principled", R, use_gpu=True) for R in _ROUGH}
    bad = {R: v for R, v in vals.items() if not (0.97 <= v <= 1.02)}
    assert not bad, (f"principled rough glass LIT furnace (GPU) not in band at "
                     f"{bad}; all={vals}")
