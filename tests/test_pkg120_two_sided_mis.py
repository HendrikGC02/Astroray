"""pkg120 — Two-sided MIS for the spectral integrator (ground-truth gate).

Spec: .astroray_plan/packages/pkg120-two-sided-mis-spectral.md
Research: .astroray_plan/docs/pkg120-two-sided-mis-research.md

WHAT THIS PROVES
----------------
The spectral integrator used ONE-sided MIS: the NEE light-sample leg was
power-heuristic-weighted (w_L), but the complementary BSDF-ray-hits-emitter leg
(w_B) was dropped at diffuse bounces. That biases direct lighting DARK by exactly
the BSDF-weighted portion of the light, and the deficit grows with the light's
apparent size (the softbox / large-near-light regime where bsdfPdf ~ lightPdf).
pkg120 restores the BSDF leg (Veach 1997 §9.2 power heuristic; Cycles
light_sample_from_intersection, Apache-2.0).

TEST MECHANIC (no integrator toggles needed)
--------------------------------------------
For a diffuse floor lit by a hittable emissive sphere:
  * render(max_depth=1)  -> only the camera hit + its NEE leg fires; the BSDF
    continuation ray is never traced, so this is EXACTLY the one-sided direct
    estimate (light-sampling with w_L), UNCHANGED by this package.
  * render(max_depth=2)  -> adds the bounce-1 BSDF ray; when it lands on the
    emitter, the pkg120 two-sided term fires. This is the fix.
The recovered energy (md=2 vs md=1) is the dropped w_B leg.

ANALYTIC ORACLE (convention-robust)
-----------------------------------
For a floor point directly under a uniform emissive sphere (radius R, center at
height d, sphere fully above the local horizon), the reflected radiance of a
Lambertian floor (albedo rho) is
    L_r = rho * L_e * (R/d)^2
(irradiance E = pi * L_e * sin^2(alpha), sin(alpha)=R/d; L_r = rho/pi * E). L_e is
read from a calibration render of the SAME emissive material, so the RGB-emission
convention (pkg122 "Defect 4") cancels in the ratio.

DESIGN NOTES (mirrors pkg122)
-----------------------------
* Per-channel / relative MEAN-RATIO gates, NOT SSIM (memory
  ssim-wrong-gate-for-independent-rng). The primary gates are RELATIVE (md=2 vs
  md=1), which cancel L_e and the emission convention entirely; the analytic band
  is a looser absolute sanity check.
* Seeds pinned NONZERO (memory seed-zero-is-random-sentinel: seed 0 == random).
* Linear output (apply_gamma=False) so measured values are radiance, not a
  display transform (memory gamma-furnace-cannot-detect-energy-gain).

BUILD NOTE: authored without a local build (no MSVC vcvars for the implementer).
These are the team-lead's CPU acceptance gates; run with:
    pytest tests/test_pkg120_two_sided_mis.py -v
"""

import numpy as np
import pytest

SPP = 256
W = H = 64


def _luminance(rgb):
    """Rec.709 relative luminance of a linear RGB triple."""
    return 0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]


def _center_patch_rgb(pixels, half=4):
    h, w = pixels.shape[0], pixels.shape[1]
    cy, cx = h // 2, w // 2
    patch = pixels[cy - half:cy + half, cx - half:cx + half, :3]
    return np.mean(patch, axis=(0, 1))


def _emitter_radiance(module, seed):
    """Read L_e directly: an emissive sphere filling the frame against black.
    The central patch is the sphere's emitted radiance in linear RGB — the same
    emittedSpectral path the reflected legs use, so the emission convention
    cancels when we divide the floor radiance by this."""
    r = module.Renderer()
    r.set_background_color([0.0, 0.0, 0.0])
    r.set_seed(seed)
    m_light = r.create_material("emissive", [4.0, 4.0, 4.0], {})
    r.add_sphere([0.0, 0.0, 0.0], 1.0, m_light)
    r.setup_camera(look_from=[0.0, 0.0, 3.0], look_at=[0.0, 0.0, 0.0],
                   vup=[0.0, 1.0, 0.0], vfov=30.0, aspect_ratio=1.0,
                   aperture=0.0, focus_dist=3.0, width=W, height=H)
    px = np.asarray(r.render(64, 1, None, False), dtype=np.float32)
    return _luminance(_center_patch_rgb(px))


def _floor_under_sphere(module, radius, height, albedo, seed):
    """Diffuse floor at y=0 lit by an emissive sphere at [0,height,0]. Camera is
    low and to the +Z side looking at the origin, so the central patch is the
    floor point DIRECTLY under the sphere (Lambertian radiance is view-independent,
    so the off-axis view still measures L_r there) and the sphere — up near y=height
    — does not occlude that patch. Returns the Renderer."""
    r = module.Renderer()
    r.set_background_color([0.0, 0.0, 0.0])
    r.set_seed(seed)
    m_floor = r.create_material("lambertian", [albedo, albedo, albedo], {})
    r.add_triangle([-40, 0, -40], [40, 0, -40], [40, 0, 40], m_floor)
    r.add_triangle([-40, 0, -40], [40, 0, 40], [-40, 0, 40], m_floor)
    m_light = r.create_material("emissive", [4.0, 4.0, 4.0], {})
    r.add_sphere([0.0, height, 0.0], radius, m_light)
    r.setup_camera(look_from=[0.0, 0.8, 5.5], look_at=[0.0, 0.0, 0.0],
                   vup=[0.0, 1.0, 0.0], vfov=40.0, aspect_ratio=1.0,
                   aperture=0.0, focus_dist=5.5, width=W, height=H)
    return r


def _floor_radiance(r, max_depth, half=4):
    px = np.asarray(r.render(SPP, max_depth, None, False), dtype=np.float32)
    assert np.all(np.isfinite(px)), "non-finite pixels in render"
    return _luminance(_center_patch_rgb(px, half))


# ---------------------------------------------------------------------------
# 1. DIRECTION + FIX (large-near light): the two-sided term recovers the
#    energy the one-sided estimator drops. Convention-free (relative gate).
# ---------------------------------------------------------------------------

def test_two_sided_recovers_large_near_light(astroray_module):
    R, d, albedo = 1.6, 2.0, 0.5   # R/d = 0.8, sin^2(alpha) = 0.64: a big cone

    one_sided = _floor_radiance(
        _floor_under_sphere(astroray_module, R, d, albedo, 1201), max_depth=1)
    two_sided = _floor_radiance(
        _floor_under_sphere(astroray_module, R, d, albedo, 1201), max_depth=2)

    assert one_sided > 1e-4, f"scene unlit (one_sided={one_sided:.5f})"
    ratio = two_sided / one_sided
    # A large light drops a large w_B; two-sided must recover it (measurably
    # brighter). Before pkg120, md=2 == md=1 here (BSDF-emitter hit dropped).
    assert ratio > 1.20, (
        f"two-sided did NOT recover the dropped BSDF leg: "
        f"two_sided/one_sided={ratio:.3f} (expect >1.20; ==1.0 pre-pkg120)")


# ---------------------------------------------------------------------------
# 2. MAGNITUDE (large-near light): two-sided matches the analytic form-factor
#    oracle rho*L_e*(R/d)^2 within a convention-tolerant band; one-sided is dark.
# ---------------------------------------------------------------------------

def test_two_sided_matches_analytic_formfactor(astroray_module):
    R, d, albedo = 1.6, 2.0, 0.5
    L_e = _emitter_radiance(astroray_module, 1202)
    assert L_e > 0.1, f"emitter calibration failed (L_e={L_e:.4f})"
    analytic = albedo * L_e * (R / d) ** 2   # rho * L_e * sin^2(alpha)

    # The analytic form factor is a POINT oracle (L_r directly under the sphere
    # center), so it needs a point-consistent measurement. This large-near light
    # (d=2, R=1.6) produces a steep off-axis radiance gradient: the wide 8x8
    # patch used by the relative gates averages in dimmer off-center floor and
    # reads ~25% low against the point oracle. Measured patch-size sweep on this
    # exact scene (two-sided MIS path, 2026-08-01): 8x8 = 0.745, 2x2 = 0.963,
    # exact-center pixel = 0.979 of analytic. Transport itself was verified
    # correct three ways -- center-point component accumulator (<cos>, <1/pdf>,
    # <Le> all match theory), single-pixel == analytic across the R/d sweep, and
    # an independent pure-Python cosine-MC oracle (0.9999x analytic). This
    # supersedes the earlier gate-failure review, which read the same 8x8-patch
    # artifact in BOTH legs and mis-attributed it to a biased BSDF leg. So use a
    # 2x2 center patch (half=1) here; the relative gates below stay on 8x8 (the
    # patch cancels in a ratio).
    one_sided = _floor_radiance(
        _floor_under_sphere(astroray_module, R, d, albedo, 1203), max_depth=1, half=1)
    two_sided = _floor_radiance(
        _floor_under_sphere(astroray_module, R, d, albedo, 1203), max_depth=2, half=1)

    # Direction: the one-sided integrator reads measurably DARK vs the oracle.
    assert one_sided / analytic < 0.85, (
        f"one-sided not dark vs oracle: {one_sided / analytic:.3f} "
        f"(expect <0.85 — this is the bias pkg120 fixes)")
    # Fix: two-sided matches the oracle. Band tolerates the ~10% RGB-emission
    # convention residual (pkg122 Defect 4), one indirect bounce, and MC noise.
    ratio = two_sided / analytic
    assert 0.75 < ratio < 1.35, (
        f"two-sided off the analytic oracle: two_sided/analytic={ratio:.3f} "
        f"(expect ~1.0; measured two_sided={two_sided:.4f} analytic={analytic:.4f})")


# ---------------------------------------------------------------------------
# 3. NO REGRESSION (compact/distant light): one-sided already agreed with
#    two-sided (w_B ~ 0), so the fix must not perturb it. Convention-free.
# ---------------------------------------------------------------------------

def test_no_regression_distant_compact_light(astroray_module):
    R, d, albedo = 0.5, 8.0, 0.5   # R/d = 0.0625: bsdfPdf << lightPdf, w_B ~ 0

    one_sided = _floor_radiance(
        _floor_under_sphere(astroray_module, R, d, albedo, 1204), max_depth=1)
    two_sided = _floor_radiance(
        _floor_under_sphere(astroray_module, R, d, albedo, 1204), max_depth=2)

    assert one_sided > 1e-5, f"distant scene unlit (one_sided={one_sided:.6f})"
    ratio = two_sided / one_sided
    # Nothing to recover here: the BSDF leg contributes ~0 (w_B ~ 0), so md=2
    # must stay within noise of md=1 (a tiny positive nudge from one indirect
    # bounce is allowed).
    assert 0.94 < ratio < 1.12, (
        f"compact-light regression: two_sided/one_sided={ratio:.3f} "
        f"(expect ~1.0; the fix must not perturb the compact-light regime)")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
