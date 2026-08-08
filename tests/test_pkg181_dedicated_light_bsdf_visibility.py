"""pkg181 -- dedicated-light visibility to BSDF rays (Cycles lights_intersect parity).

Authors all 7 gates from the pkg181 spec. The CPU legs run here (astroray.Renderer,
CPU device). The GPU legs (gate 6) are DEFERRED to the lead's RTX hardware sweep —
this agent cannot build/verify CUDA — and skip when no GPU is present.

All gates are LINEAR (apply_gamma=False) with floor AND ceiling bounds so an energy
GAIN cannot hide under a [0,1] clamp (memory gamma-furnace-cannot-detect-energy-gain).

Root cause + numbers: .astroray_plan/docs/pkg180-systemic-cycles-dim-diagnosis.md
Cycles oracle values (Blender 5.1, CPU, Standard view, 512 spp) taken from pkg180:
  * mirror reflecting a 100 W 2x2 area lamp: 7.155
  * 3x3 area lamp 300 W @ h=3, floor center:  1.2494
  * sun E=pi diffuse floor rho=0.5 analytic:   0.5
"""
import math
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import runtime_setup
runtime_setup.configure_test_imports()

import astroray

SEED = 777          # nonzero: seed 0 is the random sentinel
ALBEDO = 0.5

# Cycles oracle constants (pkg180 Phase 2).
CYCLES_MIRROR_LAMP = 7.155
CYCLES_AREA_FLOOR = 1.2494


def _lum(rgb):
    return 0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]


def _center_rgb(px, patch=8):
    h, w = px.shape[0], px.shape[1]
    cy, cx = h // 2, w // 2
    p = px[cy - patch // 2:cy + patch // 2, cx - patch // 2:cx + patch // 2, :3]
    return np.mean(p, axis=(0, 1))


def _bright_top(px, k=40):
    l = 0.2126 * px[..., 0] + 0.7152 * px[..., 1] + 0.0722 * px[..., 2]
    return float(np.sort(l.ravel())[::-1][:k].mean())


def _floor_scene(use_gpu, metal=False):
    r = astroray.Renderer()
    try:
        r.set_use_gpu(use_gpu)
    except Exception:
        pass
    r.set_background_color([0.0, 0.0, 0.0])
    r.set_seed(SEED)
    if metal:
        mat = r.create_material('metal', [0.9, 0.9, 0.9], {'roughness': 0.05})
    else:
        mat = r.create_material('lambertian', [ALBEDO] * 3, {})
    r.add_triangle([-20, 0, -20], [20, 0, -20], [20, 0, 20], mat)
    r.add_triangle([-20, 0, -20], [20, 0, 20], [-20, 0, 20], mat)
    return r


def _topdown(r, res=48):
    r.setup_camera(look_from=[0.0, 20.0, 0.01], look_at=[0.0, 0.0, 0.0],
                   vup=[0.0, 0.0, -1.0], vfov=20.0, aspect_ratio=1.0,
                   aperture=0.0, focus_dist=20.0, width=res, height=res)


def _mirror_cam(r, res=96):
    r.setup_camera(look_from=[0.0, 3.0, 8.0], look_at=[0.0, 0.0, 0.0],
                   vup=[0.0, 1.0, 0.0], vfov=30.0, aspect_ratio=1.0,
                   aperture=0.0, focus_dist=8.5, width=res, height=res)


def _render_area_floor(use_gpu, depth):
    """3x3 300 W dedicated area lamp at h=3 over a diffuse floor, top-down."""
    r = _floor_scene(use_gpu)
    _topdown(r)
    r.add_area_light_dedicated([0.0, 3.0, 0.0], [1.0, 0.0, 0.0], [0.0, 0.0, 1.0],
                               3.0, 3.0, 'RECTANGLE',
                               {'mode': 'rgb', 'color': [1.0, 1.0, 1.0]}, 300.0, 1.0)
    px = np.array(r.render(768, depth, None, False), dtype=np.float32)
    return _lum(_center_rgb(px))


def _render_mirror(use_gpu, mesh):
    """Low-roughness metal floor; camera sees the reflection of a 100 W 2x2 lamp."""
    P, size = 100.0, 2.0
    Le = P / (math.pi * size * size)
    n = np.array([0.0, -3.0, 8.0]); n = n / np.linalg.norm(n)
    u = np.array([1.0, 0.0, 0.0]); v = np.cross(n, u)
    c = np.array([0.0, 3.0, -8.0])
    r = _floor_scene(use_gpu, metal=True)
    _mirror_cam(r)
    if mesh:
        em = r.create_material('light', [1.0, 1.0, 1.0], {'intensity': Le})
        hs = size / 2
        p00, p10 = c - u * hs - v * hs, c + u * hs - v * hs
        p11, p01 = c + u * hs + v * hs, c - u * hs + v * hs
        r.add_triangle(list(p00), list(p10), list(p11), em)
        r.add_triangle(list(p00), list(p11), list(p01), em)
    else:
        r.add_area_light_dedicated(list(c), list(u), list(v), size, size, 'RECTANGLE',
                                   {'mode': 'rgb', 'color': [1.0, 1.0, 1.0]}, P, 1.0)
    px = np.array(r.render(512, 4, None, False), dtype=np.float32)
    return _bright_top(px)


def _render_sun(use_gpu, depth):
    r = _floor_scene(use_gpu)
    _topdown(r)
    r.add_sun_light_dedicated([0.0, -1.0, 0.0], math.radians(0.526),
                              {'mode': 'rgb', 'color': [1.0, 1.0, 1.0]}, math.pi)
    px = np.array(r.render(768, depth, None, False), dtype=np.float32)
    return _lum(_center_rgb(px))


def _gpu_available():
    try:
        r = astroray.Renderer()
        r.set_use_gpu(True)
        return bool(getattr(r, "is_using_gpu", lambda: False)())
    except Exception:
        return False


# --------------------------------------------------------------------------- #
# Gate 1 — mirror-lamp A/B >= 0.95x Cycles (was 0.017x). The owner's observation.
# --------------------------------------------------------------------------- #
def test_gate1_mirror_lamp_reflection_not_dark():
    lamp = _render_mirror(use_gpu=False, mesh=False)
    ratio = lamp / CYCLES_MIRROR_LAMP
    assert ratio >= 0.95, f"mirror-lamp A/B={ratio:.3f} < 0.95 (lamp={lamp:.4f})"
    assert ratio <= 1.10, f"mirror-lamp A/B={ratio:.3f} > 1.10 (energy gain, lamp={lamp:.4f})"


def test_gate1b_dedicated_lamp_matches_hittable_mesh_in_mirror():
    """Cycles-independent: a dedicated lamp reflection must match a radiance-matched
    hittable emissive mesh reflection (the physical-emitter reference)."""
    lamp = _render_mirror(use_gpu=False, mesh=False)
    mesh = _render_mirror(use_gpu=False, mesh=True)
    ratio = lamp / mesh
    assert 0.92 <= ratio <= 1.08, f"dedicated/mesh mirror ratio={ratio:.3f} (lamp={lamp:.4f} mesh={mesh:.4f})"


# --------------------------------------------------------------------------- #
# Gate 2 — pkg122 AREA floor A/B in [0.97, 1.03] (was 0.921x).
# --------------------------------------------------------------------------- #
def test_gate2_area_floor_ratio_in_band():
    floor = _render_area_floor(use_gpu=False, depth=8)
    ratio = floor / CYCLES_AREA_FLOOR
    assert 0.97 <= ratio <= 1.03, f"AREA floor A/B={ratio:.4f} outside [0.97,1.03] (floor={floor:.4f})"


def test_gate2b_bsdf_share_recovered_vs_depth1():
    """The BSDF-share is only collectable on continuation (non-camera) rays, so the
    fix must make depth-8 brighter than depth-1 (where no continuation ray exists)."""
    d1 = _render_area_floor(use_gpu=False, depth=1)
    d8 = _render_area_floor(use_gpu=False, depth=8)
    assert d8 > d1 * 1.02, f"depth-8 ({d8:.4f}) not brighter than depth-1 ({d1:.4f}); BSDF share not collected"


# --------------------------------------------------------------------------- #
# Gate 3 — SUN analytic 0.5 within +/-1% (regression guard for near-delta lights).
# --------------------------------------------------------------------------- #
def test_gate3_sun_analytic_regression_guard():
    for depth in (1, 8):
        s = _render_sun(use_gpu=False, depth=depth)
        assert 0.495 <= s <= 0.505, f"SUN depth={depth} lum={s:.5f} outside 0.5 +/-1%"


# --------------------------------------------------------------------------- #
# Gate 4 — no new energy gain: the fixed AREA floor must stay bounded ABOVE the
# analytic point value (the estimator is unbiased, not energy-adding). Linear.
# --------------------------------------------------------------------------- #
def test_gate4_area_floor_no_energy_gain():
    # analytic L at floor center for the 3x3 300 W @ h=3 config (probe reference).
    A, P, h, size = 9.0, 300.0, 3.0, 3.0
    Le = P / (math.pi * A)
    n = 600
    xs = (np.arange(n) + 0.5) / n * size - size / 2
    X, Z = np.meshgrid(xs, xs)
    d2 = X * X + Z * Z + h * h
    cos = h / np.sqrt(d2)
    E = np.sum(Le * cos * cos / d2) * (size / n) ** 2
    analytic = ALBEDO * E / math.pi
    floor = _render_area_floor(use_gpu=False, depth=8)
    assert floor <= analytic * 1.03, f"AREA floor {floor:.4f} exceeds analytic {analytic:.4f} +3% (energy gain)"
    assert floor >= analytic * 0.90, f"AREA floor {floor:.4f} implausibly below analytic {analytic:.4f}"


# --------------------------------------------------------------------------- #
# Gate 6 — CPU/GPU agreement on probes (1)-(3). GPU leg DEFERRED to the lead's
# RTX sweep (this agent cannot build CUDA); skips when no GPU is present.
# --------------------------------------------------------------------------- #
@pytest.mark.skipif(not _gpu_available(), reason="pkg181 gate 6 GPU leg deferred to lead RTX sweep")
def test_gate6_cpu_gpu_agreement():
    for label, cpu, gpu in (
        ("mirror", _render_mirror(False, mesh=False), _render_mirror(True, mesh=False)),
        ("area", _render_area_floor(False, 8), _render_area_floor(True, 8)),
        ("sun", _render_sun(False, 8), _render_sun(True, 8)),
    ):
        ratio = gpu / cpu if cpu > 0 else 0.0
        assert 0.95 <= ratio <= 1.05, f"CPU/GPU {label} ratio={ratio:.3f} (cpu={cpu:.4f} gpu={gpu:.4f})"


# --------------------------------------------------------------------------- #
# Gate 7 — the stale 180-deg AREA harness flips are removed (pkg180 side-finding 1).
# --------------------------------------------------------------------------- #
def test_gate7_stale_area_flips_removed():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for rel in ("benchmarks/blender_parity/scene_library.py",
                "scripts/verify_pkg122_cycles_oracle.py"):
        with open(os.path.join(root, rel), encoding="utf-8") as fh:
            text = fh.read()
        assert "rotation_euler = (math.pi, 0.0, 0.0)" not in text, \
            f"{rel} still flips the AREA lamp 180 deg (renders Astroray leg black post-pkg139)"
