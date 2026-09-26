"""#902 — metallic thin-film iridescence phase vs Cycles.

The spectral sensitivity phasor had the wrong sign (exp(+i·2π·OPD/λ) vs Cycles'
LUT convention exp(-i·...)), so the conductor's complex reflection phase entered
the Airy series as cos(m(Δ-φ)) instead of cos(m(Δ+φ)). Dielectric phases are
0/π and hide the sign; conductor colours came out ~70 nm "thinner" than Cycles.

Reference here is an INDEPENDENT implementation of Cycles' formula
(bsdf_microfacet.h F82_TINT thin-film branch: Gulbrandsen n,k inversion, and
bsdf_util.h fresnel_iridescence_channel<true>, Belcour & Barla 2017 Eq. 10),
evaluated per λ at normal incidence and projected to linear Rec.709 with the
Wyman-Sloan-Shirley 2013 analytic CIE 1931 fit, per-channel DC-normalised (the
same normalisation as Cycles' thin-film LUT). The render is the centre of a
near-mirror grey metal sphere under a white background, so pixel ≈ F(cosθ≈1).
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

F0, TINT, FILM_IOR = 0.55, 0.70, 2.4  # issue #902 showcase metal (grey)
THICKNESSES = [160.0, 230.0, 380.0]
# Per channel, linear. Pre-fix CPU renders matched this reference evaluated with
# the OLD sign to <= 0.035 (4-λ hero sampling, CIE fit, cosθ ~0.99), while the
# old-vs-fixed gap is >= 0.15 in some channel at every thickness.
ABS_TOL = 0.06
RES, SPP, SEED = 64, 256, 902


# ---- independent reference (Cycles formula, re-derived) ---------------------
def _f82(c, f0, b):
    s = min(max(1.0 - c, 0.0), 1.0)
    return min(max(f0 + (1.0 - f0) * s ** 5 - b * c * s ** 6, 0.0), 1.0)


def _f82tint_b(f0, tint):
    f = 6.0 / 7.0
    return (f0 + (1.0 - f0) * f ** 5) * (7.0 / f ** 6) * (1.0 - tint)


def _conductor_nk(f0, tint):
    """Gulbrandsen 2014 inversion as used by Cycles' F82_TINT thin-film branch."""
    r = min(f0, 0.999)
    g = _f82(1.0 / 7.0, f0, _f82tint_b(f0, tint))
    sr = math.sqrt(r)
    n = (1 + sr) / (1 - sr) * (1 - g) + (1 - r) / (1 + r) * g
    k = math.sqrt(max(0.0, (r * (n + 1) ** 2 - (n - 1) ** 2) / (1 - r)))
    return n, k, g


def _airy_normal(d, lam, nf, n, k, g):
    """Belcour-Barla Eq. 10, m<=3, normal incidence, F82 magnitudes (Cycles)."""
    r12 = (1.0 - nf) / (1.0 + nf)
    m = complex(n, k)
    r23 = (nf - m) / (nf + m)  # phase of Cycles' conductor phasor at cos=1
    nn, kk = n / nf, (k / nf) ** 2
    f0f = ((nn - 1) ** 2 + kk) / ((nn + 1) ** 2 + kk)
    fs = f0f + (1.0 - f0f) * (6.0 / 7.0) ** 5
    R23 = _f82(1.0, f0f, (7.0 / (6.0 / 7.0) ** 6) * (fs - g))
    R12 = r12 * r12
    phasor = (r23 / abs(r23)) * -(1.0 if r12 >= 0 else -1.0)
    t = 1.0 - R12
    r123 = math.sqrt(R12 * R23)
    rs = t * t * R23 / (1.0 - R12 * R23)
    R, cm, acc = rs + R12, rs - t, phasor
    for mm in range(1, 4):
        cm *= r123
        a = 2.0 * math.pi * mm * 2.0 * nf * d / lam
        R += cm * 2.0 * (acc.real * math.cos(a) + acc.imag * -math.sin(a))
        acc *= phasor
    return min(max(R, 0.0), 1.0)


def _g(x, mu, s1, s2):
    s = s1 if x < mu else s2
    return math.exp(-0.5 * ((x - mu) / s) ** 2)


def _xyz(lam):  # Wyman, Sloan, Shirley, JCGT 2(2) 2013, multi-lobe fit
    x = 1.056 * _g(lam, 599.8, 37.9, 31.0) + 0.362 * _g(lam, 442.0, 16.0, 26.7) \
        - 0.065 * _g(lam, 501.1, 20.4, 26.2)
    y = 0.821 * _g(lam, 568.8, 46.9, 40.5) + 0.286 * _g(lam, 530.9, 16.3, 31.1)
    z = 1.217 * _g(lam, 437.0, 11.8, 36.0) + 0.681 * _g(lam, 459.0, 26.0, 13.8)
    return np.array([x, y, z])


_XYZ_TO_709 = np.array([[3.2404542, -1.5371385, -0.4985314],
                        [-0.9692660, 1.8760108, 0.0415560],
                        [0.0556434, -0.2040259, 1.0572252]])


def expected_rgb(d):
    n, k, g = _conductor_nk(F0, TINT)
    acc, norm = np.zeros(3), np.zeros(3)
    for lam in range(380, 781):
        c = _XYZ_TO_709 @ _xyz(lam)
        acc += c * _airy_normal(d, lam, FILM_IOR, n, k, g)
        norm += c
    return acc / norm


# ---- render -----------------------------------------------------------------
def _render_centre(d, use_gpu):
    r = astroray.Renderer()
    r.set_use_gpu(use_gpu)
    r.set_background_color([1.0, 1.0, 1.0])
    params = {"metallic": 1.0, "roughness": 0.05, "specular_tint": [TINT] * 3,
              "thin_film_thickness": d, "thin_film_ior": FILM_IOR}
    mid = r.create_material("principled", [F0] * 3, params)
    r.add_sphere([0.0, 0.0, 0.0], 1.0, mid)
    r.set_integrator("path_tracer")
    r.setup_camera([0, 0, 4], [0, 0, 0], [0, 1, 0], 40.0, 1.0, 0.0, 4.0, RES, RES)
    r.set_seed(SEED)
    img = np.asarray(r.render(SPP, 4, None, False), dtype=np.float64).reshape(RES, RES, 3)
    c = RES // 2
    return img[c - 3:c + 3, c - 3:c + 3].reshape(-1, 3).mean(axis=0)  # cosθ >= 0.99


def _check(use_gpu):
    rows = []
    for d in THICKNESSES:
        got, exp = _render_centre(d, use_gpu), expected_rgb(d)
        rows.append((d, got, exp))
        print(f"d={d:.0f} got={np.round(got, 3)} cycles_formula={np.round(exp, 3)}")
    for d, got, exp in rows:
        assert np.all(np.abs(got - exp) <= ABS_TOL), (
            f"#902 conductor thin-film d={d:.0f}nm: render {np.round(got, 3)} vs "
            f"Cycles-formula {np.round(exp, 3)} (tol {ABS_TOL})")


@pytest.mark.cpu
def test_conductor_thinfilm_matches_cycles_formula_cpu():
    _check(use_gpu=False)


@pytest.mark.gpu
def test_conductor_thinfilm_matches_cycles_formula_gpu():
    if not astroray.__features__.get("cuda", False):
        pytest.skip("CUDA feature not in this build")
    _check(use_gpu=True)
