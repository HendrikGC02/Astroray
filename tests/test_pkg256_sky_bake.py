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

import sky_bake

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
    return round(row) % height, round(col) % width


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
                                   aerosol_density=1.0,
                                   width=W, height=H)
    preetham = sky_bake.bake_params("PREETHAM", E, A, turbidity=6.0,
                                    width=W, height=H)
    assert not np.allclose(nishita, preetham)


def test_dropped_sockets_named():
    """pkg200: sockets/props the bake does not honour are enumerated verbatim.
    #799: sun_disc/sun_size/sun_intensity are now HONOURED (dedicated sun light)
    and must NOT appear; sun_limb_darkening is the remaining sun non-goal."""
    assert sky_bake.DROPPED_SOCKETS == (
        "sun_direction", "altitude", "air_density", "ozone_density",
        "ground_albedo", "sun_limb_darkening", "Vector",
    )
    for honoured in ("sun_disc", "sun_size", "sun_intensity"):
        assert honoured not in sky_bake.DROPPED_SOCKETS


def test_exposure_constant_is_derived_decomposition():
    """#799: LUM_TO_RADIANCE = (1/K_m photopic) x (Cycles-Nishita exposure),
    not an opaque magic number. K_m = 683 lm/W; the product is exactly 1/1766
    (corpus Nishita gate unchanged)."""
    assert sky_bake.PHOTOPIC_LUMINOUS_EFFICACY == 683.0
    expected = sky_bake.CYCLES_NISHITA_EXPOSURE / sky_bake.PHOTOPIC_LUMINOUS_EFFICACY
    assert sky_bake.LUM_TO_RADIANCE == expected
    assert abs(sky_bake.LUM_TO_RADIANCE - 1.0 / 1766.0) < 1e-15


def test_sun_disc_params_disabled_returns_none():
    node = SkyNode(sun_disc=False)
    assert sky_bake.sun_disc_params_from_node(node) is None


def test_sun_disc_params_enabled_shape_and_direction():
    E, A = math.radians(28.0), math.radians(115.0)
    node = SkyNode(sky_type="MULTIPLE_SCATTERING", sun_disc=True,
                   sun_elevation=E, sun_rotation=A, sun_size=0.009512,
                   sun_intensity=1.0)
    p = sky_bake.sun_disc_params_from_node(node)
    assert p is not None
    # travel direction == -sun (sun points toward the sun, light travels away).
    ce, se = math.cos(E), math.sin(E)
    sun = (ce * math.cos(A), ce * math.sin(A), se)
    assert p["direction"] == pytest.approx([-sun[0], -sun[1], -sun[2]], abs=1e-9)
    assert p["angular_diameter"] == pytest.approx(0.009512)
    assert p["intensity"] > 0.0
    # unit-luminance disc colour
    c = p["color"]
    lum = 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]
    assert lum == pytest.approx(1.0, abs=1e-6)


def test_sun_disc_irradiance_integral():
    """E_sun = L_sun . Omega_disc . sun_intensity . LUM_TO_RADIANCE — the
    returned intensity must equal that closed form (Beer-Lambert direct beam)."""
    E = math.radians(28.0)
    t = sky_bake._effective_turbidity("MULTIPLE_SCATTERING", 2.0, 1.0)
    air_mass = 1.0 / math.sin(E)
    tau = sky_bake._optical_depth(t)
    l_sun = sky_bake.SOLAR_DISC_LUMINANCE * math.exp(-tau * air_mass)
    omega = 2.0 * math.pi * (1.0 - math.cos(0.5 * sky_bake.DEFAULT_SUN_SIZE))
    expected = l_sun * omega * 1.0 * sky_bake.LUM_TO_RADIANCE
    p = sky_bake.sun_disc_params("MULTIPLE_SCATTERING", E, 0.0,
                                 aerosol_density=1.0,
                                 sun_size=sky_bake.DEFAULT_SUN_SIZE,
                                 sun_intensity=1.0)
    assert p["intensity"] == pytest.approx(expected, rel=1e-9)


def test_sun_disc_intensity_scales_and_dims_with_air_mass():
    """sun_intensity is linear; a lower sun (more air mass) is dimmer."""
    hi = sky_bake.sun_disc_params("MULTIPLE_SCATTERING", math.radians(60), 0.0)
    lo = sky_bake.sun_disc_params("MULTIPLE_SCATTERING", math.radians(10), 0.0)
    assert lo["intensity"] < hi["intensity"]  # Beer-Lambert: low sun attenuated
    x2 = sky_bake.sun_disc_params("MULTIPLE_SCATTERING", math.radians(60), 0.0,
                                  sun_intensity=2.0)
    assert x2["intensity"] == pytest.approx(2.0 * hi["intensity"], rel=1e-9)


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
        pytest.skip(f"astroray module not available: {e}")


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


# --- Cycles A/B: sky-band luminance within 25% (Blender-gated, serial) --------
_BLENDER = os.environ.get(
    "ASTRORAY_BLENDER",
    r"C:/Program Files/Blender Foundation/Blender 5.2/blender.exe")
_AB_SCRIPT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "benchmarks", "reference_corpus", "sky_ab_bands.py")


@pytest.fixture(scope="module")
def blender_ab_stdout():
    """Run the Cycles-vs-bake A/B script inside Blender ONCE and hand its stdout
    to every A/B test (band luminance + sun column), so Blender launches a
    single time. Skips cleanly when Blender 5.2 is not installed."""
    import subprocess
    if not os.path.exists(_BLENDER):
        pytest.skip("Blender 5.2 not installed - local-host gate")
    proc = subprocess.run([_BLENDER, "-b", "--factory-startup", "--python", _AB_SCRIPT],
                          capture_output=True, text=True, timeout=300, check=False)
    return proc.stdout, proc.stderr


def _ab_line(stdout, tag):
    return next((ln for ln in stdout.splitlines() if ln.startswith(tag + " ")), None)


@pytest.mark.serial
def test_sky_band_luminance_within_25pct_of_cycles(blender_ab_stdout):
    """Render the corpus world_sky_sky scene in Cycles at low res, bake the same
    sky, project it into the camera, and compare the per-band MEAN LUMINANCE.
    Gated loosely (±25% per band) — the per-channel colour differs by design
    (Preetham warm horizon vs Cycles' Nishita blue). Requires Blender 5.2."""
    import json
    stdout, stderr = blender_ab_stdout
    line = _ab_line(stdout, "PKG256_AB")
    assert line is not None, f"no A/B result:\n{stdout[-2000:]}\n{stderr[-1000:]}"
    res = json.loads(line[len("PKG256_AB "):])
    for band, data in res.items():
        assert abs(data["ratio_lum"] - 1.0) <= 0.25, (band, data)


@pytest.mark.serial
def test_sun_column_matches_cycles(blender_ab_stdout):
    """Azimuth zero-reference gate (PR #793 review item 3). The per-band A/B is
    azimuth-insensitive, so a +X/+Y sun-axis swap or a 90° azimuth error would
    pass it silently. Here the brightest sky COLUMN of the Cycles render and of
    the baked sky projected through the SAME camera must land on the same side
    of the frame. Measured (240px wide, sun az 115°, elev 28°): cycles_col 41,
    bake_col 26 -> dcol 15px (6.25%). Gate at 15% of width: comfortably passes
    the real broad-peak offset yet fails a 90° swap (which moves the peak >25%
    of the frame or off-screen entirely)."""
    import json
    stdout, stderr = blender_ab_stdout
    line = _ab_line(stdout, "PKG256_SUNCOL")
    assert line is not None, f"no sun-column result:\n{stdout[-2000:]}\n{stderr[-1000:]}"
    res = json.loads(line[len("PKG256_SUNCOL "):])
    assert res["dcol_frac"] <= 0.15, res
