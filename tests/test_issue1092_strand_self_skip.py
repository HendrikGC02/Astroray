"""#1092 -- a ray leaving a curve skips the WHOLE strand (Cycles), not just the segment.

Cycles' intersection_skip_self (kernel/bvh/util.h, Apache-2.0) compares the
primitive's prim_index; for hair that is the curve index (bvh/build.cpp
add_reference_curves packs the segment into the primitive TYPE, and the Embree
path maps segment -> curve in kernel/device/cpu/bvh.h), so shadow rays and
spawned (TT) rays never re-hit the strand they leave. Astroray skipped only the
exact segment (#1037): on a bent strand the shadow ray of a point on one arm was
blocked by the other arm. Strand id: CurveStrip::buildCurveSegments ->
CurveSegment::curveStrandId (CPU), GCurveSegment::strandId (GPU).

Gates:
  1. Bent single strand under a sun, CPU/GPU render vs Cycles 5.2 CPU (THICK, Chiang
     Principled Hair, ortho, 64x64, 512 spp; script astra_run/batch-i/i12/cy_bent.py):
     image-sum ratio inside 2.5 %. Before: sun in the V plane 0.33 (the far arm shadows
     the near one), front-lit 1.19, hairpin 1.37; behind-lit (TT-dominated) 1.00.
  2. Two separate strands still occlude / re-hit each other (the skip is per strand).
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

RES, RAD, E_SUN = 64, 0.1, 2.0
COLOR = (0.15, 0.09, 0.05)
V3 = [(-0.6, 0.7, 0.0), (0.0, -0.5, 0.0), (0.6, 0.7, 0.0)]
HAIRPIN = [(-0.5, 0.8, 0.0), (-0.1, -0.6, 0.0), (0.1, -0.6, 0.0), (0.5, 0.8, 0.0)]


def _gpu_ok() -> bool:
    return AVAILABLE and bool(astroray.__features__.get("cuda", False))


BACKENDS = [False] + ([True] if _gpu_ok() else [])


def _render(gpu, sun_to, strands, spp=512, depth=4, seed=1092):
    r = astroray.Renderer()
    r.set_background_color([0.0, 0.0, 0.0])
    m = r.create_material("principled_hair", list(COLOR), {
        "roughness": 0.3, "radial_roughness": 0.3, "parametrization": "reflectance",
        "color": list(COLOR)})
    pts = np.asarray([p for s in strands for p in s], np.float32)
    r.add_curves_bulk(pts, np.full(len(pts), RAD, np.float32), [len(s) for s in strands], m)
    r.set_curve_thick_mode(True)
    d = np.asarray(sun_to, np.float64)
    d /= np.linalg.norm(d)
    r.add_sun_light_dedicated(list(-d), 0.0, {"mode": "rgb", "color": [1, 1, 1]}, E_SUN)
    r.setup_camera([0, 0, 5], [0, 0, 0], [0, 1, 0], 40.0, 1.0, 0.0, 5.0, RES, RES,
                   orthographic=True, ortho_width=2.0, ortho_height=2.0)
    r.set_integrator("path_tracer")
    r.set_integrator_param("max_depth", depth)
    r.set_adaptive_sampling(False)
    if gpu:
        r.set_use_gpu(True)
    r.set_seed(seed)
    return np.asarray(r.render(spp, depth, None, False), np.float32).reshape(RES, RES, 3)


# Cycles 5.2 CPU image sums (RGB), THICK, same scene (cy_bent.py).
CYCLES = {
    # name: (sun toward, strand, Cycles RGB sum)
    "bent_sun_in_plane": ((1.0, 0.2, -0.1), V3, [19.467508, 18.025272, 16.223957]),
    "bent_front_lit": ((1.0, 0.2, 0.4), V3, [6.707502, 6.49178, 6.266897]),
    "bent_behind_lit_TT": ((1.0, 0.2, -0.4), V3, [58.272297, 53.080276, 46.51169]),
    "hairpin_front_lit": ((1.0, 0.2, 0.4), HAIRPIN, [11.73061, 11.432595, 11.113303]),
}


@pytest.mark.parametrize("gpu", BACKENDS, ids=lambda g: "gpu" if g else "cpu")
@pytest.mark.parametrize("name", list(CYCLES))
def test_bent_strand_matches_cycles(gpu, name):
    sun, strand, ref = CYCLES[name]
    img = _render(gpu, sun, [strand])
    ratio = img.sum((0, 1)) / np.asarray(ref)
    print(f"\n[1092] {name} {'gpu' if gpu else 'cpu'}: engine/Cycles {np.round(ratio, 4)}")
    assert np.all(np.abs(ratio - 1.0) < 0.025), f"{name}: engine / Cycles = {ratio}"


@pytest.mark.parametrize("gpu", BACKENDS, ids=lambda g: "gpu" if g else "cpu")
def test_separate_strands_still_interact(gpu):
    # Over-skip guard: the V's two arms as two separate strands. With the sun in the V
    # plane the arms occlude each other, so lit together they are dimmer than lit alone
    # (a single bent strand skips its own other arm: gate 1).
    arm_a = [(-0.6, 0.7, 0.0), (0.0, -0.5, 0.0)]
    arm_b = [(0.0, -0.5, 0.0), (0.6, 0.7, 0.0)]
    sun = (1.0, 0.2, -0.1)
    a = _render(gpu, sun, [arm_a], spp=128).sum()
    b = _render(gpu, sun, [arm_b], spp=128).sum()
    both = _render(gpu, sun, [arm_a, arm_b], spp=128).sum()
    print(f"\n  a={a:.3f} b={b:.3f} both={both:.3f} both/(a+b)={both / (a + b):.4f}")
    # Two different strands shadow each other; as one strand they would not (ratio 1).
    assert both / (a + b) < 0.9, "separate strands must still occlude each other"
