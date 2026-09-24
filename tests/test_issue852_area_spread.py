"""#852 — AREA light spread: Blender full-angle lowering + Cycles soft-box attenuation.

Pre-fix the addon passed Blender's FULL spread angle as AreaLight's half-angle and
AreaLight only hard-clipped the cone, so a 45 deg spread rendered ~6x dark vs
Cycles (lighting_studio AREA booth 0.17). Cycles (kernel/light/area.h
area_light_spread_attenuation + scene/light.cpp normalize_spread, Apache-2.0)
scales radiance by f = max(tan h - tan a, 0) / (tan h - h), h = spread/2, which
keeps the lamp's emitted power. Oracles here: (1) flux is independent of spread
when the whole cone lands on the plane; (2) centre irradiance ratio vs a
Lambertian lamp matches quadrature of f over the lamp.
"""
import math
import types

import numpy as np
import pytest

from test_pkg139_area_light_orientation import (IDENTITY, _RecordingRenderer,
                                                 _load_blender_addon,
                                                 _make_area_light_instance)


def test_addon_lowers_full_spread_to_half_angle(monkeypatch):
    addon = _load_blender_addon(monkeypatch)
    engine = addon.CustomRaytracerRenderEngine()
    renderer = _RecordingRenderer()
    inst = _make_area_light_instance(IDENTITY, shape='RECTANGLE')
    inst.object.data.spread = math.radians(45.0)
    engine.convert_lights(types.SimpleNamespace(object_instances=[inst], objects=[]), renderer)
    spread = renderer.area_light_calls[0][8]
    assert abs(spread - math.radians(22.5)) < 1e-6, f"half-angle expected, got {spread}"


# ---- render-level gates -----------------------------------------------------
_H, _SIZE, _RES, _CAM_H, _FOV = 1.0, 0.2, 80, 6.0, 30.0


def _render(astroray_module, half_spread, use_gpu=False, spp=256):
    r = astroray_module.Renderer()
    if hasattr(r, "set_use_gpu"):
        r.set_use_gpu(use_gpu)
    r.set_adaptive_sampling(False)
    r.set_seed(11)
    r.set_background_color([0.0, 0.0, 0.0])
    r.setup_camera([0, 0, _CAM_H], [0, 0, 0], [0, 1, 0], _FOV, 1.0, 0.0, _CAM_H, _RES, _RES)
    m = r.create_material('lambertian', [0.5, 0.5, 0.5], {})
    e = 6.0
    r.add_triangle([-e, -e, 0], [e, -e, 0], [e, e, 0], m)
    r.add_triangle([-e, -e, 0], [e, e, 0], [-e, e, 0], m)
    r.add_area_light_dedicated([0, 0, _H], [1, 0, 0], [0, -1, 0], _SIZE, _SIZE, 'RECTANGLE',
                               {'mode': 'rgb', 'color': [1, 1, 1]}, 10.0, half_spread)
    return np.asarray(r.render(spp, 2, None, False), dtype=np.float64).reshape(_RES, _RES, 3)


def _flux(img):
    """Sum of plane radiance x pixel footprint area (pinhole: area ~ (1+x^2+y^2)^1.5)."""
    t = math.tan(math.radians(_FOV) / 2)
    c = (np.arange(_RES) + 0.5) / _RES * 2 - 1
    x, y = np.meshgrid(c * t, c * t)
    return float((img.mean(-1) * (1 + x * x + y * y) ** 1.5).sum())


def _centre(img):
    k = _RES // 2
    return float(img[k - 2:k + 2, k - 2:k + 2].mean())


def _atten(cos_a, h):
    if h >= math.pi / 2:
        return np.ones_like(cos_a)
    tan_a = np.sqrt(np.maximum(0, 1 - cos_a ** 2)) / cos_a
    return np.maximum((math.tan(h) - tan_a) / (math.tan(h) - h), 0)


def _centre_irradiance(h, n=200):
    """Quadrature of f(a) cos_l cos_r / d^2 over the lamp, averaged over the ROI."""
    pix = 2 * _CAM_H * math.tan(math.radians(_FOV) / 2) / _RES
    offs = (np.arange(4) - 1.5) * pix          # the 4x4 ROI pixel centres
    g = (np.arange(n) + 0.5) / n - 0.5
    lx, ly = np.meshgrid(g * _SIZE, g * _SIZE)
    total = 0.0
    for px in offs:
        for py in offs:
            dx, dy = px - lx, py - ly
            d2 = dx * dx + dy * dy + _H * _H
            cos = _H / np.sqrt(d2)
            total += float((_atten(cos, h) * cos * cos / d2).mean())
    return total


@pytest.fixture(scope="module")
def cpu_renders(astroray_module):
    return {h: _render(astroray_module, h) for h in (math.pi / 2, math.radians(45), math.radians(22.5))}


def test_spread_preserves_flux_cpu(cpu_renders):
    """Pre-fix (hard cone only) 22.5/45 flux ratio = sin^2(22.5)/sin^2(45) = 0.29."""
    ratio = _flux(cpu_renders[math.radians(22.5)]) / _flux(cpu_renders[math.radians(45)])
    assert 0.96 <= ratio <= 1.04, f"flux(22.5)/flux(45) = {ratio:.4f}, expected 1"


@pytest.mark.parametrize("deg", [45.0, 22.5])
def test_spread_centre_boost_matches_quadrature_cpu(cpu_renders, deg):
    """Pre-fix the centre ratio was ~1 (the hard cone does not clip the centre)."""
    h = math.radians(deg)
    got = _centre(cpu_renders[h]) / _centre(cpu_renders[math.pi / 2])
    want = _centre_irradiance(h) / _centre_irradiance(math.pi / 2)
    assert abs(got / want - 1) < 0.05, f"half {deg}: centre ratio {got:.3f}, quadrature {want:.3f}"


@pytest.mark.parametrize("use_gpu", [False, pytest.param(True, marks=pytest.mark.gpu)])
@pytest.mark.parametrize("half", [0.0, 5e-11, 1e-4])
def test_zero_and_tiny_spread_finite(astroray_module, half, use_gpu):
    """Spread -> 0 must not produce Inf*0 = NaN (Cycles: collimated, pi on axis)."""
    if use_gpu and not getattr(astroray_module, "__features__", {}).get("cuda", False):
        pytest.skip("CUDA build required")
    img = _render(astroray_module, half, use_gpu=use_gpu, spp=64)
    assert np.isfinite(img).all(), f"half {half}: non-finite pixels"
    assert (img >= 0).all(), f"half {half}: negative pixels"


@pytest.mark.gpu
@pytest.mark.parametrize("deg", [90.0, 45.0, 22.5])
def test_spread_gpu_matches_cpu(astroray_module, cpu_renders, deg):
    if not getattr(astroray_module, "__features__", {}).get("cuda", False):
        pytest.skip("CUDA build required")
    h = math.radians(deg)
    cpu = cpu_renders[h] if h in cpu_renders else _render(astroray_module, h)
    gpu = _render(astroray_module, h, use_gpu=True)
    for name, fn in (("flux", _flux), ("centre", _centre)):
        ratio = fn(gpu) / fn(cpu)
        assert abs(ratio - 1) < 0.05, f"half {deg}: GPU/CPU {name} = {ratio:.4f}"
