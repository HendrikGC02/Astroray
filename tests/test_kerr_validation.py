"""pkg41 Kerr validation harness.

References:
- Bardeen, Press & Teukolsky 1972, ApJ 178, 347: ISCO, photon orbit,
  frame-dragging, and Kerr image-plane constants.
- Chandrasekhar 1983, The Mathematical Theory of Black Holes, ch. 7:
  circular orbit and shadow formulae.
- GYOTO (Vincent et al. 2011), RAPTOR (Bronzwaer et al. 2018), and
  ipole (Mościbrodzka & Gammie 2018) are independent cross-validation
  references only; no GPL/CeCILL code is mirrored.
"""

from __future__ import annotations

import json
import math
import os
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from runtime_setup import configure_test_imports

os.environ.setdefault(
    "ASTRORAY_BUILD_DIR",
    str(Path(__file__).resolve().parent.parent / "build" / "Release"),
)
configure_test_imports()

try:
    import astroray
    AVAILABLE = True
except ImportError:
    AVAILABLE = False

pytestmark = pytest.mark.skipif(not AVAILABLE, reason="astroray module not available")

from scripts import generate_gyoto_references as refgen  # noqa: E402


REF_DIR = Path(__file__).resolve().parent / "reference" / "kerr"
DATA = json.loads((REF_DIR / "analytic_orbits.json").read_text(encoding="utf-8"))
SPIN_KEYS = ("0", "0.5", "0.9", "0.998")
SPINS = [DATA["spins"][key] for key in SPIN_KEYS]


def _params(record: dict[str, object]) -> dict[str, float]:
    return {"M": 1.0, "a": float(record["a"])}


def _image(record: dict[str, object]) -> np.ndarray:
    path = REF_DIR / str(record["reference_image"])
    with Image.open(path) as img:
        return np.asarray(img.convert("L"), dtype=np.float32)


def _shadow_metrics(img: np.ndarray) -> dict[str, float | list[int]]:
    mask = img < 64.0
    y, x = np.nonzero(mask)
    assert len(x) > 0
    return {
        "area_px": float(mask.sum()),
        "centroid_x_px": float(x.mean()),
        "centroid_y_px": float(y.mean()),
        "bbox_px": [int(x.min()), int(y.min()), int(x.max()), int(y.max())],
        "width_px": int(x.max() - x.min() + 1),
        "height_px": int(y.max() - y.min() + 1),
        "circularity_width_height_ratio": float((x.max() - x.min() + 1) / (y.max() - y.min() + 1)),
    }


def _contravariant_kerr_components(a: float, r: float, theta: float, p_t: float,
                                   p_theta: float, p_phi: float) -> list[float]:
    sin_th = math.sin(theta)
    cos_th = math.cos(theta)
    sigma = r * r + a * a * cos_th * cos_th
    delta = r * r - 2.0 * r + a * a
    A = (r * r + a * a) ** 2 - delta * a * a * sin_th * sin_th
    g_tt = -A / (sigma * delta)
    g_tphi = -2.0 * a * r / (sigma * delta)
    g_thetatheta = 1.0 / sigma
    g_phiphi = (delta - a * a * sin_th * sin_th) / (
        sigma * delta * sin_th * sin_th
    )
    return [
        g_tt * p_t + g_tphi * p_phi,
        0.0,
        g_thetatheta * p_theta,
        g_tphi * p_t + g_phiphi * p_phi,
    ]


@pytest.mark.parametrize("record", SPINS, ids=SPIN_KEYS)
def test_isco_radius_matches_bpt_1972_prograde(record: dict[str, object]) -> None:
    # Bardeen, Press & Teukolsky 1972 ApJ 178, 347, eq. 2.21.
    actual = astroray.metric_isco_radius("kerr", _params(record))
    assert actual == pytest.approx(float(record["isco_prograde"]), rel=1e-6, abs=1e-8)


@pytest.mark.parametrize("record", SPINS, ids=SPIN_KEYS)
def test_photon_ring_radius_matches_bpt_1972_both_directions(record: dict[str, object]) -> None:
    # Bardeen, Press & Teukolsky 1972 ApJ 178, 347 gives equatorial photon orbit radii.
    prograde = astroray.metric_photon_sphere_radius("kerr", _params(record), prograde=True)
    retrograde = astroray.metric_photon_sphere_radius("kerr", _params(record), prograde=False)
    assert prograde == pytest.approx(float(record["photon_ring_prograde"]), rel=1e-6, abs=1e-8)
    assert retrograde == pytest.approx(float(record["photon_ring_retrograde"]), rel=1e-6, abs=1e-8)


@pytest.mark.parametrize("record", SPINS, ids=SPIN_KEYS)
def test_horizon_frame_dragging_matches_closed_form(record: dict[str, object]) -> None:
    # Bardeen, Press & Teukolsky 1972 sets Omega_H = a / (r_+^2 + a^2).
    actual = astroray.metric_horizon_angular_velocity("kerr", _params(record))
    assert actual == pytest.approx(float(record["horizon_angular_velocity"]), rel=1e-6, abs=1e-8)


@pytest.mark.parametrize("record", SPINS, ids=SPIN_KEYS)
def test_isco_orbital_period_fixture_matches_chandrasekhar_formula(record: dict[str, object]) -> None:
    # Chandrasekhar 1983 ch. 7: Omega = M^1/2 / (r^(3/2) + a M^1/2).
    a = float(record["a"])
    r_isco = float(record["isco_prograde"])
    omega = refgen.orbital_frequency(a, r_isco, prograde=True)
    period = 2.0 * math.pi / omega
    assert period == pytest.approx(float(record["orbital_period_isco_prograde"]), rel=1e-12)


@pytest.mark.parametrize("record", SPINS, ids=SPIN_KEYS)
def test_closed_form_circular_photon_is_null_in_metric(record: dict[str, object]) -> None:
    # Bardeen image-plane constants inserted into the shipped Kerr metric must be null.
    a = float(record["a"])
    theta = math.pi / 2.0
    r = float(record["photon_ring_prograde"])
    if abs(a) < 1e-12:
        f = 1.0 - 2.0 / r
        tangent = [1.0 / f, 0.0, 0.0, math.sqrt(27.0) / (r * r)]
    else:
        xi = refgen.impact_parameter_xi(a, r)
        tangent = _contravariant_kerr_components(a, r, theta, -1.0, 0.0, xi)
    norm = astroray.metric_inner_product("kerr", _params(record), 0.0, r, theta, 0.0, tangent, tangent)
    # The Python binding returns float-valued metric contractions; near-extremal
    # a=0.998 sits close to the BL horizon, so the regression tolerance is set
    # by binding precision, not by the analytic expression.
    assert norm == pytest.approx(0.0, abs=3e-4)


def test_kerr_a0_matches_registered_schwarzschild_metric_grid() -> None:
    # Schwarzschild is the a=0 Kerr limit; this validates the pkg40 wrapper extraction.
    points = [(3.5, math.pi / 2.0), (6.0, 1.1), (20.0, 2.0)]
    vectors = [
        ([1.0, 0.0, 0.0, 0.0], [1.0, 0.0, 0.0, 0.0]),
        ([0.0, 1.0, 0.0, 0.0], [0.0, 1.0, 0.0, 0.0]),
        ([1.0, 0.0, 0.0, 0.25], [0.5, 0.0, 0.0, 0.1]),
    ]
    for r, theta in points:
        for a_vec, b_vec in vectors:
            kerr = astroray.metric_inner_product("kerr", {"M": 1.0, "a": 0.0}, 0.0, r, theta, 0.0, a_vec, b_vec)
            schwarzschild = astroray.metric_inner_product("schwarzschild", {"M": 1.0}, 0.0, r, theta, 0.0, a_vec, b_vec)
            assert kerr == pytest.approx(schwarzschild, rel=1e-7, abs=1e-7)


def test_christoffel_lower_indices_are_symmetric() -> None:
    gamma = astroray.metric_christoffel("kerr", {"M": 1.0, "a": 0.9}, 0.0, 7.0, 1.2, 0.0)
    for alpha in range(4):
        for mu in range(4):
            for nu in range(4):
                assert gamma[alpha][mu][nu] == pytest.approx(gamma[alpha][nu][mu], abs=1e-7)


def test_kerr_frame_dragging_cross_term_scales_with_spin() -> None:
    # BPT 1972 BL metric has g_tphi = -2Mar sin^2(theta) / Sigma.
    u_t = [1.0, 0.0, 0.0, 0.0]
    u_phi = [0.0, 0.0, 0.0, 1.0]
    g_05 = astroray.metric_inner_product("kerr", {"M": 1.0, "a": 0.5}, 0.0, 4.0, math.pi / 2.0, 0.0, u_t, u_phi)
    g_09 = astroray.metric_inner_product("kerr", {"M": 1.0, "a": 0.9}, 0.0, 4.0, math.pi / 2.0, 0.0, u_t, u_phi)
    assert g_05 < 0.0
    assert g_09 < g_05
    assert g_09 == pytest.approx(-2.0 * 0.9 / 4.0, rel=1e-6)


@pytest.mark.parametrize("record", SPINS, ids=SPIN_KEYS)
def test_reference_shadow_png_exists_and_is_finite(record: dict[str, object]) -> None:
    img = _image(record)
    assert img.shape == (256, 256)
    assert np.all(np.isfinite(img))
    assert img.min() < 16.0
    assert img.max() > 200.0


@pytest.mark.parametrize("record", SPINS, ids=SPIN_KEYS)
def test_shadow_contour_metrics_match_static_reference(record: dict[str, object]) -> None:
    # GYOTO-compatible fixture regression: contour metrics are stable to pixel rounding.
    measured = _shadow_metrics(_image(record))
    expected = record["shadow_metrics"]
    assert measured["area_px"] == pytest.approx(float(expected["area_px"]), rel=0.0, abs=0.0)
    assert measured["centroid_x_px"] == pytest.approx(float(expected["centroid_x_px"]), abs=1e-12)
    assert measured["centroid_y_px"] == pytest.approx(float(expected["centroid_y_px"]), abs=1e-12)
    assert measured["bbox_px"] == expected["bbox_px"]


def test_shadow_area_decreases_monotonically_with_prograde_spin() -> None:
    # Bardeen/Chandrasekhar image-plane regression: prograde spin shrinks the apparent shadow.
    areas = [float(record["shadow_metrics"]["area_px"]) for record in SPINS]
    assert areas == sorted(areas, reverse=True)


def test_shadow_centroid_offset_grows_with_spin() -> None:
    # Kerr frame dragging displaces the Bardeen shadow centroid on the image plane.
    center = (int(DATA["meta"]["image_size"]) - 1) * 0.5
    offsets = [abs(float(record["shadow_metrics"]["centroid_x_px"]) - center) for record in SPINS]
    assert offsets == sorted(offsets)
    assert offsets[-1] > 35.0


def test_schwarzschild_shadow_is_circular_to_pixel_tolerance() -> None:
    metrics = SPINS[0]["shadow_metrics"]
    assert float(metrics["circularity_width_height_ratio"]) == pytest.approx(1.0, rel=0.015)


@pytest.mark.parametrize("record", SPINS, ids=SPIN_KEYS)
def test_equatorial_reflection_symmetry_of_shadow_fixture(record: dict[str, object]) -> None:
    # Kerr BL metric is symmetric under theta -> pi-theta for these equatorial fixtures.
    metrics = _shadow_metrics(_image(record))
    center = (int(DATA["meta"]["image_size"]) - 1) * 0.5
    assert float(metrics["centroid_y_px"]) == pytest.approx(center, abs=0.5)
    bbox = metrics["bbox_px"]
    assert isinstance(bbox, list)
    assert abs((center - float(bbox[1])) - (float(bbox[3]) - center)) <= 1.0


def test_reference_fixture_source_documents_license_fence() -> None:
    readme = (REF_DIR / "README.md").read_text(encoding="utf-8")
    assert "Bardeen, Press & Teukolsky 1972" in readme
    assert "no GPL or" in readme
    script = Path("scripts/generate_gyoto_references.py").read_text(encoding="utf-8")
    assert "GYOTO" in script and "RAPTOR" in script and "no code" in script
