"""pkg265 / issue #782 — the INDEPENDENT oracle gate.

`heitz_random_walk.py` and the engine header `microsurface_dielectric.h` are both
clean-room transcriptions of the SAME Smith random-walk equations, so the pkg265
directional gate is a self-consistency check, not ground truth
(memory `clean-room-oracle-is-self-consistency-not-ground-truth`). This module
gates the genuinely independent reference of `heightfield_oracle.py`: an explicit
Gaussian(Beckmann) rough surface traced GEOMETRICALLY (no Lambda, no C1^Lambda
masking, no VNDF sampling — Heitz 2016's own validation method, explicit random
Beckmann surfaces) and a numpy glass-sphere path tracer.

The tests encode the #782 verdict: the multiple-scattering exit-interface energy
redistribution the walk predicts (and the pkg263 +52% centre band) is PHYSICAL,
confirmed by explicit geometry — Cycles' uniform 1/E single-scatter compensation
is the approximation, weakest exactly where single scatter loses the most energy.

Pure numpy (no astroray build needed), marked cpu, small M / loose bands so CI
stays well under a minute. The full grid runs via
`python benchmarks/cycles-parity/glass_ms_oracle/heightfield_oracle.py --full`
(single interface) and `... --sphere --full` (sphere).
"""
import math
import os
import sys

import numpy as np
import pytest

pytestmark = pytest.mark.cpu

_ORACLE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "benchmarks", "cycles-parity", "glass_ms_oracle")
sys.path.insert(0, _ORACLE_DIR)
import heightfield_oracle as hfo  # noqa: E402
import heitz_random_walk as hrw   # noqa: E402

IOR = 1.45
# fast config: small surface + ray count. Loose bands absorb the extra MC noise.
N = 128
XI = 5.0
RAYS = 6000


def _hf(alpha, mu, entering, seed=1):
    return hfo.trace_interface(alpha, mu, IOR, np.random.default_rng(seed), RAYS,
                               entering=entering, N=N, xi_cells=XI)


def _hf_1E(alpha, mu, entering, seed=2):
    ss = hfo.trace_interface(alpha, mu, IOR, np.random.default_rng(seed), RAYS,
                             entering=entering, N=N, xi_cells=XI, single_scatter=True)
    E = ss["R"] + ss["T"]
    comp = 1.0 / E if E > 1e-6 else 0.0
    return ss["R"] * comp, ss["T"] * comp


def test_explicit_oracle_conserves_energy():
    """The independent oracle's own correctness self-check: a lossless dielectric
    surface, traced geometrically, must return R+T==1 (no absorption). If this
    drifts the reference is broken, not the engine."""
    for alpha in (0.3, 0.72, 1.0):
        for mu in (0.1, 0.5, 0.9):
            for entering in (True, False):
                r = _hf(alpha, mu, entering)
                s = r["R"] + r["T"]
                assert 0.96 <= s <= 1.02, (
                    f"explicit HF R+T={s:.3f} (a{alpha} mu{mu} ent{entering})")


@pytest.mark.parametrize("alpha,mu", [(0.72, 0.9), (1.0, 0.9), (1.0, 0.5)])
def test_exit_interface_redistribution_is_physical(alpha, mu):
    """#782 verdict, independent of Cycles and of the engine: at the EXIT interface
    (glass->air) at high roughness, an explicit rough surface keeps substantially
    MORE internal reflection than Cycles' uniform 1/E single-scatter rescale
    predicts. This is the mechanism behind the pkg263 +52% centre band."""
    hf = _hf(alpha, mu, entering=False)
    oneE_R, _ = _hf_1E(alpha, mu, entering=False)
    # explicit geometry keeps clearly more internal reflection than 1/E
    assert hf["R"] >= 1.3 * oneE_R, (
        f"explicit HF_R {hf['R']:.3f} not >> 1/E_R {oneE_R:.3f} "
        f"(a{alpha} mu{mu} exit) — the redistribution the walk predicts")


@pytest.mark.parametrize("alpha,mu", [(0.72, 0.9), (1.0, 0.9)])
def test_engine_walk_tracks_explicit_better_than_1E(alpha, mu):
    """The engine's GGX Smith walk is a better predictor of the explicit
    ground-truth exit-interface reflectance than Cycles' 1/E is (despite the
    Beckmann-vs-GGX NDF difference)."""
    hf = _hf(alpha, mu, entering=False)
    gw = hrw.sample_albedo_hist(
        np.array([math.sqrt(1 - mu * mu), 0.0, mu]), alpha, IOR,
        np.random.default_rng(3), RAYS, scatter_max=64, entering=False)
    oneE_R, _ = _hf_1E(alpha, mu, entering=False)
    err_walk = abs(hf["R"] - gw["R"])
    err_1E = abs(hf["R"] - oneE_R)
    assert err_walk < err_1E, (
        f"walk err {err_walk:.3f} not < 1/E err {err_1E:.3f} "
        f"(HF_R {hf['R']:.3f} walk_R {gw['R']:.3f} 1/E_R {oneE_R:.3f})")


def test_entry_interface_walk_matches_explicit():
    """At the ENTRY interface the explicit Beckmann surface and the GGX walk agree
    closely on the R/T split (the mechanism is NDF-robust)."""
    for alpha, mu in [(0.72, 0.1), (0.72, 0.5), (1.0, 0.1)]:
        hf = _hf(alpha, mu, entering=True)
        gw = hrw.sample_albedo_hist(
            np.array([math.sqrt(1 - mu * mu), 0.0, mu]), alpha, IOR,
            np.random.default_rng(4), RAYS, scatter_max=64, entering=True)
        assert abs(hf["R"] - gw["R"]) <= 0.05, (
            f"entry HF_R {hf['R']:.3f} vs walk_R {gw['R']:.3f} (a{alpha} mu{mu})")


def test_sphere_multiscatter_brightens_centre():
    """Independent render-level reproduction of the pkg263 +52% centre band: a
    numpy glass-sphere path tracer (walk BSDF at BOTH interfaces) gives a centre
    ~unchanged at roughness 0 and markedly brighter at r0.85 relative to a
    single-scatter BSDF in the SAME tracer — the +52% is the physics of composing
    two conserving multiple-scattering interfaces, not an engine artefact."""
    Msph = 12000
    # smooth glass: MS == SS (walk reduces to single scatter as alpha -> 0)
    a0 = hfo.alpha_from_roughness(0.0)
    ms0 = hfo.render_sphere(a0, IOR, np.random.default_rng(100), Msph, 0.0, 0.15)
    ss0 = hfo.render_sphere(a0, IOR, np.random.default_rng(100), Msph, 0.0, 0.15,
                            single_scatter=True)
    assert 0.95 <= ms0 / ss0 <= 1.05, f"smooth centre MS/SS {ms0/ss0:.3f} != ~1"

    # rough glass: the multiple-scattering centre is clearly brighter
    a = hfo.alpha_from_roughness(0.85)
    ms = hfo.render_sphere(a, IOR, np.random.default_rng(100), Msph, 0.0, 0.15)
    ss = hfo.render_sphere(a, IOR, np.random.default_rng(100), Msph, 0.0, 0.15,
                           single_scatter=True)
    ratio = ms / ss
    assert ratio >= 1.3, (
        f"rough centre MS/SS {ratio:.3f} does not reproduce the +52% band "
        f"(engine measured Astroray/Cycles centre 1.61 at r0.85)")
