"""#767 colour-skew root cause: the engine observer must be CIE 1931 2 deg.

The XYZ->linear-sRGB matrix (IEC 61966-2-1 / ITU-R BT.709: primaries and the
D65 white are CIE 1931 chromaticities) and the vendored Jakob-Hanika LUT
(fit by rgb2spec_opt against details/cie1931.h) both assume the CIE 1931 2 deg
observer. The engine integrated with the CIE 1964 10 deg table, so the
RGB->spectrum->RGB round trip was not the identity: a white illuminant rendered
(1.000, 1.002, 0.983), albedo (0.1, 0.1, 0.8) rendered R x0.64 / G x1.44.
Research note: .astroray_plan/docs/issue767-observer-mismatch-research.md.

Tolerances are predeclared from the 1 nm quadrature model (same note):
2 deg observer -> white within 3e-4, RGB-grid round trip max |err| 9.9e-4;
10 deg observer -> white B -1.7 %, grid max |err| 0.117.
"""

from __future__ import annotations

import itertools
import re
from pathlib import Path

import numpy as np
import pytest

from runtime_setup import configure_test_imports

configure_test_imports()

try:
    import astroray  # noqa: E402
    AVAILABLE = True
except ImportError:
    AVAILABLE = False

ROOT = Path(__file__).resolve().parent.parent
_needs_engine = pytest.mark.skipif(not AVAILABLE, reason="astroray not built")


def _inc_array(name: str) -> np.ndarray:
    txt = (ROOT / "data" / "spectra" / ("cie_cmf.inc" if "Cmf" in name else "illuminant_d65.inc")).read_text(
        encoding="utf-8")
    body = re.search(name + r"\[\d+\]\s*=\s*\{(.*?)\};", txt, re.S).group(1)
    return np.array([float(v.strip().rstrip("f")) for v in body.split(",") if v.strip()])


def _matrix(path: str, fn: str) -> np.ndarray:
    """M[out, in] from the `float r/g/b = c * xyz.x + ...` lines of `fn`,
    keyed by channel and component (independent of term order)."""
    txt = (ROOT / path).read_text(encoding="utf-8")
    body = txt[txt.index(fn):]
    m = np.full((3, 3), np.nan)
    for row, ch in enumerate("rgb"):
        expr = re.search(r"float\s+" + ch + r"\s*=\s*([^;]+);", body).group(1).replace(" ", "")
        for coef, comp in re.findall(r"([-+]?\d+\.\d+)f\*xyz\.([xyz])", expr):
            m[row, "xyz".index(comp)] = float(coef)
    assert not np.isnan(m).any(), (path, m)
    return m


LAM = np.arange(360.0, 831.0)
BAND = (LAM >= 380.0) & (LAM <= 780.0)  # production render band
CMF = np.stack([_inc_array("kCieCmfX"), _inc_array("kCieCmfY"), _inc_array("kCieCmfZ")])
D65 = _inc_array("kD65Spd")
M_CPU = _matrix("include/astroray/spectral.h", "inline Vec3 xyzToLinearSRGB")
M_GPU = _matrix("src/gpu/gpu_spectral_tables.h", "xyzToLinearSRGB_dev")


def test_baked_cmf_is_cie_1931_2deg():
    # CIE 1931 2 deg spot values (cvrl / colour-science 0.4.7); the 1964 10 deg
    # table differs by >1e-2 at every one of these points.
    ref = {360: (1.299e-4, 3.917e-6, 6.061e-4), 445: (0.34806, 0.0298, 1.7826),
           555: (0.5120501, 1.0, 0.00575), 600: (1.0622, 0.631, 0.0008)}
    for lam, xyz in ref.items():
        got = CMF[:, int(lam - 360)]
        assert got == pytest.approx(xyz, rel=1e-4, abs=1e-9), (lam, got)


def test_cpu_gpu_output_matrices_match():
    # IEC 61966-2-1 XYZ(D65) -> linear sRGB, 4-decimal form.
    srgb = np.array([[3.2406, -1.5372, -0.4986],
                     [-0.9689, 1.8758, 0.0415],
                     [0.0557, -0.2040, 1.0570]])
    np.testing.assert_allclose(M_CPU, srgb, atol=1e-4)
    np.testing.assert_array_equal(M_CPU, M_GPU)


@pytest.mark.parametrize("band", ["production_380_780", "full_360_830"])
def test_d65_white_is_neutral_through_engine_matrix(band):
    w = BAND if band.startswith("production") else np.ones_like(LAM, bool)
    d65n = D65 / (D65 * CMF[1]).sum()  # sampleD65 normalisation (Y = 1)
    rgb = M_CPU @ (d65n * CMF)[:, w].sum(axis=1)
    # 2 deg: (0.9999, 1.0001, 0.9997). 10 deg was (1.0001, 1.0017, 0.9831).
    assert np.abs(rgb - 1.0).max() < 1e-3, rgb


@_needs_engine
def test_engine_cmf_binding_reads_1931_table():
    c = astroray.cie_cmf_1931_2deg(555.0)
    assert (c.X, c.Y, c.Z) == pytest.approx((0.5120501, 1.0, 0.00575), rel=1e-5)


@_needs_engine
def test_albedo_roundtrip_is_identity_under_d65():
    """Engine JH upsampling (astroray.rgb_to_spectrum) x engine D65 x engine
    CMF x engine matrix must reproduce the input RGB (the Cycles-identical
    result for a diffuse surface under a white illuminant)."""
    lams = [float(x) for x in LAM[BAND]]
    d65 = np.array([astroray.sample_d65(x) for x in lams])
    cmf = np.array([[c.X, c.Y, c.Z] for c in (astroray.cie_cmf_1931_2deg(x) for x in lams)]).T
    grid = [np.array(c) for c in itertools.product(np.linspace(0.05, 0.95, 5), repeat=3)]
    named = [np.array(c) for c in ((0.25, 0.27, 0.24), (0.15, 0.45, 0.25), (0.1, 0.1, 0.8), (0.9, 0.9, 0.92))]
    worst = (0.0, None, None)
    for rgb in grid + named:
        s = np.array(astroray.rgb_to_spectrum(rgb.tolist(), lams))
        out = M_CPU @ (s * d65 * cmf).sum(axis=1)
        err = float(np.abs(out - rgb).max())
        if err > worst[0]:
            worst = (err, rgb, out)
    # Model: 9.9e-4 (2 deg) vs 0.117 (10 deg).
    assert worst[0] < 2e-3, worst


def _white_env_sphere(albedo, *, use_gpu, spp=256):
    r = astroray.Renderer()
    r.set_background_color([1.0, 1.0, 1.0])
    m = r.create_material("lambertian", list(albedo), {})
    r.add_sphere([0.0, 0.0, 0.0], 1.0, m)
    r.set_integrator("path_tracer")
    if use_gpu:
        r.set_use_gpu(True)
    r.setup_camera([0, 0, 4], [0, 0, 0], [0, 1, 0], 40.0, 1.0, 0.0, 4.0, 80, 80)
    r.set_seed(7)
    img = np.asarray(r.render(spp, 8, None, False), dtype=np.float64).reshape(80, 80, 3)
    # World ROI = top + bottom 8 rows (1280 px). A 6x6 corner is too small:
    # the blue (z-bar) lane has high per-sample variance under the
    # luminance-weighted hero proposal (measured +-2.8 % at 256 spp).
    world = np.concatenate([img[:8].reshape(-1, 3), img[-8:].reshape(-1, 3)])
    return img[30:50, 30:50].reshape(-1, 3).mean(0), world.mean(0)


def _render_legs():
    legs = [pytest.param(False, id="cpu")]
    if AVAILABLE and astroray.__features__.get("cuda", False):
        legs.append(pytest.param(True, id="gpu"))
    return legs


@_needs_engine
@pytest.mark.parametrize("use_gpu", _render_legs())
@pytest.mark.parametrize("albedo,tol", [((0.5, 0.5, 0.5), 0.006),
                                        ((0.25, 0.27, 0.24), 0.01),
                                        ((0.1, 0.1, 0.8), 0.03)])
def test_white_env_sphere_matches_albedo(use_gpu, albedo, tol):
    """Render-level: a convex diffuse sphere under a uniform white world reflects
    exactly its albedo (Cycles gives the albedo bit-exactly). Pre-fix the 10 deg
    observer gave B x0.981 on grey, (1.011, 0.993, 0.976) on the #767 ground and
    (0.64, 1.44, 1.01) on the saturated blue."""
    if use_gpu and not astroray.Renderer().gpu_available:
        pytest.skip("CUDA GPU not available")
    sphere, env = _white_env_sphere(albedo, use_gpu=use_gpu)
    ratio = sphere / np.array(albedo)
    assert np.abs(ratio - 1.0).max() < tol, f"sphere/albedo={ratio}"
    # The directly seen white world must stay white (was B 0.983).
    assert np.abs(env - 1.0).max() < 0.004, f"env={env}"
