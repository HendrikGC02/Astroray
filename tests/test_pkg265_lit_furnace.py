"""pkg265 — LIT white furnace: rough glass under a uniform field that includes a
dedicated area light exercises the NEE leg the lightless furnace cannot see (the
cycles-parity-reviewer's regression request for PR #778).

A lossless dielectric is invisible in a UNIFORM radiance field: with the world
background AND the area light both emitting radiance ~1.0, the whole hemisphere
above the glass reads 1.0, so the sphere must render ~1.0 for every roughness —
regardless of whether NEE, BSDF sampling, or emitter-hit MIS carries the light.

pkg265 routes rough-glass vertices through the Heitz walk and skips light-sampling
NEE (eval()==0, isDelta=true — the same delta contract smooth glass uses), so all
light transport is BSDF sampling + emitter-hit MIS. This test proves that is
unbiased: an inconsistent NEE eval (the bug the reviewer flagged) or a broken
eta/energy accounting would pull the lit furnace out of [0.97, 1.02].

Measured after the fix (CPU, 256 spp, seed 7): principled 0.992-0.996, disney
0.986-0.995 — all in band; NOT relaxed to pass.
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
