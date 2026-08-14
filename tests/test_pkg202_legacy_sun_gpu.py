#!/usr/bin/env python
"""pkg202 — legacy `add_sun_light` renders on GPU (upload-time conversion to the
pkg89 dedicated distant light).

BUG (pre-pkg202): the legacy `add_sun_light` / `.blend`-importer sun is a hittable
`DistantLight`. On GPU it maps to GPRIM_SKIP and its unified-CDF `GLight` slot
returns an empty NEE sample, so it contributes EXACTLY zero (imported `.blend`
files lost all sun light on GPU). CPU was always non-zero.

FIX: at scene upload (src/gpu/scene_upload.cu) the legacy sun is converted to a
dedicated distant `GDedicatedLight` (the verified pkg89 path) and its dead
hittable CDF slot is removed, so it appears in the CDF exactly once, carrying the
SAME per-light power the CPU unified CDF uses (luminance(emittedRadiance)).

UNITS (lossless — see PR derivation): the legacy sun delivers irradiance
  S = RGBIlluminant(emittedRadiance())
because the CPU sampler multiplies emission by directionFalloff (1/Ω for a finite
disk, 1 for a delta sun) then divides by the solid-angle pdf (1/Ω, or 1) — the 1/Ω
factors cancel. The dedicated distant delivers RGBIlluminant(emissionRGB)·staticScale
with the device gpu_rgbSpectrumAt == CPU RGBIlluminant (linear in magnitude), so
emissionRGB = S, staticScale = 1 reproduces S exactly. For a `('light', [1,1,1],
intensity=S)` sun over an albedo-ρ Lambertian floor, reflected radiance = ρ·S/π.

DELTA-SUN NOTE (measured on RTX 5070 Ti): for a finite angular diameter the GPU
converted sun matches the CPU legacy render to <0.1% (ratio 1.000). For a TRUE
DELTA sun (angular_diameter == 0, the .blend importer's value) the GPU converted
sun is analytically correct (ρ·S/π) and matches the CPU *dedicated* delta sun,
but the CPU *legacy hittable* delta sun reads ~10% LOW (0.576 vs 0.637): the
hittable path never received the pkg140 `isDelta` MIS-weight-1 treatment that both
the GPU conversion and the CPU dedicated distant apply. That CPU-legacy-delta MIS
deficit is a pre-existing CPU quirk, out of pkg202 scope (CPU is byte-identical).
So the delta gate asserts GPU==analytic and GPU==CPU-dedicated, not GPU==CPU-legacy.

GATES (memory-compliant): per-channel MEAN-RATIO never SSIM; NONZERO pinned seed;
linear output (apply_gamma=False) with an upper AND lower analytic bracket.

GPU-gated: skips when CUDA is absent (CI has no GPU); /verify runs on the RTX box.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from runtime_setup import configure_test_imports

configure_test_imports()

try:
    import astroray
    AVAILABLE = True
except ImportError:
    AVAILABLE = False

pytestmark = pytest.mark.skipif(not AVAILABLE, reason="astroray not built")

if AVAILABLE and not astroray.__features__.get("cuda", False):
    pytest.skip("CUDA feature not in this build — pkg202 needs CUDA; "
                "/verify runs this on the RTX box.", allow_module_level=True)

WIDTH = HEIGHT = 96
SPP = 256
MAX_DEPTH = 3
SEED = 7             # nonzero (memory seed-zero-is-random-sentinel)
ALBEDO = 0.5
SUN_INTENSITY = 4.0  # emittedRadiance = (4,4,4); analytic ρ·S/π = 0.6366
BLENDER_SUN_ANGLE = 0.009  # ~0.5° — Blender's default sun angular diameter
ANALYTIC = ALBEDO * SUN_INTENSITY / math.pi  # 0.6366


def _gpu_available() -> bool:
    return astroray.Renderer().gpu_available


def _floor_scene():
    r = astroray.Renderer()
    r.set_background_color([0.0, 0.0, 0.0])
    r.setup_camera(look_from=[0, 20, 0.0001], look_at=[0, 0, 0], vup=[0, 0, -1],
                   vfov=20.0, aspect_ratio=1.0, aperture=0.0, focus_dist=20.0,
                   width=WIDTH, height=HEIGHT)
    m = r.create_material('lambertian', [ALBEDO, ALBEDO, ALBEDO], {})
    r.add_triangle([-50, 0, -50], [50, 0, -50], [50, 0, 50], m)
    r.add_triangle([-50, 0, -50], [50, 0, 50], [-50, 0, 50], m)
    return r


def _legacy_sun_scene(angle):
    r = _floor_scene()
    # Mirrors the .blend-importer call (tools/blend_import/scene_builder.py:907-915):
    # a "light" material carrying the lamp energy, added via the legacy hittable
    # add_sun_light with a straight-down sun.
    mat = r.create_material('light', [1, 1, 1], {'intensity': SUN_INTENSITY})
    r.add_sun_light([0, -1, 0], angle, mat, 0, 0)
    return r


def _dedicated_sun_scene(angle):
    r = _floor_scene()
    # Equivalent dedicated sun: emission color [1,1,1] * intensity S reproduces the
    # legacy emittedRadiance = (S,S,S) via the same RGBIlluminant upsample.
    r.add_sun_light_dedicated([0, -1, 0], angle,
                              {'mode': 'rgb', 'color': [1, 1, 1]}, SUN_INTENSITY)
    return r


def _render(r, use_gpu, spp=SPP):
    r.set_integrator("path_tracer")
    r.set_use_gpu(use_gpu)
    r.set_seed(SEED)
    return np.asarray(r.render(spp, MAX_DEPTH, None, False))  # linear


def _center_mean(px):
    h, w = px.shape[0], px.shape[1]
    cy, cx = h // 2, w // 2
    return float(np.mean(px[cy - 8:cy + 8, cx - 8:cx + 8, :3]))


# ---------------------------------------------------------------------------
# (1) Finite-angle legacy sun: exact GPU/CPU parity + analytic bracket.
#     This is the headline gate — where the CPU reference is itself correct,
#     the GPU conversion reproduces it to <0.1%.
# ---------------------------------------------------------------------------

def test_legacy_sun_finite_gpu_cpu_parity():
    if not _gpu_available():
        pytest.skip("no GPU on this machine")
    gpu = _render(_legacy_sun_scene(BLENDER_SUN_ANGLE), True)
    cpu = _render(_legacy_sun_scene(BLENDER_SUN_ANGLE), False)
    assert np.all(np.isfinite(gpu)), "GPU pixels not finite"

    gpu_m = _center_mean(gpu)
    cpu_m = _center_mean(cpu)

    # (a) black -> lit: pre-pkg202 the legacy sun was EXACTLY zero on GPU.
    assert gpu_m > 0.05, f"legacy sun still dark on GPU (mean={gpu_m:.5f})"
    # (b) GPU/CPU per-channel mean-ratio ~ 1 (same pdfs + emission).
    ratio = gpu_m / max(cpu_m, 1e-9)
    assert 0.95 <= ratio <= 1.05, \
        f"GPU/CPU mean-ratio {ratio:.3f} outside [0.95,1.05] (gpu={gpu_m:.4f} cpu={cpu_m:.4f})"
    # (c) analytic furnace bracket (upper AND lower): reflected radiance ρ·S/π.
    lo, hi = ANALYTIC * 0.90, ANALYTIC * 1.10
    assert lo < gpu_m < hi, f"GPU mean {gpu_m:.4f} outside analytic bracket [{lo:.4f},{hi:.4f}]"
    assert lo < cpu_m < hi, f"CPU mean {cpu_m:.4f} outside analytic bracket [{lo:.4f},{hi:.4f}]"
    print(f"[legacy-sun finite PASS] gpu={gpu_m:.4f} cpu={cpu_m:.4f} ratio={ratio:.3f} "
          f"analytic={ANALYTIC:.4f}")


# ---------------------------------------------------------------------------
# (2) DELTA legacy sun (angular_diameter == 0 — the .blend importer's value):
#     GPU is analytically correct and matches the CPU *dedicated* delta sun.
#     (The CPU *legacy* delta sun reads ~10% low from a pre-existing MIS-weight
#     deficit; see the module docstring — that is out of pkg202 scope.)
# ---------------------------------------------------------------------------

def test_legacy_sun_delta_analytic_and_nonblack():
    if not _gpu_available():
        pytest.skip("no GPU on this machine")
    gpu = _center_mean(_render(_legacy_sun_scene(0.0), True))
    cpu_dedicated = _center_mean(_render(_dedicated_sun_scene(0.0), False))

    assert gpu > 0.05, f"delta legacy sun renders black on GPU (mean={gpu:.5f})"
    # analytic furnace bracket (upper AND lower).
    lo, hi = ANALYTIC * 0.90, ANALYTIC * 1.10
    assert lo < gpu < hi, f"GPU delta mean {gpu:.4f} outside analytic bracket [{lo:.4f},{hi:.4f}]"
    # matches the correct reference (CPU dedicated delta sun).
    ratio = gpu / max(cpu_dedicated, 1e-9)
    assert 0.95 <= ratio <= 1.05, \
        f"GPU delta sun != CPU dedicated delta sun: ratio {ratio:.3f} " \
        f"(gpu={gpu:.4f} cpu_dedicated={cpu_dedicated:.4f})"
    print(f"[legacy-sun delta PASS] gpu={gpu:.4f} cpu_dedicated={cpu_dedicated:.4f} "
          f"ratio={ratio:.3f} analytic={ANALYTIC:.4f}")


# ---------------------------------------------------------------------------
# (3) Converted legacy sun == native dedicated sun on GPU (sun-only, so selPdf==1
#     and the two power() conventions do not matter): proves the converted sun
#     uses the identical dedicated device path — a dead GPRIM_SKIP slot would zero
#     this sun-only scene.
# ---------------------------------------------------------------------------

def test_legacy_sun_matches_dedicated_sun_on_gpu():
    if not _gpu_available():
        pytest.skip("no GPU on this machine")
    legacy = _center_mean(_render(_legacy_sun_scene(0.0), True))
    native = _center_mean(_render(_dedicated_sun_scene(0.0), True))
    assert legacy > 0.05 and native > 0.05, f"one sun scene dark (legacy={legacy:.4f} native={native:.4f})"
    ratio = legacy / max(native, 1e-9)
    assert 0.95 <= ratio <= 1.05, \
        f"converted legacy sun != native dedicated sun: ratio {ratio:.3f} " \
        f"(legacy={legacy:.4f} native={native:.4f})"
    print(f"[legacy==dedicated PASS] legacy={legacy:.4f} native={native:.4f} ratio={ratio:.3f}")


# ---------------------------------------------------------------------------
# (4) No dead-CDF-entry / no selection-mass theft. Two balanced legacy suns share
#     the unified CDF. Their combined render must equal the SUM of the individual
#     renders (radiometric linearity) on GPU. A dead GPRIM_SKIP slot would waste
#     one sun's selection mass — the combined image would drop that sun AND
#     under-sample the other — breaking linearity.
# ---------------------------------------------------------------------------

def _two_sun_scene(second):
    r = _floor_scene()
    mat1 = r.create_material('light', [1, 1, 1], {'intensity': SUN_INTENSITY})
    r.add_sun_light([0, -1, 0], BLENDER_SUN_ANGLE, mat1, 0, 0)
    if second:
        mat2 = r.create_material('light', [1, 1, 1], {'intensity': SUN_INTENSITY})
        r.add_sun_light([0.4, -1, 0.0], BLENDER_SUN_ANGLE, mat2, 0, 0)
    return r


def test_no_cdf_theft_gpu_linearity():
    if not _gpu_available():
        pytest.skip("no GPU on this machine")
    spp = 512  # push convergence for the linearity assertion
    one = _center_mean(_render(_two_sun_scene(False), True, spp))
    two_only = _floor_scene()
    m2 = two_only.create_material('light', [1, 1, 1], {'intensity': SUN_INTENSITY})
    two_only.add_sun_light([0.4, -1, 0.0], BLENDER_SUN_ANGLE, m2, 0, 0)
    other = _center_mean(_render(two_only, True, spp))
    both = _center_mean(_render(_two_sun_scene(True), True, spp))
    expected = one + other
    ratio = both / max(expected, 1e-9)
    assert 0.97 <= ratio <= 1.03, \
        f"CDF theft: combined {both:.4f} != sum {expected:.4f} (ratio {ratio:.3f}) — " \
        f"a dead sun slot would break two-light linearity"
    print(f"[no-CDF-theft PASS] sun1={one:.4f} sun2={other:.4f} sum={expected:.4f} "
          f"combined={both:.4f} ratio={ratio:.3f}")


# ---------------------------------------------------------------------------
# (5) Dedicated-sun control unchanged (regression guard on the upload change).
# ---------------------------------------------------------------------------

def test_dedicated_sun_control_unchanged():
    if not _gpu_available():
        pytest.skip("no GPU on this machine")
    gpu = _center_mean(_render(_dedicated_sun_scene(BLENDER_SUN_ANGLE), True))
    cpu = _center_mean(_render(_dedicated_sun_scene(BLENDER_SUN_ANGLE), False))
    assert gpu > 0.05, f"dedicated sun dark on GPU (mean={gpu:.5f})"
    ratio = gpu / max(cpu, 1e-9)
    assert 0.95 <= ratio <= 1.05, \
        f"dedicated-sun control regressed: GPU/CPU ratio {ratio:.3f} (gpu={gpu:.4f} cpu={cpu:.4f})"
    assert ANALYTIC * 0.90 < gpu < ANALYTIC * 1.10, \
        f"dedicated sun GPU mean {gpu:.4f} off analytic {ANALYTIC:.4f}"
    print(f"[dedicated-sun control PASS] gpu={gpu:.4f} cpu={cpu:.4f} ratio={ratio:.3f}")


# ---------------------------------------------------------------------------
# (6) .blend-importer code path: a SUN lamp routed through the importer's exact
#     renderer calls renders non-black on GPU (the real-world regression).
# ---------------------------------------------------------------------------

def test_blend_importer_sun_renders_nonblack_gpu():
    if not _gpu_available():
        pytest.skip("no GPU on this machine")
    # Mirror tools/blend_import/scene_builder.py _emit_lamp LA_SUN branch exactly:
    #   mat_id = create_material("light", rgb, {"intensity": energy})
    #   add_sun_light(fwd, 0.0, mat_id, 0, 0)
    r = _floor_scene()
    rgb = [1.0, 0.95, 0.9]     # a warm-ish lamp color, like a real .blend sun
    energy = 5.0
    mat_id = r.create_material("light", rgb, {"intensity": float(energy)})
    fwd = [0.0, -1.0, 0.0]     # straight-down sun (object -Z forward)
    r.add_sun_light(fwd, 0.0, mat_id, 0, 0)
    gpu = _render(r, True)
    assert np.all(np.isfinite(gpu)), "importer sun GPU pixels not finite"
    m = _center_mean(gpu)
    assert m > 0.05, f"imported .blend SUN lamp renders black on GPU (mean={m:.5f})"
    print(f"[blend-importer sun PASS] gpu_center_mean={m:.4f}")
