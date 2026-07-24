"""
pkg151 — unit tests for DisneyEnergyCompensationTables' glass (rough
dielectric transmission) lookups: the trilinear sample3D, the z(ior) remap,
and the ior<1 -> _inv_ table swap.

Independently re-implements the trilinear/bilinear interpolation and the
z = sqrt(|ior-1|/(ior+1)) remap in plain NumPy, reading the same
data/disney_compensation/ggx_glass_*.bin files the C++ loader reads, and
cross-checks against astroray_test_helpers.disney_ggx_glass_e/eavg (exposed
via module/test_helpers_module.cpp, which calls
astroray::DisneyEnergyCompensationTables::ggxGlassE/ggxGlassEavg —
plugins/materials/disney.cpp's own compensation lookup).

Table provenance: Blender Cycles intern/cycles/scene/shader.tables
(Apache-2.0), table_ggx_glass_E[16*16*16] / _Eavg[16*16] / _inv_E / _inv_Eavg.
See data/disney_compensation/README.md and
.astroray_plan/docs/pkg151-cycles-glass-tables-research.md.
"""

from __future__ import annotations

import os
import struct

import pytest

from runtime_setup import configure_test_imports

configure_test_imports()

try:
    import astroray_test_helpers
    HELPERS_AVAILABLE = True
except ImportError:
    HELPERS_AVAILABLE = False

pytestmark = pytest.mark.skipif(not HELPERS_AVAILABLE, reason="astroray_test_helpers not built")

_DATA_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data", "disney_compensation")

_SIZE = 16


def _load_bin(name: str, count: int) -> list[float]:
    path = os.path.join(_DATA_DIR, name)
    with open(path, "rb") as f:
        data = f.read()
    assert len(data) == count * 4, f"{name}: expected {count*4} bytes, got {len(data)}"
    return list(struct.unpack("<%df" % count, data))


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def _sample3d(table, roughness, mu, z):
    roughness, mu, z = _clamp01(roughness), _clamp01(mu), _clamp01(z)
    fx, fy, fz = roughness * (_SIZE - 1), mu * (_SIZE - 1), z * (_SIZE - 1)
    x0, y0, z0 = int(fx), int(fy), int(fz)
    x1, y1, z1 = min(x0 + 1, _SIZE - 1), min(y0 + 1, _SIZE - 1), min(z0 + 1, _SIZE - 1)
    tx, ty, tz = fx - x0, fy - y0, fz - z0

    def at(xi, yi, zi):
        return table[(zi * _SIZE + yi) * _SIZE + xi]

    def lerp(a, b, t):
        return a * (1.0 - t) + b * t

    c00 = lerp(at(x0, y0, z0), at(x1, y0, z0), tx)
    c10 = lerp(at(x0, y1, z0), at(x1, y1, z0), tx)
    c01 = lerp(at(x0, y0, z1), at(x1, y0, z1), tx)
    c11 = lerp(at(x0, y1, z1), at(x1, y1, z1), tx)
    c0, c1 = lerp(c00, c10, ty), lerp(c01, c11, ty)
    return lerp(c0, c1, tz)


def _sample2d(table, roughness, z):
    roughness, z = _clamp01(roughness), _clamp01(z)
    fx, fy = roughness * (_SIZE - 1), z * (_SIZE - 1)
    x0, y0 = int(fx), int(fy)
    x1, y1 = min(x0 + 1, _SIZE - 1), min(y0 + 1, _SIZE - 1)
    tx, ty = fx - x0, fy - y0
    v00, v10 = table[y0 * _SIZE + x0], table[y0 * _SIZE + x1]
    v01, v11 = table[y1 * _SIZE + x0], table[y1 * _SIZE + x1]
    vx0 = v00 * (1.0 - tx) + v10 * tx
    vx1 = v01 * (1.0 - tx) + v11 * tx
    return vx0 * (1.0 - ty) + vx1 * ty


def _z_from_ior(ior: float) -> float:
    import math
    return math.sqrt(abs((ior - 1.0) / (ior + 1.0)))


@pytest.fixture(scope="module")
def tables():
    return {
        "E": _load_bin("ggx_glass_E.bin", _SIZE ** 3),
        "Eavg": _load_bin("ggx_glass_Eavg.bin", _SIZE * _SIZE),
        "invE": _load_bin("ggx_glass_inv_E.bin", _SIZE ** 3),
        "invEavg": _load_bin("ggx_glass_inv_Eavg.bin", _SIZE * _SIZE),
    }


def test_disney_compensation_tables_loaded():
    assert astroray_test_helpers.disney_compensation_tables_loaded(), \
        "data/disney_compensation/*.bin failed to load (glass tables missing/corrupt?)"


def test_exact_grid_point_roughness0_mu0_ior1(tables):
    # roughness=0, mu=0, ior=1.0 -> z=0 -> exact grid corner (0,0,0), no
    # interpolation: the raw table[0] element.
    expected_e = tables["E"][0]
    got_e = astroray_test_helpers.disney_ggx_glass_e(0.0, 0.0, 1.0)
    assert got_e == pytest.approx(expected_e, abs=1e-6), (got_e, expected_e)

    expected_eavg = tables["Eavg"][0]
    got_eavg = astroray_test_helpers.disney_ggx_glass_eavg(0.0, 1.0)
    assert got_eavg == pytest.approx(expected_eavg, abs=1e-6), (got_eavg, expected_eavg)


def test_exact_grid_point_mu_axis_is_fastest_after_roughness(tables):
    # roughness=0, mu=1/15, ior=1.0 -> z=0 -> flat index 1 (mu is the second
    # axis; roughness=0 keeps x0=0, so index = z*256 + mu_idx*16 + 0 = 1).
    expected = tables["E"][1]
    got = astroray_test_helpers.disney_ggx_glass_e(0.0, 1.0 / 15.0, 1.0)
    assert got == pytest.approx(expected, abs=1e-6), (got, expected)


@pytest.mark.parametrize("roughness,mu,ior", [
    (0.35, 0.62, 1.5),
    (0.83, 0.12, 1.33),
    (0.05, 0.9, 2.0),
])
def test_trilinear_interpolation_matches_independent_reimplementation(tables, roughness, mu, ior):
    z = _z_from_ior(ior)
    expected_e = _sample3d(tables["E"], roughness, mu, z)
    expected_eavg = _sample2d(tables["Eavg"], roughness, z)

    got_e = astroray_test_helpers.disney_ggx_glass_e(roughness, mu, ior)
    got_eavg = astroray_test_helpers.disney_ggx_glass_eavg(roughness, ior)

    assert got_e == pytest.approx(expected_e, rel=1e-4, abs=1e-6), (got_e, expected_e)
    assert got_eavg == pytest.approx(expected_eavg, rel=1e-4, abs=1e-6), (got_eavg, expected_eavg)


@pytest.mark.parametrize("roughness,mu,ior_inv", [
    (0.3, 0.5, 1.0 / 1.5),
    (0.6, 0.2, 1.0 / 2.0),
])
def test_ior_below_one_uses_inv_table_not_normal_table(tables, roughness, mu, ior_inv):
    # ior<1 must swap to the _inv_ tables (looked up at ior'=1/ior), NOT just
    # invert the ior and query the SAME (non-inv) table -- Cycles bakes the
    # two directions asymmetrically (entering vs. exiting a rough interface
    # are not mirror images of each other).
    ior_eff = 1.0 / ior_inv
    z = _z_from_ior(ior_eff)
    expected_inv = _sample3d(tables["invE"], roughness, mu, z)
    expected_normal_wrong = _sample3d(tables["E"], roughness, mu, z)

    got = astroray_test_helpers.disney_ggx_glass_e(roughness, mu, ior_inv)

    assert got == pytest.approx(expected_inv, rel=1e-4, abs=1e-6), (got, expected_inv)
    # Sanity: the two tables actually differ at this sample point, so this
    # test would catch a "forgot to swap tables" regression.
    assert expected_inv != pytest.approx(expected_normal_wrong, rel=1e-3), \
        "test point does not discriminate normal vs inv table; pick a different sample"


def test_e_and_eavg_stay_in_unit_range(tables):
    # Directional/average albedo tables must stay in [0, 1] (physical
    # reflectance/transmittance bound) across a coarse grid, both normal and
    # inv variants.
    import itertools
    for roughness, mu, ior in itertools.product(
            [0.0, 0.3, 0.6, 1.0], [0.0, 0.5, 1.0], [0.5, 1.0, 1.5, 2.5]):
        e = astroray_test_helpers.disney_ggx_glass_e(roughness, mu, ior)
        eavg = astroray_test_helpers.disney_ggx_glass_eavg(roughness, ior)
        assert 0.0 <= e <= 1.0001, (roughness, mu, ior, e)
        assert 0.0 <= eavg <= 1.0001, (roughness, ior, eavg)
