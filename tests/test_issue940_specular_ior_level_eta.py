"""#940 — Principled specular_ior_level must re-derive the layer IOR (Cycles parity).

The addon lowers Blender's Diffuse BSDF to Principled with specular_ior_level = 0.
Cycles (svm/closure.h principled "Apply IOR adjustment", Apache-2.0) then sets
f0 = 0 and eta = ior_from_F0(0) = 1, so the dielectric layer reflects nothing and
the floor equals a Lambertian one. Astroray scaled f0 but kept the Fresnel exponent
at ior = 1.5: at grazing view the real-Fresnel rise still reflected the lamp (a
sharp mirror image of a tilted rect lamp, 2.0x Cycles on the floor) and the layer
albedo dimmed the diffuse under a downward lamp (0.82x Cycles).
Oracle: Principled(specular_ior_level=0) == Lambertian, same base colour.
"""
import math

import numpy as np
import pytest

_RES = 48
# Grazing camera over a floor (the pkg294 nv_* scenes, #940).
_CAM = ([0.0, -2.6, 0.75], [0.0, -1.6066, 0.6354], [0.0, 0.1146, 0.9934])


def _render(astroray_module, principled, tilt_deg, use_gpu=False, spp=32):
    r = astroray_module.Renderer()
    if hasattr(r, "set_use_gpu"):
        r.set_use_gpu(use_gpu)
    r.set_adaptive_sampling(False)
    r.set_seed(7)
    r.set_background_color([0.0, 0.0, 0.0])
    r.setup_camera(_CAM[0], _CAM[1], _CAM[2], 39.6, 1.0, 0.0, 10.0, _RES, _RES)
    if principled:
        m = r.create_material('principled', [0.5, 0.5, 0.5],
                              {'metallic': 0.0, 'roughness': 0.0, 'specular_ior_level': 0.0})
    else:
        m = r.create_material('lambertian', [0.5, 0.5, 0.5], {})
    r.add_triangle([-4, -4, 0], [4, -4, 0], [4, 4, 0], m)
    r.add_triangle([-4, -4, 0], [4, 4, 0], [-4, 4, 0], m)
    t = math.radians(tilt_deg)                       # emission normal tilted toward the camera
    n = np.array([0.0, -math.sin(t), -math.cos(t)])
    u = np.array([1.0, 0.0, 0.0])
    v = np.cross(n, u)                               # u x v = n
    pos = [0.0, 1.2, 1.2] if tilt_deg else [0.0, 0.0, 1.5]
    r.add_area_light_dedicated(pos, list(u), list(v), 1.5, 1.125, 'RECTANGLE',
                               {'mode': 'rgb', 'color': [1, 1, 1]}, 900.0, math.pi / 2)
    img = np.asarray(r.render(spp, 4, None, False), dtype=np.float64).reshape(_RES, _RES, 3)
    return img[_RES // 2 + 4:].mean(-1)              # floor rows below the horizon


@pytest.mark.parametrize("use_gpu", [False, pytest.param(True, marks=pytest.mark.gpu)])
@pytest.mark.parametrize("tilt", [0.0, 45.0, 69.4])
def test_specular_level_zero_equals_lambertian(astroray_module, tilt, use_gpu):
    """Pre-fix: tilt 45 -> 1.21, tilt 69.4 -> 2.02, downward (0) -> 0.82."""
    if use_gpu and not getattr(astroray_module, "__features__", {}).get("cuda", False):
        pytest.skip("CUDA build required")
    pr = _render(astroray_module, True, tilt, use_gpu)
    lb = _render(astroray_module, False, tilt, use_gpu)
    ratio = pr.mean() / lb.mean()
    assert abs(ratio - 1.0) < 0.03, f"tilt {tilt}: principled(level 0)/lambertian = {ratio:.3f}"
    # No mirror footprint: the brightest floor rows must not exceed the Lambertian ones.
    peak = np.percentile(pr, 99) / np.percentile(lb, 99)
    assert peak < 1.15, f"tilt {tilt}: 99th-percentile ratio {peak:.3f} (lamp mirror image)"
