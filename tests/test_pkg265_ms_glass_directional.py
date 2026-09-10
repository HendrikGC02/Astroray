"""pkg265 — directional gate for the Heitz-2016 multiple-scattering microfacet
DIELECTRIC on the native Principled transmission lobe.

The oracle is the clean-room numpy random walk
`benchmarks/cycles-parity/glass_ms_oracle/heitz_random_walk.py` (Heitz et al. 2016,
DOI 10.1145/2897824.2925943; see .astroray_plan/docs/pkg265-multiscatter-microfacet-
research.md). For a lossless dielectric the walk is a PERFECT importance sampler
(phase-function weight == 1, zero dead samples), so the distribution of sampled
directions equals the normalised BSDF*cos distribution. We therefore compare the
engine's raw sampled-direction histogram (debug_bsdf_sample_batch) directly against
the oracle's, and the reflected/transmitted split against the oracle albedo.

RED on main: the shipped lobe is single-scatter + the #771 delta reroute + a pkg138
delta fallback -- rerouted grazing samples collapse into a Dirac (specular) bin and
dead samples (pdf==0) drop energy, so both the per-bin histogram and the R:T split
diverge from the smooth multiple-scattering oracle. GREEN after Phase 2/3 rewires the
lobe to the walk.

Convention: makeMaterialTestRecord uses normal +Y. wo has cosine mu to +Y. A sampled
wi with wi.y>0 is on the incident hemisphere (reflected), wi.y<0 is transmitted.
front_face=True probes the ENTRY interface (eta=ior); front_face=False the EXIT
interface (eta=1/ior, dense->rare, where the reroute is most active).
"""
import math
import os
import sys

import numpy as np
import pytest
from runtime_setup import configure_test_imports

configure_test_imports()

try:
    import astroray
    AVAILABLE = True
except ImportError:
    AVAILABLE = False

# Import the numpy oracle by path (lives under benchmarks/, not on sys.path).
_ORACLE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "benchmarks", "cycles-parity", "glass_ms_oracle")
sys.path.insert(0, _ORACLE_DIR)
import heitz_random_walk as hrw

pytestmark = pytest.mark.skipif(not AVAILABLE, reason="astroray module not available")

IOR = 1.45
NBINS = 18
N = 100_000
# spec grid
ROUGHS = [0.3, 0.5, 0.85, 1.0]
MUS = [0.1, 0.3, 0.5, 0.7, 0.9]
FACES = [True, False]          # entry / exit interface


def _front_face_supported():
    """The exit-interface probe needs the pkg265 front_face binding arg."""
    r = astroray.Renderer()
    mid = r.create_material("principled", [1, 1, 1],
                            {"transmission_weight": 1.0, "roughness": 0.5, "ior": IOR})
    u2 = np.ascontiguousarray(np.random.rand(2, 4), dtype=np.float32)
    try:
        r.debug_bsdf_sample_batch(mid, [0.5, 0.8, 0.0], u2, False)
        return True
    except TypeError:
        return False


FRONT_FACE_ARG = AVAILABLE and _front_face_supported()


def _engine_hist(roughness, mu, front_face):
    """Sampled-direction histogram + reflected/transmitted valid-sample fractions
    from the native Principled glass lobe."""
    r = astroray.Renderer()
    mid = r.create_material(
        "principled", [1.0, 1.0, 1.0],
        {"transmission_weight": 1.0, "roughness": roughness, "ior": IOR, "metallic": 0.0})
    st = math.sqrt(max(0.0, 1.0 - mu * mu))
    wo = [st, mu, 0.0]                      # cosine mu to normal +Y
    u2 = np.ascontiguousarray(np.random.rand(2, N), dtype=np.float32)
    if FRONT_FACE_ARG:
        wi, pdf = r.debug_bsdf_sample_batch(mid, wo, u2, front_face)
    else:
        wi, pdf = r.debug_bsdf_sample_batch(mid, wo, u2)
    wi = np.asarray(wi, dtype=np.float64)
    pdf = np.asarray(pdf, dtype=np.float64)
    valid = pdf > 0.0
    ny = wi[:, 1]
    refl = valid & (ny > 0.0)
    trans = valid & (ny < 0.0)
    R = float(np.mean(refl))
    T = float(np.mean(trans))
    theta = np.degrees(np.arccos(np.clip(np.abs(ny), 0.0, 1.0)))
    edges = np.linspace(0.0, 90.0, NBINS + 1)
    hist_R = np.histogram(theta[refl], bins=edges)[0] / N
    hist_T = np.histogram(theta[trans], bins=edges)[0] / N
    return {"R": R, "T": T, "hist_R": hist_R, "hist_T": hist_T,
            "pdf": pdf, "wi": wi, "valid": valid}


def _oracle(roughness, mu, front_face):
    a = hrw.alpha_from_roughness(roughness)
    st = math.sqrt(max(0.0, 1.0 - mu * mu))
    wo = np.array([st, 0.0, mu])
    rng = np.random.default_rng(7)
    return hrw.sample_albedo_hist(wo, a, IOR, rng, N, nbins=NBINS,
                                  scatter_max=32, entering=front_face)


def _cases():
    for r in ROUGHS:
        for mu in MUS:
            for f in FACES:
                yield r, mu, f


@pytest.mark.parametrize("roughness,mu,front_face", list(_cases()))
def test_directional_matches_oracle(roughness, mu, front_face):
    if not front_face and not FRONT_FACE_ARG:
        pytest.skip("exit-interface probe needs the pkg265 front_face binding")
    eng = _engine_hist(roughness, mu, front_face)
    orc = _oracle(roughness, mu, front_face)

    # (b) albedo split within +/-2% of the oracle
    assert abs(eng["R"] - orc["R"]) <= 0.02, (
        f"R {eng['R']:.3f} vs oracle {orc['R']:.3f} (r{roughness} mu{mu} ff{front_face})")
    assert abs(eng["T"] - orc["T"]) <= 0.02, (
        f"T {eng['T']:.3f} vs oracle {orc['T']:.3f} (r{roughness} mu{mu} ff{front_face})")

    # (a) per-bin sampled-direction histogram within +/-5% on bins holding >=2% mass
    for name in ("hist_R", "hist_T"):
        oh = orc[name]
        eh = eng[name]
        heavy = oh >= 0.02
        if heavy.any():
            diff = np.abs(eh[heavy] - oh[heavy])
            assert diff.max() <= 0.05, (
                f"{name} bin diff {diff.max():.3f} > 0.05 "
                f"(r{roughness} mu{mu} ff{front_face}); eng={np.round(eh,3)} "
                f"orc={np.round(oh,3)}")

    # (c) MIS PDF covers the sampler's support (no blind spots): pdf>0 wherever a
    # direction was sampled. A stochastic-walk sampler is only MIS-safe if its
    # reported (approximate, first-bounce+diffuse) pdf is positive on its support.
    cover = float(np.mean(eng["pdf"] > 0.0))
    assert cover >= 0.98, (
        f"pdf covers only {cover:.2%} of samples (r{roughness} mu{mu} ff{front_face})")


def test_energy_conservation_oracle_selfcheck():
    """Guard the oracle itself: a correct lossless dielectric walk has R+T==1 and
    zero dead samples. If this drifts, the reference is broken, not the engine."""
    rng = np.random.default_rng(1)
    for r in ROUGHS:
        a = hrw.alpha_from_roughness(r)
        for mu in MUS:
            for f in (True, False):
                st = math.sqrt(max(0.0, 1.0 - mu * mu))
                wo = np.array([st, 0.0, mu])
                res = hrw.sample_albedo_hist(wo, a, IOR, rng, 40_000, entering=f)
                assert abs(res["R"] + res["T"] - 1.0) <= 0.01, (
                    f"oracle R+T={res['R']+res['T']:.4f} (r{r} mu{mu} entering={f})")
                assert res["dead"] <= 0.005, f"oracle dead {res['dead']:.4f}"
