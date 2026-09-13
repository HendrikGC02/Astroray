"""Batch J item 1 (#799 Phase 2) — engine-side spectral Nishita sky.

Engine-only tests (no Blender, no GPU): the vendored Apache/MIT sky models
(external/blender_sky/) exposed via astroray.nishita_sky / nishita_sun.

Gates covered here:
  * (3) pinned-pixel regression — the vendored precompute reproduces a fixed
    solar-disc radiance triple;
  * (4, unit level) orientation — the baked sky's brightest column sits at the
    requested sun_rotation azimuth, for BOTH modes;
  * shape / physicality / no-exposure-bridge sanity.

The Cycles-parity band ratios (gate 1) and ground direct:diffuse (gate 2) are
measured against live Blender in benchmarks/reference_corpus/sky_ab_bands.py and
the batch-J A/B harness; they are not reproducible without Blender so they are
not asserted here.
"""
import math

import numpy as np
import pytest

import astroray

MODES = ("SINGLE_SCATTERING", "MULTIPLE_SCATTERING")


@pytest.mark.parametrize("mode", MODES)
def test_nishita_sky_shape_and_physical(mode):
    sky = astroray.nishita_sky(mode, 256, 128, math.radians(28.0), math.radians(115.0),
                               100.0, 1.0, 1.0, 1.0)
    assert sky.shape == (128, 256, 3)
    assert sky.dtype == np.float32
    assert np.all(np.isfinite(sky))
    assert float(sky.min()) >= 0.0  # xyz_to_rgb_clamped clamps negatives
    # Zenith (row 0) is bluer than the horizon band (Rayleigh); horizon is
    # brighter (longer optical path, forward scatter).
    zenith = sky[0].mean(axis=0)
    horizon = sky[sky.shape[0] // 2].mean(axis=0)
    assert zenith[2] > zenith[0], ("zenith should be blue-dominant", zenith)
    lum = lambda c: 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]
    assert lum(horizon) > lum(zenith), (lum(horizon), lum(zenith))


def test_no_exposure_bridge_values_are_order_one():
    """The 1/1766 LUM_TO_RADIANCE bridge is gone; the table is already in
    Cycles' radiometric units, so sky radiance is O(1-10), not O(1e-3)."""
    sky = astroray.nishita_sky("MULTIPLE_SCATTERING", 256, 128, math.radians(28.0), 0.0,
                               100.0, 1.0, 1.0, 1.0)
    assert 0.1 < float(sky.mean()) < 100.0, float(sky.mean())


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("rot_deg", [0.0, 45.0, 115.0, 270.0])
def test_sun_azimuth_orientation(mode, rot_deg):
    """The baked sky's brightest column must sit at the requested sun_rotation
    azimuth (both models, despite their opposite native sun-X convention)."""
    w, h = 720, 180
    sky = astroray.nishita_sky(mode, w, h, math.radians(20.0), math.radians(rot_deg),
                               100.0, 1.0, 1.0, 1.0)
    lum = 0.2126 * sky[:, :, 0] + 0.7152 * sky[:, :, 1] + 0.0722 * sky[:, :, 2]
    cmax = int(np.argmax(lum.sum(axis=0)))
    az = ((cmax + 0.5) / w - 0.5) * 360.0
    # Wrap the signed difference into [-180, 180].
    diff = (az - rot_deg + 180.0) % 360.0 - 180.0
    assert abs(diff) <= 1.5, (mode, rot_deg, az, diff)


# Pinned solar-disc radiance triples (linear RGB) from the vendored
# precompute_sun at sun_elevation=28 deg, sun_size=0.009512 rad, altitude=100 m,
# unit densities. Regression pin (gate 3): changing the vendored model or the
# XYZ->RGB conversion must be a deliberate, reviewed change.
_SUN_PINS = {
    "MULTIPLE_SCATTERING": {
        "bottom": (2593678.0, 2109483.5, 1473699.125),
        "top": (2602627.25, 2121300.0, 1488951.0),
    },
    "SINGLE_SCATTERING": {
        "bottom": (2450398.25, 1933862.875, 1351806.75),
        "top": (2457401.5, 1943081.375, 1365131.25),
    },
}


@pytest.mark.parametrize("mode", MODES)
def test_nishita_sun_pinned_triple(mode):
    bottom, top = astroray.nishita_sun(mode, math.radians(28.0), 0.009512,
                                       100.0, 1.0, 1.0, 1.0)
    exp = _SUN_PINS[mode]
    for got, want in zip(bottom, exp["bottom"]):
        assert got == pytest.approx(want, rel=2e-3), (mode, "bottom", got, want)
    for got, want in zip(top, exp["top"]):
        assert got == pytest.approx(want, rel=2e-3), (mode, "top", got, want)
    # Sun below the horizon -> black disc (precompute_sun returns zeros).
    b2, t2 = astroray.nishita_sun(mode, math.radians(-5.0), 0.009512, 100.0, 1.0, 1.0, 1.0)
    assert max(b2) == pytest.approx(0.0, abs=1e-3), b2
    assert max(t2) == pytest.approx(0.0, abs=1e-3), t2
