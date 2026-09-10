#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
#786 / #787 — World Mapping rotation + diffuse env illumination repro.

Two defects seen in the pkg259 Phase 2 corpus scene world_sky_hdri.blend
(World = TexCoord.Generated -> Mapping(Rotation (0,0,115 deg)) -> TexEnvironment
-> Background 1.15), both rendered through the addon world lowering, which
loads the env map with blender_convention=True and passes the Mapping Euler as
(rx, ry, rz):

  #786  A world Mapping (0, 0, theta) must be a PURE YAW: the HDRI horizon
        stays horizontal and the sky stays up. On main the yaw is applied on
        the wrong side of the Z-up -> env-Y-polar basis change, so it becomes
        a ROLL about a horizontal axis (horizon runs vertically ~90 deg off).

  #787  A diffuse surface under the same rotated HDRI renders near-black even
        though the environment is reachable (a mirror shows it). Hypothesis:
        the roll rotates the bright sky to a horizontal/downward world
        direction, so an up-facing diffuse surface no longer sees it and its
        upward hemisphere samples the HDRI's dark ground band instead.

These are in-process (no Blender). The synthetic HDRIs are written to a temp
Radiance .hdr and loaded by the engine. The reference for the Mapping/equirect
convention is Cycles direction_to_equirectangular + MappingNode (Apache-2.0);
Blender's Mapping "Point" node applies out = Euler(rot).to_matrix() @ vec, i.e.
the standard right-handed Rz for a (0,0,theta) rotation.
"""
import math
import os
import sys

import numpy as np
import pytest

from runtime_setup import configure_test_imports

configure_test_imports()
sys.path.insert(0, os.path.dirname(__file__))

try:
    import astroray
    AVAILABLE = True
except ImportError:
    AVAILABLE = False

from base_helpers import setup_camera  # noqa: E402

pytestmark = pytest.mark.skipif(not AVAILABLE, reason="astroray not built")


# ---------------------------------------------------------------------------
# Radiance .hdr writer (RGBE) — same encoder as test_world_hdri_parity.py.
# Reference: Greg Ward, "Real Pixels", Graphics Gems II (1991).
# ---------------------------------------------------------------------------

def _write_radiance_hdr(path, img):
    img = np.asarray(img, dtype=np.float32)
    height, width = img.shape[:2]
    rgbe = np.zeros((height, width, 4), dtype=np.uint8)
    m = np.max(img, axis=2)
    valid = m > 1e-32
    mant, exp = np.frexp(np.where(valid, m, 1.0))
    scale = np.where(valid, mant * 256.0 / np.where(m > 0, m, 1.0), 0.0)
    rgbe[..., 0] = np.clip(np.floor(img[..., 0] * scale), 0, 255).astype(np.uint8)
    rgbe[..., 1] = np.clip(np.floor(img[..., 1] * scale), 0, 255).astype(np.uint8)
    rgbe[..., 2] = np.clip(np.floor(img[..., 2] * scale), 0, 255).astype(np.uint8)
    rgbe[..., 3] = np.where(valid, exp + 128, 0).astype(np.uint8)
    with open(path, 'wb') as f:
        f.write(b"#?RADIANCE\n")
        f.write(b"FORMAT=32-bit_rle_rgbe\n\n")
        f.write(f"-Y {height} +X {width}\n".encode('ascii'))
        f.write(rgbe.tobytes())


def _rz(theta):
    """Standard right-handed rotation about +Z (Blender Mapping (0,0,theta))."""
    c, s = math.cos(theta), math.sin(theta)
    return np.array([[c, -s, 0.0], [s, c, 0.0], [0.0, 0.0, 1.0]], dtype=np.float64)


def _env_brightness(r, direction, strata=(0.0, 0.25, 0.5, 0.75)):
    """Sum spectral env radiance over wavelength strata -> scalar brightness."""
    total = 0.0
    d = list(direction)
    for u in strata:
        total += float(np.sum(np.abs(np.array(r.eval_env_spectral(d, u)))))
    return total


# ---------------------------------------------------------------------------
# Synthetic HDRIs
# ---------------------------------------------------------------------------

def _sky_ground_hdri(width=64, height=32):
    """Bright top band (sky), dark bottom band (ground) — vertical structure
    only, so a PURE YAW must leave the pole (straight-up) lookup unchanged."""
    img = np.full((height, width, 3), 0.02, dtype=np.float32)  # dim ground default
    img[: height // 2, :, :] = 8.0   # top rows bright (sky)
    return img


def _azimuth_quadrant_hdri(width=64, height=32):
    """Four distinct pure-colour azimuth wedges, constant in elevation.

    Column x -> u = x/width -> azimuth. Uniform over rows so the value is a
    clean function of azimuth only, letting a pure-yaw shift be checked exactly
    against 'rotate the map by theta == look at Rz(theta)*d in the unrotated
    map'.
    """
    img = np.zeros((height, width, 3), dtype=np.float32)
    colors = [(5.0, 0.0, 0.0), (0.0, 5.0, 0.0),
              (0.0, 0.0, 5.0), (5.0, 5.0, 0.0)]
    for x in range(width):
        q = int((x / width) * 4) % 4
        img[:, x, :] = colors[q]
    return img


def _uniform_hdri(width=32, height=16, value=1.0):
    return np.full((height, width, 3), value, dtype=np.float32)


@pytest.fixture(scope="module")
def sky_ground_path(tmp_path_factory):
    p = tmp_path_factory.mktemp("env786_skyground") / "sky_ground.hdr"
    _write_radiance_hdr(str(p), _sky_ground_hdri())
    return str(p)


@pytest.fixture(scope="module")
def quadrant_path(tmp_path_factory):
    p = tmp_path_factory.mktemp("env786_quad") / "quad.hdr"
    _write_radiance_hdr(str(p), _azimuth_quadrant_hdri())
    return str(p)


@pytest.fixture(scope="module")
def uniform_path(tmp_path_factory):
    p = tmp_path_factory.mktemp("env787_uniform") / "uniform.hdr"
    _write_radiance_hdr(str(p), _uniform_hdri())
    return str(p)


# ---------------------------------------------------------------------------
# #786 — pure-yaw invariance of the pole
# ---------------------------------------------------------------------------

def test_zyaw_keeps_pole_bright(sky_ground_path):
    """A world Mapping (0,0,theta) is a pure yaw about Blender Z: the
    straight-up (+Z) lookup must return the SAME sky radiance for every theta
    (the pole is on the yaw axis). On main the (0,0,90 deg) yaw is applied as a
    roll, so the pole tips toward the dark horizon/ground -> RED."""
    up = [0.0, 0.0, 1.0]

    def pole_at(theta):
        r = astroray.Renderer()
        assert r.load_environment_map(sky_ground_path, 1.0,
                                      0.0, 0.0, theta,
                                      1.0, 1.0, 1.0, True)  # blender_convention
        return _env_brightness(r, up)

    b0 = pole_at(0.0)
    b90 = pole_at(math.pi / 2.0)
    b115 = pole_at(math.radians(115.0))
    # Sanity: there IS vertical structure (the +Z pole is the bright sky band;
    # the summed-strata brightness of the value-8 sky is ~0.79, the value-0.02
    # ground ~0.002).
    assert b0 > 0.1, f"sky pole not bright at theta=0 ({b0:.4f})"
    # Pure yaw: pole radiance invariant to theta. The scene's 115 deg yaw is the
    # robust catch — on main the roll tips the +Z pole into the dark ground
    # band (0.79 -> 0.002). (At exactly 90 deg the rolled pole lands on the
    # sky/ground horizon boundary and coincidentally still reads sky, so 90 deg
    # alone does not distinguish the bug.)
    assert abs(b90 - b0) / b0 < 0.05, \
        f"pole radiance changed under 90 deg yaw: {b0:.4f} -> {b90:.4f} (roll bug)"
    assert abs(b115 - b0) / b0 < 0.05, \
        f"pole radiance changed under 115 deg yaw: {b0:.4f} -> {b115:.4f} (roll bug)"


def test_zyaw_equals_direction_rotation(quadrant_path):
    """Cycles Mapping semantics: looking in direction d through a map yawed by
    theta equals looking in Rz(theta)*d through the un-yawed map (the Mapping
    node applies out = Rz(theta)*vec before the equirect lookup).

    Encodes the (0,0,90 deg) 'quadrant seen straight ahead' gate from #786:
    a Blender camera looking +Y with a (0,0,90 deg) world yaw sees the env at
    Rz(90 deg)*(0,1,0) = (-1,0,0). On main the yaw is composed on the wrong side
    of the basis change so the two disagree -> RED."""
    r0 = astroray.Renderer()
    assert r0.load_environment_map(quadrant_path, 1.0,
                                   0.0, 0.0, 0.0, 1.0, 1.0, 1.0, True)

    # Probe directions away from wedge seams and the poles.
    probes = [
        [0.0, 1.0, 0.0],    # +Y (Blender camera forward in the #786 gate)
        [1.0, 0.0, 0.0],
        [0.0, -1.0, 0.0],
        [0.70710678, 0.70710678, 0.0],
    ]
    for theta in (math.pi / 2.0, math.radians(115.0)):
        r_yaw = astroray.Renderer()
        assert r_yaw.load_environment_map(quadrant_path, 1.0,
                                          0.0, 0.0, theta, 1.0, 1.0, 1.0, True)
        Rz = _rz(theta)
        for d in probes:
            d_rot = (Rz @ np.array(d, dtype=np.float64)).tolist()
            s_yaw = np.array(r_yaw.eval_env_spectral(d, 0.25))
            s_ref = np.array(r0.eval_env_spectral(d_rot, 0.25))
            np.testing.assert_allclose(
                s_yaw, s_ref, rtol=0.02, atol=1e-3,
                err_msg=f"yaw {math.degrees(theta):.0f} deg dir {d}: "
                        f"rotated-map lookup != direction-rotated lookup")


# ---------------------------------------------------------------------------
# #787 — diffuse env illumination
# ---------------------------------------------------------------------------

def _floor_mean(hdri_path, theta, nee, spp=256):
    r = astroray.Renderer()
    r.set_use_gpu(False)
    r.set_integrator("path_tracer")
    r.set_seed(1234)
    r.set_adaptive_sampling(False)
    r.set_env_nee(nee)
    floor = r.create_material("lambertian", [0.8, 0.8, 0.8], {})
    s = 40.0
    # Floor in the Z=0 plane (Blender-style Z-up world, matching the addon path).
    r.add_triangle([-s, -s, 0], [s, -s, 0], [s, s, 0], floor)
    r.add_triangle([-s, -s, 0], [s, s, 0], [-s, s, 0], floor)
    assert r.load_environment_map(hdri_path, 1.0,
                                  0.0, 0.0, theta, 1.0, 1.0, 1.0, True)
    # Look straight down the +Z floor from above; vup +Y so only floor is framed.
    r.setup_camera(look_from=[0, 0, 14], look_at=[0, 0, 0], vup=[0, 1, 0],
                   vfov=40, aspect_ratio=1.0, aperture=0.0, focus_dist=14.0,
                   width=24, height=24)
    img = np.asarray(r.render(spp, 3, None, False), dtype=np.float64)
    return float(img.reshape(-1, 3).mean())


@pytest.mark.parametrize("nee", [True, False])
def test_white_furnace_diffuse(uniform_path, nee):
    """Diffuse albedo-0.8 floor under a uniform white world (strength 1) must
    render ~=0.8 outgoing radiance (furnace), NEE on and off. Rotation is
    irrelevant for a uniform env — this isolates the energy path from the roll
    so we can tell whether #787 is purely the rotation or a separate defect."""
    mean = _floor_mean(uniform_path, 0.0, nee)
    assert abs(mean - 0.8) / 0.8 < 0.06, \
        f"white furnace floor mean {mean:.4f} != 0.8 (nee={nee})"


@pytest.mark.parametrize("nee", [True, False])
def test_diffuse_lit_under_rotated_sky(sky_ground_path, nee):
    """The corpus symptom: a diffuse floor under the bright-sky/dark-ground
    HDRI with a (0,0,115 deg) world yaw. A pure yaw leaves the sky overhead, so
    the up-facing floor stays lit — the mean must match the un-yawed render
    within noise. On main the roll rotates the sky to the horizon and the floor
    samples the dark ground band -> near-black -> RED."""
    m0 = _floor_mean(sky_ground_path, 0.0, nee)
    m115 = _floor_mean(sky_ground_path, math.radians(115.0), nee)
    assert m0 > 0.3, f"floor not lit even un-yawed (mean {m0:.4f}, nee={nee})"
    assert abs(m115 - m0) / m0 < 0.15, \
        f"floor brightness collapsed under 115 deg yaw: {m0:.4f} -> {m115:.4f} " \
        f"(nee={nee}) — roll rotates the sky out of the up-hemisphere"
