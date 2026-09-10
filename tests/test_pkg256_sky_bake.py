# -*- coding: utf-8 -*-
"""pkg256 — Sky-texture (`ShaderNodeTexSky`) bake tests (CPU, no Blender).

Verifies the Preetham/Perez equirect bake in `blender_addon/sky_bake.py`:
determinism, zenith-is-up orientation, sun lands at the requested
azimuth/elevation (argmax), radiance ordering (brighter near a low sun),
`sky_type` changes output, the degradation-warning socket list, and — through
the real engine — that the baked temp file loads via
`renderer.load_environment_map` and its orientation matches
`eval_env_rgb_upsample`.
"""

import math
import os
import sys
import tempfile

import numpy as np
import pytest

# sky_bake imports only math + numpy (no bpy), so import it standalone rather
# than through the bpy-dependent blender_addon package.
_ADDON_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "blender_addon")
if _ADDON_DIR not in sys.path:
    sys.path.insert(0, _ADDON_DIR)

import sky_bake  # noqa: E402

pytestmark = pytest.mark.cpu

W, H = 512, 256


class SkyNode:
    """Duck-typed ShaderNodeTexSky stub."""

    def __init__(self, **kw):
        self.sky_type = "SINGLE_SCATTERING"
        self.sun_elevation = math.radians(15.0)
        self.sun_rotation = math.radians(115.0)
        self.turbidity = 2.0
        self.air_density = 1.0
        self.aerosol_density = 1.0
        self.__dict__.update(kw)


def _expected_sun_pixel(elevation, rotation, width=W, height=H):
    """Row/col the sun should land on, per research note §4."""
    row = (0.5 * math.pi - elevation) / math.pi * height
    col = ((0.5 - rotation / (2.0 * math.pi)) % 1.0) * width
    return int(round(row)) % height, int(round(col)) % width


def test_bake_finite_and_nonuniform():
    img = sky_bake.bake_params("SINGLE_SCATTERING", math.radians(15),
                               math.radians(115), width=W, height=H)
    assert img.shape == (H, W, 3)
    assert img.dtype == np.float32
    assert np.all(np.isfinite(img))
    assert img.min() >= 0.0
    # Not a flat solid colour.
    assert img.std() > 1e-3
    assert img.max() > 2.0 * (img.mean() + 1e-6)


def test_bake_deterministic():
    a = sky_bake.bake_params("SINGLE_SCATTERING", 0.3, 1.1, width=W, height=H)
    b = sky_bake.bake_params("SINGLE_SCATTERING", 0.3, 1.1, width=W, height=H)
    assert np.array_equal(a, b)


def test_zenith_is_top_row():
    """+Z (Blender up) must map to the top image row (row 0). For a low sun the
    zenith is dimmer than the sun band lower down."""
    E = math.radians(10.0)
    img = sky_bake.bake_params("SINGLE_SCATTERING", E, math.radians(115),
                               width=W, height=H)
    lum = img.sum(axis=2)
    sun_row, _ = _expected_sun_pixel(E, math.radians(115))
    # top row (zenith) darker than the sun's row for a low sun
    assert lum[0].mean() < lum[sun_row].max()


@pytest.mark.parametrize("elev_deg,rot_deg", [(15, 115), (45, 0), (30, 250), (5, 340)])
def test_sun_lands_at_requested_azimuth_elevation(elev_deg, rot_deg):
    E, A = math.radians(elev_deg), math.radians(rot_deg)
    img = sky_bake.bake_params("SINGLE_SCATTERING", E, A, width=W, height=H)
    lum = img.sum(axis=2)
    r, c = np.unravel_index(int(np.argmax(lum)), lum.shape)
    er, ec = _expected_sun_pixel(E, A)
    # within a few pixels (the circumsolar Perez peak is broad)
    assert abs(int(r) - er) <= 3, (r, er)
    dc = min(abs(int(c) - ec), W - abs(int(c) - ec))  # wrap-around azimuth
    assert dc <= 3, (c, ec)


def test_radiance_ordering_near_sun_vs_antisolar():
    """Horizon toward the sun is brighter than the horizon opposite it."""
    E, A = math.radians(12.0), math.radians(0.0)
    img = sky_bake.bake_params("SINGLE_SCATTERING", E, A, width=W, height=H)
    lum = img.sum(axis=2)
    sun_row, sun_col = _expected_sun_pixel(E, A)
    anti_col = (sun_col + W // 2) % W
    assert lum[sun_row, sun_col] > lum[sun_row, anti_col]


def test_sky_type_changes_output():
    E, A = math.radians(20.0), math.radians(60.0)
    nishita = sky_bake.bake_params("SINGLE_SCATTERING", E, A,
                                   air_density=1.0, aerosol_density=1.0,
                                   width=W, height=H)
    preetham = sky_bake.bake_params("PREETHAM", E, A, turbidity=6.0,
                                    width=W, height=H)
    assert not np.allclose(nishita, preetham)


def test_dropped_sockets_named():
    """pkg200: sockets/props the bake does not honour are enumerated verbatim."""
    assert sky_bake.DROPPED_SOCKETS == (
        "sun_disc", "sun_size", "sun_intensity", "altitude",
        "ozone_density", "ground_albedo", "Vector",
    )


def test_write_hdr_roundtrip_numpy():
    """write_hdr produces a file whose RGBE decodes back close to the source."""
    img = sky_bake.bake_params("PREETHAM", math.radians(30), 0.0,
                               turbidity=3.0, width=64, height=32)
    fd, path = tempfile.mkstemp(suffix=".hdr")
    os.close(fd)
    try:
        sky_bake.write_hdr(path, img)
        raw = np.fromfile(path, dtype=np.uint8)
        # skip header up to the first byte after the resolution line
        hdr_end = bytes(raw.tobytes()).index(b"+X ")
        hdr_end = bytes(raw.tobytes()).index(b"\n", hdr_end) + 1
        rgbe = raw[hdr_end:].reshape(32, 64, 4).astype(np.float64)
        f = np.ldexp(1.0, (rgbe[..., 3] - 136).astype(int))
        dec = (rgbe[..., :3] + 0.5) * f[..., None]
        # RGBE is ~1% relative; compare where source is bright enough
        m = img.max(axis=2) > 1.0
        rel = np.abs(dec[m] - img[m]) / (img[m] + 1e-3)
        assert np.median(rel) < 0.05
    finally:
        os.unlink(path)


def test_bake_to_equirect_from_node_stub():
    node = SkyNode(sky_type="HOSEK_WILKIE", turbidity=4.0)
    img = sky_bake.bake_to_equirect(node, width=128, height=64)
    assert img.shape == (64, 128, 3)
    assert np.all(np.isfinite(img)) and img.max() > 0.0


# --- Engine-level: temp file loads and its orientation matches the engine ----
@pytest.fixture(scope="module")
def astroray_mod():
    try:
        import astroray
        return astroray
    except ImportError as e:
        pytest.skip("astroray module not available: %s" % e)


def test_temp_file_loads_and_orientation_matches_engine(astroray_mod):
    """Bake a low sun, write the temp .hdr, load through load_environment_map
    with blender_convention=True (as setup_world does), then confirm the
    Blender-frame sun direction is the brightest sampled direction via
    eval_env_rgb_upsample — closing the orientation loop through the real
    EnvironmentMap C++ code."""
    E, A = math.radians(15.0), math.radians(115.0)
    img = sky_bake.bake_params("SINGLE_SCATTERING", E, A, width=1024, height=512)
    fd, path = tempfile.mkstemp(prefix="astroray_sky_test_", suffix=".hdr")
    os.close(fd)
    try:
        sky_bake.write_hdr(path, img)
        r = astroray_mod.Renderer()
        ok = r.load_environment_map(path, 1.0, 0.0, 0.0, 0.0,
                                    1.0, 1.0, 1.0, True)
        assert ok, "load_environment_map failed on baked sky HDRI"

        def lum(direction):
            s = r.eval_env_rgb_upsample(list(direction), 0.5)
            return float(sum(s))

        ce, se = math.cos(E), math.sin(E)
        sun = (ce * math.cos(A), ce * math.sin(A), se)
        sun_lum = lum(sun)
        # sample a grid of world directions; the sun must be near the top
        rng = np.random.default_rng(0)
        others = []
        for _ in range(200):
            v = rng.normal(size=3)
            v = v / np.linalg.norm(v)
            if v[2] < 0:      # upper hemisphere only (sky)
                v[2] = -v[2]
            others.append(lum(tuple(v)))
        others = np.array(others)
        # the sun direction should be brighter than ~95% of random sky dirs
        assert sun_lum >= np.quantile(others, 0.95), (sun_lum, np.quantile(others, 0.95))
    finally:
        os.unlink(path)
