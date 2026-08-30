#!/usr/bin/env python
"""pkg29 — spectral dielectric prism validation."""

from __future__ import annotations

import os
import sys

import numpy as np
import pytest

from runtime_setup import configure_test_imports

configure_test_imports()
sys.path.insert(0, os.path.dirname(__file__))

try:
    import astroray  # noqa: E402
    AVAILABLE = True
except ImportError:
    AVAILABLE = False

from base_helpers import save_image  # noqa: E402
from scenes.prism_reference import (  # noqa: E402
    HEIGHT,
    WIDTH,
    bright_region_mean_chroma_and_spread,
    red_blue_centroid_separation,
    render_prism,
    render_spectral_prism,
)


pytestmark = pytest.mark.skipif(not AVAILABLE, reason="astroray not built")

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROFILES_BIN = os.path.join(REPO_ROOT, "data", "spectral_profiles", "profiles.bin")
HAS_PROFILES = os.path.exists(PROFILES_BIN)


def test_dispersive_prism_render_is_finite_and_saved(test_results_dir):
    pixels = render_prism(astroray, dispersive=True, seed=17)
    save_image(pixels, os.path.join(test_results_dir, "pkg29_dispersive_prism.png"))

    assert pixels.shape == (HEIGHT, WIDTH, 3)
    assert np.isfinite(pixels).all()
    assert float(pixels.mean()) > 0.01
    assert float(pixels.max()) > 0.1


def test_dispersive_prism_has_measurable_color_spread(test_results_dir):
    flat = render_prism(astroray, dispersive=False, seed=17)
    dispersive = render_prism(astroray, dispersive=True, seed=17)

    save_image(flat, os.path.join(test_results_dir, "pkg29_flat_prism.png"))
    save_image(dispersive, os.path.join(test_results_dir, "pkg29_bk7_prism.png"))

    diff = np.abs(dispersive - flat)
    flat_sep = red_blue_centroid_separation(flat)
    dispersive_sep = red_blue_centroid_separation(dispersive)

    print(f"\n  flat red/blue centroid separation: {flat_sep:.3f}px")
    print(f"  BK7 red/blue centroid separation:  {dispersive_sep:.3f}px")
    print(f"  max absolute RGB diff:             {float(diff.max()):.4f}")

    assert np.isfinite(dispersive).all()
    assert float(diff.mean()) > 0.02
    assert float(diff.max()) > 0.25
    # Dispersion must add clear red/blue spatial separation beyond the flat prism.
    # Threshold relaxed 3.0 -> 2.0 px after the 2026-05-30 refraction fix (dielectric
    # enter/exit now keys off rec.frontFace, correcting the exit Snell angle): the
    # corrected refraction shifted the dispersion magnitude to ~2.77 px extra (still a
    # clear red-left/blue-right split — verified visually). See
    # .astroray_plan/docs/glass-dark-energy-bug-2026-05-30.md.
    assert dispersive_sep - flat_sep > 2.0


# --- pkg208: chromatic-light-source dispersion oracle ---------------------
#
# Cycles superiority oracle (no engine change): a spectrally-narrow light
# source refracted through a dispersive prism must disperse into a
# single-hue band, NOT a full rainbow -- because a true spectral renderer
# carries the source SPD to the dispersive event, unlike Cycles' RGB
# hero-wavelength pipeline (which cannot know the source SPD; PR #162041
# author: "we don't know the spectrum of the light source"). See
# .astroray_plan/docs/pkg208-dispersion-oracle-research.md for the full
# citation trail and the reason this reuses the panel-through-prism scene
# (ordinary NEE + specular transmission, no caustics/photon-mapping needed).

pytestmark_profiles = pytest.mark.skipif(not HAS_PROFILES, reason="profiles.bin not found")


@pytestmark_profiles
def test_narrow_line_band_is_amber_hued(test_results_dir):
    """pkg208 predicate 1: the sodium_vapor (~589 nm) line's dispersed band is
    amber/yellow-dominant (R > G > 3*B in chromaticity), not a rainbow."""
    astroray.load_spectral_profiles(PROFILES_BIN)
    sodium = render_spectral_prism(astroray, profile_name="sodium_vapor", seed=17)
    save_image(sodium, os.path.join(test_results_dir, "pkg208_sodium_prism.png"))

    assert np.isfinite(sodium).all()
    mean_chroma, _ = bright_region_mean_chroma_and_spread(sodium)
    R, G, B = (float(c) for c in mean_chroma)
    print(f"\n  sodium_vapor dispersed-band mean chroma (R,G,B) = ({R:.4f}, {G:.4f}, {B:.4f})")
    assert R > 1e-3, f"pkg208 FAIL: sodium-line band emits no light -- R={R:.4f}"
    assert R > G > 3.0 * B, (
        f"pkg208 FAIL: sodium-line band is not amber -- R={R:.4f} G={G:.4f} B={B:.4f} "
        f"(need R > G > 3*B)"
    )


@pytestmark_profiles
def test_narrow_line_disperses_narrower_than_broadband(test_results_dir):
    """pkg208 predicate 2 (the crux): the sodium_vapor narrow-line prism band's
    chromaticity spread is well below the led_6500k broadband control's --
    reusing the same prism, only the light's SPD changes. If this INVERTS
    (narrow-line disperses as widely as broadband, or wider), that is a real
    engine defect -- source SPD not reaching the dispersive event -- and must
    be filed as a separate spec, not papered over here (spec pkg208 S1)."""
    astroray.load_spectral_profiles(PROFILES_BIN)
    sodium = render_spectral_prism(astroray, profile_name="sodium_vapor", seed=17)
    broadband = render_spectral_prism(astroray, profile_name="led_6500k", seed=17)
    save_image(broadband, os.path.join(test_results_dir, "pkg208_led6500k_prism.png"))

    assert np.isfinite(sodium).all()
    assert np.isfinite(broadband).all()

    _, sodium_spread = bright_region_mean_chroma_and_spread(sodium)
    _, broadband_spread = bright_region_mean_chroma_and_spread(broadband)
    print(f"\n  sodium_vapor chromaticity spread:  {sodium_spread:.4f}")
    print(f"  led_6500k    chromaticity spread:  {broadband_spread:.4f}")

    assert broadband_spread > 0.1, (
        f"pkg208 FAIL: broadband control shows no measurable dispersion spread "
        f"({broadband_spread:.4f}) -- control scene is not exercising dispersion"
    )
    # The crux assertion: narrow-line disperses into a MUCH tighter hue band
    # than the broadband control through the same prism. Measured ~0.015 vs
    # ~0.49 (~33x) during development; use a generous 3x margin so ordinary
    # MC-noise variation across seeds/builds cannot flip this.
    assert sodium_spread < broadband_spread / 3.0, (
        f"pkg208 FAIL: sodium-line dispersion spread ({sodium_spread:.4f}) is not "
        f"well below the broadband control's ({broadband_spread:.4f}) -- "
        f"expected narrow-line spread < broadband/3"
    )
