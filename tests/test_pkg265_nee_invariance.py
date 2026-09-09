"""pkg265 — NEE ON/OFF estimator invariance for the multiple-scattering glass.

THE acceptance criterion for the Heitz-2016 stochastic eval (PR #778): switching
between two unbiased strategies (NEE + MIS vs pure BSDF sampling with unweighted
emitter hits) must NOT move a converged mean. Memory
[[unbiased-strategy-switch-moving-a-mean-is-a-bug-signal]] — the previous lane's
skip-NEE delta contract moved the pkg263 harness limb from 1.05x to 0.60x of
Cycles, which is exactly what this gate is built to catch.

`renderer.set_light_nee(False)` (pkg265, the lamp twin of pkg258's
set_env_nee) drops the light-sampling leg AND takes every emitter/lamp hit at
full weight, so both legs estimate the SAME image with different variance.

Two confounds MUST be off or the comparison is meaningless:
  * adaptive sampling — the stop metric is colour-blind and spp-dependent
    (pkg237); with it ON the noisier NEE-off leg stopped early and read 4-11%
    darker at 512 spp, a pure artifact.
  * gamma — every mean here is a linear radiance (apply_gamma=False).

Measured on this branch (CPU, 128x128, 512 spp, 16 seeds, adaptive off):
r0.5 centre on 0.27291 vs off 0.27277 (+0.05%); r0.5 limb 0.61411 vs 0.60819
(+0.96%, 2.9 sigma) — the residual is the stochastic eval's known grazing-angle
error (research note Phase 9: eval-vs-walk T agrees to +4..6% per direction).
The gates below therefore allow max(2 sigma, 2% of the mean) and are still
~20x tighter than the 40% collapse they exist to detect.
"""
import math

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

_SEEDS = (7, 11, 23, 41, 59, 73)
_ROUGH = (0.3, 0.5, 0.85)
_IOR = 1.45
# Relative floor under the 2-sigma band: with 6 seeds the standard error is
# itself noisy, and the eval carries a ~1% grazing-angle residual (see module
# docstring). NOT a relaxation to pass — the failure mode this gate targets is
# tens of percent.
_REL_FLOOR = 0.02


def _glass_material(r, kind, roughness):
    if kind == "principled":
        params = {"transmission_weight": 1.0, "ior": _IOR, "roughness": roughness}
    else:
        params = {"transmission": 1.0, "ior": _IOR, "roughness": roughness,
                  "metallic": 0.0}
    return r.create_material(kind, [1.0, 1.0, 1.0], params)


def _stats(values):
    a = np.asarray(values, dtype=np.float64)
    return float(a.mean()), float(a.std(ddof=1) / math.sqrt(a.size))


def _assert_invariant(label, on_vals, off_vals):
    on, sem_on = _stats(on_vals)
    off, sem_off = _stats(off_vals)
    delta = on - off
    tol = max(2.0 * math.sqrt(sem_on ** 2 + sem_off ** 2), _REL_FLOOR * abs(on))
    assert abs(delta) <= tol, (
        f"{label}: NEE-on {on:.5f}+-{sem_on:.5f} vs NEE-off {off:.5f}+-{sem_off:.5f} "
        f"-> delta {delta:+.5f} ({100.0 * delta / on:+.2f}%), tolerance {tol:.5f}. "
        f"An unbiased strategy switch moved the mean: eval()/pdf() on the "
        f"Heitz-2016 walk are inconsistent with sample().")
    return on, sem_on, off, sem_off, delta


# ---------------------------------------------------------------------------
# (a) pure-reflection probe: black world + black ground, one area light. Every
# transmitted path dies in the void, so the measured disc is the walk's
# REFLECTION half only — the half the pkg263 limb is made of.
# ---------------------------------------------------------------------------
def _reflection_probe(kind, roughness, nee, seed, spp=192, res=64):
    r = astroray.Renderer()
    r.set_background_color([0.0, 0.0, 0.0])
    g = _glass_material(r, kind, roughness)
    r.add_sphere([0.0, 0.0, 0.0], 1.0, g)
    r.add_area_light_dedicated(
        [2.0, 3.0, 2.0], [1.0, 0.0, 0.0], [0.0, 0.0, 1.0], 2.0, 2.0,
        "RECTANGLE", {"mode": "rgb", "color": [1.0, 1.0, 1.0]}, 40.0)
    r.set_integrator("path_tracer")
    r.set_adaptive_sampling(False)
    r.set_light_nee(nee)
    r.setup_camera([0, 0, 4], [0, 0, 0], [0, 1, 0], 40.0, 1.0, 0.0, 4.0, res, res)
    r.set_seed(seed)
    img = np.asarray(r.render(spp, 24, None, False),
                     dtype=np.float32).reshape(res, res, 3)
    lo, hi = int(res * 0.28), int(res * 0.72)
    return float(img[lo:hi, lo:hi].mean())


@pytest.mark.parametrize("kind", ["principled", "disney"])
@pytest.mark.parametrize("roughness", _ROUGH)
def test_reflection_probe_nee_invariant(kind, roughness):
    on = [_reflection_probe(kind, roughness, True, s) for s in _SEEDS]
    off = [_reflection_probe(kind, roughness, False, s) for s in _SEEDS]
    _assert_invariant(f"reflection probe {kind} r{roughness}", on, off)


# ---------------------------------------------------------------------------
# (b) lit white furnace, both strategies. The uniform field pins the answer at
# 1.0, so this catches an eval that is merely MIS-consistent but wrongly scaled.
# ---------------------------------------------------------------------------
def _lit_furnace(kind, roughness, nee, seed, spp=256, res=80):
    r = astroray.Renderer()
    r.set_background_color([1.0, 1.0, 1.0])
    g = _glass_material(r, kind, roughness)
    r.add_sphere([0.0, 0.0, 0.0], 1.0, g)
    r.add_area_light_dedicated(
        [0.0, 0.0, 8.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0], 10.0, 10.0,
        "RECTANGLE", {"mode": "rgb", "color": [1.0, 1.0, 1.0]}, 1.0)
    r.set_integrator("path_tracer")
    r.set_adaptive_sampling(False)
    r.set_light_nee(nee)
    r.setup_camera([0, 0, 4], [0, 0, 0], [0, 1, 0], 40.0, 1.0, 0.0, 4.0, res, res)
    r.set_seed(seed)
    img = np.asarray(r.render(spp, 32, None, False),
                     dtype=np.float32).reshape(res, res, 3)
    return float(img[28:52, 28:52].mean())


@pytest.mark.parametrize("kind", ["principled", "disney"])
@pytest.mark.parametrize("roughness", _ROUGH)
def test_lit_furnace_nee_invariant(kind, roughness):
    on = [_lit_furnace(kind, roughness, True, s) for s in _SEEDS]
    off = [_lit_furnace(kind, roughness, False, s) for s in _SEEDS]
    mo, _, mf, _, _ = _assert_invariant(f"lit furnace {kind} r{roughness}", on, off)
    for tag, v in (("NEE-on", mo), ("NEE-off", mf)):
        assert 0.97 <= v <= 1.02, (
            f"lit furnace {kind} r{roughness} {tag} = {v:.4f} outside [0.97, 1.02]")


# ---------------------------------------------------------------------------
# (c) the pkg263 metal_ab glass A/B geometry, in-process. This is the gate that
# catches the 0.60x limb: a glass sphere lifted off a grey plane, one area light
# plus a dim grey world, with the harness's own centre/limb/background ROIs
# (benchmarks/cycles-parity/metal_ab/scenes.py build_glass_scene). Calibration:
# at roughness 0 this scene reads centre 0.175 / limb 0.286 against the pkg263
# Cycles reference's 0.1773 / 0.2842 (<1.5%), so it really is that scene.
# ---------------------------------------------------------------------------
_P263_R = 0.6            # sphere radius
_P263_GAP = 0.05         # lifted off the plane
_P263_CAM = 2.4          # camera distance along the view axis
_P263_FOV = 50.0
_P263_WORLD = 0.6 * 0.3  # world colour x strength
_P263_LIGHT = 150.0      # Blender area-light power / area


# 128 spp, not the harness's 64: the NEE-off leg finds the 1x1 radiance-150
# key light only by BSDF sampling, so its per-sample distribution is heavy-
# tailed and 64 spp is not converged (measured r0.5 centre delta +3.44% at
# 64 spp, +0.42% at 128, +0.37% at 256, -0.01% at 512, 8 seeds each). The
# tail is an estimator-variance property, not a BSDF property.
def _pkg263_scene(roughness, nee, seed, res=128, spp=128):
    r = astroray.Renderer()
    r.set_background_color([_P263_WORLD] * 3)
    cy = _P263_R + _P263_GAP
    ground = r.create_material("principled", [0.5, 0.5, 0.5],
                               {"roughness": 0.6, "metallic": 0.0})
    h = 10.0
    r.add_triangle([-h, 0.0, -h], [h, 0.0, -h], [h, 0.0, h], ground)
    r.add_triangle([-h, 0.0, -h], [h, 0.0, h], [-h, 0.0, h], ground)
    r.add_sphere([0.0, cy, 0.0], _P263_R, _glass_material(r, "principled", roughness))
    # Blender key light at (1.2, -1.2, cy+1.75) Z-up -> (1.2, cy+1.75, 1.2) Y-up,
    # aimed at the sphere centre.
    lp = [1.2, cy + 1.75, 1.2]
    d = np.array([0.0, cy, 0.0]) - np.array(lp)
    d /= np.linalg.norm(d)
    u = np.cross([0.0, 1.0, 0.0], d)
    u /= np.linalg.norm(u)
    v = np.cross(d, u)
    r.add_area_light_dedicated(lp, list(u), list(v), 1.0, 1.0, "RECTANGLE",
                               {"mode": "rgb", "color": [1.0, 1.0, 1.0]}, _P263_LIGHT)
    r.set_integrator("path_tracer")
    r.set_adaptive_sampling(False)
    r.set_light_nee(nee)
    r.setup_camera([0.0, cy, _P263_CAM], [0.0, cy, 0.0], [0, 1, 0], _P263_FOV,
                   1.0, 0.0, _P263_CAM, res, res)
    r.set_seed(seed)
    img = np.asarray(r.render(spp, 16, None, False),
                     dtype=np.float32).reshape(res, res, 3)
    rpx = _P263_R / (math.tan(math.radians(_P263_FOV) / 2.0) * _P263_CAM) * (res / 2.0)
    yy, xx = np.mgrid[0:res, 0:res]
    c = (res - 1) / 2.0
    dist = np.sqrt((xx - c) ** 2 + (yy - c) ** 2)
    return {
        "centre": float(img[dist < 0.35 * rpx].mean()),
        "limb": float(img[(dist > 0.80 * rpx) & (dist < 0.98 * rpx)].mean()),
        "background": float(img[:int(res * 0.12), :int(res * 0.12)].mean()),
    }


@pytest.mark.parametrize("roughness", _ROUGH)
def test_pkg263_geometry_nee_invariant(roughness):
    on = [_pkg263_scene(roughness, True, s) for s in _SEEDS]
    off = [_pkg263_scene(roughness, False, s) for s in _SEEDS]
    for roi in ("centre", "limb", "background"):
        _assert_invariant(f"pkg263 r{roughness} {roi}",
                          [v[roi] for v in on], [v[roi] for v in off])
