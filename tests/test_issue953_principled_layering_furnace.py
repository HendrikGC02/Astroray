"""#953 -- Principled white furnace vs Cycles 5.2 (roughness, IOR, specular level, tints, coat, sheen).

Two Cycles-parity defects in the Principled layering (Cycles svm/closure.h, bsdf.h,
bsdf_util.h, bsdf_microfacet.h; Apache-2.0):
  1. Layering albedo: Cycles' bsdf_albedo() = sc->weight * estimate_albedo(), and the
     specular/coat sc->weight already carries preserve-energy E * (1 + Fms * missing).
     Dropping it over-attenuated the diffuse: 0.973 at roughness 1 (Cycles 1.000).
  2. closure_layering_weight is a SCALAR, saturate(1 - reduce_max(albedo / weight)),
     not the per-channel (1 - albedo): coloured sheen / specular tint diverged (sheen
     tint (0.2, 0.9, 0.3): 0.995 vs Cycles 0.952 in red).

Scene: unit sphere in a uniform white world, pinhole camera at z=5, vertical fov 45,
48x48, linear, mean over pixels well inside the silhouette. Pins: Cycles 5.2 CPU, same
scene (smooth 256x128 UV sphere, 1024 spp, box filter, sensor_fit VERTICAL, angle_y 45),
rendered headless 2026-09-29. Energy gate: white-base cases stay <= 1 + eps per channel
(sphere mean) and per pixel after a 5x5 box (per-pixel values carry ~3% spectral MC
noise at this spp even for a white Lambertian).
"""
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

pytestmark = pytest.mark.skipif(not AVAILABLE, reason="astroray module not available")

_W = _H = 48
_FOV = 45.0
_SPP = 512
# id -> (base, params, Cycles 5.2 RGB mean over the mask)
_CASES = {
    "b1.0_r0.0": (1.0, {'ior': 1.5, 'roughness': 0.0}, [0.99985, 0.99985, 0.99985]),
    "b1.0_r0.25": (1.0, {'ior': 1.5, 'roughness': 0.25}, [0.99989, 0.99989, 0.99989]),
    "b1.0_r0.5": (1.0, {'ior': 1.5, 'roughness': 0.5}, [0.99955, 0.99955, 0.99955]),
    "b1.0_r0.75": (1.0, {'ior': 1.5, 'roughness': 0.75}, [0.99949, 0.99949, 0.99949]),
    "b1.0_r1.0": (1.0, {'ior': 1.5, 'roughness': 1.0}, [1.00015, 1.00015, 1.00015]),
    "b0.8_r0.0": (0.8, {'ior': 1.5, 'roughness': 0.0}, [0.81069, 0.81069, 0.81069]),
    "b0.8_r0.25": (0.8, {'ior': 1.5, 'roughness': 0.25}, [0.81074, 0.81074, 0.81074]),
    "b0.8_r0.5": (0.8, {'ior': 1.5, 'roughness': 0.5}, [0.8091, 0.8091, 0.8091]),
    "b0.8_r0.75": (0.8, {'ior': 1.5, 'roughness': 0.75}, [0.80603, 0.80603, 0.80603]),
    "b0.8_r1.0": (0.8, {'ior': 1.5, 'roughness': 1.0}, [0.80375, 0.80375, 0.80375]),
    "ior1.0_r0.5": (1.0, {'ior': 1.0, 'roughness': 0.5}, [0.99999, 0.99999, 0.99999]),
    "ior1.5_lvl0": (1.0, {'ior': 1.5, 'roughness': 0.5, 'specular_ior_level': 0.0}, [0.99999, 0.99999, 0.99999]),
    "ior1.5_lvl1": (1.0, {'ior': 1.5, 'roughness': 0.5, 'specular_ior_level': 1.0}, [0.99948, 0.99948, 0.99948]),
    "ior3.0_r0.3": (1.0, {'ior': 3.0, 'roughness': 0.3}, [1.00029, 1.00029, 1.00029]),
    "ior3.0_r1.0": (1.0, {'ior': 3.0, 'roughness': 1.0}, [1.00008, 1.00008, 1.00008]),
    "spec_tint": (1.0, {'ior': 1.5, 'roughness': 0.5, 'specular_tint': [1.0, 0.2, 0.2]}, [0.99957, 0.97111, 0.97111]),
    "coat_tint": (1.0, {'ior': 1.5, 'roughness': 0.5, 'coat_weight': 1.0, 'coat_tint': [0.9, 0.5, 0.2], 'coat_roughness': 0.2, 'coat_ior': 1.5}, [0.89514, 0.49267, 0.2136]),
    "coat_half": (1.0, {'ior': 1.5, 'roughness': 0.5, 'coat_weight': 0.5, 'coat_roughness': 0.5, 'coat_ior': 1.5}, [0.99923, 0.99923, 0.99923]),
    "sheen_tint": (1.0, {'ior': 1.5, 'roughness': 0.5, 'sheen_weight': 1.0, 'sheen_tint': [0.2, 0.9, 0.3], 'sheen_roughness': 0.5}, [0.95207, 0.99953, 0.95885]),
    "combo": (1.0, {'ior': 2.0, 'roughness': 0.4, 'specular_ior_level': 0.8, 'specular_tint': [0.3, 0.6, 1.0], 'coat_weight': 0.7, 'coat_tint': [1.0, 0.8, 0.6], 'coat_roughness': 0.1, 'coat_ior': 1.6, 'sheen_weight': 0.8, 'sheen_tint': [1.0, 0.3, 0.6], 'sheen_roughness': 0.3}, [0.88768, 0.79807, 0.7141]),
}


def _mask(margin=0.9):
    t = math.tan(math.radians(_FOV / 2))
    j, i = np.meshgrid(np.arange(_W), np.arange(_H))
    x = ((j + 0.5) / _W * 2 - 1) * t
    y = ((i + 0.5) / _H * 2 - 1) * t
    d = np.stack([x, y, -np.ones_like(x)], -1)
    d /= np.linalg.norm(d, axis=-1, keepdims=True)
    b = 5.0 * d[..., 2]  # o . d with o = (0, 0, 5)
    return np.sqrt(np.maximum(25.0 - b * b, 0.0)) < margin


def _render(use_gpu, base, params):
    r = astroray.Renderer()
    r.setup_camera(look_from=[0, 0, 5], look_at=[0, 0, 0], vup=[0, 1, 0], vfov=_FOV,
                   aspect_ratio=1.0, aperture=0.0, focus_dist=5.0, width=_W, height=_H)
    r.set_background_color([1.0, 1.0, 1.0])
    r.set_integrator("path_tracer")
    r.set_use_gpu(use_gpu)
    # Pinned: seed 0 is the random sentinel; the sphere mean has ~0.0017/channel MC sigma at
    # 512 spp, so the 1.005 energy gate was a ~3-sigma coin flip across ~48 unseeded runs.
    r.set_seed(278)
    mid = r.create_material("principled", [base] * 3, dict(params, metallic=0.0))
    r.add_sphere([0, 0, 0], 1.0, mid)
    px = np.array(r.render(_SPP, 8, None, False), dtype=np.float64).reshape(_H, _W, -1)[..., :3]
    assert np.isfinite(px).all()
    return px


def _box5(img):
    p = np.pad(img, ((2, 2), (2, 2), (0, 0)), mode="edge")
    return sum(p[dy:dy + _H, dx:dx + _W] for dy in range(5) for dx in range(5)) / 25.0


_BACKENDS = [
    pytest.param(False, id="cpu"),
    pytest.param(True, id="gpu", marks=pytest.mark.skipif(
        not (AVAILABLE and astroray.__features__.get("cuda", False)),
        reason="CUDA feature not in this build")),
]


@pytest.mark.parametrize("use_gpu", _BACKENDS)
@pytest.mark.parametrize("case", list(_CASES))
def test_principled_furnace_matches_cycles(use_gpu, case):
    base, params, ref = _CASES[case]
    px = _render(use_gpu, base, params)
    mask = _mask()
    m = px[mask].mean(axis=0)
    ref = np.array(ref)
    rel = m / ref - 1.0
    print(f"[#953 {'gpu' if use_gpu else 'cpu'}] {case} mean={m} cycles={ref} rel={rel}")
    assert np.all(np.abs(rel) <= 0.01), f"{case}: furnace {m} vs Cycles {ref} (rel {rel}) exceeds 1%"
    if base == 1.0:
        assert np.all(m <= 1.005), f"{case}: sphere-mean energy gain {m}"
        pmax = float(_box5(px)[mask].max())
        assert pmax <= 1.04, f"{case}: 5x5-box per-pixel max {pmax:.4f} > 1.04 (energy gain)"
