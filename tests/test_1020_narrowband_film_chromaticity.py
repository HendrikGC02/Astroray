"""#1020: a narrow-band lamp's rendered colour equals the CIE 1931 integral of its own stored SPD.

Root cause: the film conversion (XYZ -> linear sRGB of the final pixel, CPU and GPU) desaturated out-of-gamut
colours toward white by adding -min(r, g, b) to every channel. A sodium lamp is outside the sRGB gamut (B < 0), so
the film added |B| of white: R/G fell from the CIE value 4.5 to 3.9 and luminance rose. pkg307's Mitsuba
arbitration (narrow-band wall) measured exactly that. The film now uses the exact IEC 61966-2-1 matrix and clips
negative channels to 0 per channel (R and G exact, B clipped).

Analytic expectation: a grey Lambertian floor under a sun whose emission is the ``sodium_vapor`` profile reflects
L(lambda) proportional to SPD(lambda); its colour is M_sRGB @ integral SPD * CMF (CIE 1931 2 deg, the engine's own
table), independent of the absolute scale.
"""
import math
import re
from pathlib import Path

import astroray
import numpy as np
import pytest

ROOT = Path(__file__).resolve().parent.parent
PROFILE = "sodium_vapor"
PROFILES_BIN = ROOT / "data" / "spectral_profiles" / "profiles.bin"
pytestmark = pytest.mark.skipif(not PROFILES_BIN.is_file(), reason="profiles.bin not found")


@pytest.fixture(autouse=True)
def _profiles():
    astroray.load_spectral_profiles(str(PROFILES_BIN))


# IEC 61966-2-1 XYZ(D65) -> linear sRGB (test_issue767 pins the engine matrices to this).
M_SRGB = np.array([[3.2406, -1.5372, -0.4986], [-0.9689, 1.8758, 0.0415], [0.0557, -0.2040, 1.0570]])


def _cmf():
    txt = (ROOT / "data" / "spectra" / "cie_cmf.inc").read_text(encoding="utf-8")
    rows = []
    for name in ("kCieCmfX", "kCieCmfY", "kCieCmfZ"):
        body = re.search(name + r"\[\d+\]\s*=\s*\{(.*?)\};", txt, re.DOTALL).group(1)
        rows.append([float(v.strip().rstrip("f")) for v in body.split(",") if v.strip()])
    return np.array(rows)  # 3 x 471, 360..830 nm at 1 nm


def _expected_rgb():
    lam = np.arange(360.0, 831.0)
    spd = np.array([astroray.spectral_profile_reflectance(PROFILE, float(w)) for w in lam])
    return M_SRGB @ (_cmf() * spd).sum(axis=1)


def _render(gpu):
    import base_helpers as bh
    r = bh.create_renderer()
    if gpu:
        try:
            r.set_use_gpu(True)
        except Exception as e:  # noqa: BLE001 - CPU-only build
            pytest.skip(f"GPU unavailable: {e}")
        if not getattr(r, "gpu_available", False):
            pytest.skip("gpu_available is False")
    elif hasattr(r, "set_use_gpu"):
        r.set_use_gpu(False)
    r.set_seed(1020)
    r.set_background_color([0.0, 0.0, 0.0])
    grey = r.create_material("lambertian", [0.8, 0.8, 0.8], {})
    e = 50.0
    r.add_triangle([-e, 0, -e], [e, 0, -e], [e, 0, e], grey)
    r.add_triangle([-e, 0, -e], [e, 0, e], [-e, 0, e], grey)
    r.add_sun_light_dedicated(direction=[0.0, -1.0, 0.0], angular_diameter=math.radians(1.0),
                              emission={"mode": "measured_spd", "profile_name": PROFILE}, intensity=5.0)
    bh.setup_camera(r, look_from=[0.0, 20.0, 0.01], look_at=[0, 0, 0], vup=[0, 0, -1], vfov=10.0, width=32, height=32)
    img = bh.render_image(r, samples=256, max_depth=2, apply_gamma=False)
    return np.asarray(img, dtype=np.float64)[..., :3].reshape(-1, 3).mean(axis=0)


def test_sodium_profile_is_out_of_the_srgb_gamut():
    """Precondition of the regression: the exact colour has a negative blue channel."""
    rgb = _expected_rgb()
    assert rgb[0] > 0 and rgb[1] > 0 and rgb[2] < 0, rgb
    assert rgb[0] / rgb[1] == pytest.approx(4.5, rel=0.03)  # pkg307: CIE integral 4.51, Mitsuba 4.61 (incl. albedo)


@pytest.mark.parametrize("gpu", [False, True], ids=["cpu", "gpu"])
def test_narrowband_rg_matches_cie_integral(gpu):
    exp = _expected_rgb()
    got = _render(gpu)
    # Pre-fix: R/G 3.90 against 4.51 (-14 %); the MC error of the ratio at 262k samples is < 0.5 %.
    assert got[0] / got[1] == pytest.approx(exp[0] / exp[1], rel=0.02), (got, exp)
    # Negative blue is clipped to 0 per channel, not lifted by adding white to R and G.
    assert got[2] <= 1e-3 * got[0], got
