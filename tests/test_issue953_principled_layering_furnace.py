"""#953 -- Principled (specular 0.5) white furnace vs Cycles across roughness.

Cycles' layering albedo for the Principled specular layer is bsdf_albedo() =
sc->weight * bsdf_microfacet_estimate_albedo(), and sc->weight already carries the
microfacet_ggx_preserve_energy darkening E * (1 + Fms * missing). Astroray's port
(pkg261) dropped that factor, so the diffuse beneath was attenuated by the full
mix(f0, 1, s) while the specular lobe only reflects ~E times that: the furnace read
0.973 at roughness 1 (Cycles 1.000), 0.782 vs 0.803 for base 0.8.

Scene: unit sphere in a uniform white world, pinhole camera at z=5, vfov 45, linear
output, mean over pixels well inside the silhouette. Cycles 5.2 references: same
scene (256x128 smooth UV sphere, 512 spp, box filter), measured 2026-09-29.
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
# (base, roughness) -> Cycles 5.2 furnace mean (achromatic).
_CYCLES = {
    (1.0, 0.0): 0.9999, (1.0, 0.25): 0.9999, (1.0, 0.5): 0.9998, (1.0, 0.75): 0.9998,
    (1.0, 1.0): 1.0001,
    (0.8, 0.0): 0.8082, (0.8, 0.25): 0.8082, (0.8, 0.5): 0.8076, (0.8, 0.75): 0.8055,
    (0.8, 1.0): 0.8031,
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


def _furnace(use_gpu, base, roughness, spp=128):
    r = astroray.Renderer()
    r.setup_camera(look_from=[0, 0, 5], look_at=[0, 0, 0], vup=[0, 1, 0], vfov=_FOV,
                   aspect_ratio=1.0, aperture=0.0, focus_dist=5.0, width=_W, height=_H)
    r.set_background_color([1.0, 1.0, 1.0])
    r.set_integrator("path_tracer")
    r.set_use_gpu(use_gpu)
    mid = r.create_material("principled", [base] * 3,
                            {"roughness": roughness, "metallic": 0.0, "ior": 1.5})
    r.add_sphere([0, 0, 0], 1.0, mid)
    px = np.array(r.render(spp, 8, None, False), dtype=np.float64).reshape(_H, _W, -1)[..., :3]
    assert np.isfinite(px).all()
    return px[_mask()].mean(axis=0)


@pytest.mark.parametrize("use_gpu", [
    pytest.param(False, id="cpu"),
    pytest.param(True, id="gpu", marks=pytest.mark.skipif(
        not (AVAILABLE and astroray.__features__.get("cuda", False)),
        reason="CUDA feature not in this build")),
])
@pytest.mark.parametrize("base", [1.0, 0.8])
def test_principled_furnace_matches_cycles(use_gpu, base):
    worst = []
    for rough in (0.0, 0.25, 0.5, 0.75, 1.0):
        m = _furnace(use_gpu, base, rough)
        ref = _CYCLES[(base, rough)]
        rel = m / ref - 1.0
        print(f"[#953 {'gpu' if use_gpu else 'cpu'}] base={base} r={rough} mean={m} cycles={ref} rel={rel}")
        worst.append((float(np.max(np.abs(rel))), rough, m))
    bad = [w for w in worst if w[0] > 0.01]
    assert not bad, f"furnace deviates >1% from Cycles at (|rel|, roughness, rgb): {bad}"
